from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageConfig:
    page_key: str
    title: str
    subtitle: str
    question: str
    boundary: str
    highlights: str
    nav_summary: str


PAGE_CONFIGS = [
    PageConfig(
        page_key="case_study",
        title="项目说明",
        subtitle="一页说明项目定位、评测流程与数据边界。",
        question="评估模型在财务、法律、投行等专业场景中的回答质量、主要问题和使用边界。",
        boundary="AI 评测结论只代表当前样本范围内的自动评测结果。",
        highlights="项目定位、评测流程、数据边界。",
        nav_summary="项目定位与流程",
    ),
    PageConfig(
        page_key="samples",
        title="样本库",
        subtitle="维护正式评测样本，确认哪些样本可进入测试。",
        question="维护正式评测样本。完整且已入库的样本可以进入发起评测。",
        boundary="样本状态和完整度共同决定测试准入；只有已入库且完整度通过的样本才可进入发起评测。",
        highlights="查询与筛选、样本列表、当前样本。",
        nav_summary="样本库",
    ),
    PageConfig(
        page_key="test_run",
        title="发起评测",
        subtitle="执行评测：选择可测样本和对比模型，生成模型回答与 AI 评分。",
        question="选择样本和模型，运行评测并生成 AI 评分。",
        boundary="被评测模型只看到任务题、业务背景与输出要求，不看到专业标准答案；AI 评分成功后直接进入评测结论。",
        highlights="评测配置、模型回答、AI 评分。",
        nav_summary="发起评测",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        subtitle="汇总 AI 评分结果，形成当前样本范围内的评测结论与使用边界。",
        question="基于当前样本、模型回答和 AI 评分生成评测结论。",
        boundary="结论只代表当前样本范围内的自动评测结果，不代表模型整体能力或采购建议。",
        highlights="当前结论、模型当前判断、模型详情。",
        nav_summary="评测结论",
    ),
]

PAGE_CONFIG_BY_KEY = {config.page_key: config for config in PAGE_CONFIGS}
PAGE_CONTEXTS = {
    config.title: {
        "question": config.question,
        "boundary": config.boundary,
        "highlights": config.highlights,
    }
    for config in PAGE_CONFIGS
}
DEFAULT_PAGE_KEY = "case_study"


def get_page_config(page_key: str) -> PageConfig:
    return PAGE_CONFIG_BY_KEY.get(page_key, PAGE_CONFIG_BY_KEY[DEFAULT_PAGE_KEY])
