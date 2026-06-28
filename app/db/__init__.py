"""FinDueEval SQLite 数据层包。

集中暴露 schema 与默认数据库路径，供 init_db、repository 与 service 复用。
"""

from __future__ import annotations

from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DEFAULT_DB_PATH = DB_DIR / "findueval.db"


def default_db_path() -> Path:
    return DEFAULT_DB_PATH
