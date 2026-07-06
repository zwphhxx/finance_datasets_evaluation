from __future__ import annotations

import pandas as pd


# Display-name mappings: translate stored English field values to business
# Chinese labels. Unmapped values fall back to the raw value so new data is
# never dropped or hidden. These are presentation labels, not invented data.
DOMAIN_LABELS = {
    "Capital Markets": "投行场景",
    "Financial": "财务场景",
    "Legal": "法律场景",
    "finance": "财务场景",
    "financial": "财务场景",
    "legal": "法律场景",
    "ib": "投行场景",
    "investment_banking": "投行场景",
}
TASK_TYPE_LABELS = {
    "Financial Judgment": "财务专业判断",
    "Legal Judgment": "法律专业判断",
    "Investment Banking Judgment": "投行专业判断",
    "Regulatory Analysis": "监管合规分析",
    "Revenue Verification": "收入核查",
    "Inventory Assessment": "存货评估",
    "Legal Compliance": "法律合规审查",
    "Gross Margin Analysis": "毛利率分析",
    "Receivables Risk": "应收回款风险",
    "Cash Flow Analysis": "现金流分析",
    "Related Party Funds": "关联方资金核查",
    "Contract Review": "重大合同审阅",
    "Related Party Compliance": "关联交易合规",
    "Control Change Review": "控制权变更审查",
    "Performance Commitment": "业绩承诺与补偿",
    "IPO Inquiry Review": "IPO 问询回复评估",
    "M&A Analysis": "并购交易分析",
}
DIFFICULTY_LABELS = {"Hard": "高难度", "Medium": "中等难度", "Easy": "低难度"}
DIFFICULTY_BADGE = {"Hard": "high", "Medium": "medium", "Easy": "low"}
RISK_LABELS = {"高": "高风险", "中": "中风险", "低": "低风险"}
RISK_BADGE = {"高": "high", "中": "medium", "低": "low"}

SUMMARY_LIMIT = 140

TABLE_COLUMNS = [
    ("case_id", "案例编号", None),
    ("domain", "专业场景", DOMAIN_LABELS),
    ("task_type", "任务类型", TASK_TYPE_LABELS),
    ("difficulty", "难度", DIFFICULTY_LABELS),
    ("risk_level", "风险等级", RISK_LABELS),
    ("expected_capability", "考察能力", None),
    ("question", "任务摘要", None),
]


def clean_text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def display_label(value, mapping: dict[str, str]) -> str:
    text = clean_text(value)
    if text == "未标注":
        return text
    return mapping.get(text, text)


def summarize_text(value, limit: int = SUMMARY_LIMIT) -> str:
    text = clean_text(value, fallback="")
    if not text:
        return "暂无摘要"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_task_records(tasks_df: pd.DataFrame) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for row in tasks_df.to_dict(orient="records"):
        difficulty_raw = clean_text(row.get("difficulty"))
        risk_raw = clean_text(row.get("risk_level"))
        records.append(
            {
                "case_id": clean_text(row.get("case_id")),
                "domain_label": display_label(row.get("domain"), DOMAIN_LABELS),
                "task_type_label": display_label(row.get("task_type"), TASK_TYPE_LABELS),
                "difficulty_label": DIFFICULTY_LABELS.get(difficulty_raw, difficulty_raw),
                "difficulty_badge": DIFFICULTY_BADGE.get(difficulty_raw, "neutral"),
                "risk_label": RISK_LABELS.get(risk_raw, risk_raw),
                "risk_badge": RISK_BADGE.get(risk_raw, "neutral"),
                "capability": clean_text(row.get("expected_capability"), fallback="暂无记录"),
                "summary": summarize_text(row.get("question")),
                "question_full": clean_text(row.get("question"), fallback="暂无任务全文"),
                "context_full": clean_text(row.get("context"), fallback=""),
            }
        )
    return records


def build_task_table(tasks_df: pd.DataFrame) -> pd.DataFrame:
    table: dict[str, list[str]] = {}
    for source_column, display_name, mapping in TABLE_COLUMNS:
        if source_column not in tasks_df.columns:
            continue
        if mapping is not None:
            table[display_name] = [display_label(value, mapping) for value in tasks_df[source_column]]
        elif display_name == "任务摘要":
            table[display_name] = [summarize_text(value, limit=60) for value in tasks_df[source_column]]
        else:
            table[display_name] = [clean_text(value) for value in tasks_df[source_column]]
    return pd.DataFrame(table)
