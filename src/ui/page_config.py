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
        title="红线评测台",
        subtitle="面向投行 / 财务 / 法律尽调任务，判断模型回答哪些可直接用、哪些必须复核、哪些不可直接用。",
        question="本页用于一屏判断当前样本下，模型回答的可用边界、本轮最大风险与数据补强方向。",
        boundary="题库与 Gold 为 MVP 脱敏样本；可用边界与风险均为当前样本内观察，红线错误一票否决。",
        highlights="三类使用边界、本轮最大风险与评测闭环入口。",
        nav_summary="红线评测台",
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
        page_key="eval_run",
        title="发起评测",
        subtitle="选择模型与任务，运行真实评测并由裁判模型自动评分。",
        question="本页用于运行一次真实模型评测并获取裁判建议分。",
        boundary="模型回答仅用于评测，评分为裁判模型建议分，需人工复核确认后归档。",
        highlights="选 Provider / 模型 / 任务、运行生成、裁判评分、人工复核与下一步引导。",
        nav_summary="运行真实评测",
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
        title="模型能力指纹",
        subtitle="为每个模型生成一张能力指纹卡，呈现在当前样本中的强项、短板、红线风险与适用边界。",
        question="本页用于判断当前样本下各模型的强项、短板与红线风险分别集中在哪里。",
        boundary="本页不作为模型整体能力结论，也不提供绝对排名、采购建议或性价比判断。",
        highlights="模型能力指纹卡、横向对比、维度达成矩阵、错误类型分布与领域场景表现。",
        nav_summary="能力指纹与短板",
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
