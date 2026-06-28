from __future__ import annotations

import pandas as pd


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
