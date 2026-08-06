"""
MiniHermes Desktop — Python 子进程服务。

架构：Electron 壳（前端 React）↔ WebSocket/HTTP ↔ 本服务 ↔ minihermes 内核

职责：
  1. 拉起 minihermes 内核（Provider / Agent / SessionDB / 技能系统）
  2. 通过 WebSocket 与前端实时双向通信（流式 token、思考、工具事件、
     clarify/approval 请求-应答）
  3. 通过 HTTP API 提供会话 / 配置 / 用户记忆 / 技能管理

启动方式（由 Electron 主进程 spawn）：
    python server.py
启动后把 {"port": <port>} 以单行 JSON 打印到 stdout，Electron 据此连接。
"""

import asyncio
import json
import os
import socket
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── 把 minihermes 内核根目录注入 sys.path ──────────────────────────────────
# 开发环境：直接 import 内核源码
# PyInstaller 打包环境：模块已随 bundle 打包（sys._MEIPASS），无需注入
if not (getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)):
    _KERNEL_ROOT = Path(__file__).resolve().parent.parent
    if str(_KERNEL_ROOT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_ROOT))

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config as cfg
import tools as tool_registry
from provider import Provider
from provider.provider import MODEL_NAME
from agent.agent import Agent
from session import SessionDB
from skills import discover_skills, load_skill_structured, sync_builtin_skills

# Plan 模式（与内核 CLI 对齐）：只读规划 + 审批执行
from cli.plan import PLAN_ALLOWED_TOOLS, PLAN_MODE_PROMPT, generate_plan_path

PLAN_MODE_PREFIX = "__PLAN_MODE__:"
PLAN_TIMEOUT = 600

from gui_renderer import GuiRenderer

MINIHERMES_HOME = Path.home() / ".minihermes"
CONFIG_PATH = MINIHERMES_HOME / "config.yaml"
MEMORY_DIR = MINIHERMES_HOME / "memory"
USER_MEMORY_FILE = MEMORY_DIR / "USER.md"
PROJECT_MEMORY_FILE = MEMORY_DIR / "MEMORY.md"

# 成果面板关注的写文件工具
WRITE_TOOLS = ("write_file",)

# ── 斜杠命令（桌面端）──────────────────────────────────────────────
# action: local=前端处理 UI 动作; backend=后端处理; skill=技能命令
BUILTIN_COMMANDS = [
    {"cmd": "/help", "desc": "显示可用命令", "has_arg": False, "action": "local"},
    {"cmd": "/clear", "desc": "清空当前会话，新建会话", "has_arg": False, "action": "local"},
    {"cmd": "/compress", "desc": "强制触发上下文压缩", "has_arg": False, "action": "backend"},
    {"cmd": "/title", "desc": "设置当前会话标题", "has_arg": True, "action": "backend"},
    {"cmd": "/init", "desc": "扫描项目生成 minihermes.md", "has_arg": False, "action": "backend"},
    {"cmd": "/sysprompt", "desc": "打印当前系统提示词（调试）", "has_arg": False, "action": "backend"},
    {"cmd": "/exit", "desc": "退出应用", "has_arg": False, "action": "local"},
]

BACKEND_CMDS = {c["cmd"] for c in BUILTIN_COMMANDS if c["action"] == "backend"}

CLARIFY_TIMEOUT = 120
APPROVAL_TIMEOUT = 300

app = FastAPI(title="MiniHermes Desktop Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 工具函数 ──────────────────────────────────────────────────────────────

def generate_session_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def session_to_ui(s: dict, tokens: dict | None = None) -> dict:
    """把 DB session 行转换为前端友好结构。"""
    title = s.get("title") or f"会话 {s['started_at'] and datetime.fromtimestamp(s['started_at']).strftime('%m-%d %H:%M') or ''}"
    return {
        "id": s["id"],
        "title": title,
        "model": s.get("model") or "",
        "started_at": s.get("started_at"),
        "ended_at": s.get("ended_at"),
        "message_count": s.get("message_count", 0),
        "tool_call_count": s.get("tool_call_count", 0),
        "parent_session_id": s.get("parent_session_id"),
        "tokens": tokens or {"input": 0, "output": 0, "reasoning": 0},
    }


# ── ConnectionManager: 线程安全的 WS 消息分发 ───────────────────────────────

class ConnectionManager:
    """持有当前 WebSocket 连接；send() 可从任意线程调用（Agent 线程）。"""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._sender_task: asyncio.Task | None = None
        self._ws: WebSocket | None = None

    async def connect(self, ws: WebSocket):
        self._ws = ws
        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())

    async def disconnect(self):
        self._ws = None
        if self._sender_task:
            self._sender_task.cancel()
            self._sender_task = None

    def send(self, payload: dict):
        """线程安全：从任何线程调用，消息入队由事件循环协程发送。"""
        self._queue.put_nowait(payload)

    async def _sender_loop(self):
        while True:
            payload = await self._queue.get()
            ws = self._ws
            if ws is None:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                pass


manager = ConnectionManager()


# ── PendingRequest: clarify / approval 阻塞等待 ─────────────────────────────

class PendingRequest:
    def __init__(self):
        self.event = threading.Event()
        self.result = None


class RequestRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, PendingRequest] = {}

    def create(self) -> tuple[str, PendingRequest]:
        rid = uuid.uuid4().hex[:12]
        pr = PendingRequest()
        with self._lock:
            self._items[rid] = pr
        return rid, pr

    def resolve(self, rid: str, value) -> bool:
        with self._lock:
            pr = self._items.pop(rid, None)
        if pr is None:
            return False
        pr.result = value
        pr.event.set()
        return True

    def wait(self, pr: PendingRequest, timeout: float):
        pr.event.wait(timeout)
        return pr.result


registry = RequestRegistry()


# ── 回调工厂（Agent 注入）───────────────────────────────────────────────────

def make_clarify_callback(ws_send):
    def _callback(question: str, choices) -> str:
        rid, pr = registry.create()
        ws_send({
            "type": "clarify_request",
            "request_id": rid,
            "question": question,
            "choices": list(choices or []),
        })
        answer = registry.wait(pr, CLARIFY_TIMEOUT)
        if answer is None:
            return (
                "The user did not provide a response within the time limit. "
                "Use your best judgement to make the choice and proceed."
            )
        return answer
    return _callback


def make_approval_callback(ws_send):
    def _callback(tool_name: str, args: dict, description: str) -> str:
        rid, pr = registry.create()
        ws_send({
            "type": "approval_request",
            "request_id": rid,
            "tool_name": tool_name,
            "args": args,
            "description": description,
        })
        answer = registry.wait(pr, APPROVAL_TIMEOUT)
        return answer if answer in ("once", "session", "deny") else "deny"
    return _callback


# ── Kernel: 内核封装 ────────────────────────────────────────────────────────

def install_file_events():
    """包装内核 write_file 工具：成功写文件后推送 file_written 事件（内核零改动）。

    注意：ToolRegistry 在 @register 装饰时保存的是函数对象引用，
    因此必须替换注册表里的 fn，仅改模块属性不生效。
    """
    import tools as tool_registry

    mgr = tool_registry.get_tool_manager()
    entry = mgr._registry.get("write_file")
    if entry is None:
        return
    orig_write = entry["fn"]

    def wrapped_write(path: str, content: str = "", append: bool = False) -> str:
        result = orig_write(path=path, content=content, append=append)
        if result.startswith("Successfully"):
            k = get_kernel()
            sid = k.current_sid or ""
            try:
                resolved = str(Path(path).expanduser().resolve())
            except OSError:
                resolved = str(path)
            manager.send({
                "type": "file_written",
                "session_id": sid,
                "path": resolved,
                "tool": "write_file",
                "ts": time.time(),
            })
        return result

    entry["fn"] = wrapped_write
    # 同步替换模块属性，保持两处引用一致
    import tools.files as tf
    tf.write_file = wrapped_write


def install_compress_events():
    """包装内核 ContextCompressor.compress：压缩开始/结束推事件（内核零改动）。

    压缩是同步阻塞的 LLM 总结（可能耗时数十秒），必须让前端有明确反馈，
    否则用户会以为卡住了。
    """
    agent = get_kernel().agent
    compressor = getattr(agent, "_compressor", None)
    if compressor is None:
        return
    orig_compress = compressor.compress

    def wrapped_compress(history, db=None, session_id=None):
        sid = session_id or get_kernel().current_sid or ""
        manager.send({"type": "compress_start", "session_id": sid})
        try:
            return orig_compress(history, db=db, session_id=session_id)
        finally:
            manager.send({"type": "compress_end", "session_id": sid})

    compressor.compress = wrapped_compress


class Kernel:
    """持有内核单例，提供线程安全的对话编排。"""

    def __init__(self, ws_send):
        self.db = SessionDB()
        self.provider = Provider()
        self.clarify_callback = make_clarify_callback(ws_send)
        self.approval_callback = make_approval_callback(ws_send)
        self.agent = Agent(
            self.provider,
            db=self.db,
            clarify_callback=self.clarify_callback,
            approval_callback=self.approval_callback,
        )
        self._turn_lock = threading.Lock()
        self._ws_send = ws_send
        self.current_sid: str = ""

    # ── 会话 ─────────────────────────────────────────────
    def new_session(self) -> str:
        sid = generate_session_id()
        model = cfg.get_model_config().get("name") or MODEL_NAME
        self.db.create_session(
            sid, model,
            model_config=json.dumps(cfg.get_model_config(), ensure_ascii=False),
            system_prompt=self.agent.system_prompt,
        )
        return sid

    def resume_session(self, sid: str) -> list[dict]:
        return self.db.get_messages(sid)

    def sessions(self) -> list[dict]:
        rows = self.db.list_sessions(limit=50)
        return [session_to_ui(s, self._token_stats(s["id"])) for s in rows]

    def _token_stats(self, sid: str) -> dict:
        """从 messages 表统计 token 消耗（内核的 update_tokens 由 CLI 层调用，
        桌面端绕过后在此处直接统计，避免重复累加）。"""
        try:
            cur = self.db._conn.execute(
                """SELECT
                       COALESCE(SUM(CASE WHEN role IN ('user','tool') THEN token_count ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN role = 'assistant' THEN token_count ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN reasoning IS NOT NULL THEN LENGTH(reasoning) / 4 ELSE 0 END), 0)
                   FROM messages WHERE session_id = ?""",
                (sid,),
            )
            inp, out, reason = cur.fetchone()
            return {
                "input": int(inp or 0),
                "output": int(out or 0),
                "reasoning": int(reason or 0),
                "context_window": self._context_window(),
            }
        except Exception:
            return {"input": 0, "output": 0, "reasoning": 0, "context_window": self._context_window()}

    def _context_window(self) -> int:
        """当前配置的上下文窗口大小（tokens）。"""
        try:
            from context.compressor import CONTEXT_WINDOW
            cw = int(cfg.load().get("context", {}).get("context_window", 0) or 0)
            return cw or int(CONTEXT_WINDOW or 0) or 1000000
        except Exception:
            return 1000000

    def set_title(self, sid: str, title: str):
        self.db.set_title(sid, title)

    def delete_session(self, sid: str):
        self.db.delete_session(sid)

    # ── 对话 ─────────────────────────────────────────────
    def send_message(self, sid: str, content: str) -> dict:
        with self._turn_lock:
            self.current_sid = sid
            history = self.db.get_messages_for_llm(sid)
            renderer = GuiRenderer(self._ws_send, sid)
            self._ws_send({"type": "turn_start", "session_id": sid})
            result = self.agent.run_conversation(
                user_message=content,
                history=history,
                renderer=renderer,
                session_id=sid,
            )
            return {
                "final_response": result.final_response,
                "reasoning": result.reasoning,
                "session_id": result.session_id,
                "compressed": result.compressed,
            }

    # ── Plan 模式：只读规划 + 审批执行（对齐内核 CLI cli/plan.py）────────
    def run_plan(self, sid: str, plan_description: str):
        with self._turn_lock:
            self.current_sid = sid
            renderer = GuiRenderer(self._ws_send, sid)
            self._ws_send({"type": "turn_start", "session_id": sid})
            self._ws_send({"type": "toast", "message": "📋 进入 Plan 模式：正在只读分析并生成方案…"})

            # 构建提示词（与 CLI 的 _execute_plan_mode 一致）
            user_input = (
                f"Create a detailed implementation plan for:\n\n"
                f"{plan_description}\n\n"
                f"Analyze the codebase thoroughly using read-only tools before producing the plan."
            ) if plan_description else (
                "The user wants you to create an implementation plan. "
                "Ask them what they'd like to plan using the clarify tool, "
                "then analyze the codebase and produce a detailed plan."
            )

            # Phase 1: 只读规划 Agent（复用主 Agent 的 provider/回调，只读工具 + plan prompt）
            plan_agent = Agent(
                provider=self.provider,
                db=self.db,
                clarify_callback=self.clarify_callback,
                auto_approve=True,
                tool_filter={"include": PLAN_ALLOWED_TOOLS},
                system_prompt_override=(self.agent.system_prompt or "") + PLAN_MODE_PROMPT,
                max_iterations_override=50,
            )
            try:
                plan_result = plan_agent.run_conversation(
                    user_message=user_input,
                    history=[],
                    renderer=renderer,
                    session_id=sid,
                )
            except Exception as e:
                self._ws_send({"type": "toast", "message": f"⚠ Plan 生成失败: {e}"})
                self._ws_send({"type": "turn_end", "session_id": sid})
                return

            plan_text = plan_result.final_response or "(empty plan)"
            plan_path = str(generate_plan_path(plan_description or "plan"))
            try:
                Path(plan_path).write_text(plan_text, encoding="utf-8")
            except Exception:
                pass
            self._ws_send({"type": "toast", "message": f"📄 方案已保存: {plan_path}"})

            # Phase 2: 审批（复用 RequestRegistry 阻塞等待，前端弹窗选择）
            rid, pr = registry.create()
            self._ws_send({
                "type": "plan_approval_request",
                "request_id": rid,
                "plan_text": plan_text[:6000],
                "plan_path": plan_path,
            })
            choice = registry.wait(pr, PLAN_TIMEOUT)
            if choice != "execute":
                self._ws_send({"type": "toast", "message": "✋ 已取消执行方案。"})
                self._ws_send({"type": "turn_end", "session_id": sid})
                return

            # Phase 3: 执行（注入方案，走主 Agent）
            self._ws_send({"type": "toast", "message": "▶ 已批准，开始执行方案…"})
            exec_message = (
                f"Execute the following approved implementation plan. "
                f"Implement each step in order using the appropriate tools.\n\n"
                f"---\n{plan_text}\n---"
            )
            history = self.db.get_messages_for_llm(sid)
            result = self.agent.run_conversation(
                user_message=exec_message,
                history=history,
                renderer=renderer,
                session_id=sid,
            )
            return {
                "final_response": result.final_response,
                "reasoning": result.reasoning,
                "session_id": result.session_id,
                "compressed": result.compressed,
            }

    def interrupt(self):
        self.agent.interrupt()

    # ── 成果文件 ─────────────────────────────────────────
    def session_files(self, sid: str) -> list[dict]:
        """从 DB 消息推导该会话生成的文件列表（仅统计成功的 write_file）。

        通过 assistant.tool_calls 里的 arguments.path 拿到目标路径，
        再匹配对应的 tool 结果消息确认写入成功。
        """
        files: list[dict] = []
        seen: set[str] = set()
        pending: dict[str, str] = {}  # tool_call_id -> resolved path
        for m in self.db.get_messages(sid):
            role = m.get("role")
            if role == "assistant":
                for tc in (m.get("tool_calls") or []):
                    fn = (tc.get("function") or {}).get("name")
                    if fn in WRITE_TOOLS:
                        try:
                            args = json.loads((tc["function"] or {}).get("arguments") or "{}")
                        except (json.JSONDecodeError, KeyError):
                            continue
                        p = args.get("path")
                        if p:
                            try:
                                pending[tc.get("id", "")] = str(Path(p).expanduser().resolve())
                            except OSError:
                                pending[tc.get("id", "")] = str(p)
            elif role == "tool" and m.get("tool_name") in WRITE_TOOLS:
                content = m.get("content") or ""
                if content.startswith("Successfully"):
                    p = pending.pop(m.get("tool_call_id", ""), None)
                    if p and p not in seen:
                        seen.add(p)
                        files.append({"path": p, "tool": m.get("tool_name", "write_file")})
        return files


kernel: Kernel | None = None


def get_kernel() -> Kernel:
    global kernel
    if kernel is None:
        kernel = Kernel(ws_send=manager.send)
        # 启动时同步内置技能（幂等）
        try:
            sync_builtin_skills()
        except Exception:
            pass
        # 包装写文件工具，推送成果文件事件
        try:
            install_file_events()
        except Exception as e:
            print(f"[warn] install_file_events failed: {e}", flush=True)
        # 包装上下文压缩，推送开始/结束事件
        try:
            install_compress_events()
        except Exception as e:
            print(f"[warn] install_compress_events failed: {e}", flush=True)
    return kernel


# ── WS 消息处理 ─────────────────────────────────────────────────────────────

async def handle_ws_message(data: dict):
    msg_type = data.get("type")
    k = get_kernel()

    if msg_type == "send_message":
        sid = data.get("session_id")
        content = data.get("content", "")
        if not sid or not content:
            manager.send({"type": "error", "message": "缺少 session_id 或 content"})
            return
        # @file: 引用展开（复用内核 cli/context_ref 能力）
        try:
            from cli.context_ref import preprocess as expand_file_refs
            ref_result = expand_file_refs(content, cwd=Path.cwd())
            content = ref_result.message
            if ref_result.warnings:
                manager.send({"type": "toast", "message": "；".join(ref_result.warnings)})
        except Exception:
            pass
        # Plan 模式：前端模式开关为 Plan 时自动注入 __PLAN_MODE__: 前缀
        if content.startswith(PLAN_MODE_PREFIX):
            plan_desc = content[len(PLAN_MODE_PREFIX):]
            def _run_plan(sid, desc):
                try:
                    result = k.run_plan(sid, desc)
                    if result:  # 执行分支正常结束后由这里发 turn_end
                        manager.send({
                            "type": "turn_end",
                            "session_id": result["session_id"],
                            "final_response": result["final_response"],
                            "reasoning": result["reasoning"],
                            "compressed": result["compressed"],
                        })
                        manager.send({"type": "sessions", "sessions": get_kernel().sessions()})
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    manager.send({"type": "error", "message": f"{type(e).__name__}: {e}"})
            threading.Thread(target=_run_plan, args=(sid, plan_desc), daemon=True).start()
        else:
            threading.Thread(
                target=run_turn, args=(sid, content), daemon=True
            ).start()

    elif msg_type == "command":
        raw = data.get("cmd", "")
        parts = raw.strip().split(None, 1)
        cmd = (parts[0] or "").lower()
        arg = parts[1] if len(parts) > 1 else ""
        sid = data.get("session_id") or k.current_sid or ""
        if not cmd.startswith("/"):
            manager.send({"type": "command_result", "text": f"[invalid command: {cmd}]"})
        elif not handle_backend_command(k, cmd, arg, sid):
            manager.send({
                "type": "command_result",
                "text": f"[unknown command: {cmd}. 输入 /help 查看可用命令]",
            })

    elif msg_type == "interrupt":
        k.interrupt()
        # 立即回发确认，前端收到即可给出"正在停止"反馈，无需等 turn_end
        manager.send({"type": "interrupted", "session_id": k.current_sid or data.get("session_id", "")})

    elif msg_type == "clarify_answer":
        registry.resolve(data.get("request_id", ""), data.get("answer"))

    elif msg_type == "approval_answer":
        registry.resolve(data.get("request_id", ""), data.get("answer"))

    elif msg_type == "plan_approval_answer":
        # Plan 审批：answer ∈ {"execute", "cancel"}
        registry.resolve(data.get("request_id", ""), data.get("answer"))

    elif msg_type == "new_session":
        sid = k.new_session()
        manager.send({"type": "session_created", "session_id": sid})
        manager.send({"type": "sessions", "sessions": k.sessions()})

    elif msg_type == "resume_session":
        sid = data.get("session_id", "")
        messages = k.resume_session(sid)
        manager.send({
            "type": "session_messages",
            "session_id": sid,
            "messages": messages,
        })

    elif msg_type == "refresh_sessions":
        manager.send({"type": "sessions", "sessions": k.sessions()})


def run_turn(sid: str, content: str):
    """在后台线程中执行一轮对话。"""
    try:
        result = get_kernel().send_message(sid, content)
        manager.send({
            "type": "turn_end",
            "session_id": result["session_id"],
            "final_response": result["final_response"],
            "reasoning": result["reasoning"],
            "compressed": result["compressed"],
        })
        manager.send({"type": "sessions", "sessions": get_kernel().sessions()})
    except Exception as e:
        import traceback
        traceback.print_exc()
        manager.send({"type": "error", "message": f"{type(e).__name__}: {e}"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data)
    except WebSocketDisconnect:
        await manager.disconnect()
    except Exception:
        await manager.disconnect()


# ── HTTP API ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/sessions")
def api_sessions():
    return {"sessions": get_kernel().sessions()}


@app.post("/api/sessions")
def api_new_session():
    sid = get_kernel().new_session()
    return {"session_id": sid, "sessions": get_kernel().sessions()}


@app.get("/api/sessions/{sid}/messages")
def api_session_messages(sid: str):
    return {"messages": get_kernel().resume_session(sid)}


@app.get("/api/sessions/{sid}/files")
def api_session_files(sid: str):
    return {"files": get_kernel().session_files(sid)}


class TitleBody(BaseModel):
    title: str


@app.post("/api/sessions/{sid}/title")
def api_set_title(sid: str, body: TitleBody):
    get_kernel().set_title(sid, body.title)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def api_delete_session(sid: str):
    get_kernel().delete_session(sid)
    return {"ok": True, "sessions": get_kernel().sessions()}


# ── 配置 ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def api_get_config():
    return cfg.load()


class ConfigBody(BaseModel):
    model: dict | None = None
    search: dict | None = None
    code_execution: dict | None = None
    evolution: dict | None = None
    general: dict | None = None


@app.post("/api/config")
def api_set_config(body: ConfigBody):
    """浅合并写入 ~/.minihermes/config.yaml。"""
    data = {}
    if CONFIG_PATH.exists():
        import yaml
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    for key in ("model", "search", "code_execution", "evolution", "general"):
        value = getattr(body, key)
        if value is not None:
            data[key] = value
    import yaml
    CONFIG_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "config": data}


# ── 工作目录（cwd）─────────────────────────────────────────────────────────

@app.get("/api/cwd")
def api_get_cwd():
    """返回当前内核进程的工作目录。"""
    return {"cwd": os.getcwd()}


class CwdBody(BaseModel):
    path: str


@app.post("/api/cwd")
def api_set_cwd(body: CwdBody):
    """切换内核工作目录：os.chdir 全局生效（工具/上下文文件/相对路径都跟随），
    同时持久化到 config.yaml 的 general.cwd，下次启动恢复。"""
    target = str(Path(body.path).expanduser().resolve())
    if not os.path.isdir(target):
        return {"ok": False, "error": f"目录不存在: {target}"}
    try:
        os.chdir(target)
    except OSError as e:
        return {"ok": False, "error": f"切换失败: {e}"}

    # 持久化到 config.yaml general.cwd（浅合并，保留其他字段）
    try:
        data = {}
        if CONFIG_PATH.exists():
            import yaml
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        general = data.get("general") or {}
        general["cwd"] = target
        data["general"] = general
        import yaml
        CONFIG_PATH.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 持久化失败不影响本次切换

    return {"ok": True, "cwd": os.getcwd()}


# ── 用户记忆（USER.md / MEMORY.md）─────────────────────────────────────────

class MemoryBody(BaseModel):
    user: str | None = None
    project: str | None = None


@app.get("/api/memory")
def api_get_memory():
    def _read(p: Path) -> str:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return {"user": _read(USER_MEMORY_FILE), "project": _read(PROJECT_MEMORY_FILE)}


@app.post("/api/memory")
def api_set_memory(body: MemoryBody):
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if body.user is not None:
        USER_MEMORY_FILE.write_text(body.user, encoding="utf-8")
    if body.project is not None:
        PROJECT_MEMORY_FILE.write_text(body.project, encoding="utf-8")
    return {"ok": True}


# ── 技能 ────────────────────────────────────────────────────────────────────

@app.get("/api/skills")
def api_list_skills():
    try:
        skills = discover_skills()
    except Exception as e:
        return {"skills": [], "error": str(e)}
    items = []
    for s in skills:
        items.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "version": s.get("version", ""),
            "path": s.get("path", ""),
        })
    return {"skills": items}


@app.get("/api/skills/{name}")
def api_get_skill(name: str):
    try:
        info = load_skill_structured(name)
        return {"skill": info}
    except Exception as e:
        return {"skill": None, "error": str(e)}


# ── 工具信息 ────────────────────────────────────────────────────────────────

@app.get("/api/tools")
def api_list_tools():
    try:
        schemas = tool_registry.get_schemas()
        return {"tools": [s.get("function", {}).get("name") for s in schemas]}
    except Exception as e:
        return {"tools": [], "error": str(e)}


# ── 斜杠命令 ────────────────────────────────────────────────────────

@app.get("/api/commands")
def api_list_commands():
    items = [dict(c) for c in BUILTIN_COMMANDS]
    try:
        for skill in discover_skills():
            name = skill.get("name", "")
            if not name:
                continue
            items.append({
                "cmd": f"/{name}",
                "desc": f"[技能] {skill.get('description', '')[:60]}",
                "has_arg": False,
                "action": "skill",
            })
    except Exception:
        pass
    return {"commands": items}


def handle_backend_command(kernel: Kernel, cmd: str, arg: str, sid: str) -> bool:
    """处理需要内核能力的命令。返回 True 表示已处理。"""
    if cmd == "/compress":
        kernel.agent.request_compress()
        manager.send({"type": "command_result", "text": "[manual compression triggered — will execute on next LLM call]"})
        return True

    if cmd == "/title":
        if not arg:
            manager.send({"type": "command_result", "text": "[usage: /title <name>]"})
        else:
            kernel.set_title(sid, arg.strip()[:100])
            manager.send({"type": "command_result", "text": f"[session titled: {arg.strip()[:100]}]"})
            manager.send({"type": "sessions", "sessions": kernel.sessions()})
        return True

    if cmd == "/sysprompt":
        sp = kernel.agent.system_prompt or ""
        manager.send({
            "type": "command_result",
            "text": f"── system prompt ({len(sp)} chars, ~{len(sp) // 4} tokens) ──\n\n{sp}",
        })
        return True

    if cmd == "/init":
        try:
            from cli.commands import _INIT_INSTRUCTION
            threading.Thread(target=run_turn, args=(sid, _INIT_INSTRUCTION), daemon=True).start()
        except Exception as e:
            manager.send({"type": "command_result", "text": f"[init failed: {e}]"})
        return True

    # 技能命令：/<skill-name> [arg]
    skill_name = cmd.lstrip("/")
    try:
        skill_info = load_skill_structured(skill_name)
    except Exception:
        skill_info = None
    if skill_info:
        lines = [
            f"[IMPORTANT: The user has invoked the '{skill_name}' skill. "
            "Follow the instructions below unless the user asks otherwise.]",
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
        threading.Thread(target=run_turn, args=(sid, "\n".join(lines)), daemon=True).start()
        return True

    return False


# ── 入口 ────────────────────────────────────────────────────────────────────

def main():
    # 绑定随机端口并持有 socket，避免 find-free-then-bind 竞态
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    print(json.dumps({"port": port}), flush=True)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets",
    )
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
