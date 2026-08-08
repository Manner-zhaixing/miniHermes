"""预设厂商注册表（多供应商支持）。

纯数据 + 查询函数，不依赖 config：
- 每个厂商一条 ProviderPreset，声明默认 base_url、模型候选、上下文长度、
  默认思考强度、env 兜底变量名。
- config.yaml 只存用户覆盖项（api_key / 模型 / 上下文 / 思考强度），
  解析层把「预设默认 + 用户覆盖」合并成 resolved config。

新增厂商只需在 PRESETS 加一条（并保证 config.yaml 模板里同步一份空覆盖块）。
"""

from dataclasses import dataclass, field


# 思考强度可选档位（off 关闭思考；其余透传给 reasoning_effort）
# 无 low：DeepSeek 服务端只认 high/max，low 会被映射且 flash 下不产出思考
THINKING_EFFORT_LEVELS = ("off", "medium", "high", "max")

# 合法思考强度值（None/空 视为未设置，走预设默认）
THINKING_EFFORT_VALUES = THINKING_EFFORT_LEVELS + (None, "")


@dataclass(frozen=True)
class ModelPreset:
    """单个模型候选：id + 上下文窗口（tokens）。"""
    id: str
    context_window: int


@dataclass(frozen=True)
class ProviderPreset:
    """一个 OpenAI 兼容厂商的预设信息。"""
    name: str                      # 稳定 id：deepseek / glm
    title: str                     # 展示名
    base_url: str                  # 官方兼容端点
    models: list                    # list[ModelPreset]：下拉候选，也允许自定义
    default_model: str             # 未设置时使用的模型
    default_context_window: int    # 未设置时的上下文窗口（tokens）
    default_thinking_effort: str = "max"
    env_key: str = ""              # 环境变量兜底（如 DEEPSEEK_API_KEY）


# ── 预设表 ─────────────────────────────────────────────────────────────────
# 模型 id / 上下文长度已对照官方文档核实（2026-08）：
# - deepseek-v4-flash / v4-pro：上下文 1M（输出上限 384K）；reasoning_effort 官方支持 high/max（low/medium/xhigh 会被映射）
# - GLM-5 / GLM-5.1 / GLM-5-Turbo：上下文 200K；glm-5-flash 不存在

PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        name="deepseek",
        title="DeepSeek",
        base_url="https://api.deepseek.com",
        models=[
            ModelPreset("deepseek-v4-flash", 1_000_000),
            ModelPreset("deepseek-v4-pro", 1_000_000),
        ],
        default_model="deepseek-v4-flash",
        default_context_window=1_000_000,
        default_thinking_effort="max",
        env_key="DEEPSEEK_API_KEY",
    ),
    "glm": ProviderPreset(
        name="glm",
        title="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=[
            ModelPreset("glm-5", 200_000),
            ModelPreset("glm-5.1", 200_000),
            ModelPreset("glm-5-turbo", 200_000),
        ],
        default_model="glm-5",
        default_context_window=200_000,
        default_thinking_effort="max",
        env_key="ZHIPU_API_KEY",
    ),
}


# ── 查询函数 ───────────────────────────────────────────────────────────────

def provider_names() -> list[str]:
    """所有预设厂商 id（保持 PRESETS 定义顺序）。"""
    return list(PRESETS.keys())


def get_preset(name: str) -> ProviderPreset | None:
    """按 id 取预设；未知厂商返回 None。"""
    return PRESETS.get(name)


def default_provider_name() -> str:
    """未配置 active 时的回退厂商。"""
    return provider_names()[0] if PRESETS else "deepseek"


def default_model_for(name: str) -> str:
    """厂商默认模型；未知厂商回退默认厂商的默认模型。"""
    preset = get_preset(name) or get_preset(default_provider_name())
    return preset.default_model if preset else "deepseek-v4-flash"


def context_window_for(name: str, model: str | None = None) -> int:
    """厂商/模型的默认上下文窗口。

    优先精确匹配模型的预设窗口，否则回落厂商默认窗口。
    """
    preset = get_preset(name)
    if preset is None:
        preset = get_preset(default_provider_name())
    if preset is None:
        return 128_000
    if model:
        for m in preset.models:
            if m.id == model and m.context_window > 0:
                return m.context_window
    return preset.default_context_window


def validate_thinking_effort(value) -> str:
    """规范化思考强度：空/非法值回退预设默认（max）。"""
    if value in THINKING_EFFORT_VALUES:
        return value or "max"
    return "max"


def model_ids_for(name: str) -> list[str]:
    """厂商预设模型 id 列表（UI 下拉用）。"""
    preset = get_preset(name)
    if preset is None:
        return []
    return [m.id for m in preset.models]
