"""评测结论页与结论汇总服务。

覆盖真实运行数据的区分与 AI 结论口径：
  - seed 示例评价不计入评测结论；
  - judge_status=success 的 AI 评分计入评测结论；
  - failed / mock / skipped 记录不计入评测结论；
  - SQLite 不可用时 live 结果回退空表；
  - 模型名变化经展示名映射、字段缺失时不报错。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        "review_note": f"{model} 评分说明",
    }
    defaults = {"accuracy_score": 24, "reasoning_score": 16, "coverage_score": 16,
                "evidence_score": 12, "expression_score": 12}
    defaults.update(scores)
    row.update(defaults)
    return row


def _run_row(run_id, *, created_at, prompt_hash="prompt-a", **overrides):
    row = {
        "run_id": run_id,
        "status": "completed",
        "dataset_version": "v2",
        "dataset_hash": "dataset-a",
        "prompt_hash": prompt_hash,
        "generation_parameters_json": '{"max_tokens": 4096, "temperature": 0.1}',
        "judge_parameters_json": '{"judge_model": "judge-a", "max_tokens": 2048, "temperature": 0.0}',
        "created_at": created_at,
        "updated_at": created_at,
    }
    row.update(overrides)
    return row


def _cohort_score(row_id, run_id, case_id, model, *, updated_at, judge_status="success", **overrides):
    row = {
        "id": row_id,
        "score_run_id": f"SCORE-{run_id}",
        "run_id": run_id,
        "case_id": case_id,
        "eval_model": model,
        "judge_mode": "live",
        "judge_status": judge_status,
        "review_status": "ai_final",
        "status": "active",
        "total_score": 80,
        "created_at": updated_at,
        "updated_at": updated_at,
    }
    row.update(overrides)
    return row


class RegistrationTests(unittest.TestCase):
    def test_page_registered_with_config(self):
        self.assertIn("conclusions", PAGES)
        self.assertIn("conclusions", PAGE_CONFIG_BY_KEY)
        self.assertIn("评测结论", PAGE_CONTEXTS)

    def test_positioning_not_a_leaderboard(self):
        # The formal-conclusion positioning lives in case_study (project intro).
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertIn("当前样本范围", source)
        self.assertIn("使用边界", source)


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
    def test_seed_conclusions_do_not_enter_formal(self):
        seed = _seed_scores()
        conclusions = cc.build_formal_conclusions(seed, pd.DataFrame())
        self.assertEqual([], conclusions)
        summary = cc.summarize_formal(seed, pd.DataFrame())
        self.assertEqual(summary["seed_rows"], 0)
        self.assertEqual(summary["confirmed_rows"], 0)
        self.assertEqual(summary["total_rows"], 0)

    def test_success_ai_score_enters_formal_without_manual_status(self):
        live = pd.DataFrame([_live_row("C1", "live-model", "pending", total=30)])
        ai_scores, excluded = cc.split_live_scores(live)
        self.assertEqual(len(ai_scores), 1)
        self.assertEqual(len(excluded), 0)

        formal = cc.build_formal_conclusions(pd.DataFrame(), ai_scores)
        self.assertTrue(any(item["model_name"] == "live-model" for item in formal))
        summary = cc.summarize_formal(pd.DataFrame(), ai_scores)
        self.assertEqual(summary["ai_score_rows"], 1)

    def test_ai_scores_enters_formal(self):
        live = pd.DataFrame([_live_row("C1", "live-model", "confirmed", total=88)])
        ai_scores, _ = cc.split_live_scores(live)
        self.assertEqual(len(ai_scores), 1)

        formal = cc.build_formal_conclusions(pd.DataFrame(), ai_scores, mapping={"live-model": "现场模型"})
        live_items = [item for item in formal if item["model_name"] == "live-model"]
        self.assertEqual(len(live_items), 1)
        self.assertEqual(live_items[0]["display_name"], "现场模型")
        self.assertEqual(live_items[0]["confirmed_count"], 1)

        summary = cc.summarize_formal(pd.DataFrame(), ai_scores)
        self.assertEqual(summary["ai_score_rows"], 1)
        self.assertEqual(summary["seed_rows"], 0)
        self.assertEqual(summary["total_rows"], 1)

    def test_mixed_pending_and_confirmed_split(self):
        live = pd.DataFrame([
            _live_row("C1", "m", "confirmed", total=80),
            _live_row("C2", "m", "pending", total=40),
            _live_row("C3", "m", "mock_should_drop", total=10),  # 非 success 由 judge_status 过滤
        ])
        live.loc[2, "judge_status"] = "mock"
        ai_scores, excluded = cc.split_live_scores(live)
        self.assertEqual(len(ai_scores), 2)
        self.assertEqual(len(excluded), 1)

    def test_mock_judge_mode_never_enters_conclusions_even_with_success_status(self):
        live = pd.DataFrame([_live_row("C1", "mock-mode", "ai_final", total=90)])
        live.loc[0, "judge_mode"] = "mock"

        ai_scores, excluded = cc.split_live_scores(live)

        self.assertTrue(ai_scores.empty)
        self.assertEqual(1, len(excluded))

    def test_runtime_score_summary_explains_live_status_counts(self):
        live = pd.DataFrame([
            _live_row("C1", "vendor/live-a", "confirmed", total=80),
            _live_row("C2", "vendor/live-a", "pending", total=70),
            _live_row("C3", "vendor/live-b", "skipped", total=50),
            _live_row("C4", "Model_A_baseline", "confirmed", total=99),
        ])
        summary = cc.summarize_runtime_scores(live)

        self.assertEqual("SQLite 运行期数据", summary["data_source"])
        self.assertEqual(2, summary["total"])
        self.assertEqual(2, summary["ai_scores"])
        self.assertEqual(1, summary["excluded"])
        self.assertEqual(1, summary["models"])
        self.assertEqual(2, summary["cases"])

    def test_conclusion_page_uses_data_maintenance_dialog(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        notice_source = source[
            source.index("def _render_data_source_notice"):
            source.index("@st.dialog(\"AI 评测结果数据\"")
        ]
        dialog_source = source[source.index("@st.dialog(\"AI 评测结果数据\""):]

        self.assertIn("当前结论来源：", notice_source)
        self.assertIn("data_source", notice_source)
        self.assertIn('"数据维护"', notice_source)
        self.assertNotIn("st.download_button", notice_source)
        self.assertNotIn("file_uploader", notice_source)
        self.assertIn("导出 AI 评测结果", dialog_source)
        self.assertIn("导入评分文件", dialog_source)
        self.assertIn("从演示结果文件恢复", dialog_source)


class CompatibleCohortTests(unittest.TestCase):
    def test_compatible_runs_merge_even_when_json_key_order_differs(self):
        runs = pd.DataFrame([
            _run_row("RUN-OLD", created_at="2026-07-16T10:00:00"),
            _run_row(
                "RUN-NEW",
                created_at="2026-07-17T10:00:00",
                generation_parameters_json='{"temperature":0.1,"max_tokens":4096}',
                judge_parameters_json='{"temperature":0.0,"max_tokens":2048,"judge_model":"judge-a"}',
            ),
        ])
        scores = pd.DataFrame([
            _cohort_score(1, "RUN-OLD", "C1", "model-old", updated_at="2026-07-16T11:00:00"),
            _cohort_score(2, "RUN-NEW", "C1", "model-new", updated_at="2026-07-17T11:00:00"),
        ])

        selected = cc.select_current_cohort_scores(runs, scores)
        ai_scores, excluded = cc.split_live_scores(selected)

        self.assertEqual({"model-old", "model-new"}, set(ai_scores["eval_model"]))
        self.assertTrue(excluded.empty)

    def test_latest_incompatible_prompt_becomes_baseline_and_excludes_old_run(self):
        runs = pd.DataFrame([
            _run_row("RUN-OLD", created_at="2026-07-16T10:00:00", prompt_hash="prompt-old"),
            _run_row("RUN-NEW", created_at="2026-07-17T10:00:00", prompt_hash="prompt-new"),
        ])
        scores = pd.DataFrame([
            _cohort_score(1, "RUN-OLD", "C1", "model-old", updated_at="2026-07-16T11:00:00"),
            _cohort_score(2, "RUN-NEW", "C1", "model-new", updated_at="2026-07-17T11:00:00"),
        ])

        selected = cc.select_current_cohort_scores(runs, scores)
        ai_scores, _ = cc.split_live_scores(selected)

        self.assertEqual(["RUN-NEW"], ai_scores["run_id"].tolist())

    def test_latest_success_wins_and_newer_failure_does_not_replace_it(self):
        runs = pd.DataFrame([
            _run_row("RUN-A", created_at="2026-07-16T10:00:00"),
            _run_row("RUN-B", created_at="2026-07-17T10:00:00"),
        ])
        scores = pd.DataFrame([
            _cohort_score(10, "RUN-A", "C1", "same-model", updated_at="2026-07-16T11:00:00"),
            _cohort_score(11, "RUN-B", "C1", "same-model", updated_at="2026-07-17T11:00:00"),
            _cohort_score(
                12,
                "RUN-B",
                "C1",
                "same-model",
                updated_at="2026-07-17T12:00:00",
                judge_status="failed",
                score_run_id="SCORE-RETRY",
            ),
        ])

        selected = cc.select_current_cohort_scores(runs, scores)
        ai_scores, excluded = cc.split_live_scores(selected)

        self.assertEqual([11], ai_scores["id"].tolist())
        self.assertEqual([12], excluded["id"].tolist())

    def test_database_id_breaks_ties_between_equally_timed_successes(self):
        runs = pd.DataFrame([
            _run_row("RUN-A", created_at="2026-07-17T10:00:00"),
        ])
        scores = pd.DataFrame([
            _cohort_score(
                21,
                "RUN-A",
                "C1",
                "same-model",
                updated_at="2026-07-17T11:00:00",
                score_run_id="SCORE-NEWER-ID",
            ),
            _cohort_score(
                20,
                "RUN-A",
                "C1",
                "same-model",
                updated_at="2026-07-17T11:00:00",
                score_run_id="SCORE-OLDER-ID",
            ),
        ])

        selected = cc.select_current_cohort_scores(runs, scores)
        ai_scores, _ = cc.split_live_scores(selected)

        self.assertEqual([21], ai_scores["id"].tolist())

    def test_missing_required_run_metadata_never_guesses_a_cohort(self):
        runs = pd.DataFrame([
            _run_row("RUN-MISSING", created_at="2026-07-17T10:00:00", prompt_hash=""),
        ])
        scores = pd.DataFrame([
            _cohort_score(1, "RUN-MISSING", "C1", "model-a", updated_at="2026-07-17T11:00:00"),
        ])

        selected = cc.select_current_cohort_scores(runs, scores)

        self.assertTrue(selected.empty)

    def test_loader_reads_runs_and_scores_before_selecting_current_cohort(self):
        tables = {
            "live_evaluation_runs": [_run_row("RUN-A", created_at="2026-07-17T10:00:00")],
            "live_run_scores": [
                _cohort_score(1, "RUN-A", "C1", "model-a", updated_at="2026-07-17T11:00:00")
            ],
        }

        class Store:
            def list_rows(self, table):
                return tables[table]

        with patch("app.persistence.get_result_store", return_value=Store()):
            selected = cc.load_current_cohort_scores()

        self.assertEqual(["model-a"], selected["eval_model"].tolist())


class AnswerDetailJoinTests(unittest.TestCase):
    def test_answers_join_by_run_case_and_model_without_cross_run_leakage(self):
        scores = pd.DataFrame([
            _cohort_score(
                1,
                "RUN-A",
                "C1",
                "same-model",
                updated_at="2026-07-16T11:00:00",
                total_score=81,
            ),
            _cohort_score(
                2,
                "RUN-B",
                "C1",
                "same-model",
                updated_at="2026-07-17T11:00:00",
                total_score=92,
            ),
        ])
        responses = pd.DataFrame([
            {
                "run_id": "RUN-A",
                "case_id": "C1",
                "model_name": "same-model",
                "answer_text": "回答 A",
            },
            {
                "run_id": "RUN-B",
                "case_id": "C1",
                "model_name": "same-model",
                "answer_text": "回答 B",
            },
        ])

        rows = cc.build_answer_detail_rows(scores, responses)

        by_run = {row["run_id"]: row for row in rows}
        self.assertEqual("回答 A", by_run["RUN-A"]["answer_text"])
        self.assertEqual("回答 B", by_run["RUN-B"]["answer_text"])
        self.assertEqual(81.0, by_run["RUN-A"]["total_score"])
        self.assertEqual(92.0, by_run["RUN-B"]["total_score"])

    def test_missing_answer_stays_visible_as_empty_detail(self):
        scores = pd.DataFrame([
            _cohort_score(
                1,
                "RUN-A",
                "C1",
                "model-a",
                updated_at="2026-07-16T11:00:00",
            )
        ])

        rows = cc.build_answer_detail_rows(scores, pd.DataFrame())

        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["answer_text"])

    def test_conclusion_page_loads_and_renders_persisted_answers(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        render_source = source[
            source.index("def render_conclusions_page"):
            source.index("# --------------------------------------------------------------------------- #")
        ]
        detail_source = source[
            source.index("def _render_model_issue_details"):
        ]

        self.assertIn("cc.load_live_responses()", render_source)
        self.assertIn("cc.build_answer_detail_rows", render_source)
        self.assertIn("answer_rows", render_source)
        self.assertIn('"选择样本查看回答"', detail_source)
        self.assertIn("render_markdown_detail_panel", detail_source)
        self.assertIn('row.get("answer_text")', detail_source)


class AiFinalPageTests(unittest.TestCase):
    def test_conclusion_page_no_longer_uses_session_draft_fallback(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        self.assertNotIn("_session_draft_rows", source)
        self.assertNotIn("build_page_draft_rows", source)
        self.assertIn("暂无 AI 评分结果", source)


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
        # 缺少部分维度列的 confirmed live 风格表：仍应聚合 total 并把缺失维度置 None。
        partial = pd.DataFrame([
            {"eval_model": "m", "case_id": "C1", "total_score": 70, "accuracy_score": 20, "review_note": ""}
        ])
        formal = cc.build_formal_conclusions(pd.DataFrame(), partial)
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
        live = pd.DataFrame([
            _live_row("C1", "live-model", "confirmed", total=55, coverage_score=5),
            _live_row("C2", "live-model", "confirmed", total=58, coverage_score=6),
        ])
        confirmed, _ = cc.split_live_scores(live)
        combined = cc.combine_formal_scores(data.scores, confirmed)
        issues = cc.summarize_frequent_issues(combined, data.errors, ["回答较笼统"])
        self.assertTrue(issues)
        self.assertTrue(any("达成率" in issue for issue in issues))


class ModelIssueSummaryTests(unittest.TestCase):
    def test_model_issue_summaries_are_model_scoped(self):
        live = pd.DataFrame([
            _live_row("C1", "vendor/model-a", "confirmed", total=88, coverage_score=8),
            _live_row("C2", "vendor/model-a", "confirmed", total=86, coverage_score=9),
            _live_row("C3", "vendor/model-b", "confirmed", total=58, evidence_score=4),
            _live_row("C4", "vendor/model-b", "confirmed", total=56, evidence_score=5),
        ])
        confirmed, _ = cc.split_live_scores(live)

        rows = cc.build_model_issue_summaries(confirmed, pd.DataFrame(), pd.DataFrame())
        by_model = {row["model_name"]: row for row in rows}

        self.assertIn("vendor/model-a", by_model)
        self.assertIn("vendor/model-b", by_model)
        self.assertTrue(any("风险覆盖" in issue for issue in by_model["vendor/model-a"]["main_issues"]))
        self.assertTrue(any("依据可靠性" in issue for issue in by_model["vendor/model-b"]["main_issues"]))
        self.assertEqual("model-a", by_model["vendor/model-a"]["display_name"])
        self.assertEqual("样本不足，暂不形成判断", by_model["vendor/model-b"]["current_suggestion"])

    def test_model_issue_summary_marks_insufficient_sample(self):
        live = pd.DataFrame([_live_row("C1", "vendor/model-single", "confirmed", total=94)])
        confirmed, _ = cc.split_live_scores(live)

        rows = cc.build_model_issue_summaries(confirmed, pd.DataFrame(), pd.DataFrame())

        self.assertEqual(1, len(rows))
        self.assertEqual("样本不足，暂不形成判断", rows[0]["current_suggestion"])
        self.assertTrue(any("样本数不足" in issue for issue in rows[0]["main_issues"]))


class RenderTests(unittest.TestCase):
    def test_page_renders_without_exception(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        at.session_state["current_page"] = "conclusions"
        at.run()
        self.assertEqual(list(at.exception), [])


if __name__ == "__main__":
    unittest.main()
