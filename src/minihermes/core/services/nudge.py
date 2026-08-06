"""进化系统触发服务：CLI 与桌面共用的 nudge 检查。"""

from minihermes.core.config import get_evolution_config

EVO_MEMORY_NUDGE_INTERVAL = 10
EVO_SKILL_NUDGE_INTERVAL = 10
EVO_NUDGE_MIN_TURNS = 5


def maybe_trigger_nudge(agent, conversation_history: list[dict], user_turns: int):
    """检查进化系统 nudge 触发条件，满足则后台运行 nudge agent。

    计数器保留在 agent 实例上（turns_since_memory / iters_since_skill），
    由调用方在对话循环推进时递增。
    """
    evo_cfg = get_evolution_config()
    if not evo_cfg.get("enabled", False):
        return

    if user_turns < EVO_NUDGE_MIN_TURNS:
        return

    nudge_type = None

    # Memory nudge：按用户对话轮数
    agent.turns_since_memory += 1
    if EVO_MEMORY_NUDGE_INTERVAL > 0 and agent.turns_since_memory >= EVO_MEMORY_NUDGE_INTERVAL:
        nudge_type = "memory"
        agent.turns_since_memory = 0

    # Skill nudge：按工具迭代次数（计数器在 agent 主循环中递增）
    if EVO_SKILL_NUDGE_INTERVAL > 0 and agent.iters_since_skill >= EVO_SKILL_NUDGE_INTERVAL:
        nudge_type = "both" if nudge_type == "memory" else "skill"
        agent.iters_since_skill = 0

    if nudge_type and conversation_history:
        from minihermes.core.evolution.nudge import spawn_nudge
        spawn_nudge(agent.provider, conversation_history, nudge_type)
