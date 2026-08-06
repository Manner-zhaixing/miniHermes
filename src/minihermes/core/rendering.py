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
    """无操作渲染器：需要静默输出的场景（后台 nudge、无头测试）。"""

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
