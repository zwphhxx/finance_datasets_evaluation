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
        boundary="正式结论必须经过人工确认，只代表当前已确认样本范围内的观察。",
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
        subtitle="执行评测：选择可测样本和对比模型，生成待确认的评分草稿。",
        question="选择样本和模型，生成模型回答与评分草稿。",
        boundary="被评测模型只看到任务题、业务背景与输出要求，不看到专业标准答案；评分草稿需人工确认后才纳入正式结论。",
        highlights="评测配置、模型回答、评分草稿。",
        nav_summary="发起评测",
    ),
    PageConfig(
        page_key="review",
        title="评分确认",
        subtitle="确认评分草稿，必要时在对话框中修订分数与复核说明。",
        question="确认评分草稿是否纳入正式结论。",
        boundary="评分草稿只可作为确认输入；确认生效前不可作为正式结论或业务依据。",
        highlights="待处理评分、当前评分摘要、评分依据、确认处理。",
        nav_summary="评分确认",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        subtitle="汇总已确认评分与复核说明，形成当前样本内正式结论与使用边界。",
        question="仅汇总已确认评分，形成当前样本内观察。",
        boundary="正式结论只含已确认评分；待确认评分不会进入正式结论。",
        highlights="当前结论、模型当前判断、模型详情、待确认评分。",
        nav_summary="正式结论",
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
