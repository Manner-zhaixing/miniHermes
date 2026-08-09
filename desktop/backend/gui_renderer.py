"""
GuiRenderer: 桌面端渲染器。

实现 minihermes.core.rendering.Renderer 接口（Protocol / 鸭子类型）：
    reset / on_thinking / on_delta / on_tool_start / on_tool_result / finalize

职责：把 Agent 对话循环产生的流式事件实时转发到前端 WebSocket，
前端负责实际渲染（Markdown / 思考块 / 工具卡片）。

所有事件携带 session_id，前端据此做会话隔离，避免切换会话后
旧会话的流式事件污染当前视图。

工具结果成败判定复用 minihermes.core.output._detect_status。
"""

from minihermes.core.output import _detect_status


class GuiRenderer:
    """将流式事件通过 send 回调转发到前端。send 必须是线程安全的。"""

    def __init__(self, send, session_id: str):
        self._send = send
        self._sid = session_id

    def reset(self):
        pass

    def on_thinking(self, text: str):
        self._send({"type": "thinking", "text": text, "session_id": self._sid})

    def on_delta(self, text: str):
        self._send({"type": "delta", "text": text, "session_id": self._sid})

    def on_tool_start(self, tool_name: str):
        self._send({
            "type": "tool_start",
            "tool_name": tool_name,
            "session_id": self._sid,
        })

    def on_tool_result(self, tool_name: str, result: str):
        status = _detect_status(result)
        self._send({
            "type": "tool_result",
            "tool_name": tool_name,
            "result": result,
            "status": status,
            "session_id": self._sid,
        })

    def on_child_event(self, child_id: str, task: str, event_type: str, payload: dict) -> None:
        """子代理事件（ChildRenderer 转发）→ subagent_* WS 事件。

        前端默认折叠显示，点击展开查看全部过程。
        """
        base = {
            "type": f"subagent_{event_type}",
            "session_id": self._sid,
            "subagent_id": child_id,
            "task": task,
        }
        if event_type in ("thinking", "delta"):
            self._send({**base, "text": payload.get("text", "")})
        elif event_type == "tool_start":
            self._send({**base, "tool_name": payload.get("tool_name", "")})
        elif event_type == "tool_result":
            self._send({
                **base,
                "tool_name": payload.get("tool_name", ""),
                "result": payload.get("result", ""),
                "status": _detect_status(payload.get("result", "")),
            })
        else:  # start / end
            self._send(base)

    def finalize(self):
        pass
