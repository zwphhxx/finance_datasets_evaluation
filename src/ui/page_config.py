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
        page_key="project_methodology",
        title="项目介绍",
        subtitle="说明这套尽调评测的目的、样本来源、评价框架与使用方式。",
        question="本页用于说明项目要解决什么问题、样本从哪来、怎么评、以及如何使用评测结果。",
        boundary="样本为脱敏抽象编写，不含真实公司与敏感数据；本项目是尽调可用边界评测，不是模型排行榜。",
        highlights="项目背景、样本来源与结构、评价框架、红线机制与使用方式。",
        nav_summary="项目介绍与方法论",
    ),
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
        title="样本库",
        subtitle="按筛选浏览任务内容、Gold Answer 状态与模型回答覆盖。",
        question="本页用于看清数据集里有哪些任务，以及每道任务的质量与覆盖状态。",
        boundary="当前任务是脱敏专业任务样本，不是概念题，也不是完整行业题库。",
        highlights="轻量筛选、紧凑任务表、Gold Answer 状态与选中任务详情。",
        nav_summary="任务内容与覆盖",
    ),
    PageConfig(
        page_key="eval_run",
        title="可复现实验",
        subtitle="现场可复现实验：选活跃任务调用模型生成回答，对照 Gold/Rubric 打建议分；现场结果受 API、网络、模型版本影响，离线评测结论才是默认展示依据。",
        question="本页用于现场复现一次模型调用并获取裁判建议分，便于核对而非作为正式结论。",
        boundary="现场运行结果默认进入草稿（待复核），不覆盖离线样本评价；经人工复核确认后才计入正式结论。",
        highlights="连通性检查、默认单任务、逐条进度、调用元信息（HTTP/耗时/错误码/trace_id）、裁判评分与人工复核。",
        nav_summary="可复现实验",
    ),
    PageConfig(
        page_key="case_detail",
        title="典型样本拆解",
        subtitle="用一道真实尽调题，拆解任务考察点、Gold 锚点、模型回答差异、评分依据与红线。",
        question="本页用于说明这道题为什么能测出模型能力，以及各模型回答具体差在哪里。",
        boundary="单题拆解只服务于样本内观察，不代表模型整体能力。",
        highlights="任务背景、Gold Answer、多模型回答对比、多维度评分、人工点评与红线提示。",
        nav_summary="典型样本拆解",
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
        page_key="evaluation_conclusions",
        title="评测结论",
        subtitle="汇总已有结论、现场草稿与已复核归档，区分哪些已计入正式结论。",
        question="本页用于查看当前样本内的正式评测结论，并把现场新增评测经人工复核后归档计入。",
        boundary="正式结论只含 seed 已有结论与已复核归档结论；现场草稿未计入；这是样本内可用边界观察，不是模型排行榜。",
        highlights="正式结论多维度汇总、人工点评摘要、高频问题归纳、草稿待复核与复核归档流程。",
        nav_summary="正式结论与复核归档",
    ),
    PageConfig(
        page_key="dataset_quality",
        title="数据集质量",
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
