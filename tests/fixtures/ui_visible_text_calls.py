MODE_PREFIX = "演示"
MODE_LABEL = MODE_PREFIX + "模式"
SCORE_ACTION = "生成 AI " + "评分"
st = None  # This fixture is parsed as source and is never imported or executed.


@st.dialog("演示弹层")
def show_dialog():
    pass


def render(st, fake, mode, render_numbered_section):
    col, _other = st.columns(2)
    col.selectbox(
        MODE_LABEL,
        ["正式模式", SCORE_ACTION],
        key="从演示结果文件恢复",
        help="安全说明",
    )
    st.warning(body=f"演示恢复：{mode}")
    ordered_bad = "先前禁语应保留"
    st.warning(ordered_bad)
    ordered_bad = "安全"
    later_bad = "安全"
    st.caption(later_bad)
    later_bad = "后置禁语不应出现"
    with st.spinner("演示加载"):
        st.checkbox("演示选择")
        st.slider("演示滑杆", 0, 10)
        st.form_submit_button("演示提交")
    render_numbered_section("01", "可见章节", caption="可见说明")
    fake.error("从演示结果文件恢复")
    fake.title("假标题不可见")
