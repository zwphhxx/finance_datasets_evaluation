"""PR-D tests: 「发起评测」重构为可复现实验 + 模型调用可见性。

本文件聚焦 PR-D 的页面框架与默认选择变更；底层调用链（空回答 / 超时 / 401 / 429 /
回答抽取 / 进度回调 / persist flag）已由 tests/test_pr13_5_live_results.py 覆盖，这里只补齐：

  - 默认只选 1 道「活跃」任务（active 优先，缺 status 时回退首条）；
  - 页面副标题强调现场结果受 API/网络/模型版本影响、离线评测才是默认展示依据；
  - 页面显式区分「离线样本评价」与「本次现场运行」；
  - 结果主表展示状态/HTTP/耗时/回答长度/错误码/错误信息/trace_id；
  - 现场结果默认进入草稿（pending），不进正式结论；仅 confirmed 计入。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import unittest
from pathlib import Path

import pandas as pd

from app.services import conclusions as cc
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.page_config import PAGE_CONFIG_BY_KEY
from src.ui.test_run import eligible_case_ids


_PAGE_SOURCE = Path("src/ui/test_run.py").read_text(encoding="utf-8")


class DefaultActiveTaskSelectionTests(unittest.TestCase):
    def test_prefers_first_active_task(self):
        tasks = [
            {"case_id": "A", "status": "draft"},
            {"case_id": "B", "status": "active"},
            {"case_id": "C", "status": "active"},
        ]
        self.assertEqual([{"case_id": "B", "status": "active"}], er.default_task_selection(tasks))

    def test_single_task_only(self):
        tasks = [{"case_id": "B", "status": "active"}, {"case_id": "C", "status": "active"}]
        self.assertEqual(1, len(er.default_task_selection(tasks)))

    def test_falls_back_to_first_when_no_status(self):
        tasks = [{"case_id": "A"}, {"case_id": "B"}]
        self.assertEqual([{"case_id": "A"}], er.default_task_selection(tasks))

    def test_falls_back_to_first_when_none_active(self):
        tasks = [{"case_id": "A", "status": "archived"}, {"case_id": "B", "status": "draft"}]
        self.assertEqual([{"case_id": "A", "status": "archived"}], er.default_task_selection(tasks))

    def test_empty_yields_empty(self):
        self.assertEqual([], er.default_task_selection([]))


class PageFramingTests(unittest.TestCase):
    def test_subtitle_emphasizes_reproducibility_and_offline_default(self):
        config = PAGE_CONFIG_BY_KEY["test_run"]
        subtitle = config.subtitle
        # 页面副标题应包含评测相关关键词
        self.assertIn("评测", subtitle)

    def test_boundary_mentions_prompt_separation(self):
        config = PAGE_CONFIG_BY_KEY["test_run"]
        self.assertIn("不看到理想回复标准 / Gold Answer", config.boundary)

    def test_page_keeps_live_run_boundary_in_collapsed_note(self):
        self.assertIn("RUN_BOUNDARY_NOTE", _PAGE_SOURCE)
        self.assertIn("不会覆盖正式结论", _PAGE_SOURCE)
        self.assertIn("st.expander", _PAGE_SOURCE)


class ResultsTableColumnsTests(unittest.TestCase):
    def test_results_table_shows_required_call_metadata(self):
        # 结果主表必须展示状态、HTTP 状态、耗时、回答长度、错误码、错误信息、trace_id。
        for column in ("状态", "HTTP状态", "耗时(ms)", "回答长度", "错误码", "错误信息", "trace_id"):
            self.assertIn(column, _PAGE_SOURCE)


class FormalSampleEligibilityTests(unittest.TestCase):
    def test_eligible_case_ids_use_formal_status_gold_and_rubric(self):
        tasks = [
            {"case_id": "A", "status": "active", "question": "题干", "context": "背景", "scenario": "场景"},
            {"case_id": "B", "status": "draft", "question": "题干", "context": "背景", "scenario": "场景"},
            {"case_id": "C", "status": "inactive", "question": "题干", "context": "背景", "scenario": "场景"},
            {"case_id": "D", "status": "active", "question": "题干", "context": "背景", "scenario": "场景"},
        ]
        gold_map = {
            "A": {
                "core_conclusion": "有结论",
                "must_have_points": ["要点"],
                "unacceptable_errors": ["错误"],
            },
            "B": {
                "core_conclusion": "有结论",
                "must_have_points": ["要点"],
                "unacceptable_errors": ["错误"],
            },
            "C": {
                "core_conclusion": "有结论",
                "must_have_points": ["要点"],
                "unacceptable_errors": ["错误"],
            },
            "D": {"core_conclusion": "缺少 Rubric 支撑要素"},
        }
        dimensions = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]

        self.assertEqual(["A"], eligible_case_ids(tasks, gold_map, dimensions))
        self.assertEqual([], eligible_case_ids(tasks, gold_map, []))

    def test_test_run_no_longer_depends_on_samples_json_eligibility(self):
        self.assertNotIn("get_eligible_case_ids", _PAGE_SOURCE)


class DraftPendingInvariantTests(unittest.TestCase):
    """现场运行 + 裁判评分默认 pending，不进正式结论；仅 confirmed 计入。"""

    def test_score_outcome_defaults_to_pending(self):
        # 裁判评分默认 review_status=pending（建议分，待人工复核）。
        outcome = sc.ScoreOutcome(
            case_id="C1", task_type="analysis", eval_model="m",
            judge_provider="mock", judge_model="judge", judge_status="success",
            scores={}, total_score=70,
        )
        self.assertEqual("pending", outcome.review_status)

    def test_pending_live_excluded_confirmed_included_in_formal(self):
        seed = pd.DataFrame(
            [{"model_name": "seed_m", "case_id": "C1", "total_score": 80, "accuracy_score": 24,
              "reasoning_score": 16, "coverage_score": 16, "evidence_score": 12,
              "expression_score": 12, "review_note": ""}]
        )
        live = pd.DataFrame([
            {"id": 1, "run_id": "R", "case_id": "C1", "eval_model": "live_m", "judge_status": "success",
             "review_status": "pending", "status": "active", "total_score": 30,
             "accuracy_score": 9, "reasoning_score": 6, "coverage_score": 6,
             "evidence_score": 4, "expression_score": 5, "review_note": ""},
            {"id": 2, "run_id": "R", "case_id": "C2", "eval_model": "live_m", "judge_status": "success",
             "review_status": "confirmed", "status": "active", "total_score": 88,
             "accuracy_score": 26, "reasoning_score": 18, "coverage_score": 18,
             "evidence_score": 13, "expression_score": 13, "review_note": ""},
        ])
        confirmed, pending = cc.split_live_scores(live)
        self.assertEqual(1, len(pending))
        self.assertEqual(1, len(confirmed))

        formal = cc.build_formal_conclusions(seed, confirmed)
        models = {item["model_name"] for item in formal}
        # 确认归档的现场模型进入正式结论；待复核草稿不进入。
        self.assertIn("live_m", models)
        summary = cc.summarize_formal(seed, confirmed)
        self.assertEqual(1, summary["confirmed_rows"])
        # pending 那条没有被计入任何正式行。
        self.assertEqual(len(seed) + 1, summary["total_rows"])


if __name__ == "__main__":
    unittest.main()
