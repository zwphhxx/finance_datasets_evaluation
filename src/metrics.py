from __future__ import annotations

import pandas as pd


SCORE_DIMENSIONS = [
    ("accuracy_score", "专业准确性"),
    ("reasoning_score", "推理与场景适配"),
    ("coverage_score", "风险覆盖"),
    ("evidence_score", "依据可靠性"),
    ("expression_score", "专业表达"),
]

# 评分标准维度满分配置，合计 100 分，与 total_score 保持一致。
# 这是评测方法配置，不是样本级数据；用于在统一口径下比较各维度达成率。
SCORE_DIMENSION_FULL_MARKS = {
    "accuracy_score": 30,
    "reasoning_score": 20,
    "coverage_score": 20,
    "evidence_score": 15,
    "expression_score": 15,
}

# 错误标签到评分维度的映射，依据 data/label_taxonomy.yml 中的标签定义维护。
# 错误标签本身来自数据文件，这里只负责把标签归入对应评分维度。
ERROR_TYPE_TO_DIMENSION = {
    "依据错误": "依据可靠性",
    "风险遗漏": "风险覆盖",
    "可执行性弱": "风险覆盖",
    "推理不足": "推理与场景适配",
    "场景错配": "推理与场景适配",
    "表达问题": "专业表达",
}


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def get_overview_metrics(data_bundle: dict) -> dict[str, float | int | None]:
    data = data_bundle["data"]
    average_score = None
    if "total_score" in data.scores and not data.scores.empty:
        average_score = data.scores["total_score"].mean()

    return {
        "task_count": len(data.tasks),
        "model_count": data.model_outputs["model_name"].nunique()
        if "model_name" in data.model_outputs
        else 0,
        "average_total_score": average_score,
        "error_label_count": len(data.errors),
        "optimization_count": len(data.optimizations),
    }


def get_model_average_scores(scores_df: pd.DataFrame) -> pd.DataFrame:
    if scores_df.empty or not has_columns(scores_df, ["model_name", "total_score"]):
        return pd.DataFrame(columns=["model_name", "total_score"])
    return scores_df.groupby("model_name")["total_score"].mean().reset_index()


def get_model_total_scores(scores_df: pd.DataFrame) -> pd.DataFrame:
    return get_model_average_scores(scores_df)


def get_model_dimension_scores(scores_df: pd.DataFrame) -> pd.DataFrame:
    if scores_df.empty or "model_name" not in scores_df:
        return pd.DataFrame(columns=["model_name", "dimension", "score"])

    rows = []
    for column, label in SCORE_DIMENSIONS:
        if column not in scores_df:
            continue
        grouped = scores_df.groupby("model_name")[column].mean().reset_index()
        for _, row in grouped.iterrows():
            rows.append(
                {
                    "model_name": row["model_name"],
                    "dimension": label,
                    "score": row[column],
                }
            )
    return pd.DataFrame(rows, columns=["model_name", "dimension", "score"])


def get_model_error_type_counts(error_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["model_name", "error_type", "count"]
    if error_df.empty or not has_columns(error_df, ["model_name", "error_type"]):
        return pd.DataFrame(columns=columns)
    return error_df.groupby(["model_name", "error_type"]).size().reset_index(name="count")


def get_dimension_gap_ranking(scores_df: pd.DataFrame) -> pd.DataFrame:
    """计算各评分标准维度在所有回答中的平均达成率.

    Returns columns [dimension, avg_score, full_mark, attainment] sorted from
    weakest to strongest, so the first row is the shared weak dimension.
    """
    columns = ["dimension", "avg_score", "full_mark", "attainment"]
    if scores_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for column, label in SCORE_DIMENSIONS:
        if column not in scores_df:
            continue
        full_mark = SCORE_DIMENSION_FULL_MARKS.get(column)
        if not full_mark:
            continue
        avg_score = float(scores_df[column].mean())
        rows.append(
            {
                "dimension": label,
                "avg_score": avg_score,
                "full_mark": full_mark,
                "attainment": avg_score / full_mark,
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values("attainment").reset_index(drop=True)


def get_model_domain_scores(scores_df: pd.DataFrame, tasks_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["model_name", "domain", "scenario", "total_score"]
    if (
        scores_df.empty
        or tasks_df.empty
        or not has_columns(scores_df, ["case_id", "model_name", "total_score"])
        or not has_columns(tasks_df, ["case_id", "domain", "scenario"])
    ):
        return pd.DataFrame(columns=columns)

    merged = pd.merge(
        scores_df[["case_id", "model_name", "total_score"]],
        tasks_df[["case_id", "domain", "scenario"]],
        on="case_id",
        how="left",
    )
    return merged.groupby(["model_name", "domain", "scenario"])["total_score"].mean().reset_index()


def get_model_capability_summaries(
    scores_df: pd.DataFrame,
    error_df: pd.DataFrame,
    tasks_df: pd.DataFrame,
) -> list[dict[str, str]]:
    if scores_df.empty or not has_columns(scores_df, ["model_name", "total_score"]):
        return []

    total_scores = get_model_total_scores(scores_df)
    dimension_scores = get_model_dimension_scores(scores_df)
    error_counts = get_model_error_type_counts(error_df)
    domain_scores = get_model_domain_scores(scores_df, tasks_df)

    summaries = []
    for _, score_row in total_scores.iterrows():
        model_name = score_row["model_name"]
        model_scores = scores_df[scores_df["model_name"] == model_name]
        sample_count = len(model_scores)
        average_score = score_row["total_score"]

        weakest_dimension = _get_weakest_dimension(dimension_scores, model_name)
        top_error = _get_top_error_type(error_counts, model_name)
        weakest_domain = _get_weakest_domain(domain_scores, model_name)

        parts = [
            f"基于当前 {sample_count} 个样本，平均总分 {average_score:.1f}。",
            f"相对短板集中在{weakest_dimension}。",
        ]
        if top_error:
            parts.append(f"错误标签中 {top_error} 较集中。")
        else:
            parts.append("当前错误标签样本较少，暂不判断集中错误类型。")
        if weakest_domain:
            parts.append(f"按领域观察，{weakest_domain} 相关任务需继续关注。")
        parts.append("结论仅用于当前评测集观察。")
        summaries.append({"model_name": model_name, "summary": "".join(parts)})
    return summaries


def get_error_type_counts(error_df: pd.DataFrame) -> pd.DataFrame:
    if error_df.empty or "error_type" not in error_df:
        return pd.DataFrame(
            {
                "error_type": pd.Series(dtype="object"),
                "count": pd.Series(dtype="int64"),
            }
        )
    error_counts = error_df["error_type"].value_counts().reset_index()
    error_counts.columns = ["error_type", "count"]
    return error_counts


def get_task_domains(tasks_df: pd.DataFrame) -> list[str]:
    if tasks_df.empty or "domain" not in tasks_df:
        return ["全部"]
    return ["全部"] + sorted(tasks_df["domain"].dropna().unique().tolist())


def filter_tasks_by_domain(tasks_df: pd.DataFrame, selected_domain: str) -> pd.DataFrame:
    if selected_domain == "全部" or "domain" not in tasks_df:
        return tasks_df
    return tasks_df[tasks_df["domain"] == selected_domain]


def get_case_ids(tasks_df: pd.DataFrame) -> list[str]:
    if tasks_df.empty or "case_id" not in tasks_df:
        return []
    return tasks_df["case_id"].tolist()


def get_task_by_case_id(tasks_df: pd.DataFrame, case_id: str) -> pd.DataFrame:
    if tasks_df.empty or "case_id" not in tasks_df:
        return pd.DataFrame(columns=tasks_df.columns)
    return tasks_df[tasks_df["case_id"] == case_id]


def merge_case_outputs_with_scores(
    model_outputs_df: pd.DataFrame,
    scores_df: pd.DataFrame,
    case_id: str,
) -> pd.DataFrame:
    if "case_id" not in model_outputs_df:
        return pd.DataFrame(columns=model_outputs_df.columns)

    case_outputs = model_outputs_df[model_outputs_df["case_id"] == case_id]
    merge_keys = ["output_id", "case_id", "model_name"]
    if has_columns(scores_df, merge_keys):
        return pd.merge(case_outputs, scores_df, on=merge_keys, how="left")
    return case_outputs.copy()


def get_errors_for_output(error_df: pd.DataFrame, output_id) -> pd.DataFrame:
    if error_df.empty or "output_id" not in error_df:
        return pd.DataFrame(columns=error_df.columns)
    return error_df[error_df["output_id"] == output_id]


def get_preference_pairs_for_case(preference_pairs_df: pd.DataFrame, case_id: str) -> pd.DataFrame:
    if preference_pairs_df.empty or "case_id" not in preference_pairs_df:
        return pd.DataFrame(columns=preference_pairs_df.columns)
    return preference_pairs_df[preference_pairs_df["case_id"] == case_id]


def get_preference_pair_details_for_case(
    preference_pairs_df: pd.DataFrame,
    model_outputs_df: pd.DataFrame,
    case_id: str,
) -> pd.DataFrame:
    pairs = get_preference_pairs_for_case(preference_pairs_df, case_id)
    detail_columns = [
        "preferred_model_name",
        "preferred_answer_text",
        "rejected_model_name",
        "rejected_answer_text",
    ]
    if pairs.empty:
        return pd.DataFrame(columns=list(preference_pairs_df.columns) + detail_columns)

    output_lookup = _build_output_lookup(model_outputs_df)
    records = []
    for _, pair in pairs.iterrows():
        preferred = output_lookup.get(str(pair.get("preferred_output_id")), {})
        rejected = output_lookup.get(str(pair.get("rejected_output_id")), {})
        record = pair.to_dict()
        record.update(
            {
                "preferred_model_name": preferred.get("model_name"),
                "preferred_answer_text": preferred.get("answer_text"),
                "rejected_model_name": rejected.get("model_name"),
                "rejected_answer_text": rejected.get("answer_text"),
            }
        )
        records.append(record)
    return pd.DataFrame(records)


def get_optimization_suggestions_for_case(
    error_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
    case_id: str,
) -> pd.DataFrame:
    if (
        error_df.empty
        or optimization_df.empty
        or not has_columns(error_df, ["case_id", "error_type"])
        or "frequent_error" not in optimization_df
    ):
        return pd.DataFrame(columns=optimization_df.columns)

    case_errors = error_df[error_df["case_id"] == case_id]
    if case_errors.empty:
        return pd.DataFrame(columns=optimization_df.columns)

    error_types = set(case_errors["error_type"].dropna().astype(str))
    return optimization_df[optimization_df["frequent_error"].astype(str).isin(error_types)]


def _build_output_lookup(model_outputs_df: pd.DataFrame) -> dict[str, dict]:
    if model_outputs_df.empty or "output_id" not in model_outputs_df:
        return {}
    return {
        str(row["output_id"]): row.to_dict()
        for _, row in model_outputs_df.iterrows()
    }


def _get_weakest_dimension(dimension_scores: pd.DataFrame, model_name: str) -> str:
    if dimension_scores.empty:
        return "尚无分维度评分"
    model_dimensions = dimension_scores[dimension_scores["model_name"] == model_name]
    if model_dimensions.empty:
        return "尚无分维度评分"
    return str(model_dimensions.sort_values("score").iloc[0]["dimension"])


def _get_top_error_type(error_counts: pd.DataFrame, model_name: str) -> str | None:
    if error_counts.empty:
        return None
    model_errors = error_counts[error_counts["model_name"] == model_name]
    if model_errors.empty:
        return None
    return str(model_errors.sort_values("count", ascending=False).iloc[0]["error_type"])


def _get_weakest_domain(domain_scores: pd.DataFrame, model_name: str) -> str | None:
    if domain_scores.empty:
        return None
    model_domains = domain_scores[domain_scores["model_name"] == model_name]
    if model_domains.empty:
        return None
    return str(model_domains.sort_values("total_score").iloc[0]["domain"])

# Error attribution to data improvement actions
OPTIMIZATION_ACTION_COLUMNS = [
    "action_id",
    "error_type",
    "root_cause",
    "data_action",
    "sample_format",
    "priority",
    "expected_effect",
    "validation_metric",
    "status",
]

ERROR_DISTRIBUTION_COLUMNS = [
    "error_type",
    "count",
    "severity",
    "models",
    "cases",
]

ERROR_ACTION_COLUMNS = ERROR_DISTRIBUTION_COLUMNS + [
    column for column in OPTIMIZATION_ACTION_COLUMNS if column != "error_type"
]

PRIORITY_ERROR_SAMPLE_COLUMNS = [
    "case_id",
    "model_name",
    "error_type",
    "severity",
    "error_description",
    "root_cause",
    "data_action",
    "sample_format",
    "priority",
    "expected_effect",
    "validation_metric",
    "status",
]


def _empty_metrics_frame(columns):
    import pandas as pd

    return pd.DataFrame(columns=columns)


def _copy_metrics_frame(df):
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    return df.copy()


def _pick_metrics_column(df, preferred, legacy=None, default=""):
    if preferred in df.columns:
        return df[preferred]
    if legacy and legacy in df.columns:
        return df[legacy]
    return default


def _join_unique_values(values):
    cleaned = [str(value) for value in values if str(value) and str(value).lower() != "nan"]
    return "; ".join(sorted(set(cleaned)))


def _highest_severity(values):
    severity_order = {"高": 3, "中": 2, "低": 1, "high": 3, "medium": 2, "low": 1}
    cleaned = [str(value) for value in values if str(value) and str(value).lower() != "nan"]
    if not cleaned:
        return ""
    return sorted(cleaned, key=lambda value: severity_order.get(value, 0), reverse=True)[0]


def normalize_optimization_plan(optimization_df):
    """Normalize legacy and current optimization plan schemas into one action table."""
    import pandas as pd

    df = _copy_metrics_frame(optimization_df)
    if df.empty:
        return _empty_metrics_frame(OPTIMIZATION_ACTION_COLUMNS)

    normalized = pd.DataFrame()
    normalized["error_type"] = _pick_metrics_column(df, "error_type", "frequent_error", "")
    normalized["root_cause"] = _pick_metrics_column(df, "root_cause", "likely_cause", "")
    normalized["data_action"] = _pick_metrics_column(df, "data_action", "optimization_action", "")
    normalized["sample_format"] = _pick_metrics_column(df, "sample_format", "data_sample_format", "")
    normalized["priority"] = _pick_metrics_column(df, "priority", default="")
    normalized["expected_effect"] = _pick_metrics_column(
        df,
        "expected_effect",
        default="补强对应错误类型的训练与评测覆盖。",
    )
    normalized["validation_metric"] = _pick_metrics_column(
        df,
        "validation_metric",
        default="相关错误类型出现次数下降，匹配维度评分提升。",
    )
    normalized["status"] = _pick_metrics_column(df, "status", default="planned")

    if "action_id" in df.columns:
        normalized["action_id"] = df["action_id"]
    else:
        normalized["action_id"] = [f"ACTION-{index + 1:03d}" for index in range(len(df))]

    normalized = normalized[OPTIMIZATION_ACTION_COLUMNS]
    for column in OPTIMIZATION_ACTION_COLUMNS:
        normalized[column] = normalized[column].fillna("").astype(str)
    return normalized


def get_error_distribution_summary(error_df):
    """Summarize error frequency with severity, involved models, and cases."""
    df = _copy_metrics_frame(error_df)
    required = {"error_type"}
    if df.empty or not required.issubset(df.columns):
        return _empty_metrics_frame(ERROR_DISTRIBUTION_COLUMNS)

    for column in ["severity", "model_name", "case_id"]:
        if column not in df.columns:
            df[column] = ""

    summary = (
        df.groupby("error_type", dropna=False)
        .agg(
            count=("error_type", "size"),
            severity=("severity", _highest_severity),
            models=("model_name", _join_unique_values),
            cases=("case_id", _join_unique_values),
        )
        .reset_index()
        .sort_values(["count", "error_type"], ascending=[False, True])
    )
    return summary[ERROR_DISTRIBUTION_COLUMNS]


def _error_action_fallbacks(error_df):
    import pandas as pd

    df = _copy_metrics_frame(error_df)
    columns = ["error_type", "data_action"]
    if df.empty or "error_type" not in df.columns or "optimization_action" not in df.columns:
        return pd.DataFrame(columns=columns)

    fallback = (
        df[["error_type", "optimization_action"]]
        .dropna()
        .rename(columns={"optimization_action": "data_action"})
    )
    fallback = fallback[fallback["data_action"].astype(str).str.strip() != ""]
    if fallback.empty:
        return pd.DataFrame(columns=columns)
    return fallback.drop_duplicates("error_type", keep="first")


def get_error_attribution_actions(error_df, optimization_df):
    """Link observed errors to root causes and data improvement actions."""
    summary = get_error_distribution_summary(error_df)
    if summary.empty:
        return _empty_metrics_frame(ERROR_ACTION_COLUMNS)

    plan = normalize_optimization_plan(optimization_df)
    actions = summary.merge(plan, on="error_type", how="left")

    fallback = _error_action_fallbacks(error_df)
    if not fallback.empty:
        actions = actions.merge(fallback, on="error_type", how="left", suffixes=("", "_fallback"))
        if "data_action_fallback" in actions.columns:
            actions["data_action"] = actions["data_action"].fillna("")
            actions["data_action"] = actions["data_action"].where(
                actions["data_action"].astype(str).str.strip() != "",
                actions["data_action_fallback"].fillna(""),
            )
            actions = actions.drop(columns=["data_action_fallback"])

    for column in OPTIMIZATION_ACTION_COLUMNS:
        if column not in actions.columns:
            actions[column] = ""
    return actions[ERROR_ACTION_COLUMNS]


def get_priority_error_samples(error_df, optimization_df, limit=20):
    """Return priority error examples with their matched data improvement action."""
    df = _copy_metrics_frame(error_df)
    if df.empty or "error_type" not in df.columns:
        return _empty_metrics_frame(PRIORITY_ERROR_SAMPLE_COLUMNS)

    for column in ["case_id", "model_name", "severity", "error_description"]:
        if column not in df.columns:
            df[column] = ""

    plan = normalize_optimization_plan(optimization_df)
    samples = df.merge(plan, on="error_type", how="left")

    if "optimization_action" in samples.columns:
        samples["data_action"] = samples.get("data_action", "")
        samples["data_action"] = samples["data_action"].fillna("")
        samples["data_action"] = samples["data_action"].where(
            samples["data_action"].astype(str).str.strip() != "",
            samples["optimization_action"].fillna(""),
        )

    for column in PRIORITY_ERROR_SAMPLE_COLUMNS:
        if column not in samples.columns:
            samples[column] = ""

    severity_rank = {"高": 0, "中": 1, "低": 2, "high": 0, "medium": 1, "low": 2}
    samples["_severity_rank"] = samples["severity"].map(severity_rank).fillna(9)
    samples = samples.sort_values(["_severity_rank", "error_type", "case_id", "model_name"])
    if limit:
        samples = samples.head(limit)
    return samples[PRIORITY_ERROR_SAMPLE_COLUMNS]


# Optimization comparison metrics
OPTIMIZATION_COMPARISON_COLUMNS = [
    "experiment_id",
    "version",
    "change_type",
    "change_description",
    "avg_score",
    "hallucination_rate",
    "evidence_score",
    "reasoning_score",
    "red_line_error_rate",
    "note",
]

OPTIMIZATION_COMPARISON_NUMERIC_COLUMNS = [
    "avg_score",
    "hallucination_rate",
    "evidence_score",
    "reasoning_score",
    "red_line_error_rate",
]


def get_optimization_comparison_metrics(comparison_df: pd.DataFrame) -> pd.DataFrame:
    """Return comparison data with a stable schema and numeric metric columns."""
    if comparison_df is None or comparison_df.empty:
        return pd.DataFrame(columns=OPTIMIZATION_COMPARISON_COLUMNS)

    metrics = comparison_df.copy()
    for column in OPTIMIZATION_COMPARISON_COLUMNS:
        if column not in metrics.columns:
            metrics[column] = None

    metrics = metrics[OPTIMIZATION_COMPARISON_COLUMNS]
    for column in OPTIMIZATION_COMPARISON_NUMERIC_COLUMNS:
        metrics[column] = pd.to_numeric(metrics[column], errors="coerce")
    return metrics


def get_optimization_change_summary(comparison_df: pd.DataFrame) -> list[str]:
    """Summarize metric movement between the first and latest comparison versions."""
    metrics = get_optimization_comparison_metrics(comparison_df)
    if len(metrics) < 2:
        return []

    baseline = metrics.iloc[0]
    latest = metrics.iloc[-1]

    avg_delta = latest["avg_score"] - baseline["avg_score"]
    evidence_delta = latest["evidence_score"] - baseline["evidence_score"]
    reasoning_delta = latest["reasoning_score"] - baseline["reasoning_score"]
    hallucination_delta = latest["hallucination_rate"] - baseline["hallucination_rate"]
    red_line_delta = latest["red_line_error_rate"] - baseline["red_line_error_rate"]

    return [
        (
            f"平均分从 {baseline['avg_score']:.1f} 变化至 {latest['avg_score']:.1f}，"
            f"差值 {avg_delta:+.1f}。"
        ),
        (
            f"依据可靠性从 {baseline['evidence_score']:.1f} 变化至 {latest['evidence_score']:.1f}，"
            f"推理与场景适配从 {baseline['reasoning_score']:.1f} 变化至 {latest['reasoning_score']:.1f}。"
        ),
        (
            f"幻觉率从 {baseline['hallucination_rate']:.1%} 变化至 {latest['hallucination_rate']:.1%}，"
            f"红线错误率从 {baseline['red_line_error_rate']:.1%} 变化至 {latest['red_line_error_rate']:.1%}。"
        ),
        (
            f"最新版本记录为 {latest['change_type']}：{latest['change_description']}。"
        ),
        "以上为当前评测集观察，样本量有限，不代表真实大规模实验结论。",
    ]
