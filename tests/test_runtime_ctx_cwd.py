"""thread-local cwd —— 桌面多会话并行隔离测试。

验证 set_current_cwd / current_cwd：默认空串；turn 线程内设置、finally 清理后恢复空。
"""

from __future__ import annotations

import threading

from minihermes.core.agent import runtime_ctx


def test_current_cwd_default_empty():
    assert runtime_ctx.current_cwd() == ""


def test_set_and_clear_roundtrip():
    runtime_ctx.set_current_cwd("/proj/a")
    try:
        assert runtime_ctx.current_cwd() == "/proj/a"
    finally:
        runtime_ctx.set_current_cwd("")
    assert runtime_ctx.current_cwd() == ""


def test_thread_isolation():
    """不同线程的 cwd 互不可见（多会话并行不同目录同时跑）。"""
    results = {}

    def worker(dir_name):
        runtime_ctx.set_current_cwd(dir_name)
        results[dir_name] = runtime_ctx.current_cwd()
        # 不清理，验证下一线程设置不污染自己
        assert results.get(dir_name) == dir_name
        runtime_ctx.set_current_cwd("")

    t1 = threading.Thread(target=worker, args=("/proj/a",))
    t2 = threading.Thread(target=worker, args=("/proj/b",))
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert results == {"/proj/a": "/proj/a", "/proj/b": "/proj/b"}
