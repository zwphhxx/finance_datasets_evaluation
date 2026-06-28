from __future__ import annotations

from src.ui.case_detail import render_case_detail_page
from src.ui.error_analysis import render_error_analysis_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.optimization_compare import render_optimization_compare_page
from src.ui.overview import render_overview_page
from src.ui.tasks import render_tasks_page


PAGES = {
    "评测项目总览": render_overview_page,
    "专业任务集": render_tasks_page,
    "样板题深度评测": render_case_detail_page,
    "模型能力诊断": render_model_diagnosis_page,
    "错误归因与数据补强": render_error_analysis_page,
    "优化验证": render_optimization_compare_page,
}
