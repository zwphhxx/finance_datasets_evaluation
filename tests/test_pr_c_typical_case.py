"""PR-C tests: 「典型样本拆解」（原样板题深度评测）。

重点覆盖：
  - 模型回答对比（build_case_model_comparison）：逐模型动态推导、空状态、含红线计数；
  - 这道题为什么能测出能力（build_case_rationale）：Gold 锚点与模型分差动态推导；
  - Gold 缺失 / 评分缺失时不崩溃；
  - live / seed 两种数据来源：未运行真实评测时默认展示 seed 评价，不再要求先发起评测；
    有真实运行时可展示本次结果，且不覆盖离线 seed 评价。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import dataclasses
import unittest
import warnings

import pandas as pd

from app.services.live_results import empty_results_evaluation_data
from src.data_service import load_all_data
from src.metrics import get_case_ids, merge_case_outputs_with_scores
from src.ui import case_detail as cd
from src.validators import validate_evaluation_data


def _output_row(model="M", total=None, **dims):
    profile = {
        "accuracy_score": 30,
        "reasoning_score": 20,
        "coverage_score": 20,
        "evidence_score": 15,
        "expression_score": 15,
    }
    profile.update(dims)
    return pd.Series({"output_id": f"OUT-{model}", "model_name": model, "total_score": total, **profile})


class ModelComparisonTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def _merged(self, case_id):
        return merge_case_outputs_with_scores(self.data.model_outputs, self.data.scores, case_id)

    def test_comparison_has_one_row_per_model_with_required_keys(self):
        case_id = get_case_ids(self.data.tasks)[0]
        merged = self._merged(case_id)
        gold = self.data.gold_answer_map.get(case_id)
        rows = cd.build_case_model_comparison(merged, self.data.errors, gold, self.data.optimizations, None)
        self.assertEqual(sorted(r["model_name"] for r in rows), sorted(cd.get_case_models(merged)))
        for row in rows:
            for key in ("model_name", "tier", "title", "level", "score_text", "total", "weakest", "redline_count"):
                self.assertIn(key, row)

    def test_comparison_is_empty_without_outputs(self):
        empty = pd.DataFrame(columns=["output_id", "model_name", "total_score"])
        self.assertEqual([], cd.build_case_model_comparison(empty, self.data.errors, None, self.data.optimizations, None))

    def test_redline_count_tracks_high_severity(self):
        errors = pd.DataFrame(
            [{"output_id": "OUT-M", "error_type": "风险遗漏", "severity": "高", "error_description": "漏报"}],
            columns=["output_id", "error_type", "severity", "error_description"],
        )
        merged = pd.DataFrame([_output_row(model="M", total=90)])
        rows = cd.build_case_model_comparison(merged, errors, {}, pd.DataFrame(), pd.Series({"risk_level": "中"}))
        self.assertEqual(1, rows[0]["redline_count"])
        self.assertEqual("not_direct", rows[0]["tier"])

    def test_comparison_sorted_scored_first_then_by_total(self):
        merged = pd.DataFrame([
            _output_row(model="low", total=40),
            _output_row(model="high", total=92),
            _output_row(model="none", total=None),
        ])
        rows = cd.build_case_model_comparison(merged, pd.DataFrame(), {}, pd.DataFrame(), pd.Series({"risk_level": "中"}))
        self.assertEqual(["high", "low", "none"], [r["model_name"] for r in rows])


class CaseRationaleTests(unittest.TestCase):
    def test_rationale_counts_gold_anchors_and_spread(self):
        gold = {"must_have_points": ["a", "b"], "unacceptable_errors": ["x"]}
        task = pd.Series({"expected_capability": "风险识别", "domain": "FD", "risk_level": "高"})
        comparison = [{"total": 90.0}, {"total": 60.0}]
        rationale = cd.build_case_rationale(task, gold, comparison)
        self.assertEqual(2, rationale["must_count"])
        self.assertEqual(1, rationale["redline_count"])
        self.assertEqual(2, rationale["model_count"])
        self.assertAlmostEqual(30.0, rationale["score_spread"])
        self.assertEqual("风险识别", rationale["capability"])

    def test_rationale_tolerates_missing_gold_and_single_model(self):
        task = pd.Series({"expected_capability": "", "domain": "FD", "risk_level": "中"})
        rationale = cd.build_case_rationale(task, None, [{"total": 70.0}])
        self.assertEqual(0, rationale["must_count"])
        self.assertEqual(0, rationale["redline_count"])
        self.assertIsNone(rationale["score_spread"])

    def test_rationale_tolerates_missing_task(self):
        rationale = cd.build_case_rationale(None, None, [])
        self.assertEqual("", rationale["capability"])
        self.assertEqual(0, rationale["model_count"])


class EmptyStateRenderTests(unittest.TestCase):
    """页面必须在缺 Gold / 缺评分 / 缺模型回答时安全渲染。"""

    def setUp(self):
        warnings.simplefilter("ignore")
        self.base = load_all_data()
        self.validation = validate_evaluation_data(self.base)

    def _bundle(self, data, live, score_run_id=None):
        return {
            "data": data,
            "base": self.base,
            "validation_result": self.validation,
            "eval_status": {"live": live, "run_id": "RUN-1", "score_run_id": score_run_id},
        }

    def test_renders_seed_default_without_live_run(self):
        # 未运行真实评测：data 为空结果，但 base 为 seed，页面应默认拆解 seed 评价。
        empty = empty_results_evaluation_data(self.base)
        cd.render_case_detail_page(self._bundle(empty, False))

    def test_renders_with_live_run(self):
        cd.render_case_detail_page(self._bundle(self.base, True))

    def test_renders_with_no_gold(self):
        no_gold = dataclasses.replace(self.base, gold_answers=[], gold_answer_map={})
        cd.render_case_detail_page(self._bundle(no_gold, True))

    def test_renders_with_no_scores(self):
        no_scores = dataclasses.replace(self.base, scores=self.base.scores.iloc[0:0])
        cd.render_case_detail_page(self._bundle(no_scores, True))


class SeedVsLiveSourceTests(unittest.TestCase):
    """未运行评测时默认展示 seed 评价，且不再短路为“请先发起评测”；有真实运行也能渲染。"""

    def setUp(self):
        warnings.simplefilter("ignore")
        self.base = load_all_data()
        self.validation = validate_evaluation_data(self.base)

    def _bundle(self, data, live):
        return {
            "data": data,
            "base": self.base,
            "validation_result": self.validation,
            "eval_status": {"live": live, "run_id": "RUN-1", "score_run_id": None},
        }

    def _captured_titles(self, bundle):
        """收集页面渲染过程中产生的 section 标题，判断走到了哪条分支（不依赖 Streamlit 运行时）。"""
        titles: list[str] = []
        original = cd.render_section_title
        cd.render_section_title = lambda title, *args, **kwargs: titles.append(title)
        try:
            cd.render_case_detail_page(bundle)
        finally:
            cd.render_section_title = original
        return titles

    def test_seed_default_renders_comparison_without_live_run(self):
        # data 为空结果（未运行），base 为 seed：应默认拆解 seed 评价，而非早退到空状态。
        empty = empty_results_evaluation_data(self.base)
        titles = self._captured_titles(self._bundle(empty, live=False))
        self.assertIn("模型回答对比", titles)
        self.assertIn("这道题为什么能测出模型能力", titles)

    def test_live_run_also_renders_comparison(self):
        titles = self._captured_titles(self._bundle(self.base, live=True))
        self.assertIn("模型回答对比", titles)


if __name__ == "__main__":
    unittest.main()
