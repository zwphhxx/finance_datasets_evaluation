from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

# Unified chart palette so every page shares one visual language instead of the
# default Streamlit colors. Models map to the first colors in declared order.
BRAND_BLUE = "#12345a"
SERIES_PALETTE = ["#12345a", "#33567e", "#5b7ba3", "#88a1c2", "#b9c9dc"]
AXIS_LABEL_COLOR = "#607089"


def _base_config(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor=AXIS_LABEL_COLOR,
            titleColor=AXIS_LABEL_COLOR,
            grid=False,
            domainColor="#d8dee8",
            tickColor="#d8dee8",
        )
        .configure_legend(labelColor=AXIS_LABEL_COLOR, titleColor=AXIS_LABEL_COLOR)
    )


def themed_bar_chart(
    data: pd.DataFrame,
    x: str,
    y: str,
    x_title: str,
    y_title: str,
    color_field: str | None = None,
    color_title: str | None = None,
    y_format: str | None = None,
) -> None:
    """Render a brand-themed grouped/simple bar chart with Chinese axis titles."""
    encodings = {
        "x": alt.X(f"{x}:N", title=x_title, axis=alt.Axis(labelAngle=0)),
        "y": alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=True)),
        "tooltip": list(data.columns),
    }
    if color_field:
        encodings["color"] = alt.Color(
            f"{color_field}:N",
            title=color_title or color_field,
            scale=alt.Scale(range=SERIES_PALETTE),
        )
        encodings["xOffset"] = alt.XOffset(f"{color_field}:N")
    else:
        encodings["color"] = alt.value(BRAND_BLUE)

    chart = alt.Chart(data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, size=56).encode(**encodings)
    if y_format:
        labels = chart.mark_text(dy=-6, color=AXIS_LABEL_COLOR, fontSize=12, fontWeight=600).encode(
            text=alt.Text(f"{y}:Q", format=y_format)
        )
        chart = chart + labels
    st.altair_chart(_base_config(chart), use_container_width=True)
