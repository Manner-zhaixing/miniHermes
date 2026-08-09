"""CLI `/persona` 命令单测 —— 列表 / 详情 / 切换 / 退出。

核心行为（apply_persona / db.set_persona）由 test_personas.py 锁定，
这里验证 CLI 层接线（_handle_persona_command 的解析 + 状态持久化）。
"""

from __future__ import annotations

import pytest

from minihermes.cli.conversation import _handle_persona_command, _handle_slash_commands
from minihermes.cli.state import AppState
from minihermes.core.agent.agent import Agent
from minihermes.core.personas import get_persona_registry
from minihermes.core.provider.provider import Provider
from minihermes.core.session import db as db_mod
from minihermes.core.session.db import SessionDB


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
    return SessionDB()


@pytest.fixture()
def state(db):
    s = AppState()
    s.session_id = "cli-session"
    db.create_session("cli-session", "m")
    return s


@pytest.fixture()
def agent():
    prov = Provider({"name": "m", "base_url": "http://127.0.0.1:1/v1"})
    return Agent(provider=prov)


class TestPersonaCommand:
    def test_list(self, state, db, agent, capsys):
        _handle_persona_command("/persona", state, db, agent)
        out = capsys.readouterr().out
        assert "doc-writer" in out and "research-analyst" in out and "dev-team" in out
        # 未激活：无 active 标记
        assert "◀ active" not in out

    def test_list_marks_active(self, state, db, agent, capsys):
        state.current_persona_id = "doc-writer"
        _handle_persona_command("/persona list", state, db, agent)
        out = capsys.readouterr().out
        assert "doc-writer" in out and "◀ active" in out

    def test_view(self, state, db, agent, capsys):
        _handle_persona_command("/persona view doc-writer", state, db, agent)
        out = capsys.readouterr().out
        assert "doc-writer" in out
        assert "工具白名单" in out and "read_file" in out

    def test_view_unknown(self, state, db, agent, capsys):
        _handle_persona_command("/persona view ghost", state, db, agent)
        assert "unknown persona" in capsys.readouterr().out

    def test_activate(self, state, db, agent, capsys):
        _handle_persona_command("/persona activate doc-writer", state, db, agent)
        out = capsys.readouterr().out
        assert "activated" in out
        assert state.current_persona_id == "doc-writer"
        assert db.get_persona("cli-session") == "doc-writer"
        assert agent.persona_id == "doc-writer"

    def test_deactivate_restores(self, state, db, agent, capsys):
        _handle_persona_command("/persona activate doc-writer", state, db, agent)
        capsys.readouterr()
        _handle_persona_command("/persona deactivate", state, db, agent)
        assert "deactivated" in capsys.readouterr().out
        assert state.current_persona_id == ""
        assert db.get_persona("cli-session") is None
        assert agent.persona_id == ""

    def test_unknown_subcommand(self, state, db, agent, capsys):
        _handle_persona_command("/persona frobnicate", state, db, agent)
        assert "unknown /persona subcommand" in capsys.readouterr().out

    def test_resolve_uses_registry(self):
        # 内置专家必须可被 registry 解析（desktop/CLI 共用同一单例）
        m = get_persona_registry().resolve("dev-team")
        assert m is not None and m.is_team()
        assert {x.id for x in m.resolved_members} >= {"backend-coder", "frontend-coder", "code-reviewer"}


class TestClearResumeInheritance:
    """/clear 新建会话继承当前专家；/resume 恢复会话自带专家。"""

    def test_clear_inherits_persona(self, state, db, agent, mocker):
        state.current_persona_id = "doc-writer"
        # mock handle_slash_command：/clear 会先建新会话再返回新 sid
        db.create_session("new-sid", "m")
        mocker.patch("minihermes.cli.conversation.handle_slash_command",
                     return_value=(True, [], "new-sid", ""))
        _handle_slash_commands("/clear", agent, state, db, "m")
        assert db.get_persona("new-sid") == "doc-writer"

    def test_clear_without_persona_no_inherit(self, state, db, agent, mocker):
        # 无专家时 /clear 不写 persona（兼容原行为）
        db.create_session("new-sid", "m")
        mocker.patch("minihermes.cli.conversation.handle_slash_command",
                     return_value=(True, [], "new-sid", ""))
        _handle_slash_commands("/clear", agent, state, db, "m")
        assert db.get_persona("new-sid") is None

    def test_resume_restores_persona(self, state, db, agent, mocker):
        db.create_session("resume-sid", "m", persona_id="research-analyst")
        mocker.patch("minihermes.cli.conversation.handle_slash_command",
                     return_value=(True, [], "resume-sid", ""))
        _handle_slash_commands("/resume resume-sid", agent, state, db, "m")
        assert agent.persona_id == "research-analyst"
        assert state.current_persona_id == "research-analyst"

    def test_resume_plain_session_clears_persona(self, state, db, agent, mocker):
        # 先激活专家，再 resume 一个无专家会话 → 退出专家
        state.current_persona_id = "doc-writer"
        agent.apply_persona(get_persona_registry().resolve("doc-writer"))
        db.create_session("plain-sid", "m")
        mocker.patch("minihermes.cli.conversation.handle_slash_command",
                     return_value=(True, [], "plain-sid", ""))
        _handle_slash_commands("/resume plain-sid", agent, state, db, "m")
        assert agent.persona_id == ""
        assert state.current_persona_id == ""
