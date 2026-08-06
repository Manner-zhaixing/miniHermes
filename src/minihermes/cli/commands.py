"""斜杠命令定义与处理。"""

import json
import sys
import time
from typing import Optional

from minihermes.core.output import _cprint, _DIM, _RST
from minihermes.cli.renderer import print_resumed_history
from minihermes.core.session import SessionDB
from minihermes.core.skills import load_skill, load_skill_structured
from minihermes.core.services.commands import (
    SLASH_COMMANDS,  # noqa: F401  (补全器引用同一对象)
    _INIT_INSTRUCTION,
    register_skill_commands,  # noqa: F401  (main.py 经此获取)
    build_skill_activation_message,
)
from minihermes.core.services.session_service import generate_session_id
import minihermes.core.config as cfg


def handle_slash_command(
    cmd: str, history: list, db: SessionDB, session_id: str,
    agent=None,
) -> tuple[bool, list, str, Optional[str]]:
    """
    处理斜杠命令。

    Returns:
        (handled, history, session_id, override_message)
        handled=True 表示命令已处理完毕（主循环应 continue）
        override_message 非 None 时替换原始输入后继续交给 agent
    """
    parts = cmd.strip().split(None, 1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        db.end_session(session_id, end_reason="user_exit")
        print("Bye!")
        sys.exit(0)

    if command == "/compress":
        print("[manual compression triggered — will execute on next LLM call]")
        return True, history, session_id, None

    if command == "/clear":
        print("\033[2J\033[H", end="")
        print("[history cleared — starting new session]")
        db.end_session(session_id, end_reason="clear")
        new_id = generate_session_id()
        from minihermes.core.provider.provider import MODEL_NAME
        model_name = cfg.get_model_config().get("name") or MODEL_NAME
        db.create_session(new_id, model_name,
                          model_config=json.dumps(cfg.get_model_config(), ensure_ascii=False))
        return True, [], new_id, None

    if command == "/history":
        user_turns = sum(1 for m in history if m["role"] == "user")
        print(f"[session: {session_id} | {user_turns} user turns, {len(history)} total messages]")
        return True, history, session_id, None

    if command == "/sessions":
        sessions = db.list_sessions(limit=15)
        if not sessions:
            print("[no sessions found]")
        else:
            print(f"{'ID':<14} {'Messages':>4}  {'Time':<20} Title")
            print("─" * 60)
            for s in sessions:
                t = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"]))
                title = s["title"] or ""
                active = " ◀" if s["id"] == session_id else ""
                print(f"{s['id']:<14} {s['message_count']:>4}  {t:<20} {title}{active}")
        return True, history, session_id, None

    if command == "/resume":
        target_id = arg.strip()
        if not target_id:
            sessions = db.list_sessions(limit=5)
            candidates = [s for s in sessions if s["id"] != session_id and s["message_count"] > 0]
            if not candidates:
                print("[no previous session to resume]")
                return True, history, session_id, None
            target_id = candidates[0]["id"]

        # 解析压缩链路：走到最新的有消息的 session
        resolved_id = db.resolve_resume_session_id(target_id)

        all_msgs = db.get_messages(resolved_id)
        if not all_msgs:
            print(f"[session {resolved_id} has no messages]")
            return True, history, session_id, None

        db.end_session(session_id, end_reason="resumed")
        if resolved_id != target_id:
            print(f"[session {target_id} was compressed → following to {resolved_id}]")
        print(f"[resumed session {resolved_id} with {len(all_msgs)} messages]")
        print_resumed_history(all_msgs)
        llm_msgs = db.get_messages_for_llm(resolved_id)
        return True, llm_msgs, resolved_id, None

    if command == "/title":
        if not arg:
            print("[usage: /title <name>]")
        else:
            db.set_title(session_id, arg)
            print(f"[session titled: {arg.strip()[:100]}]")
        return True, history, session_id, None

    if command == "/sysprompt":
        if agent is None or not getattr(agent, "system_prompt", None):
            print("[no system prompt available]")
            return True, history, session_id, None
        sp = agent.system_prompt
        char_count = len(sp)
        token_estimate = char_count // 4
        print(f"{_DIM}─── system prompt ({char_count} chars, ~{token_estimate} tokens) ───{_RST}")
        print(sp)
        print(f"{_DIM}─── end of system prompt ───{_RST}")
        return True, history, session_id, None

    if command == "/help":
        print(
            "/clear       — clear history & start new session\n"
            "/compress    — manually trigger context compression\n"
            "/history     — show current session info\n"
            "/sessions    — list recent sessions\n"
            "/resume [id] — resume a previous session\n"
            "/title <name>— name the current session\n"
            "/sysprompt   — print current system prompt (debug)\n"
            "/setup       — interactive configuration setup\n"
            "/init        — scan project and generate minihermes.md\n"
            "/exit        — exit MiniHermes\n"
            "Ctrl+C       — interrupt current response\n"
            "Ctrl+D       — exit\n"
            "Shift+Enter / Cmd+Enter — new line (multiline input)"
        )
        return True, history, session_id, None

    if command == "/plan":
        override_msg = f"__PLAN_MODE__:{arg}"
        return False, history, session_id, override_msg

    if command == "/init":
        from pathlib import Path
        target = Path.cwd() / "minihermes.md"
        if target.exists():
            print(f"[minihermes.md already exists at {target}. Delete it first to regenerate.]")
            return True, history, session_id, None
        return False, history, session_id, _INIT_INSTRUCTION

    if command == "/setup":
        # /setup 的实际处理在 conversation.py 中通过 run_in_terminal 完成
        # 如果走到这里说明不在正常对话循环上下文中
        from minihermes.cli.setup_wizard import run_setup_cli
        try:
            run_setup_cli()  # 无 event loop，直接运行（首次向导等场景）
        except Exception as e:
            print(f"[Setup error: {e}]")
        return True, history, session_id, None

    # 尝试匹配 skill（优先用结构化数据，降级到旧版 load_skill）
    skill_name = command.lstrip("/")
    skill_info = load_skill_structured(skill_name)
    if skill_info:
        override_msg = build_skill_activation_message(skill_info, arg)
        return False, history, session_id, override_msg

    # Fallback: try old-school load_skill for backward compat
    skill_content = load_skill(skill_name)
    if skill_content:
        msg = f"[Skill '{skill_name}' loaded. Follow these instructions:]\n\n{skill_content}"
        if arg:
            msg += f"\n\n[User request: {arg}]"
        return False, history, session_id, msg

    print(f"[unknown command: {command}. Type /help for available commands]")
    return True, history, session_id, None
