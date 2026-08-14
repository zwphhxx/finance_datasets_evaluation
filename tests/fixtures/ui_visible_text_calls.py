def render(st, col, mode, render_numbered_section):
    col.selectbox(
        "演示模式",
        ["正式模式", "生成 AI 评分"],
        key="从演示结果文件恢复",
        help="安全说明",
    )
    st.warning(body=f"演示恢复：{mode}")
    render_numbered_section("01", "可见章节", caption="可见说明")
