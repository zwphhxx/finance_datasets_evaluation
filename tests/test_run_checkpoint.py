from app.services.run_checkpoint import build_run_metadata, canonical_hash


def test_canonical_hash_ignores_mapping_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_sample_change_changes_dataset_hash():
    first = build_run_metadata(
        run_id="RUN-1",
        provider="mock",
        model_ids=["m1"],
        queue_items=[
            {"case_id": "FD-001", "task": {"question": "A", "context": "B"}}
        ],
        generation_parameters={"temperature": 0.1, "max_tokens": 4096},
        judge_parameters={"temperature": 0.0, "max_tokens": 2048},
        dataset_version="1.0.0",
        prompt_payload={"system": "prompt-v1"},
    )
    second = build_run_metadata(
        run_id="RUN-1",
        provider="mock",
        model_ids=["m1"],
        queue_items=[
            {
                "case_id": "FD-001",
                "task": {"question": "changed", "context": "B"},
            }
        ],
        generation_parameters={"temperature": 0.1, "max_tokens": 4096},
        judge_parameters={"temperature": 0.0, "max_tokens": 2048},
        dataset_version="1.0.0",
        prompt_payload={"system": "prompt-v1"},
    )

    assert first["dataset_hash"] != second["dataset_hash"]
    assert first["prompt_hash"] == second["prompt_hash"]


def test_metadata_records_reproducible_parameters():
    metadata = build_run_metadata(
        run_id="RUN-1",
        provider="mock",
        model_ids=["m2", "m1"],
        queue_items=[{"case_id": "FD-001", "task": {"question": "A"}}],
        generation_parameters={"temperature": 0.1},
        judge_parameters={"temperature": 0.0},
        dataset_version="1.0.0",
        prompt_payload={"system": "prompt-v1"},
    )

    assert metadata["run_id"] == "RUN-1"
    assert metadata["model_ids_json"] == '["m2", "m1"]'
    assert metadata["pending_count"] == 1
    assert len(metadata["dataset_hash"]) == 64
    assert len(metadata["prompt_hash"]) == 64


def _metadata_with_scoring_evidence(gold_map, dimensions):
    return build_run_metadata(
        run_id="RUN-1",
        provider="test-live",
        model_ids=["m1"],
        queue_items=[
            {"case_id": "FD-001", "model_id": "m1", "task": {"question": "A"}}
        ],
        generation_parameters={"temperature": 0.1},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0},
        dataset_version="1.0.0",
        prompt_payload={"system": "prompt-v1"},
        gold_map=gold_map,
        dimensions=dimensions,
    )


def test_gold_or_scoring_dimension_change_changes_dataset_hash():
    baseline = _metadata_with_scoring_evidence(
        {"FD-001": {"core_conclusion": "gold", "must_have_points": ["A"]}},
        [{"field": "accuracy_score", "max_score": 5}],
    )
    changed_gold = _metadata_with_scoring_evidence(
        {"FD-001": {"core_conclusion": "changed", "must_have_points": ["A"]}},
        [{"field": "accuracy_score", "max_score": 5}],
    )
    changed_dimensions = _metadata_with_scoring_evidence(
        {"FD-001": {"core_conclusion": "gold", "must_have_points": ["A"]}},
        [{"field": "accuracy_score", "max_score": 10}],
    )

    assert baseline["dataset_hash"] != changed_gold["dataset_hash"]
    assert baseline["dataset_hash"] != changed_dimensions["dataset_hash"]


def test_scoring_evidence_hash_is_stable_for_mapping_key_order():
    first = _metadata_with_scoring_evidence(
        {"FD-001": {"core_conclusion": "gold", "must_have_points": ["A"]}},
        [{"field": "accuracy_score", "max_score": 5}],
    )
    second = _metadata_with_scoring_evidence(
        {"FD-001": {"must_have_points": ["A"], "core_conclusion": "gold"}},
        [{"max_score": 5, "field": "accuracy_score"}],
    )

    assert first["dataset_hash"] == second["dataset_hash"]


def test_legacy_metadata_without_scoring_evidence_keeps_original_hash_contract():
    metadata = build_run_metadata(
        run_id="RUN-1",
        provider="test-live",
        model_ids=["m1"],
        queue_items=[{"case_id": "FD-001", "task": {"question": "A"}}],
        generation_parameters={},
        judge_parameters={},
        dataset_version="1.0.0",
        prompt_payload=[],
    )

    assert metadata["dataset_hash"] == canonical_hash(
        [{"case_id": "FD-001", "task": {"question": "A"}}]
    )
