import unittest
from pathlib import Path


class UIUXAuditFixesTests(unittest.TestCase):
    def test_overview_has_evaluation_loop_rail_steps(self):
        from src.ui.overview import get_evaluation_loop_steps
        import src.ui.components as components

        expected = [
            "专业任务",
            "Gold Answer",
            "模型回答",
            "Rubric 评分",
            "错误归因",
            "数据补强",
            "优化验证",
        ]
        self.assertEqual(expected, get_evaluation_loop_steps())
        self.assertTrue(hasattr(components, "render_loop_rail"))
        self.assertIn(".loop-rail", components.STYLE_CSS)
        self.assertIn(".loop-step", components.STYLE_CSS)

        overview_source = Path("src/ui/overview.py").read_text(encoding="utf-8")
        self.assertIn("render_loop_rail", overview_source)

    def test_pages_use_compact_context_summary(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_context_summary"))
        self.assertIn(".context-grid", components.STYLE_CSS)
        self.assertIn(".context-item", components.STYLE_CSS)

        for file_path in [
            "src/ui/overview.py",
            "src/ui/tasks.py",
            "src/ui/case_detail.py",
            "src/ui/model_diagnosis.py",
            "src/ui/error_analysis.py",
            "src/ui/optimization_compare.py",
        ]:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertIn("render_context_summary", source, file_path)


if __name__ == "__main__":
    unittest.main()
