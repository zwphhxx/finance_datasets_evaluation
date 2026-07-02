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
        title="Case Study",
        subtitle="说明这套尽调评测的目的、样本来源、评价框架与使用方式。",
        question="本页用于说明项目要解决什么问题、样本从哪来、怎么评、以及如何使用评测结果。",
        boundary="样本为脱敏抽象编写，不含真实公司与敏感数据；本项目是尽调可用边界评测，不是模型排行榜。",
        highlights="项目背景、样本来源与结构、评价框架、红线机制与使用方式。",
        nav_summary="项目介绍与方法论",
    ),
    PageConfig(
        page_key="samples",
        title="样本库",
        subtitle="样本库 = 任务内容 + 评判标准；含 add/edit sample。",
        question="本页用于浏览样本列表、查看评判标准完整性，并新增或编辑样本与 Gold Answer。",
        boundary="当前任务是脱敏专业任务样本，不是概念题，也不是完整行业题库。",
        highlights="样本列表、评判标准完整性、新增/编辑样本、Gold Answer 管理。",
        nav_summary="样本库",
    ),
    PageConfig(
        page_key="test_run",
        title="发起测试",
        subtitle="选择样本与模型，运行评测并获取裁判建议分。",
        question="本页用于选择样本与模型，发起模型评测并获取裁判建议分。",
        boundary="被评测模型仅见任务题、背景与输出要求，绝不见 Gold Answer；裁判模型固定为 deepseek-ai/DeepSeek-V4-Pro。",
        highlights="样本选择、模型选择、裁判评分（固定 DeepSeek-V4-Pro）、人工复核。",
        nav_summary="发起测试",
    ),
    PageConfig(
        page_key="review",
        title="评测复核",
        subtitle="逐条查看评判标准、模型回复、各维度建议分与扣分理由，人工复核后归档。",
        question="本页用于逐条查看评判标准、模型回复、各维度建议分与扣分理由，人工复核后归档。",
        boundary="单题复核只服务于样本内观察，不代表模型整体能力。",
        highlights="评判标准、模型回复、维度建议分、扣分理由、红线触发、使用边界、人工复核。",
        nav_summary="评测复核",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        subtitle="汇总正式评测结论：seed + confirmed live；模型 averages、weaknesses、usage boundaries。",
        question="本页用于查看当前样本内的正式评测结论，并区分 seed 基准与已复核归档的现场结论。",
        boundary="正式结论只含 seed 已有结论与已复核归档结论；现场草稿未计入；这是样本内可用边界观察，不是模型排行榜。",
        highlights="正式结论多维度汇总、人工点评摘要、高频问题归纳、草稿待复核与复核归档流程。",
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
