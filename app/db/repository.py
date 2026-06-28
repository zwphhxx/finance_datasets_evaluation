"""SQLite 仓储层（repository）。

封装对 FinDueEval SQLite 数据库的基础读写，避免在页面或服务中散落原始 SQL。
仅依赖标准库 sqlite3 与 pandas，不引入任何外部数据库或 ORM。

读取统一返回 pandas.DataFrame（与现有以 DataFrame 为中心的页面/指标层一致），
写入提供 insert / update / delete 等基础方法，便于后续 CRUD 与运行记录留存。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


# 各表主键列名。无单列业务主键的表使用自增 id。
TABLE_PRIMARY_KEYS: dict[str, str] = {
    "task_cases": "case_id",
    "gold_answers": "case_id",
    "rubrics": "dimension_field",
    "model_responses": "output_id",
    "score_records": "output_id",
    "error_annotations": "id",
    "improvement_actions": "id",
    "evaluation_runs": "run_id",
}

# 写入时由数据库默认值维护、调用方无需显式提供的列。
_MANAGED_COLUMNS = {"created_at"}


class RepositoryError(RuntimeError):
    """仓储层操作失败时抛出。"""


class Repository:
    """对单个 SQLite 数据库文件的轻量读写封装。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    # -- 连接管理 -------------------------------------------------------------
    @contextmanager
    def connect(self):
        if not self.db_path.exists():
            raise RepositoryError(f"数据库文件不存在：{self.db_path}。请先运行 app/db/init_db.py 初始化。")
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON;")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # -- 读取 -----------------------------------------------------------------
    def list_df(self, table: str, *, order_by: str | None = None) -> pd.DataFrame:
        """读取整张表为 DataFrame，可选排序（默认按主键/插入顺序稳定）。"""
        self._ensure_known_table(table)
        order = order_by or TABLE_PRIMARY_KEYS[table]
        query = f"SELECT * FROM {table} ORDER BY {order}"
        with self.connect() as connection:
            return pd.read_sql_query(query, connection)

    def count(self, table: str) -> int:
        self._ensure_known_table(table)
        with self.connect() as connection:
            cursor = connection.execute(f"SELECT COUNT(*) AS n FROM {table}")
            return int(cursor.fetchone()["n"])

    def get(self, table: str, key: Any, *, key_column: str | None = None) -> dict | None:
        self._ensure_known_table(table)
        column = key_column or TABLE_PRIMARY_KEYS[table]
        with self.connect() as connection:
            cursor = connection.execute(f"SELECT * FROM {table} WHERE {column} = ?", (key,))
            row = cursor.fetchone()
            return dict(row) if row is not None else None

    # -- 写入 -----------------------------------------------------------------
    def insert(self, table: str, values: dict[str, Any]) -> int:
        """插入一行，返回新行的 rowid。created_at/updated_at 缺省由数据库填充。"""
        self._ensure_known_table(table)
        columns = list(values.keys())
        if not columns:
            raise RepositoryError("insert 需要至少一个字段。")
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                tuple(values[column] for column in columns),
            )
            return int(cursor.lastrowid)

    def bulk_insert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        """批量插入，返回插入行数。所有行需具有一致的列集合。"""
        self._ensure_known_table(table)
        rows = list(rows)
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        payload = [tuple(row.get(column) for column in columns) for row in rows]
        with self.connect() as connection:
            connection.executemany(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                payload,
            )
        return len(payload)

    def update(self, table: str, key: Any, changes: dict[str, Any], *, key_column: str | None = None) -> int:
        """按主键更新若干字段，自动刷新 updated_at，返回受影响行数。"""
        self._ensure_known_table(table)
        column = key_column or TABLE_PRIMARY_KEYS[table]
        editable = {k: v for k, v in changes.items() if k not in _MANAGED_COLUMNS and k != column}
        if not editable:
            raise RepositoryError("update 需要至少一个可修改字段。")
        assignments = ", ".join(f"{name} = ?" for name in editable)
        assignments += ", updated_at = datetime('now')"
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments} WHERE {column} = ?",
                (*editable.values(), key),
            )
            return cursor.rowcount

    def delete(self, table: str, key: Any, *, key_column: str | None = None) -> int:
        self._ensure_known_table(table)
        column = key_column or TABLE_PRIMARY_KEYS[table]
        with self.connect() as connection:
            cursor = connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (key,))
            return cursor.rowcount

    # -- 内部工具 -------------------------------------------------------------
    def _ensure_known_table(self, table: str) -> None:
        if table not in TABLE_PRIMARY_KEYS:
            raise RepositoryError(f"未知数据表：{table}。")
