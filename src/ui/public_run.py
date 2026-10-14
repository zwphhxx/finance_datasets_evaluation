"""Real anonymous evaluation only after an explicit, budgeted start click."""

from __future__ import annotations

import secrets

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.persistence import PersistenceConfigurationError, ResultStoreError
from app.services import public_run as service
from app.services.evaluation_workflow import INTERRUPTED, STOPPED, WorkflowCheckpointError, WorkflowStopped
from app.services.model_display import display_model_name
from app.services.public_preflight import check_run_configuration
from app.services.score_recovery import linked_retry_runs, retry_options, run_score_retry
from src.ui import conclusions_data as cd
from src.ui.evaluation_feedback import pair_rows, safe_attempt_details
from src.ui.review import open_case_review


def _forget_job():
    st.session_state.pop("public_live_job", None)
    st.session_state.pop("public_result_record", None)
    st.session_state.pop("public_run_pending_confirmation", None)
    st.session_state.pop("public_pending_score_retry", None)
    for field in ("public_job", "public_ticket"):
        st.query_params.pop(field, None)


def _remember_job(job, owner):
    st.session_state.public_live_job = {"job_id": job["job_id"], "owner": owner}
    st.query_params.update(public_job=job["job_id"], public_ticket=owner)


def _execute(base, cases, models, *, owner, job_id=None):
    progress = None
    try:
        with st.status("正在生成回答并自动评分，请保留此页面。", expanded=True) as progress:
            _, status = service.run_public_evaluation(
                base,
                cases,
                models,
                owner=owner,
                job_id=job_id,
                temperature=st.session_state.get("preview_temperature", 0.0),
                max_tokens=st.session_state.get("preview_max_tokens", 4096),
                on_reserved=lambda job: _remember_job(job, owner),
                on_event=lambda case, model, phase: progress.update(
                    label=case
                    + " · "
                    + display_model_name(model, source="live")
                    + ("：正在生成回答" if phase == "answer" else "：正在AI评分")
                ),
            )
            progress.update(
                label="本批次已结束，包含失败任务" if status.failed else "回答与AI评分已完成",
                state="error" if status.failed else "complete",
                expanded=False,
            )
        cd.clear_conclusions_caches()
        st.rerun()
    except PermissionError as exc:
        if progress is not None:
            progress.update(label="评测未启动或已停止", state="error", expanded=False)
        st.warning(str(exc))
    except (
        PersistenceConfigurationError,
        ResultStoreError,
        SQLAlchemyError,
        WorkflowStopped,
        WorkflowCheckpointError,
        ValueError,
    ):
        if progress is not None:
            progress.update(label="评测已停止", state="error", expanded=False)
        st.error("评测未完成：服务或结果保存不可用，已停止进一步调用。已保存记录可查看；中断任务可稍后继续。")
        cd.clear_conclusions_caches()


def _dismiss_confirmation():
    st.session_state.pop("public_run_pending_confirmation", None)


def _dismiss_retry():
    st.session_state.pop("public_pending_score_retry", None)


@st.dialog("运行前确认", width="medium", on_dismiss=_dismiss_confirmation)
def _confirmation_dialog(base, cases, models, report):
    st.markdown(f"**{len(cases)}个样本 × {len(models)}个模型 = {report['task_count']}个回答任务**")
    st.write("样本：" + "、".join(cases))
    st.write("被评测模型：" + "、".join(display_model_name(m, source="live") for m in models))
    st.write("评分模型：" + display_model_name(report["judge"], source="live"))
    quota = report.get("quota") or {}
    st.caption(
        f"全站今日剩余{quota.get('tasks_remaining', '未知')}个任务、{quota.get('calls_remaining', '未知')}次请求；每对最多5次请求，评分最多3次尝试。"
    )
    st.caption(f"评分单次等待上限{report.get('judge_timeout', '未知')}秒。新评测使用当前题库及标准。")
    st.warning("确认后将使用网站密钥生成回答并进行AI评分，可能产生费用。重试也占用额度；不估算未经确认的金额。")
    if st.button("确认并开始评测", key="public_start_evaluation", type="primary", width="stretch"):
        st.session_state.pop("public_run_pending_confirmation", None)
        _execute(base, cases, models, owner=secrets.token_hex(32))
    if st.button("返回调整", key="public_cancel_confirmation", width="stretch"):
        st.session_state.pop("public_run_pending_confirmation", None)
        st.rerun()


def render_start_action(base, cases, models):
    count = len(cases) * len(models)
    limit = service.daily_limit()
    configured = service.sf.is_configured()
    disabled = not service.enabled() or not configured or not 0 < count <= limit
    st.caption(f"网站密钥 · 全站每日（UTC）最多{limit}个任务，每对最多5次请求。失败不退还预占额度。")
    if st.button(
        "检查并查看运行前确认 →", key="public_prepare_evaluation", type="primary", disabled=disabled, width="stretch"
    ):
        with st.spinner("正在检查配置、存储、额度和免费模型目录…"):
            report = check_run_configuration(
                base,
                cases,
                models,
                temperature=st.session_state.get("preview_temperature", 0.0),
                max_tokens=st.session_state.get("preview_max_tokens", 4096),
                check_catalogue=True,
            )
        if report["ready"]:
            st.session_state.public_run_pending_confirmation = {
                "cases": cases,
                "models": models,
                "report": report,
                "temperature": st.session_state.get("preview_temperature", 0.0),
                "max_tokens": st.session_state.get("preview_max_tokens", 4096),
            }
        else:
            for error in report["errors"]:
                st.warning(error)
    pending = st.session_state.get("public_run_pending_confirmation")
    if pending:
        if (
            pending["cases"] == cases
            and pending["models"] == models
            and pending["temperature"] == st.session_state.get("preview_temperature", 0.0)
            and pending["max_tokens"] == st.session_state.get("preview_max_tokens", 4096)
        ):
            _confirmation_dialog(base, cases, models, pending["report"])
        else:
            st.session_state.pop("public_run_pending_confirmation", None)
    if not configured:
        st.caption("网站未配置模型服务密钥，真实调用暂不可用；仍可查看历史结果。")
    elif not service.enabled():
        st.caption("网站已暂停公开真实评测，仍可查看历史结果。")
    elif count > limit:
        st.warning(f"当前选择共{count}个任务，请减少到{limit}个以内。")


@st.dialog("只重试AI评分", width="medium", on_dismiss=_dismiss_retry)
def _retry_dialog(job_id, owner, option):
    case, model = option["pair"]
    st.markdown(f"**{case} · {display_model_name(model, source='live')}**")
    st.write("复用已保存的原始回答与当次专业标准，只新增评分记录；原失败记录保留。")
    st.write("评分模型：" + display_model_name(option["judge"], source="live"))
    attempts = min(3, option["remaining"])
    st.caption(f"该任务剩余{option['remaining']}次请求，最多尝试{attempts}次；失败停止，不重置额度。")
    st.warning("确认后会调用裁判模型，可能产生费用；不会重新生成模型回答。")
    if st.button("确认并重试AI评分", key="public_confirm_score_retry", type="primary", width="stretch"):
        st.session_state.pop("public_pending_score_retry", None)
        try:
            with st.status("正在AI评分，复用原回答", expanded=True) as progress:
                _, status = run_score_retry(
                    job_id,
                    owner,
                    option["pair"],
                    on_event=lambda case, model, phase: progress.update(label=case + "：正在AI评分"),
                )
                progress.update(
                    label="AI评分完成" if status.succeeded else "AI评分未完成",
                    state="complete" if status.succeeded else "error",
                )
            cd.clear_conclusions_caches()
            st.rerun()
        except (PermissionError, ValueError) as exc:
            st.warning(str(exc))
        except (ResultStoreError, SQLAlchemyError, WorkflowStopped):
            st.error("评分已停止，原回答与已保存记录仍保留。请查看状态后处理。")
    if st.button("返回", key="public_cancel_score_retry", width="stretch"):
        st.session_state.pop("public_pending_score_retry", None)
        st.rerun()


def _open_result(row):
    # Shareable case URLs do not carry the private resume capability.
    for field in ("public_job", "public_ticket"):
        st.query_params.pop(field, None)
    open_case_review(str(row["case_id"]), str(row["eval_model"]), str(row["run_id"]), str(row["score_run_id"]))
    st.query_params["origin"] = "evaluation_preview"


def render_owned_job(base):
    saved = st.session_state.get("public_live_job") or {}
    job_id = st.query_params.get("public_job") or saved.get("job_id")
    owner = st.query_params.get("public_ticket") or saved.get("owner")
    if not job_id and not owner:
        return False
    try:
        job, status, store = service.read_public_job(job_id, owner)
    except PermissionError as exc:
        st.warning(str(exc))
        st.button("重新选择评测", key="public_reset_job", on_click=_forget_job)
        return True
    except (ResultStoreError, SQLAlchemyError, ValueError):
        st.warning("本次任务暂不可读取，未发起模型调用。请稍后刷新。")
        st.button("重新选择评测", key="public_reset_job", on_click=_forget_job)
        return True
    _remember_job(job, owner)
    st.subheader("本次评测")
    if status:
        answers = store.list_rows("live_run_responses", run_id=job["run_id"])
        scores = store.list_rows("live_run_scores", run_id=job["run_id"])
        attempts = store.list_rows("request_attempts", run_id=job["run_id"])
        for child in linked_retry_runs(store, job["run_id"]):
            scores.extend(store.list_rows("live_run_scores", run_id=child["run_id"]))
            attempts.extend(store.list_rows("request_attempts", run_id=child["run_id"]))
        records = pair_rows(answers, scores)
        answer_count = sum(r.get("run_status") == "success" for r in answers)
        score_count = sum(r["评分状态"] == "成功" for r in records)
        st.markdown(f"**共{status.total}个任务 · 回答已保存{answer_count} · 评分完成{score_count}**")
        if records:
            st.dataframe(
                [{k: v for k, v in r.items() if k != "_score"} for r in records], hide_index=True, width="stretch"
            )
        failed = [r for r in records if r["_score"] and r["_score"].get("judge_status") == "failed"]
        if failed:
            st.warning("模型回答已生成并保存，但AI评分未完成。原回答仍可查看，失败评分不计入有效结果。")
            options = retry_options(job_id, owner)
            usable = [r for r in options if r["eligible"]]
            if usable:
                selected = st.selectbox(
                    "选择要重新评分的回答",
                    range(len(usable)),
                    format_func=lambda i: usable[i]["pair"][0]
                    + " · "
                    + display_model_name(usable[i]["pair"][1], source="live"),
                    key="public_retry_pair",
                )
                if st.button(
                    "重新尝试AI评分",
                    key="public_prepare_score_retry",
                    type="primary",
                    disabled=not service.enabled() or not service.sf.is_configured(),
                ):
                    st.session_state.public_pending_score_retry = {"job_id": job_id, "option": usable[selected]}
                pending_retry = st.session_state.get("public_pending_score_retry")
                if pending_retry and pending_retry["job_id"] == job_id:
                    _retry_dialog(job_id, owner, pending_retry["option"])
            else:
                for reason in dict.fromkeys(o["reason"] for o in options):
                    st.caption("无法自动重评分：" + reason)
        if scores:
            by_id = {(r["case_id"], r["eval_model"], r["score_run_id"]): r for r in scores}
            selected = st.selectbox(
                "查看本次案例",
                list(by_id),
                format_func=lambda k: k[0]
                + " · "
                + display_model_name(k[1], source="live")
                + " · "
                + (
                    "AI评分 " + str(by_id[k].get("total_score"))
                    if by_id[k].get("judge_status") == "success"
                    else "评分未完成"
                ),
                key="public_result_record",
            )
            st.button(
                "查看完整案例 →",
                key="public_open_result",
                type="secondary" if failed else "primary",
                on_click=_open_result,
                args=(by_id[selected],),
            )
        if status.pending and status.state in {INTERRUPTED, STOPPED}:
            if st.button(
                "继续本次评测",
                key="public_continue_evaluation",
                type="primary",
                disabled=not service.enabled() or not service.sf.is_configured(),
            ):
                _execute(base, [], [], owner=owner, job_id=job_id)
        elif status.pending:
            st.info("任务正在运行或等待恢复。请勿重复启动；中断后可稍后刷新继续。")
        with st.expander("运行诊断与请求尝试"):
            st.caption("历史未记录的字段保持缺失；超时不能仅凭日志归因于模型内部计算。")
            if attempts:
                st.dataframe(safe_attempt_details(attempts), hide_index=True, width="stretch")
            st.caption("运行批次：" + str(job["run_id"]))
    else:
        st.warning("额度已预占，但尚未建立运行批次。没有可回放的结果；重新启动会使用新的额度。")
    st.caption("当前链接包含本次任务恢复凭证，请勿分享；可分享完整案例链接。")
    st.button("新建一批评测", key="public_new_batch", on_click=_forget_job, type="secondary")
    return True
