"""
配置加载层。

职责单一：读取 ~/.minihermes/config.yaml（首次启动则触发 setup wizard），
并把项目模板里新增的顶层 key 补齐到用户配置中。

多厂商：预设厂商在 core/provider/registry.py（代码注册表），
config.yaml 只存用户覆盖项（provider.list.<name>.*）。
get_provider_config() / get_model_config() 返回「预设默认 + 用户覆盖 + env 兜底」
合并后的 resolved 配置，是全项目唯一的厂商配置真相源。

模块/算法级别的常量（如 RETRY 阈值等）已下沉到各自使用方所在的模块。
"""

import os
import sys
import yaml
from pathlib import Path

from minihermes.core.provider.registry import (
    PRESETS,
    default_provider_name,
    get_preset,
    provider_names,
    context_window_for,
    validate_thinking_effort,
)

MINIHERMES_HOME = Path.home() / ".minihermes"

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_CONFIG_PATH = MINIHERMES_HOME / "config.yaml"

# 首次运行配置向导钩子（CLI 在启动早期注册；桌面/无头不注册则静默补齐默认值）
_setup_wizard = None


def register_setup_wizard(fn):
    """注册首次运行配置向导。

    CLI 在 main 的 import 阶段尽早注册（早于任何 config 访问）；
    桌面后端不注册，_ensure_config 会用默认模板静默补齐。
    """
    global _setup_wizard
    _setup_wizard = fn


def _ensure_config():
    """确保 ~/.minihermes/config.yaml 存在，不存在则引导或补齐。"""
    if _CONFIG_PATH.exists():
        return
    if _setup_wizard is not None:
        if not _setup_wizard():
            sys.exit(0)
        return
    # 无向导（桌面/无头场景）：用默认模板静默补齐
    if DEFAULT_CONFIG_PATH.exists():
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def _migrate_legacy_model(user_cfg: dict) -> bool:
    """把旧版扁平 `model:` 段迁移到 `provider:` + `agent:` 结构。

    返回是否发生迁移（调用方据此决定是否写回磁盘）。
    """
    model_cfg = user_cfg.get("model")
    if not isinstance(model_cfg, dict) or not model_cfg:
        return False
    # 已存在新结构（provider.list 非空）则不迁移
    if isinstance(user_cfg.get("provider"), dict) and user_cfg["provider"].get("list"):
        return False

    # 按 base_url / name 启发式判定厂商
    blob = " ".join(str(model_cfg.get(k) or "") for k in ("base_url", "name")).lower()
    vendor = "glm" if ("bigmodel" in blob or "zhipu" in blob) else "deepseek"

    provider = user_cfg.setdefault("provider", {})
    plist = provider.setdefault("list", {})
    # 为所有预设厂商建空条目，便于在 config.yaml 里发现其他厂商
    for name in provider_names():
        plist.setdefault(name, {})
    entry = plist[vendor]
    if model_cfg.get("api_key"):
        entry["api_key"] = model_cfg.get("api_key")
    if model_cfg.get("base_url"):
        entry["base_url"] = model_cfg.get("base_url")
    if model_cfg.get("name"):
        entry["model"] = model_cfg.get("name")
    if "thinking_effort" not in entry:
        reason = model_cfg.get("reason")
        entry["thinking_effort"] = "" if reason in (None, True) else "off"
    provider["active"] = vendor

    # 注意：max_iterations / show_thinking 已写死进代码，不再迁移到 agent 段
    del user_cfg["model"]
    return True


def _resolve_provider_config(data: dict) -> dict:
    """把 provider 段（预设默认 + 用户覆盖 + env 兜底）合并成 resolved dict。"""
    provider_cfg = data.get("provider") or {}
    active = provider_cfg.get("active") or default_provider_name()
    if active not in PRESETS:
        active = default_provider_name()
    preset = PRESETS[active]
    overrides = (provider_cfg.get("list") or {}).get(active) or {}

    model = overrides.get("model") or preset.default_model
    effort = validate_thinking_effort(overrides.get("thinking_effort") or preset.default_thinking_effort)
    context_window = int(overrides.get("context_window") or 0) or context_window_for(active, model)

    api_key = overrides.get("api_key") or ""
    if not api_key and preset.env_key:
        api_key = os.environ.get(preset.env_key, "")

    return {
        "provider": active,
        "name": model,
        "model": model,
        "base_url": overrides.get("base_url") or preset.base_url,
        "api_key": api_key,
        "context_window": context_window,
        "thinking_effort": effort,
        "reason": effort != "off",
        # max_iterations / show_thinking 已写死进代码，不再出现在 resolved config
    }


def _write_config(data: dict) -> None:
    """把完整配置 dict 写回 ~/.minihermes/config.yaml。"""
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except OSError:
        pass


def load() -> dict:
    _ensure_config()
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}

    # 旧 model: 段 → provider:/agent: 一次性迁移
    # （须在合并模板之前：模板的 provider.list 空条目会干扰「是否已新结构」判断）
    mutated = _migrate_legacy_model(user_cfg)

    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            default_cfg = yaml.safe_load(f) or {}
        for key, value in default_cfg.items():
            if key not in user_cfg:
                user_cfg[key] = value
                mutated = True

    if mutated:
        _write_config(user_cfg)

    return user_cfg


def set_active_provider(name: str) -> None:
    """切换当前激活厂商并写回磁盘（不刷新内存缓存，调用方随后 reload_config）。"""
    data = load()
    data.setdefault("provider", {})["active"] = name
    _write_config(data)


def set_provider_override(name: str, **overrides) -> None:
    """写 provider.list.<name> 的覆盖项（None 表示删除该覆盖项）。

    用于运行时切换模型 / 设置厂商参数；之后需调用 reload_config() 生效。
    """
    data = load()
    provider = data.setdefault("provider", {})
    entry = provider.setdefault("list", {}).setdefault(name, {})
    for key, value in overrides.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    _write_config(data)


class Config:
    """可注入的配置容器。

    延迟加载 ~/.minihermes/config.yaml，
    首次访问 property 时读取并合并默认值。
    支持通过 config_path 指定自定义路径（测试用）。
    """

    def __init__(self, config_path: Path | None = None):
        """可指定自定义配置路径，默认 ~/.minihermes/config.yaml。"""
        self._config_path = config_path or _CONFIG_PATH
        self._data: dict | None = None

    def _ensure_loaded(self):
        """延迟加载：首次访问时从磁盘读取并合并默认值。"""
        if self._data is not None:
            return
        self._data = load()

    @property
    def provider(self) -> dict:
        """当前生效的厂商配置（预设默认 + 用户覆盖合并后）。"""
        self._ensure_loaded()
        return _resolve_provider_config(self._data)

    @property
    def model(self) -> dict:
        """向后兼容：与 provider 解析结果一致（name/base_url/api_key/…）。"""
        return self.provider

    @property
    def agent(self) -> dict:
        """Agent 通用配置（max_iterations, show_thinking）。"""
        self._ensure_loaded()
        return self._data.get("agent", {})

    @property
    def search(self) -> dict:
        """搜索相关配置。"""
        self._ensure_loaded()
        return self._data.get("search", {})

    @property
    def code_execution(self) -> dict:
        """代码执行沙箱配置。"""
        self._ensure_loaded()
        return self._data.get("code_execution", {})

    def reload(self):
        """强制从磁盘重新加载（运行时配置变更后调用）。"""
        self._data = None


# 向后兼容：模块级默认实例和访问器函数
_default_config = Config()


def get_provider_config() -> dict:
    return _default_config.provider


def get_model_config() -> dict:
    """旧访问器：返回当前生效厂商的 resolved 配置（与 get_provider_config 一致）。"""
    return _default_config.provider


def get_agent_config() -> dict:
    return _default_config.agent


def get_search_config() -> dict:
    return _default_config.search


def get_code_execution_config() -> dict:
    return _default_config.code_execution


def reload_config():
    """强制模块级单例从磁盘重读（运行时切换厂商/模型后调用）。"""
    _default_config.reload()
