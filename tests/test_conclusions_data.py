"""评测结论页缓存层与失效点接线守护。"""

from pathlib import Path


def test_conclusions_data_module_exposes_cached_loaders():
    from src.ui import conclusions_data as cd

    assert callable(cd.load_current_cohort_scores)
    assert callable(cd.load_live_responses)
    assert callable(cd.clear_conclusions_caches)
    assert hasattr(cd.load_current_cohort_scores, "clear")
    assert hasattr(cd.load_live_responses, "clear")


def test_conclusions_page_uses_cached_loaders():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")

    assert "cd.load_current_cohort_scores()" in source
    assert "cd.load_live_responses()" in source
    assert source.count("cd.clear_conclusions_caches()") >= 2


def test_run_finalize_paths_invalidate_conclusions_caches():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

    assert "from src.ui import conclusions_data as cd" in source
    assert source.count("cd.clear_conclusions_caches()") >= 2
