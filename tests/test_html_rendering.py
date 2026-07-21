"""HTML rendering helpers must not leak indented markup as code blocks."""

import sys
import types
import unittest


def _capture_render(call):
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
                <div class="detail-panel">
                    <div class="detail-panel-body">

                        <p>正文</p>
                    </div>
                </div>
                """
            )
        )
        self._assert_no_code_block(emitted)
        self.assertIn('<div class="detail-panel">', emitted[0])

    def test_current_fragments_are_not_code_blocks(self):
        cases = [
            lambda c: c.render_page_heading("标题", "副标题"),
            lambda c: c.render_numbered_section("01", "样本列表", "说明"),
            lambda c: c.render_detail_panel("<p>正文</p>", title="标题"),
            lambda c: c.render_inline_status([("本页回答", "评测"), ("数据边界", "当前样本内观察")]),
        ]
        for case in cases:
            self._assert_no_code_block(_capture_render(case))

    def test_global_styles_hide_dev_chrome(self):
        import src.ui.components as components

        for selector in ("stDeployButton", "#MainMenu", "footer"):
            self.assertIn(selector, components.STYLE_CSS)


if __name__ == "__main__":
    unittest.main()
