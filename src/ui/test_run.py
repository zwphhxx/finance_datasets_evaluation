"""评测操作页：一次启动或一次续跑，回答与评分作为同一持久化流程。"""

from __future__ import annotations

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
from src.ui import evaluation_config as ec
from src.ui.components import (
    render_empty_state,
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

_SILICONFLOW_LABEL = "硅基流动"
_JUDGE_TEMPERATURE = 0.0
_JUDGE_MAX_TOKENS = 2048
_MAINTENANCE_EXPORT_KEY = "test_run_maintenance_export"

# Compatibility re-exports for callers of the former configuration module surface.
resolve_eval_max_tokens = ec.resolve_eval_max_tokens
resolve_eval_temperature = ec.resolve_eval_temperature
filter_sample_selection_options = ec.filter_sample_selection_options
build_sample_selection_rows = ec.build_sample_selection_rows
sample_checkbox_key = ec.sample_checkbox_key
merge_sample_checkbox_selection = ec.merge_sample_checkbox_selection
build_model_selection_options = ec.build_model_selection_options
prompt_preview_task_for_case = ec.prompt_preview_task_for_case

def _persistence_gate(result: bool) -> None:
    if not result:
        raise RuntimeError("runtime persistence required")


def _require_persistence_preflight(store, provider_name: str) -> None:
    from app.persistence import (
        ResultStoreSettings,
        ResultStoreUnavailableError,
        require_durable_live_store,
    )

    settings = ResultStoreSettings(url="", is_postgresql=store.is_postgresql)
    require_durable_live_store(provider_name, settings)
    if not store.ping():
        raise ResultStoreUnavailableError(
            "评测结果数据库暂不可用，已停止模型调用。"
        )


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
    ec.ensure_default_selected_cases(sample_options)
    provider_name = ec.current_provider_name(sf.PROVIDER_NAME)
    selected_tasks = ec.selected_tasks_from_state(sample_options)
    model_ids = ec.selected_model_ids_from_state()
    run_plan = build_run_plan_summary(model_ids, selected_tasks)

    ec.render_evaluation_scope(
        sample_options,
        selected_tasks,
        model_ids,
        run_plan,
        provider_name=provider_name,
    )

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
            if latest_rows:
                latest_run_id = str(latest_rows[0].get("run_id") or "").strip()
                metadata_rows = (
                    result_store.list_rows("live_evaluation_runs", run_id=latest_run_id)
                    if latest_run_id
                    else []
                )
                metadata = metadata_rows[0] if len(metadata_rows) == 1 else None
                if metadata is not None and formal.formal_recovery_run_eligible(
                    metadata, latest_rows
                ):
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
                require_preflight(result_store, provider_name)
                evaluation_config = build_new_config(base, selected_tasks, model_ids)
                workflow = build_workflow(result_store)
                workflow.start_evaluation(evaluation_config)
            except WorkflowStopped as exc:
                cd.clear_conclusions_caches()
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except (
                PersistenceConfigurationError,
                ResultStoreUnavailableError,
                ResultStoreError,
            ) as exc:
                cd.clear_conclusions_caches()
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except WorkflowCheckpointError as exc:
                cd.clear_conclusions_caches()
                render_persistence_status(str(exc) or "评测配置无法通过一致性校验。")
            else:
                cd.clear_conclusions_caches()
                st.rerun()
    elif status is not None and status.state == INTERRUPTED:
        checkpoint_config = None
        try:
            checkpoint_config = rebuild_checkpoint(status.run_id, base, store=result_store)
        except (ResultStoreError, ResultStoreUnavailableError):
            store_available = False
            render_persistence_status(
                "评测结果数据库暂不可用，已禁用继续评测。请在数据库恢复后重试。"
            )
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
                require_preflight(result_store, provider_name)
                workflow = build_workflow(result_store)
                workflow.continue_evaluation(status.run_id, checkpoint_config)
            except WorkflowStopped as exc:
                cd.clear_conclusions_caches()
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except (
                PersistenceConfigurationError,
                ResultStoreUnavailableError,
                ResultStoreError,
            ) as exc:
                cd.clear_conclusions_caches()
                display_status = stopped_status(
                    str(exc) or "评测已停止，未继续调用模型服务。"
                )
            except WorkflowCheckpointError as exc:
                cd.clear_conclusions_caches()
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
    dialog_name = ec.pending_dialog_name()
    model_provider = None
    if dialog_name == "models" and store_available and sf.is_configured():
        try:
            require_preflight(result_store, provider_name)
        except (
            PersistenceConfigurationError,
            ResultStoreUnavailableError,
            ResultStoreError,
        ):
            store_available = False
            render_persistence_status(
                "评测结果数据库暂不可用，模型列表暂不可读取。请在数据库恢复后重试。"
            )
        else:
            model_provider = sf.SiliconFlowProvider()
    ec.render_pending_dialogs(
        sample_options,
        provider_name=provider_name,
        provider_label=_SILICONFLOW_LABEL,
        provider_configured=sf.is_configured(),
        model_provider=model_provider,
    )


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
        generation_parameters={
            "temperature": ec.current_eval_temperature(),
            "max_tokens": ec.EVAL_MAX_TOKENS,
        },
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
    with st.container(key="test_run_maintenance_entry"):
        maintenance_popover = st.popover("评测维护", type="tertiary")
    with maintenance_popover:
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
                result = sc.import_score_rows(
                    rows,
                    duplicate_action="skip",
                    result_store=store,
                )
                cd.clear_conclusions_caches()
                st.caption(
                    f"已导入 {int(result.get('imported_count') or 0)} 条，"
                    f"跳过 {int(result.get('skipped_count') or 0)} 条。"
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

def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _safe_key(value) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return text[:80] or "item"
