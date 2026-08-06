"""Plan 模式：只读规划 + 审批执行（CLI 与桌面共用）。

流程（原 cli/conversation._execute_plan_mode 与 desktop server.Kernel.run_plan 统一）：
  1. 只读 plan agent 生成方案
  2. 写入 .minihermes/plans/<timestamp>-<slug>.md
  3. 审批回调（CLI TUI 面板 / 桌面 WS 弹窗）返回 execute/cancel
  4. 批准则返回统一执行指令消息，交由调用方驱动主 Agent
"""

import re
from datetime import datetime
from pathlib import Path

from minihermes.core.agent.agent import Agent


# ── Plan 模式允许的工具（只读）─────────────────────────────────────────────────

PLAN_ALLOWED_TOOLS = {
    "read_file", "list_dir", "web_search", "web_extract",
    "session_search", "process", "memory", "clarify",
    "todo", "skill_view",
}

# ── Plan 模式系统提示追加 ─────────────────────────────────────────────────────

PLAN_MODE_PROMPT = """

# Plan Mode Active

You are in PLAN MODE. Your job is to analyze the codebase and produce a detailed implementation plan.

RULES:
- You MUST NOT make any changes to files or run any commands that modify state.
- You CAN ONLY read files, search code, browse the web, and use other read-only tools.
- Analyze the codebase thoroughly before producing the plan.

Your final response MUST be a complete implementation plan in markdown format with:
1. **Goal** — What needs to be accomplished
2. **Analysis** — Key findings from reading the code
3. **Steps** — Ordered implementation steps with specific file paths and changes
4. **Risks** — Potential issues or considerations

Be specific: include file paths, function names, and describe exact changes needed.
"""

# 用户输入前缀：CLI 的 /plan 命令与桌面 Plan 模式开关都通过该前缀注入
PLAN_MODE_PREFIX = "__PLAN_MODE__:"


# ── Plan 文件路径生成 ──────────────────────────────────────────────────────────

def generate_plan_path(description: str) -> Path:
    """生成 plan 文件路径：.minihermes/plans/<timestamp>-<slug>.md"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    words = re.sub(r'[^a-zA-Z0-9一-鿿\s]', '', description).split()[:5]
    slug = "-".join(w.lower() for w in words) if words else "plan"
    slug = slug[:40]
    filename = f"{timestamp}-{slug}.md"
    plan_dir = Path.cwd() / ".minihermes" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir / filename


# ── Plan agent 输入消息 ────────────────────────────────────────────────────────

def build_plan_user_message(plan_description: str) -> str:
    """构建 plan agent 的用户消息（CLI 与桌面保持一致）。"""
    if plan_description:
        return (
            f"Create a detailed implementation plan for:\n\n"
            f"{plan_description}\n\n"
            f"Analyze the codebase thoroughly using read-only tools before producing the plan."
        )
    return (
        "The user wants you to create an implementation plan. "
        "Ask them what they'd like to plan using the clarify tool, "
        "then analyze the codebase and produce a detailed plan."
    )


# ── 统一三阶段流程 ─────────────────────────────────────────────────────────────

def run_plan_flow(
    *,
    provider,
    db,
    renderer,
    session_id: str,
    plan_description: str,
    base_system_prompt: str,
    clarify_callback=None,
    approval,
    on_plan_saved=None,
    max_iterations_override: int = 50,
) -> str | None:
    """Plan 三阶段流程共享实现（只读规划 → 存盘 → 审批）。

    Args:
        provider:            主 Agent 的 Provider（plan agent 复用）
        db:                  SessionDB
        renderer:            Renderer 实例（CLI StreamRenderer / 桌面 GuiRenderer）
        session_id:          当前会话
        plan_description:    用户要规划的任务描述
        base_system_prompt:  主 Agent 的 system prompt（plan agent 追加 PLAN_MODE_PROMPT）
        clarify_callback:    透传给 plan agent
        approval:            Callable[[plan_text, plan_path], "execute"|"cancel"]
        on_plan_saved:       Callable[[Path], None] — 方案落盘后的通知（CLI 打印 / 桌面 toast）
        max_iterations_override: plan agent 迭代预算（默认 50）

    Returns:
        批准后返回"执行指令消息"，调用方应交给主 Agent 执行；取消/失败返回 None。
    """
    plan_agent = Agent(
        provider=provider,
        db=db,
        clarify_callback=clarify_callback,
        auto_approve=True,
        tool_filter={"include": PLAN_ALLOWED_TOOLS},
        system_prompt_override=(base_system_prompt or "") + PLAN_MODE_PROMPT,
        max_iterations_override=max_iterations_override,
    )

    plan_result = plan_agent.run_conversation(
        user_message=build_plan_user_message(plan_description),
        history=[],
        renderer=renderer,
        session_id=session_id,
    )

    plan_text = plan_result.final_response or "(empty plan)"
    plan_path = generate_plan_path(plan_description)
    plan_path.write_text(plan_text, encoding="utf-8")
    if on_plan_saved:
        on_plan_saved(plan_path)

    choice = approval(plan_text, str(plan_path))
    if choice != "execute":
        return None

    return (
        f"Execute the following approved implementation plan. "
        f"Implement each step in order using the appropriate tools.\n\n"
        f"---\n{plan_text}\n---"
    )
