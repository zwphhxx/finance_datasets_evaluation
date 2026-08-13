"""评测结论页缓存层与失效点接线守护。"""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.persistence.result_store import ResultStoreError


def test_conclusions_data_module_exposes_cached_loaders():
    from src.ui import conclusions_data as cd

    assert callable(cd.load_current_cohort_scores)
    assert callable(cd.load_live_responses)
    assert callable(cd.load_conclusion_source)
    assert callable(cd.clear_conclusions_caches)
    assert hasattr(cd.load_current_cohort_scores, "clear")
    assert hasattr(cd.load_live_responses, "clear")
    assert hasattr(cd.load_conclusion_source, "clear")


def test_conclusions_page_uses_cached_loaders():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")

    assert "cd.load_current_cohort_scores(allowed_case_ids)" in source
    assert "cd.load_live_responses(allowed_case_ids)" in source
    assert source.count("cd.clear_conclusions_caches()") >= 1


def test_run_finalize_paths_invalidate_conclusions_caches():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

    assert "from src.ui import conclusions_data as cd" in source
    assert source.count("cd.clear_conclusions_caches()") >= 2


def test_conclusion_source_reports_empty_database_as_available_and_passes_strict_loader_flags(monkeypatch):
    from src.ui import conclusions_data as cd

    calls = []
    monkeypatch.setattr(cd.cc, "load_evaluation_runs", lambda *, suppress_errors=True: calls.append(("runs", suppress_errors)) or pd.DataFrame())
    monkeypatch.setattr(cd.cc, "load_live_scores", lambda *, suppress_errors=True: calls.append(("scores", suppress_errors)) or pd.DataFrame())
    monkeypatch.setattr(cd.cc, "load_live_responses", lambda *, allowed_case_ids=None, suppress_errors=True: calls.append(("responses", suppress_errors, allowed_case_ids)) or pd.DataFrame())
    monkeypatch.setattr(cd.cc, "select_current_cohort_scores", lambda runs, scores, *, allowed_case_ids=None: scores)
    cd.load_conclusion_source.clear()

    source = cd.load_conclusion_source(("C1",), [{"case_id": "C1"}], {"C1": {}}, ({"field": "accuracy_score", "full_mark": 25},))

    assert source.available is True
    assert source.report is not None
    assert source.report.scope.formal_score_count == 0
    assert calls == [("runs", False), ("scores", False), ("responses", False, ("C1",))]
    cd.load_conclusion_source.clear()


def test_conclusion_source_only_catches_expected_database_failures(monkeypatch):
    from src.ui import conclusions_data as cd

    cd.load_conclusion_source.clear()
    monkeypatch.setattr(cd.cc, "load_evaluation_runs", lambda *, suppress_errors=True: (_ for _ in ()).throw(ResultStoreError("offline")))
    unavailable = cd.load_conclusion_source((), [], {}, ())
    assert unavailable.available is False
    assert unavailable.report is None
    assert "数据库暂不可用" in unavailable.message

    cd.load_conclusion_source.clear()
    monkeypatch.setattr(cd.cc, "load_evaluation_runs", lambda *, suppress_errors=True: pd.DataFrame())
    monkeypatch.setattr(cd.cc, "load_live_scores", lambda *, suppress_errors=True: pd.DataFrame())
    monkeypatch.setattr(cd.cc, "load_live_responses", lambda *, allowed_case_ids=None, suppress_errors=True: pd.DataFrame())
    monkeypatch.setattr(cd.cc, "select_current_cohort_scores", lambda runs, scores, *, allowed_case_ids=None: scores)
    monkeypatch.setattr(cd, "build_conclusion_report", lambda **kwargs: (_ for _ in ()).throw(ValueError("programming error")))
    with pytest.raises(ValueError, match="programming error"):
        cd.load_conclusion_source((), [], {}, ())
    cd.load_conclusion_source.clear()


def test_clear_conclusions_caches_clears_report_source_cache():
    from src.ui import conclusions_data as cd

    with patch.object(cd.load_current_cohort_scores, "clear") as clear_scores, patch.object(
        cd.load_live_responses, "clear"
    ) as clear_responses, patch.object(cd.load_conclusion_source, "clear") as clear_source:
        cd.clear_conclusions_caches()

    clear_scores.assert_called_once_with()
    clear_responses.assert_called_once_with()
    clear_source.assert_called_once_with()
