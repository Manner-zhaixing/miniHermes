"""专家（Persona）系统 —— 让同一内核以不同专业身份工作。

格式：一个 Markdown 文件 = 一个专家（YAML frontmatter 声明 + 正文=角色系统提示），
与 SKILL.md 同构。会话级单专家：一个会话绑定一个专家，切专家（桌面）= 新建会话。
"""

from minihermes.core.personas.manifest import (
    ManifestError,
    PersonaManifest,
    manifest_to_dict,
    parse_persona_md,
)
from minihermes.core.personas.registry import (
    LOCAL_DIR,
    PersonaRegistry,
    get_persona_registry,
)
from minihermes.core.personas.team import build_member_prompt, build_team_roster

__all__ = [
    "ManifestError",
    "PersonaManifest",
    "manifest_to_dict",
    "parse_persona_md",
    "LOCAL_DIR",
    "PersonaRegistry",
    "get_persona_registry",
    "build_member_prompt",
    "build_team_roster",
]
