from __future__ import annotations

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
RISK_LABELS = {"高": "高风险", "中": "中风险", "低": "低风险"}

SUMMARY_LIMIT = 140


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
