"""LLM 适配层：OpenAI SDK 封装 + 多厂商预设注册表。"""
from .health import test_provider_connection
from .provider import Provider, StreamResult
from .registry import (
    PRESETS,
    ProviderPreset,
    ModelPreset,
    THINKING_EFFORT_LEVELS,
    provider_names,
    get_preset,
    default_provider_name,
    default_model_for,
    context_window_for,
    model_ids_for,
    validate_thinking_effort,
)

__all__ = [
    "Provider",
    "StreamResult",
    "test_provider_connection",
    "PRESETS",
    "ProviderPreset",
    "ModelPreset",
    "THINKING_EFFORT_LEVELS",
    "provider_names",
    "get_preset",
    "default_provider_name",
    "default_model_for",
    "context_window_for",
    "model_ids_for",
    "validate_thinking_effort",
]
