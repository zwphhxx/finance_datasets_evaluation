"""项目说明页：以项目 brief 说明定位、流程与数据边界。"""

from __future__ import annotations

from src.ui.components import (
    PROJECT_DISPLAY_NAME,
    render_brief_intro,
    render_home_section,
)

PROCESS_STEPS = ["人工录入样本库", "发起模型评测", "生成 AI 评分", "进入评测结论"]


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
        return "样本来自财务场景、法律场景和投行场景，不包含真实公司、真实交易或敏感数据。"
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


def render_case_study_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    base = data_bundle.get("base") or data

    render_brief_intro(
        title=PROJECT_DISPLAY_NAME,
        note=(
            "本项目评估大模型在财务、法律、投行等专业任务中的回答质量，"
            "并在当前样本范围内识别模型的主要问题和使用边界。"
        ),
    )

    render_home_section(
        number="01",
        title="项目定位",
        lead="评估模型在财务、法律、投行场景中的回答质量。",
        body=[
            "本项目围绕财务核查、法律合规、投行尽调等专业任务，评估大模型回答是否具备业务参考价值。评测重点不是通用问答能力，而是模型在具体专业场景中的结论准确性、依据充分性、推理完整性、风险识别和专业表达。",
            "当前样本库包含 13 条人工整理的专业任务样本及专业标准答案，覆盖财务场景、法律场景和投行场景。评测时，将不同模型的回答与专业标准答案、必须覆盖点、不可接受错误和评分标准进行对照，用于观察模型在当前样本范围内的质量差异。",
        ],
        first=True,
    )

    render_home_section(
        number="02",
        title="评测流程",
        lead="从专业样本到 AI 评分后的评测结论。",
        body=[
            "评测流程从人工整理的专业样本开始，到模型回答、AI 评分和评测结论形成闭环。",
            "样本库包括任务题、业务背景、专业标准答案、必须覆盖点、不可接受错误和评分标准。发起评测时，被测模型只看到任务题、业务背景和输出要求，不会看到专业标准答案或评分标准。模型生成回答后，AI 评分链路根据专业标准答案和评分标准生成维度分、评分依据和评分说明。",
            "评测结论只汇总成功 AI 评分，用于展示当前样本下不同模型的质量表现、主要问题和使用边界。",
        ],
        process_steps=PROCESS_STEPS,
    )

    render_home_section(
        number="03",
        title="数据边界",
        lead="结论只代表当前样本范围，不做脱离样本的泛化排名。",
        body=[
            _build_sample_scope_text(base) + "当前结论只反映成功 AI 评分覆盖的样本范围，不代表模型在全部财务、法律或投行业务中的稳定表现。",
            "被测模型不会看到专业标准答案、必须覆盖点、不可接受错误或评分标准。上述材料仅用于 AI 评分。",
            "评测结论由真实运行结果和 AI 评分共同形成。失败评分、演示数据或示例评价均不进入评测结论。",
        ],
    )
