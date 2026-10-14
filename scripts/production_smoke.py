#!/usr/bin/env python3
"""Read the public app and one SELECT-only database table; never import the app."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PUBLIC_URL = "https://finance-model-eval.streamlit.app/"
DATABASE_SECRET = "FINDUEVAL_HEALTHCHECK_DATABASE_URL"
ALLOWED_CLICKS = frozenset({"Yes, get this app back up!", "查看完整案例 →"})
READ_QUERY = "SELECT run_id FROM public.live_evaluation_runs LIMIT 1"
SCORE_PATTERN = re.compile(r"AI评分[：:\s]*([0-9]+(?:\.[0-9]+)?)(?![\w.])")


class ConfigurationFailure(Exception):
    """Missing or unsafe probe configuration; messages contain no credentials."""


class ProbeFailure(Exception):
    """A generic operational failure safe to print in a public CI log."""


def validate_public_url(value: str) -> str:
    """Only the known HTTPS homepage is accepted; no login or ticket URLs."""
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == "finance-model-eval.streamlit.app"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ConfigurationFailure("public target must be the approved HTTPS homepage") from None
    return PUBLIC_URL


def validate_database_url(value: str) -> str:
    """Require PostgreSQL over TLS without exposing any part of the DSN."""
    try:
        parsed = urlsplit(value)
        ssl_modes = parse_qs(parsed.query).get("sslmode", [])
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and bool(parsed.hostname)
            and not parsed.fragment
            and len(ssl_modes) == 1
            and ssl_modes[0] in {"require", "verify-ca", "verify-full"}
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ConfigurationFailure("database URL must use PostgreSQL and sslmode=require or stricter") from None
    return value


def probe_database(database_url: str, *, connect=None) -> None:
    """Exactly one SELECT; the server and transaction both default to read-only."""
    try:
        if connect is None:
            import psycopg

            connect = psycopg.connect
        with connect(
            database_url,
            connect_timeout=10,
            options="-c default_transaction_read_only=on -c statement_timeout=10000",
        ) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(READ_QUERY)
                if cursor.fetchone() is None:
                    raise ProbeFailure("no saved runtime row")
    except Exception:
        raise ProbeFailure("database read check failed") from None


def click_allowed(frame, label: str) -> None:
    """All probe clicks go through this exact-label allowlist."""
    if label not in ALLOWED_CLICKS:
        raise ProbeFailure("disallowed browser action")
    button = frame.get_by_role("button", name=label, exact=True).first
    button.click(timeout=5000)


def _visible_button(frame, label: str) -> bool:
    button = frame.get_by_role("button", name=label, exact=True).first
    return bool(button.count() and button.is_visible() and button.is_enabled())


def _frame_states(page):
    """Read the wrapper and application iframe separately, without logging text."""
    for frame in page.frames:
        try:
            parsed = urlsplit(frame.url)
            if parsed.scheme != "https" or parsed.hostname != urlsplit(PUBLIC_URL).hostname:
                continue
            if frame.locator('[data-testid="stException"]').count():
                continue
            body = frame.locator("body")
            if body.count() and body.is_visible():
                yield frame, body.inner_text(timeout=1500)
        except Exception:
            # Streamlit reruns can detach an iframe during an ordinary read.
            continue


def inspect_public_page(page, *, timeout=180, poll_interval=1, clock=time.monotonic) -> None:
    """Require a scored homepage, then the saved answer and numeric case score."""
    deadline = clock() + timeout
    woke = False
    opened = False
    while clock() < deadline:
        for frame, text in _frame_states(page):
            if not woke and _visible_button(frame, "Yes, get this app back up!"):
                click_allowed(frame, "Yes, get this app back up!")
                woke = True
                break
            if (
                "专业场景大模型评测" in text
                and "历史回答节选" in text
                and "专业评价" in text
                and SCORE_PATTERN.search(text)
                and _visible_button(frame, "查看完整案例 →")
            ):
                click_allowed(frame, "查看完整案例 →")
                opened = True
                break
        if opened:
            break
        page.wait_for_timeout(poll_interval * 1000)
    if not opened:
        raise ProbeFailure("public homepage did not render a saved scored case")
    while clock() < deadline:
        for frame, text in _frame_states(page):
            if not all(marker in text for marker in ("任务与业务背景", "模型回答", "专业评价")):
                continue
            if "尚无可读取的模型回答" in text or "本次没有有效评分" in text:
                continue
            answer = frame.locator('.st-key-portfolio_case_answer [data-testid="stText"]').first
            if not (answer.count() and answer.is_visible() and answer.inner_text(timeout=1500).strip()):
                continue
            metric = frame.locator('[data-testid="stMetric"]')
            if metric.count() and metric.first.is_visible() and SCORE_PATTERN.search(metric.inner_text(timeout=1500)):
                return
        page.wait_for_timeout(poll_interval * 1000)
    raise ProbeFailure("public case detail did not render a saved answer and numeric score")


def _save_failure_screenshot(page) -> None:
    """Save public UI only on failure; mask server exceptions and omit traces/HAR."""
    try:
        parsed = urlsplit(page.url)
        if parsed.scheme != "https" or parsed.hostname != urlsplit(PUBLIC_URL).hostname:
            return
        masks = [frame.locator('[data-testid="stException"]') for frame in page.frames]
        directory = Path("artifacts")
        directory.mkdir(exist_ok=True)
        page.screenshot(path=str(directory / "production-smoke-failure.png"), full_page=True, mask=masks)
    except Exception:
        pass  # Screenshot failures must not expose URLs, browser logs or page text.


def probe_browser(public_url: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            try:
                # A 200 response is never treated as health; inspect actual rendered UI.
                page.goto(public_url, wait_until="domcontentloaded", timeout=45000)
                inspect_public_page(page)
            except Exception:
                _save_failure_screenshot(page)
                raise ProbeFailure("public browser check failed") from None
        finally:
            browser.close()


def main(argv=None, *, environ=None, database_probe=probe_database, browser_probe=probe_browser) -> int:
    environment = os.environ if environ is None else environ
    database_url = environment.get(DATABASE_SECRET, "").strip()
    # This check deliberately precedes dependency imports and every network call.
    if not database_url:
        print(f"CONFIGURATION FAILURE: missing {DATABASE_SECRET}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=environment.get("FINDUEVAL_SMOKE_URL", PUBLIC_URL))
    arguments = parser.parse_args(argv)
    try:
        public_url = validate_public_url(arguments.url)
        validate_database_url(database_url)
    except ConfigurationFailure as failure:
        print(f"CONFIGURATION FAILURE: {failure}", file=sys.stderr)
        return 2
    stage = "database"
    started = time.monotonic()
    try:
        database_probe(database_url)
        stage = "public browser"
        browser_probe(public_url)
    except Exception:
        # Never stringify backend/browser exceptions: they can contain DSNs or data.
        guidance = (
            " Check Supabase project status; if paused, use manual Resume."
            " This probe never resumes projects automatically."
            if stage == "database"
            else ""
        )
        print(f"SMOKE FAILED: {stage} check failed.{guidance} duration={time.monotonic() - started:.1f}s",
              file=sys.stderr)
        return 1
    print("SMOKE PASSED: SELECT-only database, public homepage, and saved scored case detail"
          f" duration={time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
