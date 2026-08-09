"""专家（Persona）manifest —— 数据模型 + Markdown 解析校验。

格式与技能 SKILL.md 同构：YAML frontmatter（身份/能力声明）+ Markdown 正文（= 角色系统提示）。
解析严格：非法 manifest 抛 ManifestError（fail loudly，不静默降级）。

单专家与团队共用同一模型：`expert_type: agent|team`；team 型 `members` 只存 id，
运行时由 registry 惰性解析为 `resolved_members`（避免嵌套递归）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from minihermes.core.skills.manager import parse_frontmatter

# id 校验：小写字母/数字开头，后续允许 `-`/`_`，最长 64（目录名/注册键，防路径穿越）
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

VALID_EXPERT_TYPES = {"agent", "team"}
VALID_SOUL_MODES = {"replace", "stack"}


class ManifestError(ValueError):
    """manifest 非法（字段缺失/未知枚举值）→ fail loudly。"""


@dataclass
class PersonaManifest:
    id: str
    name: str
    expert_type: str = "agent"                 # "agent" | "team"
    icon: str = ""
    tagline: str = ""
    description: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    quick_prompts: list[str] = field(default_factory=list)  # 专家面板点击即发
    default_init_prompt: str = ""              # 会话首个 user 消息（面板「应用」后自动注入）
    tools: list[str] = field(default_factory=list)          # 空=全开；非空=硬白名单
    skills: list[str] = field(default_factory=list)
    soul_mode: str = "replace"                 # "replace" | "stack"
    system_prompt: str = ""                    # markdown 正文 = 身份 prompt
    source: str = "builtin"                    # "builtin" | "local"
    path: Optional[str] = None                 # 来源文件路径（provenance）
    # ── team 专用（members 只存 id，不嵌套递归）──
    members: list[str] = field(default_factory=list)
    lead_id: str = ""                          # team 时 == self.id
    max_team_iterations: int = 50              # 团员子代理迭代预算
    # 运行时填充：registry.list()/get() 时把 members id → PersonaManifest
    resolved_members: list["PersonaManifest"] = field(default_factory=list, init=False)

    def is_team(self) -> bool:
        return self.expert_type == "team"


def _strlist(meta: Dict[str, Any], key: str) -> list[str]:
    """frontmatter 列表字段：支持 YAML 列表或逗号分隔字符串。"""
    val = meta.get(key)
    if val is None:
        return []
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    if isinstance(val, (list, tuple)):
        return [str(v).strip() for v in val if str(v).strip()]
    raise ManifestError(f"`{key}` 必须是 YAML 列表或逗号分隔字符串")


def parse_persona_md(path: str | Path, *, source: str = "builtin") -> PersonaManifest:
    """解析一个专家 md 文件 → PersonaManifest。非法即抛 ManifestError。

    复用 skills.manager.parse_frontmatter 提取 frontmatter；正文 = 其余部分。
    正文过 _scan_for_injection 注入检测（与 SOUL.md 同策略；命中返回 BLOCKED 占位而非抛错）。
    """
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"无法读取 {p}: {e}")

    meta, body = parse_frontmatter(content)
    if not isinstance(meta, dict):
        meta = {}

    persona_id = str(meta.get("id") or "").strip()
    if not persona_id:
        raise ManifestError(f"{p.name}: 缺少必填字段 `id`（注册键/目录名）")
    if not _ID_RE.match(persona_id):
        raise ManifestError(
            f"{p.name}: id {persona_id!r} 非法——仅允许小写字母/数字开头，"
            "后续 `-`/`_`，最长 64 字符"
        )

    name = str(meta.get("name") or persona_id).strip()
    if not name:
        raise ManifestError(f"{p.name}: 缺少必填字段 `name`")

    body = body.strip()
    if not body:
        raise ManifestError(f"{p.name}: 正文不能为空（正文即角色系统提示）")

    # 注入检测：与 SOUL.md 同策略，命中返回 BLOCKED 占位（fail-safe 而非抛错）
    from minihermes.core.prompt.builder import _scan_for_injection
    body = _scan_for_injection(body, p.name)

    expert_type = str(meta.get("expert_type", "agent")).strip().lower()
    if expert_type not in VALID_EXPERT_TYPES:
        raise ManifestError(f"{p.name}: expert_type 必须是 {sorted(VALID_EXPERT_TYPES)} 之一")

    soul_mode = str(meta.get("soul_mode", "replace")).strip().lower()
    if soul_mode not in VALID_SOUL_MODES:
        raise ManifestError(f"{p.name}: soul_mode 必须是 {sorted(VALID_SOUL_MODES)} 之一")

    members = _strlist(meta, "members")
    lead_id = str(meta.get("lead_id") or (persona_id if expert_type == "team" else "")).strip()

    try:
        max_team_iterations = int(meta.get("max_team_iterations", 50))
    except (TypeError, ValueError):
        raise ManifestError(f"{p.name}: max_team_iterations 必须是整数")

    return PersonaManifest(
        id=persona_id,
        name=name,
        expert_type=expert_type,
        icon=str(meta.get("icon", "")).strip(),
        tagline=str(meta.get("tagline", "")).strip(),
        description=str(meta.get("description", "")).strip(),
        category=str(meta.get("category", "general")).strip() or "general",
        tags=_strlist(meta, "tags"),
        quick_prompts=_strlist(meta, "quick_prompts"),
        default_init_prompt=str(meta.get("default_init_prompt", "")).strip(),
        tools=_strlist(meta, "tools"),
        skills=_strlist(meta, "skills"),
        soul_mode=soul_mode,
        system_prompt=body,
        source=source,
        path=str(p),
        members=members,
        lead_id=lead_id,
        max_team_iterations=max_team_iterations,
    )


def manifest_to_dict(m: PersonaManifest) -> dict:
    """序列化为前端/命令展示用的 dict（含完整 system_prompt，桌面详情页滚动展示全文）。"""
    return {
        "id": m.id,
        "name": m.name,
        "expert_type": m.expert_type,
        "icon": m.icon,
        "tagline": m.tagline,
        "description": m.description,
        "category": m.category,
        "tags": m.tags,
        "quick_prompts": m.quick_prompts,
        "default_init_prompt": m.default_init_prompt,
        "tools": m.tools,
        "skills": m.skills,
        "soul_mode": m.soul_mode,
        "members": m.members,
        "lead_id": m.lead_id,
        "source": m.source,
        "is_team": m.is_team(),
        # 团员展示名（详情面板用）
        "member_names": [mem.name for mem in m.resolved_members],
        # 角色正文（身份 system prompt 全文；本地桌面展示，CLI /persona view 已有正文预览先例）
        "system_prompt": m.system_prompt,
    }
