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

仅 import minihermes.core.*（+ 自身 gui_renderer），永不 import minihermes.cli。
"""

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import minihermes.core.config as cfg
from minihermes.core import tools as tool_registry
from minihermes.core.provider import Provider, test_provider_connection
from minihermes.core.provider.provider import MODEL_NAME
from minihermes.core.agent.agent import Agent
from minihermes.core.agent.runtime_ctx import (
    set_current_sid as runtime_set_sid,
    current_sid as runtime_current_sid,
    set_current_cwd as runtime_set_cwd,
    current_cwd as runtime_current_cwd,
)
from minihermes.core.session import SessionDB
from minihermes.core.skills import discover_skills, load_skill_structured, sync_builtin_skills
from minihermes.core.services.commands import (
    BUILTIN_COMMANDS, _INIT_INSTRUCTION, build_skill_activation_message,
)
from minihermes.core.services.context_ref import preprocess as expand_file_refs
from minihermes.core.services.session_service import generate_session_id, list_sessions_ui
from minihermes.core.personas import get_persona_registry, manifest_to_dict

from gui_renderer import GuiRenderer

MINIHERMES_HOME = Path.home() / ".minihermes"
CONFIG_PATH = MINIHERMES_HOME / "config.yaml"
MEMORY_DIR = MINIHERMES_HOME / "memory"
USER_MEMORY_FILE = MEMORY_DIR / "USER.md"
PROJECT_MEMORY_FILE = MEMORY_DIR / "MEMORY.md"

# 「默认」工作目录 = 应用后端进程启动时的初始目录（早于任何 restore-chdir）。
# 首次启动快照存入 config general.default_cwd；侧栏会话按 cwd 分组时，
# cwd == default_cwd（或未绑定 cwd）的会话归「默认」组。
DEFAULT_CWD: str = os.getcwd()

# 成果面板关注的写文件工具
WRITE_TOOLS = ("write_file",)

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
        # rid -> (sid, PendingRequest)。rid 全局唯一，多会话并发时归属仍可解析。
        self._items: dict[str, tuple[str, PendingRequest]] = {}

    def create(self, sid: str = "") -> tuple[str, PendingRequest]:
        rid = uuid.uuid4().hex[:12]
        pr = PendingRequest()
        with self._lock:
            self._items[rid] = (sid, pr)
        return rid, pr

    def resolve_all_for_sid(self, sid: str):
        """会话删除时清理其全部 pending 请求（置 None 返回默认值）。"""
        with self._lock:
            for rid, (rsid, pr) in list(self._items.items()):
                if rsid == sid:
                    self._items.pop(rid, None)
                    pr.result = None
                    pr.event.set()

    def resolve(self, rid: str, value) -> bool:
        with self._lock:
            entry = self._items.pop(rid, None)
        if entry is None:
            return False
        pr = entry[1]
        pr.result = value
        pr.event.set()
        return True

    def wait(self, pr: PendingRequest, timeout: float):
        pr.event.wait(timeout)
        return pr.result


registry = RequestRegistry()


# ── 回调工厂（Agent 注入，按会话）───────────────────────────────────────────

def make_callbacks(ws_send, sid: str) -> tuple:
    """构造绑定到指定会话的 clarify / approval 回调。

    事件带 session_id 供前端按会话路由；pending 请求按会话登记，
    多会话并发时归属互不混淆（answer 仍按全局唯一 request_id 解析）。
    """
    def _clarify(question: str, choices) -> str:
        rid, pr = registry.create(sid=sid)
        ws_send({
            "type": "clarify_request",
            "session_id": sid,
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

    def _approval(tool_name: str, args: dict, description: str) -> str:
        rid, pr = registry.create(sid=sid)
        ws_send({
            "type": "approval_request",
            "session_id": sid,
            "request_id": rid,
            "tool_name": tool_name,
            "args": args,
            "description": description,
        })
        answer = registry.wait(pr, APPROVAL_TIMEOUT)
        return answer if answer in ("once", "session", "deny") else "deny"

    return _clarify, _approval


# ── Kernel: 内核封装 ────────────────────────────────────────────────────────

def install_file_events():
    """包装内核 write_file 工具：成功写文件后推送 file_written 事件（内核零改动）。

    注意：ToolRegistry 在 @register 装饰时保存的是函数对象引用，
    因此必须替换注册表里的 fn，仅改模块属性不生效。
    """
    mgr = tool_registry.get_tool_manager()
    entry = mgr._registry.get("write_file")
    if entry is None:
        return
    orig_write = entry["fn"]

    def wrapped_write(path: str, content: str = "", append: bool = False) -> str:
        result = orig_write(path=path, content=content, append=append)
        if result.startswith("Successfully"):
            # 多会话并行：写文件发生在某会话的 turn 线程内，thread-local 归因到正确会话
            sid = runtime_current_sid() or get_kernel().current_sid or ""
            try:
                # 相对路径按会话绑定目录（thread-local cwd）解析，与工具层 _resolve_path 一致
                base = runtime_current_cwd() or os.getcwd()
                resolved = str((Path(base) / Path(path).expanduser()).resolve())
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
    import minihermes.core.tools.files as tf
    tf.write_file = wrapped_write


def install_compress_events_on(agent: Agent):
    """包装某 Agent 的 ContextCompressor.compress：压缩开始/结束推事件（内核零改动）。

    压缩是同步阻塞的 LLM 总结（可能耗时数十秒），必须让前端有明确反馈，
    否则用户会以为卡住了。每会话 Agent 各自的压缩器单独包装（多会话并行时
    事件归因到正确会话）。
    """
    compressor = getattr(agent, "_compressor", None)
    if compressor is None:
        return
    orig_compress = compressor.compress

    def wrapped_compress(history, db=None, session_id=None):
        sid = session_id or runtime_current_sid() or get_kernel().current_sid or ""
        manager.send({"type": "compress_start", "session_id": sid})
        try:
            return orig_compress(history, db=db, session_id=session_id)
        finally:
            manager.send({"type": "compress_end", "session_id": sid})

    compressor.compress = wrapped_compress


# 每会话运行时上限（LRU 淘汰，防无限增长；丢内存态、DB 重建语义正确）
MAX_RUNTIMES = 32


class SessionRuntime:
    """一个会话的独立运行时：专属 Agent + 专属会话锁 + persona。

    不同会话的 runtime 各自持锁、并行跑对话；同一会话串行（一轮对话中
    重复 send 会在会话锁上排队——前端已阻止 busy 会话发消息，这里只是兜底）。
    """

    def __init__(self, sid: str, kernel: "Kernel", persona_id: str = ""):
        self.sid = sid
        self.kernel = kernel
        self.lock = threading.Lock()
        self.persona_id = persona_id or ""   # 该会话 DB 绑定的 persona（幂等判断用）
        self.busy = False
        self.deleted = False
        self.last_turn_ts = 0.0
        self._agent: Agent | None = None
        # 会话绑定 cwd 缓存（DB 是唯一事实源；refresh_cwd 后重读）
        self._cwd: str | None = None
        self._cwd_loaded = False

    def _session_cwd(self) -> str:
        """懒读取该会话绑定的工作目录（DB 事实源）。无绑定（CLI 会话）返回 ""。"""
        if not self._cwd_loaded:
            self._cwd = self.kernel.db.get_session_cwd(self.sid) or ""
            self._cwd_loaded = True
        return self._cwd or ""

    def refresh_cwd(self):
        """重绑定后清缓存，下次读取按新目录。"""
        self._cwd_loaded = False

    def ensure_agent(self) -> Agent:
        """懒创建本会话的 Agent；DB persona 变化时幂等重新应用。"""
        pid = self.kernel.db.get_persona(self.sid) or ""
        cwd = self._session_cwd()
        if self._agent is None:
            clarify, approval = self.kernel.callbacks_for(self.sid)
            manifest = get_persona_registry().resolve(pid) if pid else None
            self._agent = Agent(
                self.kernel.provider,
                db=self.kernel.db,
                clarify_callback=clarify,
                approval_callback=approval,
                persona=manifest,
                cwd=cwd or None,
            )
            install_compress_events_on(self._agent)
        elif pid != self.persona_id:
            manifest = get_persona_registry().resolve(pid) if pid else None
            self._agent.apply_persona(manifest)
        # cwd-drift 守卫：runtime 的 agent 在旧目录构建过（重绑定/自动切换后）→ 重刷 prompt
        if cwd and self._agent.cwd != cwd:
            self._agent.reload_system_prompt(cwd=cwd)
        self.persona_id = pid
        return self._agent

    def run_turn(self, content: str, thinking_effort: str | None = None):
        with self.lock:
            self.busy = True
            runtime_set_sid(self.sid)
            runtime_set_cwd(self._session_cwd())
            try:
                if self.deleted:
                    return None
                agent = self.ensure_agent()
                history = self.kernel.db.get_messages_for_llm(self.sid)
                renderer = GuiRenderer(self.kernel._ws_send, self.sid)
                self.kernel._ws_send({"type": "turn_start", "session_id": self.sid})
                result = agent.run_conversation(
                    user_message=content,
                    history=history,
                    renderer=renderer,
                    session_id=self.sid,
                    thinking_effort=thinking_effort,
                )
                return {
                    "final_response": result.final_response,
                    "reasoning": result.reasoning,
                    "session_id": result.session_id,
                    "compressed": result.compressed,
                }
            finally:
                self.busy = False
                self.last_turn_ts = time.time()
                runtime_set_sid("")
                runtime_set_cwd("")

    def interrupt(self):
        if self._agent is not None:
            self._agent.interrupt()


class Kernel:
    """持有内核单例：每会话一个运行时（Agent/锁），支持多会话并行对话。"""

    def __init__(self, ws_send):
        self.db = SessionDB()
        self.provider = Provider()
        self._ws_send = ws_send
        self._runtimes: OrderedDict[str, SessionRuntime] = OrderedDict()
        self._runtime_lock = threading.Lock()  # 只保护 _runtimes 字典
        self._last_sid = ""
        # 模板 Agent：仅供 new_session 取默认 system_prompt 与兼容属性，不参与任何 turn
        self._template_agent = Agent(
            self.provider,
            db=self.db,
            clarify_callback=lambda *a, **kw: "cancel",
            approval_callback=lambda *a, **kw: "deny",
        )

    # ── 兼容 shim（tests/test_desktop_personas.py 依赖 kernel.agent）─────────
    @property
    def agent(self) -> Agent:
        rt = self._runtimes.get(self._last_sid)
        if rt is not None:
            return rt.ensure_agent()
        return self._template_agent

    @property
    def current_sid(self) -> str:
        return self._last_sid

    @current_sid.setter
    def current_sid(self, v: str):
        if v:
            self._last_sid = v

    def callbacks_for(self, sid: str) -> tuple:
        return make_callbacks(self._ws_send, sid)

    # ── 运行时管理 ─────────────────────────────────────────
    def _get_or_create_runtime(self, sid: str) -> SessionRuntime:
        with self._runtime_lock:
            rt = self._runtimes.get(sid)
            if rt is None:
                rt = SessionRuntime(sid, self)
                self._runtimes[sid] = rt
                self._evict_runtimes_locked()
            self._runtimes.move_to_end(sid)
            self._last_sid = sid
            return rt

    def _evict_runtimes_locked(self):
        while len(self._runtimes) > MAX_RUNTIMES:
            for k, rt in list(self._runtimes.items()):
                if not rt.busy:
                    self._runtimes.pop(k, None)
                    break
            else:
                break  # 全部 busy，放弃淘汰

    def runtime_agent(self, sid: str) -> Agent:
        rt = self._runtimes.get(sid)
        return rt.ensure_agent() if rt is not None else self._template_agent

    def any_busy(self) -> bool:
        return any(rt.busy for rt in self._runtimes.values())

    # ── 配置生效 ─────────────────────────────────────────
    def rebuild_provider(self):
        """按当前配置重建 Provider 并应用到所有运行时（配置保存后调用，立即生效）。

        Provider 构造在缺 key 时也成功（stream 时才报错），因此
        即使激活厂商未配 key，重建也不会抛异常，旧对话照常保留。
        """
        cfg.reload_config()
        self.provider = Provider()
        self._template_agent.switch_provider(self.provider)
        with self._runtime_lock:
            for rt in self._runtimes.values():
                if rt._agent is not None:
                    rt._agent.switch_provider(self.provider)

    # ── 会话 ─────────────────────────────────────────────
    def new_session(self, persona_id: str = "") -> str:
        sid = generate_session_id()
        model = cfg.get_model_config().get("name") or MODEL_NAME
        # 新会话绑定当前选定工作目录（os.chdir 导航后的进程 cwd）
        self.db.create_session(
            sid, model,
            model_config=json.dumps(cfg.get_model_config(), ensure_ascii=False),
            system_prompt=self._template_agent.system_prompt,
            persona_id=persona_id or None,
            cwd=os.getcwd(),
        )
        return sid

    def _apply_persona_for_session(self, sid: str):
        """按会话懒应用专家（委托该会话的 runtime，幂等，per-session Agent 上切换）。"""
        self._get_or_create_runtime(sid).ensure_agent()

    def resume_session(self, sid: str) -> list[dict]:
        return self.db.get_messages(sid)

    def sessions(self) -> list[dict]:
        return list_sessions_ui(self.db, limit=50)

    def set_title(self, sid: str, title: str):
        self.db.set_title(sid, title)

    def delete_session(self, sid: str):
        """删除会话：中断在途 turn 并抑制其后续事件。"""
        with self._runtime_lock:
            rt = self._runtimes.pop(sid, None)
        if rt is not None:
            rt.deleted = True
            rt.interrupt()
            registry.resolve_all_for_sid(sid)
        self.db.delete_session(sid)

    # ── 对话 ─────────────────────────────────────────────
    def send_message(self, sid: str, content: str, thinking_effort: str | None = None) -> dict:
        rt = self._get_or_create_runtime(sid)
        return rt.run_turn(content, thinking_effort=thinking_effort)

    def interrupt(self, sid: str = ""):
        """定向中断指定会话（前端必带 session_id）。"""
        rt = self._runtimes.get(sid or self._last_sid)
        if rt is not None:
            rt.interrupt()

    # ── 成果文件 ─────────────────────────────────────────
    def session_files(self, sid: str) -> list[dict]:
        """从 DB 消息推导该会话生成的文件列表（仅统计成功的 write_file）。

        通过 assistant.tool_calls 里的 arguments.path 拿到目标路径，
        再匹配对应的 tool 结果消息确认写入成功。
        """
        files: list[dict] = []
        seen: set[str] = set()
        pending: dict[str, str] = {}  # tool_call_id -> resolved path
        # 相对路径按会话绑定目录锚定（DB 事实源），与工具层执行目录一致
        base = self.db.get_session_cwd(sid) or os.getcwd()
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
                                pending[tc.get("id", "")] = str((Path(base) / Path(p).expanduser()).resolve())
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
    global kernel, DEFAULT_CWD
    if kernel is None:
        # 「默认」目录 = 首次启动时的工作目录（restore-chdir 之前，早于任何恢复）。
        # 首次启动快照持久化到 general.default_cwd；后续启动沿用持久化值。
        try:
            _general = cfg.load().get("general") or {}
            if "default_cwd" not in _general:
                _save_general_key("default_cwd", DEFAULT_CWD)
            else:
                DEFAULT_CWD = _general["default_cwd"]
        except Exception:
            pass
        # 启动时恢复上次保存的工作目录（general.cwd）
        try:
            _saved_cwd = cfg.load().get("general", {}).get("cwd")
            if _saved_cwd and os.path.isdir(_saved_cwd):
                os.chdir(_saved_cwd)
        except Exception:
            pass
        kernel = Kernel(ws_send=manager.send)
        # 启动时同步内置技能（幂等）
        try:
            sync_builtin_skills()
        except Exception:
            pass
        # 包装写文件工具，推送成果文件事件（压缩事件在每会话 Agent 上单独包装）
        try:
            install_file_events()
        except Exception as e:
            print(f"[warn] install_file_events failed: {e}", flush=True)
    return kernel


# ── 工作目录工具 ─────────────────────────────────────────────────────────────

def _save_general_key(key: str, value) -> bool:
    """浅合并写入 config.yaml 的 general.<key>（保留其他字段），失败静默返回 False。"""
    try:
        import yaml
        data = {}
        if CONFIG_PATH.exists():
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        general = data.get("general") or {}
        general[key] = value
        data["general"] = general
        CONFIG_PATH.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _switch_cwd(kernel: Kernel, target: str, *, persist: bool = True,
                reload_template: bool = True, notify: bool = False) -> tuple[bool, str]:
    """切换内核进程工作目录：导航（os.chdir）+ 持久化 + 重建模板 agent 系统提示。

    注意：os.chdir 只改变进程全局 cwd（= 导航 + 新会话默认目录）。
    各会话 runtime 保持各自绑定目录，其 prompt 由 cwd-drift 守卫按需重建，
    在途 turn 的 bash/files/@file 全走 thread-local cwd，对 chdir 不可见。

    返回 (ok, error_or_cwd)。
    """
    target = str(Path(target).expanduser().resolve())
    if not os.path.isdir(target):
        return False, f"目录不存在: {target}"
    try:
        os.chdir(target)
    except OSError as e:
        return False, f"切换失败: {e}"
    if persist:
        _save_general_key("cwd", target)
    if reload_template:
        try:
            kernel._template_agent.reload_system_prompt(cwd=target)
        except Exception:
            pass  # 重建失败不影响导航本身
    if notify:
        manager.send({
            "type": "cwd_changed",
            "cwd": os.getcwd(),
            "default_cwd": DEFAULT_CWD,
        })
    return True, os.getcwd()


# ── WS 消息处理 ─────────────────────────────────────────────────────────────

async def handle_ws_message(data: dict):
    msg_type = data.get("type")
    k = get_kernel()

    if msg_type == "send_message":
        sid = data.get("session_id")
        content = data.get("content", "")
        thinking_effort = data.get("thinking_effort")  # 对话窗口思考强度选择器（可选）
        if not sid or not content:
            manager.send({"type": "error", "message": "缺少 session_id 或 content", "session_id": sid or ""})
            return
        # @file: 引用展开（复用内核 core/services.context_ref 能力）——
        # 按会话绑定目录锚定相对引用（DB 事实源），而非进程全局 cwd
        try:
            ref_result = expand_file_refs(content, cwd=Path(k.db.get_session_cwd(sid) or os.getcwd()))
            content = ref_result.message
            if ref_result.warnings:
                manager.send({"type": "toast", "message": "；".join(ref_result.warnings), "session_id": sid})
        except Exception:
            pass
        threading.Thread(
            target=run_turn, args=(sid, content, thinking_effort), daemon=True
        ).start()

    elif msg_type == "command":
        raw = data.get("cmd", "")
        parts = raw.strip().split(None, 1)
        cmd = (parts[0] or "").lower()
        arg = parts[1] if len(parts) > 1 else ""
        sid = data.get("session_id") or k.current_sid or ""
        if not cmd.startswith("/"):
            manager.send({"type": "command_result", "session_id": sid, "text": f"[invalid command: {cmd}]"})
        elif not handle_backend_command(k, cmd, arg, sid):
            manager.send({
                "type": "command_result",
                "session_id": sid,
                "text": f"[unknown command: {cmd}. 输入 /help 查看可用命令]",
            })

    elif msg_type == "interrupt":
        sid = data.get("session_id") or k.current_sid or ""
        k.interrupt(sid)
        # 立即回发确认，前端收到即可给出"正在停止"反馈，无需等 turn_end
        manager.send({"type": "interrupted", "session_id": sid})

    elif msg_type == "clarify_answer":
        registry.resolve(data.get("request_id", ""), data.get("answer"))

    elif msg_type == "approval_answer":
        registry.resolve(data.get("request_id", ""), data.get("answer"))

    elif msg_type == "new_session":
        persona_id = data.get("persona_id") or ""
        sid = k.new_session(persona_id=persona_id)
        manager.send({
            "type": "session_created",
            "session_id": sid,
            "persona_id": persona_id,
        })
        manager.send({"type": "sessions", "sessions": k.sessions()})

    elif msg_type == "resume_session":
        sid = data.get("session_id", "")
        # 导航自动切换：打开其他目录的会话 → 先把进程 cwd 切到该会话绑定目录。
        # 导航行为，不受守卫 A（消息数）限制；在途 turn 的 bash/files/@file 全走
        # thread-local cwd，进程级 chdir 对其不可见，安全。cwd_changed 先于
        # session_messages 到达，前端按序处理。
        try:
            bound = k.db.get_session_cwd(sid)
            if bound and os.path.isdir(bound) and os.path.normpath(bound) != os.path.normpath(os.getcwd()):
                _switch_cwd(k, bound, persist=True, reload_template=True, notify=True)
        except Exception:
            pass  # 绑定目录缺失/切换失败不阻断打开会话
        messages = k.resume_session(sid)
        rt = k._get_or_create_runtime(sid)
        try:
            rt.ensure_agent()  # cwd-drift 守卫：用绑定目录重建 prompt（不触发 LLM）
        except Exception:
            pass
        manager.send({
            "type": "session_messages",
            "session_id": sid,
            "messages": messages,
            "persona_id": k.db.get_persona(sid) or "",
            "busy": bool(rt and rt.busy),
        })

    elif msg_type == "refresh_sessions":
        manager.send({"type": "sessions", "sessions": k.sessions()})


def run_turn(sid: str, content: str, thinking_effort: str | None = None):
    """在后台线程中执行一轮对话。thinking_effort 为对话窗口每轮选择的思考强度覆盖。"""
    try:
        result = get_kernel().send_message(sid, content, thinking_effort=thinking_effort)
        if result is None:  # 会话已被删除，抑制事件
            return
        manager.send({
            "type": "turn_end",
            "session_id": result["session_id"],
            "orig_session_id": sid,  # 压缩切新会话时前端据此迁移 bucket
            "final_response": result["final_response"],
            "reasoning": result["reasoning"],
            "compressed": result["compressed"],
        })
        manager.send({"type": "sessions", "sessions": get_kernel().sessions()})
    except Exception as e:
        import traceback
        traceback.print_exc()
        manager.send({"type": "error", "message": f"{type(e).__name__}: {e}", "session_id": sid})


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


class NewSessionBody(BaseModel):
    persona_id: str | None = None


@app.post("/api/sessions")
def api_new_session(body: NewSessionBody = None):
    persona_id = (body.persona_id or "") if body else ""
    sid = get_kernel().new_session(persona_id=persona_id)
    return {
        "session_id": sid,
        "persona_id": persona_id,
        "sessions": get_kernel().sessions(),
    }


@app.get("/api/personas")
def api_personas():
    """返回全部可用专家（含团队元数据），供右侧专家面板渲染。"""
    try:
        personas = [manifest_to_dict(m) for m in get_persona_registry().list()]
        return {"personas": personas}
    except Exception as e:
        return {"personas": [], "error": str(e)}


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


@app.get("/api/providers")
def api_get_providers():
    """返回预设厂商信息 + 当前激活 + 各厂商已配置状态（不回明文 key）。

    供设置页渲染厂商下拉 / 模型候选 / 上下文与思考强度默认值。
    """
    from minihermes.core.provider import (
        provider_names, get_preset, THINKING_EFFORT_LEVELS, validate_thinking_effort,
    )
    data = cfg.load()
    active = data.get("provider", {}).get("active") or (provider_names()[0] if provider_names() else "deepseek")
    if active not in provider_names():
        active = provider_names()[0] if provider_names() else "deepseek"
    plist = data.get("provider", {}).get("list", {})

    providers = []
    for name in provider_names():
        preset = get_preset(name)
        if preset is None:
            continue
        overrides = plist.get(name) or {}
        has_key = bool(overrides.get("api_key")) or bool(
            preset.env_key and os.environ.get(preset.env_key)
        )
        providers.append({
            "name": name,
            "title": preset.title,
            "base_url": overrides.get("base_url") or preset.base_url,
            # 每项带预设上下文窗口，供设置页模型列表标注（CLI 用 model_ids_for 不受影响）
            "models": [{"id": m.id, "context_window": m.context_window} for m in preset.models],
            "model": overrides.get("model") or preset.default_model,
            "context_window": int(overrides.get("context_window") or 0) or preset.default_context_window,
            "thinking_effort": validate_thinking_effort(overrides.get("thinking_effort") or preset.default_thinking_effort),
            "thinking_effort_levels": list(THINKING_EFFORT_LEVELS),
            "has_key": has_key,
            "env_key": preset.env_key,
        })
    return {"active": active, "providers": providers}


class TestBody(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None


class SetModelBody(BaseModel):
    model: str
    provider: str | None = None


@app.post("/api/providers/model")
def api_set_provider_model(body: SetModelBody):
    """对话窗口快速切换当前厂商模型（全局生效，等价 CLI /model）。

    写 provider.list.<name>.model 后重建 Provider/Agent，立即反映到
    徽章 / 侧栏（前端随后 refreshProviderInfo）。不碰 API Key。
    """
    from minihermes.core.provider import provider_names

    name = body.provider or (cfg.load().get("provider") or {}).get("active")
    if not name or name not in provider_names():
        return {"ok": False, "error": f"未知厂商: {name or '(空)'}"}
    if not (body.model or "").strip():
        return {"ok": False, "error": "模型不能为空"}
    try:
        cfg.set_provider_override(name, model=body.model)
        get_kernel().rebuild_provider()  # 内部 reload_config + 重建
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "model": body.model}


@app.post("/api/providers/test")
def api_test_provider(body: TestBody):
    """用 GET {base_url}/models 验证某厂商的 key / base_url 是否可用。

    入参传的是设置页尚未保存的 pending 值（key 不会落盘）；不碰 live kernel，
    因此可测任意厂商（含未激活的）。永不抛异常，返回 {ok, models, error, ...}。
    """
    return test_provider_connection(
        body.provider,
        api_key=body.api_key or "",
        base_url=body.base_url or "",
    )


class ConfigBody(BaseModel):
    model: dict | None = None
    provider: dict | None = None
    agent: dict | None = None
    search: dict | None = None
    code_execution: dict | None = None
    general: dict | None = None


@app.post("/api/config")
def api_set_config(body: ConfigBody):
    """浅合并写入 ~/.minihermes/config.yaml，并立即重建 Provider/Agent。"""
    data = {}
    if CONFIG_PATH.exists():
        import yaml
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    for key in ("model", "provider", "agent", "search", "code_execution", "general"):
        value = getattr(body, key)
        if value is not None:
            data[key] = value
    import yaml
    CONFIG_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # 配置变更即时生效（厂商/模型/上下文窗口随新 Provider 切换）
    try:
        get_kernel().rebuild_provider()
    except Exception as e:
        # 重建失败不阻断保存（例如底层 SDK 异常），返回 ok 但附带提示
        return {"ok": True, "config": data, "rebuild_warning": str(e)}
    return {"ok": True, "config": data}


# ── 工作目录（cwd）─────────────────────────────────────────────────────────

@app.get("/api/cwd")
def api_get_cwd():
    """返回当前内核进程的工作目录 + 「默认」目录（侧栏分组锚点）。"""
    return {"cwd": os.getcwd(), "default_cwd": DEFAULT_CWD}


class CwdBody(BaseModel):
    path: str
    session_id: str | None = None   # 守卫 A 输入：切换时需校验/重绑定的当前会话


@app.post("/api/cwd")
def api_set_cwd(body: CwdBody):
    """切换内核工作目录（导航）：os.chdir + 持久化 general.cwd + 重建模板 agent prompt。

    安全约束：
      - any_busy：任何会话正在生成时拒绝（保留）。
      - 守卫 A：若携带 session_id，则当前会话已有消息（message_count > 0）→ 拒绝；
        空会话（0 消息）→ 允许并重新绑定到新目录（跟随新目录）。
    会话 agent 各自保持绑定目录，其 prompt 由 cwd-drift 守卫按需重建，不在这里遍历。
    """
    k = get_kernel()
    target = str(Path(body.path).expanduser().resolve())

    # 防御性校验：os.chdir 全局生效，任何会话正在生成时拒绝（前端也做了同样检查）
    if k.any_busy():
        return {"ok": False, "error": "有会话正在生成中，请等当前对话结束后再切换工作目录"}

    # 守卫 A（权威）：按会话消息数做后端校验。>0 拒绝；==0 允许并重绑定空会话到新目录
    rebound_sid: str | None = None
    if body.session_id:
        count = k.db.get_session_message_count(body.session_id)
        if count is None:
            return {"ok": False, "error": f"会话不存在: {body.session_id}"}
        if count > 0:
            return {"ok": False, "error": "当前会话已有消息，请新建会话后再切换工作目录"}
        rebound_sid = body.session_id

    ok, err_or_cwd = _switch_cwd(k, target, persist=True, reload_template=True)
    if not ok:
        return {"ok": False, "error": err_or_cwd}

    # 空会话跟随新目录：重绑定 + 清活 runtime 的 cwd 缓存（DB 事实源）
    if rebound_sid:
        k.db.set_session_cwd(rebound_sid, target)
        rt = k._runtimes.get(rebound_sid)
        if rt is not None:
            rt.refresh_cwd()

    return {"ok": True, "cwd": os.getcwd(), "default_cwd": DEFAULT_CWD, "rebound_session_id": rebound_sid}


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
    """处理需要内核能力的命令。返回 True 表示已处理。sid 化：作用于指定会话的 runtime。"""
    if cmd == "/compress":
        kernel.runtime_agent(sid).request_compress()
        manager.send({
            "type": "command_result",
            "session_id": sid,
            "text": "[manual compression triggered — will execute on next LLM call]",
        })
        return True

    if cmd == "/title":
        if not arg:
            manager.send({"type": "command_result", "session_id": sid, "text": "[usage: /title <name>]"})
        else:
            kernel.set_title(sid, arg.strip()[:100])
            manager.send({"type": "command_result", "session_id": sid, "text": f"[session titled: {arg.strip()[:100]}]"})
            manager.send({"type": "sessions", "sessions": kernel.sessions()})
        return True

    if cmd == "/sysprompt":
        sp = kernel.runtime_agent(sid).system_prompt or ""
        manager.send({
            "type": "command_result",
            "session_id": sid,
            "text": f"── system prompt ({len(sp)} chars, ~{len(sp) // 4} tokens) ──\n\n{sp}",
        })
        return True

    if cmd == "/init":
        try:
            threading.Thread(target=run_turn, args=(sid, _INIT_INSTRUCTION), daemon=True).start()
        except Exception as e:
            manager.send({"type": "command_result", "session_id": sid, "text": f"[init failed: {e}]"})
        return True

    # 技能命令：/<skill-name> [arg]
    skill_name = cmd.lstrip("/")
    try:
        skill_info = load_skill_structured(skill_name)
    except Exception:
        skill_info = None
    if skill_info:
        msg = build_skill_activation_message(skill_info, arg)
        threading.Thread(target=run_turn, args=(sid, msg), daemon=True).start()
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
