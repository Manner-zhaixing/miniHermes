"""Persona 注册表 —— 内置 + 本地双源扫描 → id → PersonaManifest。

扫描顺序（同 id 后者覆盖前者）：
  1. 内置目录  core/personas/_builtin/*.md          （打包进 wheel，直读不复制）
  2. 本地目录  ~/.minihermes/personas/*.md           （用户自建，可覆盖内置）
  3. extra_dirs（可选，测试/项目级扩展）

team 成员惰性解析：list()/get() 时把 members id → PersonaManifest，缺失成员剔除 + log（不抛断）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

from minihermes.core.config import MINIHERMES_HOME
from minihermes.core.personas.manifest import ManifestError, PersonaManifest, parse_persona_md

logger = logging.getLogger(__name__)

# 内置专家目录（打包数据，直读）
BUILTIN_DIR = Path(__file__).resolve().parent / "_builtin"
# 用户本地专家目录（自定义/覆盖内置）
LOCAL_DIR = MINIHERMES_HOME / "personas"


class PersonaRegistry:
    """双源合一注册表。线程安全：扫描只在构造时执行，之后只读。"""

    def __init__(self, builtin_dir: str | Path = BUILTIN_DIR, extra_dirs: Optional[Iterable] = None):
        self._entries: dict[str, PersonaManifest] = {}
        self._builtin_dir = Path(builtin_dir)

        # 本地目录确保存在（用户可放入 md），建目录无害
        try:
            LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("无法创建本地专家目录 %s: %s", LOCAL_DIR, e)

        self._scan_dir(self._builtin_dir, source="builtin")
        self._scan_dir(LOCAL_DIR, source="local")
        for d in extra_dirs or []:
            self._scan_dir(d, source="local")

    def _scan_dir(self, directory: str | Path, *, source: str) -> None:
        d = Path(directory)
        if not d.is_dir():
            return
        for md in sorted(d.glob("*.md")):
            try:
                m = parse_persona_md(md, source=source)
            except ManifestError as e:
                logger.warning("跳过非法专家 %s: %s", md, e)
                continue
            # 后扫描的覆盖先扫描的 → 本地覆盖内置
            self._entries[m.id] = m

    def _resolve_members(self, m: PersonaManifest) -> None:
        """team 惰性解析：members id → manifest；缺失剔除 + log，不抛断。"""
        if not m.is_team():
            m.resolved_members = []
            return
        resolved = []
        for mid in m.members:
            mem = self._entries.get(mid)
            if mem is None:
                logger.warning("team %s 成员 %s 不存在，已从花名册剔除", m.id, mid)
                continue
            resolved.append(mem)
        m.resolved_members = resolved

    def list(self) -> list[PersonaManifest]:
        """全部可用专家（含 team 成员解析）。稳定排序：内置在前，其余按 id。"""
        out = []
        for m in self._entries.values():
            self._resolve_members(m)
            out.append(m)
        out.sort(key=lambda m: (0 if m.source == "builtin" else 1, m.id))
        return out

    def get(self, persona_id: str) -> Optional[PersonaManifest]:
        m = self._entries.get(persona_id)
        if m:
            self._resolve_members(m)
        return m

    def resolve(self, persona_id: Optional[str]) -> Optional[PersonaManifest]:
        """不存在时 log + None（降级为无专家，不抛断会话）。"""
        if not persona_id:
            return None
        m = self.get(persona_id)
        if m is None:
            logger.warning("persona %r 不存在，降级为无专家", persona_id)
        return m

    def names(self) -> list[str]:
        return sorted(self._entries)

    def __contains__(self, persona_id: str) -> bool:
        return persona_id in self._entries


# ── 模块级单例（CLI/桌面/Agent 共用，避免重复扫盘）───────────────────────────────
_singleton: Optional[PersonaRegistry] = None


def get_persona_registry() -> PersonaRegistry:
    global _singleton
    if _singleton is None:
        _singleton = PersonaRegistry()
    return _singleton


def reset_persona_registry() -> None:
    """测试用：清空单例。"""
    global _singleton
    _singleton = None
