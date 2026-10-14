"""Prompt source boundaries and immutable legacy replay; never call a live provider."""

import hashlib
import json

import pytest

from app.models.base import GenerationResult
from app.services import scorer
from app.services.score_evidence import validate_checks

TASK = {"case_id": "X", "scenario": "场景", "question": "任务", "context": "材料原文", "output_requirement": "三条以内"}
ANSWER = "回答原文"
GOLD = {"core_conclusion": "参考结论", "must_have_points": ["覆盖回款"], "unacceptable_errors": ["捏造回款"]}
DIMS = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]


def test_legacy_prompt_remains_byte_identical():
    messages = scorer.build_judge_messages(TASK, ANSWER, GOLD, DIMS)
    assert hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest() == (
        "bec0f079f00fbf84fa22de0a1c83dfa396e461ab96c54d284be9dd0180ef86cc"
    )


def test_new_prompt_separates_data_and_names_the_only_quote_source():
    messages = scorer.build_judge_messages(TASK, ANSWER, GOLD, DIMS, judge_prompt_version="answer-quotes-v2")
    payload = json.loads(messages[1]["content"])
    assert payload["evaluated_answer"]["answer_text"] == ANSWER
    assert payload["task_material"]["context"] == TASK["context"]
    assert payload["reference_standard"] == GOLD
    assert payload["rubric"] == DIMS
    assert len(payload["checkpoints"]) == 2
    rules = messages[0]["content"]
    for instruction in ("evaluated_answer.answer_text", "任务材料", "拼接", "改写", "省略号"):
        assert instruction in rules


@pytest.mark.parametrize("quote", ["材料原文", "参考结论", "回答…原文", "原文回答"])
def test_non_answer_quotes_remain_invalid(quote):
    checks = [dict(point_id="must:1", status="met", quote=quote, error_type="none",
                   dimension="accuracy_score", reason="测试")]
    with pytest.raises(ValueError, match="引文不在"):
        validate_checks(checks, {"must_have_points": ["覆盖回款"]}, ANSWER, DIMS)


def test_exact_answer_quote_and_honest_unknown_remain_supported():
    checks = [dict(point_id="must:1", status="met", quote=ANSWER, error_type="none",
                   dimension="accuracy_score", reason="测试"),
              dict(point_id="forbidden:1", status="unknown", quote="", error_type="uncertain",
                   dimension="accuracy_score", reason="未找到可判断引文")]
    result = validate_checks(checks, GOLD, ANSWER, DIMS)
    assert result[0]["quote_verified"]
    assert not result[1]["quote_verified"]


def test_v2_retry_identifies_evidence_source_without_repairing_quote():
    class Provider:
        name = "fixture"

        def __init__(self):
            self.calls = []

        def generate_response(self, model, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return GenerationResult(self.name, model, "success", json.dumps({
                "scores": {"accuracy_score": 20}, "rationale": {"accuracy_score": "测试"}, "review_note": "测试",
                "checks": [dict(point_id="must:1", status="met", quote="材料原文", error_type="none",
                                dimension="accuracy_score", reason="测试")],
            }, ensure_ascii=False))

    provider = Provider()
    result = scorer.score_single(provider, "judge", TASK, ANSWER, {"must_have_points": ["覆盖回款"]}, DIMS,
                                 judge_prompt_version="answer-quotes-v2", retry_delays=[0], sleep_fn=lambda _: None,
                                 enable_thinking=False, max_tokens=3072)
    assert result.total_score is None and result.judge_status == "failed"
    assert len(provider.calls) == 2
    corrective = provider.calls[1][0][-1]["content"]
    assert "must:1" in corrective and "evaluated_answer.answer_text" in corrective
    assert provider.calls[0][1]["enable_thinking"] is False
    assert "judge_prompt_version" not in provider.calls[0][1]


def test_new_evaluation_config_explicitly_records_mode_and_prompt(monkeypatch):
    from app.services import dataset_service as ds
    from src.ui.test_run import build_evaluation_config

    base = ds.load_evaluation_data()
    config = build_evaluation_config(base, [base.tasks.iloc[0].to_dict()], ["isolated-model"])
    assert config.judge_parameters["enable_thinking"] is False
    assert config.judge_parameters["judge_prompt_version"] == "answer-quotes-v2"
    assert config.judge_parameters["max_tokens"] == 3072


def test_new_judge_configuration_is_a_separate_comparison_cohort():
    import pandas as pd

    from app.services.conclusions import _cohort_signature

    baseline = dict(dataset_version="v", dataset_hash="d", prompt_hash="p", generation_parameters_json="{}",
                    judge_parameters_json=json.dumps({"judge_model": scorer.DEFAULT_JUDGE_MODEL, "max_tokens": 3072}))
    changed = dict(baseline, judge_parameters_json=json.dumps({"judge_model": scorer.DEFAULT_JUDGE_MODEL,
                   "max_tokens": 3072, "enable_thinking": False, "judge_prompt_version": "answer-quotes-v2"}))
    assert _cohort_signature(pd.Series(baseline)) != _cohort_signature(pd.Series(changed))


def test_unknown_prompt_version_never_calls_provider():
    class Provider:
        name = "fixture"

        def generate_response(self, *_args, **_kwargs):
            raise AssertionError("unsupported prompt version attempted a request")

    with pytest.raises(ValueError, match="提示词版本"):
        scorer.score_single(Provider(), "judge", TASK, ANSWER, GOLD, DIMS, judge_prompt_version="unknown")


def test_legacy_resume_reuses_saved_answer_and_preserves_judge_configuration(tmp_path):
    from dataclasses import replace

    from test_evaluation_workflow import RecordingProvider, config, item, sqlite_store, workflow

    from app.services.evaluation_workflow import EvaluationRunRef, answer_queue_row, score_queue_row
    from app.services.run_checkpoint import build_run_metadata

    saved_config = replace(config(item("X", "m1")), dimensions=tuple(DIMS))
    store = sqlite_store(tmp_path)
    sent = []

    class Judge(RecordingProvider):
        def generate_response(self, model, messages, **kwargs):
            sent.append((messages, kwargs))
            return GenerationResult(self.name, model, "success", json.dumps({
                "scores": {"accuracy_score": 0}, "rationale": {"accuracy_score": "隔离测试"}, "review_note": "测试",
            }))

    answer_provider = RecordingProvider()  # No generation responses; a call would fail.
    runner = workflow(store, answer_provider, Judge())
    ref = EvaluationRunRef("legacy-run", "legacy-score")
    store.initialize_evaluation(
        build_run_metadata(run_id=ref.run_id, provider=saved_config.provider_name,
                           model_ids=saved_config.model_ids, queue_items=saved_config.queue_items,
                           generation_parameters=saved_config.generation_parameters,
                           judge_parameters=saved_config.judge_parameters, dataset_version=saved_config.dataset_version,
                           prompt_payload=saved_config.prompt_payload, gold_map=saved_config.gold_map,
                           dimensions=saved_config.dimensions),
        [answer_queue_row(ref.run_id, saved_config.queue_items[0], "test-live")],
        [score_queue_row(ref.run_id, ref.score_run_id, saved_config.queue_items[0], "test-live", "judge-1")],
    )
    store.save_run_outcome(dict(run_id=ref.run_id, case_id="X", model_name="m1", provider="test-live",
                                run_status="success", answer_text=ANSWER), queue_status="success", combined=True)
    store.mark_run_stopped(ref.run_id, "isolated interruption")
    before = store.list_rows("live_run_responses", run_id=ref.run_id)
    original_parameters = store.list_rows("live_evaluation_runs", run_id=ref.run_id)[0]["judge_parameters_json"]
    status = runner.continue_evaluation(ref.run_id, saved_config)
    assert status.succeeded == 1 and len(sent) == 1
    assert sent[0][0] == scorer.build_judge_messages(saved_config.queue_items[0]["task"], ANSWER,
                                                   saved_config.gold_map["X"], DIMS)
    assert "enable_thinking" not in sent[0][1]
    assert store.list_rows("live_run_responses", run_id=ref.run_id) == before
    assert store.list_rows("live_evaluation_runs", run_id=ref.run_id)[0]["judge_parameters_json"] == original_parameters


def test_app_uses_local_png_favicon():
    import ast
    from pathlib import Path

    from PIL import Image

    icon = Path("assets/favicon.png")
    assert icon.exists()
    with Image.open(icon) as image:
        assert image.format == "PNG" and image.size == (128, 128)
        assert image.getpixel((64, 64))[:3] in ((37, 99, 235), (255, 255, 255))
    tree = ast.parse(Path("app.py").read_text())
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "set_page_config")
    assert any(k.arg == "page_icon" for k in call.keywords)
