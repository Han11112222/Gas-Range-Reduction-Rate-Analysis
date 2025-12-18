# app.py ─ 가정용 가스레인지 감소 분석 (대구 + 경산)
# - 분석1(인덕션 사용량 분석 1st): ① 월별·연도별 추이  /  ② 대구시 8개 구·군 + 경산시 감소량 지도
# - 분석2(인덕션 사용량 분석 2nd): 인덕션(비가스렌지) 추정 + 사용량 감소 추정 (연도별 / 시군구·용도별)
#
# ※ 인덕션 추정 가정(업데이트)
#   - 추정 인덕션 세대수 = [총청구계량기수 시트의 전수] − [계량기_가스렌지연결 시트의 전수]

from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────
# [지도 안정화용] folium + streamlit-folium (있으면 사용, 없으면 Plotly로 자동 백업)
# ─────────────────────────────────────
FOLIUM_OK = True
FOLIUM_ERR = ""
try:
    import folium
    from streamlit_folium import st_folium
    from branca.colormap import LinearColormap
except Exception as e:
    FOLIUM_OK = False
    FOLIUM_ERR = str(e)
    folium = None
    st_folium = None
    LinearColormap = None


# ─────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────
st.set_page_config(
    page_title="가정용 가스레인지 감소 분석 (대구 + 경산)",
    layout="wide",
)

st.title("🏠 가정용 가스레인지 감소 분석 (대구)")


# ─────────────────────────────────────
# 경로/상수
# ─────────────────────────────────────
BASE_DIR = Path(__file__).parent

# 분석1용(기존) 엑셀 파일(레포에 있는 파일명 기준)
DATA_PATH = BASE_DIR / "(ver2)가정용_가스레인지_사용유무.xlsx"

# 분석2용(사용량/전체청구전 포함된 파일 우선)
DATA_PATH_V3 = BASE_DIR / "(ver3)가정용_가스레인지_사용유무(201501_202412)_정보추가.xlsx"
DATA_PATH_V2_USAGE = BASE_DIR / "(ver2)가정용_가스레인지_사용유무(201501_202412)_사용량추가.xlsx"

# 지도용 GeoJSON (대구 8개 구·군 + 경산시)
# 레포에 있는 파일명(사용자 스크린샷 기준)
GEO_PATH_CANDIDATES = [
    BASE_DIR / "daegu_gyeongsan_sgg.geojson",
    BASE_DIR / "data" / "daegu_gyeongsan_sgg.geojson",
]
GEO_PATH = None
for p in GEO_PATH_CANDIDATES:
    if p.exists():
        GEO_PATH = p
        break

COL_YEAR_MONTH = "연월"
COL_USAGE = "용도"
COL_PRODUCT = "상품"
COL_DISTRICT = "시군구"
COL_RANGE_CNT = "가스레인지수"

TARGET_SIGUNGU = [
    "중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군",
    "경산시",
]


# ─────────────────────────────────────
# 유틸
# ─────────────────────────────────────
def to_int_series(s: pd.Series) -> pd.Series:
    """문자열/숫자 혼재된 시리즈를 정수로 변환 (콤마 제거)."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False),
        errors="coerce"
    ).fillna(0).astype(int)


# ─────────────────────────────────────
# 데이터 로딩 (분석1: 기존 파일)
# ─────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    """기존 엑셀 원시파일에서 분석용 데이터프레임 생성 (분석1용)."""
    raw = pd.read_excel(DATA_PATH, sheet_name=0, header=None)

    # 파일 구조: 0행이 헤더로 들어가 있는 형태라 가정(사용자가 올린 기존 포맷 유지)
    raw.columns = raw.iloc[0]
    df = raw.iloc[1:].copy()

    # 컬럼 표준화
    # 기대 컬럼: 연월/연도/월/용도/상품/시군구/가스레인지수 등
    # 일부 파일은 '연월'이 문자열(YYYYMM)일 수도 있어서 처리
    if COL_YEAR_MONTH not in df.columns:
        # 혹시 '연월 '처럼 공백이 섞인 경우
        for c in df.columns:
            if str(c).strip() == COL_YEAR_MONTH:
                df.rename(columns={c: COL_YEAR_MONTH}, inplace=True)

    # 기본 컬럼 정리
    if "연도" not in df.columns:
        # 연월(YYYYMM)에서 연도 생성
        if COL_YEAR_MONTH in df.columns:
            df["연도"] = df[COL_YEAR_MONTH].astype(str).str.slice(0, 4)
    if "월" not in df.columns:
        if COL_YEAR_MONTH in df.columns:
            df["월"] = df[COL_YEAR_MONTH].astype(str).str.slice(4, 6)

    # 타입 변환
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")

    # 가스레인지 수
    if COL_RANGE_CNT in df.columns:
        df[COL_RANGE_CNT] = to_int_series(df[COL_RANGE_CNT])
    else:
        # 혹시 다른 이름인 경우 보정(가능한 후보)
        for c in df.columns:
            if "가스레인지" in str(c) and "수" in str(c):
                df.rename(columns={c: COL_RANGE_CNT}, inplace=True)
                df[COL_RANGE_CNT] = to_int_series(df[COL_RANGE_CNT])
                break

    # 결측 처리
    for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
        if c not in df.columns:
            df[c] = ""

    return df


# ─────────────────────────────────────
# 데이터 로딩 (분석2: 사용량/전체청구전 포함 파일)
# ─────────────────────────────────────
@st.cache_data
def load_data_usage() -> pd.DataFrame | None:
    """
    반환:
      - df: 분석2용 데이터프레임 (사용량, 전체청구전수 등 포함)
      - 파일이 없으면 None
    """
    path = None
    if DATA_PATH_V3.exists():
        path = DATA_PATH_V3
    elif DATA_PATH_V2_USAGE.exists():
        path = DATA_PATH_V2_USAGE
    else:
        return None

    df = pd.read_excel(path)

    # 필수 컬럼 표준화
    # 기대: 연도, 시군구, 용도, 상품, 가스레인지수, 전체청구전수, 사용량_기준, (선택) 가스렌지연결_청구전수
    if "연도" not in df.columns:
        # 연월이 있다면 연도 생성
        if COL_YEAR_MONTH in df.columns:
            df["연도"] = df[COL_YEAR_MONTH].astype(str).str.slice(0, 4)
        else:
            # 예외: 아무 것도 없으면 실패
            return None

    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")

    for c in [COL_DISTRICT, COL_USAGE, COL_PRODUCT]:
        if c not in df.columns:
            # 혹시 공백/유사 컬럼
            for cc in df.columns:
                if str(cc).strip() == c:
                    df.rename(columns={cc: c}, inplace=True)
                    break
        if c not in df.columns:
            df[c] = ""

    # 가스레인지 수
    if COL_RANGE_CNT in df.columns:
        df[COL_RANGE_CNT] = to_int_series(df[COL_RANGE_CNT])
    else:
        # 후보 찾기
        for c in df.columns:
            if "가스레인지" in str(c) and "수" in str(c):
                df.rename(columns={c: COL_RANGE_CNT}, inplace=True)
                df[COL_RANGE_CNT] = to_int_series(df[COL_RANGE_CNT])
                break
        if COL_RANGE_CNT not in df.columns:
            df[COL_RANGE_CNT] = 0

    # 전체청구전수
    if "전체청구전수" in df.columns:
        df["전체청구전수"] = to_int_series(df["전체청구전수"])
    else:
        # 후보 찾기
        found = False
        for c in df.columns:
            if "전체" in str(c) and "청구" in str(c) and "전수" in str(c):
                df.rename(columns={c: "전체청구전수"}, inplace=True)
                df["전체청구전수"] = to_int_series(df["전체청구전수"])
                found = True
                break
        if not found:
            df["전체청구전수"] = np.nan

    # 사용량(기준) 컬럼명 보정
    if "사용량_기준" not in df.columns:
        for c in df.columns:
            if "사용량" in str(c) and ("기준" in str(c) or "MJ" in str(c) or "m3" in str(c)):
                df.rename(columns={c: "사용량_기준"}, inplace=True)
                break
    if "사용량_기준" in df.columns:
        df["사용량_기준"] = pd.to_numeric(
            df["사용량_기준"].astype(str).str.replace(",", "", regex=False),
            errors="coerce"
        ).fillna(0)

    # v3에는 '가스렌지연결_청구전수'가 있을 수 있음
    if "가스렌지연결_청구전수" in df.columns:
        df["가스렌지연결_청구전수"] = to_int_series(df["가스렌지연결_청구전수"])
    else:
        # v2에는 '가스렌지연결_청구전수' 개념이 없으므로 NaN
        df["가스렌지연결_청구전수"] = np.nan

    return df


# ─────────────────────────────────────
# GeoJSON 로딩 (분석1 지도)
# ─────────────────────────────────────
@st.cache_data
def load_geojson():
    if GEO_PATH is None:
        return None, None
    try:
        gj = json.loads(GEO_PATH.read_text(encoding="utf-8"))
    except Exception:
        try:
            gj = json.loads(GEO_PATH.read_text(encoding="cp949"))
        except Exception:
            return None, None

    # 속성 필드 자동 선택 (시군구 이름이 들어있는 필드 찾기)
    features = gj.get("features", [])
    if not features:
        return gj, None

    props_keys = list(features[0].get("properties", {}).keys())
    best_field = None
    best_score = -1
    target_set = set(TARGET_SIGUNGU)

    for key in props_keys:
        values = [str(f["properties"].get(key, "")) for f in features]
        score = 0
        for d in target_set:
            if any(d in v for v in values):
                score += 1
        if score > best_score:
            best_score = score
            best_field = key

    return gj, best_field


# ─────────────────────────────────────
# [지도용] 감소량 테이블 만들기
# ─────────────────────────────────────
@st.cache_data
def build_map_table_cached(df_raw: pd.DataFrame,
                           usage_sel: tuple,
                           product_sel: tuple,
                           base_year: int,
                           comp_year: int) -> pd.DataFrame:
    df_map = df_raw.copy()
    df_map = df_map[df_map[COL_USAGE].isin(list(usage_sel))]
    df_map = df_map[df_map[COL_PRODUCT].isin(list(product_sel))]
    df_map = df_map[df_map[COL_DISTRICT].isin(TARGET_SIGUNGU)]

    map_df = df_map[df_map["연도"].isin([base_year, comp_year])]
    if map_df.empty:
        return pd.DataFrame()

    # 연간합계 기준: 연도×시군구 합계
    grp = (
        map_df.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
        .sum()
        .rename(columns={COL_RANGE_CNT: "가스레인지수(연간합계)"})
    )

    base_df = grp[grp["연도"] == base_year].set_index(COL_DISTRICT)
    comp_df = grp[grp["연도"] == comp_year].set_index(COL_DISTRICT)

    rows = []
    for sgg in TARGET_SIGUNGU:
        base_val = int(base_df.loc[sgg, "가스레인지수(연간합계)"]) if sgg in base_df.index else 0
        comp_val = int(comp_df.loc[sgg, "가스레인지수(연간합계)"]) if sgg in comp_df.index else 0
        diff_val = base_val - comp_val
        rate_val = (diff_val / base_val * 100) if base_val > 0 else np.nan
        rows.append([sgg, base_val, comp_val, diff_val, rate_val])

    map_table = pd.DataFrame(
        rows,
        columns=[
            "시군구",
            f"{base_year}년 가스레인지 수(연간합계)",
            f"{comp_year}년 가스레인지 수(연간합계)",
            "감소량(기준-비교)",
            "감소율(%)",
        ],
    )

    return map_table


def _attach_geo_key(map_table: pd.DataFrame, geojson: dict, GEO_NAME_FIELD: str) -> pd.DataFrame:
    """map_table에 geo_key를 붙여서 GeoJSON feature와 매칭되게 만든다."""
    mt = map_table.copy()
    geo_names = [
        str(f["properties"].get(GEO_NAME_FIELD, ""))
        for f in geojson.get("features", [])
    ]

    def find_geo_name(d):
        for name in geo_names:
            if d == name:
                return name
        # 포함/부분일치 허용
        for name in geo_names:
            if d in name or name in d:
                return name
        return None

    mt["geo_key"] = mt["시군구"].apply(find_geo_name)
    # 못 찾은 경우 대비: 원본 이름
    mt.loc[mt["geo_key"].isna(), "geo_key"] = mt.loc[mt["geo_key"].isna(), "시군구"]
    return mt


# ─────────────────────────────────────
# Folium Choropleth 만들기
# ─────────────────────────────────────
@st.cache_data
def build_folium_choropleth(map_table: pd.DataFrame, geojson: dict, GEO_NAME_FIELD: str, base_year: int, comp_year: int):
    # 중심: 대구 근처로 대충 세팅
    m = folium.Map(location=[35.87, 128.60], zoom_start=10, tiles="cartodbpositron")

    vcol = "감소량(기준-비교)"
    vals = map_table[vcol].astype(float).to_list()
    vmin = float(np.nanmin(vals)) if len(vals) else 0.0
    vmax = float(np.nanmax(vals)) if len(vals) else 0.0
    if vmin == vmax:
        vmin -= 1.0
        vmax += 1.0

    # 0을 가운데로 보고 싶으면 (감소/증가) 대칭 범위로 맞춤
    absmax = max(abs(vmin), abs(vmax))
    vmin2, vmax2 = -absmax, absmax

    cmap = LinearColormap(["#2c7bb6", "#ffffbf", "#d7191c"], vmin=vmin2, vmax=vmax2)
    cmap.caption = f"감소량(기준-비교) : {base_year}년 - {comp_year}년"
    cmap.add_to(m)

    row_by_key = {r["geo_key"]: r for _, r in map_table.iterrows()}

    def style_function(feature):
        key = str(feature["properties"].get(GEO_NAME_FIELD, ""))
        row = row_by_key.get(key, None)
        if row is None:
            return {"fillOpacity": 0.15, "weight": 0.8, "color": "white", "fillColor": "#999999"}

        val = float(row.get("감소량(기준-비교)", 0.0))
        return {
            "fillOpacity": 0.7,
            "weight": 0.8,
            "color": "white",
            "fillColor": cmap(val),
        }

    def highlight_function(feature):
        return {"weight": 2, "color": "#333333", "fillOpacity": 0.85}

    tooltip = folium.GeoJsonTooltip(
        fields=[GEO_NAME_FIELD],
        aliases=["시군구"],
        sticky=True,
    )

    gj = folium.GeoJson(
        geojson,
        name="choropleth",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
    )
    gj.add_to(m)

    # Popup(표 값을 보기 쉽게)
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        k = str(props.get(GEO_NAME_FIELD, ""))
        row = row_by_key.get(k, None)
        if row is None:
            continue

        base_val = int(row.get(f"{base_year}년 가스레인지 수(연간합계)", 0))
        comp_val = int(row.get(f"{comp_year}년 가스레인지 수(연간합계)", 0))
        diff_val = int(row.get("감소량(기준-비교)", 0))
        rate_val = row.get("감소율(%)", np.nan)

        rate_txt = "" if pd.isna(rate_val) else f"{float(rate_val):.1f}%"

        html = f"""
        <div style="font-size:12px">
          <b>{k}</b><br/>
          {base_year}년: {base_val:,}<br/>
          {comp_year}년: {comp_val:,}<br/>
          감소량: {diff_val:,}<br/>
          감소율: {rate_txt}
        </div>
        """
        # 해당 feature의 중심에 popup 달기
        try:
            geom = feat.get("geometry", None)
            if geom:
                # 대표 좌표(대략) 찾기: 첫 좌표
                coords = None
                if geom["type"] == "Polygon":
                    coords = geom["coordinates"][0][0]
                elif geom["type"] == "MultiPolygon":
                    coords = geom["coordinates"][0][0][0]
                if coords:
                    folium.Marker(
                        location=[coords[1], coords[0]],
                        popup=folium.Popup(html, max_width=250),
                        icon=folium.DivIcon(html=""),
                    ).add_to(m)
        except Exception:
            pass

    folium.LayerControl().add_to(m)
    return m


# GeoJSON 미리 로딩
geojson, GEO_NAME_FIELD = load_geojson()


# ─────────────────────────────────────
# 사이드바 필터
# ─────────────────────────────────────
st.sidebar.markdown("## ⚙️ 분석 조건")

analysis_mode = st.sidebar.radio(
    "분석 탭 선택",
    ["1. 인덕션 사용량 분석 1st", "2. 인덕션 사용량 분석 2nd"],
    index=0,
)

df = load_data()

# 공통 필터 후보값
year_list = sorted(df["연도"].dropna().unique().tolist())
usage_list = sorted(df[COL_USAGE].dropna().unique().tolist())
product_list = sorted(df[COL_PRODUCT].dropna().unique().tolist())
district_list = sorted(df[COL_DISTRICT].dropna().unique().tolist())

# 범위 슬라이더용(연도)
if len(year_list) == 0:
    year_list = [2015, 2024]

base_year, comp_year = st.sidebar.select_slider(
    "기준연도 / 비교연도",
    options=year_list,
    value=(year_list[0], year_list[-1]) if len(year_list) >= 2 else (year_list[0], year_list[0]),
)

usage_sel = st.sidebar.multiselect(
    "용도 선택 (복수 선택 가능)",
    options=usage_list,
    default=usage_list[:2] if len(usage_list) >= 2 else usage_list,
)

product_sel = st.sidebar.multiselect(
    "상품 선택 (복수 선택 가능)",
    options=product_list,
    default=product_list[:3] if len(product_list) >= 3 else product_list,
)

district_sel = st.sidebar.multiselect(
    "시군구 선택 (복수 선택 가능, 비우면 전체)",
    options=district_list,
    default=[],
)

st.sidebar.caption(f"데이터 행 수(분석1 기준): {len(df):,}")


# ─────────────────────────────────────
# 분석1: 가스레인지 수 추이 + 군구별 감소 지도
# ─────────────────────────────────────
if analysis_mode.startswith("1."):
    st.subheader("인덕션 사용량 분석 1st ─ 가스레인지 수 추이 및 군구별 감소량 지도")

    tab1, tab2 = st.tabs(["① 월별·연도별 추이", "② 군구별 감소량 지도"])

    # ─────────────────────────────────
    # ① 월별·연도별 추이
    # ─────────────────────────────────
    with tab1:
        st.subheader("① 월별·연도별 가스레인지 수 추이")

        df_raw = df.copy()
        df_raw = df_raw[df_raw[COL_USAGE].isin(usage_sel)]
        df_raw = df_raw[df_raw[COL_PRODUCT].isin(product_sel)]
        if len(district_sel) > 0:
            df_raw = df_raw[df_raw[COL_DISTRICT].isin(district_sel)]

        if df_raw.empty:
            st.info("현재 필터 조건에 해당하는 데이터가 없어.")
        else:
            # 월 단위 집계
            month_series = (
                df_raw.groupby(COL_YEAR_MONTH, as_index=False)[COL_RANGE_CNT]
                .sum()
                .sort_values(COL_YEAR_MONTH)
            )

            fig_m = px.line(
                month_series,
                x=COL_YEAR_MONTH,
                y=COL_RANGE_CNT,
                markers=True,
                title="월별 가스레인지 수(합계) 추이",
            )
            fig_m.update_layout(margin=dict(l=40, r=20, t=60, b=40))
            st.plotly_chart(fig_m, use_container_width=True)

            # 연도 단위 집계
            year_series = (
                df_raw.groupby("연도", as_index=False)[COL_RANGE_CNT]
                .sum()
                .sort_values("연도")
            )
            fig_y = px.bar(
                year_series,
                x="연도",
                y=COL_RANGE_CNT,
                title="연도별 가스레인지 수(연간합계)",
            )
            fig_y.update_layout(margin=dict(l=40, r=20, t=60, b=40))
            st.plotly_chart(fig_y, use_container_width=True)

            # 시군구별 연도 추이
            gu_year = (
                df_raw.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
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
                fig_gu.update_layout(margin=dict(l=40, r=20, t=60, b=40))
                st.plotly_chart(fig_gu, use_container_width=True)

            # 히트맵: 연도×시군구
            heat = (
                df_raw.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
                .sum()
            )
            pivot = heat.pivot(index="연도", columns=COL_DISTRICT, values=COL_RANGE_CNT).sort_index()
            fig_heat = px.imshow(
                pivot,
                labels=dict(x="시군구", y="연도", color="가스레인지수(연간합계)"),
                aspect="auto",
                title="연도 × 시군구 가스레인지수(연간합계) 히트맵",
                color_continuous_scale="Blues",
            )
            fig_heat.update_xaxes(side="top")
            st.plotly_chart(fig_heat, use_container_width=True)

    # ─────────────────────────────────
    # ② 군구별 감소량 지도 (대구 8개 구·군 + 경산시)
    # ─────────────────────────────────
    with tab2:
        st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

        # map_table 계산 (캐시)
        map_table = build_map_table_cached(
            df_raw=df,
            usage_sel=tuple(usage_sel),
            product_sel=tuple(product_sel),
            base_year=int(base_year),
            comp_year=int(comp_year),
        )

        if map_table.empty:
            st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
        else:
            # ─ GeoJSON 매핑 ─
            if geojson is not None and GEO_NAME_FIELD is not None:
                geo_names = [
                    str(f["properties"].get(GEO_NAME_FIELD, ""))
                    for f in geojson.get("features", [])
                ]
                map_table = _attach_geo_key(map_table, geojson, GEO_NAME_FIELD)
                st.caption(
                    f"GeoJSON feature 개수: {len(geo_names)}, "
                    f"선택된 속성필드: {GEO_NAME_FIELD}"
                )
            else:
                map_table["geo_key"] = map_table["시군구"]
                st.caption(
                    "GeoJSON 속성 필드를 자동 선택하지 못했어. "
                    "시군구 이름 그대로 사용 중."
                )

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

            # 지도 (✅ folium 우선 + 없으면 plotly 백업)
            with c2:
                if geojson is None or GEO_NAME_FIELD is None:
                    st.warning(
                        f"대구+경산 GeoJSON({GEO_PATH})을 찾을 수 없거나, "
                        "시군구 이름이 들어 있는 속성 필드를 찾지 못해서 지도를 그릴 수 없어."
                    )
                else:
                    if FOLIUM_OK:
                        map_key = (
                            f"folium_map_{base_year}_{comp_year}_"
                            + "_".join(sorted(usage_sel))
                            + "_"
                            + "_".join(sorted(product_sel))
                        )

                        m = build_folium_choropleth(
                            map_table=map_table,
                            geojson=geojson,
                            GEO_NAME_FIELD=GEO_NAME_FIELD,
                            base_year=int(base_year),
                            comp_year=int(comp_year),
                        )
                        st_folium(m, use_container_width=True, returned_objects=[], key=map_key)
                    else:
                        st.warning(
                            "현재 실행환경에 folium(또는 streamlit-folium)이 설치되어 있지 않아서 "
                            "Plotly 지도로 대체 표시 중이야.\n"
                            f"- 에러: `{FOLIUM_ERR}`"
                        )

                        fig_map = px.choropleth(
                            map_table,
                            geojson=geojson,
                            locations="geo_key",
                            featureidkey=f"properties.{GEO_NAME_FIELD}",
                            color="감소량(기준-비교)",
                            hover_name="시군구",
                            hover_data={
                                f"{base_year}년 가스레인지 수(연간합계)": True,
                                f"{comp_year}년 가스레인지 수(연간합계)": True,
                                "감소량(기준-비교)": True,
                                "감소율(%)": True,
                            },
                            color_continuous_scale="RdBu_r",
                            color_continuous_midpoint=0,
                        )

                        fig_map.update_geos(
                            fitbounds="locations",
                            visible=False,
                        )

                        fig_map.update_traces(
                            marker_line_width=0.8,
                            marker_line_color="white",
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


# ─────────────────────────────────────
# 분석2: 인덕션 사용 추정 + 사용량 감소 추정
# (인덕션 사용량 분석 2nd)
# ─────────────────────────────────────
else:
    st.subheader("인덕션 사용량 분석 2nd ─ 인덕션(비가스레인지) 사용 추정 및 사용량 감소 분석")

    df_usage_raw = load_data_usage()
    if df_usage_raw is None:
        st.error(
            "사용량·전체청구전수를 포함한 파일을 찾지 못했어.  \n"
            "`(ver3)가정용_가스레인지_사용유무(201501_202412)_정보추가.xlsx` "
            "또는 `(ver2)가정용_가스레인지_사용유무(201501_202412)_사용량추가.xlsx` "
            "파일이 같은 폴더에 있는지 확인해줘."
        )
    else:
        # 공통 필터 적용
        dfu = df_usage_raw.copy()
        dfu = dfu[dfu[COL_USAGE].isin(usage_sel)]
        dfu = dfu[dfu[COL_PRODUCT].isin(product_sel)]
        if len(district_sel) > 0:
            dfu = dfu[dfu[COL_DISTRICT].isin(district_sel)]

        if dfu.empty:
            st.info("현재 필터 조건에 해당하는 데이터가 없어.")
        else:
            # 인덕션 추정(업데이트)
            # 추정 인덕션 세대수 = 전체청구전수 − 가스렌지연결_청구전수(있으면)  / 없으면 전체청구전수 − 가스레인지수
            if dfu["가스렌지연결_청구전수"].notna().any():
                dfu["추정_인덕션세대수"] = (dfu["전체청구전수"] - dfu["가스렌지연결_청구전수"]).clip(lower=0)
            else:
                dfu["추정_인덕션세대수"] = (dfu["전체청구전수"] - dfu[COL_RANGE_CNT]).clip(lower=0)

            # ─────────────────────────────
            # 화면 구성: 탭 2개
            # ─────────────────────────────
            tab_a, tab_b = st.tabs(
                ["① 연도별 인덕션 사용 및 사용량 감소 추정", "② 시군구·용도별 인덕션/감소 추정"]
            )

            # ─────────────────────────────
            # ① 연도별 인덕션 및 사용량 감소 추정
            # ─────────────────────────────
            with tab_a:
                st.markdown("### ① 연도별 인덕션 사용 및 사용량 감소 추정")

                # 연도 집계
                agg_dict = {
                    "가스레인지수합": (COL_RANGE_CNT, "sum"),
                    "전체청구전수합": ("전체청구전수", "sum"),
                    "가스렌지연결_청구전수합": ("가스렌지연결_청구전수", "sum"),
                    "사용량합": ("사용량_기준", "sum"),
                    "인덕션세대합": ("추정_인덕션세대수", "sum"),
                }

                # v2 파일은 가스렌지연결_청구전수가 전부 NaN일 수 있음 → 합계 의미없음 방지
                if dfu["가스렌지연결_청구전수"].isna().all():
                    agg_dict.pop("가스렌지연결_청구전수합", None)

                year_agg = (
                    dfu.groupby("연도", as_index=False)
                    .agg(**agg_dict)
                    .sort_values("연도")
                )

                # 인덕션 비중(%) = 추정_인덕션세대수 / 전체청구전수
                year_agg["인덕션비중(%)"] = np.where(
                    year_agg["전체청구전수합"] > 0,
                    year_agg["인덕션세대합"] / year_agg["전체청구전수합"] * 100,
                    np.nan,
                ).round(2)

                # 인덕션 사용량 감소 추정:
                # - 기준: "가스레인지 있는 세대(가스렌지연결 또는 가스레인지수)"의 평균 사용량을,
                # - 인덕션 세대로 확장했다면 발생했을 사용량을 가정 → 감소량 = 가정 사용량
                # 단순화: (가스레인지 세대당 평균 사용량) × 인덕션세대수
                # 가스레인지 세대수: (전체청구전수 - 인덕션세대수)
                year_agg["가스레인지세대합"] = (year_agg["전체청구전수합"] - year_agg["인덕션세대합"]).clip(lower=0)
                year_agg["가스레인지세대당평균사용량"] = np.where(
                    year_agg["가스레인지세대합"] > 0,
                    year_agg["사용량합"] / year_agg["가스레인지세대합"],
                    np.nan,
                )
                year_agg["추정_사용량감소"] = year_agg["가스레인지세대당평균사용량"] * year_agg["인덕션세대합"]

                # 단위 라벨: 파일에 따라 MJ/m3 혼재 가능. 여기서는 "사용량_기준" 그대로 표시
                unit_label = "사용량_기준"

                c1, c2 = st.columns([2, 2])
                with c1:
                    fig1 = px.line(
                        year_agg,
                        x="연도",
                        y="인덕션비중(%)",
                        markers=True,
                        title="연도별 인덕션 비중(%)",
                    )
                    fig1.update_layout(margin=dict(l=40, r=20, t=60, b=40))
                    st.plotly_chart(fig1, use_container_width=True)

                with c2:
                    fig2 = px.bar(
                        year_agg,
                        x="연도",
                        y="추정_사용량감소",
                        title=f"연도별 추정 사용량 감소 ({unit_label})",
                    )
                    fig2.update_layout(margin=dict(l=40, r=20, t=60, b=40))
                    st.plotly_chart(fig2, use_container_width=True)

                st.dataframe(
                    year_agg.set_index("연도"),
                    use_container_width=True,
                    height=320,
                )

            # ─────────────────────────────
            # ② 시군구·용도별 인덕션/감소 추정
            # ─────────────────────────────
            with tab_b:
                st.markdown("### ② 시군구·용도별 인덕션 및 사용량 감소 추정")

                agg_dict2 = {
                    "가스레인지수합": (COL_RANGE_CNT, "sum"),
                    "전체청구전수합": ("전체청구전수", "sum"),
                    "사용량합": ("사용량_기준", "sum"),
                }

                # 가스렌지연결_청구전수 있으면 함께 집계
                if dfu["가스렌지연결_청구전수"].notna().any():
                    agg_dict2["가스렌지연결_청구전수합"] = ("가스렌지연결_청구전수", "sum")

                grp = (
                    dfu.groupby([COL_DISTRICT, COL_USAGE], as_index=False)
                    .agg(**agg_dict2)
                )

                if "가스렌지연결_청구전수합" in grp.columns:
                    base_induction_grp = (
                        grp["전체청구전수합"] - grp["가스렌지연결_청구전수합"]
                    )
                else:
                    base_induction_grp = (
                        grp["전체청구전수합"] - grp["가스레인지수합"]
                    )

                grp["추정_인덕션세대수"] = base_induction_grp.clip(lower=0)

                # 사용량 감소 추정: (가스레인지 세대당 평균 사용량) × 인덕션세대수
                grp["가스레인지세대수"] = (grp["전체청구전수합"] - grp["추정_인덕션세대수"]).clip(lower=0)
                grp["가스레인지세대당평균사용량"] = np.where(
                    grp["가스레인지세대수"] > 0,
                    grp["사용량합"] / grp["가스레인지세대수"],
                    np.nan,
                )
                grp["추정_사용량감소"] = grp["가스레인지세대당평균사용량"] * grp["추정_인덕션세대수"]

                # ─ (1) 시군구별 추정 사용량 감소 바차트
                st.markdown("#### ▸ 시군구별 추정 사용량 감소")

                gu_agg = (
                    grp.groupby(COL_DISTRICT, as_index=False)
                    .agg(
                        가스레인지수합=("가스레인지수합", "sum"),
                        전체청구전수합=("전체청구전수합", "sum"),
                        인덕션세대합=("추정_인덕션세대수", "sum"),
                        사용량합=("사용량합", "sum"),
                        추정_사용량감소=("추정_사용량감소", "sum"),
                    )
                )
                gu_agg["감소율(%)"] = np.where(
                    gu_agg["사용량합"] > 0,
                    gu_agg["추정_사용량감소"] / gu_agg["사용량합"] * 100,
                    np.nan,
                ).round(1)

                fig_gu = px.bar(
                    gu_agg.sort_values("추정_사용량감소", ascending=False),
                    x=COL_DISTRICT,
                    y="추정_사용량감소",
                    hover_data=[
                        "가스레인지수합",
                        "전체청구전수합",
                        "인덕션세대합",
                        "사용량합",
                        "감소율(%)",
                    ],
                    title="시군구별 추정 사용량 감소",
                )
                fig_gu.update_layout(
                    xaxis_title="시군구",
                    yaxis_title=f"추정 사용량 감소 ({unit_label})",
                    margin=dict(l=40, r=20, t=60, b=40),
                )
                st.plotly_chart(fig_gu, use_container_width=True)

                st.dataframe(
                    gu_agg.set_index(COL_DISTRICT),
                    use_container_width=True,
                    height=320,
                )

                # ─ (2) 용도별 추정 사용량 감소 바차트
                st.markdown("---")
                st.markdown("#### ▸ 용도별 추정 사용량 감소")

                use_agg = (
                    grp.groupby(COL_USAGE, as_index=False)
                    .agg(
                        가스레인지수합=("가스레인지수합", "sum"),
                        전체청구전수합=("전체청구전수합", "sum"),
                        인덕션세대합=("추정_인덕션세대수", "sum"),
                        사용량합=("사용량합", "sum"),
                        추정_사용량감소=("추정_사용량감소", "sum"),
                    )
                )
                use_agg["감소율(%)"] = np.where(
                    use_agg["사용량합"] > 0,
                    use_agg["추정_사용량감소"] / use_agg["사용량합"] * 100,
                    np.nan,
                ).round(1)

                fig_use = px.bar(
                    use_agg.sort_values("추정_사용량감소", ascending=False),
                    x=COL_USAGE,
                    y="추정_사용량감소",
                    hover_data=[
                        "가스레인지수합",
                        "전체청구전수합",
                        "인덕션세대합",
                        "사용량합",
                        "감소율(%)",
                    ],
                    title="용도별 추정 사용량 감소",
                )
                fig_use.update_layout(
                    xaxis_title="용도",
                    yaxis_title=f"추정 사용량 감소 ({unit_label})",
                    margin=dict(l=40, r=20, t=60, b=40),
                )
                st.plotly_chart(fig_use, use_container_width=True)

                st.dataframe(
                    use_agg.set_index(COL_USAGE),
                    use_container_width=True,
                    height=300,
                )

                # ─────────────────────────────
                # ③ 인덕션 비중 연도×시군구 히트맵 (추세용, 화면 최하단)
                # ─────────────────────────────
                st.markdown("---")
                st.markdown("#### ▸ 연도 × 시군구 인덕션 비중(%) 히트맵")

                heat_ind = (
                    dfu.groupby(["연도", COL_DISTRICT], as_index=False)
                    .agg(
                        전체청구전수합=("전체청구전수", "sum"),
                        인덕션세대합=("추정_인덕션세대수", "sum"),
                    )
                )
                heat_ind["인덕션비중(%)"] = np.where(
                    heat_ind["전체청구전수합"] > 0,
                    heat_ind["인덕션세대합"]
                    / heat_ind["전체청구전수합"]
                    * 100,
                    np.nan,
                )

                pivot_ind = heat_ind.pivot(
                    index="연도", columns=COL_DISTRICT, values="인덕션비중(%)"
                ).sort_index()

                fig_ind_heat = px.imshow(
                    pivot_ind,
                    labels=dict(x="시군구", y="연도", color="인덕션비중(%)"),
                    aspect="auto",
                    title="연도 × 시군구 인덕션 비중(%) 히트맵",
                    color_continuous_scale="Blues",
                )
                fig_ind_heat.update_xaxes(side="top")
                st.plotly_chart(fig_ind_heat, use_container_width=True)

                # ─────────────────────────────
                # ④ 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)
                #   - 분석1의 "군구별 감소량 지도"를 분석2 화면 맨 하단에 재표시
                # ─────────────────────────────
                st.markdown("---")
                st.markdown("### ④ 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

                # map_table 계산 (캐시)  ─ 시군구 선택 필터와 무관하게, 대구 8개 구·군 + 경산시만 표시
                map_table = build_map_table_cached(
                    df_raw=df_usage_raw,
                    usage_sel=tuple(usage_sel),
                    product_sel=tuple(product_sel),
                    base_year=int(base_year),
                    comp_year=int(comp_year),
                )

                if map_table.empty:
                    st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
                else:
                    # ─ GeoJSON 매핑 ─
                    if geojson is not None and GEO_NAME_FIELD is not None:
                        geo_names = [
                            str(f["properties"].get(GEO_NAME_FIELD, ""))
                            for f in geojson.get("features", [])
                        ]
                        map_table = _attach_geo_key(map_table, geojson, GEO_NAME_FIELD)
                        st.caption(
                            f"GeoJSON feature 개수: {len(geo_names)}, "
                            f"선택된 속성필드: {GEO_NAME_FIELD}"
                        )
                    else:
                        map_table["geo_key"] = map_table["시군구"]
                        st.caption(
                            "GeoJSON 속성 필드를 자동 선택하지 못했어. "
                            "시군구 이름 그대로 사용 중."
                        )

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

                    # 지도 (folium 우선 + 없으면 plotly 백업)
                    with c2:
                        if geojson is None or GEO_NAME_FIELD is None:
                            st.warning(
                                f"대구+경산 GeoJSON({GEO_PATH})을 찾을 수 없거나, "
                                "시군구 이름이 들어 있는 속성 필드를 찾지 못해서 지도를 그릴 수 없어."
                            )
                        else:
                            if FOLIUM_OK:
                                # Streamlit 재실행 시 “불필요 리로드” 줄이기 위한 key
                                map_key = (
                                    f"folium_map_2nd_{base_year}_{comp_year}_"
                                    + "_".join(sorted(usage_sel))
                                    + "_"
                                    + "_".join(sorted(product_sel))
                                )

                                m = build_folium_choropleth(
                                    map_table=map_table,
                                    geojson=geojson,
                                    GEO_NAME_FIELD=GEO_NAME_FIELD,
                                    base_year=int(base_year),
                                    comp_year=int(comp_year),
                                )
                                # returned_objects=[] 로 클릭/마우스 이벤트 반환 끊어서 리로드 최소화
                                st_folium(m, use_container_width=True, returned_objects=[], key=map_key)
                            else:
                                # folium 미설치 → Plotly로 자동 백업 (기존 기능 유지)
                                st.warning(
                                    "현재 실행환경에 folium(또는 streamlit-folium)이 설치되어 있지 않아서 "
                                    "Plotly 지도로 대체 표시 중이야.\n"
                                    f"- 에러: `{FOLIUM_ERR}`"
                                )

                                fig_map = px.choropleth(
                                    map_table,
                                    geojson=geojson,
                                    locations="geo_key",
                                    featureidkey=f"properties.{GEO_NAME_FIELD}",
                                    color="감소량(기준-비교)",
                                    hover_name="시군구",
                                    hover_data={
                                        f"{base_year}년 가스레인지 수(연간합계)": True,
                                        f"{comp_year}년 가스레인지 수(연간합계)": True,
                                        "감소량(기준-비교)": True,
                                        "감소율(%)": True,
                                    },
                                    color_continuous_scale="RdBu_r",
                                    color_continuous_midpoint=0,
                                )

                                fig_map.update_geos(
                                    fitbounds="locations",
                                    visible=False,
                                )

                                fig_map.update_traces(
                                    marker_line_width=0.8,
                                    marker_line_color="white",
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
