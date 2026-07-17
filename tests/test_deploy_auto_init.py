"""Deployment startup tests for SQLite auto initialization."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.db.repository import Repository
from app.services import dataset_service as ds

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class DeployAutoInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "findueval_deploy.db"
        self.previous_db = os.environ.get("FINDUEVAL_DB_PATH")
        self.previous_auto = os.environ.get("FINDUEVAL_AUTO_INIT_DB")
        st.cache_data.clear()

    def tearDown(self):
        if self.previous_db is None:
            os.environ.pop("FINDUEVAL_DB_PATH", None)
        else:
            os.environ["FINDUEVAL_DB_PATH"] = self.previous_db
        if self.previous_auto is None:
            os.environ.pop("FINDUEVAL_AUTO_INIT_DB", None)
        else:
            os.environ["FINDUEVAL_AUTO_INIT_DB"] = self.previous_auto
        st.cache_data.clear()
        self.tmp.cleanup()

    def _run_app(self):
        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=60)
        self.assertEqual(list(at.exception), [])
        return at

    def test_missing_database_is_initialized_by_default(self):
        os.environ["FINDUEVAL_DB_PATH"] = str(self.db_path)
        os.environ.pop("FINDUEVAL_AUTO_INIT_DB", None)

        self._run_app()

        self.assertTrue(self.db_path.exists())
        self.assertTrue(ds.database_ready(self.db_path))

    def test_existing_database_is_not_overwritten(self):
        ds.ensure_seed_database(self.db_path, force=True)
        repo = Repository(self.db_path)
        repo.insert("evaluation_runs", {"run_id": "RUN-AUTO-INIT-MARKER", "run_name": "保留记录"})
        before = repo.count("evaluation_runs")
        os.environ["FINDUEVAL_DB_PATH"] = str(self.db_path)
        os.environ.pop("FINDUEVAL_AUTO_INIT_DB", None)

        self._run_app()

        repo_after = Repository(self.db_path)
        self.assertEqual(before, repo_after.count("evaluation_runs"))
        self.assertEqual("保留记录", repo_after.get("evaluation_runs", "RUN-AUTO-INIT-MARKER")["run_name"])

    def test_auto_init_can_be_disabled(self):
        os.environ["FINDUEVAL_DB_PATH"] = str(self.db_path)
        os.environ["FINDUEVAL_AUTO_INIT_DB"] = "0"

        self._run_app()

        self.assertFalse(self.db_path.exists())
        self.assertFalse(ds.database_ready(self.db_path))

    def test_sqlite_database_files_remain_ignored(self):
        gitignore = (APP_PATH.parents[0] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("app/db/*.db", gitignore)


if __name__ == "__main__":
    unittest.main()
