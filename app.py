import streamlit as st

from app.services.dataset_service import load_evaluation_data
from src.data_service import DataLoadError
from src.ui.components import apply_global_styles
from src.ui.navigation import PAGES, render_sidebar_navigation
from src.validators import ValidationResult, validate_evaluation_data


st.set_page_config(page_title="模型评测及数据优化", layout="wide")
apply_global_styles()

try:
    # 优先从 SQLite 数据层读取；数据库未初始化时回退到 data/ 种子文件。
    data = load_evaluation_data()
except DataLoadError as exc:
    st.error(str(exc))
    st.stop()

try:
    validation_result = validate_evaluation_data(data)
except Exception:
    validation_result = ValidationResult(
        errors=["数据质量检查未能完成。请检查数据结构后重试。"],
        warnings=[],
    )

data_bundle = {
    "data": data,
    "validation_result": validation_result,
}

page = render_sidebar_navigation()
PAGES[page](data_bundle)
