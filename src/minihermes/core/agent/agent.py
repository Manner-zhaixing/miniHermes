"""
Agent 核心层：对话循环。

设计参考 hermes run_agent.py 的 run_conversation() + while 主循环：
  1. 构建完整 messages（system + history + user）
  2. while 循环驱动：LLM 调用 → 工具执行 → 继续 → 直到 stop 或预算耗尽
  3. IterationBudget 防止无限循环
  4. 上下文压缩：两处检查（调 LLM 前估算 + 响应后精确 usage）
  5. 返回更新后的对话历史，供下一轮使用
"""

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from minihermes.core import tools as tool_registry
from minihermes.core.tools.memory import get_store as get_memory_store
from minihermes.core.provider import Provider, StreamResult
from minihermes.core.prompt import build_system_prompt
from minihermes.core.output import print_budget_warning, render_diff, _cprint, _DIM, _RST
from minihermes.core.rendering import Renderer
from minihermes.core.session import SessionDB
from minihermes.core.context.compressor import ContextCompressor
from minihermes.core.context import ConversationContext
from minihermes.core.personas import build_team_roster
from minihermes.core.personas.manifest import PersonaManifest
from minihermes.core.agent import runtime_ctx


# 最大迭代次数写死（不再读 config.agent.max_iterations）：
# 子 Agent 用 max_iterations_override 覆盖（plan 50 / delegate 50 / 进化 10）
DEFAULT_MAX_ITERATIONS = 100


@dataclass
class ConversationResult:
    """run_conversation() 的返回值。"""
    final_response: str          # 最终文本回复
    reasoning: str               # 思考过程（可能为空）
    messages: list[dict]         # 更新后的完整对话历史（不含 system）
    session_id: str = ""         # 当前 session_id（压缩后可能改变）
    compressed: bool = False     # 本轮是否发生了压缩


class Agent:
    def __init__(
        self,
        provider: Provider,
        db: SessionDB = None,
        clarify_callback=None,
        approval_callback=None,
        auto_approve: bool = False,
        tool_filter: dict | None = None,
        system_prompt_override: str | None = None,
        max_iterations_override: int | None = None,
        persona: Optional[PersonaManifest] = None,
        cwd: str | None = None,
    ):
        self.provider = provider
        self.db = db
        self.clarify_callback = clarify_callback
        self.approval_callback = approval_callback
        self.auto_approve = auto_approve
        self._tool_filter = tool_filter or {}

        # 会话级专家（None = 无专家，行为与现状一致）
        self.persona: Optional[PersonaManifest] = persona
        self.persona_id = persona.id if persona else ""
        # team 主理人花名册（仅 team 型非空）
        self.team_roster = build_team_roster(persona) if (persona and persona.is_team()) else None

        # 会话绑定的工作目录（桌面端会话级 cwd；CLI 未传 → os.getcwd()）
        self.cwd: str = cwd or os.getcwd()

        # system prompt：支持外部覆盖（子 Agent 使用精简 prompt）
        if system_prompt_override is not None:
            self.system_prompt = system_prompt_override
        else:
            self.reload_system_prompt(persona=self.persona)

        # 设置最大迭代次数（写死默认；override 供子 Agent/plan/进化覆盖）
        self._max_iterations = max_iterations_override or DEFAULT_MAX_ITERATIONS
        self.max_iterations = self._max_iterations
        # 上下文压缩器
        self._compressor = ContextCompressor(provider)
        # 安全审批引擎
        from minihermes.core.approval import ApprovalEngine
        self._approval = ApprovalEngine()
        # 对话状态容器（token 追踪、预算、压缩触发、进化计数器）
        tools_json = json.dumps(self._get_tool_schemas())
        self._ctx = ConversationContext(
            max_iterations=self.max_iterations,
            system_prompt=self.system_prompt,
            tools_schema_json=tools_json,
        )
        # 中断请求
        self._interrupt_requested = False
        # delegate_task 的子代理 trace（keyed by tool_call id，_process_tool_call 落盘后弹出）
        self._subagent_traces: dict[str, dict] = {}

    def _get_tool_schemas(self) -> list[dict]:
        """返回经过过滤的工具 schema 列表。

        _tool_filter（Agent 级）与 persona 白名单（会话级）并存时取交集；
        persona 无白名单（tools 为空）→ 只按 _tool_filter 过滤（等效 include=None 全开）。
        """
        inc = set(self._tool_filter.get("include")) if self._tool_filter.get("include") else None
        if self.persona and self.persona.tools:
            wl = set(self.persona.tools)
            inc = (inc & wl) if inc is not None else wl
        return tool_registry.get_schemas(
            include=list(inc) if inc else None,
            exclude=self._tool_filter.get("exclude"),
        )

    def interrupt(self):
        """外部请求中断当前对话循环。"""
        self._interrupt_requested = True

    # ── 公开 API（供 CLI 层调用）─────────────────────────────

    @property
    def last_prompt_tokens(self) -> int:
        """上次 LLM prompt 的真实 token 数（状态栏百分比用）。"""
        return self._ctx.last_prompt_tokens

    @property
    def budget_used(self) -> int:
        """当前轮已使用的 LLM 调用次数。"""
        return self._ctx.budget_used

    def request_compress(self):
        """设置强制压缩标志，下次 LLM 调用前触发压缩（/compress 命令）。"""
        self._ctx.force_compress = True

    def reset_token_tracking(self):
        """重置 token 追踪状态（/setup、/clear 后调用）。"""
        self._ctx.reset_token_tracking()

    def reload_system_prompt(self, memory_store=None,
                             tool_names=None, cwd=None,
                             persona=None, team_roster=None):
        """重建系统提示并重新计算 token 开销。

        /init 创建 minihermes.md 后调用，使新的上下文文件立即生效。
        persona/team_roster 显式传入时用传入值，否则沿用当前 self.persona/self.team_roster。
        """
        memory_store = memory_store or get_memory_store()
        tool_names = tool_names or tool_registry.get_tool_manager().get_names()
        # 显式 cwd= 才重绑定；否则沿用 self.cwd（绑定目录），无绑定（CLI）回退进程 cwd
        cwd = cwd or self.cwd or os.getcwd()
        self.cwd = cwd
        p = persona if persona is not None else self.persona
        roster = team_roster if team_roster is not None else self.team_roster
        self.system_prompt = build_system_prompt(
            model_name=self.provider.model,
            memory_store=memory_store,
            cwd=cwd,
            tool_names=tool_names,
            persona=p,
            team_roster=roster,
        )
        # 换 persona/工具白名单后重算 token 固定开销（_ctx 在 __init__ 后半段创建）
        if hasattr(self, "_ctx"):
            self._ctx.update_overhead(self.system_prompt, json.dumps(self._get_tool_schemas()))

    def apply_persona(self, persona: Optional[PersonaManifest]):
        """会话级切换专家：换身份 + 工具集 + 花名册，下一轮生效（不打断当前轮）。

        persona=None 退出专家，恢复默认行为。team 型同时更新主理人花名册。
        调用方负责把 persona_id 持久化到会话（db.set_persona）。
        """
        self.persona = persona
        self.persona_id = persona.id if persona else ""
        self.team_roster = build_team_roster(persona) if (persona and persona.is_team()) else None
        self.reload_system_prompt(persona=persona)
        self._ctx.reset_token_tracking()

    def switch_provider(self, provider: Provider):
        """运行时切换厂商/模型：换 provider、重建压缩器、刷新系统提示。

        保留 callbacks / db / 工具 schema / 审批引擎，避免整 Agent 重建。
        切换后当前会话历史保留（由调用方决定是否 /clear）。
        """
        self.provider = provider
        self.max_iterations = self._max_iterations  # 保留 __init__ 的 override（写死默认）
        self._compressor = ContextCompressor(provider)  # 新上下文窗口立即生效
        self.reload_system_prompt()                      # 系统提示里的 Model 标签刷新
        self._ctx.reset_token_tracking()

    def _execute_tool(self, tool_name: str, tool_call: dict, args: dict,
                      renderer=None) -> str:
        """
        执行单个工具调用。

        Args:
            tool_name: 工具名，例如 "clarify"。
            tool_call: OpenAI tool_call 原始字典。
            args: 已解析的工具参数，例如 {"question": "..."}。
            renderer: 当前会话渲染器（用于子代理事件透传；None 时子代理走默认终端打印）。

        Returns:
            工具返回的字符串结果。
        """
        if tool_name == "clarify":
            from minihermes.core.tools.clarify import clarify as clarify_tool

            return clarify_tool(
                question=args.get("question", ""),
                callback=self.clarify_callback,
                choices=args.get("choices"),
            )

        if tool_name == "delegate_task":
            from minihermes.core.agent.delegate import run_delegate, DelegationRequest

            # 团队会话：persona_id → 团员 manifest（未知团员返回错误而非静默降级）
            member = None
            persona_id = args.get("persona_id", "")
            if persona_id:
                member = self._resolve_team_member(persona_id)
                if member is None:
                    return self._team_member_error(persona_id)

            request = DelegationRequest(
                task=args.get("task", ""),
                context=args.get("context", ""),
            )

            # 子代理过程透传：构造 ChildRenderer 包一层，把事件转发给父渲染器
            # 的 on_child_event 钩子（桌面 → subagent_* WS 事件；CLI → 终端打印），
            # 同时累积 parts 供 subagent_trace 持久化。start/end 边界由这里显式触发。
            child_renderer = None
            child_id = ""
            if renderer is not None:
                from minihermes.core.rendering import ChildRenderer

                child_id = uuid.uuid4().hex[:8]
                child_renderer = ChildRenderer(renderer, child_id=child_id, task=args.get("task", ""))
                start_hook = getattr(renderer, "on_child_event", None)
                if start_hook is not None:
                    start_hook(child_id, args.get("task", ""), "start", {})

            try:
                result = run_delegate(request, self.provider,
                                      renderer=child_renderer, persona=member)
            finally:
                if child_renderer is not None:
                    end_hook = getattr(renderer, "on_child_event", None)
                    if end_hook is not None:
                        end_hook(child_id, args.get("task", ""), "end", {})
                    # 收集 trace（即使失败也保留已发生的过程）
                    self._subagent_traces[tool_call["id"]] = {
                        "task": args.get("task", ""),
                        "parts": child_renderer.parts,
                    }
            if result.success:
                return result.response
            return f"[Delegation failed: {result.error}]"

        return tool_registry.execute(tool_call)

    def _resolve_team_member(self, persona_id: str):
        """把 delegate_task 的 persona_id 解析为当前专家团团员（仅 team 主理人会话有效）。

        非团队会话或团员不存在时返回 None（调用方给出明确错误）。
        """
        if not (self.persona and self.persona.is_team()):
            return None
        for mem in self.persona.resolved_members:
            if mem.id == persona_id:
                return mem
        return None

    def _team_member_error(self, persona_id: str) -> str:
        """未知团员/非团队会话的 delegate 错误信息（含可用团员列表）。"""
        if self.persona and self.persona.is_team():
            available = ", ".join(m.id for m in self.persona.resolved_members) or "（无）"
            return (
                f"Error: 专家团中没有成员 {persona_id!r}。"
                f"可用团员: {available}。请把 persona_id 换成上面的某个 id，或省略以使用通用子代理。"
            )
        return (
            "Error: 当前会话不是专家团（team）会话，无法按 persona_id 委派给团员。"
            "请省略 persona_id 使用通用子代理，或在团队专家（如 dev-team）会话中调用。"
        )

    def _process_tool_call(self, tc: dict, result: StreamResult,
                           messages: list[dict], working_history: list[dict],
                           renderer, session_id: str) -> None:
        """处理单个 tool_call 的完整生命周期。

        JSON 解析 → 审批检查 → 工具执行 → 计数器更新 →
        diff 渲染 → 结果消息追加到 messages/working_history/DB。
        """
        tool_name = tc["function"]["name"]
        raw_args = tc["function"].get("arguments", "{}")

        # ── 1. 解析参数 ──────────────────────────────────────────
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError as e:
            self._handle_json_error(tc, tool_name, raw_args, e, result,
                                    messages, working_history, renderer, session_id)
            return

        # ── 2. 审批检查 ──────────────────────────────────────────
        check_result = self._approval.check(tool_name, args)

        # diff 快照（write_file 执行前读取旧内容）
        old_content = self._snapshot_old_content(tool_name, args, check_result.action)

        # 解析审批结果
        blocked_msg = self._approval.resolve(
            check_result, tool_name=tool_name, args=args,
            auto_approve=self.auto_approve,
            approval_callback=self.approval_callback,
        )

        # ── 3. 执行工具 ──────────────────────────────────────────
        if blocked_msg is not None:
            tool_result = blocked_msg
        else:
            tool_result = self._execute_tool(tool_name, tc, args, renderer=renderer)

        if renderer:
            renderer.on_tool_result(tool_name, tool_result)

        # ── 4. inline diff ───────────────────────────────────────
        if tool_name == "write_file" and old_content is not None and renderer:
            new_content = args.get("content", "")
            if old_content != new_content:
                render_diff(old_content, new_content, args.get("path", ""))

        # ── 6. 构建结果消息并追加 ────────────────────────────────
        result_msg = self.provider.build_tool_result_message(
            tool_call_id=tc["id"], result=tool_result,
        )
        result_msg["_token_count"] = len(tool_result) // 4
        result_msg["tool_name"] = tool_name
        messages.append(result_msg)
        working_history.append(result_msg)

        if self.db and session_id:
            trace = self._subagent_traces.pop(tc["id"], None)
            self.db.append_message(
                session_id, role="tool", content=tool_result,
                tool_call_id=tc["id"], tool_name=tool_name,
                token_count=len(tool_result) // 4,
                subagent_trace=json.dumps(trace, ensure_ascii=False) if trace else None,
            )

    def _handle_json_error(self, tc: dict, tool_name: str, raw_args: str,
                           error: json.JSONDecodeError, result: StreamResult,
                           messages: list[dict], working_history: list[dict],
                           renderer, session_id: str) -> None:
        """处理 tool_call arguments 的 JSON 解析错误。

        把错误回填给 LLM 让它重发，避免崩整轮对话。
        """
        preview = raw_args if len(raw_args) <= 300 else raw_args[:150] + " ... " + raw_args[-150:]
        _cprint(
            f"\n{_DIM}[agent] tool args JSONDecodeError (tool={tool_name},"
            f" finish_reason={result.finish_reason}, len={len(raw_args)}): {error}{_RST}\n"
            f"{_DIM}raw: {preview}{_RST}"
        )
        err_msg = (
            f"ERROR: tool arguments JSON malformed or truncated "
            f"(JSONDecodeError: {error}). The previous arguments were not valid JSON; "
            f"please re-issue the tool call with shorter / well-formed arguments."
        )
        err_result_msg = self.provider.build_tool_result_message(
            tool_call_id=tc["id"], result=err_msg,
        )
        err_result_msg["_token_count"] = len(err_msg) // 4
        err_result_msg["tool_name"] = tool_name
        messages.append(err_result_msg)
        working_history.append(err_result_msg)

        if self.db and session_id:
            self.db.append_message(
                session_id, role="tool", content=err_msg,
                tool_call_id=tc["id"], tool_name=tool_name,
                token_count=len(err_msg) // 4,
            )
        if renderer:
            renderer.on_tool_result(tool_name, err_msg)

    _MAX_SNAPSHOT_LINES = 20
    _MAX_SNAPSHOT_LINE_CHARS = 2000

    @staticmethod
    def _snapshot_old_content(tool_name: str, args: dict, action: str) -> str | None:
        """write_file 执行前读取旧文件前 N 行，用于 diff 渲染。"""
        if tool_name != "write_file" or action == "block":
            return None
        write_path = args.get("path", "")
        try:
            # 相对路径按当前线程会话绑定目录解析（无 thread-local cwd 时回退进程 cwd）
            p = Path(write_path).expanduser()
            if not p.is_absolute():
                p = Path(runtime_ctx.current_cwd() or os.getcwd()) / p
            if not p.is_file():
                return None
            lines: list[str] = []
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if len(line) > Agent._MAX_SNAPSHOT_LINE_CHARS:
                        line = line[:Agent._MAX_SNAPSHOT_LINE_CHARS] + "......\n"
                    lines.append(line)
                    if len(lines) >= Agent._MAX_SNAPSHOT_LINES:
                        lines.append("......\n")
                        break
            return "".join(lines)
        except (OSError, UnicodeDecodeError):
            return None

    def run_conversation(
        self,
        user_message: str,
        history: list[dict],
        renderer: Optional[Renderer] = None,
        session_id: Optional[str] = None,
        *,
        thinking_effort: str | None = None,
    ) -> ConversationResult:
        """
        执行一次完整的对话轮次。agent运行的核心方法

        Args:
            user_message: 用户本轮输入
            history:      历史消息列表（不含 system，由调用方维护）
            renderer:     流式渲染器
            session_id:   当前会话 ID（用于压缩时写入 DB）
            thinking_effort: 每轮思考强度覆盖（桌面对话窗口选择器）。
                None/空 → 用 Provider 默认；off/low/medium/high/max → 本轮所有 LLM 调用生效。

        Returns:
            ConversationResult
        """
        compressed = False
        self._interrupt_requested = False

        # 构建 API 所需的完整 messages（system + history + 本轮用户消息）
        messages = [{"role": "system", "content": self.system_prompt}]
        messages += history
        messages.append({"role": "user", "content": user_message})

        # 工作副本（不含 system，用于返回给调用方）
        working_history = list(history)
        working_history.append({"role": "user", "content": user_message})

        # 实时写入 user 消息
        if self.db and session_id:
            self.db.append_message(session_id, "user", user_message,
                                   token_count=len(user_message) // 4)

        final_response = ""
        final_reasoning = ""

        # ══ 主循环 ══════════════════════════════════════════════════════════
        while True:
            if self._interrupt_requested:
                # 早期中断（流式响应之前）：写入占位 assistant 消息，
                # 避免 DB 中出现孤立 user 消息导致下次连续 user 异常
                if self.db and session_id:
                    self.db.append_message(
                        session_id, role="assistant", content="[Interrupted before response]",
                        finish_reason="interrupted_before_response",
                    )
                break
            # 检查最大轮数的预算
            if not self._ctx.consume_budget():
                print_budget_warning(self._ctx.budget_used, self.max_iterations)
                break

            # ── 检查点 1：调 LLM 前，估算 token 是否超限 ────────────────────
            current_tokens = self._ctx.estimate_tokens(messages)
            should = self._compressor.should_compress(current_tokens) or self._ctx.force_compress
            if should:
                self._ctx.force_compress = False
                _cprint(f"\n{_DIM}⟳ compacting context...{_RST}")
                working_history, new_sid = self._compressor.compress(
                    working_history, self.db, session_id
                )
                if new_sid != session_id:
                    session_id = new_sid
                messages = [{"role": "system", "content": self.system_prompt}] + working_history
                self._ctx.reset_token_tracking()
                compressed = True

            if renderer:
                renderer.reset()

            # 调用 LLM（流式）；thinking_effort 每轮覆盖（桌面选择器），None → 厂商默认
            result: StreamResult = self.provider.stream(
                messages=messages,
                tools=self._get_tool_schemas(),
                on_delta=renderer.on_delta if renderer else None,
                on_thinking=renderer.on_thinking if renderer else None,
                on_tool_start=renderer.on_tool_start if renderer else None,
                interrupt_check=lambda: self._interrupt_requested,
                renderer=renderer,
                thinking_effort=thinking_effort,
            )

            # 渲染器收尾
            if renderer:
                renderer.finalize()

            # ── 中断处理：Ctrl+C 终止了流式输出 ────────────────────────────
            if result.interrupted:
                assistant_msg = self.provider.build_assistant_message(result)
                messages.append(assistant_msg)
                working_history.append(assistant_msg)
                if self.db and session_id:
                    self.db.append_message(
                        session_id, role="assistant", content=result.content,
                        finish_reason="interrupted",
                    )
                final_response = result.content or ""
                break

            # ── 检查点 2：用真实 usage 更新 token 追踪 ──────────────────────
            if result.prompt_tokens:
                self._ctx.update_from_usage(result.prompt_tokens, len(messages))

            # 构建 assistant 消息并追加到历史
            assistant_msg = self.provider.build_assistant_message(result)
            if result.completion_tokens:
                assistant_msg["_token_count"] = result.completion_tokens
            messages.append(assistant_msg)
            working_history.append(assistant_msg)

            # 实时写入 assistant 消息
            if self.db and session_id:
                self.db.append_message(
                    session_id, role="assistant", content=result.content,
                    tool_calls=result.tool_calls or None,
                    reasoning=result.reasoning or None,
                    token_count=result.completion_tokens,
                    finish_reason=result.finish_reason,
                )

            final_reasoning = result.reasoning

            # ── 无工具调用：最终回复，退出循环 ────────────────────────────
            if not result.has_tool_calls:
                final_response = result.content
                break

            # ── 有工具调用：逐个处理 ──────────────────────────────
            for tc in result.tool_calls:
                if self._interrupt_requested:
                    break
                self._process_tool_call(
                    tc, result, messages, working_history,
                    renderer, session_id,
                )

        return ConversationResult(
            final_response=final_response,
            reasoning=final_reasoning,
            messages=working_history,
            session_id=session_id,
            compressed=compressed,
        )
