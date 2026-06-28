from __future__ import annotations

import pandas as pd


SCORE_DIMENSIONS = [
    ("accuracy_score", "专业准确性"),
    ("reasoning_score", "推理与场景适配"),
    ("coverage_score", "风险覆盖"),
    ("evidence_score", "依据可靠性"),
    ("expression_score", "专业表达"),
]


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def get_overview_metrics(data_bundle: dict) -> dict[str, float | int | None]:
    data = data_bundle["data"]
    average_score = None
    if "total_score" in data.scores:
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
        return pd.DataFrame(columns=["error_type", "count"])
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
    if model_outputs_df.empty or "case_id" not in model_outputs_df:
        return pd.DataFrame(columns=model_outputs_df.columns)

    case_outputs = model_outputs_df[model_outputs_df["case_id"] == case_id]
    merge_keys = ["output_id", "case_id", "model_name"]
    if not scores_df.empty and has_columns(scores_df, merge_keys):
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
