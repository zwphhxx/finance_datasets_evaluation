"""PR-B tests: 评测结论页与结论汇总服务。

覆盖三类数据的区分与正式结论口径：
  - seed 已有结论计入正式结论；
  - pending live 草稿不计入正式结论；
  - confirmed live 结论计入正式结论；
  - SQLite 不可用时仍可只用 seed 展示（load_live_scores 回退空表）；
  - 模型名变化经展示名映射、字段缺失时不报错。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.services import conclusions as cc
from src.data_service import load_all_data
from src.ui.navigation import PAGES
from src.ui.page_config import PAGE_CONFIG_BY_KEY, PAGE_CONTEXTS


def _seed_scores():
    return load_all_data().scores


def _live_row(case_id, model, status, total=80, **scores):
    row = {
        "id": abs(hash((case_id, model, status))) % 100000,
        "run_id": "RUN-X",
        "case_id": case_id,
        "eval_model": model,
        "judge_status": "success",
        "review_status": status,
        "status": "active",
        "total_score": total,
        "review_note": f"{model} 复核说明",
    }
    defaults = {"accuracy_score": 24, "reasoning_score": 16, "coverage_score": 16,
                "evidence_score": 12, "expression_score": 12}
    defaults.update(scores)
    row.update(defaults)
    return row


class RegistrationTests(unittest.TestCase):
    def test_page_registered_with_config(self):
        self.assertIn("evaluation_conclusions", PAGES)
        self.assertIn("evaluation_conclusions", PAGE_CONFIG_BY_KEY)
        self.assertIn("评测结论", PAGE_CONTEXTS)

    def test_positioning_not_a_leaderboard(self):
        source = Path("src/ui/evaluation_conclusions.py").read_text(encoding="utf-8")
        self.assertIn("不是模型排行榜", source)
        self.assertIn("可用边界", source)


class DisplayNameTests(unittest.TestCase):
    def test_mapping_used_then_falls_back_to_original(self):
        self.assertEqual("展示名", cc.display_model_name("raw", {"raw": "展示名"}))
        self.assertEqual("raw", cc.display_model_name("raw", {}))
        self.assertEqual("raw", cc.display_model_name("raw"))

    def test_blank_or_nan_name_is_placeholder(self):
        self.assertEqual("未标注模型", cc.display_model_name(None))
        self.assertEqual("未标注模型", cc.display_model_name(float("nan")))
        self.assertEqual("未标注模型", cc.display_model_name("  "))


class FormalConclusionTests(unittest.TestCase):
    def test_seed_conclusions_enter_formal(self):
        seed = _seed_scores()
        conclusions = cc.build_formal_conclusions(seed, pd.DataFrame())
        self.assertTrue(conclusions)
        for item in conclusions:
            self.assertGreater(item["seed_count"], 0)
            self.assertEqual(item["confirmed_count"], 0)
        summary = cc.summarize_formal(seed, pd.DataFrame())
        self.assertEqual(summary["seed_rows"], len(seed))
        self.assertEqual(summary["confirmed_rows"], 0)

    def test_pending_live_excluded_from_formal(self):
        live = pd.DataFrame([_live_row("C1", "live-model", "pending", total=30)])
        confirmed, pending = cc.split_live_scores(live)
        self.assertEqual(len(confirmed), 0)
        self.assertEqual(len(pending), 1)

        formal = cc.build_formal_conclusions(_seed_scores(), confirmed)
        self.assertFalse(any(item["model_name"] == "live-model" for item in formal))
        summary = cc.summarize_formal(_seed_scores(), confirmed)
        self.assertEqual(summary["confirmed_rows"], 0)

    def test_confirmed_live_enters_formal(self):
        live = pd.DataFrame([_live_row("C1", "live-model", "confirmed", total=88)])
        confirmed, _ = cc.split_live_scores(live)
        self.assertEqual(len(confirmed), 1)

        formal = cc.build_formal_conclusions(_seed_scores(), confirmed, mapping={"live-model": "现场模型"})
        live_items = [item for item in formal if item["model_name"] == "live-model"]
        self.assertEqual(len(live_items), 1)
        self.assertEqual(live_items[0]["display_name"], "现场模型")
        self.assertEqual(live_items[0]["confirmed_count"], 1)

        summary = cc.summarize_formal(_seed_scores(), confirmed)
        self.assertEqual(summary["confirmed_rows"], 1)
        self.assertEqual(summary["seed_rows"], len(_seed_scores()))

    def test_mixed_pending_and_confirmed_split(self):
        live = pd.DataFrame([
            _live_row("C1", "m", "confirmed", total=80),
            _live_row("C2", "m", "pending", total=40),
            _live_row("C3", "m", "mock_should_drop", total=10),  # 非 success 由 judge_status 过滤
        ])
        live.loc[2, "judge_status"] = "mock"
        confirmed, pending = cc.split_live_scores(live)
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(len(pending), 1)


class DraftRowTests(unittest.TestCase):
    def test_build_draft_rows_joins_answer_and_marks_pending(self):
        pending = pd.DataFrame([_live_row("C1", "live-model", "pending", total=42)])
        responses = pd.DataFrame([
            {"run_id": "RUN-X", "case_id": "C1", "model_name": "live-model", "answer_text": "现场回答内容"}
        ])
        rows = cc.build_draft_rows(pending, responses, mapping={"live-model": "现场模型"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["display_name"], "现场模型")
        self.assertEqual(rows[0]["answer_text"], "现场回答内容")
        self.assertEqual(rows[0]["review_status"], "pending")
        self.assertEqual(rows[0]["total_score"], 42)

    def test_build_draft_rows_handles_missing_responses(self):
        pending = pd.DataFrame([_live_row("C1", "live-model", "pending")])
        rows = cc.build_draft_rows(pending, None)
        self.assertEqual(rows[0]["answer_text"], "")


class RobustnessTests(unittest.TestCase):
    def test_all_empty_inputs_do_not_error(self):
        self.assertEqual(cc.build_formal_conclusions(pd.DataFrame(), pd.DataFrame()), [])
        self.assertEqual(cc.build_draft_rows(pd.DataFrame()), [])
        confirmed, pending = cc.split_live_scores(pd.DataFrame())
        self.assertTrue(confirmed.empty)
        self.assertTrue(pending.empty)
        summary = cc.summarize_formal(pd.DataFrame(), pd.DataFrame())
        self.assertEqual(summary["total_rows"], 0)
        self.assertEqual(cc.summarize_frequent_issues(pd.DataFrame()), [])

    def test_missing_dimension_columns_are_tolerated(self):
        # 缺少部分维度列的 seed 风格表：仍应聚合 total 并把缺失维度置 None。
        partial = pd.DataFrame([
            {"model_name": "m", "case_id": "C1", "total_score": 70, "accuracy_score": 20, "review_note": ""}
        ])
        formal = cc.build_formal_conclusions(partial, pd.DataFrame())
        self.assertEqual(len(formal), 1)
        self.assertIsNotNone(formal[0]["dimensions"]["accuracy_score"])
        self.assertIsNone(formal[0]["dimensions"]["coverage_score"])

    def test_load_live_scores_returns_empty_when_db_unavailable(self):
        missing = Path(tempfile.gettempdir()) / "definitely_missing_findueval.db"
        self.assertTrue(cc.load_live_scores(missing).empty)
        self.assertTrue(cc.load_live_responses(missing).empty)


class FrequentIssuesTests(unittest.TestCase):
    def test_issues_derived_from_dimensions_and_errors(self):
        data = load_all_data()
        combined = cc.combine_formal_scores(data.scores, pd.DataFrame())
        issues = cc.summarize_frequent_issues(combined, data.errors, ["回答较笼统"])
        self.assertTrue(issues)
        self.assertTrue(any("达成率" in issue for issue in issues))


class RenderTests(unittest.TestCase):
    def test_page_renders_without_exception(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        at.session_state["current_page"] = "evaluation_conclusions"
        at.run()
        self.assertEqual(list(at.exception), [])


if __name__ == "__main__":
    unittest.main()
