"""会话绑定工作目录 —— DB 层测试（cwd 列 + 迁移 + 继承 + 查询 + UI 透传）。

隔离 DB（tmp_path 替换 SESSION_DB_PATH），不污染真实 ~/.minihermes/state.db。
"""

from __future__ import annotations

import pytest

from minihermes.core.services.session_service import session_to_ui
from minihermes.core.session import db as db_mod
from minihermes.core.session.db import SessionDB


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
    return SessionDB()


def test_cwd_column_migration(tmp_path, monkeypatch):
    """老库无 cwd 列 → _migrate 自动补列，存量行 NULL 不丢数据。"""
    monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "old.db"))
    old = SessionDB()
    old.create_session("s1", "m")
    # 模拟旧 schema：删掉 cwd 列（SQLite 3.35+ 支持，无约束/索引的纯列可直接删）
    old._conn.execute("ALTER TABLE sessions DROP COLUMN cwd")
    old._conn.commit()
    cols = [r[1] for r in old._conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "cwd" not in cols
    del old
    # 重建实例触发 _migrate
    new = SessionDB()
    cols = [r[1] for r in new._conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "cwd" in cols
    assert new.get_session_cwd("s1") is None  # 存量行 cwd = NULL（归「默认」组）


def test_create_session_with_cwd(db):
    db.create_session("s1", "m", cwd="/proj/a")
    assert db.get_session_cwd("s1") == "/proj/a"


def test_create_session_default_no_cwd(db):
    db.create_session("s1", "m")
    assert db.get_session_cwd("s1") is None


def test_set_session_cwd_rebind(db):
    db.create_session("s1", "m", cwd="/proj/a")
    db.set_session_cwd("s1", "/proj/b")
    assert db.get_session_cwd("s1") == "/proj/b"


def test_child_inherits_parent_cwd(db):
    db.create_session("parent", "m", cwd="/proj/a")
    db.create_child_session("parent", "child", "m")
    assert db.get_session_cwd("child") == "/proj/a"


def test_child_explicit_cwd_overrides(db):
    db.create_session("parent", "m", cwd="/proj/a")
    db.create_child_session("parent", "child", "m", cwd="/proj/z")
    assert db.get_session_cwd("child") == "/proj/z"


def test_child_no_cwd_and_no_parent(db):
    db.create_session("parent", "m")  # 父无 cwd
    db.create_child_session("parent", "child", "m")
    assert db.get_session_cwd("child") is None


def test_message_count_guard_input(db):
    db.create_session("s1", "m")
    assert db.get_session_message_count("s1") == 0
    db.append_message("s1", "user", "hi")
    db.append_message("s1", "assistant", "hello")
    assert db.get_session_message_count("s1") == 2


def test_message_count_missing_session(db):
    assert db.get_session_message_count("nope") is None


def test_list_sessions_includes_cwd(db):
    db.create_session("s1", "m", cwd="/proj/a")
    rows = db.list_sessions(limit=50)
    row = next(r for r in rows if r["id"] == "s1")
    assert row["cwd"] == "/proj/a"


def test_session_to_ui_includes_cwd(db):
    db.create_session("s1", "m", cwd="/proj/a")
    rows = db.list_sessions(limit=50)
    ui = session_to_ui(next(r for r in rows if r["id"] == "s1"))
    assert ui.get("cwd") == "/proj/a"


def test_session_to_ui_cwd_empty_for_null(db):
    db.create_session("s1", "m")
    rows = db.list_sessions(limit=50)
    ui = session_to_ui(next(r for r in rows if r["id"] == "s1"))
    assert ui.get("cwd") == ""
