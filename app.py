import streamlit as st

from src.data_service import DataLoadError, load_all_data
from src.ui.navigation import PAGES
from src.validators import ValidationResult, validate_evaluation_data


st.set_page_config(page_title="FinDueEval MVP", layout="wide")

try:
    data = load_all_data()
except DataLoadError as exc:
    st.sidebar.title("导航")
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

st.sidebar.title("导航")
page = st.sidebar.radio("选择页面", tuple(PAGES.keys()))
PAGES[page](data_bundle)
