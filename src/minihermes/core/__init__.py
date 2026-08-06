"""MiniHermes 共享核心：前端无关的 Agent / Provider / 工具 / 会话等能力。

边界规则：
- core 不得 import minihermes.cli、prompt_toolkit、rich（渲染由前端注入）。
- 桌面后端只 import minihermes.core.*，永不 import minihermes.cli。
"""
