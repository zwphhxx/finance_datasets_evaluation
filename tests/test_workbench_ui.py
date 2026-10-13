"""Workbench read projections and visible, honest evidence contracts."""

from types import SimpleNamespace

import pandas as pd
from streamlit.testing.v1 import AppTest

from app.services.conclusion_read_model import ConclusionReport, ReportScope


def report():
    scores = pd.DataFrame(
        [
            {
                "run_id": "r",
                "case_id": c,
                "eval_model": m,
                "total_score": 60 + i,
                "judge_status": "success",
                "provider": "siliconflow",
            }
            for i, c in enumerate(["FD001", "LA001", "FD002"])
            for m in ["m1", "m2"]
        ]
    )
    return ConclusionReport(
        ReportScope(3, 2, 6),
        scores,
        pd.DataFrame(),
        (),
        {},
        runtime_tables={
            "live_evaluation_runs": [
                {
                    "run_id": "r",
                    "created_at": "2026-10-01T10:00:00",
                    "provider": "siliconflow",
                    "model_ids_json": '["m1","m2"]',
                }
            ]
        },
    )


def test_overview_counts_real_tasks_and_formal_records_only():
    from src.ui.workbench import overview_facts

    base = SimpleNamespace(
        tasks=pd.DataFrame([{"case_id": "FD001", "domain": "finance"}, {"case_id": "LA001", "domain": "law"}])
    )
    assert overview_facts(base, None) == {"samples": 2, "domains": 2, "models": 0, "scores": 0, "latest": None}
    assert overview_facts(base, report())["scores"] == 6
    assert overview_facts(base, report())["latest"] == "2026-10-01T10:00:00"


def test_filters_preserve_common_denominator_and_original_report():
    from src.ui.workbench import filter_report

    original = report()
    tasks = [
        {"case_id": "FD001", "domain": "finance"},
        {"case_id": "FD002", "domain": "finance"},
        {"case_id": "LA001", "domain": "law"},
    ]
    filtered = filter_report(original, tasks, domain="finance", models=["m1", "m2"])
    assert filtered.scope.formal_score_count == 4
    assert filtered.comparison["common_count"] == 2
    assert not filtered.comparison["sufficient"]
    assert len(original.formal_scores) == 6
    assert filter_report(original, tasks, case_id="missing").scope.formal_score_count == 0


def test_score_detail_has_two_columns_and_never_invents_quote():
    app = AppTest.from_string("""
from src.ui.trust_details import render_score_detail
render_score_detail(
    task={'task':'核查收入', 'business_background':'财务背景'},
    answer='没有回款依据。',
    score={'total_score': 50, 'checks_json': '[{"status":"not_met","requirement":"核实回款","quote":"回款正常","reason":"缺少证据"}]'},
    dimensions=[{'field':'accuracy','name':'准确性','full_mark':100}], key='test')
""").run()
    assert not app.exception
    assert len(app.columns) == 2
    assert any("引用不在" in w.value for w in app.warning)
    assert any("财务背景" in t.value for t in app.text)


def test_default_page_and_query_route_are_overview():
    from src.ui.navigation import PRIMARY_NAV_ITEMS
    from src.ui.page_config import DEFAULT_PAGE_KEY

    assert DEFAULT_PAGE_KEY == "case_study"
    assert PRIMARY_NAV_ITEMS[0] == ("评测概览", "case_study")


def test_no_real_result_empty_state_and_no_provider_calls(monkeypatch):
    import src.ui.workbench as ui

    monkeypatch.setattr(ui.cd, "load_conclusion_source", lambda *a: ui.cd.ConclusionSource(True, None))
    source = ui.load_workbench_source(SimpleNamespace(tasks=pd.DataFrame(), gold_answer_map={}))
    assert source.report is None


def test_redaction_cannot_turn_different_quotes_into_matches():
    from src.ui.trust_details import quote_matches

    assert not quote_matches("sk-BBBBBBBBBBBB", "实际标识 sk-AAAAAAAAAAAA")
    assert not quote_matches("[已脱敏]", "实际标识 [已脱敏]")
    at = AppTest.from_string("""
import json
from src.ui.trust_details import render_score_detail
render_score_detail(task={}, answer='实际标识 sk-AAAAAAAAAAAA',
 score={'checks_json':json.dumps([{'status':'not_met','requirement':'核实标识','quote':'sk-BBBBBBBBBBBB'}])},
 dimensions=[], key='redaction')
""").run()
    assert not at.exception
    assert len(at.warning) == 2  # Main evidence and raw-evidence inspector.
    assert not any("已验证" in c.value for c in at.caption)
    assert "sk-AAAAAAAAAAAA" not in str(at)


def test_filtered_task_rebuilds_evidence_and_keeps_saved_dimensions():
    import json

    from src.ui.workbench import filter_report, historical_dimensions, report_tasks

    r = report()
    context = {
        "samples": [
            {"case_id": c, "task": {"case_id": c, "domain": "historical", "question": "原始任务"}}
            for c in ["FD001", "FD002", "LA001"]
        ],
        "gold": [],
        "dimensions": [{"field": "accuracy_score", "name": "历史准确性", "full_mark": 17}],
    }
    r.runtime_tables["live_evaluation_runs"][0]["evaluation_context_json"] = json.dumps(context)
    filtered = filter_report(r, report_tasks(r, []), case_id="FD002")
    assert filtered.evidence_by_model["m1"][0].case_id == "FD002"
    assert filtered.evidence_by_model["m1"][0].task["question"] == "原始任务"
    assert historical_dimensions(filtered)[0]["full_mark"] == 17


def test_multiple_service_endpoints_are_detected_without_pooling():
    from dataclasses import replace

    from src.ui.workbench import has_multiple_endpoints

    r = replace(report(), comparison={"models": [{"model_id": "m | p | one"}, {"model_id": "m | p | two"}]})
    assert has_multiple_endpoints(r)


def test_unavailable_results_are_unknown_in_overview(monkeypatch):
    from src.ui import workbench

    monkeypatch.setattr(
        workbench, "load_workbench_source", lambda _: workbench.cd.ConclusionSource(False, None, "数据库不可用")
    )
    at = AppTest.from_string("""
from types import SimpleNamespace
import pandas as pd
from src.ui.case_study import render_case_study_page
render_case_study_page({'base':SimpleNamespace(tasks=pd.DataFrame([{'case_id':'x','domain':'finance'}]))})
""").run()
    assert not at.exception
    assert "已评测模型</dt><dd>—" in " ".join(m.value for m in at.markdown)
    assert not any("尚无正式实测结果" in i.value for i in at.info)


def test_page_route_survives_refresh_and_invalid_route_falls_back(isolated_app_database):
    at = AppTest.from_file("app.py")
    at.query_params["page"] = "samples"
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["current_page"] == "samples"
    at = AppTest.from_file("app.py")
    at.query_params["page"] = "invalid"
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["current_page"] == "case_study"


def test_legacy_dimension_scores_do_not_invent_full_marks():
    at = AppTest.from_string("""
from src.ui.trust_details import render_score_detail
render_score_detail(task={}, answer='历史回答', score={'accuracy_score': 17, 'total_score': 60}, dimensions=[], key='legacy')
""").run()
    assert not at.exception
    assert at.dataframe[0].value.iloc[0].tolist() == ["accuracy_score", 17, "未记录"]
    assert any("满分未知" in c.value for c in at.caption)


def test_report_filter_rerun_preserves_selection_without_default_warning():
    at = AppTest.from_string("""
from types import SimpleNamespace
import pandas as pd
from tests.test_workbench_ui import report
from src.ui.workbench import render_report_filters
render_report_filters(report(), SimpleNamespace(tasks=pd.DataFrame()))
""").run()
    assert not at.exception
    at.multiselect[0].set_value(["m2"]).run()
    assert not at.exception
    assert at.multiselect[0].value == ["m2"]
    assert not at.warning
