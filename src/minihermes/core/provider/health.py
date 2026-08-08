"""厂商连接探测：用 GET {base_url}/models 验证 API Key / Base URL 是否可用。

参考 openworker `coworker/providers/registry.py` 的 `validate_provider_credentials()`
（httpx.get(base + "/models", headers={"Authorization": f"Bearer {key}"})，永不抛异常）。

CLI 与桌面端共用：用户填完 API Key 后可先测试再保存。
"""

import os
import time

import requests

import minihermes.core.config as cfg
from minihermes.core.provider.registry import (
    PRESETS,
    get_preset,
)

# 探测超时（秒）：bad base_url / 无响应时快速失败
_PROBE_TIMEOUT = 10.0


def _friendly_error(status: int | None = None) -> str:
    """按 HTTP 状态码给友好中文错误。"""
    if status == 401 or status == 403:
        return "API Key 无效或无权限（HTTP 401/403）"
    if status == 404 or status == 405:
        return "该厂商不支持模型列表接口（HTTP 404/405）"
    if status == 429:
        return "请求过于频繁（HTTP 429）"
    if status is not None and 500 <= status < 600:
        return f"服务端错误（HTTP {status}）"
    if status is not None:
        return f"请求失败（HTTP {status}）"
    return "无法连接厂商"


def test_provider_connection(
    name: str,
    api_key: str = "",
    base_url: str = "",
) -> dict:
    """用 GET {base_url}/models 验证厂商连通性与 key 有效性。永不抛异常。

    合并优先级：入参 > config.provider.list.<name> 覆盖 > 预设默认 > env 兜底。

    返回：
        {
            "ok": bool,
            "models": list[str],      # ok=True 时返回模型 id 列表（可能为空）
            "latency_ms": int,        # 请求耗时
            "status": int | None,     # HTTP 状态码
            "error": str | None,      # ok=False 时的友好错误信息
        }
    """
    if name not in PRESETS:
        return {
            "ok": False,
            "models": [],
            "latency_ms": 0,
            "status": None,
            "error": f"未知厂商: {name}",
        }
    preset = get_preset(name)

    # 合并配置覆盖（mirror server.py api_get_providers 的 per-name 合并）
    overrides = {}
    try:
        data = cfg.load()
        overrides = (data.get("provider", {}).get("list") or {}).get(name) or {}
    except Exception:
        overrides = {}

    base = (
        (base_url or "").strip().rstrip("/")
        or str(overrides.get("base_url") or "").strip().rstrip("/")
        or preset.base_url.rstrip("/")
    )
    key = (
        (api_key or "").strip()
        or str(overrides.get("api_key") or "").strip()
        or os.environ.get(preset.env_key or "", "")
    )

    started = time.monotonic()
    try:
        resp = requests.get(
            base + "/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=_PROBE_TIMEOUT,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
    except Exception as exc:  # DNS / 连接 / 超时 —— 绝不冒泡成 500
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "models": [],
            "latency_ms": latency_ms,
            "status": None,
            "error": f"无法连接厂商（{type(exc).__name__}）",
        }

    if resp.status_code < 300:
        # OpenAI 标准响应：{"data": [{"id": "..."}, ...]}
        models: list[str] = []
        try:
            payload = resp.json()
            models = [
                str(item.get("id"))
                for item in (payload.get("data") or [])
                if item.get("id")
            ]
        except Exception:
            models = []
        return {
            "ok": True,
            "models": models,
            "latency_ms": latency_ms,
            "status": resp.status_code,
            "error": None,
        }

    return {
        "ok": False,
        "models": [],
        "latency_ms": latency_ms,
        "status": resp.status_code,
        "error": _friendly_error(resp.status_code),
    }
