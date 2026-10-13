from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageConfig:
    page_key: str
    title: str
    question: str


PAGE_CONFIGS = [
    PageConfig("review", "案例分析", "核对专业任务、模型回答及评价依据。"),
    PageConfig(
        page_key="conclusions",
        title="评测结果",
        question="从一个专业任务，查看模型回答及评价依据。",
    ),
    PageConfig(
        page_key="case_study",
        title="评测方法",
        question="了解专业样本、评分流程与结论的适用范围。",
    ),
    PageConfig(
        page_key="samples",
        title="样本维护",
        question="维护正式评测样本。完整且已入库的样本可以在发起评测中使用。",
    ),
    PageConfig(
        page_key="test_run",
        title="发起评测",
        question="选择样本和模型，运行评测并自动完成评分。",
    ),
]

PAGE_CONFIG_BY_KEY = {config.page_key: config for config in PAGE_CONFIGS}
DEFAULT_PAGE_KEY = "conclusions"


def get_page_config(page_key: str) -> PageConfig:
    return PAGE_CONFIG_BY_KEY.get(page_key, PAGE_CONFIG_BY_KEY[DEFAULT_PAGE_KEY])
