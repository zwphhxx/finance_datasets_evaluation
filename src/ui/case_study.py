"""项目说明页：以项目 brief 说明定位、流程与数据边界。"""

from __future__ import annotations

from src.metrics import SCORE_DIMENSIONS
from src.ui.components import (
    PROJECT_DISPLAY_NAME,
    render_brief_intro,
    render_home_section,
    render_process_line,
)


PROCESS_STEPS = ["样本库", "发起评测", "评分草稿", "人工确认", "评测结论"]
PROCESS_TEXT = "样本库 → 发起评测 → 评分草稿 → 人工确认 → 评测结论"


def _distinct_count(df, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def scored_case_count(scores_df) -> int:
    """当前样本中已产出评分的条数（运行真实评测后才大于 0），从 scores 动态计算。"""
    if scores_df is None or getattr(scores_df, "empty", True):
        return 0
    if "total_score" not in getattr(scores_df, "columns", []):
        return 0
    return int(scores_df["total_score"].notna().sum())


def _build_home_stats(base, eval_status: dict | None) -> list[tuple[str, str]]:
    tasks = getattr(base, "tasks", None)
    task_count = len(tasks) if tasks is not None else 0
    domain_count = _distinct_count(tasks, "domain")
    return [
        (f"{task_count} 个", "当前样本"),
        (f"{domain_count} 类", "覆盖领域"),
        (f"{len(SCORE_DIMENSIONS)} 个", "Rubric 维度"),
    ]


def _build_sample_scope_text(data) -> str:
    """Describe sample scope as plain text instead of homepage tags."""
    from src.ui.labels import DOMAIN_LABELS, display_label
    tasks = getattr(data, "tasks", None)
    if tasks is None or tasks.empty or "domain" not in tasks.columns:
        return "样本来自金融尽调场景，已脱敏抽象为可评测任务；不包含真实公司、交易或敏感数据。"
    domains = [
        display_label(domain, DOMAIN_LABELS)
        for domain in tasks["domain"].dropna().astype(str).unique()
    ]
    domains = [domain for domain in domains if domain and domain != "未标注"]
    if domains:
        shown = domains[:4]
        suffix = "等" if len(domains) > len(shown) else ""
        domain_text = "、".join(shown) + suffix
    else:
        domain_text = "金融尽调"
    return f"样本来自{domain_text}场景，已脱敏抽象为可评测任务；不包含真实公司、交易或敏感数据。"


def render_case_study_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    base = data_bundle.get("base") or data
    eval_status = data_bundle.get("eval_status") or {}

    render_brief_intro(
        title=PROJECT_DISPLAY_NAME,
        subtitle=(
            "用脱敏专业任务样本，对比模型回答在结论准确性、依据充分性、推理完整性、"
            "风险识别和专业表达上的表现。"
        ),
        note=(
            "本项目评估大模型在财务、法律、投行等专业场景中的回答质量，"
            "并在当前样本范围内判断模型表现、主要问题和使用边界。"
        ),
        stats=_build_home_stats(base, eval_status),
        process_text=PROCESS_TEXT,
    )

    render_home_section(
        number="01",
        title="项目定位",
        lead="评估模型在财务、法律、投行场景中的回答质量。",
        body=[
            "本项目面向财务尽调、法律审阅、投行判断等专业任务，评估大模型回答是否具备业务参考价值。评测重点不是通用问答能力，而是模型在具体专业场景中的结论准确性、依据充分性、推理完整性、风险识别和专业表达。",
            "评测结果用于观察不同模型在当前样本范围内的质量差异，并进一步判断其可作为初稿参考、需要人工复核，还是不宜作为专业判断依据。",
        ],
    )

    render_home_section(
        number="02",
        title="评测流程",
        lead="从专业样本到人工确认，形成可追溯的评分闭环。",
        body=[
            "样本库维护任务题、业务背景、Gold Answer、必须覆盖点、不可接受错误和 Rubric。发起评测时，被测模型只基于任务题和必要背景生成回答，裁判模型再基于 Gold Answer 和 Rubric 形成评分草稿。",
            "评分草稿不会直接进入正式结论。所有评分需要经过人工确认、修订后确认或暂不采用。评测结论仅汇总已确认评分，用于展示当前样本下不同模型的质量表现、主要问题和使用边界。",
        ],
    )
    render_process_line(PROCESS_STEPS)

    render_home_section(
        number="03",
        title="数据边界",
        lead="结论只代表当前已确认样本，不做脱离样本的泛化排名。",
        body=[
            _build_sample_scope_text(base),
            "当前结论是当前样本内观察，只反映已确认评分覆盖的样本范围，不代表模型在全部财务、法律或投行业务中的稳定表现。",
            "被测模型不会看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric。上述材料仅用于裁判评分和人工复核。",
            "正式结论由真实运行结果、裁判评分草稿和人工确认共同形成。待确认、暂不采用、评分失败或示例评价均不进入正式结论。",
        ],
    )
