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
        title="FinDueEval 数据集概览",
        subtitle="一屏看清数据集内容、样本边界与模型评测的样本内观察。",
        question="本页用于快速判断数据集里有什么、样本与评测边界是什么、当前样本内模型表现如何。",
        boundary="当前为 MVP 样本、脱敏任务与模拟模型回答，结论仅用于样本内观察。",
        highlights="核心指标、任务覆盖、模型表现摘要与样板题评测入口。",
        nav_summary="数据集与模型边界",
    ),
    PageConfig(
        page_key="tasks",
        title="任务样本",
        subtitle="按筛选浏览任务内容、Gold Answer 状态与模型回答覆盖。",
        question="本页用于看清数据集里有哪些任务，以及每道任务的质量与覆盖状态。",
        boundary="当前任务是脱敏专业任务样本，不是概念题，也不是完整行业题库。",
        highlights="轻量筛选、紧凑任务表、Gold Answer 状态与选中任务详情。",
        nav_summary="任务内容与覆盖",
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
        page_key="model_boundary",
        title="模型边界报告",
        subtitle="把评分与错误标签归纳为可直接使用、需人工复核与不可直接使用的边界。",
        question="本页用于判断当前样本下，模型在金融专业任务中哪些可用、哪些必须人工复核、哪些不可直接采用。",
        boundary="边界结论来自当前评分、错误标签与 Gold Answer 红线，仅用于样本内观察，不代表模型整体能力或采购建议。",
        highlights="数据边界、三类使用边界、高频风险、数据补强方向和模型维度矩阵。",
        nav_summary="可用边界与风险",
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
    PageConfig(
        page_key="dataset_quality",
        title="数据集质量与扩展框架",
        subtitle="说明数据集的质量门槛、任务覆盖、答案边界与可扩展接入方式。",
        question="本页用于判断当前数据集是否具备可扩展、可质检、可复用的基础。",
        boundary="当前为 MVP 样本规模，覆盖矩阵用于展示结构而非完整生产数据集。",
        highlights="数据集概览、覆盖矩阵、Gold Answer 质检、Rubric 质检、错误标签覆盖和扩展说明。",
        nav_summary="质量门槛与扩展接入",
    ),
    PageConfig(
        page_key="dataset_admin",
        title="数据集管理",
        subtitle="维护任务题、Gold Answer 与 Rubric，写入 SQLite 运行时数据层。",
        question="本页用于新增、编辑、停用任务题，编辑 Gold Answer，查看与维护评分维度。",
        boundary="CRUD 仅写入 SQLite；CSV/JSON/YAML 仍为初始化 seed 与可审阅数据资产，删除统一为停用。",
        highlights="任务题增改停与详情、Gold Answer 要素编辑、评分维度权重与扣分规则维护。",
        nav_summary="数据集维护与 CRUD",
    ),
    PageConfig(
        page_key="live_eval",
        title="真实模型评测",
        subtitle="从数据集选择任务与硅基流动模型，生成真实模型回答并查看运行状态。",
        question="本页用于选择任务与模型，运行一次真实（或 mock）模型生成，查看回答与运行状态。",
        boundary="本页只负责运行与展示，不做评分、不做模型排名；未配置 API Key 时自动使用 mock 模式。",
        highlights="数据集版本、任务范围、Provider 与模型选择、生成参数、运行结果表与模型回答查看。",
        nav_summary="真实模型运行",
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
