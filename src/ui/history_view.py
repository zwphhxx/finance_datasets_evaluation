"""Public history replay and manual judge checks; no API activity during rendering."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services.comparison import comparison_for_runs, runtime_counts
from app.services.conclusion_read_model import build_conclusion_report
from app.services.model_display import display_model_name
from app.services.snapshot import _safe, export_snapshot, load_snapshot, restore_context

PUBLIC_SNAPSHOT = Path(__file__).resolve().parents[2] / "public" / "evaluation_snapshot.json"


def snapshot_report(snapshot, run_ids=None):
    tables = snapshot["tables"]
    runs = pd.DataFrame(tables["live_evaluation_runs"])
    scores = pd.DataFrame(tables["live_run_scores"])
    if run_ids:
        runs = runs[runs["run_id"].isin(run_ids)]
        scores = scores[scores["run_id"].isin(run_ids)] if not scores.empty else scores
    cohort = cc.select_current_cohort_scores(runs, scores)
    baseline = next((r for r in runs.to_dict("records") if r["run_id"] in set(cohort.get("run_id", []))), None)
    compatible = [
        r
        for r in runs.to_dict("records")
        if baseline and cc._cohort_signature(pd.Series(r)) == cc._cohort_signature(pd.Series(baseline))
    ]
    task_records, gold, dimensions = restore_context(compatible, [r["case_id"] for r in tables["live_run_queue"]])
    planned = set()
    for r in runs.to_dict("records"):
        planned.update(json.loads(r.get("model_ids_json") or "[]"))
    report = build_conclusion_report(
        scores_df=cohort,
        responses_df=pd.DataFrame(tables["live_run_responses"]),
        tasks_df=pd.DataFrame(task_records),
        gold_map=gold,
        dimensions=dimensions,
        planned_models=planned or None,
    )
    scoped_tables = {name: [r for r in rows if not run_ids or r["run_id"] in run_ids] for name, rows in tables.items()}
    comparison = comparison_for_runs(report.formal_scores, compatible) if compatible else report.comparison
    return replace(report, comparison=comparison, runtime_tables=scoped_tables)


def active_snapshot():
    snapshot = st.session_state.get("readonly_evaluation_snapshot")
    if snapshot is None and not st.session_state.get("public_snapshot_dismissed") and PUBLIC_SNAPSHOT.is_file():
        try:
            snapshot = load_snapshot(PUBLIC_SNAPSHOT.read_bytes())
            st.session_state["readonly_evaluation_snapshot"] = snapshot
        except (ValueError, OSError):
            st.warning("公开评测快照不可读取或校验未通过。")
    return snapshot


def render_history_controls():
    snapshot = active_snapshot()
    with st.expander("真实历史评测：只读加载与完整快照"):
        st.caption("无需API Key。加载或回放不发起模型调用、不写入数据库。上传文件的真实来源声明未经独立认证。")
        uploaded = st.file_uploader("加载完整评测快照 JSON", type=["json"], key="readonly_snapshot_upload")
        if uploaded is not None and st.button("只读加载快照", key="readonly_snapshot_load"):
            try:
                snapshot = load_snapshot(uploaded.getvalue())
                st.session_state["readonly_evaluation_snapshot"] = snapshot
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if snapshot:
            st.caption(f"来源：{snapshot['provenance']['source']}｜导出时间：{snapshot['provenance']['exported_at']}")
            if st.button("返回当前数据库结果", key="readonly_snapshot_close"):
                st.session_state.pop("readonly_evaluation_snapshot", None)
                st.session_state["public_snapshot_dismissed"] = True
                snapshot = None
                st.rerun()
    if not snapshot:
        return None
    runs = snapshot["tables"]["live_evaluation_runs"]
    if not runs:
        st.info("快照中没有真实历史评测记录。")
        return snapshot_report(snapshot)
    selected = st.selectbox(
        "历史运行批次", options=["当前兼容比较组", *[r["run_id"] for r in runs]], key="history_run_select"
    )
    return snapshot_report(snapshot, None if selected == "当前兼容比较组" else [selected])


def render_snapshot_export(store):
    if store is None:
        st.caption("数据库不可用；仍可加载完整评测快照。")
        return
    try:
        snapshot = export_snapshot(store)
    except Exception:
        st.caption("当前无法导出完整快照。")
        return
    st.download_button(
        "导出完整评测快照",
        data=json.dumps(snapshot, ensure_ascii=False, indent=2),
        file_name="evaluation_snapshot.json",
        mime="application/json",
        disabled=not snapshot["tables"]["live_evaluation_runs"],
        key="export_full_snapshot",
    )
    st.caption(
        "包含运行时题目和专业标准（旧批次可能缺失）、模型回答、评分、原始响应、状态、配置版本与请求尝试；文本密钥及本机路径自动脱敏。"
    )


def render_comparison_and_runtime(report, *, include_runtime=True):
    result = report.comparison
    if result:
        st.markdown("**共同有效样本质量比较**")
        st.caption(
            "比较对象："
            + ("同模型不同服务端点" if result.get("kind") == "service_endpoint" else "不同模型及其服务配置")
        )
        st.caption(f"共同有效样本：{result['common_count']} 条。各模型自身样本均分仅用于单模型观察。")
        if result["common_count"]:
            display_rows = [dict(row, model_id=" | ".join([display_model_name(str(row["model_id"]).split(" | ")[0], source="live"), *str(row["model_id"]).split(" | ")[1:]])) for row in result["models"]]
            st.dataframe(
                pd.DataFrame(display_rows).rename(
                    columns={"model_id": "模型", "common_count": "共同样本数", "avg_total": "共同样本均分"}
                ),
                column_config={
                    "模型": st.column_config.TextColumn(),
                    "共同样本数": st.column_config.NumberColumn("共同样本", width="small"),
                    "共同样本均分": st.column_config.NumberColumn("共同均分", width="small", format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
            )
        if not result["sufficient"]:
            st.info("数据不足以形成模型优劣比较。" + result["reason"])
    if include_runtime:
        render_runtime_details(report)


def render_runtime_details(report):
    tables = report.runtime_tables
    if not tables:
        return
    counts = runtime_counts(tables.get("live_run_queue", []), tables.get("live_run_responses", []), tables.get("live_run_scores", []))
    if counts:
        st.markdown("**运行覆盖与失败记录**")
        st.caption("以下为当前来源全部运行的状态；上方筛选仅影响质量比较，失败项不参与均分。")
        st.dataframe(pd.DataFrame(counts)[["model_id", "planned", "answer_failed", "judge_failed", "unfinished"]].rename(columns={"model_id":"模型", "planned":"计划任务", "answer_failed":"回答失败", "judge_failed":"评分失败", "unfinished":"未完成"}), hide_index=True, use_container_width=True)
        failures = [{"运行批次": r.get("run_id"), "样本":r.get("case_id"), "模型":r.get("model_name") or r.get("eval_model"), "阶段":stage, "原因":r.get("error_message") or r.get("error_code") or "该记录未保存失败原因"} for stage, name, field in [("模型回答", "live_run_responses", "run_status"), ("自动评分", "live_run_scores", "judge_status")] for r in tables.get(name, []) if r.get(field) == "failed"]
        if failures:
            with st.expander(f"查看失败原因 · {len(failures)} 条记录"):
                st.dataframe(_safe(failures), hide_index=True, use_container_width=True)
    with st.expander("运行覆盖、失败与测试配置"):
        if report.comparison.get("case_ids"):
            st.caption("共同任务：" + "、".join(report.comparison["case_ids"]))
        st.caption("此处列出所选快照批次或当前数据库全部运行；共同质量比较仅使用兼容版本组。失败记录继续保留。")
        counts = runtime_counts(
            tables.get("live_run_queue", []), tables.get("live_run_responses", []), tables.get("live_run_scores", [])
        )
        if counts:
            labels = {
                "model_id": "模型",
                "planned": "计划任务",
                "answer_success": "回答成功",
                "answer_failed": "回答失败",
                "judge_success": "评分成功",
                "judge_failed": "评分失败",
                "unfinished": "未完成",
                "answer_success_rate": "回答成功率（计划任务为分母）",
                "judge_success_rate": "评分成功率（已尝试评分为分母）",
                "answer_timeout": "回答最终超时",
                "judge_timeout": "评分最终超时",
            }
            st.dataframe(pd.DataFrame(counts).rename(columns=labels), hide_index=True, use_container_width=True)
        runs = tables.get("live_evaluation_runs", [])
        fields = [
            "run_id",
            "provider",
            "service_endpoint",
            "model_ids_json",
            "created_at",
            "dataset_version",
            "dataset_hash",
            "prompt_hash",
            "generation_parameters_json",
            "judge_parameters_json",
            "status",
        ]
        st.dataframe(_safe([{k: r.get(k) for k in fields} for r in runs]), hide_index=True, use_container_width=True)
        st.caption(
            "模型比较观察回答质量；同一模型在不同服务端点的比较观察服务实现。旧批次未记录端点时无法判断端点一致性。不同端点数据不应合并成一个模型排名。"
        )


def render_judge_selftest(dimensions):
    with st.expander("裁判模型自测（人工构造数据，独立于正式评测）"):
        from app.models.registry import get_text_provider
        from app.services.judge_selftest import run_selftest
        from app.services.scorer import DEFAULT_JUDGE_MODEL

        provider = get_text_provider()
        st.caption(
            "财务、法律、投行各一个任务，分别测试正确、重大错误、简短正确回答。最多9次裁判API请求；无重试；每次输出上限3072 Token。普通浏览不调用API。"
        )
        st.caption("检查已知错误识别、引文、重大错误扣分及篇幅偏好；少量自测通过不代表全面验证。")
        if st.button("手动运行9次裁判自测（产生API费用）", disabled=provider.name == "mock", key="run_judge_selftest"):
            with st.spinner("正在运行独立裁判自测"):
                st.session_state["judge_selftest_result"] = run_selftest(
                    provider, DEFAULT_JUDGE_MODEL, dimensions, max_calls=9
                )
        result = st.session_state.get("judge_selftest_result")
        if result:
            st.caption(f"自测时间：{result['created_at']}｜服务商：{result['provider']}｜裁判：{result['judge_model']}")
            for row in result["results"]:
                st.text(
                    f"{row['case_id']}：{'通过有限检查' if row['passed'] else '未满足预期'}；错误识别：{row['error_detected']}"
                )
                for reason in row["reasons"]:
                    st.warning(reason)
                st.json(_safe(row["outcomes"]), expanded=False)
            st.download_button(
                "导出独立裁判自测记录",
                json.dumps(_safe(result), ensure_ascii=False, indent=2),
                file_name="judge_selftest.json",
                mime="application/json",
                key="export_judge_selftest",
            )


def render_attempts_and_costs(report):
    from app.services.formal_records import filter_formal_scores
    from app.services.runtime_metrics import attempt_metrics, cost_summary, expected_attempts

    tables = report.runtime_tables
    if not tables:
        return
    attempts = tables.get("request_attempts", [])
    with st.expander("全部请求尝试、Token用量与费用估算"):
        if not attempts:
            st.caption("历史批次未保存独立请求尝试；无法还原重试用量或完整费用，不默认记为0。")
        else:
            st.dataframe(_safe(attempts), hide_index=True, use_container_width=True)
            st.dataframe(
                [dict(phase=phase, **metrics) for phase, metrics in attempt_metrics(attempts).items()],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "耗时与已知Token为全部尝试累计；usage_unknown为用量缺失尝试数，latency_unknown为耗时缺失数。运行中断的running尝试用量未知。"
            )
        uploaded = st.file_uploader(
            "费用价格配置 JSON（带来源、币种和有效日期）", type=["json"], key="cost_prices_upload"
        )
        if uploaded is None:
            st.caption(
                "未提供价格配置，不估算费用。价格按每百万输入/输出Token填写，区间为生效日起至失效日前，按请求UTC日期匹配。"
            )
            return
        try:
            prices = json.loads(uploaded.getvalue())
            scores = filter_formal_scores(
                pd.DataFrame(tables.get("live_run_scores", [])), pd.DataFrame(tables.get("live_run_responses", []))
            )
            if not scores.empty:
                scores = scores.drop_duplicates(["run_id", "case_id", "eval_model"], keep="last")
            passed = int((pd.to_numeric(scores["total_score"], errors="coerce") >= 60).sum()) if not scores.empty else 0
            summary = cost_summary(attempts, prices, expected=expected_attempts(tables), passed_tasks=passed)
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"价格配置无法使用：{exc}")
            return
        st.json(_safe(prices), expanded=False)
        st.dataframe(
            [dict(phase=phase, **metrics) for phase, metrics in summary["phases"].items()],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"未知用量：{summary['unknown_usage']}；缺失价格：{summary['missing_prices']}；历史尝试覆盖缺口：{summary['missing_attempt_groups']}。"
        )
        if summary["complete"] and summary["cost_per_passed_task"] is not None:
            st.text(
                f"达标任务（正式总分≥60）：{passed}；每个达标任务估算API费用：{summary['cost_per_passed_task']:.6f} {summary['currencies'][0]}"
            )
        else:
            st.info("费用覆盖不完整、币种不一致或无达标任务；不计算每个达标任务成本。known_subtotal仅为已知覆盖部分。")
        st.caption(
            "回答请求和裁判评分费用分别列示。仅按显式价格估算API调用费用，不是真实结算账单或模型公司内部推理成本。"
        )
