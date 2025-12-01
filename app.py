# app.py ─ 가정용 가스레인지 감소 분석 (대구)
# - 월별 가스레인지 수 시계열 (YYYY.MM, 정점 이후 하이라이트)
# - 연도별 요약표 (월평균·연간합계)
# - 시군구별 연도별 추이
# - 월 패턴 히트맵
# - 군구별 감소량 지도

from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ─────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="가정용 가스레인지 감소 분석 (대구)",
    layout="wide"
)

st.title("🏠 가정용 가스레인지 감소 분석 (대구)")

# 파일 경로 (레포 구조에 맞게)
DATA_PATH = Path(__file__).parent / "(ver2)가정용_가스레인지_사용유무.xlsx"
GEO_PATH = Path(__file__).parent / "data" / "daegu_gu.geojson"

# 엑셀 컬럼 이름 정의 (엑셀 헤더와 정확히 일치해야 함)
COL_YEAR_MONTH = "구분"          # 예: 201501, 201502 …
COL_USAGE = "용도"               # 예: 단독주택 / 공동주택
COL_PRODUCT = "상품"             # 예: 취사용 / 취사난방용 / 개별난방용
COL_DISTRICT = "시군구"          # 예: 중구 / 동구 / 서구 …
COL_RANGE_CNT = "가스레인지수"    # 엑셀의 실제 열 이름에 맞게 필요시 수정


# ─────────────────────────────────────────
# 데이터 로딩 & 전처리
# ─────────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    # 1) 헤더 없이 전체를 읽어오기 (위에 기간 설명행 등 있어도 괜찮게)
    raw = pd.read_excel(DATA_PATH, sheet_name=0, header=None)

    # 2) 첫 번째 열에서 '구분' 이라는 글자가 있는 행을 찾아 헤더로 사용
    first_col = raw.iloc[:, 0].astype(str).str.strip()
    header_rows = first_col[first_col == COL_YEAR_MONTH].index.tolist()

    if not header_rows:
        st.error(
            f"엑셀에서 '{COL_YEAR_MONTH}' 헤더 행을 찾지 못했다.\n"
            "엑셀 파일에서 컬럼명이 정확히 맞는지 확인해줘."
        )
        st.stop()

    header_idx = header_rows[0]

    # 3) 해당 행을 컬럼명으로, 그 아래 행들을 실제 데이터로 사용
    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header

    # 4) 완전히 빈 행 제거
    df = df.dropna(how="all")

    # 5) '구분' → 연도 / 월 추출 (YYYYMM)
    df[COL_YEAR_MONTH] = df[COL_YEAR_MONTH].astype(str).str.strip()
    df["연도"] = df[COL_YEAR_MONTH].str[:4].astype(int)
    df["월"] = df[COL_YEAR_MONTH].str[4:6].astype(int)

    # 6) 가스레인지 수 숫자형 변환 (쉼표 제거 포함)
    df[COL_RANGE_CNT] = (
        df[COL_RANGE_CNT]
        .astype(str)
        .str.replace(",", "", regex=False)
    )
    df[COL_RANGE_CNT] = (
        pd.to_numeric(df[COL_RANGE_CNT], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    # 7) 문자열 컬럼 공백 정리
    for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
        df[c] = df[c].astype(str).str.strip()

    return df


@st.cache_data
def load_geojson():
    try:
        with open(GEO_PATH, encoding="utf-8") as f:
            gj = json.load(f)
        return gj
    except FileNotFoundError:
        return None


df_raw = load_data()
geojson = load_geojson()

years = sorted(df_raw["연도"].unique())
usage_list = sorted(df_raw[COL_USAGE].unique())
product_list = sorted(df_raw[COL_PRODUCT].unique())
district_list = sorted(df_raw[COL_DISTRICT].unique())


# ─────────────────────────────────────────
# 사이드바 필터
# ─────────────────────────────────────────
st.sidebar.header("⚙️ 분석 조건")

base_year, comp_year = st.sidebar.select_slider(
    "기준연도 / 비교연도",
    options=years,
    value=(years[0], years[-1])
)

usage_sel = st.sidebar.multiselect(
    "용도 선택 (복수 선택 가능)",
    options=usage_list,
    default=usage_list
)

product_sel = st.sidebar.multiselect(
    "상품 선택 (복수 선택 가능)",
    options=product_list,
    default=product_list
)

district_sel = st.sidebar.multiselect(
    "시군구 선택 (복수 선택 가능, 비우면 전체)",
    options=district_list,
    default=district_list
)

# 필터 적용
df = df_raw.copy()
df = df[df[COL_USAGE].isin(usage_sel)]
df = df[df[COL_PRODUCT].isin(product_sel)]
if len(district_sel) > 0:
    df = df[df[COL_DISTRICT].isin(district_sel)]

st.sidebar.markdown("---")
st.sidebar.write(f"데이터 행 수: **{len(df):,}**")


# ─────────────────────────────────────────
# 탭 구성
# ─────────────────────────────────────────
tab1, tab2 = st.tabs(["① 월별·연도별 추이", "② 군구별 감소량 지도"])


# ─────────────────────────────────────────
# ① 월별·연도별 추이
# ─────────────────────────────────────────
with tab1:
    st.subheader("① 월별·연도별 가스레인지 수 추이")

    # ── (A) 월별 시계열 (YYYY.MM 단위) ─────────────────────
    # 월(YYYYMM) 단위 집계
    month_series = (
        df.groupby(COL_YEAR_MONTH, as_index=False)[COL_RANGE_CNT]
        .sum()
    )
    month_series["date"] = pd.to_datetime(month_series[COL_YEAR_MONTH], format="%Y%m")
    month_series = month_series.sort_values("date")

    # 정점(최대 월) 찾기
    peak_idx = month_series[COL_RANGE_CNT].idxmax()
    peak_date = month_series.loc[peak_idx, "date"]
    peak_val = float(month_series.loc[peak_idx, COL_RANGE_CNT])
    peak_label = peak_date.strftime("%Y.%m")

    start_label = month_series["date"].iloc[0].strftime("%Y.%m")
    end_label = month_series["date"].iloc[-1].strftime("%Y.%m")

    st.markdown(
        f"#### 🔹 월별 가스레인지 수 시계열 (YYYY.MM)  \n"
        f"- 기간: **{start_label} ~ {end_label}**  \n"
        f"- 기준연도: **{base_year}년**, 비교연도: **{comp_year}년**, 정점: **{peak_label}**"
    )

    # 정점 이전/이후로 나눠서 라인 색을 다르게 표시
    pre_mask = month_series["date"] <= peak_date
    post_mask = month_series["date"] >= peak_date

    fig_month_ts = go.Figure()

    # 정점 이전 구간
    fig_month_ts.add_trace(
        go.Scatter(
            x=month_series.loc[pre_mask, "date"],
            y=month_series.loc[pre_mask, COL_RANGE_CNT],
            mode="lines",
            name="정점 이전",
        )
    )

    # 정점 이후 구간
    fig_month_ts.add_trace(
        go.Scatter(
            x=month_series.loc[post_mask, "date"],
            y=month_series.loc[post_mask, COL_RANGE_CNT],
            mode="lines",
            name="정점 이후",
        )
    )

    # 전체에 마커 추가 (옵션적으로 좀 더 또렷하게)
    fig_month_ts.add_trace(
        go.Scatter(
            x=month_series["date"],
            y=month_series[COL_RANGE_CNT],
            mode="markers",
            name="월별 값",
            marker=dict(size=4),
            showlegend=False,
        )
    )

    # 정점 월 수직선 + 영역 하이라이트 (후반부)
    fig_month_ts.add_vline(x=peak_date, line_dash="dash", line_width=2)

    # 정점 이후 영역 색칠 (살짝 강조)
    fig_month_ts.add_vrect(
        x0=peak_date,
        x1=month_series["date"].iloc[-1],
        fillcolor="LightSalmon",
        opacity=0.15,
        layer="below",
        line_width=0,
    )

    # 정점 포인트 annotation (그래프 안, 위로 튀어나가지 않게)
    fig_month_ts.add_annotation(
        x=peak_date,
        y=peak_val,
        text=f"정점 {peak_label}",
        showarrow=True,
        arrowhead=2,
        ax=0,
        ay=-40,  # 위쪽으로 약간 띄우기
    )

    fig_month_ts.update_layout(
        title="월별 가스레인지 수 추이 (정점 이후 구간 하이라이트)",
        yaxis_title="가스레인지 수",
        xaxis_title="기간 (YYYY.MM)",
        hovermode="x unified",
        margin=dict(l=40, r=20, t=80, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
    )
    # x축 표시 형식 YYYY.MM
    fig_month_ts.update_xaxes(tickformat="%Y.%m")

    st.plotly_chart(fig_month_ts, use_container_width=True)

    st.markdown("---")

    # ── (B) 연도별 요약표 (월평균·연간합계) ─────────────────────
    st.markdown("#### 🔹 연도별 가스레인지 수 요약 (월평균·연간합계 기준)")

    # 연도×월별 집계 → 연도별 월평균/연간합계
    year_month = (
        df.groupby(["연도", COL_YEAR_MONTH], as_index=False)[COL_RANGE_CNT]
        .sum()
    )

    yearly = (
        year_month
        .groupby("연도", as_index=False)[COL_RANGE_CNT]
        .agg(연간합계="sum", 월평균="mean")
        .sort_values("연도")
    )

    # 전년 대비 (월평균 기준)
    yearly["전년대비 증감"] = yearly["월평균"].diff()
    yearly["전년대비 증감률(%)"] = (
        yearly["전년대비 증감"] / yearly["월평균"].shift(1) * 100
    ).round(1)

    # 기준연도 대비 (월평균 기준)
    if base_year in yearly["연도"].values:
        base_val = float(
            yearly.loc[yearly["연도"] == base_year, "월평균"].iloc[0]
        )
        yearly["기준연도 대비 증감"] = yearly["월평균"] - base_val
        yearly["기준연도 대비 증감률(%)"] = (
            (yearly["월평균"] - base_val) / base_val * 100
        ).round(1)
    else:
        yearly["기준연도 대비 증감"] = np.nan
        yearly["기준연도 대비 증감률(%)"] = np.nan

    yearly_table = yearly.copy().set_index("연도")

    # 숫자 포맷팅
    int_cols = ["연간합계", "월평균", "전년대비 증감", "기준연도 대비 증감"]
    rate_cols = ["전년대비 증감률(%)", "기준연도 대비 증감률(%)"]

    for c in int_cols:
        if c in yearly_table.columns:
            yearly_table[c] = yearly_table[c].apply(
                lambda x: "" if pd.isna(x) else f"{x:,.0f}"
            )
    for c in rate_cols:
        if c in yearly_table.columns:
            yearly_table[c] = yearly_table[c].apply(
                lambda x: "" if pd.isna(x) else f"{x:,.1f}"
            )

    st.dataframe(
        yearly_table,
        use_container_width=True,
        height=350
    )

    st.markdown("---")

    # ── (C) 시군구별 연도별 추이 ─────────────────────
    st.markdown("#### 🔹 시군구별 가스레인지 수 연도 추세 (연간합계 기준)")

    gu_year = (
        df.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
        .sum()
        .sort_values(["연도", COL_DISTRICT])
    )

    if gu_year.empty:
        st.info("현재 필터 조건에 해당하는 데이터가 없다.")
    else:
        fig_gu = px.line(
            gu_year,
            x="연도",
            y=COL_RANGE_CNT,
            color=COL_DISTRICT,
            markers=True,
            title="시군구별 연도별 가스레인지 수 추이 (연간합계)",
        )
        fig_gu.update_layout(
            yaxis_title="연간 가스레인지 수",
            xaxis_title="연도",
            hovermode="x unified",
            legend=dict(
                title="시군구",
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=40, r=20, t=60, b=40),
        )
        st.plotly_chart(fig_gu, use_container_width=True)

    st.markdown("---")

    # ── (D) 월 패턴 히트맵 ─────────────────────
    st.markdown(
        "#### 🔹 연도 × 월 패턴 히트맵  \n"
        "- 각 연도의 월별 가스레인지 수 수준을 한눈에 보는 용도."
    )

    monthly_for_heat = (
        df.groupby(["연도", "월"], as_index=False)[COL_RANGE_CNT]
        .sum()
    )

    heat_pivot = monthly_for_heat.pivot(index="월", columns="연도", values=COL_RANGE_CNT)
    heat_pivot = heat_pivot.sort_index()  # 월 1~12 순서

    fig_heat = px.imshow(
        heat_pivot,
        labels=dict(x="연도", y="월", color="가스레인지 수"),
        aspect="auto",
        title="연도 × 월 가스레인지 수 히트맵",
    )
    fig_heat.update_xaxes(side="top")
    st.plotly_chart(fig_heat, use_container_width=True)


# ─────────────────────────────────────────
# ② 군구별 감소량 지도
# ─────────────────────────────────────────
with tab2:
    st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도")

    # 기준연도 & 비교연도만 추출 (연간합계 기준)
    map_df = df[df["연도"].isin([base_year, comp_year])]

    grouped = (
        map_df.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
        .sum()
    )

    pivot_map = (
        grouped.pivot(index=COL_DISTRICT, columns="연도", values=COL_RANGE_CNT)
        .fillna(0)
    )

    if base_year not in pivot_map.columns:
        pivot_map[base_year] = 0
    if comp_year not in pivot_map.columns:
        pivot_map[comp_year] = 0

    pivot_map["감소량(기준-비교)"] = pivot_map[base_year] - pivot_map[comp_year]
    pivot_map["감소율(%)"] = np.where(
        pivot_map[base_year] > 0,
        pivot_map["감소량(기준-비교)"] / pivot_map[base_year] * 100,
        np.nan
    )
    pivot_map["감소율(%)"] = pivot_map["감소율(%)"].round(1)

    map_table = pivot_map.reset_index().rename(
        columns={
            base_year: f"{base_year}년 가스레인지 수(연간합계)",
            comp_year: f"{comp_year}년 가스레인지 수(연간합계)",
        }
    )

    c1, c2 = st.columns([2, 3])

    with c1:
        st.markdown(
            f"**군구별 가스레인지 수 및 감소량 (연간합계 기준)**  \n"
            f"(기준연도: {base_year}년, 비교연도: {comp_year}년)"
        )
        st.dataframe(
            map_table.set_index(COL_DISTRICT),
            use_container_width=True,
            height=450
        )

    with c2:
        if geojson is None:
            st.warning(
                "대구 시군구 GeoJSON(`data/daegu_gu.geojson`)이 없어서 지도를 표시할 수 없다.\n\n"
                "GeoJSON 파일을 추가하고 `featureidkey`를 실제 속성명에 맞게 수정해줘."
            )
        else:
            # featureidkey는 GeoJSON의 속성명에 맞게 수정 필요
            feature_key = "properties.SIG_KOR_NM"

            fig_map = px.choropleth(
                map_table,
                geojson=geojson,
                locations=COL_DISTRICT,
                featureidkey=feature_key,
                color="감소량(기준-비교)",
                hover_name=COL_DISTRICT,
                hover_data={
                    f"{base_year}년 가스레인지 수(연간합계)": ":,",
                    f"{comp_year}년 가스레인지 수(연간합계)": ":,",
                    "감소량(기준-비교)": ":,",
                    "감소율(%)": True,
                },
                title=f"{base_year}년 → {comp_year}년 군구별 가스레인지 감소량 (연간합계 기준)",
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            fig_map.update_layout(
                margin=dict(l=0, r=0, t=40, b=0),
                coloraxis_colorbar=dict(title="감소량")
            )
            st.plotly_chart(fig_map, use_container_width=True)

    st.markdown(
        """
        - **감소량(기준-비교)** : 기준연도 연간 가스레인지 수 − 비교연도 연간 가스레인지 수  
        - **감소율(%)** : 감소량 ÷ 기준연도 연간 가스레인지 수 × 100
        """
    )
