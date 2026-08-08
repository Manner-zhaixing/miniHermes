"""首次启动引导 & 运行时 /setup 配置向导。"""

import getpass
import sys
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from minihermes.core.config.config import DEFAULT_CONFIG_PATH as _DEFAULT_CONFIG_PATH

_console = Console()

# ── 路径常量 ──────────────────────────────────────────────────────────────────

MINIHERMES_HOME = Path.home() / ".minihermes"
_USER_CONFIG_PATH = MINIHERMES_HOME / "config.yaml"


# ── 配置读写工具 ──────────────────────────────────────────────────────────────

def _ensure_config_dir():
    """确保 ~/.minihermes/ 目录存在。"""
    MINIHERMES_HOME.mkdir(parents=True, exist_ok=True)


def read_user_config() -> dict:
    """读取用户配置。不存在时从模板复制一份返回。"""
    if _USER_CONFIG_PATH.exists():
        with open(_USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    # 首次：读模板
    if _DEFAULT_CONFIG_PATH.exists():
        with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def write_user_config(cfg: dict) -> Path:
    """写入 ~/.minihermes/config.yaml，返回路径。"""
    _ensure_config_dir()
    with open(_USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return _USER_CONFIG_PATH


# ── 输入辅助 ──────────────────────────────────────────────────────────────────

def _prompt(label: str, *, default: str = "", secret: bool = False) -> str:
    """交互式输入。secret=True 时隐藏字符，default 非空时回车采用默认值。"""
    suffix = f" [{default}]" if default else ""
    hint = "（回车跳过）" if not default and not secret else ""
    prompt_text = f"  {label}{suffix}{hint}: "

    try:
        if secret:
            value = getpass.getpass(prompt_text)
        else:
            value = input(prompt_text)
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

    return value.strip() or default


def _mask_secret(value: str) -> str:
    """将 secret 值渲染为 **** 格式（保留后 4 位）。"""
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def _normalize_bool(value: str) -> bool | None:
    """标准化布尔输入。无法识别时返回 None。"""
    v = value.strip().lower()
    if v in ("true", "yes", "y", "1"):
        return True
    if v in ("false", "no", "n", "0"):
        return False
    return None


def _normalize_int(value: str) -> int | None:
    """标准化整数输入。无法识别时返回 None。"""
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return None


# ── 首次运行向导（Rich 风格，保留原有行为） ──────────────────────────────────

def run_setup_wizard() -> bool:
    """执行首次配置引导。成功返回 True，用户中断返回 False。"""
    try:
        _console.print()
        _console.print(Panel(
            Text.from_markup(
                "[bold gold1]Welcome to MiniHermes![/]\n\n"
                "首次运行，需要选择服务厂商并配置 API Key。\n"
                "完成后配置将保存到 [dim]~/.minihermes/config.yaml[/]"
            ),
            border_style="gold1",
            padding=(1, 2),
        ))
        _console.print()

        from minihermes.core.provider import provider_names, get_preset, model_ids_for

        # ── 1. 服务厂商（必填） ──
        _console.print("  [bold]◆ 服务厂商[/]（必填）\n")
        names = provider_names()
        for name in names:
            preset = get_preset(name)
            title = preset.title if preset else name
            _console.print(f"    [cyan]{name}[/] — {title}")

        _console.print()
        provider_name = ""
        while provider_name not in names:
            provider_name = _prompt("选择厂商", default=names[0] if names else "").strip()
            if provider_name not in names:
                _console.print("    [red]无效的厂商，请从列表中选择[/]")

        preset = get_preset(provider_name)
        if preset:
            _console.print(f"    Base URL: {preset.base_url}")

        api_key = ""
        while not api_key:
            api_key = _prompt("API Key", secret=True)
            if not api_key:
                _console.print("    [red]API Key 不能为空[/]")

        _console.print()

        # ── 2. 模型（可选，回车用预设默认） ──
        _console.print("  [bold]◆ 模型[/]（可选，回车用预设默认）\n")
        default_model = preset.default_model if preset else ""
        candidates = model_ids_for(provider_name)
        if candidates:
            _console.print(f"    候选: {', '.join(candidates)}")
        model = _prompt("模型", default=default_model).strip() or default_model
        _console.print()

        # ── 3. 搜索配置（可选） ──
        _console.print("  [bold]◆ 搜索配置[/]（可选，回车跳过）\n")
        _console.print("    Exa AI 搜索引擎 — 专为 AI Agent 设计")
        _console.print("    免费注册获取 API Key：https://dashboard.exa.ai")
        _console.print()
        search_api_key = _prompt("Exa API Key", secret=True)
        _console.print()

        # ── 4. 代码沙箱配置（可选） ──
        _console.print("  [bold]◆ 代码沙箱配置[/]（可选，回车跳过）\n")
        code_api_key = _prompt("七牛 E2B 沙箱 API Key", secret=True)
        _console.print()

        # ── 写入配置 ──
        cfg = read_user_config()

        provider = cfg.setdefault("provider", {})
        entry = provider.setdefault("list", {}).setdefault(provider_name, {})
        entry["api_key"] = api_key
        if model:
            entry["model"] = model
        provider["active"] = provider_name

        if search_api_key:
            cfg["search"]["api_key"] = search_api_key

        if code_api_key:
            cfg["code_execution"]["api_key"] = code_api_key

        config_path = write_user_config(cfg)

        _console.print(Panel(
            Text.from_markup(
                "[bold green]✓ 配置完成！[/]\n\n"
                f"配置文件: [dim]{config_path}[/]\n"
                "随时可以手动编辑该文件修改配置。"
            ),
            border_style="green",
            padding=(1, 2),
        ))
        _console.print()
        return True

    except KeyboardInterrupt:
        _console.print("\n\n  [dim]已取消配置，退出。[/]\n")
        return False


# ── CLI /setup 向导（Rich 美化，覆盖全部字段） ─────────────────────────────────

def run_setup_cli(app_loop=None) -> bool:
    """运行时配置引导（/setup 命令调用）。

    在 prompt_toolkit 运行期间，通过 run_in_terminal 临时恢复终端 cooked 模式
    来安全地进行交互式输入。app_loop 是 prompt_toolkit 的主事件循环。
    如果 app_loop 为 None（首次运行向导场景），则直接运行。
    """
    if app_loop is None:
        # 非 prompt_toolkit 上下文（如首次运行向导），直接执行
        return _run_setup_cli_core()

    import asyncio
    import threading
    from prompt_toolkit.application.run_in_terminal import run_in_terminal

    result_holder: list[bool] = []
    done_event = threading.Event()

    def _run():
        """在 cooked 终端中运行的实际设置逻辑。"""
        try:
            result_holder.append(_run_setup_cli_core())
        except Exception:
            result_holder.append(False)
        finally:
            done_event.set()

    async def _bridge():
        await run_in_terminal(_run)

    # 在主事件循环中调度运行
    asyncio.run_coroutine_threadsafe(_bridge(), app_loop)
    # 阻塞直到设置完成
    done_event.wait()

    return result_holder[0] if result_holder else False


def _run_setup_cli_core() -> bool:
    """设置引导的核心逻辑（在 cooked 终端中运行）。

    所有输出直接写到 sys.__stdout__，绕过 prompt_toolkit 的 patch_stdout，
    确保在 run_in_terminal 期间渲染干净无冲突。
    使用 ANSI 转义码做颜色和样式，不依赖任何第三方库。
    """
    _out = sys.__stdout__

    # ── ANSI 颜色 / 样式 ──────────────────────────────────────────────────
    B = "\033[1m"       # bold
    D = "\033[2m"       # dim
    _R = "\033[0m"      # reset
    # 前景色
    C = "\033[36m"      # cyan
    G = "\033[32m"      # green
    Y = "\033[33m"      # yellow
    R = "\033[31m"      # red
    W = "\033[37m"      # white
    # 粗体 + 颜色
    BC = "\033[1;36m"   # bold cyan
    BG = "\033[1;32m"   # bold green
    BY = "\033[1;33m"   # bold yellow
    BR = "\033[1;31m"   # bold red
    BW = "\033[1;37m"   # bold white

    WIDTH = 58

    # ── 框线辅助（先拼纯文本 + len() 算宽度，最后 ANSI 上色，参考 Hermes 做法）──

    def _box_top(color: str, inner: int) -> None:
        print(f"  {color}╔{'═' * inner}╗{_R}", file=_out)

    def _box_mid(color: str, inner: int) -> None:
        print(f"  {color}╠{'═' * inner}╣{_R}", file=_out)

    def _box_bot(color: str, inner: int) -> None:
        print(f"  {color}╚{'═' * inner}╝{_R}", file=_out)

    def _box_line(color: str, inner: int, left: str, mid: str,
                  mid_color: str = "") -> None:
        """单行框：border(color) + 内容(可选mid_color) + 右border(color)。
        内容区宽度 = inner，由 left(纯文本) + mid(纯文本) + 空格填充 组成。"""
        plain = left + mid
        pad = inner - len(plain)
        if mid_color:
            print(f"  {color}║{_R}{left}{mid_color}{mid}{_R}{' ' * pad}{color}║{_R}", file=_out)
        else:
            print(f"  {color}║{_R}{left}{mid}{' ' * pad}{color}║{_R}", file=_out)

    def _header(title: str):
        """主标题框。"""
        inner = WIDTH - 2
        print(file=_out)
        _box_top(C, inner)
        # 居中标题
        pad_total = inner - len(title)
        pad_l = pad_total // 2
        _box_line(C, inner, ' ' * pad_l, title, mid_color=BW)
        _box_mid(C, inner)
        _box_line(C, inner, ' ', "Enter = keep current   Ctrl+C = cancel",
                  mid_color=D)
        _box_bot(C, inner)
        print(file=_out)

    def _section(num: int, title: str):
        """编号分节标题。"""
        print(f"  {BY}◆ {num}. {title}{_R}", file=_out)
        print(f"  {D}{'─' * WIDTH}{_R}", file=_out)

    def _field(label: str, default: str = "", required: bool = False):
        """格式化字段标签行，显示默认值。"""
        req = f" {BR}*{_R}" if required else ""
        def_str = f" {D}[{default}]{_R}" if default else ""
        print(f"    {B}{label}{_R}{req}{def_str}", file=_out)

    def _info(msg: str):
        """提示。"""
        print(f"    {D}{msg}{_R}", file=_out)

    def _hint(msg: str):
        """选项提示。"""
        print(f"    {D}└ {msg}{_R}", file=_out)

    def _error(msg: str):
        """错误。"""
        print(f"    {R}✗ {msg}{_R}", file=_out)

    def _done(msg: str):
        """成功标记。"""
        print(f"  {G}✓{_R} {msg}", file=_out)

    def _summary_header():
        """汇总表头。"""
        print(file=_out)
        print(f"  {BG}  Summary  {_R}", file=_out)
        print(f"  {D}{'─' * WIDTH}{_R}", file=_out)

    def _summary_row(section: str, field: str, value: str):
        """汇总行。"""
        print(f"  {C}{section:<14s}{_R} {B}{field:<22s}{_R} {D}{value}{_R}", file=_out)

    def _success_box():
        """完成面板。"""
        inner = WIDTH - 2
        print(file=_out)
        print(f"  {G}╭{'─' * inner}╮{_R}", file=_out)
        _box_line(G, inner, ' ', "✓  Config saved", mid_color=BG)
        _box_line(G, inner, ' ', "Changes take effect immediately.",
                  mid_color=D)
        print(f"  {G}╰{'─' * inner}╯{_R}", file=_out)
        print(file=_out)

    def _cancel_box():
        """取消面板。"""
        inner = WIDTH - 2
        print(file=_out)
        print(f"  {D}╭{'─' * inner}╮{_R}", file=_out)
        _box_line(D, inner, ' ', "Setup cancelled. No changes saved.",
                  mid_color=D)
        print(f"  {D}╰{'─' * inner}╯{_R}", file=_out)
        print(file=_out)

    try:
        cfg = read_user_config()
        provider_cfg: dict[str, Any] = cfg.get("provider", {})
        agent_cfg: dict[str, Any] = cfg.get("agent", {})
        search_cfg: dict[str, Any] = cfg.get("search", {})
        code_cfg: dict[str, Any] = cfg.get("code_execution", {})

        from minihermes.core.provider import (
            provider_names, get_preset, model_ids_for, THINKING_EFFORT_LEVELS,
        )
        _names = provider_names()


        # ── 标题 ──────────────────────────────────────────────────────────
        _header("MiniHermes Setup")

        # ═══════════════════ 1. Provider Connection ═══════════════════════
        _section(1, "Provider Connection")

        # 厂商选择
        current_provider = provider_cfg.get("active") or (_names[0] if _names else "deepseek")
        if current_provider not in _names:
            current_provider = _names[0] if _names else "deepseek"
        _field("Provider", current_provider)
        _hint(" / ".join(_names))
        while True:
            prov = _prompt("  ▸ Provider", default=current_provider).strip()
            if prov in _names:
                provider_cfg["active"] = prov
                current_provider = prov
                break
            _error(f"Unknown provider: {prov} (available: {', '.join(_names)})")

        preset = get_preset(current_provider)
        entry = provider_cfg.setdefault("list", {}).setdefault(current_provider, {})
        default_effort = preset.default_thinking_effort if preset else "max"

        # API Key（必填）
        current_key = entry.get("api_key", "")
        _field("API Key", _mask_secret(current_key), required=not bool(current_key))
        while True:
            api_key = _prompt("  ▸ API Key",
                              default=_mask_secret(current_key) if current_key else "",
                              secret=True)
            if api_key and api_key != _mask_secret(current_key):
                entry["api_key"] = api_key
                break
            if current_key:
                break
            _error("API Key cannot be empty")

        # Model（候选 + 自由输入）
        current_model = entry.get("model") or (preset.default_model if preset else "")
        _field("Model", current_model)
        if preset:
            _hint("candidates: " + ", ".join(model_ids_for(current_provider)))
        model = _prompt("  ▸ Model", default=current_model).strip() or current_model
        if model:
            entry["model"] = model

        # Base URL（可选覆盖，留空用预设默认）
        preset_base = preset.base_url if preset else ""
        current_base = entry.get("base_url", "")
        _field("Base URL", current_base or preset_base)
        _hint("留空使用预设默认")
        base_url = _prompt("  ▸ Base URL", default=current_base).strip()
        if base_url and base_url != current_base:
            entry["base_url"] = base_url
        elif current_base and not base_url:
            entry.pop("base_url", None)

        # Context Window（0 = 预设默认）
        current_cw = int(entry.get("context_window") or 0)
        _field("Context Window",
               str(current_cw) if current_cw else f"default ({preset.default_context_window if preset else 0})")
        _hint("0 = 使用预设默认")
        cw = _prompt("  ▸ Context Window", default=str(current_cw) if current_cw else "0")
        if (n := _normalize_int(cw)) is not None and n >= 0:
            entry["context_window"] = n
        elif n is not None:
            _error("Must be a non-negative integer, keeping current value")

        # Thinking Effort（off|low|medium|high|max；空 = 预设默认）
        current_effort = entry.get("thinking_effort", "")
        _field("Thinking Effort", current_effort or f"default ({default_effort})")
        _hint(" / ".join(THINKING_EFFORT_LEVELS) + "（留空用默认）")
        effort = _prompt("  ▸ Thinking Effort", default=current_effort or default_effort).strip()
        if effort in THINKING_EFFORT_LEVELS:
            entry["thinking_effort"] = "" if effort == default_effort else effort
        elif effort:
            _error(f"Invalid effort: {effort} (use: {', '.join(THINKING_EFFORT_LEVELS)})")

        # ═══════════════════ 2. Search ═════════════════════════════════════
        # （max_iterations / show_thinking 已写死进代码，不再引导配置）
        print(file=_out)
        _section(2, "Search — Exa AI")

        _info("AI-native search engine for agents")
        _info("Free API key → https://dashboard.exa.ai")
        print(file=_out)

        current_search_key = search_cfg.get("api_key", "")
        _field("Exa API Key", _mask_secret(current_search_key))
        search_key = _prompt("  ▸ Exa API Key",
                             default=_mask_secret(current_search_key) if current_search_key else "",
                             secret=True)
        if search_key and search_key != _mask_secret(current_search_key):
            search_cfg["api_key"] = search_key

        _field("Result Count", str(search_cfg.get("count", 5)))
        search_count = _prompt("  ▸ Result Count",
                               default=str(search_cfg.get("count", 5)))
        if (n := _normalize_int(search_count)) is not None and n > 0:
            search_cfg["count"] = n

        # ═══════════════════ 3. Code Execution ═════════════════════════════
        print(file=_out)
        _section(3, "Code Execution — E2B Sandbox")

        current_code_key = code_cfg.get("api_key", "")
        _field("E2B Sandbox API Key", _mask_secret(current_code_key))
        code_key = _prompt("  ▸ E2B Sandbox API Key",
                           default=_mask_secret(current_code_key) if current_code_key else "",
                           secret=True)
        if code_key and code_key != _mask_secret(current_code_key):
            code_cfg["api_key"] = code_key

        # ── 写回 ──────────────────────────────────────────────────────────
        cfg["provider"] = provider_cfg
        cfg["agent"] = agent_cfg
        cfg["search"] = search_cfg
        cfg["code_execution"] = code_cfg

        config_path = write_user_config(cfg)

        # ── 汇总 ───────────────────────────────────────────────────────────
        _summary_header()
        _summary_row("Provider", "Active", provider_cfg.get("active", ""))
        _summary_row("Model", "Name", entry.get("model") or (preset.default_model if preset else ""))
        _summary_row("Model", "Base URL", entry.get("base_url") or (preset.base_url if preset else ""))
        _summary_row("Model", "API Key", _mask_secret(entry.get("api_key", "")))
        _summary_row("Agent", "Thinking Effort", entry.get("thinking_effort") or f"default ({default_effort})")
        _summary_row("Search", "API Key", _mask_secret(search_cfg.get("api_key", "")))
        _summary_row("Search", "Count", str(search_cfg.get("count", "")))
        _summary_row("Code Exec", "API Key", _mask_secret(code_cfg.get("api_key", "")))
        print(f"  {D}{'─' * WIDTH}{_R}", file=_out)
        _done(f"Saved to {config_path}")
        _success_box()
        return True

    except KeyboardInterrupt:
        _cancel_box()
        return False
