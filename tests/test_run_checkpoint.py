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
