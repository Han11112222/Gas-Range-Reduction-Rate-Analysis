# app.py ─ 가정용 가스레인지 감소 분석 (대구 + 경산)
# - ① 월별·연도별 추이
# - ② 대구시 8개 구·군 + 경산시 감소량 지도

from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────
st.set_page_config(
    page_title="가정용 가스레인지 감소 분석 (대구)",
    layout="wide"
)
st.title("🏠 가정용 가스레인지 감소 분석 (대구)")

# 데이터 / GeoJSON 경로
DATA_PATH = Path(__file__).parent / "(ver2)가정용_가스레인지_사용유무.xlsx"
GEO_PATH = Path(__file__).parent / "data" / "daegu_gyeongsan_sgg.geojson"

# 엑셀 컬럼 이름
COL_YEAR_MONTH = "구분"        # 201501, 201502 …
COL_USAGE = "용도"             # 단독주택 / 공동주택
COL_PRODUCT = "상품"           # 취사용 / 취사난방용 / 개별난방용
COL_DISTRICT = "시군구"        # 중구 / 동구 / 경산시 …
COL_RANGE_CNT = "가스레인지수"   # 엑셀 수량 컬럼

# 대구 + 경산 시군구(표/지도 정렬 기준)
TARGET_SIGUNGU = [
    "중구", "동구", "서구", "남구", "북구",
    "수성구", "달서구", "달성군",
    "경산시",
]

# ─────────────────────────────────────
# 데이터 로딩
# ─────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    """엑셀 원시파일에서 분석용 데이터프레임 생성"""
    # 1) 헤더 없이 읽어서 헤더 행 찾기
    raw = pd.read_excel(DATA_PATH, sheet_name=0, header=None)

    # 첫 열에서 '구분' 행을 찾는다
    first_col = raw.iloc[:, 0].astype(str).str.strip()
    header_rows = first_col[first_col == COL_YEAR_MONTH].index.tolist()
    if not header_rows:
        st.error(f"엑셀에서 '{COL_YEAR_MONTH}' 헤더 행을 찾지 못했어. 엑셀 컬럼명을 확인해줘.")
        st.stop()
    header_idx = header_rows[0]

    # 2) 헤더/데이터 분리
    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    # 3) 구분 → 연도, 월
    df[COL_YEAR_MONTH] = df[COL_YEAR_MONTH].astype(str).str.strip()
    df["연도"] = df[COL_YEAR_MONTH].str[:4].astype(int)
    df["월"] = df[COL_YEAR_MONTH].str[4:6].astype(int)

    # 4) 가스레인지 수 숫자 변환
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

    # 5) 문자열 컬럼 정리
    for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
        df[c] = df[c].astype(str).str.strip()

    return df


@st.cache_data
def load_geojson():
    """대구+경산 시군구 GeoJSON 로딩"""
    try:
        with open(GEO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


df_raw = load_data()
geojson = load_geojson()

years = sorted(df_raw["연도"].unique())
usage_list = sorted(df_raw[COL_USAGE].unique())
product_list = sorted(df_raw[COL_PRODUCT].unique())
district_list = sorted(df_raw[COL_DISTRICT].unique())

# ─────────────────────────────────────
# 사이드바 필터
# ─────────────────────────────────────
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

# ─────────────────────────────────────
# 탭 구성
# ─────────────────────────────────────
tab1, tab2 = st.tabs(["① 월별·연도별 추이", "② 군구별 감소량 지도"])

# ─────────────────────────────────────
# ① 월별·연도별 추이
# ─────────────────────────────────────
with tab1:
    st.subheader("① 월별·연도별 가스레인지 수 추이")

    # 월 단위 집계
    month_series = (
        df.groupby(COL_YEAR_MONTH, as_index=False)[COL_RANGE_CNT]
        .sum()
    )
    month_series["date"] = pd.to_datetime(month_series[COL_YEAR_MONTH], format="%Y%m")
    month_series = month_series.sort_values("date")

    if month_series.empty:
        st.info("현재 필터 조건에 해당하는 데이터가 없어.")
    else:
        # 월 정점
        peak_idx_m = month_series[COL_RANGE_CNT].idxmax()
        peak_date_m = month_series.loc[peak_idx_m, "date"]
        peak_val_m = float(month_series.loc[peak_idx_m, COL_RANGE_CNT])
        peak_label_m = peak_date_m.strftime("%Y.%m")

        start_label = month_series["date"].iloc[0].strftime("%Y.%m")
        end_label = month_series["date"].iloc[-1].strftime("%Y.%m")

        # 연도별 요약 (연간합계, 월평균)
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

        # 연간 정점/마지막
        peak_idx_y = yearly["연간합계"].idxmax()
        peak_year_y = int(yearly.loc[peak_idx_y, "연도"])
        peak_val_y = float(yearly.loc[peak_idx_y, "연간합계"])
        last_year_y = int(yearly["연도"].iloc[-1])
        last_val_y = float(yearly["연간합계"].iloc[-1])
        decline_pct_y = (last_val_y / peak_val_y - 1.0) * 100

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

        # 월간 마지막 값 정점 대비
        last_date_m = month_series["date"].iloc[-1]
        last_val_m = float(month_series[COL_RANGE_CNT].iloc[-1])
        decline_pct_m = (last_val_m / peak_val_m - 1.0) * 100
        last_label_m = last_date_m.strftime("%Y.%m")

        st.markdown(
            f"#### 🔹 가스레인지 수 추이 (연간 기본, 월간 선택 표시)  \n"
            f"- 월간 기간: **{start_label} ~ {end_label}**  \n"
            f"- 연간 기준연도: **{base_year}년**, 비교연도: **{comp_year}년**, "
            f"연간 정점: **{peak_year_y}년**, 월간 정점: **{peak_label_m}**"
        )

        show_month = st.checkbox("월간 추이 함께 보기 (YYYY.MM)", value=False)

        # ─ 연간 그래프 ─
        yearly_graph = yearly[["연도", "연간합계"]].copy()
        pre_mask_y = yearly_graph["연도"] <= peak_year_y
        post_mask_y = yearly_graph["연도"] >= peak_year_y

        fig_year_ts = go.Figure()

        fig_year_ts.add_trace(
            go.Scatter(
                x=yearly_graph.loc[pre_mask_y, "연도"],
                y=yearly_graph.loc[pre_mask_y, "연간합계"],
                mode="lines+markers",
                name="정점 이전(연간)",
                line=dict(color="lightgray", width=2, dash="dot"),
                marker=dict(size=6),
            )
        )
        fig_year_ts.add_trace(
            go.Scatter(
                x=yearly_graph.loc[post_mask_y, "연도"],
                y=yearly_graph.loc[post_mask_y, "연간합계"],
                mode="lines+markers",
                name="정점 이후(연간)",
                line=dict(color="royalblue", width=3),
                marker=dict(size=7),
            )
        )

        fig_year_ts.add_vline(x=peak_year_y, line_dash="dash", line_width=2)
        fig_year_ts.add_vrect(
            x0=peak_year_y,
            x1=yearly_graph["연도"].iloc[-1],
            fillcolor="LightSalmon",
            opacity=0.18,
            layer="below",
            line_width=0,
        )
        fig_year_ts.add_annotation(
            x=peak_year_y,
            y=peak_val_y,
            text=f"연간 정점 {peak_year_y}",
            showarrow=True,
            arrowhead=2,
            ax=0,
            ay=-40,
        )
        fig_year_ts.add_annotation(
            x=last_year_y,
            y=last_val_y,
            text=f"마지막 {last_year_y}년\n(정점 대비 {decline_pct_y:.1f}%)",
            showarrow=True,
            arrowhead=2,
            ax=40,
            ay=40,
        )

        fig_year_ts.update_layout(
            title="연간 가스레인지 수 추이 (연간합계, 정점 이후 구간 하이라이트)",
            yaxis_title="연간 가스레인지 수",
            xaxis_title="연도",
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
        st.plotly_chart(fig_year_ts, use_container_width=True)

        # ─ 월간 그래프 (옵션) ─
        if show_month:
            pre_mask_m = month_series["date"] <= peak_date_m
            post_mask_m = month_series["date"] >= peak_date_m

            fig_month_ts = go.Figure()
            fig_month_ts.add_trace(
                go.Scatter(
                    x=month_series.loc[pre_mask_m, "date"],
                    y=month_series.loc[pre_mask_m, COL_RANGE_CNT],
                    mode="lines",
                    name="정점 이전(월간)",
                    line=dict(color="lightgray", width=2, dash="dot"),
                )
            )
            fig_month_ts.add_trace(
                go.Scatter(
                    x=month_series.loc[post_mask_m, "date"],
                    y=month_series.loc[post_mask_m, COL_RANGE_CNT],
                    mode="lines",
                    name="정점 이후(월간)",
                    line=dict(color="crimson", width=3),
                )
            )
            fig_month_ts.add_trace(
                go.Scatter(
                    x=month_series["date"],
                    y=month_series[COL_RANGE_CNT],
                    mode="markers",
                    name="월별 값",
                    marker=dict(size=4, color="crimson"),
                    showlegend=False,
                )
            )
            fig_month_ts.add_vline(x=peak_date_m, line_dash="dash", line_width=2)
            fig_month_ts.add_vrect(
                x0=peak_date_m,
                x1=month_series["date"].iloc[-1],
                fillcolor="LightSalmon",
                opacity=0.18,
                layer="below",
                line_width=0,
            )
            fig_month_ts.add_annotation(
                x=peak_date_m,
                y=peak_val_m,
                text=f"월간 정점 {peak_label_m}",
                showarrow=True,
                arrowhead=2,
                ax=0,
                ay=-40,
            )
            fig_month_ts.add_annotation(
                x=last_date_m,
                y=last_val_m,
                text=f"마지막 {last_label_m}\n(정점 대비 {decline_pct_m:.1f}%)",
                showarrow=True,
                arrowhead=2,
                ax=40,
                ay=40,
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
            fig_month_ts.update_xaxes(tickformat="%Y.%m")

            st.plotly_chart(fig_month_ts, use_container_width=True)

        st.markdown("---")

        # 연도별 요약표
        st.markdown("#### 🔹 연도별 가스레인지 수 요약 (월평균·연간합계 기준)")
        yearly_table = yearly.copy().set_index("연도")

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

        st.dataframe(yearly_table, use_container_width=True, height=350)

        st.markdown("---")

        # 시군구별 연도 추세 (연간합계)
        st.markdown("#### 🔹 시군구별 가스레인지 수 연도 추세 (연간합계 기준)")
        gu_year = (
            df.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
            .sum()
            .sort_values(["연도", COL_DISTRICT])
        )
        if gu_year.empty:
            st.info("현재 필터 조건에 해당하는 시군구별 데이터가 없어.")
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
                    x=1,
                ),
                margin=dict(l=40, r=20, t=60, b=40),
            )
            st.plotly_chart(fig_gu, use_container_width=True)

        st.markdown("---")

        # 연도×월 히트맵
        st.markdown("#### 🔹 연도 × 월 패턴 히트맵")
        monthly_for_heat = (
            df.groupby(["연도", "월"], as_index=False)[COL_RANGE_CNT]
            .sum()
        )
        heat_pivot = monthly_for_heat.pivot(index="월", columns="연도", values=COL_RANGE_CNT)
        heat_pivot = heat_pivot.sort_index()

        fig_heat = px.imshow(
            heat_pivot,
            labels=dict(x="연도", y="월", color="가스레인지 수"),
            aspect="auto",
            title="연도 × 월 가스레인지 수 히트맵",
        )
        fig_heat.update_xaxes(side="top")
        st.plotly_chart(fig_heat, use_container_width=True)

# ─────────────────────────────────────
# ② 군구별 감소량 지도 (대구 8개 구·군 + 경산시)
# ─────────────────────────────────────
with tab2:
    st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

    # usage / product 필터 적용 + 대구+경산 시군구만 사용
    df_map = df_raw.copy()
    df_map = df_map[df_map[COL_USAGE].isin(usage_sel)]
    df_map = df_map[df_map[COL_PRODUCT].isin(product_sel)]
    df_map = df_map[df_map[COL_DISTRICT].isin(TARGET_SIGUNGU)]

    map_df = df_map[df_map["연도"].isin([base_year, comp_year])]

    if map_df.empty:
        st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
    else:
        grouped = (
            map_df.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
            .sum()
        )

        pivot_map = (
            grouped
            .pivot(index=COL_DISTRICT, columns="연도", values=COL_RANGE_CNT)
            .reindex(index=TARGET_SIGUNGU)
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
            np.nan,
        )
        pivot_map["감소율(%)"] = pivot_map["감소율(%)"].round(1)

        map_table = pivot_map.reset_index().rename(
            columns={
                COL_DISTRICT: "시군구",
                base_year: f"{base_year}년 가스레인지 수(연간합계)",
                comp_year: f"{comp_year}년 가스레인지 수(연간합계)",
            }
        )

        # 디버깅용: GeoJSON feature 이름 리스트
        if geojson is not None:
            feature_names = [f["properties"].get("시군구") for f in geojson["features"]]
            st.caption(f"GeoJSON feature 개수: {len(feature_names)}, 시군구 목록: {', '.join(feature_names)}")

        c1, c2 = st.columns([2, 3])

        # 표
        with c1:
            st.markdown(
                f"**대구시 구·군 + 경산시 시군구별 가스레인지 수 및 변화 (연간합계 기준)**  \n"
                f"(기준연도: {base_year}년, 비교연도: {comp_year}년)"
            )
            df_show = map_table.copy()

            int_cols = [
                f"{base_year}년 가스레인지 수(연간합계)",
                f"{comp_year}년 가스레인지 수(연간합계)",
                "감소량(기준-비교)",
            ]
            for col in int_cols:
                df_show[col] = df_show[col].apply(lambda x: f"{int(x):,}")

            df_show["감소율(%)"] = df_show["감소율(%)"].apply(
                lambda x: "" if pd.isna(x) else f"{x:.1f}"
            )

            st.dataframe(
                df_show.set_index("시군구"),
                use_container_width=True,
                height=450,
            )

        # 지도
        with c2:
            if geojson is None:
                st.warning(
                    f"대구+경산 GeoJSON({GEO_PATH})을 찾을 수 없어서 지도를 그릴 수 없어.  "
                    "daegu_gyeongsan_sgg.geojson 파일이 data 폴더에 있는지 확인해줘."
                )
            else:
                fig_map = px.choropleth(
                    map_table,
                    geojson=geojson,
                    locations="시군구",
                    featureidkey="properties.시군구",
                    color="감소량(기준-비교)",
                    hover_name="시군구",
                    hover_data={
                        f"{base_year}년 가스레인지 수(연간합계)": ":,",
                        f"{comp_year}년 가스레인지 수(연간합계)": ":,",
                        "감소량(기준-비교)": ":,",
                        "감소율(%)": True,
                    },
                    color_continuous_scale="RdBu_r",
                    color_continuous_midpoint=0,
                )

                # ── 여기서 경계선/레이아웃 세팅 ──
                fig_map.update_geos(
                    fitbounds="locations",
                    visible=False,
                )
                fig_map.update_traces(
                    marker_line_width=1.2,
                    marker_line_color="white",
                    opacity=0.95,
                )
                fig_map.update_layout(
                    margin=dict(l=0, r=0, t=40, b=0),
                    coloraxis_colorbar=dict(title="감소량"),
                    title=f"{base_year}년 → {comp_year}년 대구시 구·군 + 경산시 시군구별 가스레인지 감소량",
                )

                st.plotly_chart(fig_map, use_container_width=True)

        st.markdown(
            """
            - **감소량(기준-비교)** : 기준연도 연간 가스레인지 수 − 비교연도 연간 가스레인지 수  
            - **감소율(%)** : 감소량 ÷ 기준연도 연간 가스레인지 수 × 100  
            - 시군구 선택 필터와 무관하게, 대구 8개 구·군 + 경산시만 지도/표에 표시됨.
            """
        )
