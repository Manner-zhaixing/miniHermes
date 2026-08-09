"""
渲染接口：核心与前端之间的事件缝（参考 Aider 的 io.py 思路）。

Agent.run_conversation 接收一个 Renderer 实例，消费流式事件。
终端实现 StreamRenderer（minihermes.cli.renderer）与桌面实现 GuiRenderer
（desktop/backend/gui_renderer.py）都满足该接口（鸭子类型 + Protocol）。
"""

from typing import Protocol


class Renderer(Protocol):
    """流式渲染器接口：Agent 对话循环产出的事件。"""

    def reset(self) -> None: ...

    def on_thinking(self, text: str) -> None: ...

    def on_delta(self, text: str) -> None: ...

    def on_tool_start(self, tool_name: str) -> None: ...

    def on_tool_result(self, tool_name: str, result: str) -> None: ...

    def finalize(self) -> None: ...


class NullRenderer:
    """无操作渲染器：需要静默输出的场景（后台线程、无头测试）。"""

    def reset(self):
        pass

    def on_thinking(self, text: str):
        pass

    def on_delta(self, text: str):
        pass

    def on_tool_start(self, tool_name: str):
        pass

    def on_tool_result(self, tool_name: str, result: str):
        pass

    def finalize(self):
        pass


class ChildRenderer:
    """子代理渲染器（包装器）：把子代理的事件转发给内层 renderer 的 on_child_event 钩子，
    同时累积 self.parts（与前端 part 同构）供持久化。

    内层 renderer 无 on_child_event（如 NullRenderer）时静默跳过转发，但累积始终进行。
    start/end 边界事件由调用方（Agent._execute_tool 的 delegate_task 分支）围绕
    run_delegate 调用显式触发，此处只转发内容事件（thinking/delta/tool_start/tool_result）。
    """

    def __init__(self, inner, child_id: str, task: str = ""):
        self._inner = inner
        self._child_id = child_id
        self._task = task
        self.parts: list[dict] = []

    def _emit(self, event_type: str, payload: dict) -> None:
        hook = getattr(self._inner, "on_child_event", None)
        if hook is None:
            return
        hook(self._child_id, self._task, event_type, payload)

    def reset(self):
        pass

    def on_thinking(self, text: str):
        self.parts.append({"type": "thinking", "text": text})
        self._emit("thinking", {"text": text})

    def on_delta(self, text: str):
        self.parts.append({"type": "text", "text": text})
        self._emit("delta", {"text": text})

    def on_tool_start(self, tool_name: str):
        self.parts.append({"type": "tool", "name": tool_name, "status": "running", "args": "", "result": ""})
        self._emit("tool_start", {"tool_name": tool_name})

    def on_tool_result(self, tool_name: str, result: str):
        for part in reversed(self.parts):
            if part.get("type") == "tool" and part.get("name") == tool_name and part.get("status") == "running":
                part["status"] = "done"
                part["result"] = result
                break
        self._emit("tool_result", {"tool_name": tool_name, "result": result})

    def finalize(self):
        pass
