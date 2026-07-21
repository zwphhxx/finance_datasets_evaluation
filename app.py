import os

import streamlit as st

from app.services import dataset_service as ds
from app.services.data_resolver import resolve_active_data
from src.data_service import DataLoadError
from src.ui.components import apply_global_styles
from src.ui.navigation import PAGES, render_sidebar_navigation

AUTO_INIT_DB_ENV = "FINDUEVAL_AUTO_INIT_DB"
_DISABLED_AUTO_INIT_VALUES = {"0", "false", "no", "off"}


def _auto_init_db_enabled() -> bool:
    value = os.getenv(AUTO_INIT_DB_ENV, "").strip().lower()
    return value not in _DISABLED_AUTO_INIT_VALUES


def _ensure_deploy_database() -> None:
    """Initialize local SQLite from seed data when deployment cannot run CLI setup."""
    if not _auto_init_db_enabled():
        return
    db_path = ds.get_db_path()
    if ds.database_ready(db_path):
        return
    try:
        ds.ensure_seed_database(db_path, force=False)
    except Exception:
        st.warning(
            "SQLite 自动初始化未完成，当前将回退读取 data/ 种子文件；"
            "样本 CRUD 的正式数据层同步可能不可用。"
        )


st.set_page_config(page_title="模型评测及数据优化", layout="wide")
apply_global_styles()
_ensure_deploy_database()

try:
    # 优先从 SQLite 数据层读取；数据库未初始化时回退到 data/ 种子文件。
    # base 提供题库与 Gold（参考），结果（model_outputs/scores）由真实评测置换。
    base = ds.load_evaluation_data()
except DataLoadError as exc:
    st.error(str(exc))
    st.stop()

# 把会话中的真实运行 + 裁判评分组装为分析页可用的 EvaluationData；未运行时结果类为空。
data, _eval_status = resolve_active_data(base)

data_bundle = {
    "data": data,
    "base": base,
}

page = render_sidebar_navigation()
PAGES[page](data_bundle)
