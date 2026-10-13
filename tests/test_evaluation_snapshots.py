import copy
import json

import pytest

from app.services import snapshot as sp


def records():
    return {
        "live_evaluation_runs": [
            dict(
                run_id="r",
                provider="vendor",
                dataset_version="v",
                dataset_hash="d" * 64,
                prompt_hash="p" * 64,
                generation_parameters_json="{}",
                judge_parameters_json="{}",
                status="completed",
                created_at="2026-10-13T10:00:00",
                model_ids_json='["m"]',
            )
        ],
        "live_run_queue": [dict(run_id="r", case_id="c", model_id="m", status="success")],
        "live_run_responses": [
            dict(
                run_id="r",
                case_id="c",
                model_name="m",
                provider="vendor",
                run_mode="live",
                run_status="success",
                answer_text="收入风险较高。",
            )
        ],
        "live_run_scores": [
            dict(
                score_run_id="s",
                run_id="r",
                case_id="c",
                eval_model="m",
                judge_status="success",
                judge_provider="vendor",
                judge_model="judge",
                judge_mode="live",
                total_score=80,
                accuracy_score=25,
                reasoning_score=15,
                coverage_score=15,
                evidence_score=12,
                expression_score=13,
            )
        ],
        "live_score_queue": [],
        "request_attempts": [],
    }


class ReadOnlyStore:
    def list_rows(self, table, **filters):
        return records()[table]


def test_complete_snapshot_replays_without_provider_or_database_writes():
    payload = sp.export_snapshot(ReadOnlyStore())
    restored = sp.load_snapshot(json.dumps(payload, ensure_ascii=False).encode())
    assert restored["tables"]["live_run_responses"][0]["answer_text"] == "收入风险较高。"
    assert restored["tables"]["live_run_queue"]
    assert restored["tables"]["live_evaluation_runs"][0]["created_at"]
    assert restored["provenance"]["source"] == "runtime_database_export"


def test_orphan_score_and_fake_records_are_rejected():
    payload = sp.export_snapshot(ReadOnlyStore())
    for mutate in ["orphan", "mock", "score_range", "total"]:
        changed = copy.deepcopy(payload)
        if mutate == "orphan":
            changed["tables"]["live_run_responses"] = []
        elif mutate == "mock":
            changed["tables"]["live_run_scores"][0]["judge_mode"] = "mock"
        elif mutate == "score_range":
            changed["tables"]["live_run_scores"][0]["accuracy_score"] = 40
        else:
            changed["tables"]["live_run_scores"][0]["total_score"] = 99
        with pytest.raises(ValueError):
            sp.load_snapshot(json.dumps(changed).encode())


def test_unknown_fields_cannot_smuggle_secrets_and_export_redacts_text():
    raw = records()
    raw["live_run_responses"][0]["api_key"] = "SECRET"
    raw["live_run_responses"][0]["answer_text"] += " /Users/private/file sk-abcdefghijklmnopqrstuvwx"

    class Store:
        def list_rows(self, table, **filters):
            return raw[table]

    payload = sp.export_snapshot(Store())
    text = json.dumps(payload)
    assert "SECRET" not in text and "/Users/private" not in text and "sk-abcdefghijkl" not in text
    assert payload["provenance"]["redacted"] is True
    payload["tables"]["live_run_responses"][0]["api_key"] = "secret"
    with pytest.raises(ValueError):
        sp.load_snapshot(json.dumps(payload).encode())


def test_judge_selftest_export_is_not_a_formal_snapshot():
    with pytest.raises(ValueError):
        sp.load_snapshot(b'{"export_type":"judge_selftest","schema_version":1,"tables":{}}')


def test_missing_time_and_duplicate_records_are_rejected():
    payload = sp.export_snapshot(ReadOnlyStore())
    payload["tables"]["live_evaluation_runs"][0].pop("created_at")
    with pytest.raises(ValueError):
        sp.load_snapshot(json.dumps(payload).encode())
    payload = sp.export_snapshot(ReadOnlyStore())
    payload["tables"]["live_run_scores"] *= 2
    with pytest.raises(ValueError):
        sp.load_snapshot(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_ids_json", "123"),
        ("generation_parameters_json", "[]"),
        ("judge_parameters_json", "not json"),
        ("evaluation_context_json", '{"samples":42}'),
    ],
)
def test_bad_nested_metadata_is_rejected_before_ui_render(field, value):
    payload = sp.export_snapshot(ReadOnlyStore())
    payload["tables"]["live_evaluation_runs"][0][field] = value
    with pytest.raises(ValueError):
        sp.load_snapshot(json.dumps(payload).encode())


def test_declared_verified_quotes_require_complete_reason_and_score_fields():
    payload = sp.export_snapshot(ReadOnlyStore())
    row = payload["tables"]["live_run_scores"][0]
    row["evidence_status"] = "verified_quotes"
    with pytest.raises(ValueError):
        sp.load_snapshot(json.dumps(payload).encode())


def test_export_excludes_mock_judges_and_their_dependents_but_preserves_live_failures():
    raw = records()
    raw['live_run_scores'].append(dict(raw['live_run_scores'][0], score_run_id='mock-score', judge_mode='mock', judge_provider='mock'))
    raw['live_run_scores'].append(dict(raw['live_run_scores'][0], score_run_id='failed-score', judge_status='error', error_code='timeout'))
    raw['live_score_queue'] = [
        dict(run_id='r',score_run_id='mock-score',case_id='c',eval_model='m',judge_provider='vendor',status='success'),
        dict(run_id='r',score_run_id='failed-score',case_id='c',eval_model='m',judge_provider='vendor',status='error'),
    ]
    raw['request_attempts'] = [
        dict(attempt_id='mock-a',run_id='r',score_run_id='mock-score',case_id='c',eval_model='m',provider='vendor',phase='judge'),
        dict(attempt_id='failed-a',run_id='r',score_run_id='failed-score',case_id='c',eval_model='m',provider='vendor',phase='judge'),
    ]
    before=copy.deepcopy(raw)

    class Store:
        def list_rows(self,table):return raw[table]

    exported=sp.export_snapshot(Store())
    assert {r['score_run_id'] for r in exported['tables']['live_run_scores']} == {'s','failed-score'}
    assert [r['score_run_id'] for r in exported['tables']['live_score_queue']] == ['failed-score']
    assert [r['attempt_id'] for r in exported['tables']['request_attempts']] == ['failed-a']
    assert raw == before
    restored=sp.load_snapshot(json.dumps(exported,ensure_ascii=False))
    assert restored['tables']['live_run_scores'][-1]['error_code'] == 'timeout'


@pytest.mark.parametrize('mode',['MOCK','selftest','synthetic','synthetic_judge_selftest','demo'])
def test_snapshot_export_and_loader_share_non_formal_record_policy(mode):
    raw=records()
    raw['live_run_scores'][0]['judge_mode']=mode

    class Store:
        def list_rows(self,table):return raw[table]

    exported=sp.export_snapshot(Store())
    assert not exported['tables']['live_run_scores']
    sp.load_snapshot(json.dumps(exported))
    exported['tables']['live_run_scores']=raw['live_run_scores']
    with pytest.raises(ValueError,match='模拟或裁判自测'):
        sp.load_snapshot(json.dumps(exported))
