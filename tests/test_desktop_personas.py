"""桌面后端专家接口 —— 隔离 DB 测试（不污染真实 ~/.minihermes/state.db）。

验证：
- GET /api/personas 返回内置专家
- POST /api/sessions 携带 persona_id 建会话
- Kernel._apply_persona_for_session 懒应用 / 幂等 / 退出 / 未知 id 降级
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from minihermes.core.session import db as db_mod

BACKEND_DIR = Path(__file__).resolve().parent.parent / "desktop" / "backend"


@pytest.fixture()
def server_mod(tmp_path, monkeypatch):
    """把 server 模块装载到 sys.path 并隔离 DB 路径。"""
    monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import server
    return server


@pytest.fixture()
def kernel(server_mod):
    ws_calls = []

    def _ws(payload):
        ws_calls.append(payload)

    k = server_mod.Kernel(ws_send=_ws)
    return k


class TestPersonaApi:
    def test_get_personas(self, server_mod, kernel, monkeypatch):
        monkeypatch.setattr(server_mod, "get_kernel", lambda: kernel)
        client = TestClient(server_mod.app)
        res = client.get("/api/personas")
        assert res.status_code == 200
        personas = res.json()["personas"]
        assert personas, "应至少返回内置专家"
        by_id = {p["id"]: p for p in personas}
        assert "doc-writer" in by_id
        assert "dev-team" in by_id                      # 内置团队专家
        d = by_id["doc-writer"]
        assert d["name"] and d["expert_type"] == "agent"
        assert d["system_prompt"]                        # 完整角色正文（桌面详情页滚动展示）

    def test_new_session_with_persona_http(self, server_mod, kernel, monkeypatch):
        monkeypatch.setattr(server_mod, "get_kernel", lambda: kernel)
        client = TestClient(server_mod.app)
        res = client.post("/api/sessions", json={"persona_id": "research-analyst"})
        assert res.status_code == 200
        data = res.json()
        sid = data["session_id"]
        assert data["persona_id"] == "research-analyst"
        assert kernel.db.get_persona(sid) == "research-analyst"


class TestApplyPersonaForSession:
    def test_idempotent_lazy_apply(self, kernel):
        # 无专家会话：apply 后仍无专家（无变化）
        sid = kernel.new_session()
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == ""

        # 绑定 doc-writer → apply 生效
        kernel.db.set_persona(sid, "doc-writer")
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == "doc-writer"
        # 幂等：再次 apply 跳过（persona_id 不变）
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == "doc-writer"

        # 解绑 → apply 退出专家
        kernel.db.set_persona(sid, None)
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == ""

    def test_unknown_persona_degrades(self, kernel):
        sid = kernel.new_session()
        kernel.db.set_persona(sid, "ghost-persona")
        # 未知 id → resolve 降级为无专家，不抛断
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == ""

    def test_switch_agent_to_team(self, kernel):
        """普通会话 → dev-team：主理人花名册注入（system prompt 含 Team Roster）。"""
        sid = kernel.new_session()
        assert kernel.agent.persona_id == ""
        kernel.db.set_persona(sid, "dev-team")
        kernel._apply_persona_for_session(sid)
        assert kernel.agent.persona_id == "dev-team"
        assert "Team Roster" in kernel.agent.system_prompt
        assert kernel.agent.team_roster
