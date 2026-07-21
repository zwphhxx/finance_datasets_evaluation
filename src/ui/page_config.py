from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageConfig:
    page_key: str
    title: str
    question: str


PAGE_CONFIGS = [
    PageConfig(
        page_key="case_study",
        title="项目说明",
        question="评估模型在财务、法律、投行等专业场景中的回答质量、主要问题和使用边界。",
    ),
    PageConfig(
        page_key="samples",
        title="样本库",
        question="维护正式评测样本。完整且已入库的样本可以进入发起评测。",
    ),
    PageConfig(
        page_key="test_run",
        title="发起评测",
        question="选择样本和模型，运行评测并生成 AI 评分。",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        question="基于当前样本、模型回答和 AI 评分生成评测结论。",
    ),
]

PAGE_CONFIG_BY_KEY = {config.page_key: config for config in PAGE_CONFIGS}
DEFAULT_PAGE_KEY = "case_study"


def get_page_config(page_key: str) -> PageConfig:
    return PAGE_CONFIG_BY_KEY.get(page_key, PAGE_CONFIG_BY_KEY[DEFAULT_PAGE_KEY])
