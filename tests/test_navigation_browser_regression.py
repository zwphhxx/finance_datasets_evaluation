"""Task 13 browser regression for Task 7 navigation layout.

Run explicitly with ``FINDUEVAL_RUN_BROWSER_REGRESSION=1``.  The fixture keeps
SQLite absent and points runtime persistence at a refused localhost port, so it
can inspect the read-only navigation without creating a database or calling a
provider.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
_RUN_BROWSER_REGRESSION = os.getenv("FINDUEVAL_RUN_BROWSER_REGRESSION") == "1"
_BROWSER_SESSION = f"fde-navigation-regression-{os.getpid()}"
_VIEWPORTS = ((1710, 1009), (768, 1009), (390, 844), (320, 844))

pytestmark = pytest.mark.browser

if not _RUN_BROWSER_REGRESSION:
    pytest.skip(
        "Task 13 browser regression: set FINDUEVAL_RUN_BROWSER_REGRESSION=1 to run",
        allow_module_level=True,
    )


def _resolve_playwright_cli(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    configured = str(env.get("FINDUEVAL_PLAYWRIGHT_CLI") or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise RuntimeError("FINDUEVAL_PLAYWRIGHT_CLI must be an executable absolute path")
        return str(candidate)

    command = shutil.which("playwright-cli")
    if command:
        return command
    npx = shutil.which("npx")
    if npx:
        return npx
    raise RuntimeError(
        "browser regression requires FINDUEVAL_PLAYWRIGHT_CLI, playwright-cli, or npx on PATH"
    )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_browser(*args: str) -> str:
    executable = _resolve_playwright_cli()
    command = [executable]
    if Path(executable).name == "npx":
        command.extend(["--yes", "--package", "@playwright/cli", "playwright-cli"])
    completed = subprocess.run(
        [*command, "--session", _BROWSER_SESSION, *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    return completed.stdout.strip()


def _browser_result(output: str) -> object:
    result = output.split("### Result\n", 1)[1].splitlines()[0]
    return json.loads(result)


def _open_browser(url: str) -> None:
    last_error: subprocess.CalledProcessError | None = None
    for _attempt in range(3):
        try:
            _run_browser("open", url)
            _run_browser("snapshot")
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(0.5)
    raise AssertionError("Playwright CLI did not retain the browser session") from last_error


def _wait_for_app(url: str, log_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    details = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    raise AssertionError(f"local Streamlit navigation regression app did not start\n{details}")


def _stop_streamlit(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


@pytest.fixture(scope="module")
def local_navigation_app(tmp_path_factory: pytest.TempPathFactory):
    port = _free_port()
    absent_db = tmp_path_factory.mktemp("navigation-browser") / "must-not-exist.db"
    log_path = absent_db.parent / "streamlit.log"
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://127.0.0.1:1/fde_navigation_browser",
        "FINDUEVAL_AUTO_INIT_DB": "0",
        "FINDUEVAL_DB_PATH": str(absent_db),
        "FINDUEVAL_DATABASE_CONNECT_TIMEOUT_SECONDS": "3",
    }
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                "streamlit",
                "run",
                "app.py",
                "--server.headless",
                "true",
                "--server.port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_app(url, log_path)
        yield url, absent_db
    finally:
        try:
            _run_browser("close")
        except subprocess.CalledProcessError:
            pass
        _stop_streamlit(process)


def _layout_snapshot() -> dict[str, object]:
    script = """
    JSON.stringify((() => {
        const review = document.querySelector('.st-key-top_nav_review_region');
        const operation = document.querySelector('.st-key-top_nav_operation_region button');
        const brand = document.querySelector('.top-nav-brand');
        const primary = review ? Array.from(review.querySelectorAll('button')) : [];
        const rect = (element) => {
            const value = element.getBoundingClientRect();
            return { top: value.top, bottom: value.bottom, left: value.left, right: value.right };
        };
        const style = (element) => {
            const value = getComputedStyle(element);
            return { fontSize: value.fontSize, fontWeight: value.fontWeight, color: value.color };
        };
        return {
            brand: brand ? rect(brand) : null,
            operation: operation ? rect(operation) : null,
            primary: primary.map(rect),
            operationStyle: operation ? style(operation) : null,
            primaryStyles: primary.map(style),
            overflow: document.documentElement.scrollWidth - window.innerWidth,
            width: window.innerWidth,
        };
    })())
    """.strip()
    output = _run_browser("eval", script)
    return json.loads(_browser_result(output))


def test_navigation_layout_in_four_real_viewports(local_navigation_app):
    url, absent_db = local_navigation_app
    _open_browser(url)

    for width, height in _VIEWPORTS:
        _run_browser("resize", str(width), str(height))
        _run_browser("reload")
        time.sleep(0.5)
        layout = _layout_snapshot()
        primary = layout["primary"]

        assert layout["width"] == width
        assert len(primary) == 3
        assert max(item["top"] for item in primary) - min(item["top"] for item in primary) <= 1
        assert layout["overflow"] <= 0

        if width <= 760:
            assert layout["brand"]["bottom"] <= min(item["top"] for item in primary)
            assert layout["operation"]["top"] >= max(item["bottom"] for item in primary)
            assert layout["operation"]["right"] >= max(item["right"] for item in primary) - 1
            primary_style = layout["primaryStyles"][0]
            operation_style = layout["operationStyle"]
            assert float(operation_style["fontSize"].removesuffix("px")) <= float(
                primary_style["fontSize"].removesuffix("px")
            )
            assert int(operation_style["fontWeight"]) <= int(primary_style["fontWeight"])
        else:
            assert abs(layout["operation"]["top"] - primary[0]["top"]) <= 1

    assert not absent_db.exists()


def test_playwright_cli_resolution_requires_valid_explicit_path(tmp_path):
    executable = tmp_path / "playwright-cli"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    assert _resolve_playwright_cli({"FINDUEVAL_PLAYWRIGHT_CLI": str(executable)}) == str(executable)
    with pytest.raises(RuntimeError, match="executable absolute path"):
        _resolve_playwright_cli({"FINDUEVAL_PLAYWRIGHT_CLI": "relative-cli"})


def test_playwright_cli_resolution_fails_clearly_without_explicit_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="requires FINDUEVAL_PLAYWRIGHT_CLI"):
        _resolve_playwright_cli({})


def test_playwright_cli_resolution_uses_path_npx_fallback(monkeypatch):
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )

    assert _resolve_playwright_cli({}) == "/usr/bin/npx"


def test_stop_streamlit_kills_after_terminate_timeout():
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("streamlit", 10), None]

    _stop_streamlit(process)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
