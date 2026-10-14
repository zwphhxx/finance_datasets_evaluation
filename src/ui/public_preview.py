"""Public configuration and history; only explicit actions may start a bounded run."""

from __future__ import annotations

import streamlit as st

from app.access import management_enabled
from app.services import dataset_service as ds
from app.services.formal_records import formal_recovery_run_eligible, is_non_formal_runtime_record
from app.services.model_display import display_model_name
from app.services.snapshot import _safe
from src.ui import workbench
from src.ui.components import render_html
from src.ui.evaluation_config import build_run_plan_summary, build_sample_options
from src.ui.evaluation_feedback import failure_label, pair_rows, safe_attempt_details
from src.ui.labels import DOMAIN_LABELS, display_label
from src.ui.portfolio import _render_task, _tasks
from src.ui.review import ROUTE_FIELDS, _record_identity, _review_records, open_case_review
from src.ui.samples import PROFESSIONAL_SCENE_OPTIONS, _build_gold_answer_json, _domain_from_professional_scene
from src.ui.scroll import request_scroll
from src.ui.trust_details import render_reference_standard

STAGES = {"config": "配置评测", "history": "历史运行", "results": "查看结果"}


def _remember_config():
    st.session_state["public_preview_config"] = {
        name: st.session_state["preview_" + name]
        for name in ("models", "cases", "temperature", "max_tokens")
        if "preview_" + name in st.session_state
    }


def _change_stage():
    stage = next(k for k, v in STAGES.items() if v == st.session_state.preview_stage)
    st.query_params["stage"] = stage
    request_scroll("top")


def render_evaluation_preview(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    with st.container(key="portfolio_preview"):
        st.title("在线评测")
        st.caption("选择专业任务和模型，核对配置与额度后再确认真实调用。浏览与切换不产生模型费用。")
        stage = st.query_params.get("stage", "config")
        if stage not in STAGES:
            stage = "config"
        st.session_state.preview_stage = STAGES[stage]
        source = workbench.load_workbench_source(base)
        report = source.report if source.available else None
        if stage == "config":
            render_html(
                '<div class="evaluation-flow" aria-label="评测步骤"><span>选择任务与模型</span><span>调用前确认</span><span>生成回答 → AI评分</span><span>查看证据</span></div>'
            )
            from src.ui.public_run import render_owned_job

            if not render_owned_job(base):
                _render_config(base, report)
        else:
            st.button("← 返回在线评测", key="preview_to_config", type="tertiary", on_click=_go_config)
            _render_history(report, results=stage == "results")


def _go_config():
    st.session_state.preview_stage = STAGES["config"]
    st.query_params["stage"] = "config"
    request_scroll("top")


def _render_config(base, report):
    with st.container(key="public_run_config"):
        left, right = st.columns([1.1, 0.9], gap="medium")
        with left, st.container(border=True, key="public_run_selection"):
            st.subheader("配置本次评测")
            _render_config_fields(base, report)
        with right, st.container(border=True, key="public_run_rules"):
            st.subheader("运行前需要明确的事")
            st.markdown("**本次使用当前题库及专业标准**")
            st.write("被评测模型只看到业务材料与任务要求；裁判依据当次专业标准和五个维度评分。")
            st.markdown("**确认后才开始真实调用**")
            st.write(
                "检查将读取数据库权限、剩余额度与免费模型目录，不生成回答。确认后生成回答并进行AI评分，重试也计入请求额度。"
            )
            st.markdown("**回答与评分分开保存**")
            st.write("评分失败时保留已生成回答。符合归属、当次材料与剩余预算条件时，可只重试AI评分。")
            st.caption("历史结果与新评测分离，不用当前题库补造历史证据。")


def _render_config_fields(base, report):
    tasks = _tasks(base)
    gold = getattr(base, "gold_answer_map", {}) or {}
    dimensions = ds.get_testable_rubric_dimensions()
    options = build_sample_options(
        tasks,
        gold,
        dimensions,
        title_map={
            str(t["case_id"]): str(t.get("title") or t.get("scenario") or t.get("question") or t["case_id"])
            for t in tasks
        },
    )
    cases = {str(r["case_id"]): r for r in options}
    models = sorted(set(str(r["eval_model"]) for r in _review_records(report)[0]))
    saved = st.session_state.get("public_preview_config", {})
    names = [display_model_name(m, source="live") for m in models]

    def model_label(model):
        label = display_model_name(model, source="live")
        return label + " · " + model if names.count(label) > 1 else label

    chosen_models = st.multiselect(
        "被评测模型",
        models,
        default=[m for m in saved.get("models", models[:2]) if m in models],
        format_func=model_label,
        key="preview_models",
        on_change=_remember_config,
    )
    st.caption("选项来自正式历史测试；当前可用性由模型服务返回。")
    chosen_cases = st.multiselect(
        "专业样本",
        list(cases),
        default=[c for c in saved.get("cases", ["FD-001"] if "FD-001" in cases else list(cases)[:1]) if c in cases],
        format_func=lambda c: c + " · " + str(cases[c]["title"]).split("——", 1)[-1],
        key="preview_cases",
        on_change=_remember_config,
    )
    if not cases:
        st.caption("当前没有通过既有完整度检查的样本；可在样本与标准查看任务。")
    st.caption("修改配置不会重算历史结果。")
    if "preview_max_tokens" in st.session_state and not 128 <= int(st.session_state.preview_max_tokens) <= 4096:
        saved = dict(saved, max_tokens=max(128, min(4096, int(st.session_state.pop("preview_max_tokens")))))
    with st.expander("生成参数与评分标准"):
        st.number_input(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=float(saved.get("temperature", 0.0)),
            step=0.1,
            key="preview_temperature",
            on_change=_remember_config,
        )
        st.number_input(
            "最大输出 Token",
            min_value=128,
            max_value=4096,
            value=max(128, min(4096, int(saved.get("max_tokens", 4096)))),
            step=128,
            key="preview_max_tokens",
            on_change=_remember_config,
        )
        if dimensions:
            st.dataframe(
                _safe([{"评分维度": d.get("name") or d.get("field"), "满分": d.get("full_mark")} for d in dimensions]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("当前评分维度未配置。")
        st.caption("模型作答后由裁判按专业标准评分，再核对评价点与原文证据。")
        st.caption("回答最多4096 Token；裁判最多3072 Token。")
    _remember_config()
    plan = build_run_plan_summary(chosen_models, [cases[c] for c in chosen_cases])
    st.markdown(
        f"**{plan['sample_count']}个样本 × {plan['model_count']}个模型 = {plan['planned_responses']}个回答任务**"
    )
    from src.ui.public_run import render_start_action

    render_start_action(base, chosen_cases, chosen_models)
    st.button("查看真实历史运行 →", key="preview_to_history", type="secondary", on_click=_go_history)


def _go_history():
    st.session_state.preview_stage = STAGES["history"]
    st.query_params["stage"] = "history"
    request_scroll("top")


def _open_record(row):
    # Callbacks can run before the page has rebound row after a selection change.
    selected = st.session_state.get("preview_history_record")
    if selected is None:
        selected = _record_identity(row) + (str(row["case_id"]),)
    run, model, score, case = selected
    if run != st.session_state.get("preview_history_run", run):
        st.warning("历史批次已切换，请重新选择评分记录。")
        return
    st.session_state["public_preview_record"] = (run, model, score, case)
    open_case_review(case, model, run, score)
    st.query_params["origin"] = "evaluation_preview"


def _remember_run():
    for field in ROUTE_FIELDS:
        st.query_params.pop(field, None)
    selected = st.session_state.get("preview_history_run")
    if selected:
        st.query_params["history"] = selected
        st.session_state["public_preview_run"] = selected


def _render_history(report, *, results):
    records, responses = _review_records(report)
    if report:
        from src.ui.conclusions import _formal_response_for_score

        records = records + [
            r
            for r in report.runtime_tables.get("live_run_scores", [])
            if r.get("judge_status") == "failed"
            and not is_non_formal_runtime_record(r)
            and _formal_response_for_score(responses, r)
        ]
    runs = report.runtime_tables.get("live_evaluation_runs", []) if report else []
    runs = [
        r
        for r in runs
        if formal_recovery_run_eligible(
            r, [q for q in report.runtime_tables.get("live_run_queue", []) if str(q.get("run_id")) == str(r["run_id"])]
        )
    ]
    if not runs:
        st.info("暂无可读取的正式历史运行。可先配置评测或查看样本，不展示模拟结果。")
        return
    by_run = {str(r["run_id"]): r for r in runs}
    labels = {}
    for run in by_run:
        row = by_run[run]
        models = sorted(
            {display_model_name(str(r["eval_model"]), source="live") for r in records if str(r["run_id"]) == run}
        )
        if not models:
            models = sorted(
                {
                    display_model_name(str(q.get("model_id") or q.get("model_name")), source="live")
                    for q in report.runtime_tables.get("live_run_queue", [])
                    if str(q.get("run_id")) == run
                }
            )
        labels[run] = str(row.get("created_at") or "日期未记录")[:10] + " · " + ("、".join(models) or "模型未记录")
    names = list(labels.values())
    labels = {
        run: str(
            _safe(
                label + " · " + str(by_run[run].get("provider") or "服务未记录") + " · " + run
                if names.count(label) > 1
                else label
            )
        )
        for run, label in labels.items()
    }
    previous = st.query_params.get("history") or st.session_state.get("public_preview_run")
    invalid = bool(previous and previous not in by_run)
    if invalid:
        st.warning("无法定位链接中的历史批次，请重新选择。")
        st.session_state.pop("preview_history_run", None)
    index = None if invalid else list(by_run).index(previous) if previous in by_run else 0
    selected = st.selectbox(
        "历史测试",
        list(by_run),
        index=index,
        format_func=labels.get,
        key="preview_history_run",
        on_change=_remember_run,
    )
    if selected is None:
        return
    st.query_params["history"] = selected
    st.session_state["public_preview_run"] = selected
    rows = sorted(
        (r for r in records if str(r["run_id"]) == selected),
        key=lambda r: (str(r["case_id"]), str(r["eval_model"]), _record_identity(r)[2]),
    )
    run = by_run[selected]
    st.caption("已保存的历史记录，未按当前配置重新运行。")
    if not results:
        tables = {
            name: [r for r in values if str(r.get("run_id")) == selected]
            for name, values in report.runtime_tables.items()
        }
        status_rows = pair_rows(tables.get("live_run_responses", []), tables.get("live_run_scores", []),tables.get('live_run_queue',[]))
        if status_rows:
            st.dataframe(
                _safe([{k: v for k, v in row.items() if k != "_score"} for row in status_rows]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("该批次未保存完整进度状态，不推算执行进度。")
        if any(r.get("judge_status") == "failed" for r in tables.get("live_run_scores", [])):
            st.warning("模型回答已保存，但本批次包含未完成的AI评分。")
        elif any(r.get('run_status')=='failed' for r in tables.get('live_run_responses',[])) or any(r.get('status')=='failed' for r in tables.get('live_run_queue',[])):
            st.warning('本批次包含回答失败，未产生对应评分。原记录保留。')
        with st.expander("请求诊断"):
            if tables.get("request_attempts"):
                st.dataframe(safe_attempt_details(tables["request_attempts"]), hide_index=True, width="stretch")
            st.caption("只有原任务持有人可通过有效恢复链接重试评分；浏览历史不提供他人任务的调用权限。")
        st.button("查看该批次评分 →", key="preview_to_results", type="primary", on_click=_go_results)
    elif rows:
        with st.expander("查看该批次全部评分"):
            st.dataframe(
                _safe(
                    [
                        {
                            "样本": r["case_id"],
                            "模型": display_model_name(str(r["eval_model"]), source="live"),
                            "AI评分": r.get("total_score"),
                        }
                        for r in rows
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        st.caption("单题历史AI评分；评分满分及证据缺失情况请进入对应案例核对，不作模型整体排名。")
        identities = {_record_identity(r) + (str(r["case_id"]),): r for r in rows}
        default = next((i for i, k in enumerate(identities) if k[3] == "FD-001"), 0)
        saved = st.session_state.get("public_preview_record")
        if any(st.query_params.get(f) for f in ROUTE_FIELDS):
            saved = tuple(st.query_params.get(f, "") for f in ("run", "model", "score", "case"))
            if saved not in identities:
                st.warning("无法定位链接中的评分记录，请重新选择历史批次。")
                return
        if saved in identities:
            default = list(identities).index(saved)
        identity = st.selectbox(
            "查看评分依据",
            list(identities),
            format_func=lambda k: k[3]
            + " · "
            + display_model_name(k[1], source="live")
            + " · "
            + (
                str(identities[k].get("total_score"))
                if identities[k].get("judge_status") == "success"
                else failure_label(identities[k])
            ),
            index=default,
            key="preview_history_record",
        )
        st.session_state["public_preview_record"] = identity
        st.query_params.update(run=identity[0], model=identity[1], score=identity[2], case=identity[3])
        st.button(
            "查看该案例",
            key="preview_review_record",
            type="primary",
            on_click=_open_record,
            args=(identities[identity],),
        )
    else:
        st.info("该历史运行尚无有效评分记录，可在历史运行中查看失败或未完成状态。")
    with st.expander("本次测试配置"):
        st.json(
            _safe({k: v for k, v in run.items() if k not in {"evaluation_context_json", "prompt_payload_json"}}),
            expanded=False,
        )


def _go_results():
    st.session_state.preview_stage = STAGES["results"]
    st.query_params["stage"] = "results"
    request_scroll("top")


def _sample_domain_changed():
    domain = st.session_state.get("preview_sample_domain")
    if domain is not None:
        st.query_params["sample_domain"] = domain
    else:
        st.query_params.pop("sample_domain", None)
    st.query_params.pop("sample_case", None)
    st.session_state.pop("preview_sample_case", None)


def _sample_case_changed():
    case = st.session_state.get("preview_sample_case")
    if case is not None:
        st.query_params["sample_case"] = case
    else:
        st.query_params.pop("sample_case", None)


def render_sample_preview(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    with st.container(key="portfolio_preview"):
        st.title("样本与评价标准")
        st.caption("当前题库的任务与评价标准；不作为旧运行批次的输入或评分依据。")
        if management_enabled():
            mode = st.radio("样本操作", ["浏览样本", "新增样本预览"], horizontal=True, key="preview_sample_mode")
            if mode == "新增样本预览":
                _render_draft()
                return
        tasks = _tasks(base)
        domains = list(dict.fromkeys(str(r["domain"]) for r in tasks if r.get("domain")))
        domain_options = ["全部", *domains]
        requested = st.query_params.get("sample_domain")
        if requested is not None:
            st.session_state.preview_sample_domain = requested if requested in domain_options else None
            if requested not in domain_options:
                st.warning("链接中的专业领域不存在，请重新选择。")
        elif st.session_state.get("preview_sample_domain") not in domain_options:
            st.session_state.preview_sample_domain = "全部"
        domain = st.selectbox(
            "专业场景",
            domain_options,
            index=None,
            format_func=lambda d: display_label(d, DOMAIN_LABELS),
            key="preview_sample_domain",
            on_change=_sample_domain_changed,
        )
        if domain is None:
            return
        filtered = [r for r in tasks if domain == "全部" or str(r.get("domain")) == domain]
        if not filtered:
            st.info("暂无匹配的专业任务，请选择其他专业领域。")
            return
        by_case = {str(r["case_id"]): r for r in filtered}
        requested = st.query_params.get("sample_case")
        if requested is not None:
            st.session_state.preview_sample_case = requested if requested in by_case else None
            if requested not in by_case:
                st.warning("链接中的专业任务不在当前领域，请重新选择。")
        elif st.session_state.get("preview_sample_case") not in by_case:
            st.session_state.preview_sample_case = next(iter(by_case))
        case = st.selectbox(
            "专业任务",
            list(by_case),
            index=None,
            format_func=lambda c: str(by_case[c].get("title") or by_case[c].get("scenario") or "专业任务") + " · " + c,
            key="preview_sample_case",
            on_change=_sample_case_changed,
        )
        if case is None:
            return
        st.query_params.update(sample_domain=domain, sample_case=case)
        st.subheader(
            str(_safe(by_case[case].get("title") or by_case[case].get("scenario") or "专业任务")) + " · " + case
        )
        _render_task(by_case[case], historical=False)
        render_reference_standard(
            (getattr(base, "gold_answer_map", {}) or {}).get(case), historical=False, summary=True
        )


def _render_draft():
    if not management_enabled():
        st.info("样本录入仅在受控管理环境开放。")
        return
    st.caption("填写新增样本并预览结构。内容仅保留在本次会话，不加入正式题库。")
    with st.form("public_sample_preview_form"):
        case = st.text_input("样本编号", key="preview_draft_id")
        title = st.text_input("样本标题", key="preview_draft_title")
        scene = st.selectbox("专业场景", PROFESSIONAL_SCENE_OPTIONS, key="preview_draft_scene")
        question = st.text_area("任务题", key="preview_draft_question")
        context = st.text_area("业务背景", key="preview_draft_context")
        output = st.text_area("输出要求", key="preview_draft_output")
        core = st.text_area("参考判断", key="preview_draft_core")
        evidence = st.text_area("关键依据", key="preview_draft_evidence")
        must = st.text_area("必须覆盖点（每行一条）", key="preview_draft_must")
        forbidden = st.text_area("不可接受错误（每行一条）", key="preview_draft_forbidden")
        boundary = st.text_area("适用边界", key="preview_draft_boundary")
        submitted = st.form_submit_button("预览任务与标准", key="preview_draft_submit", type="primary")
        st.form_submit_button("保存到样本库", key="preview_save_sample", disabled=True)
    if submitted:
        task = dict(
            case_id=case.strip(),
            title=title,
            domain=_domain_from_professional_scene(scene),
            scenario=title,
            question=question,
            context=context,
            output_requirement=output,
            status="draft",
        )
        gold = _build_gold_answer_json(
            sample_id=case,
            core_conclusion=core,
            key_evidence=evidence,
            must_have_points=must,
            unacceptable_errors=forbidden,
            boundary_conditions=boundary,
            manual_review_notes="",
        )
        st.session_state["public_sample_draft"] = dict(task=task, gold=gold)
    st.caption("实际新增、导入与维护在受控管理环境完成；公开页面无法保存。")
    draft = st.session_state.get("public_sample_draft")
    if draft:
        st.subheader("新增样本预览 · 未保存")
        st.text(
            str(_safe(draft["task"].get("title") or "标题未填写"))
            + " · "
            + str(_safe(draft["task"].get("case_id") or "编号未填写"))
        )
        _render_task(draft["task"], historical=False)
        render_reference_standard(draft["gold"], historical=False)
