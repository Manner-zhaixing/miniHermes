"""
共享输出层：核心的 ANSI 侧信道输出（与前端渲染器解耦）。

核心（agent/provider/tools/evolution）需要向用户展示的进度、错误、diff
等"旁路输出"统一走这里。实现为纯 print()，不含 prompt_toolkit / rich；
终端富渲染（欢迎页、历史回显、流式面板）在 minihermes.cli.renderer 中。
"""

import difflib
import re

# ── ANSI 颜色常量 ──────────────────────────────────────────────────────────────

_GOLD = "\033[1;38;2;255;215;0m"
_AMBER = "\033[38;2;255;191;0m"
_CREAM = "\033[38;2;255;248;220m"
_BRONZE = "\033[38;2;184;134;11m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_BOLD_RED = "\033[1;31m"
_RST = "\033[0m"

_INDENT = "    "


# ── 核心输出函数 ───────────────────────────────────────────────────────────────

def _cprint(text: str = ""):
    """核心旁路输出：纯 print，兼容 patch_stdout 环境。

    原实现走 prompt_toolkit.print_formatted_text(ANSI(...))；
    在 patch_stdout(raw=True) 下 sys.stdout 为 StdoutProxy，纯 print 输出完全等价。
    """
    print(text)


def print_error(message: str):
    _cprint(f"{_BOLD_RED}Error:{_RST} {message}")


def print_budget_warning(used: int, max_iter: int):
    _cprint(f"\n{_GOLD}⚠ Iteration budget exhausted ({used}/{max_iter}). Task may be incomplete.{_RST}")


# ── 工具结果判定（CLI 与桌面共用）────────────────────────────────────────────

def _detect_failure_suffix(result: str) -> str:
    """根据工具结果首行判断失败，返回 ANSI 着色后缀（终端用）。"""
    if not result:
        return ""
    first_line = result.split('\n', 1)[0]
    exit_match = re.search(r'\[exit (\d+)\]', first_line)
    if exit_match and exit_match.group(1) != "0":
        return f" {_BOLD_RED}[exit {exit_match.group(1)}]{_RST}"
    if result.startswith("Error:") or result.startswith("BLOCKED:") or result.startswith("DENIED"):
        return f" {_BOLD_RED}[error]{_RST}"
    return ""


def _detect_status(result: str) -> str:
    """根据工具结果首行粗略判断成功/失败（桌面工具卡片着色用）。"""
    if not result:
        return "ok"
    first = result.strip().split("\n", 1)[0].lower()
    if first.startswith(("error", "failed", "exception", "denied", "permission", "traceback")):
        return "error"
    if first.startswith("skipped"):
        return "warn"
    return "ok"


# ── Diff 渲染 ──────────────────────────────────────────────────────────────────

def render_diff(old_content: str, new_content: str, path: str):
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    lines = list(diff)
    if not lines:
        return

    max_lines = 40
    _cprint(f"{_INDENT}{_DIM}┊ diff:{_RST}")
    for i, line in enumerate(lines[:max_lines]):
        line = line.rstrip('\n')
        if line.startswith('+') and not line.startswith('+++'):
            _cprint(f"{_INDENT}  {_GREEN}{line}{_RST}")
        elif line.startswith('-') and not line.startswith('---'):
            _cprint(f"{_INDENT}  {_RED}{line}{_RST}")
        elif line.startswith('@@'):
            _cprint(f"{_INDENT}  {_DIM}{line}{_RST}")
        elif line.startswith('---') or line.startswith('+++'):
            _cprint(f"{_INDENT}  {_DIM}{line}{_RST}")
        else:
            _cprint(f"{_INDENT}  {_DIM}{line}{_RST}")

    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        _cprint(f"{_INDENT}  {_DIM}… {omitted} more lines omitted{_RST}")
