"""
SQLite 会话持久化。

对齐 hermes 的 hermes_state.py 设计（精简版）：
  - 创建/结束会话（含 model_config、system_prompt、end_reason）
  - 追加/读取消息（含 token_count、finish_reason）
  - Token 统计、工具调用计数
  - 列出/删除历史会话
"""

import functools
import json
import sqlite3
import threading
import time
from pathlib import Path

SESSION_DB_PATH = "~/.minihermes/state.db"
SESSION_LIST_LIMIT = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'cli',
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    title TEXT,
    parent_session_id TEXT,
    persona_id TEXT,
    cwd TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    tool_name TEXT,
    reasoning TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    msg_type TEXT NOT NULL DEFAULT 'normal'
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def _locked(fn):
    """序列化 SessionDB 方法调用（多会话并行线程共享同一 sqlite 连接）。

    桌面端多会话并行后，各会话 turn 跑在独立线程、同时读写 state.db。
    Python sqlite3 连接对象（即使 check_same_thread=False）不支持并发使用，
    必须用锁串行化。WAL 已在文件层串行写，这里只是保护连接对象的线程安全。
    CLI 单线程不受影响。用 RLock 以支持方法间嵌套调用（如 create_child_session）。
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class SessionDB:
    def __init__(self):
        self._list_limit = SESSION_LIST_LIMIT
        self._lock = threading.RLock()

        p = Path(SESSION_DB_PATH).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self.backfill_fts()

    def _migrate(self):
        """增量 schema 迁移。"""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "parent_session_id" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN parent_session_id TEXT")
        if "persona_id" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN persona_id TEXT")
        if "cwd" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN cwd TEXT")
        # messages 表：subagent_trace（子代理过程 JSON，仅供前端展示，不进 LLM 历史）
        msg_cols = [r[1] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "subagent_trace" not in msg_cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN subagent_trace TEXT")

    @_locked
    def create_session(
        self,
        session_id: str,
        model: str,
        model_config: str = None,
        system_prompt: str = None,
        persona_id: str = None,
        cwd: str = None,
    ) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO sessions (id, source, model, model_config, system_prompt, started_at, persona_id, cwd)
               VALUES (?, 'cli', ?, ?, ?, ?, ?, ?)""",
            (session_id, model, model_config, system_prompt, time.time(), persona_id, cwd),
        )

    @_locked
    def end_session(self, session_id: str, end_reason: str = "user_exit") -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
            (time.time(), end_reason, session_id),
        )

    @_locked
    def create_child_session(
        self,
        parent_id: str,
        child_id: str,
        model: str,
        model_config: str = None,
        system_prompt: str = None,
        persona_id: str = None,
        cwd: str = None,
    ) -> None:
        """压缩后创建子 session，同时结束 parent session。

        默认继承 parent 的 persona_id 与 cwd（压缩不丢专家、不丢工作目录）；
        显式传入可覆盖。
        """
        self.end_session(parent_id, end_reason="compression")
        if persona_id is None:
            persona_id = self.get_persona(parent_id)
        if cwd is None:
            cwd = self.get_session_cwd(parent_id)
        self._conn.execute(
            """INSERT INTO sessions (id, source, model, model_config, system_prompt,
               started_at, parent_session_id, persona_id, cwd)
               VALUES (?, 'cli', ?, ?, ?, ?, ?, ?, ?)""",
            (child_id, model, model_config, system_prompt, time.time(), parent_id, persona_id, cwd),
        )

    @_locked
    def set_persona(self, session_id: str, persona_id: str | None) -> None:
        """绑定/解绑会话专家（persona_id=None 解绑恢复默认）。"""
        self._conn.execute(
            "UPDATE sessions SET persona_id = ? WHERE id = ?",
            (persona_id, session_id),
        )

    @_locked
    def get_persona(self, session_id: str) -> str | None:
        """读取会话绑定的专家 id（无则 None）。"""
        cur = self._conn.execute(
            "SELECT persona_id FROM sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    @_locked
    def get_session_cwd(self, session_id: str) -> str | None:
        """读取会话绑定的工作目录（未绑定/迁移前行 → None）。"""
        cur = self._conn.execute(
            "SELECT cwd FROM sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    @_locked
    def set_session_cwd(self, session_id: str, cwd: str) -> None:
        """更新会话绑定的工作目录（空会话切目录时重绑定用）。"""
        self._conn.execute(
            "UPDATE sessions SET cwd = ? WHERE id = ?", (cwd, session_id)
        )

    @_locked
    def get_session_message_count(self, session_id: str) -> int | None:
        """读取会话已产生的消息条数（append_message 每写一行 +1）。

        作为「切换工作目录守卫」的权威输入；会话不存在返回 None。
        """
        cur = self._conn.execute(
            "SELECT message_count FROM sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    @_locked
    def resolve_resume_session_id(self, session_id: str) -> str:
        """沿压缩链路走到最新的有消息的 session。"""
        current = session_id
        visited = set()
        while current not in visited:
            visited.add(current)
            cur = self._conn.execute(
                """SELECT id FROM sessions
                   WHERE parent_session_id = ? ORDER BY started_at DESC LIMIT 1""",
                (current,),
            )
            child = cur.fetchone()
            if not child:
                return current
            cur2 = self._conn.execute(
                "SELECT end_reason FROM sessions WHERE id = ?", (current,)
            )
            row = cur2.fetchone()
            if row and row[0] == "compression":
                current = child[0]
            else:
                return current
        return current

    @_locked
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = None,
        tool_calls: list = None,
        tool_call_id: str = None,
        tool_name: str = None,
        reasoning: str = None,
        token_count: int = None,
        finish_reason: str = None,
        msg_type: str = "normal",
        subagent_trace: str = None,
    ) -> None:
        tc_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        self._conn.execute(
            """INSERT INTO messages
               (session_id, role, content, tool_calls, tool_call_id, tool_name, reasoning, timestamp, token_count, finish_reason, msg_type, subagent_trace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, tc_json, tool_call_id, tool_name, reasoning, time.time(), token_count, finish_reason, msg_type, subagent_trace),
        )
        self._conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
            (session_id,),
        )

    @_locked
    def increment_tool_calls(self, session_id: str, count: int = 1) -> None:
        self._conn.execute(
            "UPDATE sessions SET tool_call_count = tool_call_count + ? WHERE id = ?",
            (count, session_id),
        )

    @_locked
    def update_tokens(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        self._conn.execute(
            """UPDATE sessions SET
               input_tokens = input_tokens + ?,
               output_tokens = output_tokens + ?,
               reasoning_tokens = reasoning_tokens + ?
               WHERE id = ?""",
            (input_tokens, output_tokens, reasoning_tokens, session_id),
        )

    @_locked
    def get_token_stats(self, session_id: str) -> dict:
        """从 messages 表统计会话 token 消耗（CLI 与桌面共用）。

        注意：CLI 走 update_tokens 增量累加，桌面端绕过该路径，
        因此统一在此按消息聚合，避免重复累加。
        """
        try:
            cur = self._conn.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN role IN ('user','tool') THEN token_count ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN role = 'assistant' THEN token_count ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN reasoning IS NOT NULL THEN LENGTH(reasoning) / 4 ELSE 0 END), 0)
                   FROM messages WHERE session_id = ?""",
                (session_id,),
            )
            inp, out, reason = cur.fetchone()
            return {
                "input": int(inp or 0),
                "output": int(out or 0),
                "reasoning": int(reason or 0),
            }
        except Exception:
            return {"input": 0, "output": 0, "reasoning": 0}

    @_locked
    def get_messages(self, session_id: str) -> list[dict]:
        cur = self._conn.execute(
            """SELECT role, content, tool_calls, tool_call_id, tool_name, reasoning, token_count, finish_reason, msg_type, subagent_trace
               FROM messages WHERE session_id = ? ORDER BY id""",
            (session_id,),
        )
        messages = []
        for row in cur.fetchall():
            role, content, tc_json, tool_call_id, tool_name, reasoning, token_count, finish_reason, msg_type, subagent_trace = row
            msg: dict = {"role": role}
            if content is not None:
                msg["content"] = content
            if tc_json:
                msg["tool_calls"] = json.loads(tc_json)
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            if tool_name:
                msg["tool_name"] = tool_name
            if reasoning:
                msg["_reasoning"] = reasoning
            if token_count is not None:
                msg["_token_count"] = token_count
            if finish_reason:
                msg["finish_reason"] = finish_reason
            if msg_type != "normal":
                msg["_msg_type"] = msg_type
            if subagent_trace:
                msg["subagent_trace"] = json.loads(subagent_trace)
            messages.append(msg)
        return messages

    @_locked
    def get_messages_for_llm(self, session_id: str) -> list[dict]:
        """加载用于 LLM 的消息：反向遍历，遇到最近的 summary 停止。

        注意：subagent_trace 只给前端展示，绝不进入 LLM 历史——返回前逐条剥离。
        """
        all_msgs = self.get_messages(session_id)
        for msg in all_msgs:
            msg.pop("subagent_trace", None)

        summary_idx = None
        for i in range(len(all_msgs) - 1, -1, -1):
            if all_msgs[i].get("_msg_type") == "summary":
                summary_idx = i
                break

        if summary_idx is None:
            return all_msgs

        return [all_msgs[summary_idx]] + all_msgs[summary_idx + 1:]

    @_locked
    def list_sessions(self, limit: int = None) -> list[dict]:
        if limit is None:
            limit = self._list_limit
        cur = self._conn.execute(
            """SELECT id, source, model, model_config, system_prompt, started_at, ended_at,
                      end_reason, message_count, tool_call_count, input_tokens, output_tokens,
                      reasoning_tokens, title, parent_session_id, persona_id, cwd
               FROM sessions ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        )
        return [
            {
                "id": row[0],
                "source": row[1],
                "model": row[2],
                "model_config": row[3],
                "system_prompt": row[4],
                "started_at": row[5],
                "ended_at": row[6],
                "end_reason": row[7],
                "message_count": row[8],
                "tool_call_count": row[9],
                "input_tokens": row[10],
                "output_tokens": row[11],
                "reasoning_tokens": row[12],
                "title": row[13],
                "parent_session_id": row[14],
                "persona_id": row[15],
                "cwd": row[16],
            }
            for row in cur.fetchall()
        ]

    @_locked
    def get_last_session_id(self) -> str | None:
        cur = self._conn.execute(
            "SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else None

    @_locked
    def set_title(self, session_id: str, title: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title.strip()[:100], session_id),
        )

    @_locked
    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    @_locked
    def search_messages(self, query: str, limit: int = 5) -> list[dict]:
        """FTS5 搜索消息内容，按 session 分组返回匹配片段。"""
        try:
            cur = self._conn.execute(
                """SELECT m.session_id, m.role, m.content, s.title, s.started_at,
                          snippet(messages_fts, 0, '>>>', '<<<', '...', 40) as snippet
                   FROM messages_fts
                   JOIN messages m ON m.id = messages_fts.rowid
                   JOIN sessions s ON s.id = m.session_id
                   WHERE messages_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit * 3),
            )
            rows = cur.fetchall()
        except Exception:
            return []

        # 按 session 分组，每个 session 最多保留 3 条匹配
        sessions: dict[str, dict] = {}
        for session_id, role, content, title, started_at, snippet in rows:
            if session_id not in sessions:
                if len(sessions) >= limit:
                    break
                sessions[session_id] = {
                    "session_id": session_id,
                    "title": title,
                    "started_at": started_at,
                    "matches": [],
                }
            if len(sessions[session_id]["matches"]) < 3:
                sessions[session_id]["matches"].append({
                    "role": role,
                    "snippet": snippet or (content[:200] if content else ""),
                })

        return list(sessions.values())

    @_locked
    def backfill_fts(self):
        """首次启动时回填已有消息到 FTS 表。"""
        count = self._conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        if count == 0:
            self._conn.execute(
                "INSERT INTO messages_fts(rowid, content) "
                "SELECT id, content FROM messages WHERE content IS NOT NULL"
            )

    @_locked
    def close(self):
        self._conn.close()
