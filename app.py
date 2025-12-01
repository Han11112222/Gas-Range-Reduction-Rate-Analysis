# app.py ─ 가정용 가스레인지 감소 분석 (대구)
# - 연도·용도·상품·시군구별 가스레인지 수 추이
# - 기준연도 vs 비교연도 군구별 감소량 / 감소율 지도
# - 시군구별 연도별 추이 그래프

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

    # 5) '구분' → 연도 추출 (YYYYMM → YYYY)
    df[COL_YEAR_MONTH] = df[COL_YEAR_MONTH].astype(str).str.strip()
    df["연도"] = df[COL_YEAR_MONTH].str[:4].astype(int)

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
tab1, tab2 = st.tabs(["① 연도·상품·시군구 추이", "② 군구별 감소량 지도"])


# ─────────────────────────────────────────
# ① 연도·상품·시군구별 추이
# ─────────────────────────────────────────
with tab1:
    st.subheader("① 연도·상품·시군구별 가스레인지 수 추이")

    # 연도별 총합
    yearly = (
        df.groupby("연도", as_index=False)[COL_RANGE_CNT]
        .sum()
        .sort_values("연도")
    )

    # 전년 대비 증감 및 증감률
    yearly["전년대비 증감"] = yearly[COL_RANGE_CNT].diff()
    yearly["전년대비 증감률(%)"] = (
        yearly["전년대비 증감"] / yearly[COL_RANGE_CNT].shift(1) * 100
    ).round(1)

    # 기준연도 대비 증감 / 증감률
    if base_year in yearly["연도"].values:
        base_val = float(
            yearly.loc[yearly["연도"] == base_year, COL_RANGE_CNT].iloc[0]
        )
        yearly["기준연도 대비 증감"] = yearly[COL_RANGE_CNT] - base_val
        yearly["기준연도 대비 증감률(%)"] = (
            (yearly[COL_RANGE_CNT] - base_val) / base_val * 100
        ).round(1)
    else:
        yearly["기준연도 대비 증감"] = np.nan
        yearly["기준연도 대비 증감률(%)"] = np.nan

    # 정점 연도(가스레인지 수 최대 연도) 계산
    peak_idx = yearly[COL_RANGE_CNT].idxmax()
    peak_year = int(yearly.loc[peak_idx, "연도"])
    peak_val = float(yearly.loc[peak_idx, COL_RANGE_CNT])

    st.markdown("#### 🔹 연도별 가스레인지 수 추이 (상단: 동적 차트, 하단: 숫자표)")

    # ── (1) 연도별 전체 추이 그래프 (정점 연도 강조) ──
    fig_year = go.Figure()

    # 기본 라인 + 에어리어
    fig_year.add_trace(
        go.Scatter(
            x=yearly["연도"],
            y=yearly[COL_RANGE_CNT],
            mode="lines+markers",
            name="총 가스레인지 수",
            fill="tozeroy",
        )
    )

    # 기준연도 / 비교연도 / 정점연도 수직선 (텍스트는 annotation으로 별도)
    fig_year.add_vline(x=base_year, line_dash="dot", line_width=2)
    fig_year.add_vline(x=comp_year, line_dash="dot", line_width=2)
    fig_year.add_vline(x=peak_year, line_dash="dash", line_width=2)

    # 정점 포인트 강조
    fig_year.add_trace(
        go.Scatter(
            x=[peak_year],
            y=[peak_val],
            mode="markers+text",
            text=[f"정점 {peak_year}"],
            textposition="top center",
            marker=dict(size=12),
            showlegend=False,
        )
    )

    # 수직선에 대한 텍스트 라벨(annotation)
    ymax = float(yearly[COL_RANGE_CNT].max())
    y_text = ymax * 1.02  # 그래프 위 여백 부분

    fig_year.add_annotation(
        x=base_year,
        y=y_text,
        text=f"기준연도 {base_year}",
        showarrow=False,
        yanchor="bottom"
    )
    fig_year.add_annotation(
        x=comp_year,
        y=y_text,
        text=f"비교연도 {comp_year}",
        showarrow=False,
        yanchor="bottom"
    )
    fig_year.add_annotation(
        x=peak_year,
        y=y_text,
        text=f"정점연도 {peak_year}",
        showarrow=False,
        yanchor="bottom"
    )

    fig_year.update_layout(
        title="연도별 가스레인지 수 추이 (정점 연도 하이라이트)",
        yaxis_title="가스레인지 수",
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

    st.plotly_chart(fig_year, use_container_width=True)

    # ── (2) 연도별 숫자표 (그래프 하단) ──
    st.markdown("##### 📊 연도별 가스레인지 수 요약표")
    st.dataframe(
        yearly.set_index("연도"),
        use_container_width=True,
        height=320
    )

    st.markdown("---")

    # ── (3) 시군구별 연도별 추이 그래프 ──
    st.markdown("#### 🔹 시군구별 가스레인지 수 연도 추세")

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
            title="시군구별 연도별 가스레인지 수 추이",
        )
        fig_gu.update_layout(
            yaxis_title="가스레인지 수",
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

    # ── (4) 세부 피벗 테이블 ──
    st.markdown("##### 📑 세부 피벗테이블 (연도 × 용도 × 상품 × 시군구)")
    pivot = (
        df.pivot_table(
            index=["연도", COL_USAGE, COL_PRODUCT, COL_DISTRICT],
            values=COL_RANGE_CNT,
            aggfunc="sum",
        )
        .reset_index()
        .sort_values(["연도", COL_USAGE, COL_PRODUCT, COL_DISTRICT])
    )

    st.dataframe(
        pivot,
        use_container_width=True,
        height=400
    )


# ─────────────────────────────────────────
# ② 군구별 감소량 지도
# ─────────────────────────────────────────
with tab2:
    st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도")

    # 기준연도 & 비교연도만 추출
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
            base_year: f"{base_year}년 가스레인지 수",
            comp_year: f"{comp_year}년 가스레인지 수",
        }
    )

    c1, c2 = st.columns([2, 3])

    with c1:
        st.markdown(
            f"**군구별 가스레인지 수 및 감소량**  \n"
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
            # 예: properties.SIG_KOR_NM, properties.adm_nm 등
            feature_key = "properties.SIG_KOR_NM"

            fig_map = px.choropleth(
                map_table,
                geojson=geojson,
                locations=COL_DISTRICT,
                featureidkey=feature_key,
                color="감소량(기준-비교)",
                hover_name=COL_DISTRICT,
                hover_data={
                    f"{base_year}년 가스레인지 수": ":,",
                    f"{comp_year}년 가스레인지 수": ":,",
                    "감소량(기준-비교)": ":,",
                    "감소율(%)": True,
                },
                title=f"{base_year}년 → {comp_year}년 군구별 가스레인지 감소량",
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            fig_map.update_layout(
                margin=dict(l=0, r=0, t=40, b=0),
                coloraxis_colorbar=dict(title="감소량")
            )
            st.plotly_chart(fig_map, use_container_width=True)

    st.markdown(
        """
        - **감소량(기준-비교)** : 기준연도 가스레인지 수 − 비교연도 가스레인지 수  
        - **감소율(%)** : 감소량 ÷ 기준연도 가스레인지 수 × 100
        """
    )
