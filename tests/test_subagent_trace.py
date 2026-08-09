"""子代理过程透传 + todo 渲染配套核心测试。

覆盖：
- ChildRenderer：转发 on_child_event + 累积 parts + 无钩子时静默跳过
- GuiRenderer.on_child_event → subagent_* WS 事件映射
- db.py subagent_trace 列：append → get_messages 解析还原 / get_messages_for_llm 剥离净化
- Agent delegate_task 分支：renderer 透传 + start/end 边界 + trace 落盘
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from minihermes.core.agent.agent import Agent
from minihermes.core.agent.delegate import DelegationResult
from minihermes.core.provider.provider import Provider
from minihermes.core.rendering import ChildRenderer
from minihermes.core.session import db as db_mod
from minihermes.core.session.db import SessionDB

BACKEND_DIR = Path(__file__).resolve().parent.parent / "desktop" / "backend"


# ── ChildRenderer ──────────────────────────────────────────────────────────

class _Spy:
    def __init__(self):
        self.events = []

    def on_child_event(self, child_id, task, event_type, payload):
        self.events.append((child_id, task, event_type, payload))


class TestChildRenderer:
    def test_forwards_and_accumulates(self):
        spy = _Spy()
        cr = ChildRenderer(spy, child_id="abc123", task="写接口")
        cr.on_thinking("分析需求")
        cr.on_delta("产出草稿")
        cr.on_tool_start("write_file")
        cr.on_tool_result("write_file", "written ok")

        # 转发事件（start/end 由 Agent 触发，这里只转发内容事件）
        assert [e[2] for e in spy.events] == ["thinking", "delta", "tool_start", "tool_result"]
        assert spy.events[0][0] == "abc123" and spy.events[0][1] == "写接口"
        assert spy.events[1][3] == {"text": "产出草稿"}

        # parts 累积，tool 结果回填到同名 running 片段
        assert cr.parts[0] == {"type": "thinking", "text": "分析需求"}
        assert cr.parts[1] == {"type": "text", "text": "产出草稿"}
        tool_part = cr.parts[2]
        assert tool_part["type"] == "tool"
        assert tool_part["name"] == "write_file"
        assert tool_part["status"] == "done"
        assert tool_part["result"] == "written ok"

    def test_multiple_tools_pair_by_name_reverse(self):
        spy = _Spy()
        cr = ChildRenderer(spy, child_id="x", task="t")
        cr.on_tool_start("bash")
        cr.on_tool_start("bash")          # 连续两次同名调用
        cr.on_tool_result("bash", "first result")
        assert cr.parts[-1]["result"] == "first result"   # 只回填最后一个 running
        assert cr.parts[-2]["status"] == "running"

    def test_silent_when_inner_has_no_hook(self):
        cr = ChildRenderer(object(), child_id="x", task="t")
        cr.on_delta("hi")                # 不抛异常
        assert cr.parts == [{"type": "text", "text": "hi"}]

    def test_reset_finalize_noop(self):
        cr = ChildRenderer(_Spy(), child_id="x", task="t")
        cr.reset()
        cr.finalize()                    # 不抛异常


# ── GuiRenderer on_child_event → subagent_* WS ─────────────────────────────

class TestGuiRendererSubagent:
    @pytest.fixture()
    def gui(self, monkeypatch):
        monkeypatch.setattr(db_mod, "SESSION_DB_PATH", "/tmp/_test_gui_state.db")
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        from gui_renderer import GuiRenderer

        ws = []
        return ws, GuiRenderer(ws.append, session_id="s1")

    def test_maps_to_subagent_events(self, gui):
        ws, g = gui
        g.on_child_event("abc", "写接口", "start", {})
        g.on_child_event("abc", "写接口", "thinking", {"text": "思考"})
        g.on_child_event("abc", "写接口", "tool_start", {"tool_name": "bash"})
        g.on_child_event("abc", "写接口", "tool_result", {"tool_name": "bash", "result": "ok"})
        g.on_child_event("abc", "写接口", "end", {})

        assert [e["type"] for e in ws] == [
            "subagent_start", "subagent_thinking", "subagent_tool_start",
            "subagent_tool_result", "subagent_end",
        ]
        assert ws[0]["session_id"] == "s1"
        assert ws[0]["subagent_id"] == "abc"
        assert ws[0]["task"] == "写接口"
        assert ws[1]["text"] == "思考"
        assert ws[3]["tool_name"] == "bash" and ws[3]["status"] == "ok"
        assert ws[4] == {"type": "subagent_end", "session_id": "s1", "subagent_id": "abc", "task": "写接口"}


# ── db.py subagent_trace 落盘 + LLM 净化 ───────────────────────────────────

class TestDbSubagentTrace:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
        return SessionDB()

    def test_append_get_and_llm_sanitize(self, db):
        db.create_session("s1", "m")
        trace = {"task": "写接口", "parts": [{"type": "thinking", "text": "分析"}]}
        db.append_message(
            "s1", role="tool", content="团员回复",
            tool_call_id="call_1", tool_name="delegate_task",
            subagent_trace=json.dumps(trace, ensure_ascii=False),
        )

        # get_messages 解析还原（供前端展示）
        msgs = db.get_messages("s1")
        tool = [m for m in msgs if m.get("role") == "tool"][0]
        assert tool["subagent_trace"] == trace

        # get_messages_for_llm 剥离——trace 绝不进 LLM 历史
        llm = db.get_messages_for_llm("s1")
        assert all("subagent_trace" not in m for m in llm)

    def test_no_trace_key_when_absent(self, db):
        db.create_session("s1", "m")
        db.append_message("s1", role="tool", content="done", tool_call_id="c", tool_name="bash")
        msgs = db.get_messages("s1")
        assert all("subagent_trace" not in m for m in msgs)


# ── Agent delegate_task 分支 ───────────────────────────────────────────────

class _FakeResult:
    finish_reason = "stop"


class TestDelegateTrace:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_mod, "SESSION_DB_PATH", str(tmp_path / "state.db"))
        return SessionDB()

    def test_renderer_passthrough_and_trace_persisted(self, db, mocker):
        agent = Agent(
            provider=Provider({"name": "t", "base_url": "http://127.0.0.1:1/v1"}),
            db=db, auto_approve=True,
        )
        db.create_session("s1", "t")

        events = []

        class SpyRenderer:
            def on_child_event(self, child_id, task, event_type, payload):
                events.append((event_type, payload))

            def on_tool_result(self, tool_name, result):  # _process_tool_call 会调
                pass

        captured = {}

        def _fake_run(request, provider, renderer=None, persona=None):
            captured["renderer"] = renderer
            # 模拟子代理内容事件（真实 run_delegate 会经 ChildRenderer 转发）
            renderer.on_thinking("分析需求")
            renderer.on_delta("产出草稿")
            renderer.on_tool_start("write_file")
            renderer.on_tool_result("write_file", "written ok")
            return DelegationResult(success=True, response="团员回复")

        mocker.patch("minihermes.core.agent.delegate.run_delegate", side_effect=_fake_run)

        tc = {
            "id": "call_1", "type": "function",
            "function": {
                "name": "delegate_task",
                "arguments": json.dumps({"task": "写接口", "context": "", "persona_id": ""}),
            },
        }
        agent._process_tool_call(
            tc, _FakeResult(), messages=[], working_history=[],
            renderer=SpyRenderer(), session_id="s1",
        )

        # renderer 透传：run_delegate 收到的是 ChildRenderer 包装器
        assert captured["renderer"] is not None
        assert type(captured["renderer"]).__name__ == "ChildRenderer"

        # start/end 边界事件（Agent 显式触发）
        ev_types = [e[0] for e in events]
        assert ev_types[0] == "start"
        assert ev_types[-1] == "end"

        # trace 落盘（含子代理过程）
        msgs = db.get_messages("s1")
        tool = [m for m in msgs if m.get("role") == "tool"][0]
        trace = tool["subagent_trace"]
        assert trace["task"] == "写接口"
        assert trace["parts"][0] == {"type": "thinking", "text": "分析需求"}
        assert trace["parts"][2] == {
            "type": "tool", "name": "write_file", "status": "done",
            "args": "", "result": "written ok",
        }

        # 落盘后 trace 弹出（_subagent_traces 不残留）
        assert agent._subagent_traces == {}
