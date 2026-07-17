"""model usage boundaries are service-level, risk-aware conclusions."""

import unittest

import pandas as pd

from app.services import conclusions as cc


def _score(case_id: str, model: str, total: int, output_id: str | None = None, **dims):
    row = {
        "id": abs(hash((case_id, model, total))) % 100000,
        "run_id": "RUN-BOUNDARY",
        "output_id": output_id or f"{case_id}-{model}",
        "case_id": case_id,
        "eval_model": model,
        "model_name": model,
        "judge_status": "success",
        "review_status": "confirmed",
        "status": "active",
        "accuracy_score": 27,
        "reasoning_score": 18,
        "coverage_score": 18,
        "evidence_score": 13,
        "expression_score": 13,
        "total_score": total,
        "review_note": "",
    }
    row.update(dims)
    return row


def _live(case_id: str, model: str, status: str, total: int, **dims):
    row = {
        "id": abs(hash((case_id, model, status))) % 100000,
        "run_id": "RUN-BOUNDARY",
        "case_id": case_id,
        "eval_model": model,
        "judge_status": "success",
        "review_status": status,
        "status": "active",
        "accuracy_score": 27,
        "reasoning_score": 18,
        "coverage_score": 18,
        "evidence_score": 13,
        "expression_score": 13,
        "total_score": total,
        "review_note": "",
    }
    row.update(dims)
    return row


def _tasks(*rows):
    return pd.DataFrame(rows, columns=["case_id", "risk_level"])


def _errors(*rows):
    return pd.DataFrame(
        rows,
        columns=["output_id", "case_id", "model_name", "error_type", "severity", "error_description"],
    )


def _boundary_by_model(rows):
    return {row["model_name"]: row for row in rows}


class ModelBoundaryClassificationTests(unittest.TestCase):
    def test_high_average_without_redline_or_weakness_can_be_reference(self):
        scores = pd.DataFrame([
            _score("C1", "model-high", 92),
            _score("C2", "model-high", 90),
        ])

        result = cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks())
        row = _boundary_by_model(result)["model-high"]

        self.assertEqual("可作为初稿参考", row["boundary"])
        self.assertEqual(2, row["sample_count"])
        self.assertFalse(row["has_high_severity_error"])

    def test_positive_risk_wording_does_not_downgrade_structured_scores(self):
        scores = pd.DataFrame([
            _score("C1", "model-positive-note", 92, review_note="风险覆盖全面，无不可接受错误"),
            _score("C2", "model-positive-note", 90, review_note="风险覆盖全面，无不可接受错误"),
        ])

        row = _boundary_by_model(
            cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks())
        )["model-positive-note"]

        self.assertEqual("可作为初稿参考", row["boundary"])
        self.assertFalse(any("评分说明提示" in reason for reason in row["reasons"]))

    def test_positive_review_note_remains_detail_instead_of_main_issue(self):
        scores = pd.DataFrame([
            _score("C1", "model-positive-detail", 92, review_note="风险覆盖全面，无不可接受错误"),
            _score("C2", "model-positive-detail", 90, review_note="风险覆盖全面，无不可接受错误"),
            _score("C3", "model-positive-detail", 91, review_note="风险覆盖全面，无不可接受错误"),
        ])

        row = cc.build_model_issue_summaries(scores, pd.DataFrame(), _tasks())[0]

        self.assertEqual("可作为初稿参考", row["current_suggestion"])
        self.assertNotIn("评分说明提示需谨慎", row["main_issues"])
        self.assertTrue(any("评分说明：风险覆盖全面" in detail for detail in row["detail_basis"]))

    def test_medium_average_requires_caution(self):
        scores = pd.DataFrame([
            _score("C1", "model-mid", 78),
            _score("C2", "model-mid", 72),
        ])

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks()))["model-mid"]

        self.assertEqual("需谨慎参考", row["boundary"])
        self.assertTrue(any("平均分处于中间区间" in reason for reason in row["reasons"]))

    def test_low_average_is_not_evidence(self):
        scores = pd.DataFrame([
            _score("C1", "model-low", 58),
            _score("C2", "model-low", 55),
        ])

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks()))["model-low"]

        self.assertEqual("不可作为依据", row["boundary"])
        self.assertTrue(any("平均分明显偏低" in reason for reason in row["reasons"]))

    def test_high_severity_error_downgrades_high_average(self):
        scores = pd.DataFrame([
            _score("C1", "model-risk", 92, output_id="O1"),
            _score("C2", "model-risk", 90, output_id="O2"),
        ])
        errors = _errors({"output_id": "O1", "case_id": "C1", "model_name": "model-risk",
                          "error_type": "风险遗漏", "severity": "高", "error_description": "遗漏关键风险"})

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, errors, _tasks()))["model-risk"]

        self.assertEqual("需谨慎参考", row["boundary"])
        self.assertTrue(row["has_high_severity_error"])
        self.assertTrue(any("高严重度错误" in reason for reason in row["reasons"]))

    def test_high_risk_task_with_severe_error_is_not_evidence(self):
        scores = pd.DataFrame([
            _score("C1", "model-high-risk", 90, output_id="O1"),
            _score("C2", "model-high-risk", 88, output_id="O2"),
        ])
        errors = _errors({"output_id": "O1", "case_id": "C1", "model_name": "model-high-risk",
                          "error_type": "风险遗漏", "severity": "高", "error_description": "遗漏关键风险"})
        tasks = _tasks({"case_id": "C1", "risk_level": "高"}, {"case_id": "C2", "risk_level": "中"})

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, errors, tasks))["model-high-risk"]

        self.assertEqual("不可作为依据", row["boundary"])
        self.assertTrue(any("高风险任务" in reason for reason in row["reasons"]))

    def test_high_risk_low_score_requires_caution_without_forcing_danger(self):
        scores = pd.DataFrame([
            _score("C1", "model-high-risk-low-score", 52),
            _score("C2", "model-high-risk-low-score", 100),
            _score("C3", "model-high-risk-low-score", 100),
            _score("C4", "model-high-risk-low-score", 100),
        ])
        tasks = _tasks(
            {"case_id": "C1", "risk_level": "高"},
            {"case_id": "C2", "risk_level": "中"},
            {"case_id": "C3", "risk_level": "中"},
            {"case_id": "C4", "risk_level": "低"},
        )

        row = _boundary_by_model(
            cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), tasks)
        )["model-high-risk-low-score"]

        self.assertGreaterEqual(row["avg_total"], cc.BOUNDARY_REFERENCE_FLOOR)
        self.assertEqual("需谨慎参考", row["boundary"])
        self.assertTrue(any("高风险任务" in reason for reason in row["reasons"]))

    def test_weak_dimension_is_reported_in_reasons(self):
        scores = pd.DataFrame([
            _score("C1", "model-weak", 86, coverage_score=8),
            _score("C2", "model-weak", 88, coverage_score=9),
        ])

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks()))["model-weak"]

        self.assertEqual("需谨慎参考", row["boundary"])
        self.assertTrue(row["major_weaknesses"])
        self.assertTrue(any("风险覆盖" in weakness["dimension"] for weakness in row["major_weaknesses"]))

    def test_small_sample_count_limits_conclusion_strength(self):
        scores = pd.DataFrame([_score("C1", "model-single", 94)])

        row = _boundary_by_model(cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame(), _tasks()))["model-single"]

        self.assertEqual("需谨慎参考", row["boundary"])
        self.assertTrue(row["sample_insufficient"])
        self.assertTrue(any("样本数量不足" in reason for reason in row["reasons"]))

    def test_success_ai_scores_enter_boundaries_without_manual_status(self):
        live = pd.DataFrame([
            _live("C1", "pending-model", "pending", 95),
            _live("C1", "confirmed-model", "confirmed", 91),
            _live("C2", "confirmed-model", "confirmed", 90),
        ])
        ai_scores, excluded = cc.split_live_scores(live)

        result = cc.build_model_boundaries(pd.DataFrame(), ai_scores, pd.DataFrame(), _tasks())
        by_model = _boundary_by_model(result)

        self.assertEqual(0, len(excluded))
        self.assertIn("pending-model", by_model)
        self.assertIn("confirmed-model", by_model)

    def test_missing_error_and_risk_columns_do_not_crash(self):
        scores = pd.DataFrame([
            _score("C1", "model-plain", 89),
            _score("C2", "model-plain", 88),
        ])

        result = cc.build_model_boundaries(pd.DataFrame(), scores, pd.DataFrame([{"case_id": "C1"}]), pd.DataFrame())
        row = _boundary_by_model(result)["model-plain"]

        self.assertEqual("可作为初稿参考", row["boundary"])
        self.assertFalse(row["has_high_severity_error"])


if __name__ == "__main__":
    unittest.main()
