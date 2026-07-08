"""Repository readiness guardrails for project submission."""

from __future__ import annotations

import csv
import json
import re
import subprocess
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
RESULT_SEED_FILES = [
    "model_outputs.csv",
    "scores.csv",
    "error_labels.csv",
    "optimization_plan.csv",
]


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
        if path.name == "test_repository_readiness.py":
            continue
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


def test_readme_uses_concise_project_submission_structure() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_screen = "\n".join(readme.splitlines()[:40])

    assert "# 财务/法律/投行场景大模型对比评测" in first_screen
    assert "## " + "面" + "试官快速阅读" not in readme
    assert "docs/demo_script.md" in readme
    assert "docs/" + "inter" + "view_script.md" not in readme
    assert "## 数据对象与数据流" not in readme
    assert len(readme.splitlines()) < 120
    for heading in [
        "## 项目定位",
        "## 核心能力",
        "## 主流程",
        "## 当前样本集",
        "## 评测边界",
        "## 本地运行",
        "## 模型服务配置",
        "## 演示与恢复",
        "## 文档索引",
    ]:
        assert heading in readme
    for phrase in [
        "不是通用 Chatbot",
        "不做脱离样本范围的泛化模型排名",
        "专业样本",
        "专业标准答案",
        "评分标准",
        "裁判评分",
        "AI 评分",
        "使用边界",
        "详细字段、数据结构和 SQLite / 文件映射见 `docs/dataset_schema.md`",
    ]:
        assert phrase in readme


def test_env_example_uses_project_runtime_defaults() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "SILICONFLOW_API_KEY=" in text
    assert "sk-" not in text
    assert "SILICONFLOW_TIMEOUT_SECONDS=180" in text
    assert "FINDUEVAL_EVAL_MAX_TOKENS=4096" in text
    assert "FINDUEVAL_EVAL_TEMPERATURE=0.1" in text


def test_docs_match_current_project_demo_path() -> None:
    project_note = (ROOT / "docs" / "project_note.md").read_text(encoding="utf-8")
    demo_script = (ROOT / "docs" / "demo_script.md").read_text(encoding="utf-8")
    combined = project_note + "\n" + demo_script

    assert "评分矩阵" not in combined
    assert "旧页面" not in combined
    assert "MED" + "-001" not in combined
    assert "MA" + "-001" not in combined
    assert "面" + "试" not in combined
    assert "面" + "试" + "官" not in combined
    assert "inter" + "view" + " demo" not in combined.lower()
    for phrase in ["项目说明", "样本库", "发起评测", "评测结论"]:
        assert phrase in combined
    assert "评分" + "确认" not in project_note
    assert "人工" + "确认" not in project_note
    assert "不是通用 Chatbot" in demo_script
    assert "不是模型排名页" in demo_script
    assert "实时模型调用不能保证 100% 成功" in demo_script


def test_repository_sources_do_not_contain_packaging_or_process_markers() -> None:
    paths = [
        *sorted((ROOT / "app").rglob("*.py")),
        *sorted((ROOT / "src").rglob("*.py")),
        *sorted((ROOT / "docs").glob("*.md")),
        ROOT / "README.md",
    ]
    banned = [
        "面" + "试",
        "面" + "试" + "官",
        "inter" + "view" + " demo",
        "P" + "R-33",
        "P" + "R-34",
        "P" + "R-35",
        "P" + "R-LOGIC1",
    ]
    offenders: dict[str, list[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        hits = [term for term in banned if term in text]
        if hits:
            offenders[path.relative_to(ROOT).as_posix()] = hits
    assert offenders == {}


def test_legacy_review_apis_are_removed_from_scorer() -> None:
    from app.services import scorer as sc

    assert not hasattr(sc, "confirm_score" + "_review")
    assert not hasattr(sc, "confirm_score" + "_reviews_bulk")
    assert not hasattr(sc, "skip_score" + "_review")


def test_demo_ai_score_export_contains_usable_demo_records() -> None:
    payload = json.loads((ROOT / "data" / "demo_exports" / "demo_ai_scores.json").read_text(encoding="utf-8"))
    records = payload.get("records") or []

    assert payload["export_type"] == "ai_score_export"
    assert payload["scope"] == "ai_scores"
    assert payload["row_count"] == len(records)
    assert len(records) >= 6
    assert len({row["case_id"] for row in records}) >= 3
    assert len({row["eval_model"] for row in records}) >= 2
    assert all(row["judge_status"] == "success" for row in records)
    assert all(row["review_status"] == "ai_final" for row in records)


def test_committed_runtime_result_seed_files_are_header_only() -> None:
    for name in RESULT_SEED_FILES:
        rows = (ROOT / "data" / name).read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1, name


def test_git_tracked_files_exclude_local_runtime_artifacts() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    tracked = result.stdout.splitlines()
    forbidden_patterns = [
        re.compile(r"(^|/)\.env$"),
        re.compile(r"(^|/)\.streamlit/secrets\.toml$"),
        re.compile(r"(^|/)__pycache__/"),
        re.compile(r"(^|/)\.DS_Store$"),
        re.compile(r"(^|/)\.venv/"),
        re.compile(r"app/db/.*\.db$"),
        re.compile(r".*\.sqlite3$"),
    ]

    offenders = [
        path
        for path in tracked
        if any(pattern.search(path) for pattern in forbidden_patterns)
    ]
    assert offenders == []
