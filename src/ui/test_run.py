"""评测操作页：一次启动或一次续跑，回答与评分作为同一持久化流程。"""

from __future__ import annotations

import os
from html import escape

import pandas as pd
import streamlit as st

from app.models import siliconflow as sf
from app.models.registry import get_text_provider
from app.persistence import (
    PersistenceConfigurationError,
    ResultStoreError,
    ResultStoreUnavailableError,
    get_result_store,
)
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import formal_records as formal
from app.services import model_display as md
from app.services import sample_repository as sr
from app.services import scorer as sc
from app.services.evaluation_workflow import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    STOPPED,
    EvaluationConfig,
    EvaluationRunStatus,
    EvaluationWorkflow,
    WorkflowCheckpointError,
    WorkflowStopped,
)
from src.ui import conclusions_data as cd
from src.ui.components import (
    render_empty_state,
    render_inline_status,
    render_numbered_section,
    render_page_heading,
    render_persistence_status,
)
from src.ui.evaluation_config import (
    build_evaluation_config_from_checkpoint,
    build_run_plan_summary,
    build_run_queue_items,
    build_sample_options,
    eligible_case_ids,  # noqa: F401 - compatibility import for existing callers
)
from src.ui.evaluation_results import render_evaluation_status, render_run_record
from src.ui.page_config import get_page_config
from src.ui.scroll import request_scroll

NO_TESTABLE_SAMPLE_MESSAGE = (
    "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
    "专业标准答案具备完整评判标准，评分标准满分标准和扣分规则完整，且样本状态为已入库。"
)

_SILICONFLOW_LABEL = "硅基流动"
SAMPLE_CHECKBOX_KEY_PREFIX = "test_run_case_checkbox_"
SAMPLE_TABLE_COLUMN_WIDTHS = [0.58, 1.0, 2.6, 1.15, 0.8, 0.95]
SAMPLE_TABLE_HEADERS = ["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"]
SAMPLE_TABLE_HEIGHT = 330
_EVAL_TEMPERATURE_DEFAULT = 0.1
_EVAL_TEMPERATURE_ENV = "FINDUEVAL_EVAL_TEMPERATURE"
_EVAL_TEMPERATURE_KEY = "test_run_temperature"
_MODEL_DIALOG_TEMPERATURE_KEY = "test_run_model_dialog_temperature"
_MODEL_OPTION_LIMIT = 30
_JUDGE_TEMPERATURE = 0.0
_JUDGE_MAX_TOKENS = 2048
_EVAL_MAX_TOKENS_DEFAULT = 4096
_EVAL_MAX_TOKENS_LIMIT = 8192
_EVAL_MAX_TOKENS_ENV = "FINDUEVAL_EVAL_MAX_TOKENS"
_MAINTENANCE_EXPORT_KEY = "test_run_maintenance_export"

def _persistence_gate(result: bool) -> None:
    if not result:
        raise RuntimeError("runtime persistence required")


def _require_persistence_preflight(provider_name: str) -> None:
    from app.persistence import (
        ResultStoreSettings,
        ResultStoreUnavailableError,
        get_result_store,
        require_durable_live_store,
    )

    store = get_result_store()
    settings = ResultStoreSettings(url="", is_postgresql=store.is_postgresql)
    require_durable_live_store(provider_name, settings)
    if not store.ping():
        raise ResultStoreUnavailableError(
            "评测结果数据库暂不可用，已停止模型调用。"
        )


def resolve_eval_max_tokens(raw_value: str | None = None) -> int:
    """Resolve the hidden answer-generation token budget with a defensive cap."""
    raw = os.getenv(_EVAL_MAX_TOKENS_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return _EVAL_MAX_TOKENS_DEFAULT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _EVAL_MAX_TOKENS_DEFAULT
    if parsed <= 0:
        return _EVAL_MAX_TOKENS_DEFAULT
    return min(parsed, _EVAL_MAX_TOKENS_LIMIT)


def resolve_eval_temperature(raw_value: str | None = None) -> float:
    """Resolve the answer-generation temperature while keeping runs comparable."""
    raw = os.getenv(_EVAL_TEMPERATURE_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return _EVAL_TEMPERATURE_DEFAULT
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _EVAL_TEMPERATURE_DEFAULT
    if parsed < 0.0 or parsed > 1.0:
        return _EVAL_TEMPERATURE_DEFAULT
    return parsed


_EVAL_MAX_TOKENS = resolve_eval_max_tokens()
_EVAL_TEMPERATURE = resolve_eval_temperature()


def _normalize_eval_temperature(value) -> float:
    return resolve_eval_temperature(str(value if value is not None else ""))


def _current_eval_temperature() -> float:
    if _EVAL_TEMPERATURE_KEY not in st.session_state:
        return _EVAL_TEMPERATURE
    return _normalize_eval_temperature(st.session_state.get(_EVAL_TEMPERATURE_KEY))


def filter_sample_selection_options(
    sample_options: list[dict],
    keyword: str = "",
    scenario: str = "全部",
    difficulty: str = "全部",
) -> list[dict]:
    """Filter testable sample options for the dialog table."""
    query = str(keyword or "").strip().lower()
    scenario_value = str(scenario or "全部")
    difficulty_value = str(difficulty or "全部")
    filtered: list[dict] = []
    for item in sample_options:
        task = item.get("task") or {}
        searchable = " ".join(
            str(value or "")
            for value in [
                item.get("case_id"),
                item.get("title"),
                item.get("scenario"),
                item.get("difficulty"),
                task.get("title"),
                task.get("question"),
                task.get("context"),
                task.get("expected_capability"),
            ]
        ).lower()
        if query and query not in searchable:
            continue
        if scenario_value != "全部" and str(item.get("scenario") or "") != scenario_value:
            continue
        if difficulty_value != "全部" and str(item.get("difficulty") or "") != difficulty_value:
            continue
        filtered.append(item)
    return filtered


def build_sample_selection_rows(sample_options: list[dict], selected_case_ids: list[str]) -> list[dict]:
    """Build compact rows for selecting testable samples in the dialog table."""
    selected = set(selected_case_ids or [])
    rows: list[dict] = []
    for item in sample_options:
        case_id = str(item.get("case_id") or "").strip()
        rows.append({
            "选择": case_id in selected,
            "样本编号": case_id,
            "任务标题": item.get("title") or "待补充",
            "场景": item.get("scenario") or "待补充",
            "难度": item.get("difficulty") or "待补充",
            "测试状态": "可测试",
        })
    return rows


def sample_checkbox_key(case_id: str) -> str:
    return f"{SAMPLE_CHECKBOX_KEY_PREFIX}{case_id}"


def merge_sample_checkbox_selection(
    selected_case_ids: list[str],
    filtered_options: list[dict],
    checkbox_values: dict[str, bool],
    all_case_ids: set[str],
) -> list[str]:
    """Merge visible checkbox state while preserving selected hidden samples."""
    current = [
        case_id
        for case_id in _dedupe([str(value) for value in (selected_case_ids or [])])
        if case_id in all_case_ids
    ]
    visible_ids = [str(item.get("case_id") or "") for item in (filtered_options or [])]
    visible_set = {case_id for case_id in visible_ids if case_id}
    if not visible_set:
        return current

    checked_visible = [
        case_id
        for case_id in visible_ids
        if case_id in visible_set and bool(checkbox_values.get(case_id))
    ]
    return _dedupe([
        *[case_id for case_id in current if case_id not in visible_set],
        *checked_visible,
    ])


def _clear_session_state_prefix(prefix: str) -> None:
    for key in [key for key in st.session_state if str(key).startswith(prefix)]:
        st.session_state.pop(key, None)


def build_model_selection_options(models, keyword: str, limit: int = _MODEL_OPTION_LIMIT) -> tuple[list[str], int]:
    """Filter provider models into a bounded selectbox option list."""
    query = str(keyword or "").strip().lower()
    matched: list[str] = []
    for model in models or []:
        model_id = str(getattr(model, "id", "") or "").strip()
        if not model_id:
            continue
        raw = getattr(model, "raw", {}) or {}
        metadata = getattr(model, "metadata", {}) or {}
        searchable_parts = [
            model_id,
            str(getattr(model, "owned_by", "") or ""),
            str(raw.get("name", "") or ""),
            str(raw.get("display_name", "") or ""),
            str(metadata.get("name", "") or ""),
            str(metadata.get("display_name", "") or ""),
        ]
        haystack = " ".join(searchable_parts).lower()
        if not query or query in haystack:
            matched.append(model_id)
    deduped = _dedupe(matched)
    return deduped[:limit], len(deduped)


def prompt_preview_task_for_case(
    sample_options: list[dict],
    selected_case_ids: list[str],
    preview_case_id: str | None = None,
) -> dict:
    """Return the exact task object used for both prompt preview and run queue."""
    by_case = {str(item.get("case_id") or ""): item for item in sample_options or []}
    preview_ids = [
        str(case_id)
        for case_id in selected_case_ids or []
        if str(case_id) in by_case
    ] or list(by_case)
    current = str(preview_case_id or "")
    if current not in preview_ids:
        current = preview_ids[0] if preview_ids else ""
    return (by_case.get(current) or {}).get("task") or {}


def render_test_run_page(
    data_bundle: dict,
    *,
    store=None,
    status_loader=None,
    workflow_factory=None,
    config_builder=None,
    checkpoint_builder=None,
    preflight=None,
) -> None:
    """Render one durable answer-and-score pipeline from database state."""
    base = data_bundle["base"]
    config = get_page_config("test_run")
    render_page_heading(config.title, config.question)

    tasks_df = base.tasks
    if tasks_df is None or tasks_df.empty:
        render_empty_state("当前样本库没有可用样本。")
        return
    task_records = tasks_df.to_dict("records")
    gold_map = getattr(base, "gold_answer_map", {}) or {}
    testable_dimensions = ds.get_testable_rubric_dimensions()
    sample_title_map = {s.sample_id: s.title for s in sr.load_samples() if s.title}
    sample_options = build_sample_options(task_records, gold_map, testable_dimensions, title_map=sample_title_map)
    _ensure_default_selected_cases(sample_options)
    provider_name = _current_provider_name()
    selected_tasks = _selected_tasks_from_state(sample_options)
    model_ids = _selected_model_ids_from_state()
    run_plan = build_run_plan_summary(model_ids, selected_tasks)

    _render_evaluation_scope(sample_options, selected_tasks, model_ids, run_plan)

    result_store = store
    store_available = result_store is not None
    if result_store is None:
        try:
            result_store = get_result_store()
            store_available = True
        except (PersistenceConfigurationError, ResultStoreUnavailableError, ResultStoreError):
            render_persistence_status(
                "评测结果数据库暂不可用。可继续查看项目与样本，数据库恢复后再发起评测。"
            )

    load_status = status_loader or _load_evaluation_status
    build_workflow = workflow_factory or build_live_workflow
    build_new_config = config_builder or build_evaluation_config
    rebuild_checkpoint = checkpoint_builder or build_evaluation_config_from_checkpoint
    require_preflight = preflight or _require_persistence_preflight

    latest_rows: list[dict] = []
    status: EvaluationRunStatus | None = None
    if store_available:
        try:
            latest_rows = list(result_store.latest_queue("live_run_queue"))
            if latest_rows and formal.formal_recovery_run_eligible(None, latest_rows):
                latest_run_id = str(latest_rows[0].get("run_id") or "").strip()
                if latest_run_id:
                    status = load_status(result_store, latest_run_id)
        except (ResultStoreError, ResultStoreUnavailableError, WorkflowCheckpointError):
            store_available = False
            latest_rows = []
            status = None
            render_persistence_status(
                "评测结果数据库暂不可用，已禁用开始与继续评测。请在数据库恢复后重试。"
            )

    render_numbered_section("02", "评测进度")
    status_region = st.empty()
    display_status = status

    def stopped_status(message: str) -> EvaluationRunStatus:
        return EvaluationRunStatus(
            run_id=status.run_id if status is not None else "",
            score_run_id=status.score_run_id if status is not None else "",
            state=STOPPED,
            total=status.total if status is not None else int(run_plan["planned_responses"]),
            succeeded=status.succeeded if status is not None else 0,
            failed=status.failed if status is not None else 0,
            pending=status.pending if status is not None else int(run_plan["planned_responses"]),
            resumable=False,
            message=message,
            persistence_failed_in_session=True,
        )

    service_ready = bool(store_available and sf.is_configured())
    if not sf.is_configured():
        st.caption("当前未配置模型服务密钥，暂不能发起真实调用。")

    terminal = status is not None and status.state in {COMPLETED, PARTIAL, FAILED}
    can_start = status is None or terminal
    if can_start:
        with st.container(key="test_run_primary_action"):
            start_clicked = st.button(
                "开始评测",
                key="test_run_start_evaluation",
                type="primary",
                disabled=not bool(run_plan["can_run"]) or not service_ready,
                use_container_width=True,
            )
        if start_clicked:
            try:
                require_preflight(provider_name)
                evaluation_config = build_new_config(base, selected_tasks, model_ids)
                workflow = build_workflow(result_store)
                workflow.start_evaluation(evaluation_config)
            except WorkflowStopped as exc:
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except (
                PersistenceConfigurationError,
                ResultStoreUnavailableError,
                ResultStoreError,
            ) as exc:
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except WorkflowCheckpointError as exc:
                render_persistence_status(str(exc) or "评测配置无法通过一致性校验。")
            else:
                cd.clear_conclusions_caches()
                st.rerun()
    elif status is not None and status.state == INTERRUPTED:
        checkpoint_config = None
        try:
            checkpoint_config = rebuild_checkpoint(status.run_id, base, store=result_store)
        except WorkflowCheckpointError:
            st.caption("当前样本或参数已变化，不能继续旧批次。")
        with st.container(key="test_run_primary_action"):
            continue_clicked = st.button(
                "继续评测",
                key="test_run_continue_evaluation",
                type="primary",
                disabled=checkpoint_config is None or not service_ready,
                use_container_width=True,
            )
        if continue_clicked:
            try:
                require_preflight(provider_name)
                workflow = build_workflow(result_store)
                workflow.continue_evaluation(status.run_id, checkpoint_config)
            except WorkflowStopped as exc:
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except (
                PersistenceConfigurationError,
                ResultStoreUnavailableError,
                ResultStoreError,
            ) as exc:
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except WorkflowCheckpointError as exc:
                render_persistence_status(str(exc) or "评测配置无法通过一致性校验。")
            else:
                cd.clear_conclusions_caches()
                st.rerun()
    with status_region.container():
        if display_status is None:
            st.caption("当前没有进行中的评测批次。")
        else:
            render_evaluation_status(display_status)
            if status is not None:
                _render_persisted_evaluation_records(result_store, status)

    _render_evaluation_maintenance(result_store if store_available else None, status)
    _render_pending_dialogs(sample_options)


def _load_evaluation_status(store, run_id: str) -> EvaluationRunStatus:
    """Read status without constructing either model provider."""
    return EvaluationWorkflow(store, None, None).load_evaluation_status(run_id)


def build_live_workflow(store=None) -> EvaluationWorkflow:
    """Construct live providers only after an enabled action is clicked."""
    durable_store = store if store is not None else get_result_store()
    answer_provider = get_text_provider(sf.PROVIDER_NAME)
    judge_provider = get_text_provider(sf.PROVIDER_NAME)
    return EvaluationWorkflow(durable_store, answer_provider, judge_provider)


def build_evaluation_config(
    base,
    selected_tasks: list[dict],
    model_ids: list[str],
) -> EvaluationConfig:
    """Build a new-batch config from the explicit current selection."""
    queue_items = build_run_queue_items(model_ids, selected_tasks)
    versions = ds.list_dataset_versions()
    dataset_version = str(versions[0] if versions else "")
    gold_source = getattr(base, "gold_answer_map", {}) or {}
    case_ids = {str(item.get("case_id") or "") for item in queue_items}
    gold_map = {
        case_id: dict(gold_source[case_id])
        for case_id in case_ids
        if case_id and isinstance(gold_source.get(case_id), dict)
    }
    prompt_payload = tuple(
        {
            "case_id": str(item.get("case_id") or ""),
            "messages": er.build_messages(item.get("task") or {}),
        }
        for item in queue_items
    )
    return EvaluationConfig(
        provider_name=sf.PROVIDER_NAME,
        model_ids=tuple(_dedupe(model_ids)),
        queue_items=tuple(queue_items),
        generation_parameters={"temperature": _current_eval_temperature(), "max_tokens": _EVAL_MAX_TOKENS},
        judge_parameters={
            "temperature": _JUDGE_TEMPERATURE,
            "max_tokens": _JUDGE_MAX_TOKENS,
            "judge_model": sc.DEFAULT_JUDGE_MODEL,
        },
        dataset_version=dataset_version,
        prompt_payload=prompt_payload,
        gold_map=gold_map,
        dimensions=tuple(ds.get_rubric_dimensions()),
    )


def _render_evaluation_scope(
    sample_options: list[dict],
    selected_tasks: list[dict],
    model_ids: list[str],
    run_plan: dict[str, int | bool],
) -> None:
    render_numbered_section("01", "评测范围")
    render_inline_status([
        _status_row("已选样本", _selected_sample_summary(selected_tasks), warn=not selected_tasks),
        _status_row("已选模型", _selected_model_summary(model_ids), warn=not model_ids),
        _status_row("计划评测", f"{run_plan['planned_responses']} 项", warn=not run_plan["planned_responses"]),
    ])
    with st.container(key="test_run_scope_actions"):
        if st.button("选择样本", key="test_run_open_samples", type="secondary"):
            _open_sample_dialog(sample_options)
        if st.button("选择模型", key="test_run_open_models", type="secondary"):
            _open_model_dialog(sf.PROVIDER_NAME)
    if selected_tasks and st.button(
        "查看发送给被测模型的提示词",
        key="test_run_open_prompt_preview",
        type="tertiary",
    ):
        _open_prompt_preview_dialog(selected_tasks)


def _render_persisted_evaluation_records(store, status: EvaluationRunStatus) -> None:
    try:
        answers = store.list_rows("live_run_responses", run_id=status.run_id)
        scores = store.list_rows("live_run_scores", score_run_id=status.score_run_id)
    except (ResultStoreError, ResultStoreUnavailableError):
        render_persistence_status("评测记录暂时无法读取。")
        return
    render_run_record(answers, scores, ds.get_rubric_dimensions())


def _render_evaluation_maintenance(store=None, status: EvaluationRunStatus | None = None) -> None:
    """Keep data portability and technical navigation out of the primary flow."""
    with st.popover("评测维护", type="tertiary"):
        st.markdown("**批次技术字段**")
        if status is None:
            st.caption("当前没有可展示的持久化批次。")
        else:
            st.caption(
                f"回答批次：{status.run_id} · 评分批次：{status.score_run_id} · "
                f"计划 {status.total} 项 · 成功 {status.succeeded} 项 · "
                f"失败 {status.failed} 项 · 未完成 {status.pending} 项"
            )

        st.markdown("**结果导出**")
        prepare_disabled = store is None or status is None
        if st.button(
            "准备当前批次导出文件",
            key="test_run_maintenance_prepare_export",
            type="tertiary",
            disabled=prepare_disabled,
        ):
            try:
                answers = store.list_rows("live_run_responses", run_id=status.run_id)
                scores = store.list_rows("live_run_scores", score_run_id=status.score_run_id)
                rows = formal.filter_formal_score_rows(pd.DataFrame(scores), pd.DataFrame(answers))
                payload = sc.build_score_export_payload(rows)
                st.session_state[_MAINTENANCE_EXPORT_KEY] = sc.serialize_score_export_payload(payload)
            except (ResultStoreError, ResultStoreUnavailableError):
                st.session_state.pop(_MAINTENANCE_EXPORT_KEY, None)
                st.warning("当前批次暂时无法导出，请在数据库恢复后重试。")
            else:
                st.rerun()
        export_text = str(st.session_state.get(_MAINTENANCE_EXPORT_KEY) or "")
        if export_text:
            st.download_button(
                "下载评测记录 JSON",
                data=export_text,
                file_name=f"evaluation_records_{_safe_key(getattr(status, 'run_id', 'current'))}.json",
                mime="application/json",
                type="secondary",
                key="test_run_maintenance_download",
            )
        else:
            st.caption("按需准备导出文件，页面打开时不会额外读取全部结果。")

        st.markdown("**结果导入**")
        uploaded = st.file_uploader(
            "上传本项目导出的评测记录 JSON",
            type=["json"],
            key="test_run_maintenance_import_file",
        )
        if uploaded is not None:
            parsed = sc.parse_score_import_content(uploaded.name, uploaded.getvalue())
            errors = list(parsed.get("errors") or [])
            rows = list(parsed.get("rows") or [])
            if errors:
                st.warning("；".join(str(error) for error in errors[:3]))
            elif st.button(
                "导入已校验记录",
                key="test_run_maintenance_import_submit",
                type="secondary",
                disabled=not rows,
            ):
                result = sc.import_score_rows(rows, duplicate_action="skip")
                cd.clear_conclusions_caches()
                st.caption(
                    f"已导入 {int(result.get('imported') or 0)} 条，"
                    f"跳过 {int(result.get('skipped') or 0)} 条。"
                )

        st.markdown("**样本维护**")
        if st.button(
            "前往样本库",
            key="test_run_maintenance_open_samples",
            type="tertiary",
        ):
            st.session_state.current_page = "samples"
            request_scroll("top")
            st.rerun()


def _default_provider_name() -> str:
    return sf.PROVIDER_NAME


def _current_provider_name() -> str:
    current = _default_provider_name()
    st.session_state["test_run_provider"] = current
    return current


def _ensure_default_selected_cases(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    if "test_run_selected_cases" in st.session_state:
        st.session_state["test_run_selected_cases"] = current
        return
    if current:
        st.session_state["test_run_selected_cases"] = current
        return
    default_cases = [
        str(r.get("case_id"))
        for r in er.default_task_selection([item["task"] for item in sample_options])
        if str(r.get("case_id")) in option_ids
    ]
    st.session_state["test_run_selected_cases"] = default_cases[:1] if default_cases else option_ids[:1]


def _selected_tasks_from_state(sample_options: list[dict]) -> list[dict]:
    by_case = {item["case_id"]: item for item in sample_options}
    return [
        by_case[case_id]
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in by_case
    ]


def _selected_model_ids_from_state() -> list[str]:
    return _dedupe(list(st.session_state.get("test_run_selected_models", [])))


def _selected_sample_summary(selected_tasks: list[dict]) -> str:
    if not selected_tasks:
        return "未选择"
    ids = [str(item["case_id"]) for item in selected_tasks[:3]]
    suffix = f" 等 {len(selected_tasks)} 个" if len(selected_tasks) > 3 else ""
    return "、".join(ids) + suffix


def _selected_model_summary(model_ids: list[str]) -> str:
    if not model_ids:
        return "未选择"
    labels = [_model_short_name(model_id) for model_id in model_ids[:2]]
    suffix = f" 等 {len(model_ids)} 个" if len(model_ids) > 2 else f"（{len(model_ids)} 个）"
    return "；".join(labels) + suffix


def _status_row(label: str, value: str, *, warn: bool = False) -> tuple[str, ...]:
    return (label, value, "warning") if warn else (label, value)


def _open_sample_dialog(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    st.session_state["test_run_dialog"] = "samples"
    st.session_state["test_run_cases_dialog_selected"] = current
    st.session_state.pop("test_run_sample_search", None)
    st.session_state.pop("test_run_sample_scenario", None)
    st.session_state.pop("test_run_sample_difficulty", None)
    _clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)


def _open_model_dialog(provider_name: str) -> None:
    st.session_state["test_run_dialog"] = "models"
    st.session_state["test_run_model_dialog_selected"] = _selected_model_ids_from_state()
    st.session_state[_MODEL_DIALOG_TEMPERATURE_KEY] = _current_eval_temperature()


def _open_prompt_preview_dialog(selected_tasks: list[dict]) -> None:
    first = next((item for item in selected_tasks or [] if str(item.get("case_id") or "").strip()), None)
    if first:
        st.session_state["test_run_prompt_preview_case"] = str(first.get("case_id") or "")
    st.session_state["test_run_dialog"] = "prompt_preview"


def _render_pending_dialogs(sample_options: list[dict]) -> None:
    dialog = st.session_state.get("test_run_dialog")
    if dialog == "samples":
        _render_sample_selection_dialog(sample_options)
    elif dialog == "models":
        _render_model_selection_dialog()
    elif dialog == "prompt_preview":
        _render_prompt_preview_dialog(sample_options)


def _clear_dialog_state() -> None:
    st.session_state.pop("test_run_dialog", None)
    st.session_state.pop("test_run_cases_dialog_selected", None)
    st.session_state.pop(_MODEL_DIALOG_TEMPERATURE_KEY, None)
    st.session_state.pop("test_run_prompt_preview_case", None)
    _clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)


@st.dialog("发送给被测模型的提示词", width="large")
def _render_prompt_preview_dialog(sample_options: list[dict]) -> None:
    by_case = {str(item.get("case_id") or ""): item for item in sample_options}
    selected_ids = [
        str(case_id)
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if str(case_id) in by_case
    ]
    preview_ids = selected_ids or list(by_case)
    if not preview_ids:
        st.caption("当前没有可预览的样本。")
        with st.container(key="test_run_prompt_dialog_actions"):
            if st.button(
                "关闭",
                key="test_run_prompt_preview_close_empty",
                type="tertiary",
                use_container_width=True,
            ):
                _clear_dialog_state()
                st.rerun()
        return

    current = str(st.session_state.get("test_run_prompt_preview_case") or "")
    if current not in preview_ids:
        current = preview_ids[0]
    if len(preview_ids) > 1:
        current = st.selectbox(
            "预览样本",
            options=preview_ids,
            index=preview_ids.index(current),
            format_func=lambda case_id: _prompt_preview_case_label(by_case.get(case_id, {})),
            key="test_run_prompt_preview_case_select",
        )
    st.session_state["test_run_prompt_preview_case"] = current

    with st.spinner("正在准备提示词…"):
        task = prompt_preview_task_for_case(sample_options, selected_ids, current)
        messages = er.build_messages(task)
    st.caption("以下为被测模型实际收到的全部内容，不包含专业标准答案、必须覆盖点、不可接受错误或评分标准。")
    for message in messages:
        role = str(message.get("role") or "")
        label = "系统提示词" if role == "system" else "用户提示词"
        height = 210 if role == "system" else 340
        st.text_area(
            label,
            value=str(message.get("content") or ""),
            height=height,
            disabled=True,
            key=f"test_run_prompt_preview_{role}",
        )
    with st.container(key="test_run_prompt_dialog_actions"):
        if st.button(
            "关闭",
            key="test_run_prompt_preview_close",
            type="tertiary",
            use_container_width=True,
        ):
            _clear_dialog_state()
            st.rerun()


def _prompt_preview_case_label(item: dict) -> str:
    case_id = str(item.get("case_id") or "")
    title = str(item.get("title") or "样本任务")
    return f"{case_id}｜{title}"


@st.dialog("选择样本", width="large")
def _render_sample_selection_dialog(sample_options: list[dict]) -> None:
    if not sample_options:
        st.warning(NO_TESTABLE_SAMPLE_MESSAGE)
        with st.container(key="test_run_sample_dialog_actions"):
            if st.button(
                "关闭",
                key="test_run_sample_dialog_close",
                type="tertiary",
                use_container_width=True,
            ):
                _clear_dialog_state()
                st.rerun()
        return

    by_case = {item["case_id"]: item for item in sample_options}
    all_case_ids = set(by_case)
    selected_cases = [
        case_id
        for case_id in st.session_state.get("test_run_cases_dialog_selected", [])
        if case_id in all_case_ids
    ]
    st.session_state["test_run_cases_dialog_selected"] = selected_cases

    scenes = ["全部"] + sorted({
        str(item.get("scenario") or "")
        for item in sample_options
        if str(item.get("scenario") or "").strip() and str(item.get("scenario") or "") != "—"
    })
    difficulties = ["全部"] + sorted({
        str(item.get("difficulty") or "")
        for item in sample_options
        if str(item.get("difficulty") or "").strip() and str(item.get("difficulty") or "") != "—"
    })

    filter_cols = st.columns([2.2, 1, 1])
    with filter_cols[0]:
        keyword = st.text_input(
            "关键词搜索",
            key="test_run_sample_search",
            placeholder="输入样本编号、标题或背景关键词",
        )
    with filter_cols[1]:
        scenario = st.selectbox("场景", scenes, key="test_run_sample_scenario")
    with filter_cols[2]:
        difficulty = st.selectbox("难度", difficulties, key="test_run_sample_difficulty")

    filtered_options = filter_sample_selection_options(sample_options, keyword, scenario, difficulty)
    bulk_cols = st.columns([0.72, 0.48, 3.8])
    with bulk_cols[0]:
        if st.button(
            "全选当前筛选结果",
            key="test_run_sample_select_filtered",
            type="tertiary",
            disabled=not filtered_options,
        ):
            merged = _dedupe(list(selected_cases) + [item["case_id"] for item in filtered_options])
            st.session_state["test_run_cases_dialog_selected"] = merged
            for item in filtered_options:
                st.session_state[sample_checkbox_key(item["case_id"])] = True
            st.rerun()
    with bulk_cols[1]:
        if st.button(
            "清空",
            key="test_run_sample_clear_selected",
            type="tertiary",
            disabled=not selected_cases,
        ):
            st.session_state["test_run_cases_dialog_selected"] = []
            for case_id in all_case_ids:
                st.session_state[sample_checkbox_key(case_id)] = False
            st.rerun()
    checkbox_values: dict[str, bool] = {}
    if not filtered_options:
        st.caption("当前没有符合条件的可测样本。")
    else:
        checkbox_values = _render_sample_checkbox_table(filtered_options, selected_cases)

    selected_cases = merge_sample_checkbox_selection(
        selected_cases,
        filtered_options,
        checkbox_values,
        all_case_ids,
    )
    st.session_state["test_run_cases_dialog_selected"] = selected_cases
    st.caption(
        f"已选样本：{len(selected_cases)} 个。仅展示已入库且通过完整度校验的样本；"
        "被测模型不会看到专业标准答案或评分标准。"
    )
    with st.container(key="test_run_sample_dialog_actions"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "确认选择",
                key="test_run_sample_dialog_confirm",
                type="primary",
                disabled=not selected_cases,
                use_container_width=True,
            ):
                st.session_state["test_run_selected_cases"] = selected_cases
                _clear_dialog_state()
                st.rerun()
        with col2:
            if st.button("取消", key="test_run_sample_dialog_cancel", type="tertiary", use_container_width=True):
                _clear_dialog_state()
                st.rerun()


def _render_sample_checkbox_table(sample_options: list[dict], selected_cases: list[str]) -> dict[str, bool]:
    rows = build_sample_selection_rows(sample_options, selected_cases)
    selected_set = set(selected_cases or [])
    checkbox_values: dict[str, bool] = {}

    with st.container(
        height=SAMPLE_TABLE_HEIGHT,
        border=True,
        key="test_run_sample_table",
    ):
        with st.container(key="test_run_sample_table_header"):
            header_cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
            for col, header in zip(header_cols, SAMPLE_TABLE_HEADERS, strict=True):
                with col:
                    st.markdown(f"**{header}**")
            st.markdown(
                "<div style='border-top: 1px solid #E5E7EB; margin: 0.12rem 0 0.2rem 0;'></div>",
                unsafe_allow_html=True,
            )

        for row in rows:
            case_id = str(row["样本编号"])
            key = sample_checkbox_key(case_id)
            if key not in st.session_state:
                st.session_state[key] = case_id in selected_set

            with st.container(key=f"test_run_sample_row_{_safe_key(case_id)}"):
                cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
                with cols[0]:
                    checkbox_values[case_id] = bool(st.checkbox(
                        "选择",
                        key=key,
                        label_visibility="collapsed",
                    ))
                with cols[1]:
                    _render_sample_table_cell(case_id)
                with cols[2]:
                    _render_sample_table_cell(str(row["任务标题"]))
                with cols[3]:
                    _render_sample_table_cell(str(row["场景"]))
                with cols[4]:
                    _render_sample_table_cell(str(row["难度"]))
                with cols[5]:
                    _render_sample_table_cell(str(row["测试状态"]))

    return checkbox_values


def _render_sample_table_cell(value: str) -> None:
    st.markdown(
        "<div style='font-size: 0.9rem; line-height: 1.35; padding: 0.24rem 0; "
        f"color: #2F3947; overflow-wrap: anywhere;'>{escape(value)}</div>",
        unsafe_allow_html=True,
    )


@st.dialog("选择模型", width="large")
def _render_model_selection_dialog() -> None:
    provider = sf.SiliconFlowProvider()
    st.markdown(f"**模型服务：** {_SILICONFLOW_LABEL}")
    balance_text = _siliconflow_balance_text(provider)
    if balance_text:
        st.caption(f"账户余额：{balance_text}")
    if not sf.is_configured():
        st.warning("当前未配置模型服务密钥，暂不能发起真实调用。")
    if _MODEL_DIALOG_TEMPERATURE_KEY not in st.session_state:
        st.session_state[_MODEL_DIALOG_TEMPERATURE_KEY] = _current_eval_temperature()
    st.markdown("**回答设置**")
    st.slider(
        "回答随机性",
        min_value=0.0,
        max_value=1.0,
        step=0.1,
        key=_MODEL_DIALOG_TEMPERATURE_KEY,
        help="同一批评测内所有被测模型使用相同设置；裁判评分固定为 0.0。",
    )
    st.caption("所有被测模型使用相同回答随机性，便于横向比较。")

    with st.spinner("正在获取模型列表…"):
        result = provider.list_models()
    available_models = list(result.models) if result.ok else []
    model_options = [str(model.id) for model in available_models if str(model.id).strip()]
    st.markdown("**可用模型**")
    if model_options:
        search_keyword = st.text_input(
            "搜索模型",
            key="test_run_model_search",
            placeholder="输入模型名称、厂商或关键词",
        )
        visible_options, matched_count = build_model_selection_options(
            available_models, search_keyword, _MODEL_OPTION_LIMIT,
        )
        if matched_count > _MODEL_OPTION_LIMIT:
            st.caption(f"共匹配 {matched_count} 个模型，显示前 {len(visible_options)} 个；输入关键词可缩小范围。")
        if visible_options:
            if st.session_state.get("test_run_model_select") not in visible_options:
                st.session_state["test_run_model_select"] = visible_options[0]
            st.selectbox("模型", visible_options, key="test_run_model_select")
        else:
            st.caption("没有符合当前关键词的模型。")
        if st.button(
            "添加到对比列表",
            key="test_run_add_model",
            type="secondary",
            disabled=not visible_options,
        ):
            selected = str(st.session_state.get("test_run_model_select") or "").strip()
            current = _dedupe(list(st.session_state.get("test_run_model_dialog_selected", [])))
            if selected and selected in visible_options and selected not in current:
                current.append(selected)
            st.session_state["test_run_model_dialog_selected"] = current
            st.rerun()
    else:
        st.caption("模型列表暂未获取，请检查模型服务配置。")

    chosen_models = _dedupe([
        model
        for model in st.session_state.get("test_run_model_dialog_selected", [])
        if model in model_options
    ])
    st.session_state["test_run_model_dialog_selected"] = chosen_models
    st.markdown("**已选模型**")
    if chosen_models:
        for index, model_id in enumerate(chosen_models):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"- {_model_short_name(model_id)}")
                if _model_short_name(model_id) != model_id:
                    st.caption(f"模型 ID：{model_id}")
            with col2:
                if st.button("移除", key=f"test_run_remove_model_{index}", type="tertiary", use_container_width=True):
                    st.session_state["test_run_model_dialog_selected"] = [
                        item for item in chosen_models if item != model_id
                    ]
                    st.rerun()
    st.caption(f"已选模型：{len(chosen_models)} 个")
    with st.container(key="test_run_model_dialog_actions"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "确认选择",
                key="test_run_model_dialog_confirm",
                type="primary",
                disabled=not chosen_models,
                use_container_width=True,
            ):
                st.session_state["test_run_provider"] = sf.PROVIDER_NAME
                st.session_state["test_run_selected_models"] = chosen_models
                st.session_state[_EVAL_TEMPERATURE_KEY] = _normalize_eval_temperature(
                    st.session_state.get(_MODEL_DIALOG_TEMPERATURE_KEY)
                )
                _clear_dialog_state()
                st.rerun()
        with col2:
            if st.button("取消", key="test_run_model_dialog_cancel", type="tertiary", use_container_width=True):
                _clear_dialog_state()
                st.rerun()


def _siliconflow_balance_text(provider: sf.SiliconFlowProvider) -> str | None:
    try:
        balance = provider.get_balance()
    except Exception:
        balance = None
    if balance is None:
        return None
    if isinstance(balance, (int, float)):
        return f"¥{balance:.2f}"
    text = str(balance).strip()
    return text or None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _model_short_name(model_id: str) -> str:
    return md.display_model_name(model_id)


def _safe_key(value) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return text[:80] or "item"
