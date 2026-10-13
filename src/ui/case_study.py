"""项目说明页：作为评测结论的方法附录。"""

from __future__ import annotations

from html import escape

from app.services import dataset_service as ds
from src.ui.components import render_html
from src.ui.report_components import (
    render_report_masthead,
    report_section_html,
)

BRIEF_NOTE = "样本怎样建立、模型怎样评价，以及结果的使用边界。"
DEFAULT_SAMPLE_SCOPE_TEXT = "样本来自财务场景、法律场景和投行场景，不包含真实公司、真实交易或敏感数据。"
_SAMPLE_SCOPE_TOKEN = "{sample_scope}"

CASE_STUDY_SECTIONS = (
    {
        "number": "01", "anchor": "fde-project-positioning", "title": "专业样本设计", "lead": "",
        "body": (
            "项目结合财务、法律及投行业务经验，将典型任务整理为结构化专业样本，设置参考判断、关键评价要点和不可接受错误，用于检查具体场景中的回答质量。",
            "当前样本库包含 13 条专业任务。" + _SAMPLE_SCOPE_TOKEN,
        ),
    },
    {
        "number": "02", "anchor": "fde-evaluation-method", "title": "模型评测流程", "lead": "",
        "body": (
            "被测模型只看到任务题、业务背景和输出要求。评分模型结合模型回答、专业标准答案和评分标准，形成各维度评分及评分说明。被测模型不会看到专业标准答案、必须覆盖点、不可接受错误或评分标准。",
        ),
    },
    {
        "number": "03", "anchor": "fde-data-boundary", "title": "方法局限", "lead": "",
        "body": (
            "专业样本数量有限，AI自动评分可能存在判断偏差。结果仅用于观察当前样本范围和特定测试条件下的模型表现，不代表模型整体能力，也不构成商业采购建议。",
            "比较使用兼容版本的共同有效任务；失败评分、演示数据或示例评价均不进入评测结论。历史材料与证据缺失会明确提示，引文匹配仅核对原文是否存在，不能代替专业判断。",
        ),
    },
)

PROCESS_STEPS = ["专业任务", "模型回答", "AI评分", "结果分析"]


def professional_copy_snapshot() -> str:
    """返回受 fixture 保护的方法正文，不包含可调整的界面流程标签。"""
    lines = [BRIEF_NOTE]
    for section in CASE_STUDY_SECTIONS:
        lines.extend((str(section["title"]), str(section["lead"])))
        lines.extend(
            str(paragraph).replace(_SAMPLE_SCOPE_TOKEN, DEFAULT_SAMPLE_SCOPE_TEXT)
            for paragraph in section["body"]
        )
    return "\n".join(lines) + "\n"


def build_home_facts(base) -> list[tuple[str, str]]:
    """Build cover facts from the active dataset and scoring dimensions."""

    tasks = getattr(base, "tasks", None)
    sample_count = 0 if tasks is None else len(tasks)
    domain_count = (
        0
        if tasks is None or "domain" not in getattr(tasks, "columns", [])
        else int(tasks["domain"].dropna().nunique())
    )
    score_total = sum(
        int(dimension.get("full_mark") or 0)
        for dimension in ds.get_rubric_dimensions()
    )
    return [
        ("当前样本", str(sample_count)),
        ("覆盖领域", str(domain_count)),
        ("评分总分", str(score_total)),
    ]


def scored_case_count(scores_df) -> int:
    """当前样本中已产出评分的条数（运行真实评测后才大于 0），从 scores 动态计算。"""
    if scores_df is None or getattr(scores_df, "empty", True):
        return 0
    if "total_score" not in getattr(scores_df, "columns", []):
        return 0
    return int(scores_df["total_score"].notna().sum())


def _build_sample_scope_text(data) -> str:
    """Describe sample scope as plain text instead of homepage tags."""
    from src.ui.labels import DOMAIN_LABELS, display_label

    tasks = getattr(data, "tasks", None)
    if tasks is None or tasks.empty or "domain" not in tasks.columns:
        return DEFAULT_SAMPLE_SCOPE_TEXT
    domains = [
        display_label(domain, DOMAIN_LABELS)
        for domain in tasks["domain"].dropna().astype(str).unique()
    ]
    domains = [domain for domain in domains if domain and domain != "未标注"]
    if domains:
        shown = domains[:4]
        if len(domains) > len(shown):
            domain_text = "、".join(shown) + "等"
        elif len(shown) > 1:
            domain_text = "、".join(shown[:-1]) + "和" + shown[-1]
        else:
            domain_text = shown[0]
    else:
        domain_text = "财务场景、法律场景和投行场景"
    return f"样本来自{domain_text}，不包含真实公司、真实交易或敏感数据。"


def _process_steps_html(steps: list[str]) -> str:
    items = "".join(f"<li>{escape(str(step))}</li>" for step in steps)
    return f'<ol class="report-method-process">{items}</ol>'


def _section_body_html(section: dict, base) -> str:
    scope = _build_sample_scope_text(base)
    sample_count = len(getattr(base, "tasks", ())) if getattr(base, "tasks", ()) is not None else 0
    body = section["body"]
    paragraphs = "".join(
        "<p>" + escape(str(paragraph).replace(_SAMPLE_SCOPE_TOKEN, scope).replace("当前样本库包含 13 条", f"当前样本库包含 {sample_count} 条")) + "</p>"
        for paragraph in body
    )
    if section["number"] == "02":
        paragraphs += _process_steps_html(PROCESS_STEPS)
    return f'<div class="report-method-copy">{paragraphs}</div>'


def render_case_study_page(data_bundle: dict) -> None:
    import streamlit as st

    base = data_bundle.get("base") or data_bundle["data"]
    render_report_masthead("评测方法", BRIEF_NOTE)
    for section in CASE_STUDY_SECTIONS:
        render_html(report_section_html("", "", str(section["title"]),
                                       _section_body_html(section, base), anchor_id=str(section["anchor"])))
    st.caption("当前题库与历史运行分别保留；案例中的参考标准以历史记录为准。")
    st.markdown("[GitHub 源码与进一步阅读](https://github.com/zwphhxx/finance_datasets_evaluation)")
