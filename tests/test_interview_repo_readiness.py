"""Repository readiness guardrails for the interview demo."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CASE_IDS = {
    "FD-001",
    "FD-002",
    "FD-003",
    "FD-004",
    "FD-005",
    "LD-001",
    "LD-002",
    "LD-003",
    "LD-004",
    "CM-001",
    "CM-002",
    "CM-003",
    "CM-004",
}
EXPECTED_DOMAINS = {"Financial", "Legal", "Capital Markets"}


def _csv_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"] for row in csv.DictReader(handle) if row.get("case_id")}


def test_test_files_use_business_names_without_process_markers() -> None:
    legacy_name = re.compile(r"^test_pr(\d|_|[a-z]_).*\.py$")
    process_marker = "P" + "R-"
    test_files = sorted((ROOT / "tests").glob("test_*.py"))

    assert not [path.name for path in test_files if legacy_name.match(path.name)]
    assert not [
        path.relative_to(ROOT).as_posix()
        for path in test_files
        if process_marker in path.read_text(encoding="utf-8")
    ]


def test_tests_do_not_pin_removed_sample_identifiers() -> None:
    removed_ids = {"MED" + "-001", "MA" + "-001", "FD" + "-006"}
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        if any(case_id in source for case_id in removed_ids):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_seed_assets_are_exactly_the_final_sample_set() -> None:
    data_dir = ROOT / "data"
    task_ids = _csv_ids(data_dir / "tasks.csv")
    samples = json.loads((data_dir / "samples.json").read_text(encoding="utf-8"))
    gold_answers = json.loads((data_dir / "gold_answers.json").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((data_dir / "dataset_manifest.yml").read_text(encoding="utf-8"))

    assert task_ids == EXPECTED_CASE_IDS
    assert {sample.get("case_id") or sample["sample_id"] for sample in samples} == EXPECTED_CASE_IDS
    assert {item["case_id"] for item in gold_answers} == EXPECTED_CASE_IDS
    assert manifest["assets"]["tasks"]["file"] == "tasks.csv"
    assert manifest["assets"]["gold_answers"]["file"] == "gold_answers.json"
    assert set(manifest["scope"]["domains"]) == EXPECTED_DOMAINS
    assert {sample["domain"] for sample in samples} <= EXPECTED_DOMAINS
