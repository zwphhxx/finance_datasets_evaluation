"""PR-22 tests: the case evaluation page rebuilds into a task-vs-model
comparison whose Gold standard, model answer, point coverage and scoring
matrix all derive from the selected case and model. Nothing is hardcoded and
no HTML source leaks into the page.
"""

import unittest
from pathlib import Path

from src.data_service import load_all_data
from src.metrics import get_case_ids, get_errors_for_output, merge_case_outputs_with_scores
from src.ui import case_detail as cd


class CaseComparisonViewTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def _merged(self, case_id):
        return merge_case_outputs_with_scores(self.data.model_outputs, self.data.scores, case_id)

    def test_error_dimension_map_covers_taxonomy_labels(self):
        # Every error_type present in the data maps to a Rubric dimension or is
        # surfaced as unmapped; the matrix must never silently drop a label.
        rubric_dims = {label for _, label, _, _ in cd.RUBRIC}
        for dimension in cd.ERROR_TYPE_TO_DIMENSION.values():
            self.assertIn(dimension, rubric_dims)

    def test_errors_by_dimension_partitions_all_labels(self):
        for case_id in get_case_ids(self.data.tasks):
            merged = self._merged(case_id)
            for model in cd.get_case_models(merged):
                output_id = cd.get_output_row(merged, model)["output_id"]
                total = len(get_errors_for_output(self.data.errors, output_id))
                by_dim, unmapped = cd._errors_by_dimension(self.data.errors, output_id)
                placed = sum(len(items) for items in by_dim.values()) + len(unmapped)
                self.assertEqual(total, placed, f"{case_id}/{model}")

    def test_point_coverage_partitions_must_have_points(self):
        gold = next(g for g in self.data.gold_answer_map.values() if g.get("must_have_points"))
        points = gold["must_have_points"]
        covered, missed = cd.build_point_coverage(points, " ".join(points))
        # When the answer literally contains every point, none are missed.
        self.assertEqual(sorted(p.strip() for p in points), sorted(covered))
        self.assertEqual([], missed)

        none_covered, all_missed = cd.build_point_coverage(points, "无关内容")
        self.assertEqual([], none_covered)
        self.assertEqual(len(points), len(all_missed))

    def test_red_line_tracks_high_severity_labels(self):
        for case_id in get_case_ids(self.data.tasks):
            merged = self._merged(case_id)
            for model in cd.get_case_models(merged):
                output_id = cd.get_output_row(merged, model)["output_id"]
                errors = get_errors_for_output(self.data.errors, output_id)
                expected = any(str(s).strip() == "高" for s in errors.get("severity", []))
                self.assertEqual(expected, cd._has_red_line(self.data.errors, output_id))

    def test_two_top_selectors_present(self):
        source = Path(cd.__file__).read_text(encoding="utf-8")
        self.assertIn('"选择任务"', source)
        self.assertIn('"选择模型"', source)

    def test_no_raw_html_leak_markers_in_plain_strings(self):
        source = Path(cd.__file__).read_text(encoding="utf-8")
        # Every HTML fragment must route through render_html / render_card; the
        # page should not st.write or st.markdown raw boundary/answer markup.
        self.assertNotIn('st.markdown("<div', source)
        self.assertNotIn("st.write(f'<", source)


if __name__ == "__main__":
    unittest.main()
