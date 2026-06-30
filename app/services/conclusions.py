"""评测结论汇总服务（PR-B）。

把三类来源的评测结果归一为「正式结论 / 草稿 / 已复核归档」三层，供「评测结论」页取数：

  - 已有结论（seed）：seed 的 model_outputs / score_records / review_note，视为已人工沉淀的基准；
  - 草稿评测（draft）：live_run_scores 中 review_status != confirmed 的现场评分，未进入正式结论；
  - 已复核归档（confirmed）：live_run_scores 中 review_status == confirmed 的评分，可计入正式结论。

正式结论 = seed 已有结论 + 已复核归档 live 结论，**绝不包含 pending 草稿**。

本模块为纯函数 + 只读数据库访问，不依赖 Streamlit 渲染上下文，便于单元测试；任何数据库
异常都吞掉并回退为空，保证 SQLite 不可用时仍可只用 seed 数据展示。绝不回写 data/ 下 seed 文件。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from src.metrics import SCORE_DIMENSIONS, get_dimension_gap_ranking

# Rubric 维度字段与中文标签，统一取自 metrics（不在此另立第二份口径）。
DIMENSION_FIELDS: list[str] = [field for field, _ in SCORE_DIMENSIONS]
DIMENSION_LABELS: dict[str, str] = dict(SCORE_DIMENSIONS)

# 归一后的正式打分表列（seed 与 live 都投影到这里）。
_FORMAL_COLUMNS = ["model_name", "case_id", *DIMENSION_FIELDS, "total_score", "review_note", "source"]

# 模型展示名映射：键为原始 model_name，值为对外展示名。默认空——没有映射时一律使用原名，
# 不在代码里硬编码任何具体模型/策略名称。
MODEL_DISPLAY_NAMES: dict[str, str] = {}


def display_model_name(name: Any, mapping: Mapping[str, str] | None = None) -> str:
    """返回模型展示名：命中映射用映射值，否则用原名；空值回退到占位串。"""
    table = MODEL_DISPLAY_NAMES if mapping is None else mapping
    key = "" if name is None else str(name).strip()
    if not key or key.lower() in {"nan", "none", "null"}:
        return "未标注模型"
    return str(table.get(key, key))


# --------------------------------------------------------------------------- #
# 只读数据库访问（SQLite 不可用时一律回退空表）
# --------------------------------------------------------------------------- #
def load_live_scores(db_path=None) -> pd.DataFrame:
    """读取全部 live_run_scores 行；数据库不可用或异常时返回空 DataFrame。"""
    return _load_live_table("live_run_scores", db_path)


def load_live_responses(db_path=None) -> pd.DataFrame:
    """读取全部 live_run_responses 行（含模型回答），用于草稿区拼接回答。"""
    return _load_live_table("live_run_responses", db_path)


def _load_live_table(table: str, db_path) -> pd.DataFrame:
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return pd.DataFrame()
        frame = Repository(path).list_df(table, order_by="id")
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def split_live_scores(live_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """把 live 评分拆为 (已复核 confirmed, 草稿 pending)，均限定 judge_status=success、未停用。

    只有评分成功且人工确认（review_status=confirmed）的行进入 confirmed；其余成功行为草稿。
    失败 / mock 评分既不进正式结论也不进草稿（无可复核分数）。
    """
    empty = pd.DataFrame()
    if not isinstance(live_df, pd.DataFrame) or live_df.empty:
        return empty, empty

    df = live_df
    if "judge_status" in df.columns:
        df = df[df["judge_status"].astype(str) == "success"]
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.strip().str.lower() != "inactive"]
    if df.empty:
        return empty, empty

    if "review_status" in df.columns:
        status = df["review_status"].astype(str).str.strip().str.lower()
    else:
        status = pd.Series(["pending"] * len(df), index=df.index)
    confirmed = df[status == "confirmed"].reset_index(drop=True)
    pending = df[status != "confirmed"].reset_index(drop=True)
    return confirmed, pending


def _normalize_live_scores(live_df: pd.DataFrame) -> pd.DataFrame:
    """把 live_run_scores 行投影为正式打分表列（eval_model → model_name）。"""
    if not isinstance(live_df, pd.DataFrame) or live_df.empty:
        return pd.DataFrame(columns=_FORMAL_COLUMNS)
    out = pd.DataFrame()
    out["model_name"] = live_df.get("eval_model")
    out["case_id"] = live_df.get("case_id")
    for field in DIMENSION_FIELDS:
        out[field] = pd.to_numeric(live_df[field], errors="coerce") if field in live_df.columns else None
    out["total_score"] = (
        pd.to_numeric(live_df["total_score"], errors="coerce") if "total_score" in live_df.columns else None
    )
    out["review_note"] = live_df.get("review_note")
    out["source"] = "confirmed_live"
    return out


def combine_formal_scores(seed_scores: pd.DataFrame, confirmed_live: pd.DataFrame) -> pd.DataFrame:
    """合并 seed 已有结论与已复核归档 live 结论为统一打分表（带 source 列）。

    只接受已复核 live；pending 草稿不在此出现，从源头保证不计入正式结论。
    """
    frames: list[pd.DataFrame] = []
    if isinstance(seed_scores, pd.DataFrame) and not seed_scores.empty and "total_score" in seed_scores.columns:
        seed = seed_scores.copy()
        seed["source"] = "seed"
        frames.append(seed)
    normalized = _normalize_live_scores(confirmed_live)
    if not normalized.empty:
        frames.append(normalized)
    if not frames:
        return pd.DataFrame(columns=_FORMAL_COLUMNS)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "total_score" in combined.columns:
        combined = combined[combined["total_score"].notna()].reset_index(drop=True)
    return combined


def build_formal_conclusions(
    seed_scores: pd.DataFrame,
    confirmed_live: pd.DataFrame,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """按模型聚合正式结论：平均总分、各 Rubric 维度均分、人工点评摘要与来源构成。

    不包含 pending 草稿。无可用数据时返回空列表。
    """
    combined = combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "model_name" not in combined.columns:
        return []

    results: list[dict[str, Any]] = []
    for model_name, group in combined.groupby("model_name"):
        dimensions: dict[str, float | None] = {}
        for field in DIMENSION_FIELDS:
            if field in group.columns and group[field].notna().any():
                dimensions[field] = float(group[field].mean())
            else:
                dimensions[field] = None
        notes = _collect_notes(group.get("review_note"))
        source_counts = group["source"].value_counts().to_dict() if "source" in group.columns else {}
        results.append(
            {
                "model_name": str(model_name),
                "display_name": display_model_name(model_name, mapping),
                "sample_count": int(len(group)),
                "avg_total": float(group["total_score"].mean()),
                "dimensions": dimensions,
                "review_notes": notes,
                "seed_count": int(source_counts.get("seed", 0)),
                "confirmed_count": int(source_counts.get("confirmed_live", 0)),
            }
        )
    # 按平均总分降序仅为展示稳定性，页面文案明确说明这不是排行榜。
    results.sort(key=lambda item: (-item["avg_total"], item["display_name"]))
    return results


def summarize_formal(seed_scores: pd.DataFrame, confirmed_live: pd.DataFrame) -> dict[str, Any]:
    """正式结论首屏统计：纳入条数、模型数、平均总分与来源构成。"""
    combined = combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty:
        return {"total_rows": 0, "model_count": 0, "avg_total": None, "seed_rows": 0, "confirmed_rows": 0}
    source = combined["source"] if "source" in combined.columns else pd.Series([], dtype=str)
    return {
        "total_rows": int(len(combined)),
        "model_count": int(combined["model_name"].nunique()) if "model_name" in combined.columns else 0,
        "avg_total": float(combined["total_score"].mean()),
        "seed_rows": int((source == "seed").sum()),
        "confirmed_rows": int((source == "confirmed_live").sum()),
    }


def build_draft_rows(
    pending_live: pd.DataFrame,
    responses_df: pd.DataFrame | None = None,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把 pending live 评分整理为草稿行：模型、建议分、各维度、复核说明、错误信息与模型回答。

    回答文本从 live_run_responses 按 (run_id, case_id, model_name) 拼接，缺失则留空。
    """
    if not isinstance(pending_live, pd.DataFrame) or pending_live.empty:
        return []

    answers = _index_answers(responses_df)
    rows: list[dict[str, Any]] = []
    for _, row in pending_live.iterrows():
        eval_model = row.get("eval_model")
        key = (str(row.get("run_id")), str(row.get("case_id")), str(eval_model))
        rows.append(
            {
                "row_id": _as_int(row.get("id")),
                "model_name": _text(eval_model),
                "display_name": display_model_name(eval_model, mapping),
                "case_id": _text(row.get("case_id")),
                "total_score": _num(row.get("total_score")),
                "dimensions": {field: _num(row.get(field)) for field in DIMENSION_FIELDS},
                "review_note": _text(row.get("review_note")),
                "review_status": _text(row.get("review_status")) or "pending",
                "error_code": _text(row.get("error_code")),
                "error_message": _text(row.get("error_message")),
                "answer_text": _text(answers.get(key)),
            }
        )
    return rows


def summarize_frequent_issues(
    formal_scores: pd.DataFrame,
    errors_df: pd.DataFrame | None = None,
    notes: Sequence[str] | None = None,
    *,
    top_n: int = 4,
) -> list[str]:
    """基于低分维度、错误标签与人工复核说明，归纳当前样本内的高频问题。

    全部由数据动态推导，不臆造模型缺陷；无数据时返回空列表。
    """
    issues: list[str] = []

    if isinstance(formal_scores, pd.DataFrame) and not formal_scores.empty:
        ranking = get_dimension_gap_ranking(formal_scores)
        for _, row in ranking.head(2).iterrows():
            issues.append(f"{row['dimension']}相对薄弱（达成率约 {float(row['attainment']):.0%}）")

    if isinstance(errors_df, pd.DataFrame) and not errors_df.empty and "error_type" in errors_df.columns:
        counts = errors_df["error_type"].dropna().astype(str).value_counts()
        for error_type, count in counts.head(2).items():
            issues.append(f"高频错误标签：{error_type}（{int(count)} 次）")

    if notes:
        cleaned = _collect_notes(notes)
        if cleaned:
            issues.append("人工复核反复提到：" + "；".join(cleaned[:2]))

    return issues[:top_n]


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _index_answers(responses_df: pd.DataFrame | None) -> dict[tuple[str, str, str], str]:
    answers: dict[tuple[str, str, str], str] = {}
    if not isinstance(responses_df, pd.DataFrame) or responses_df.empty:
        return answers
    for _, row in responses_df.iterrows():
        key = (str(row.get("run_id")), str(row.get("case_id")), str(row.get("model_name")))
        answers[key] = _text(row.get("answer_text"))
    return answers


def _collect_notes(values) -> list[str]:
    """去重保序地收集非空复核说明。"""
    if values is None:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    iterable = values.tolist() if isinstance(values, pd.Series) else list(values)
    for value in iterable:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _as_int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)
