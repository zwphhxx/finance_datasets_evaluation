from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.metrics import filter_tasks_by_domain, get_task_domains
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_empty_state,
    render_html,
    render_metric_card,
    render_page_shell,
    render_section_title,
)


# Display-name mappings: translate stored English field values to business
# Chinese labels. Unmapped values fall back to the raw value so new data is
# never dropped or hidden. These are presentation labels, not invented data.
DOMAIN_LABELS = {
    "Capital Markets": "资本市场",
    "Financial": "财务尽调",
    "Legal": "法律审核",
    "Medical": "医学评估",
}
TASK_TYPE_LABELS = {
    "Regulatory Analysis": "监管合规分析",
    "Revenue Verification": "收入核查",
    "Inventory Assessment": "存货评估",
    "Legal Compliance": "法律合规审查",
    "Clinical Analysis": "临床分析",
}
DIFFICULTY_LABELS = {"Hard": "高难度", "Medium": "中等难度", "Easy": "低难度"}
DIFFICULTY_BADGE = {"Hard": "high", "Medium": "medium", "Easy": "low"}
RISK_LABELS = {"高": "高风险", "中": "中风险", "低": "低风险"}
RISK_BADGE = {"高": "high", "中": "medium", "低": "low"}

SUMMARY_LIMIT = 140

# Compact auxiliary table, ordered for business reading with Chinese headers.
TABLE_COLUMNS = [
    ("case_id", "案例编号", None),
    ("domain", "领域", DOMAIN_LABELS),
    ("task_type", "任务类型", TASK_TYPE_LABELS),
    ("difficulty", "难度", DIFFICULTY_LABELS),
    ("risk_level", "风险等级", RISK_LABELS),
    ("expected_capability", "考察能力", None),
    ("question", "任务摘要", None),
]


def _clean_text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def display_label(value, mapping: dict[str, str]) -> str:
    text = _clean_text(value)
    if text == "未标注":
        return text
    return mapping.get(text, text)


def summarize_text(value, limit: int = SUMMARY_LIMIT) -> str:
    text = _clean_text(value, fallback="")
    if not text:
        return "暂无摘要"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_task_records(tasks_df: pd.DataFrame) -> list[dict[str, str]]:
    """Pure transform from raw task rows to business display fields."""
    records: list[dict[str, str]] = []
    for row in tasks_df.to_dict(orient="records"):
        difficulty_raw = _clean_text(row.get("difficulty"))
        risk_raw = _clean_text(row.get("risk_level"))
        records.append(
            {
                "case_id": _clean_text(row.get("case_id")),
                "domain_label": display_label(row.get("domain"), DOMAIN_LABELS),
                "task_type_label": display_label(row.get("task_type"), TASK_TYPE_LABELS),
                "difficulty_label": DIFFICULTY_LABELS.get(difficulty_raw, difficulty_raw),
                "difficulty_badge": DIFFICULTY_BADGE.get(difficulty_raw, "neutral"),
                "risk_label": RISK_LABELS.get(risk_raw, risk_raw),
                "risk_badge": RISK_BADGE.get(risk_raw, "neutral"),
                "capability": _clean_text(row.get("expected_capability"), fallback="暂无记录"),
                "summary": summarize_text(row.get("question")),
                "question_full": _clean_text(row.get("question"), fallback="暂无任务全文"),
                "context_full": _clean_text(row.get("context"), fallback=""),
            }
        )
    return records


def build_task_table(tasks_df: pd.DataFrame) -> pd.DataFrame:
    """Compact, business-ordered table with Chinese headers and labels."""
    table: dict[str, list[str]] = {}
    for source_column, display_name, mapping in TABLE_COLUMNS:
        if source_column not in tasks_df.columns:
            continue
        if mapping is not None:
            table[display_name] = [display_label(value, mapping) for value in tasks_df[source_column]]
        elif display_name == "任务摘要":
            table[display_name] = [summarize_text(value, limit=60) for value in tasks_df[source_column]]
        else:
            table[display_name] = [_clean_text(value) for value in tasks_df[source_column]]
    return pd.DataFrame(table)


def _render_task_card(record: dict[str, str]) -> None:
    render_html(
        f"""
        <div class="task-card">
            <div class="task-card-head">
                <span class="task-card-id">{escape(record["case_id"])}</span>
                <span class="task-card-badges">
                    <span class="status-badge status-{record["difficulty_badge"]}">{escape(record["difficulty_label"])}</span>
                    <span class="status-badge status-{record["risk_badge"]}">{escape(record["risk_label"])}</span>
                </span>
            </div>
            <div class="task-card-tags">
                <span class="tag tag-domain">{escape(record["domain_label"])}</span>
                <span class="tag tag-type">{escape(record["task_type_label"])}</span>
            </div>
            <div class="task-card-field">
                <div class="task-card-label">考察能力</div>
                <div class="task-card-value">{escape(record["capability"])}</div>
            </div>
            <div class="task-card-field">
                <div class="task-card-label">任务摘要</div>
                <div class="task-card-value">{escape(record["summary"])}</div>
            </div>
        </div>
        """
    )
    with st.expander("查看完整任务与背景信息"):
        st.markdown("**任务全文**")
        st.write(record["question_full"])
        if record["context_full"]:
            st.markdown("**背景材料**")
            st.write(record["context_full"])


def render_tasks_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    tasks_df = data.tasks
    render_page_shell(get_page_config("tasks"))
    if tasks_df.empty:
        render_empty_state("暂无可展示数据")
        return

    _render_task_coverage(data)

    render_section_title("任务样本", "本页用于展示样本覆盖和任务边界。")
    domains = get_task_domains(tasks_df)
    selected_domain = st.selectbox(
        "按领域筛选",
        domains,
        format_func=lambda value: "全部领域" if value == "全部" else display_label(value, DOMAIN_LABELS),
    )
    filtered_tasks = filter_tasks_by_domain(tasks_df, selected_domain)
    if filtered_tasks.empty:
        render_empty_state("暂无可展示数据")
        return

    for record in build_task_records(filtered_tasks):
        _render_task_card(record)

    _render_task_distribution(tasks_df)

    render_section_title("任务数据表", "面向业务阅读的字段顺序与命名。")
    st.dataframe(build_task_table(filtered_tasks), width="stretch", hide_index=True)


def _render_task_coverage(data) -> None:
    tasks_df = data.tasks
    task_ids = set(tasks_df["case_id"].dropna().astype(str)) if "case_id" in tasks_df else set()
    gold_ids = set(data.gold_answer_map.keys())
    output_case_ids = (
        set(data.model_outputs["case_id"].dropna().astype(str))
        if "case_id" in data.model_outputs
        else set()
    )

    render_section_title("样本覆盖")
    cols = st.columns(4)
    with cols[0]:
        render_metric_card("任务样本", len(tasks_df), "脱敏专业任务。")
    with cols[1]:
        render_metric_card("领域数", tasks_df["domain"].nunique() if "domain" in tasks_df else 0, "当前样本覆盖。")
    with cols[2]:
        render_metric_card("Gold Answer 覆盖", f"{len(task_ids & gold_ids)}/{len(task_ids)}", "标准答案覆盖。")
    with cols[3]:
        render_metric_card("模型回答覆盖", f"{len(task_ids & output_case_ids)}/{len(task_ids)}", "回答样本覆盖。")


def _render_task_distribution(tasks_df) -> None:
    render_section_title("领域分布")
    if "domain" not in tasks_df:
        render_empty_state("暂无可展示数据")
        return

    distribution = tasks_df["domain"].value_counts().reset_index()
    distribution.columns = ["domain", "count"]
    distribution["领域"] = distribution["domain"].map(lambda value: display_label(value, DOMAIN_LABELS))
    distribution = distribution.rename(columns={"count": "任务数"})
    st.bar_chart(distribution, x="领域", y="任务数")
