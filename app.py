import streamlit as st

from src.data_service import DataLoadError, load_all_data
from src.ui.case_detail import render_case_detail_page
from src.ui.error_analysis import render_error_analysis_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.optimization_compare import render_optimization_compare_page
from src.ui.overview import render_overview_page
from src.ui.tasks import render_tasks_page
from src.validators import ValidationResult, validate_evaluation_data


PAGES = {
    "项目总览": render_overview_page,
    "任务列表": render_tasks_page,
    "单题详情": render_case_detail_page,
    "模型能力诊断": render_model_diagnosis_page,
    "错误归因与优化建议": render_error_analysis_page,
    "优化前后对比": render_optimization_compare_page,
}


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
