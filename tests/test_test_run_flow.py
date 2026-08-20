"""Pure contracts for the single-entry evaluation configuration flow."""

from pathlib import Path

from app.models.base import ModelInfo
from app.services import dataset_service as ds
from src.ui import evaluation_config as ec
from src.ui import test_run as tr


def test_configuration_view_owns_form_state_filters_and_dialogs():
    test_run_source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    config_source = Path("src/ui/evaluation_config.py").read_text(encoding="utf-8")

    moved_functions = [
        "resolve_eval_max_tokens",
        "resolve_eval_temperature",
        "filter_sample_selection_options",
        "build_sample_selection_rows",
        "sample_checkbox_key",
        "merge_sample_checkbox_selection",
        "build_model_selection_options",
        "prompt_preview_task_for_case",
        "render_evaluation_scope",
        "render_pending_dialogs",
        "_render_prompt_preview_dialog",
        "_render_sample_selection_dialog",
        "_render_model_selection_dialog",
    ]
    for name in moved_functions:
        assert f"def {name}(" not in test_run_source
        assert f"def {name}(" in config_source

    assert "@st.dialog" not in test_run_source
    assert "EvaluationWorkflow(" not in config_source
    assert "SiliconFlowProvider(" not in config_source


def _dimension():
    return {
        "field": "accuracy_score",
        "name": "准确性",
        "full_mark": 30,
        "full_mark_standard": "回答完整准确覆盖标准。",
        "deduction_rules": "缺少关键判断或依据时扣分。",
    }


def _task(case_id="C1", *, status=ds.ACTIVE_STATUS):
    return {
        "case_id": case_id,
        "status": status,
        "question": f"Q-{case_id}",
        "context": "背景",
        "scenario": "财务尽调——收入真实性",
        "task_type": "analysis",
        "difficulty": "Medium",
    }


def _gold():
    return {
        "core_conclusion": "结论",
        "must_have_points": ["覆盖点"],
        "unacceptable_errors": ["错误"],
    }


def test_split_configuration_helpers_remain_compatible_imports():
    assert tr.build_sample_options is ec.build_sample_options
    assert tr.build_run_plan_summary is ec.build_run_plan_summary
    assert tr.build_run_queue_items is ec.build_run_queue_items
    assert tr.build_evaluation_config_from_checkpoint is ec.build_evaluation_config_from_checkpoint


def test_hidden_generation_parameters_are_bounded():
    assert tr.resolve_eval_max_tokens("") == 4096
    assert tr.resolve_eval_max_tokens("6000") == 6000
    assert tr.resolve_eval_max_tokens("999999") == 8192
    assert tr.resolve_eval_max_tokens("bad") == 4096
    assert tr.resolve_eval_temperature("") == 0.1
    assert tr.resolve_eval_temperature("0") == 0.0
    assert tr.resolve_eval_temperature("1") == 1.0
    assert tr.resolve_eval_temperature("1.1") == 0.1


def test_only_ready_active_samples_enter_configuration():
    tasks = [_task("C1"), _task("C2", status=ds.DRAFT_STATUS)]
    options = tr.build_sample_options(
        tasks,
        {"C1": _gold(), "C2": _gold()},
        [_dimension()],
        title_map={"C1": "收入真实性核验"},
    )

    assert [item["case_id"] for item in options] == ["C1"]
    assert options[0]["title"] == "收入真实性核验"
    assert options[0]["task"] is tasks[0]


def test_filter_rows_and_checkbox_merge_share_one_selection_state():
    options = [
        {"case_id": "C1", "title": "收入", "scenario": "财务尽调", "difficulty": "中等", "task": {}},
        {"case_id": "C2", "title": "合同", "scenario": "法律尽调", "difficulty": "复杂", "task": {}},
    ]

    filtered = tr.filter_sample_selection_options(options, keyword="合同", scenario="法律尽调", difficulty="复杂")
    rows = tr.build_sample_selection_rows(filtered, ["C1", "C2"])
    merged = tr.merge_sample_checkbox_selection(
        ["C1", "C2"],
        filtered,
        {"C2": False},
        {"C1", "C2"},
    )

    assert [item["case_id"] for item in filtered] == ["C2"]
    assert rows[0]["选择"] is True
    assert merged == ["C1"]
    assert tr.sample_checkbox_key("C2") == "test_run_case_checkbox_C2"


def test_run_plan_and_queue_are_deduplicated_and_deterministic():
    selected = [{"case_id": "C1", "task": _task("C1")}, {"case_id": "C2", "task": _task("C2")}]
    models = ["vendor/m1", "vendor/m1", "vendor/m2"]

    plan = tr.build_run_plan_summary(models, selected)
    queue = tr.build_run_queue_items(models, selected)

    assert plan == {"sample_count": 2, "model_count": 2, "planned_responses": 4, "can_run": True}
    assert [(row["case_id"], row["model_id"]) for row in queue] == [
        ("C1", "vendor/m1"),
        ("C1", "vendor/m2"),
        ("C2", "vendor/m1"),
        ("C2", "vendor/m2"),
    ]


def test_sample_selection_starts_empty_and_preserves_only_explicit_valid_choices(monkeypatch):
    session_state: dict[str, object] = {}
    monkeypatch.setattr(ec.st, "session_state", session_state)
    options = [{"case_id": "C1"}, {"case_id": "C2"}]

    ec.normalize_selected_cases(options)
    assert session_state["test_run_selected_cases"] == []

    session_state["test_run_selected_cases"] = ["C2", "missing"]
    ec.normalize_selected_cases(options)
    assert session_state["test_run_selected_cases"] == ["C2"]


def test_disabled_evaluation_action_explains_the_first_missing_requirement():
    assert tr._evaluation_action_disabled_message(
        {"sample_count": 0, "model_count": 0, "planned_responses": 0, "can_run": False},
        store_available=True,
        service_configured=True,
    ) == "请先选择至少一个样本。"
    assert tr._evaluation_action_disabled_message(
        {"sample_count": 1, "model_count": 0, "planned_responses": 0, "can_run": False},
        store_available=True,
        service_configured=True,
    ) == "请先选择至少一个模型。"
    assert tr._evaluation_action_disabled_message(
        {"sample_count": 1, "model_count": 1, "planned_responses": 1, "can_run": True},
        store_available=False,
        service_configured=True,
    ) == "评测结果数据库恢复后才能开始评测。"
    assert tr._evaluation_action_disabled_message(
        {"sample_count": 1, "model_count": 1, "planned_responses": 1, "can_run": True},
        store_available=True,
        service_configured=False,
    ) == "当前未配置模型服务密钥，暂不能发起真实调用。"


def test_model_search_uses_id_owner_and_metadata_without_duplicates():
    models = [
        ModelInfo("vendor/model-a", "vendor", "model", "vendor", raw={"display_name": "Alpha"}),
        ModelInfo("vendor/model-a", "vendor", "model", "vendor"),
        ModelInfo("other/model-b", "other", "model", "other", metadata={"name": "Beta"}),
    ]

    assert tr.build_model_selection_options(models, "alpha") == (["vendor/model-a"], 1)
    assert tr.build_model_selection_options(models, "beta") == (["other/model-b"], 1)


def test_prompt_preview_returns_the_exact_selected_task_without_gold():
    task = _task("C1")
    options = [{"case_id": "C1", "task": task}, {"case_id": "C2", "task": _task("C2")}]

    selected = tr.prompt_preview_task_for_case(options, ["C1"], "C1")

    assert selected is task
    assert "gold" not in selected
