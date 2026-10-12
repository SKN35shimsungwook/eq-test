"""결과 화면 차트 (Altair / Vega-Lite). 한 가지 색(앱 기본색)만 쓰고, 값은 툴팁과 표로도 제공한다."""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd

from core.scoring import NORMAL

PRIMARY = "#0F766E"
MUTED = "#9ca3af"


def distribution_chart(index: float) -> alt.LayerChart:
    """평균 100·표준편차 15 정규분포 위에 내 위치를 표시한다."""
    xs = np.arange(40, 160.5, 0.5)
    df = pd.DataFrame({"x": xs, "y": [NORMAL.pdf((x - 100) / 15) for x in xs]})
    df["상위"] = [f"{(1 - NORMAL.cdf((x - 100) / 15)) * 100:.1f}%" for x in xs]
    df["mine"] = df["x"] <= index
    base = alt.Chart(df).encode(
        x=alt.X("x:Q", title="EQ (평균 100, 표준편차 15)", scale=alt.Scale(domain=[40, 160]),
                axis=alt.Axis(values=list(range(40, 161, 15)), grid=False)),
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[0, 0.43])),
    )
    whole = base.mark_area(color=PRIMARY, opacity=0.12, interpolate="monotone")
    below = base.transform_filter("datum.mine").mark_area(color=PRIMARY, opacity=0.45, interpolate="monotone")
    hover = base.mark_rule(color=MUTED, strokeWidth=1, opacity=0).encode(
        tooltip=[alt.Tooltip("x:Q", title="지수"), alt.Tooltip("상위:N", title="상위")],
    ).add_params(alt.selection_point(on="pointerover", nearest=True, fields=["x"], empty=False))
    marks = pd.DataFrame({"x": [100.0, index], "label": ["평균 100", f"나 {index:.0f}"],
                          "dash": [True, False]})
    rule = alt.Chart(marks).mark_rule(strokeWidth=2).encode(
        x="x:Q",
        color=alt.condition("datum.dash", alt.value(MUTED), alt.value(PRIMARY)),
        strokeDash=alt.condition("datum.dash", alt.value([4, 4]), alt.value([1, 0])),
    )
    text = alt.Chart(marks).mark_text(dy=-6, fontWeight="bold", baseline="bottom").encode(
        x="x:Q", y=alt.value(12), text="label:N",
        color=alt.condition("datum.dash", alt.value("#6b7280"), alt.value(PRIMARY)),
    )
    return (whole + below + hover + rule + text).properties(height=220).configure_view(stroke=None)


def profile_chart(rows: list[dict]) -> alt.LayerChart:
    """영역별 지수와 90% 신뢰구간. rows: 영역, 지수, 하한, 상한."""
    df = pd.DataFrame(rows)
    order = list(df["영역"])
    y = alt.Y("영역:N", sort=order, title=None, axis=alt.Axis(labelFontSize=13, ticks=False, domain=False))
    x_scale = alt.Scale(domain=[50, 150])
    tooltip = [alt.Tooltip("영역:N"), alt.Tooltip("지수:Q", format=".0f"),
               alt.Tooltip("범위:N", title="90% 범위")]
    df["범위"] = df["하한"].round().astype(int).astype(str) + "–" + df["상한"].round().astype(int).astype(str)
    base = alt.Chart(df)
    band = base.mark_rule(strokeWidth=6, color=PRIMARY, opacity=0.25, strokeCap="round").encode(
        y=y, x=alt.X("하한:Q", scale=x_scale, title="영역 지수 (평균 100)",
                     axis=alt.Axis(values=list(range(55, 146, 15)))),
        x2="상한:Q", tooltip=tooltip)
    dot = base.mark_point(filled=True, size=140, color=PRIMARY, stroke="white", strokeWidth=2).encode(
        y=y, x=alt.X("지수:Q", scale=x_scale), tooltip=tooltip)
    label = base.mark_text(dx=14, align="left", fontWeight="bold", color="#374151").encode(
        y=y, x=alt.X("지수:Q", scale=x_scale), text=alt.Text("지수:Q", format=".0f"))
    mean = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(x="x:Q")
    return (mean + band + dot + label).properties(height=44 * len(df) + 30).configure_view(stroke=None)


def trend_chart(points: list[dict]) -> alt.LayerChart:
    """차수별 점수(회색)와 누적 합산 점수(기본색)를 90% 범위와 함께. points: 차수, 종류, 지수, 하한, 상한."""
    df = pd.DataFrame(points)
    order = list(dict.fromkeys(df["차수"]))
    color = alt.Color("종류:N", scale=alt.Scale(domain=["차수별", "누적 합산"], range=[MUTED, PRIMARY]),
                      legend=alt.Legend(orient="top", title=None))
    x = alt.X("차수:N", sort=order, title=None, axis=alt.Axis(labelAngle=0))
    off = alt.XOffset("종류:N", sort=["차수별", "누적 합산"])
    tip = [alt.Tooltip("차수:N"), alt.Tooltip("종류:N"), alt.Tooltip("지수:Q", format=".0f"),
           alt.Tooltip("범위:N", title="90% 범위")]
    df["범위"] = df["하한"].round().astype(int).astype(str) + "–" + df["상한"].round().astype(int).astype(str)
    base = alt.Chart(df)
    band = base.mark_rule(strokeWidth=5, opacity=0.35, strokeCap="round").encode(
        x=x, xOffset=off, y=alt.Y("하한:Q", scale=alt.Scale(zero=False), title="EQ"), y2="상한:Q",
        color=color, tooltip=tip)
    dot = base.mark_point(filled=True, size=110, stroke="white", strokeWidth=2).encode(
        x=x, xOffset=off, y="지수:Q", color=color, tooltip=tip)
    label = base.mark_text(dy=-14, fontWeight="bold", fontSize=12).encode(
        x=x, xOffset=off, y="지수:Q", text=alt.Text("지수:Q", format=".0f"), color=color)
    mean = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(y="y:Q")
    return (mean + band + dot + label).properties(height=240).configure_view(stroke=None)


def level_chart(by_level: dict[int, tuple[int, int]], labels: dict[int, str]) -> alt.LayerChart:
    """난이도별 정답률 막대."""
    df = pd.DataFrame([{"난이도": labels[lv], "정답률": c / n, "맞힘": f"{c}/{n}"} for lv, (c, n) in by_level.items()])
    order = [labels[lv] for lv in by_level]
    base = alt.Chart(df).encode(
        x=alt.X("난이도:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        tooltip=["난이도", alt.Tooltip("정답률:Q", format=".0%"), alt.Tooltip("맞힘:N", title="맞힌 문항")])
    bar = base.mark_bar(color=PRIMARY, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.6}).encode(
        y=alt.Y("정답률:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%"), title="정답률"))
    text = base.mark_text(dy=-8, color="#374151").encode(y="정답률:Q", text="맞힘:N")
    half = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(y="y:Q")
    return (bar + text + half).properties(height=200).configure_view(stroke=None)


def deep_trace_chart(rows: list[dict]) -> alt.FacetChart:
    """심층검사에서 문항을 풀 때마다 영역 점수 범위가 좁혀지는 모습 (영역별 작은 그래프)."""
    df = pd.DataFrame(rows)
    df["범위"] = df["하한"].round().astype(int).astype(str) + "–" + df["상한"].round().astype(int).astype(str)
    tip = ["단계", alt.Tooltip("지수:Q", format=".0f"), alt.Tooltip("범위:N", title="90% 범위"), "난이도", "결과"]
    x = alt.X("단계:O", title="심층검사 문항", axis=alt.Axis(labelAngle=0, labelExpr="datum.value == 0 ? '시작' : datum.value"))
    base = alt.Chart().encode(x=x)
    band = base.mark_area(color=PRIMARY, opacity=0.15).encode(
        y=alt.Y("하한:Q", scale=alt.Scale(zero=False), title="영역 지수"), y2="상한:Q")
    line = base.mark_line(color=PRIMARY, strokeWidth=2).encode(y="지수:Q")
    dots = base.mark_point(filled=True, size=70, stroke="white", strokeWidth=1.5).encode(
        y="지수:Q", tooltip=tip,
        shape=alt.Shape("결과:N", scale=alt.Scale(domain=["출발", "정답", "오답"], range=["circle", "circle", "cross"]),
                        legend=alt.Legend(orient="top", title=None)),
        color=alt.Color("결과:N", scale=alt.Scale(domain=["출발", "정답", "오답"], range=[MUTED, PRIMARY, "#dc2626"]),
                        legend=alt.Legend(orient="top", title=None)))
    return alt.layer(band, line, dots, data=df).properties(width=190, height=150).facet(
        facet=alt.Facet("영역:N", title=None, sort=list(dict.fromkeys(df["영역"]))), columns=3
    ).resolve_scale(y="independent").configure_view(stroke=None)


def self_gap_chart(rows: list[dict]) -> alt.LayerChart:
    """자기평가(회색 빈 점)와 실제 수행(기본색 점)을 영역마다 선으로 잇는다. rows: 영역, 자기평가, 실제."""
    df = pd.DataFrame(rows)
    order = list(df["영역"])
    y = alt.Y("영역:N", sort=order, title=None, axis=alt.Axis(labelFontSize=13, ticks=False, domain=False))
    x_scale = alt.Scale(domain=[50, 150])
    tip = [alt.Tooltip("영역:N"), alt.Tooltip("자기평가:Q", format=".0f"), alt.Tooltip("실제:Q", format=".0f"),
           alt.Tooltip("판정:N")]
    base = alt.Chart(df)
    link = base.mark_rule(color=MUTED, strokeWidth=2).encode(
        y=y, x=alt.X("자기평가:Q", scale=x_scale, title="EQ 척도 (평균 100)", axis=alt.Axis(values=list(range(55, 146, 15)))),
        x2="실제:Q", tooltip=tip)
    long = df.melt(id_vars=["영역", "판정"], value_vars=["자기평가", "실제"], var_name="구분", value_name="값")
    dots = alt.Chart(long).mark_point(size=140, strokeWidth=2.5).encode(
        y=y, x=alt.X("값:Q", scale=x_scale),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["자기평가", "실제"], range=[MUTED, PRIMARY]),
                        legend=alt.Legend(orient="top", title=None)),
        fill=alt.Fill("구분:N", scale=alt.Scale(domain=["자기평가", "실제"], range=["white", PRIMARY]), legend=None),
        tooltip=["영역", "구분", alt.Tooltip("값:Q", format=".0f"), "판정"])
    mean = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(x="x:Q")
    return (mean + link + dots).properties(height=40 * len(df) + 40).configure_view(stroke=None)


def axes_chart(rows: list[dict]) -> alt.LayerChart:
    """세 축(−1~1)을 가운데 0 기준 막대로. rows: 축, 왼쪽, 오른쪽, 값."""
    df = pd.DataFrame(rows)
    df["표시"] = df["값"].map(lambda v: f"{abs(v):.0%} " + ("오른쪽" if v > 0 else "왼쪽" if v < 0 else "가운데"))
    y = alt.Y("축:N", sort=list(df["축"]), title=None, axis=None)
    x = alt.X("값:Q", scale=alt.Scale(domain=[-1, 1]), title=None, axis=alt.Axis(values=[-1, 0, 1], labels=False, ticks=False))
    base = alt.Chart(df)
    track = base.mark_bar(color="#e5e7eb", height=14, cornerRadius=7).encode(
        y=y, x=alt.datum(-1), x2=alt.datum(1))
    bar = base.mark_bar(color=PRIMARY, height=14, cornerRadius=7).encode(
        y=y, x=alt.datum(0), x2="값:Q", tooltip=["축", alt.Tooltip("표시:N", title="기울기")])
    left = base.mark_text(align="left", dx=4, dy=-16, color="#6b7280").encode(y=y, x=alt.datum(-1), text="왼쪽:N")
    right = base.mark_text(align="right", dx=-4, dy=-16, color="#6b7280").encode(y=y, x=alt.datum(1), text="오른쪽:N")
    mid = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=MUTED, strokeDash=[3, 3]).encode(x="x:Q")
    return (track + bar + mid + left + right).properties(height=60 * len(df) + 10).configure_view(stroke=None)
