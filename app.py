import pandas as pd
import streamlit as st

from src.data_service import DataLoadError, load_all_data


st.set_page_config(page_title="FinDueEval MVP", layout="wide")


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True


def write_text_field(label: str, value) -> None:
    st.write(f"**{label}：** {value if has_value(value) else '暂无'}")


def write_list_field(label: str, value) -> None:
    st.write(f"**{label}：**")
    if isinstance(value, list) and value:
        for item in value:
            st.write(f"- {item}")
    elif has_value(value):
        st.write(value)
    else:
        st.write("暂无")


def show_model_score(row: pd.Series) -> None:
    total_score = row.get("total_score")
    if not has_value(total_score):
        st.write("**评分：** 当前模型回答尚未评分。")
        return

    accuracy = row.get("accuracy_score", "暂无")
    reasoning = row.get("reasoning_score", "暂无")
    coverage = row.get("coverage_score", "暂无")
    evidence = row.get("evidence_score", "暂无")
    expression = row.get("expression_score", "暂无")
    st.write(
        f"**得分：** 总分 {float(total_score):.0f}"
        f"（专业准确性 {accuracy}，推理与场景适配 {reasoning}，风险覆盖 {coverage}，"
        f"依据可靠性 {evidence}，专业表达 {expression}）"
    )


def render_overview(tasks_df, model_outputs_df, scores_df, error_df, optimization_df) -> None:
    st.header("项目总览")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("任务数", len(tasks_df))

    model_count = model_outputs_df["model_name"].nunique() if "model_name" in model_outputs_df else 0
    col2.metric("模型数", model_count)

    average_score = scores_df["total_score"].mean() if "total_score" in scores_df else None
    col3.metric("平均总分", f"{average_score:.1f}" if has_value(average_score) else "暂无")
    col4.metric("错误标签数", len(error_df))
    col5.metric("优化建议数", len(optimization_df))

    st.subheader("各模型平均得分")
    if not scores_df.empty and has_columns(scores_df, ["model_name", "total_score"]):
        model_avg = scores_df.groupby("model_name")["total_score"].mean().reset_index()
        st.bar_chart(data=model_avg, x="model_name", y="total_score")
    else:
        st.info("暂无评分数据，暂不能展示模型平均得分。")

    st.subheader("错误类型分布")
    if not error_df.empty and "error_type" in error_df:
        error_counts = error_df["error_type"].value_counts().reset_index()
        error_counts.columns = ["error_type", "count"]
        st.bar_chart(error_counts, x="error_type", y="count")
    else:
        st.info("暂无错误标签数据，暂不能展示错误类型分布。")


def render_task_list(tasks_df) -> None:
    st.header("任务列表")
    if tasks_df.empty:
        st.info("暂无任务数据。")
        return

    domains = ["全部"] + sorted(tasks_df["domain"].dropna().unique().tolist())
    selected_domain = st.selectbox("选择领域", domains)
    if selected_domain != "全部":
        filtered_tasks = tasks_df[tasks_df["domain"] == selected_domain]
    else:
        filtered_tasks = tasks_df
    st.dataframe(filtered_tasks, use_container_width=True)


def render_gold_answer(gold_answer_map, selected_case: str) -> None:
    st.subheader("Gold Answer")
    ga = gold_answer_map.get(selected_case)
    if not ga:
        st.info("该题暂未配置 Gold Answer，不影响查看模型回答，但无法展示标准答案对照。")
        return

    write_text_field("结论", ga.get("conclusion"))
    write_text_field("判断依据", ga.get("basis"))
    write_text_field("分析逻辑", ga.get("analysis"))
    write_text_field("需核查资料", ga.get("materials_to_check"))
    write_text_field("风险边界", ga.get("risk_boundary"))
    write_list_field("必须覆盖要点", ga.get("must_have_points"))
    write_list_field("红线错误", ga.get("red_line_errors"))


def render_model_outputs(model_outputs_df, scores_df, error_df, selected_case: str) -> None:
    st.subheader("模型回答与评分")
    case_outputs = model_outputs_df[model_outputs_df["case_id"] == selected_case]
    if case_outputs.empty:
        st.info("该题暂无模型回答。")
        return

    merge_keys = ["output_id", "case_id", "model_name"]
    if not scores_df.empty and has_columns(scores_df, merge_keys):
        merged = pd.merge(case_outputs, scores_df, on=merge_keys, how="left")
    else:
        merged = case_outputs.copy()

    for _, row in merged.iterrows():
        st.write(f"### {row['model_name']}")
        st.write(row["answer_text"])
        show_model_score(row)

        if not error_df.empty and "output_id" in error_df:
            errs = error_df[error_df["output_id"] == row["output_id"]]
        else:
            errs = pd.DataFrame()

        if not errs.empty:
            st.write("**错误标签：**")
            for _, error in errs.iterrows():
                st.write(
                    f"- [{error['error_type']} - {error['severity']}] {error['error_description']} "
                    f"=> **纠正:** {error['correction']}；**优化:** {error['optimization_action']}"
                )
        else:
            st.write("**错误标签：** 当前回答暂无错误标签。")


def render_case_detail(tasks_df, gold_answer_map, model_outputs_df, scores_df, error_df) -> None:
    st.header("单题详情")
    if tasks_df.empty:
        st.info("暂无任务数据，无法展示单题详情。")
        return

    case_ids = tasks_df["case_id"].tolist()
    selected_case = st.selectbox("选择案例 ID", case_ids)
    task_rows = tasks_df[tasks_df["case_id"] == selected_case]
    if task_rows.empty:
        st.warning("未找到该案例的任务信息。")
        return

    task_info = task_rows.iloc[0]
    st.subheader("题目与背景")
    write_text_field("领域", task_info.get("domain"))
    write_text_field("场景", task_info.get("scenario"))
    write_text_field("难度", task_info.get("difficulty"))
    write_text_field("问题", task_info.get("question"))
    write_text_field("背景", task_info.get("context"))
    write_text_field("期望能力", task_info.get("expected_capability"))
    write_text_field("风险级别", task_info.get("risk_level"))

    render_gold_answer(gold_answer_map, selected_case)
    render_model_outputs(model_outputs_df, scores_df, error_df, selected_case)


def render_error_analysis(scores_df, error_df, optimization_df) -> None:
    st.header("错误归因与优化建议")

    st.subheader("错误类型分布")
    if not error_df.empty and "error_type" in error_df:
        error_counts = error_df["error_type"].value_counts().reset_index()
        error_counts.columns = ["error_type", "count"]
        st.bar_chart(error_counts, x="error_type", y="count")
    else:
        st.info("暂无错误标签数据，暂不能展示错误类型分布。")

    st.subheader("各模型平均得分对比")
    if not scores_df.empty and has_columns(scores_df, ["model_name", "total_score"]):
        model_avg = scores_df.groupby("model_name")["total_score"].mean().reset_index()
        st.bar_chart(model_avg, x="model_name", y="total_score")
    else:
        st.info("暂无评分数据，暂不能展示模型平均得分。")

    st.subheader("优化建议")
    if optimization_df.empty:
        st.info("暂无优化建议数据。")
    else:
        st.dataframe(optimization_df, use_container_width=True)


try:
    data = load_all_data()
except DataLoadError as exc:
    st.sidebar.title("导航")
    st.error(str(exc))
    st.stop()

tasks_df = data.tasks
gold_answer_map = data.gold_answer_map
model_outputs_df = data.model_outputs
scores_df = data.scores
error_df = data.errors
optimization_df = data.optimizations

st.sidebar.title("导航")
page = st.sidebar.radio("选择页面", ("项目总览", "任务列表", "单题详情", "错误归因与优化建议"))

if page == "项目总览":
    render_overview(tasks_df, model_outputs_df, scores_df, error_df, optimization_df)
elif page == "任务列表":
    render_task_list(tasks_df)
elif page == "单题详情":
    render_case_detail(tasks_df, gold_answer_map, model_outputs_df, scores_df, error_df)
elif page == "错误归因与优化建议":
    render_error_analysis(scores_df, error_df, optimization_df)
