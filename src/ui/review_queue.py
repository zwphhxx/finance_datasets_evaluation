"""评分确认页的批次、队列和表格选择逻辑。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import model_display as md
from src.metrics import get_task_by_case_id
from src.ui.components import render_inline_status
from src.ui.review_scoring import (
    as_int,
    build_review_recommendation,
    build_rubric_rows,
    clean,
    format_datetime,
    score_text,
)


REVIEW_FILTER_OPTIONS = ["待处理", "已处理"]
REVIEW_ACTION_RESULT_KEY = "review_action_result"
REVIEW_AUTO_SWITCH_KEY = "review_auto_switch_pending"
REVIEW_QUEUE_VERSION_KEY = "review_queue_version"


def filter_live_score_frame(scores: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        return pd.DataFrame()
    frame = scores.copy()
    if "judge_status" in frame:
        frame = frame[frame["judge_status"].astype(str).str.strip().str.lower() == "success"]
    if "status" in frame:
        frame = frame[frame["status"].astype(str).str.strip().str.lower() != "inactive"]
    if "eval_model" in frame:
        frame = frame[~frame["eval_model"].apply(md.is_seed_model)]
    if "score_run_id" not in frame:
        frame["score_run_id"] = ""
    if "id" in frame:
        frame = frame.sort_values("id", ascending=False)
    return frame.reset_index(drop=True)


def select_score_run_id(scores: pd.DataFrame, eval_status: dict) -> str | None:
    run_ids = score_run_ids(scores)
    if not run_ids:
        return None

    st.caption("评分批次用于区分不同时间生成的评分草稿。默认展示最新批次。")
    default = default_score_run_id(scores, eval_status)
    index = run_ids.index(default) if default in run_ids else 0
    if len(run_ids) == 1:
        summary = build_score_run_summary(scores, run_ids[0])
        created = summary["created_at"] if summary["created_at"] != "—" else "生成时间未记录"
        st.markdown(f"当前评分批次：{created} 生成，{summary['pending']} 条评分待处理。")
        render_score_run_summary(scores, run_ids[0])
        return run_ids[0]
    selected = st.selectbox(
        "评分批次",
        run_ids,
        index=index,
        format_func=lambda run_id: score_run_option_label(scores, run_id),
        key="review_score_run_select",
    )
    render_score_run_summary(scores, str(selected))
    return str(selected)


def score_run_ids(scores: pd.DataFrame) -> list[str]:
    if not isinstance(scores, pd.DataFrame) or scores.empty or "score_run_id" not in scores:
        return []
    rows = scores.copy()
    if "id" in rows:
        rows = rows.sort_values("id", ascending=False)
    elif "created_at" in rows:
        rows = rows.sort_values("created_at", ascending=False)
    ids = [str(value) for value in rows["score_run_id"].dropna().unique().tolist()]
    return [value for value in ids if value]


def latest_score_run_id(scores: pd.DataFrame) -> str:
    if scores.empty:
        return ""
    if "id" in scores:
        row = scores.sort_values("id", ascending=False).iloc[0]
    elif "created_at" in scores:
        row = scores.sort_values("created_at", ascending=False).iloc[0]
    else:
        row = scores.iloc[0]
    return str(row.get("score_run_id") or "")


def build_score_run_summary(scores: pd.DataFrame, score_run_id: str) -> dict:
    rows = scores[scores["score_run_id"].astype(str) == str(score_run_id)]
    status = rows.get("review_status", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    pending = int((status == "pending").sum())
    confirmed = int((status == "confirmed").sum())
    skipped = int((status == "skipped").sum())
    processed = int(status.isin(["confirmed", "skipped"]).sum())
    models = unique_display_models(rows)
    cases = unique_texts(rows.get("case_id", pd.Series(dtype=str)).tolist())
    return {
        "score_run_id": str(score_run_id),
        "created_at": score_run_created_at(rows),
        "total": int(len(rows)),
        "pending": pending,
        "confirmed": confirmed,
        "skipped": skipped,
        "processed": processed,
        "models": models,
        "cases": cases,
        "model_count": len(models),
        "case_count": len(cases),
    }


def score_run_option_label(scores: pd.DataFrame, score_run_id: str) -> str:
    summary = build_score_run_summary(scores, score_run_id)
    prefix = "最新批次" if str(score_run_id) == latest_score_run_id(scores) else "历史批次"
    status_text = (
        f"{summary['pending']} 条待处理"
        if summary["pending"]
        else f"已处理 {summary['processed']} 条"
    )
    return (
        f"{prefix}｜{summary['created_at']}｜{status_text}｜"
        f"{summary['model_count']} 个模型｜{summary['case_count']} 个样本"
    )


def default_score_run_id(scores: pd.DataFrame, eval_status: dict) -> str:
    run_ids = score_run_ids(scores)
    if not run_ids:
        return ""
    preferred = str((eval_status or {}).get("score_run_id") or "")
    if preferred in run_ids and build_score_run_summary(scores, preferred)["pending"] > 0:
        return preferred
    for run_id in run_ids:
        if build_score_run_summary(scores, run_id)["pending"] > 0:
            return run_id
    latest = latest_score_run_id(scores)
    return latest if latest in run_ids else run_ids[0]


def render_score_run_summary(scores: pd.DataFrame, score_run_id: str) -> None:
    summary = build_score_run_summary(scores, score_run_id)
    render_inline_status(
        [
            ("本批次评分", f"{summary['total']} 条"),
            ("待处理", f"{summary['pending']} 条"),
            ("已确认", f"{summary['confirmed']} 条"),
            ("暂不采用", f"{summary['skipped']} 条"),
            ("覆盖模型", compact_texts(summary["models"])),
            ("覆盖样本", compact_texts(summary["cases"])),
        ]
    )
    st.caption(f"批次 ID：{score_run_id}")


def score_run_created_at(rows: pd.DataFrame) -> str:
    if not isinstance(rows, pd.DataFrame) or rows.empty or "created_at" not in rows:
        return "—"
    values = rows["created_at"].dropna().astype(str)
    if values.empty:
        return "—"
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.notna().any():
        return parsed.max().strftime("%Y-%m-%d %H:%M")
    return format_datetime(values.max())


def unique_display_models(rows: pd.DataFrame) -> list[str]:
    if not isinstance(rows, pd.DataFrame) or rows.empty:
        return []
    source = rows["eval_model"] if "eval_model" in rows else rows.get("model_name", pd.Series(dtype=str))
    values = unique_texts(source.tolist())
    return [md.display_model_name(value, source="live") for value in values]


def unique_texts(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def compact_texts(values: list[str], limit: int = 3) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "—"
    if len(cleaned) <= limit:
        return "、".join(cleaned)
    return f"{'、'.join(cleaned[:limit])} 等 {len(cleaned)} 个"


def score_run_label(scores: pd.DataFrame, score_run_id: str) -> str:
    return score_run_option_label(scores, score_run_id)


def build_live_review_items(base, score_rows: pd.DataFrame, responses: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    answer_lookup = live_answer_lookup(responses)
    for _, score_row in score_rows.iterrows():
        case_id = clean(score_row.get("case_id"))
        model_name = clean(score_row.get("eval_model"))
        if not case_id or not model_name:
            continue
        task_rows = get_task_by_case_id(base.tasks, case_id)
        if task_rows.empty:
            continue
        task_info = task_rows.iloc[0]
        gold = base.gold_answer_map.get(case_id)
        run_id = clean(score_row.get("run_id"))
        output_data = dict(score_row)
        output_data["model_name"] = model_name
        output_data["answer_text"] = answer_lookup.get((run_id, case_id, model_name), "")
        output_data["output_id"] = f"{run_id}::{model_name}::{case_id}"
        output_row = pd.Series(output_data)
        rubric_rows = build_rubric_rows(output_row)
        recommendation = build_review_recommendation(
            output_row,
            pd.DataFrame(),
            gold,
            task_info,
            rubric_rows,
        )
        items.append({
            "case_id": case_id,
            "model_name": model_name,
            "display_model": md.display_model_name(model_name, source="live"),
            "source": "live",
            "source_label": "真实评分草稿",
            "score_row_id": as_int(score_row.get("id")),
            "score_run_id": clean(score_row.get("score_run_id")),
            "created_at": clean(score_row.get("created_at")),
            "task_info": task_info,
            "gold": gold,
            "output_row": output_row,
            "score_row": dict(score_row),
            "rubric_rows": rubric_rows,
            "recommendation": recommendation,
        })
    items.sort(key=lambda item: (
        review_status_rank(item["output_row"].get("review_status"), item["source"]),
        recommendation_rank(item["recommendation"]),
        item["case_id"],
        item["display_model"],
    ))
    return items


def live_answer_lookup(responses: pd.DataFrame) -> dict[tuple[str, str, str], str]:
    if not isinstance(responses, pd.DataFrame) or responses.empty:
        return {}
    lookup: dict[tuple[str, str, str], str] = {}
    for _, row in responses.iterrows():
        key = (
            clean(row.get("run_id")),
            clean(row.get("case_id")),
            clean(row.get("model_name")),
        )
        lookup[key] = clean(row.get("answer_text"))
    return lookup


def render_review_queue(items: list[dict], selected_score_run_id: str | None) -> tuple[list[dict], int | None]:
    stats = build_review_queue_stats(items)
    render_review_feedback(items)
    render_inline_status(
        [
            ("待处理", str(stats["pending"])),
            ("已处理", str(stats["processed"])),
        ]
    )

    if st.session_state.get("review_queue_filter") not in REVIEW_FILTER_OPTIONS:
        st.session_state["review_queue_filter"] = REVIEW_FILTER_OPTIONS[0]
    filter_value = st.selectbox(
        "筛选",
        REVIEW_FILTER_OPTIONS,
        key="review_queue_filter",
        help="按处理状态筛选评分记录。",
    )
    visible_items = filter_review_queue_items(items, filter_value)
    if not visible_items:
        return [], None

    table_rows = [review_queue_row(item) for item in visible_items]
    frame = pd.DataFrame(table_rows)
    version = int(st.session_state.get(REVIEW_QUEUE_VERSION_KEY, 0) or 0)
    selected_state = st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        row_height=34,
        column_order=["样本编号", "模型", "总分", "建议处理", "状态", "生成时间"],
        column_config={
            "样本编号": st.column_config.TextColumn("样本编号", width="small"),
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "总分": st.column_config.TextColumn("总分", width="small"),
            "建议处理": st.column_config.TextColumn("建议处理", width="small"),
            "状态": st.column_config.TextColumn("状态", width="small"),
            "生成时间": st.column_config.TextColumn("生成时间", width="medium"),
        },
        key=f"review_queue_table::{selected_score_run_id or 'latest'}::{filter_value}::{version}",
    )
    st.caption("点击表格行查看评分详情；未确认评分不会纳入正式结论。")
    return visible_items, selected_review_table_index(selected_state, visible_items)


def build_review_queue_stats(items: list[dict]) -> dict[str, int]:
    """统计评分确认队列；只统计真实运行评分。"""
    stats = {"pending": 0, "processed": 0}
    for item in items:
        if item.get("source") == "seed":
            continue
        status = str(item["output_row"].get("review_status") or "pending").strip().lower()
        if status in {"confirmed", "skipped"}:
            stats["processed"] += 1
            continue
        stats["pending"] += 1
    return stats


def has_pending_review_items(items: list[dict]) -> bool:
    return any(
        item.get("source") != "seed" and review_status_value(item) == "pending"
        for item in items
    )


def review_empty_message(items: list[dict]) -> str:
    if has_pending_review_items(items):
        return "当前筛选条件下暂无评分记录。"
    return "暂无待处理评分草稿。若发起评测页存在评分失败，请先重试评分。"


def should_show_no_pending_after_action(items: list[dict], action_recent: bool) -> bool:
    return bool(action_recent) and not has_pending_review_items(items)


def select_next_review_index(
    visible_items: list[dict],
    *,
    handled_row_id: int | None = None,
) -> int | None:
    if not visible_items:
        return None
    for index, item in enumerate(visible_items):
        if handled_row_id is not None and as_int(item.get("score_row_id")) == handled_row_id:
            continue
        if review_status_value(item) == "pending":
            return index
    return 0


def selected_review_table_index(selection_state, visible_items: list[dict]) -> int | None:
    if not visible_items:
        return None
    rows = []
    selection = getattr(selection_state, "selection", None)
    if isinstance(selection_state, dict):
        selection = selection_state.get("selection")
    if isinstance(selection, dict):
        rows = selection.get("rows") or []
    elif selection is not None:
        rows = getattr(selection, "rows", []) or []
    if rows:
        try:
            index = int(rows[0])
        except (TypeError, ValueError):
            index = 0
        if 0 <= index < len(visible_items):
            return index
    return select_next_review_index(visible_items)


def build_review_action_result(action_type: str, row_id: int | None) -> dict[str, object]:
    messages = {
        "confirm": "已确认生效，该评分已纳入正式结论。",
        "revision": "已修订并确认，该评分已纳入正式结论。",
        "skip": "已暂不采用，该评分未纳入正式结论。",
    }
    levels = {"confirm": "success", "revision": "success", "skip": "info"}
    return {
        "action_type": action_type,
        "level": levels.get(action_type, "success"),
        "message": messages.get(action_type, "操作已完成。"),
        "row_id": row_id,
        "show_conclusions_link": action_type in {"confirm", "revision"},
    }


def filter_review_queue_items(items: list[dict], filter_value: str) -> list[dict]:
    live_items = [item for item in items if item.get("source") != "seed"]
    if filter_value == "待处理":
        return [
            item for item in live_items
            if review_status_value(item) == "pending"
        ]
    if filter_value == "已处理":
        return [
            item for item in live_items
            if review_status_value(item) in {"confirmed", "skipped"}
        ]
    return []


def review_queue_row(item: dict) -> dict[str, object]:
    row = item["output_row"]
    recommendation = item["recommendation"]
    return {
        "样本编号": item["case_id"],
        "模型": item["display_model"],
        "总分": score_text(row.get("total_score")),
        "建议处理": str(recommendation.get("recommendation") or "待判断"),
        "状态": display_review_status(row.get("review_status"), item["source"]),
        "生成时间": format_datetime(item.get("created_at")),
    }


def render_review_feedback(items: list[dict]) -> None:
    render_review_action_feedback(items)


def render_review_action_feedback(items: list[dict]) -> None:
    result = current_review_action_result()
    if not result:
        return
    message = str(result.get("message") or "")
    level = str(result.get("level") or "success")
    if level == "warning":
        st.warning(message)
    elif level == "info":
        st.info(message)
    else:
        st.success(message)
    if has_pending_review_items(items):
        st.caption("已切换到下一条待处理评分。")
    else:
        st.caption("当前批次暂无待处理评分。")
    if result.get("show_conclusions_link") and st.button(
        "查看评测结论",
        type="secondary",
        key="review_action_go_conclusions",
    ):
        st.session_state.current_page = "conclusions"
        st.rerun()


def record_review_action_result(action_type: str, row_id: int | None) -> None:
    st.session_state[REVIEW_ACTION_RESULT_KEY] = build_review_action_result(action_type, row_id)
    st.session_state[REVIEW_AUTO_SWITCH_KEY] = True
    bump_review_queue_version()


def current_review_action_result() -> dict:
    result = st.session_state.get(REVIEW_ACTION_RESULT_KEY)
    return result if isinstance(result, dict) else {}


def bump_review_queue_version() -> None:
    st.session_state[REVIEW_QUEUE_VERSION_KEY] = int(
        st.session_state.get(REVIEW_QUEUE_VERSION_KEY, 0) or 0
    ) + 1


def review_status_value(item: dict) -> str:
    return str(item["output_row"].get("review_status") or "pending").strip().lower()


def review_item_label(item: dict) -> str:
    row = item["output_row"]
    return (
        f"{item['case_id']}｜{item['display_model']}｜"
        f"{score_text(row.get('total_score'))}｜{display_review_status(row.get('review_status'), item['source'])}"
    )


def review_status_label(status: str) -> str:
    return {
        "pending": "待确认",
        "confirmed": "已确认",
        "skipped": "暂不采用",
    }.get(str(status).strip().lower(), "待确认")


def display_review_status(status, source: str) -> str:
    return review_status_label(str(status or "pending"))


def review_status_rank(status, source: str) -> int:
    value = str(status or "pending").strip().lower()
    if value == "pending":
        return 0
    if value == "skipped":
        return 1
    if value == "confirmed":
        return 2
    return 3


def recommendation_rank(recommendation: dict) -> int:
    order = {"不建议采用": 0, "建议复核": 1, "建议确认": 2}
    return order.get(str(recommendation.get("recommendation") or ""), 3)
