"""斜杠命令注册表与共享逻辑（CLI 与桌面共用的单一事实源）。"""

_INIT_INSTRUCTION = """[/init] Please analyze this codebase and create a minihermes.md file at the current working directory's root.

What to include:
1. Build/run/test commands used in this project
2. High-level architecture (the "big picture" that requires reading multiple files to understand)
3. Key conventions or patterns that aren't obvious from a single file

Guidelines:
- Read the README.md if present, plus key config files (package.json, pyproject.toml, Cargo.toml, go.mod, etc.)
- Use list_dir and read_file to explore structure; sample a few core source files
- Keep it concise — focus on what a future agent needs to be productive quickly
- Do NOT include obvious instructions ("write tests", "handle errors", "follow security best practices")
- Do NOT enumerate every file or directory — list only what matters
- If a CLAUDE.md / AGENTS.md / .hermes.md / README.md already exists, read it first and adapt key insights

Begin the file with this exact header:

# minihermes.md

This file provides project context to miniHermes when working in this repository.

When done, write the file using the write_file tool with path="minihermes.md", then briefly tell me what you captured.
"""


# ── 统一命令定义 ───────────────────────────────────────────────────────────────
# 保留两端原有展示文案（cli_desc / desktop_desc），避免用户可见文案变动。
# desktop_action: local=前端处理 / backend=后端处理 / skill=技能命令

_COMMAND_DEFS = [
    {"cmd": "/clear", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "local",
     "cli_desc": "Clear conversation history", "desktop_desc": "清空当前会话，新建会话"},
    {"cmd": "/compress", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "backend",
     "cli_desc": "Manually trigger context compression", "desktop_desc": "强制触发上下文压缩"},
    {"cmd": "/title", "has_arg": True, "cli": True, "desktop": True, "desktop_action": "backend",
     "cli_desc": "Set title for current session", "desktop_desc": "设置当前会话标题"},
    {"cmd": "/init", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "backend",
     "cli_desc": "Scan project and generate minihermes.md", "desktop_desc": "扫描项目生成 minihermes.md"},
    {"cmd": "/sysprompt", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "backend",
     "cli_desc": "Print current system prompt (debug)", "desktop_desc": "打印当前系统提示词（调试）"},
    {"cmd": "/exit", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "local",
     "cli_desc": "Exit MiniHermes", "desktop_desc": "退出应用"},
    {"cmd": "/help", "has_arg": False, "cli": True, "desktop": True, "desktop_action": "local",
     "cli_desc": "Show available commands", "desktop_desc": "显示可用命令"},
    # CLI 专用命令
    {"cmd": "/plan", "has_arg": True, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "Enter plan mode (read-only analysis, then execute)", "desktop_desc": None},
    {"cmd": "/history", "has_arg": False, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "Show current conversation length", "desktop_desc": None},
    {"cmd": "/sessions", "has_arg": False, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "List recent sessions", "desktop_desc": None},
    {"cmd": "/resume", "has_arg": True, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "Resume a previous session", "desktop_desc": None},
    {"cmd": "/setup", "has_arg": False, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "Interactive configuration setup", "desktop_desc": None},
    {"cmd": "/quit", "has_arg": False, "cli": True, "desktop": False, "desktop_action": None,
     "cli_desc": "Exit MiniHermes", "desktop_desc": None},
]

# CLI 注册表（dict: cmd -> desc），补全器使用
SLASH_COMMANDS: dict[str, str] = {
    d["cmd"]: d["cli_desc"] for d in _COMMAND_DEFS if d["cli"]
}

# 桌面注册表（list[dict]），/api/commands 与前端命令面板使用
BUILTIN_COMMANDS: list[dict] = [
    {"cmd": d["cmd"], "desc": d["desktop_desc"], "has_arg": d["has_arg"], "action": d["desktop_action"]}
    for d in _COMMAND_DEFS if d["desktop"]
]


# ── 技能命令 ───────────────────────────────────────────────────────────────────

def register_skill_commands():
    """启动时扫描 skills 并追加到 CLI SLASH_COMMANDS。"""
    from minihermes.core.skills import discover_skills
    for skill in discover_skills():
        cmd = f"/{skill['name']}"
        if cmd not in SLASH_COMMANDS:
            SLASH_COMMANDS[cmd] = f"[skill] {skill['description']}"


def build_skill_activation_message(skill_info: dict, arg: str = "") -> str:
    """构建技能激活消息（CLI 与桌面共用）。"""
    skill_name = skill_info.get("name", "")
    lines = [
        f"[IMPORTANT: The user has invoked the '{skill_name}' skill. "
        f"Follow the instructions below unless the user asks otherwise.]",
        "",
    ]
    if skill_info.get("category"):
        lines.insert(0, f"[Skill category: {skill_info['category']}]")

    linked = skill_info.get("linked_files", {})
    has_linked = any(v for v in linked.values())
    if has_linked:
        lines.append(f"[This skill has supporting files at {skill_info['skill_dir']}:]")
        for subdir, files in linked.items():
            if files:
                file_list = ", ".join(files[:5])
                if len(files) > 5:
                    file_list += f" (+{len(files) - 5} more)"
                lines.append(f"  {subdir}/: {file_list}")
        lines.append(f"[Use skill_view('{skill_name}', file_path='...') to load a specific file.]")
        lines.append("")

    if not skill_info.get("platform_compatible", True):
        lines.append("[WARNING: This skill may not be fully compatible with your current platform.]")
        lines.append("")

    if skill_info.get("setup_needed"):
        lines.append(f"[SETUP NEEDED: {skill_info.get('setup_note', 'Some environment variables are missing.')}]")
        lines.append("")

    lines.append(skill_info["content"])

    if arg:
        lines.append(f"\n\n[User request: {arg}]")

    return "\n".join(lines)
