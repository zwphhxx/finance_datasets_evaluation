"""Offline contracts for the independent production smoke probe."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql://healthcheck:secret@db.example/postgres?sslmode=require"


def test_standalone_probe_exists():
    assert (ROOT / "scripts" / "production_smoke.py").exists(), "standalone production smoke probe is missing"


@pytest.fixture
def smoke():
    path = ROOT / "scripts" / "production_smoke.py"
    if not path.exists():
        pytest.skip("existence contract reports the missing implementation")
    spec = importlib.util.spec_from_file_location("production_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOME = "专业场景大模型评测\n历史回答节选\n专业评价\nAI评分：82.5"
DETAIL = "任务与业务背景\n模型回答\n专业评价"


class FakeLocator:
    def __init__(self, frame, kind, name=""):
        self.frame, self.kind, self.name = frame, kind, name

    @property
    def first(self):
        return self

    def count(self):
        if self.kind == "button":
            return int(self.name in self.frame.state.get("buttons", []))
        if self.kind == "exception":
            return int(self.frame.state.get("exception", False))
        if self.kind == "answer":
            return int(self.frame.state.get("answer") is not None)
        return 1

    def is_visible(self, **kwargs):
        if self.kind == "answer" and self.frame.state.get("answer_hidden", False):
            return False
        return bool(self.count())

    def is_enabled(self, **kwargs):
        return bool(self.count())

    def inner_text(self, **kwargs):
        if self.kind == "answer":
            return self.frame.state.get("answer", "")
        return self.frame.state.get("metric", "") if self.kind == "metric" else self.frame.state.get("text", "")

    def click(self, **kwargs):
        self.frame.page.clicks.append(self.name)
        if self.name.startswith("Yes,"):
            self.frame.page.phase = "home"
        elif self.name == "查看完整案例 →":
            self.frame.page.phase = "detail"


class FakeFrame:
    url = "https://finance-model-eval.streamlit.app/"

    def __init__(self, page, shell=False):
        self.page, self.shell = page, shell

    @property
    def state(self):
        if self.shell:
            return {"text": "Streamlit shell"}
        return self.page.states[self.page.phase]

    def locator(self, selector):
        kinds = {
            "body": "body", '[data-testid="stException"]': "exception", '[data-testid="stMetric"]': "metric",
            '.st-key-portfolio_case_answer [data-testid="stText"]': "answer",
        }
        return FakeLocator(self, kinds[selector])

    def get_by_role(self, role, *, name, exact):
        assert role == "button" and exact is True
        return FakeLocator(self, "button", name)


class FakePage:
    url = "https://finance-model-eval.streamlit.app/"

    def __init__(self, initial="home", home=HOME, detail=DETAIL, metric="AI评分\n82.5", answer="已保存的专业分析回答。"):
        self.phase = initial
        self.clicks = []
        self.ticks = 0
        self.states = {
            "home": {"text": home, "buttons": ["查看完整案例 →", "运行评测", "继续评分"]},
            "sleep": {"text": "This app has gone to sleep.", "buttons": ["Yes, get this app back up!"]},
            "loading": {"text": "Loading...", "buttons": []},
            "detail": {"text": detail, "metric": metric, "answer": answer, "buttons": ["重新评分", "删除记录"]},
        }
        # The useful app is inside an iframe; the shell alone never passes.
        self.frames = [FakeFrame(self, shell=True), FakeFrame(self)]

    def wait_for_timeout(self, milliseconds):
        self.ticks += milliseconds / 1000


def inspect(smoke, page):
    return smoke.inspect_public_page(page, timeout=2, poll_interval=0.25, clock=lambda: page.ticks)


def test_scored_home_and_detail_are_read_inside_iframe(smoke):
    page = FakePage()
    inspect(smoke, page)
    assert page.clicks == ["查看完整案例 →"]


def test_sleeping_app_is_woken_once_then_checked(smoke):
    page = FakePage(initial="sleep")
    inspect(smoke, page)
    assert page.clicks == ["Yes, get this app back up!", "查看完整案例 →"]


def test_loading_and_http_200_equivalent_content_never_pass(smoke):
    page = FakePage(initial="loading")
    with pytest.raises(smoke.ProbeFailure, match="homepage"):
        inspect(smoke, page)
    assert page.clicks == []


@pytest.mark.parametrize("metric", ["AI评分\n—", "AI评分\n未记录", "", "AI评分\nnan"])
def test_unscored_detail_never_passes(smoke, metric):
    with pytest.raises(smoke.ProbeFailure, match="case detail"):
        inspect(smoke, FakePage(metric=metric))


@pytest.mark.parametrize("answer", [None, "", " \n\t"])
def test_case_headings_and_score_without_actual_answer_never_pass(smoke, answer):
    with pytest.raises(smoke.ProbeFailure, match="case detail"):
        inspect(smoke, FakePage(answer=answer))


def test_hidden_case_answer_never_passes(smoke):
    page = FakePage()
    page.states["detail"]["answer_hidden"] = True
    with pytest.raises(smoke.ProbeFailure, match="case detail"):
        inspect(smoke, page)


def test_stale_home_with_application_exception_fails(smoke):
    page = FakePage()
    page.states["home"]["exception"] = True
    with pytest.raises(smoke.ProbeFailure, match="homepage"):
        inspect(smoke, page)
    assert page.clicks == []


def test_homepage_requires_a_numeric_saved_score(smoke):
    page = FakePage(home=HOME.replace("82.5", "未记录"))
    with pytest.raises(smoke.ProbeFailure):
        inspect(smoke, page)
    assert page.clicks == []


def test_click_allowlist_rejects_paid_and_management_actions(smoke):
    page = FakePage()
    for label in ["运行评测", "继续评分", "重新评分", "删除记录", "查看专业任务 →"]:
        with pytest.raises(smoke.ProbeFailure, match="disallowed"):
            smoke.click_allowed(page.frames[1], label)
    assert page.clicks == []


class FakeConnection:
    def __init__(self):
        self.read_only = False
        self.statements = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def cursor(self):
        return self

    def execute(self, statement):
        assert self.read_only is True
        self.statements.append(statement)

    def fetchone(self):
        return ("private-run-identifier",)


def test_database_probe_is_one_select_in_readonly_transaction(smoke, capsys):
    connection = FakeConnection()
    connect_calls = []

    def connect(url, **kwargs):
        connect_calls.append((url, kwargs))
        return connection

    smoke.probe_database(DATABASE_URL, connect=connect)
    assert connection.statements == ["SELECT run_id FROM public.live_evaluation_runs LIMIT 1"]
    assert "default_transaction_read_only=on" in connect_calls[0][1]["options"]
    assert connection.closed
    assert capsys.readouterr().out == ""


def test_database_without_any_saved_run_fails(smoke):
    connection = FakeConnection()
    connection.fetchone = lambda: None
    with pytest.raises(smoke.ProbeFailure, match="database read check failed"):
        smoke.probe_database(DATABASE_URL, connect=lambda *args, **kwargs: connection)


@pytest.mark.parametrize("url", [
    "http://private-host/db?sslmode=require",
    "postgresql://private-host/db",
    "postgresql://private-host/db?sslmode=disable",
    "postgresql://private-host/db?sslmode=prefer",
    "postgresql:///db?sslmode=require",
])
def test_database_config_requires_postgres_and_required_tls(smoke, url):
    with pytest.raises(smoke.ConfigurationFailure):
        smoke.validate_database_url(url)


def test_database_failure_never_exposes_exception_or_credentials(smoke, capsys):
    def connect(*args, **kwargs):
        raise RuntimeError("postgresql://role:LEAKED_PASSWORD@private-host/db private-run-identifier")

    with pytest.raises(smoke.ProbeFailure, match="database read check failed") as failure:
        smoke.probe_database("postgresql://role:LEAKED_PASSWORD@private-host/db?sslmode=require", connect=connect)
    assert "LEAKED" not in str(failure.value)
    assert failure.value.__suppress_context__ is True
    assert capsys.readouterr().out == ""


def test_missing_secret_fails_before_any_network_or_dependency_import(smoke, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("missing configuration must fail before probes")

    code = smoke.main([], environ={}, database_probe=forbidden, browser_probe=forbidden)
    assert code == 2
    output = capsys.readouterr()
    assert "CONFIGURATION FAILURE" in output.err
    assert "FINDUEVAL_HEALTHCHECK_DATABASE_URL" in output.err


@pytest.mark.parametrize("url", [
    "http://finance-model-eval.streamlit.app/",
    "https://evil.example/",
    "https://user:password@finance-model-eval.streamlit.app/",
    "https://finance-model-eval.streamlit.app/?ticket=secret",
    "https://finance-model-eval.streamlit.app/?page=evaluation",
    "https://finance-model-eval.streamlit.app/#token",
    "https://finance-model-eval.streamlit.app:444/",
    "https://finance-model-eval.streamlit.app/other",
])
def test_public_target_rejects_non_homepage_credentials_and_tickets(smoke, url):
    with pytest.raises(smoke.ConfigurationFailure):
        smoke.validate_public_url(url)


def test_main_runs_both_checks_and_reports_only_boolean_status(smoke, capsys):
    calls = []
    code = smoke.main([], environ={"FINDUEVAL_HEALTHCHECK_DATABASE_URL": DATABASE_URL},
                      database_probe=lambda url: calls.append("database"),
                      browser_probe=lambda url: calls.append("browser"))
    assert code == 0
    assert calls == ["database", "browser"]
    assert "PASSED" in capsys.readouterr().out


def test_main_redacts_unexpected_errors_and_returns_failure(smoke, capsys):
    def fail(url):
        raise RuntimeError("private credential details")

    code = smoke.main([], environ={"FINDUEVAL_HEALTHCHECK_DATABASE_URL": DATABASE_URL},
                      database_probe=fail, browser_probe=lambda url: None)
    assert code == 1
    output = capsys.readouterr()
    assert "private" not in output.out + output.err


def test_database_failure_tells_operator_to_check_status_and_manually_resume(smoke, capsys):
    def fail(url):
        raise RuntimeError("credential=private")

    code = smoke.main([], environ={"FINDUEVAL_HEALTHCHECK_DATABASE_URL": DATABASE_URL},
                      database_probe=fail, browser_probe=lambda url: None)
    assert code == 1
    output = capsys.readouterr().err
    assert "Check Supabase project status" in output
    assert "if paused, use manual Resume" in output
    assert "never resumes projects automatically" in output
    assert "duration=" in output
    assert "private" not in output


def test_probe_has_no_application_import_or_initialization(smoke):
    import ast

    tree = ast.parse((ROOT / "scripts" / "production_smoke.py").read_text())
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(module.split(".")[0] in {"app", "src", "streamlit", "supabase"} for module in modules)


def test_foreign_iframe_with_matching_ui_is_never_clicked(smoke):
    page = FakePage()
    page.frames[1].url = "https://foreign.example/"
    with pytest.raises(smoke.ProbeFailure):
        inspect(smoke, page)
    assert page.clicks == []


def test_screenshot_masks_public_exception_and_skips_foreign_origin(smoke, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    page = FakePage()
    screenshots = []
    page.screenshot = lambda **kwargs: screenshots.append(kwargs)
    smoke._save_failure_screenshot(page)
    assert len(screenshots) == 1
    assert len(screenshots[0]["mask"]) == len(page.frames)
    page.url = "https://foreign.example/"
    smoke._save_failure_screenshot(page)
    assert len(screenshots) == 1


def test_workflow_has_disabled_schedule_manual_validation_and_minimal_permissions():
    import yaml

    path = ROOT / ".github" / "workflows" / "production-smoke.yml"
    assert path.exists(), "independent smoke workflow is missing"
    workflow = yaml.safe_load(path.read_text())
    events = workflow.get("on", workflow.get(True))
    assert events["schedule"] == [{"cron": "17 */6 * * *"}]
    assert "workflow_dispatch" in events
    job = workflow["jobs"]["production-smoke"]
    assert "vars.FINDUEVAL_SMOKE_ENABLED == 'true'" in job["if"]
    assert "github.event_name == 'workflow_dispatch'" in job["if"]
    assert job["timeout-minutes"] == 10
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["permissions"] == {"contents": "read"}
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    import re

    assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", action) for action in uses)
    artifact_step = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert artifact_step["if"] == "failure()"
    assert artifact_step["with"]["retention-days"] == 7
