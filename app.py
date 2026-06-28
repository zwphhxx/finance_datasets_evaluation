import streamlit as st

from app.services.dataset_service import load_evaluation_data
from src.data_service import DataLoadError
from src.ui.components import apply_global_styles
from src.ui.eval_console import resolve_active_data
from src.ui.navigation import PAGES, render_sidebar_navigation
from src.validators import ValidationResult, validate_evaluation_data


st.set_page_config(page_title="模型评测及数据优化", layout="wide")
apply_global_styles()

try:
    # 优先从 SQLite 数据层读取；数据库未初始化时回退到 data/ 种子文件。
    # base 提供题库与 Gold（参考），结果（model_outputs/scores）由真实评测置换。
    base = load_evaluation_data()
except DataLoadError as exc:
    st.error(str(exc))
    st.stop()

try:
    # 数据质量校验仍针对数据集本体（题库 / Gold 等 seed 资产）。
    validation_result = validate_evaluation_data(base)
except Exception:
    validation_result = ValidationResult(
        errors=["数据质量检查未能完成。请检查数据结构后重试。"],
        warnings=[],
    )

# 把会话中的真实运行 + 裁判评分组装为分析页可用的 EvaluationData；未运行时结果类为空。
data, eval_status = resolve_active_data(base)

data_bundle = {
    "data": data,
    "base": base,
    "validation_result": validation_result,
    "eval_status": eval_status,
}

page = render_sidebar_navigation()
PAGES[page](data_bundle)
