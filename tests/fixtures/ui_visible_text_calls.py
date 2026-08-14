MODE_PREFIX = "演示"
MODE_LABEL = MODE_PREFIX + "模式"
SCORE_ACTION = "生成 AI " + "评分"


def render(st, fake, mode, render_numbered_section):
    col, _other = st.columns(2)
    col.selectbox(
        MODE_LABEL,
        ["正式模式", SCORE_ACTION],
        key="从演示结果文件恢复",
        help="安全说明",
    )
    st.warning(body=f"演示恢复：{mode}")
    render_numbered_section("01", "可见章节", caption="可见说明")
    fake.error("从演示结果文件恢复")
    fake.title("假标题不可见")
