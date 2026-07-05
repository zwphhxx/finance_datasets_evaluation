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
        subtitle="说明项目定位、评测流程、样本口径与使用边界。",
        question="面向金融尽调场景的模型评测样本库 MVP，用于把样本、评分草稿和人工复核沉淀为当前样本内观察。",
        boundary="样本为脱敏抽象编写，不含真实公司与敏感数据；本项目是尽调可用边界评测，不是模型排行榜。",
        highlights="项目定位、评测流程、动态指标、样本库与发起测试入口。",
        nav_summary="项目定位与流程",
    ),
    PageConfig(
        page_key="samples",
        title="样本库",
        subtitle="维护正式评测样本，确认哪些样本可进入测试。",
        question="正式评测样本的维护入口；在这里新增样本、查询索引、查看详情并处理归档。",
        boundary="样本状态和完整度共同决定测试准入；只有已入库且完整度通过的样本才可进入发起测试。",
        highlights="新增样本、查询样本、样本列表、选中样本详情。",
        nav_summary="样本库",
    ),
    PageConfig(
        page_key="test_run",
        title="发起测试",
        subtitle="执行评测：选择可测样本和对比模型，生成待人工复核的评分草稿。",
        question="按选择样本、选择模型、运行回答、生成评分草稿完成一次评测执行。",
        boundary="被评测模型只看到任务题、业务背景与输出要求，不看到理想回复标准 / Gold Answer；评分草稿需人工复核后才进入正式结论。",
        highlights="选择样本、选择模型、运行回答、生成评分草稿。",
        nav_summary="发起测试",
    ),
    PageConfig(
        page_key="review",
        title="评测复核",
        subtitle="对照理想回复标准、模型回答、评分矩阵和错误归因，确认评分草稿。",
        question="查看模型回答与 Gold Answer 的差距，核对扣分原因、红线提示并完成人工复核。",
        boundary="评分草稿只可作为复核输入；确认归档前不可作为正式结论或业务依据。",
        highlights="任务与背景、Gold Answer、模型回答摘要、评分矩阵、错误归因、红线提示、人工复核。",
        nav_summary="评测复核",
    ),
    PageConfig(
        page_key="conclusions",
        title="评测结论",
        subtitle="汇总已沉淀和已人工复核的评分，形成当前样本内正式结论与使用边界。",
        question="查看正式结论、模型使用边界和仍待复核的评分草稿；这里不是模型排行榜。",
        boundary="正式结论只含已沉淀结论与已复核归档结论；边界判断不是模型排行榜，评分草稿未计入。",
        highlights="正式结论汇总、模型使用边界、高频问题归纳、待复核草稿。",
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
