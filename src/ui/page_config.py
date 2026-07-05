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
        subtitle="说明项目定位、评测闭环、样本口径与使用边界。",
        question="本页用于说明 FinDueEval 如何把待复核样本沉淀为可复核、可归档的尽调评测结论。",
        boundary="样本为脱敏抽象编写，不含真实公司与敏感数据；本项目是尽调可用边界评测，不是模型排行榜。",
        highlights="项目定位、评测闭环、动态指标、样本库与发起测试入口。",
        nav_summary="项目定位与流程",
    ),
    PageConfig(
        page_key="samples",
        title="样本库",
        subtitle="维护正式评测样本，确认哪些样本可进入测试。",
        question="本页用于筛选样本、查看样本详情，并在管理区维护任务题、理想回复标准 / Gold Answer、Rubric 评分标准和状态。",
        boundary="样本状态用于测试准入；已入库且评判标准完整的样本才可进入发起测试。",
        highlights="筛选搜索、样本清单、选中样本详情、折叠式样本管理。",
        nav_summary="样本库",
    ),
    PageConfig(
        page_key="test_run",
        title="发起测试",
        subtitle="评测执行页：选择可测样本和对比模型，生成待人工复核的评分草稿。",
        question="本页按选择样本、选择对比模型、运行模型回答、生成评分草稿组织流程。",
        boundary="被评测模型只看到任务题、业务背景与输出要求，不看到理想回复标准 / Gold Answer；评分草稿需人工复核后才进入正式结论。",
        highlights="选择样本、选择模型、运行回答、生成评分草稿。",
        nav_summary="发起测试",
    ),
    PageConfig(
        page_key="review",
        title="评测复核",
        subtitle="逐条核对理想回复标准 / Gold Answer、模型回复、建议分与扣分理由，确认后归档。",
        question="本页用于对评分草稿进行人工复核，必要时修订分数与复核说明。",
        boundary="单题复核只服务于样本内观察，不代表模型整体能力。",
        highlights="理想回复标准 / Gold Answer、模型回复、维度建议分、扣分理由、红线触发、人工复核。",
        nav_summary="评测复核",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        subtitle="汇总已沉淀和已人工复核的评分，形成当前样本内正式结论。",
        question="本页用于查看正式结论、模型可用边界和仍待复核的评分草稿。",
        boundary="正式结论只含已沉淀结论与已复核归档结论；评分草稿未计入。",
        highlights="正式结论汇总、人工点评摘要、高频问题归纳、待复核草稿。",
        nav_summary="正式结论与复核归档",
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
