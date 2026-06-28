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
        page_key="overview",
        title="评测项目总览",
        subtitle="说明 FinDueEval 的评测对象、数据资产和优化验证路径。",
        question="本页用于判断当前评测集评什么，以及如何支撑模型评测与数据补强。",
        boundary="当前结论仅基于 MVP 样本、脱敏任务和模拟模型回答。",
        highlights="项目定位、关键问题、闭环流程和核心数据资产。",
        nav_summary="项目目标与数据资产",
    ),
    PageConfig(
        page_key="tasks",
        title="专业任务集",
        subtitle="查看脱敏专业任务样本的覆盖范围和基础分布。",
        question="本页用于判断任务样本覆盖哪些专业场景，是否足以支撑后续评测观察。",
        boundary="当前任务是脱敏专业任务样本，不是概念题，也不是完整行业题库。",
        highlights="任务分布、Gold Answer 覆盖、模型回答覆盖和任务表。",
        nav_summary="样本覆盖与任务分布",
    ),
    PageConfig(
        page_key="case_detail",
        title="样板题深度评测",
        subtitle="从一道题拆解优秀回答、模型差异、错误标签和数据补强方向。",
        question="本页用于判断一道专业题如何定义优秀回答，模型回答具体差在哪里。",
        boundary="单题结论只服务于样板题拆解，不代表模型整体能力。",
        highlights="Gold Answer、多模型回答、Rubric 评分、错误标签、偏好样本和数据补强建议。",
        nav_summary="单题评测闭环",
    ),
    PageConfig(
        page_key="model_diagnosis",
        title="模型能力诊断",
        subtitle="基于当前样本观察模型在专业能力维度上的不稳定点。",
        question="本页用于判断当前样本下模型在哪些能力维度更不稳定。",
        boundary="本页不作为模型整体能力结论，也不提供采购建议或性价比判断。",
        highlights="综合得分、分维度得分、错误类型分布、领域场景表现和能力诊断摘要。",
        nav_summary="能力短板观察",
    ),
    PageConfig(
        page_key="error_analysis",
        title="错误归因与数据补强",
        subtitle="把错误表现连接到可能原因、数据补强动作和验证指标。",
        question="本页用于判断错误表现对应什么可能原因，以及后续应该补什么数据。",
        boundary="错误归因来自当前错误标签和优化计划，未匹配记录会保留为空数据提示。",
        highlights="错误分布、可能原因、数据补强动作、样本格式和验证指标。",
        nav_summary="错误到数据补强",
    ),
    PageConfig(
        page_key="optimization_compare",
        title="优化验证",
        subtitle="观察 Prompt、RAG 或数据补强前后的关键指标变化。",
        question="本页用于判断 Prompt、RAG 或数据补强前后，关键指标是否出现可观察变化。",
        boundary="当前结果仅用于 MVP 样本观察，不代表真实大规模实验结论。",
        highlights="版本变更、平均分、依据可靠性、推理得分、幻觉率和红线错误率。",
        nav_summary="前后指标对比",
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
DEFAULT_PAGE_KEY = PAGE_CONFIGS[0].page_key


def get_page_config(page_key: str) -> PageConfig:
    return PAGE_CONFIG_BY_KEY.get(page_key, PAGE_CONFIG_BY_KEY[DEFAULT_PAGE_KEY])
