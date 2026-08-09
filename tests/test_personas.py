"""专家（Persona）系统单测 —— 锁定核心行为与「无专家逐字节兼容」。

覆盖：
- parse_persona_md 解析 / 严格校验（ManifestError）
- PersonaRegistry 双源扫描 + 覆盖顺序 + team 成员惰性解析
- build_system_prompt 无 persona 逐字节兼容 + 专家注入 + 白名单引导 + skills 过滤
- Agent.apply_persona 工具白名单交集 / 退出恢复
- db.py persona_id CRUD + 压缩子会话继承
"""

from __future__ import annotations

import textwrap

import pytest

from minihermes.core.agent.agent import Agent, ConversationResult
from minihermes.core.agent.delegate import DelegationRequest, run_delegate, CHILD_BLOCKED_TOOLS
from minihermes.core.personas import (
    build_member_prompt,
    build_team_roster,
    parse_persona_md,
    PersonaManifest,
    PersonaRegistry,
)
from minihermes.core.personas import registry as persona_registry_mod
from minihermes.core.personas.manifest import ManifestError
from minihermes.core.provider.provider import Provider
from minihermes.core.prompt import builder as builder_mod
from minihermes.core.prompt.builder import build_system_prompt
from minihermes.core.session import db as db_mod
from minihermes.core.session.db import SessionDB
from minihermes.core.tools import get_tool_manager


# ── 工具函数 ────────────────────────────────────────────────────────────

def _write_md(tmp_path, name, frontmatter: str, body: str = "你是一个测试专家。\n\n准则：如实交付。"):
    p = tmp_path / name
    p.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return p


def _agent_with_persona(persona=None) -> Agent:
    prov = Provider({"name": "test-model", "base_url": "http://127.0.0.1:1/v1"})
    return Agent(provider=prov, persona=persona)


def _schema_names(agent: Agent) -> set[str]:
    """OpenAI function-calling schema 结构：{"type","function":{"name",...}}"""
    return {s["function"]["name"] for s in agent._get_tool_schemas()}


# ── parse_persona_md ─────────────────────────────────────────────────────

class TestParsePersonaMd:
    def test_valid_agent(self, tmp_path):
        md = _write_md(
            tmp_path, "writer.md",
            "id: doc-writer\nname: 文档写手\nicon: 📝\ntagline: 把想法写成文档\n"
            "tools: read_file, write_file\nskills: code-review\n",
        )
        m = parse_persona_md(md)
        assert m.id == "doc-writer"
        assert m.name == "文档写手"
        assert m.expert_type == "agent"
        assert m.soul_mode == "replace"
        assert m.source == "builtin"
        assert m.tools == ["read_file", "write_file"]
        assert m.skills == ["code-review"]
        assert "测试专家" in m.system_prompt
        assert not m.is_team()

    def test_team_defaults_lead_id(self, tmp_path):
        md = _write_md(
            tmp_path, "team.md",
            "id: dev-team\nname: 开发团\nexpert_type: team\n"
            "members: backend-coder, frontend-coder\n",
        )
        m = parse_persona_md(md)
        assert m.is_team()
        assert m.lead_id == "dev-team"       # 默认 = id
        assert m.members == ["backend-coder", "frontend-coder"]
        assert m.max_team_iterations == 50

    def test_missing_id(self, tmp_path):
        md = _write_md(tmp_path, "bad.md", "name: 无名\n")
        with pytest.raises(ManifestError, match="id"):
            parse_persona_md(md)

    def test_invalid_id(self, tmp_path):
        md = _write_md(tmp_path, "bad.md", "id: 中文/路径\nname: x\n")
        with pytest.raises(ManifestError, match="非法"):
            parse_persona_md(md)

    def test_bad_expert_type(self, tmp_path):
        md = _write_md(tmp_path, "bad.md", "id: x\nname: x\nexpert_type: swarm\n")
        with pytest.raises(ManifestError, match="expert_type"):
            parse_persona_md(md)

    def test_bad_soul_mode(self, tmp_path):
        md = _write_md(tmp_path, "bad.md", "id: x\nname: x\nsoul_mode: prepend\n")
        with pytest.raises(ManifestError, match="soul_mode"):
            parse_persona_md(md)

    def test_empty_body(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_text("---\nid: x\nname: x\n---\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="正文"):
            parse_persona_md(p)


# ── PersonaRegistry ──────────────────────────────────────────────────────

class TestRegistry:
    def _registry(self, tmp_path, monkeypatch, extra=None):
        # 隔离本地目录，避免读到真实 ~/.minihermes/personas/
        local = tmp_path / "local"
        local.mkdir(exist_ok=True)
        monkeypatch.setattr(persona_registry_mod, "LOCAL_DIR", local)
        return PersonaRegistry(builtin_dir=tmp_path / "builtin", extra_dirs=extra)

    def test_scan_and_extra_overrides_builtin(self, tmp_path, monkeypatch):
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        _write_md(builtin, "a.md", "id: a\nname: A 内置\n")
        _write_md(builtin, "b.md", "id: b\nname: B\n")
        extra = tmp_path / "extra"
        extra.mkdir()
        _write_md(extra, "a.md", "id: a\nname: A 本地覆盖\n")

        reg = self._registry(tmp_path, monkeypatch, extra=[extra])
        names = reg.names()
        assert "a" in names and "b" in names
        assert reg.get("a").name == "A 本地覆盖"   # 后扫描覆盖先扫描
        assert reg.get("b").name == "B"

    def test_team_resolve_members_missing_dropped(self, tmp_path, monkeypatch):
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        _write_md(builtin, "lead.md", "id: lead\nexpert_type: team\nmembers: ok-member, ghost\n")
        _write_md(builtin, "ok.md", "id: ok-member\nname: OK\n")

        reg = self._registry(tmp_path, monkeypatch)
        lead = reg.get("lead")
        assert lead is not None
        ids = [m.id for m in lead.resolved_members]
        assert ids == ["ok-member"]              # ghost 缺失被剔除

    def test_local_dir_created(self, tmp_path, monkeypatch):
        local = tmp_path / "local"
        monkeypatch.setattr(persona_registry_mod, "LOCAL_DIR", local)
        PersonaRegistry(builtin_dir=tmp_path / "builtin")
        assert local.is_dir()


# ── build_system_prompt ──────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def _tools(self) -> set:
        return set(get_tool_manager().get_names())

    def test_byte_compatible_without_persona(self, tmp_path, monkeypatch):
        """无专家时 persona=None 与旧签名输出逐字节一致。"""
        tools = self._tools()
        base = build_system_prompt(model_name="m", memory_store=None, cwd=str(tmp_path), tool_names=tools)
        with_persona_none = build_system_prompt(
            model_name="m", memory_store=None, cwd=str(tmp_path), tool_names=tools, persona=None,
        )
        assert base == with_persona_none

    def test_persona_replace_is_sole_identity(self, tmp_path):
        """soul_mode=replace 时专家正文=唯一身份（不叠加默认人格）。"""
        tools = self._tools()
        persona = PersonaManifest(id="p", name="P", soul_mode="replace",
                                  system_prompt="【专家身份】我是专用角色")
        out = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools, persona=persona)
        assert "【专家身份】我是专用角色" in out
        # 默认人格不应出现在替换模式下
        assert builder_mod.DEFAULT_IDENTITY.strip() not in out

    def test_persona_stack_keeps_soul(self, tmp_path):
        tools = self._tools()
        persona = PersonaManifest(id="p", name="P", soul_mode="stack",
                                  system_prompt="【叠加角色】我是补充角色")
        out = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools, persona=persona)
        assert "【叠加角色】我是补充角色" in out
        assert builder_mod.DEFAULT_IDENTITY.strip() in out

    def test_guidance_only_for_whitelist_tools(self, tmp_path):
        """白名单外已注册工具不注入行为引导（避免"有指引无工具"）。"""
        tools = self._tools()
        # doc-writer 只白名单 read_file/write_file/list_dir/skill_view —— 不含 todo/delegate_task
        persona = PersonaManifest(
            id="doc", name="doc",
            tools=["read_file", "write_file", "list_dir", "skill_view"],
            system_prompt="doc body",
        )
        out = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools, persona=persona)
        assert "Task delegation" not in out
        assert "Task planning with todo" not in out
        # 含 memory 白名单的专家则有对应引导
        persona2 = PersonaManifest(id="doc2", name="doc2", tools=["memory"], system_prompt="b")
        out2 = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools, persona=persona2)
        assert "persistent memory across sessions" in out2

    def test_skills_only_names_passed(self, tmp_path, mocker):
        """persona.skills 非空 → _build_filtered_skills_index 收到 only_names 并旁路缓存。"""
        tools = self._tools()
        persona = PersonaManifest(id="p", name="P", skills=["code-review"],
                                  system_prompt="body")
        spy = mocker.spy(builder_mod, "_build_filtered_skills_index")
        out = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools, persona=persona)
        assert spy.called
        assert spy.call_args.kwargs.get("only_names") == {"code-review"}
        assert "code-review" in out

    def test_team_roster_injected(self, tmp_path):
        tools = self._tools()
        member = PersonaManifest(id="m1", name="M1", tagline="后端")
        lead = PersonaManifest(id="lead", name="Lead", expert_type="team",
                               members=["m1"], system_prompt="lead body")
        lead.resolved_members = [member]
        roster = build_team_roster(lead)
        assert roster and "m1" in roster and "delegate_task" in roster
        out = build_system_prompt(model_name="m", cwd=str(tmp_path), tool_names=tools,
                                  persona=lead, team_roster=roster)
        assert "Team Roster" in out
        assert "m1" in out

    def test_member_prompt_suffix(self):
        member = PersonaManifest(id="m", name="M", system_prompt="成员正文")
        prompt = build_member_prompt(member)
        assert prompt.startswith("成员正文")
        assert "团队协作规则" in prompt


# ── Agent.apply_persona ──────────────────────────────────────────────────

class TestAgentPersona:
    def test_no_persona_all_tools(self):
        agent = _agent_with_persona()
        all_names = set(get_tool_manager().get_names())
        assert _schema_names(agent) == all_names

    def test_whitelist_intersection(self, tmp_path):
        """persona.tools 声明 2 个工具 → _get_tool_schemas 只返回这 2 个。"""
        persona = PersonaManifest(id="p", name="P",
                                  tools=["read_file", "write_file"],
                                  system_prompt="b")
        agent = _agent_with_persona(persona)
        assert _schema_names(agent) == {"read_file", "write_file"}

    def test_apply_persona_and_deactivate(self, tmp_path):
        all_names = set(get_tool_manager().get_names())
        agent = _agent_with_persona()
        persona = PersonaManifest(id="p", name="P", tools=["read_file"], system_prompt="b")
        agent.apply_persona(persona)
        assert _schema_names(agent) == {"read_file"}
        assert agent.persona_id == "p"
        # 退出专家 → 全工具恢复
        agent.apply_persona(None)
        assert agent.persona_id == ""
        assert _schema_names(agent) == all_names

    def test_apply_persona_reloads_system_prompt(self, tmp_path):
        persona = PersonaManifest(id="p", name="P", system_prompt="【专属】我的身份")
        agent = _agent_with_persona()
        assert "【专属】我的身份" not in agent.system_prompt
        agent.apply_persona(persona)
        assert "【专属】我的身份" in agent.system_prompt


# ── team 运行时（run_delegate persona 分支）────────────────────────────────

class TestTeamRuntime:
    def test_run_delegate_persona_branch(self, mocker):
        """团员委派：子 Agent 用 build_member_prompt 作 system prompt + 团员白名单 + 迭代预算。"""
        member = PersonaManifest(
            id="backend-coder", name="后端码农", tagline="Go 后端",
            tools=["read_file", "write_file"], system_prompt="成员正文", max_team_iterations=30,
        )
        prov = Provider({"name": "t", "base_url": "http://127.0.0.1:1/v1"})
        req = DelegationRequest(task="实现一个接口", context="需求描述", tools_exclude={"bash"})

        fake_agent = mocker.MagicMock()
        fake_agent.run_conversation.return_value = ConversationResult(
            final_response="团员完成", reasoning="", messages=[]
        )
        fake_agent._ctx.budget_used = 3
        patched = mocker.patch("minihermes.core.agent.agent.Agent", return_value=fake_agent)

        res = run_delegate(req, prov, renderer=object(), persona=member)

        assert res.success
        assert res.response == "团员完成"
        # 捕获子 Agent 构造传参
        _, kwargs = patched.call_args
        assert kwargs["persona"] is member
        assert kwargs["system_prompt_override"] == build_member_prompt(member)
        assert "团队协作规则" in kwargs["system_prompt_override"]
        assert kwargs["max_iterations_override"] == 30
        assert kwargs["tool_filter"] == {"exclude": set(CHILD_BLOCKED_TOOLS) | {"bash"}}
        # 用户消息携带任务上下文
        user_msg = fake_agent.run_conversation.call_args.kwargs["user_message"]
        assert "需求描述" in user_msg and "实现一个接口" in user_msg


# ── db.py persona_id ─────────────────────────────────────────────────────

class TestDbPersona:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
        return SessionDB()

    def test_crud_and_child_inherit(self, db):
        db.create_session("s1", "m", persona_id="doc-writer")
        assert db.get_persona("s1") == "doc-writer"

        # 压缩子会话继承 parent 的 persona_id（压缩不丢专家）
        db.create_child_session(parent_id="s1", child_id="s2", model="m")
        assert db.get_persona("s2") == "doc-writer"

        # 显式覆盖继承
        db.create_child_session(parent_id="s1", child_id="s3", model="m", persona_id="dev-team")
        assert db.get_persona("s3") == "dev-team"

        # 解绑恢复默认
        db.set_persona("s1", None)
        assert db.get_persona("s1") is None

    def test_list_sessions_includes_persona(self, db):
        db.create_session("s1", "m", persona_id="doc-writer")
        db.create_session("s2", "m")
        by_id = {s["id"]: s for s in db.list_sessions()}
        assert by_id["s1"]["persona_id"] == "doc-writer"
        assert by_id["s2"]["persona_id"] is None
