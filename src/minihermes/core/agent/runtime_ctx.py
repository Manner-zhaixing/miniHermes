"""线程局部「当前会话」上下文。

桌面后端多会话并行：每个 turn 跑在独立 daemon 线程，
SessionRuntime 在锁内 set / finally clear，线程天然隔离。

- sid：当前线程服务的会话 id（多会话并行事件归因、todo 分桶）
- cwd：当前线程服务的会话所绑定的工作目录
  （工具 bash/files/@file 解析相对路径时使用；不同目录的会话可并行安全执行）

CLI 从不调用 set_current_sid() / set_current_cwd() → 恒返回 ""，行为与旧版一致
（工具层回退 os.getcwd()，即进程全局目录）。
"""

import threading

_local = threading.local()


def set_current_sid(sid: str):
    """设置当前线程正在服务的会话 id（桌面后端每个 turn 线程调用）。"""
    _local.sid = sid


def current_sid() -> str:
    """返回当前线程的会话 id；未设置（CLI / 非 turn 线程）返回空串。"""
    return getattr(_local, "sid", "") or ""


def set_current_cwd(cwd: str):
    """设置当前线程服务的会话所绑定的工作目录（桌面后端每个 turn 线程调用）。"""
    _local.cwd = cwd


def current_cwd() -> str:
    """返回当前线程的会话工作目录；未设置（CLI）返回空串 → 工具回退 os.getcwd()。"""
    return getattr(_local, "cwd", "") or ""
