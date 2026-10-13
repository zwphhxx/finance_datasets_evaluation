"""项目说明页：作为评测结论的方法附录。"""

from __future__ import annotations

from html import escape

from app.services import dataset_service as ds
from src.ui.components import PROJECT_DISPLAY_NAME, render_html
from src.ui.report_components import (
    render_report_masthead,
    render_scope_ledger,
    report_section_html,
)

BRIEF_NOTE = (
    "本项目评估大模型在财务、法律、投行等专业任务中的回答质量，"
    "并在当前样本范围内识别模型的主要问题和使用边界。"
)
DEFAULT_SAMPLE_SCOPE_TEXT = (
    "样本来自财务场景、法律场景和投行场景，"
    "不包含真实公司、真实交易或敏感数据。"
)
_SAMPLE_SCOPE_TOKEN = "{sample_scope}"

CASE_STUDY_SECTIONS = (
    {
        "number": "01",
        "anchor": "fde-project-positioning",
        "title": "项目定位",
        "lead": "评估模型在财务、法律、投行场景中的回答质量。",
        "body": (
            "本项目围绕财务核查、法律合规、投行尽调等专业任务，评估大模型回答是否具备业务参考价值。评测重点不是通用问答能力，而是模型在具体专业场景中的结论准确性、依据充分性、推理完整性、风险识别和专业表达。",
            "当前样本库包含 13 条人工整理的专业任务样本及专业标准答案，覆盖财务场景、法律场景和投行场景。评测时，将不同模型的回答与专业标准答案、必须覆盖点、不可接受错误和评分标准进行对照，用于观察模型在当前样本范围内的质量差异。",
        ),
    },
    {
        "number": "02",
        "anchor": "fde-evaluation-method",
        "title": "评测流程",
        "lead": "从专业样本到 AI 评分后的评测结论。",
        "body": (
            "评测流程从人工整理的专业样本开始，到模型回答、AI 评分和评测结论形成闭环。",
            "样本库包括任务题、业务背景、专业标准答案、必须覆盖点、不可接受错误和评分标准。发起评测时，被测模型只看到任务题、业务背景和输出要求，不会看到专业标准答案或评分标准。模型生成回答后，AI 评分链路根据专业标准答案和评分标准生成维度分、评分依据和评分说明。",
            "评测结论只汇总成功 AI 评分，用于展示当前样本下不同模型的质量表现、主要问题和使用边界。",
        ),
    },
    {
        "number": "03",
        "anchor": "fde-data-boundary",
        "title": "数据边界",
        "lead": "结论只代表当前样本范围，不做脱离样本的泛化排名。",
        "body": (
            _SAMPLE_SCOPE_TOKEN + "当前结论只反映成功 AI 评分覆盖的样本范围，不代表模型在全部财务、法律或投行业务中的稳定表现。",
            "被测模型不会看到专业标准答案、必须覆盖点、不可接受错误或评分标准。上述材料仅用于 AI 评分。",
            "评测结论由真实运行结果和 AI 评分共同形成。失败评分、演示数据或示例评价均不进入评测结论。",
        ),
    },
)

PROCESS_STEPS = ["人工录入样本库", "开始评测", "模型回答与 AI 评分", "进入评测结论"]


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
    paragraphs = "".join(
        "<p>" + escape(str(paragraph).replace(_SAMPLE_SCOPE_TOKEN, scope).replace("当前样本库包含 13 条", f"当前样本库包含 {sample_count} 条")) + "</p>"
        for paragraph in section["body"]
    )
    lead = f'<p class="report-method-lead">{escape(str(section["lead"]))}</p>'
    if section["number"] == "02":
        paragraphs += _process_steps_html(PROCESS_STEPS)
    return f'<div class="report-method-copy">{lead}{paragraphs}</div>'


def render_case_study_page(data_bundle: dict) -> None:
    import streamlit as st

    from src.ui.history_view import render_comparison_and_runtime, render_history_controls
    from src.ui.labels import DOMAIN_LABELS, display_label
    from src.ui.trust_details import render_score_detail
    from src.ui.workbench import has_multiple_endpoints, historical_dimensions, load_workbench_source, overview_facts

    base = data_bundle.get("base") or data_bundle["data"]
    render_report_masthead(PROJECT_DISPLAY_NAME, BRIEF_NOTE, "评测概览")
    source = load_workbench_source(base)
    report = source.report
    facts = overview_facts(base, report)
    render_scope_ledger([("评测样本", str(facts["samples"])), ("专业领域", str(facts["domains"])),
                         ("已评测模型", str(facts["models"]) if source.available else "—"), ("有效评分", str(facts["scores"]) if source.available else "—")])
    tasks = getattr(base, "tasks", None)
    if tasks is not None and "domain" in tasks:
        st.caption("覆盖领域：" + "、".join(display_label(d, DOMAIN_LABELS) for d in tasks["domain"].dropna().unique()))
    readonly = bool(st.session_state.get("readonly_evaluation_snapshot"))
    st.caption("最新实际测试时间：" + str(facts["latest"] or ("暂无实际测试记录" if source.available else "当前不可读取")) + " ｜ 结果来源：" + ("只读历史快照（来源声明未经独立认证）" if readonly else "持久化评测运行数据（当前数据库）"))
    if not source.available:
        st.warning(source.message)
        st.caption("数据库不可读取时不将未知结果数量视为零；上方模型与评分数仅表示当前可读取结果。")

    st.subheader("主要发现与模型比较")
    if report and report.model_summaries:
        st.caption("当前兼容批次；自动评分仅代表样本内观察，需要结合下方原始证据复核。")
        for summary in report.model_summaries:
            if not has_multiple_endpoints(report):
                issues = summary.get("main_issues") or []
                st.text(str(summary.get("display_name") or summary.get("model_name")) + "：" + ("；".join(str(i) for i in issues) if issues else "当前评分未形成稳定的问题归纳。"))
        st.caption("上述为自动评分记录的归纳；未保存结构化引文的历史记录仍需核对原始证据，不能作为已验证专业结论。")
        render_comparison_and_runtime(report)
    elif source.available:
        st.info("尚无正式实测结果。当前展示评测方法与专业样本，不生成示例评分或模型排名。")
        st.caption("可在评测结论中只读加载真实完整快照，或配置模型服务后发起评测。浏览页面不会产生模型调用费用。")

    if not source.available:
        st.info("评测结果当前不可读取，暂不能形成主要发现或模型比较。")

    st.subheader("专业任务与评分证据")
    items = [item for entries in (report.evidence_by_model.values() if report else []) for item in entries]
    if items:
        # Prefer an actual error record; this is an inspectable example, not a ranking.
        item = next((i for i in items if '"not_met"' in str(i.score_record.get("checks_json", ""))), items[0])
        st.caption(f"{item.case_id} · {item.model_name} · {item.run_id} ｜ 示例选择：优先展示包含未满足要点的真实记录。")
        render_score_detail(task=item.task, answer=item.answer_text, score=item.score_record,
                            dimensions=historical_dimensions(report), key="overview")
    else:
        if tasks is not None and not tasks.empty:
            task = tasks.iloc[0].to_dict()
            st.caption(f"样本预览 · {task.get('case_id', '—')} · 尚无真实模型回答与评分")
            with st.container(border=True, key="overview_task"):
                st.text(str(task.get("task") or task.get("question") or "任务正文未提供"))
                for field in ("business_background", "context", "material", "output_requirements"):
                    if task.get(field):
                        st.text(str(task[field]))
        st.caption("真实评测完成后，此处展示模型回答、评分依据及已记录错误；当前不补造评价内容。")

    st.subheader("评测方法与研究边界")
    st.text("任务 → 模型回答 → 专业标准与要点核查 → 维度评分 → 原始证据复核")
    st.caption(_build_sample_scope_text(base))
    st.text("人工样本数量有限；自动裁判可能存在判断偏差；仅在相同版本、共同有效任务范围内观察差异，不外推整体能力。引文匹配只能证明引用存在，不能代替专业判断。")
    with st.expander("查看完整评测方法与数据范围"):
        for section in CASE_STUDY_SECTIONS:
            render_html(report_section_html(str(section["number"]), "", str(section["title"]),
                                           _section_body_html(section, base), anchor_id=str(section["anchor"])))
    st.markdown("[GitHub 源码与复现说明](https://github.com/zwphhxx/finance_datasets_evaluation)")
    render_history_controls()
