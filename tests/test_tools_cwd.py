"""工具层按会话绑定目录执行 —— bash / files 相对路径解析测试。

桌面端多会话并行：不同目录的会话同时跑 turn，工具相对路径必须按
thread-local cwd（runtime_ctx）锚定；CLI 无 thread-local → 回退 os.getcwd()。
"""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

from minihermes.core.agent import runtime_ctx
from minihermes.core.tools import files
from minihermes.core.tools.bash import bash


# ── bash ───────────────────────────────────────────────────────────────────

def test_bash_uses_thread_cwd(tmp_path, monkeypatch):
    called = {}

    def fake_run(command, shell, capture_output, text, timeout, cwd):
        called["command"] = command
        called["cwd"] = cwd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runtime_ctx.set_current_cwd(str(tmp_path))
    try:
        out = bash("echo hi")
        assert out == "ok"
    finally:
        runtime_ctx.set_current_cwd("")
    assert called["command"] == "echo hi"
    assert called["cwd"] == str(tmp_path)


def test_bash_fallback_process_cwd(tmp_path, monkeypatch):
    called = {}

    def fake_run(command, shell, capture_output, text, timeout, cwd):
        called["cwd"] = cwd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
    runtime_ctx.set_current_cwd("")  # CLI：无 thread-local cwd
    bash("ls")
    assert called["cwd"] == str(tmp_path)


# ── files ──────────────────────────────────────────────────────────────────

def test_write_file_relative_uses_thread_cwd(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    runtime_ctx.set_current_cwd(str(sess))
    try:
        res = files.write_file("notes.md", "hello")
        assert res.startswith("Successfully")
        assert (sess / "notes.md").exists()
        assert not (tmp_path / "notes.md").exists()
    finally:
        runtime_ctx.set_current_cwd("")


def test_read_file_relative_uses_thread_cwd(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    (sess / "a.txt").write_text("content")
    runtime_ctx.set_current_cwd(str(sess))
    try:
        out = files.read_file("a.txt")
        assert "content" in out
    finally:
        runtime_ctx.set_current_cwd("")


def test_list_dir_relative_uses_thread_cwd(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    (sess / "f.txt").write_text("x")
    runtime_ctx.set_current_cwd(str(sess))
    try:
        out = files.list_dir(".")
        assert "f.txt" in out
    finally:
        runtime_ctx.set_current_cwd("")


def test_absolute_path_ignores_thread_cwd(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    target = tmp_path / "other" / "abs.txt"
    target.parent.mkdir()
    runtime_ctx.set_current_cwd(str(sess))
    try:
        files.write_file(str(target), "abs")
        assert target.exists()
        assert not (sess / "abs.txt").exists()
    finally:
        runtime_ctx.set_current_cwd("")


def test_files_fallback_process_cwd(tmp_path, monkeypatch):
    """CLI：无 thread-local cwd → 相对路径回退 os.getcwd()（行为逐字节不变）。"""
    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
    runtime_ctx.set_current_cwd("")
    res = files.write_file("fallback.txt", "hi")
    assert res.startswith("Successfully")
    assert (tmp_path / "fallback.txt").exists()
