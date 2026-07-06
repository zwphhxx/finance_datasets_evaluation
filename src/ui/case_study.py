"""项目说明页：以项目 brief 说明定位、流程与数据边界。"""

from __future__ import annotations

import streamlit as st

from src.metrics import SCORE_DIMENSIONS
from src.ui.components import (
    PROJECT_DISPLAY_NAME,
    render_brief_intro,
    render_clean_list,
    render_numbered_section,
    render_process_line,
)


PROCESS_STEPS = ["样本库", "发起评测", "评分确认", "评测结论"]
PROCESS_TEXT = "样本库 ── 发起评测 ── 评分确认 ── 评测结论"


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
            "用脱敏专业任务样本，对比模型在财务、法律、投行场景下的回答质量、"
            "评分依据和使用边界。"
        ),
        stats=_build_home_stats(base, eval_status),
        process_text=PROCESS_TEXT,
    )

    render_numbered_section("01", "项目定位")
    st.markdown(
        "本项目用于评估大模型在专业场景中的回答是否具备参考价值。评测对象不是通用问答能力，"
        "而是财务尽调、法律审阅、投行判断等高风险任务中的结论准确性、推理完整性、风险覆盖、"
        "依据可靠性和专业表达。"
    )
    st.markdown(
        "本项目不判断哪个模型最好，而是在当前专业样本内观察模型回答是否可参考、需复核或不应采用。"
        "模型回答只作为评分输入，正式结论必须经过人工确认后才生效。"
    )

    render_numbered_section("02", "评测流程")
    render_process_line(PROCESS_STEPS)
    render_clean_list([
        "样本库：维护任务题、业务背景、Gold Answer 和 Rubric。",
        "发起评测：选择样本和模型，生成模型回答和评分草稿。",
        "评分确认：人工确认、修订或暂不采用评分草稿。",
        "评测结论：仅汇总已确认评分，形成当前样本内观察。",
    ])

    render_numbered_section("03", "数据边界")
    st.markdown(_build_sample_scope_text(base))
    st.markdown(
        "当前结论只代表已确认评分覆盖的样本范围，不代表模型在全部财务、法律或投行业务中的稳定表现。"
    )
    st.markdown(
        "被测模型不会看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric；这些材料只用于裁判评分和人工复核。"
    )
    st.markdown(
        "正式结论 = 真实运行结果 + 裁判评分草稿 + 人工确认。待确认、暂不采用、评分失败和示例评价均不进入正式结论。"
    )
    st.markdown("**评分依据**")
    eval_items = []
    for key, label in SCORE_DIMENSIONS:
        note = {
            "accuracy_score": "结论与事实、法规、财务口径是否准确",
            "reasoning_score": "推理是否完整、贴合具体业务场景",
            "coverage_score": "关键风险是否覆盖到位",
            "evidence_score": "结论是否给出可核查的依据",
            "expression_score": "表达是否专业克制、结构清楚",
        }.get(key, "")
        eval_items.append(f"{label}：{note}")
    render_clean_list(eval_items)
    st.caption("高分只能作为初稿参考，红线错误仍需人工判断。")
