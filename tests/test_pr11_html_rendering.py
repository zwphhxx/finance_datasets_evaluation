"""PR-11 regression tests: internal HTML must never leak as Markdown code.

Streamlit renders Markdown, which turns any line indented four or more spaces
into a code block and treats a blank line as the end of an HTML block. The
shared render helpers must therefore emit HTML with no indented or blank lines,
otherwise the raw tags show up as code instead of rendered cards.
"""

import sys
import types
import unittest


def _capture_render(call):
    """Run a render helper against a stubbed Streamlit and return emitted HTML."""
    captured = []

    stub = types.ModuleType("streamlit")
    stub.markdown = lambda text, unsafe_allow_html=False: captured.append(text)
    previous = sys.modules.get("streamlit")
    sys.modules["streamlit"] = stub
    try:
        import importlib

        components = importlib.import_module("src.ui.components")
        importlib.reload(components)
        call(components)
    finally:
        if previous is not None:
            sys.modules["streamlit"] = previous
        else:
            sys.modules.pop("streamlit", None)
    return captured


class HtmlRenderingTests(unittest.TestCase):
    def _assert_no_code_block(self, emitted):
        self.assertTrue(emitted, "expected at least one markdown call")
        for block in emitted:
            for line in block.splitlines():
                self.assertFalse(
                    line.startswith(("    ", "\t")),
                    f"indented line would render as code: {line!r}",
                )
                self.assertNotEqual(line, "", "blank line terminates the HTML block")

    def test_render_html_collapses_indentation_and_blanks(self):
        emitted = _capture_render(
            lambda c: c.render_html(
                """
                <div class="context-grid">
                    <div class="context-item">

                        <div class="context-label">边界</div>
                    </div>
                </div>
                """
            )
        )
        self._assert_no_code_block(emitted)
        self.assertIn('<div class="context-grid">', emitted[0])

    def test_grid_loop_and_boundary_fragments_are_not_code_blocks(self):
        cases = [
            lambda c: c.render_context_grid([("本页回答", "评测"), ("数据边界", "MVP")]),
            lambda c: c.render_loop_rail(["专业任务", "Gold Answer", "Rubric 评分"]),
            lambda c: c.render_answer_boundary_panel(
                "回答边界", [("覆盖要点", "现金流"), ("红线", "无")]
            ),
            lambda c: c.render_page_header("标题", "副标题"),
            lambda c: c.render_metric_card("任务样本", 12, "脱敏样本"),
        ]
        for case in cases:
            self._assert_no_code_block(_capture_render(case))

    def test_model_answer_card_preserves_multiline_content(self):
        emitted = _capture_render(
            lambda c: c.render_model_answer_card(
                "GPT-X", "第一段\n第二段", "75", "扣分A\n扣分B", "领域: 金融"
            )
        )
        self._assert_no_code_block(emitted)
        html = emitted[0]
        for token in ("第一段", "第二段", "扣分A", "扣分B", "75", "<br>"):
            self.assertIn(token, html)

    def test_global_styles_hide_dev_chrome(self):
        import src.ui.components as components

        for selector in ('stDeployButton', "#MainMenu", "footer"):
            self.assertIn(selector, components.STYLE_CSS)


if __name__ == "__main__":
    unittest.main()
