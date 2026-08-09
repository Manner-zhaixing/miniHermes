"""输出样式引导：OUTPUT_FORMAT_GUIDANCE 注入 system prompt，且不再禁用 markdown。

覆盖：
- 结构化 markdown + HTML 图引导注入（mermaid 引导已移除）
- CLI_PLATFORM_HINT 去掉「Try not to use markdown」硬禁令
- 引导块位于平台提示之前（末尾高权重区）
"""

from minihermes.core.prompt.builder import build_system_prompt


def _prompt(tmp_path):
    return build_system_prompt(
        model_name="m", memory_store=None, cwd=str(tmp_path), tool_names=set()
    )


class TestOutputFormatGuidance:
    def test_guidance_injected(self, tmp_path):
        sp = _prompt(tmp_path)
        assert "draw a small diagram in raw HTML" in sp
        assert "structured Markdown" in sp
        assert "inline CSS" in sp
        # 画图优先用 HTML
        assert "prefer HTML for diagrams" in sp
        assert "(not Mermaid)" in sp
        # mermaid 引导已替换为 HTML 图引导
        assert "```mermaid" not in sp

    def test_cli_hint_no_longer_forbids_markdown(self, tmp_path):
        sp = _prompt(tmp_path)
        assert "Try not to use markdown" not in sp
        assert "flattened to plain text" in sp

    def test_guidance_before_cli_hint(self, tmp_path):
        sp = _prompt(tmp_path)
        idx_guidance = sp.find("draw a small diagram in raw HTML")
        idx_cli = sp.find("You are a CLI AI Agent")
        assert idx_guidance != -1 and idx_cli != -1
        assert idx_guidance < idx_cli
