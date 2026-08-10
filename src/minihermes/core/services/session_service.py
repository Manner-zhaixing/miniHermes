"""会话编排服务：CLI 与桌面共用的 session 工具。"""

import uuid
from datetime import datetime

import minihermes.core.config as cfg


def generate_session_id() -> str:
    """生成唯一 session id。"""
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{timestamp_str}_{short_uuid}"


def context_window() -> int:
    """当前生效厂商/模型的上下文窗口大小（tokens）。"""
    try:
        return int(cfg.get_provider_config().get("context_window") or 0) or 1000000
    except Exception:
        return 1000000


def token_stats(db, sid: str) -> dict:
    """统计会话 token 消耗（输入/输出/思考），附带 context_window。"""
    try:
        stats = db.get_token_stats(sid)
        return {
            "input": int(stats.get("input", 0)),
            "output": int(stats.get("output", 0)),
            "reasoning": int(stats.get("reasoning", 0)),
            "context_window": context_window(),
        }
    except Exception:
        return {"input": 0, "output": 0, "reasoning": 0, "context_window": context_window()}


def session_to_ui(s: dict, tokens: dict | None = None) -> dict:
    """把 DB session 行转换为前端友好结构。"""
    started = s.get("started_at")
    title = s.get("title") or (
        f"会话 {datetime.fromtimestamp(started).strftime('%m-%d %H:%M')}" if started else ""
    )
    return {
        "id": s["id"],
        "title": title,
        "model": s.get("model") or "",
        "started_at": started,
        "ended_at": s.get("ended_at"),
        "message_count": s.get("message_count", 0),
        "tool_call_count": s.get("tool_call_count", 0),
        "parent_session_id": s.get("parent_session_id"),
        "persona_id": s.get("persona_id") or "",
        "cwd": s.get("cwd") or "",
        "tokens": tokens or {"input": 0, "output": 0, "reasoning": 0},
    }


def list_sessions_ui(db, limit: int = 50) -> list[dict]:
    """列出会话并附带 token 统计（桌面会话面板用）。"""
    rows = db.list_sessions(limit=limit)
    return [session_to_ui(s, token_stats(db, s["id"])) for s in rows]
