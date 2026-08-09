"""团队（team）运行时文本 —— 主理人花名册 + 团员子代理 prompt。

team 型专家 = 主理人会话（system prompt 含花名册）+ 团员子代理（delegate_task 携 persona_id 调度）。
本模块只产出文本；实际委派走 core/agent/delegate.py 的 persona 分支。
"""

from __future__ import annotations

from minihermes.core.personas.manifest import PersonaManifest


def build_team_roster(lead: PersonaManifest) -> str:
    """注入主理人 system prompt 的花名册块：团员 id/name/tagline/工具，指示用 delegate_task 调度。

    lead 无团员（resolved_members 为空）时返回空串（调用方跳过注入）。
    """
    if not lead.is_team() or not lead.resolved_members:
        return ""
    lines = [
        "## 你的专家团（Team Roster）",
        f"你是 {lead.name} 的主理人。需要帮手时，把子任务委派给对应团员，"
        "调用 delegate_task 工具并携带参数 persona_id=<团员 id>：",
        "",
    ]
    for mem in lead.resolved_members:
        tools = ", ".join(mem.tools) if mem.tools else "（全部工具）"
        lines.append(f"- **{mem.id}** — {mem.tagline or mem.name}；可用工具: {tools}")
    lines.append("")
    lines.append(
        "委派完成后，把团员的结果整合进你的最终交付；只向用户呈现整合后的结论，"
        "并注明各子任务由哪位团员完成。"
    )
    return "\n".join(lines)


_MEMBER_SUFFIX = """

## 团队协作规则

你是该专家团的一名成员，受主理人（lead）调度。要求：
- 只完成分配给你的子任务，主动说明交付边界，不越权推进额外工作；
- 遇到超出你专业范围的请求，明确说明，不要猜测硬做；
- 完成后向主理人提交清晰、结构化的结果汇报：结论 + 关键依据 + 交付物；
- 若你的工具列表中包含 todo：每执行完分配给你的一项任务，立即调用 todo 工具把该项标记为
  completed（若存在下一未开始项，置为 in_progress）；未更新 todo 状态前不要继续下一项，防止后续遗忘。
""".strip()


def build_member_prompt(member: PersonaManifest) -> str:
    """团员子代理的 system_prompt_override：成员正文 + 团队协作补充。"""
    body = member.system_prompt.strip()
    return (body + "\n\n" + _MEMBER_SUFFIX).strip()
