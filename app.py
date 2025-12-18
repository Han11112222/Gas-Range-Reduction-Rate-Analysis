# app.py ─ 가정용 가스레인지 감소 분석 (대구 + 경산)
# - 분석1(인덕션 사용량 분석 1st): ① 월별·연도별 추이  /  ② 대구시 8개 구·군 + 경산시 감소량 지도
# - 분석2(인덕션 사용량 분석 2nd): 인덕션(비가스레인지) 추정 + 사용량 감소 추정 (연도별 / 시군구·용도별)
#
# ※ 인덕션 추정 가정(업데이트)
#   - 추정 인덕션 세대수 = [총청구계량기수 시트의 전수] − [계량기_가스렌지연결 시트의 전수]
#     (해당 컬럼이 없으면 fallback: 전체청구전수 − 가스레인지수)

from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.express as px
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
st.set_page_config(page_title="가정용 가스레인지 감소 분석 (대구)", layout="wide")
st.title("🏠 가정용 가스레인지 감소 분석 (대구)")


# ─────────────────────────────────────
# 경로/상수
# ─────────────────────────────────────
BASE_DIR = Path(__file__).parent

# 분석1 기본 파일
DATA_PATH = BASE_DIR / "(ver2)가정용_가스레인지_사용유무.xlsx"

# 분석2 파일(있으면 v3 우선, 없으면 v2_사용량추가)
DATA_PATH_V3 = BASE_DIR / "(ver3)가정용_가스레인지_사용유무(201501_202412)_정보추가.xlsx"
DATA_PATH_V2_USAGE = BASE_DIR / "(ver2)가정용_가스레인지_사용유무(201501_202412)_사용량추가.xlsx"

# 지도용 GeoJSON
GEO_PATH_CANDIDATES = [
    BASE_DIR / "daegu_gyeongsan_sgg.geojson",
    BASE_DIR / "data" / "daegu_gyeongsan_sgg.geojson",
]
GEO_PATH = next((p for p in GEO_PATH_CANDIDATES if p.exists()), None)

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
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False),
        errors="coerce"
    ).fillna(0).astype(int)


def _standardize_common_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # 기본 문자 컬럼
    for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()

    # 가스레인지 수 컬럼 보정
    if COL_RANGE_CNT not in df.columns:
        for c in df.columns:
            cc = str(c)
            if ("가스레인지" in cc) and ("수" in cc):
                df.rename(columns={c: COL_RANGE_CNT}, inplace=True)
                break
    if COL_RANGE_CNT not in df.columns:
        df[COL_RANGE_CNT] = 0
    df[COL_RANGE_CNT] = to_int_series(df[COL_RANGE_CNT])

    return df


# ─────────────────────────────────────
# ✅ 데이터 로딩 (분석1) - Streamlit Cloud에서 안 죽게 "연도/월" 생성 안정화
# ─────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    # 1) header=0 형태 우선 시도
    try:
        df0 = pd.read_excel(DATA_PATH, sheet_name=0)
        df0.columns = [str(c).strip() for c in df0.columns]
    except Exception:
        df0 = pd.DataFrame()

    def _make_year_month(df_in: pd.DataFrame) -> pd.DataFrame:
        df = _standardize_common_cols(df_in)

        # 연월 컬럼명 보정(공백 등)
        if COL_YEAR_MONTH not in df.columns:
            for c in df.columns:
                if str(c).strip() == COL_YEAR_MONTH:
                    df.rename(columns={c: COL_YEAR_MONTH}, inplace=True)
                    break

        # 연도/월이 있으면 숫자화
        if "연도" in df.columns:
            df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
        if "월" in df.columns:
            df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")

        # 없으면 연월(YYYYMM)에서 생성
        if ("연도" not in df.columns or "월" not in df.columns) and (COL_YEAR_MONTH in df.columns):
            s = df[COL_YEAR_MONTH].astype(str).str.strip()
            s = s.str.replace(r"\.0$", "", regex=True)  # 201501.0 방지

            if "연도" not in df.columns:
                df["연도"] = pd.to_numeric(s.str.slice(0, 4), errors="coerce").astype("Int64")
            if "월" not in df.columns:
                df["월"] = pd.to_numeric(s.str.slice(4, 6), errors="coerce").astype("Int64")

        return df

    # df0가 정상 포맷이면 바로 사용
    if not df0.empty and (("연도" in df0.columns) or (COL_YEAR_MONTH in df0.columns)):
        df_try = _make_year_month(df0)
        if "연도" in df_try.columns and df_try["연도"].notna().any():
            return df_try

    # 2) fallback: header=None → '연월'이 들어있는 행을 헤더로 찾아서 파싱
    raw = pd.read_excel(DATA_PATH, sheet_name=0, header=None)

    header_idx = None
    for i in range(len(raw)):
        row = raw.iloc[i].astype(str).str.strip()
        if (row == COL_YEAR_MONTH).any():
            header_idx = i
            break

    if header_idx is None:
        st.error(f"엑셀에서 '{COL_YEAR_MONTH}' 헤더 행을 찾지 못했어. (파일 포맷 확인 필요)")
        st.stop()

    header = raw.iloc[header_idx].tolist()
    df2 = raw.iloc[header_idx + 1:].copy()
    df2.columns = [str(h).strip() for h in header]
    df2 = df2.dropna(how="all")

    df_final = _make_year_month(df2)

    if "연도" not in df_final.columns or df_final["연도"].isna().all():
        st.error("연도 컬럼 생성 실패. '연월' 값이 YYYYMM 형태인지 확인해줘.")
        st.stop()

    return df_final


# ─────────────────────────────────────
# 데이터 로딩 (분석2)
# ─────────────────────────────────────
@st.cache_data
def load_data_with_usage() -> pd.DataFrame | None:
    path = None
    if DATA_PATH_V3.exists():
        path = DATA_PATH_V3
    elif DATA_PATH_V2_USAGE.exists():
        path = DATA_PATH_V2_USAGE
    else:
        return None

    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    df = _standardize_common_cols(df)

    # 연도 확보
    if "연도" not in df.columns:
        if COL_YEAR_MONTH in df.columns:
            s = df[COL_YEAR_MONTH].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            df["연도"] = pd.to_numeric(s.str.slice(0, 4), errors="coerce").astype("Int64")
        else:
            return None
    else:
        df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")

    # 전체청구전수
    if "전체청구전수" not in df.columns:
        for c in df.columns:
            if ("전체" in str(c)) and ("청구" in str(c)) and ("전수" in str(c)):
                df.rename(columns={c: "전체청구전수"}, inplace=True)
                break
    if "전체청구전수" in df.columns:
        df["전체청구전수"] = to_int_series(df["전체청구전수"])
    else:
        df["전체청구전수"] = np.nan

    # 가스렌지연결_청구전수 (있으면 사용)
    if "가스렌지연결_청구전수" in df.columns:
        df["가스렌지연결_청구전수"] = to_int_series(df["가스렌지연결_청구전수"])
    else:
        df["가스렌지연결_청구전수"] = np.nan

    # 사용량(기준)
    if "사용량_기준" not in df.columns:
        for c in df.columns:
            if ("사용량" in str(c)) and ("기준" in str(c) or "MJ" in str(c) or "m3" in str(c)):
                df.rename(columns={c: "사용량_기준"}, inplace=True)
                break
    if "사용량_기준" in df.columns:
        df["사용량_기준"] = pd.to_numeric(
            df["사용량_기준"].astype(str).str.replace(",", "", regex=False),
            errors="coerce"
        ).fillna(0)
    else:
        df["사용량_기준"] = 0.0

    return df


# ─────────────────────────────────────
# GeoJSON 로딩
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

    features = gj.get("features", [])
    if not features:
        return gj, None

    props_keys = list(features[0].get("properties", {}).keys())
    best_field, best_score = None, -1
    target_set = set(TARGET_SIGUNGU)

    for key in props_keys:
        values = [str(f["properties"].get(key, "")) for f in features]
        score = sum(1 for d in target_set if any(d in v for v in values))
        if score > best_score:
            best_score, best_field = score, key

    return gj, best_field


geojson, GEO_NAME_FIELD = load_geojson()


def _attach_geo_key(map_table: pd.DataFrame, geojson: dict, geo_field: str) -> pd.DataFrame:
    mt = map_table.copy()
    geo_names = [str(f["properties"].get(geo_field, "")) for f in geojson.get("features", [])]

    def find_geo_name(d):
        for name in geo_names:
            if d == name:
                return name
        for name in geo_names:
            if d in name or name in d:
                return name
        return None

    mt["geo_key"] = mt["시군구"].apply(find_geo_name)
    mt.loc[mt["geo_key"].isna(), "geo_key"] = mt.loc[mt["geo_key"].isna(), "시군구"]
    return mt


def build_map_table(df_raw: pd.DataFrame, usage_sel: list, product_sel: list, base_year: int, comp_year: int) -> pd.DataFrame:
    df_map = df_raw.copy()
    df_map = df_map[df_map[COL_USAGE].isin(usage_sel)]
    df_map = df_map[df_map[COL_PRODUCT].isin(product_sel)]
    df_map = df_map[df_map[COL_DISTRICT].isin(TARGET_SIGUNGU)]
    df_map = df_map[df_map["연도"].isin([base_year, comp_year])]

    if df_map.empty:
        return pd.DataFrame()

    grp = (
        df_map.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
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

    return pd.DataFrame(
        rows,
        columns=[
            "시군구",
            f"{base_year}년 가스레인지 수(연간합계)",
            f"{comp_year}년 가스레인지 수(연간합계)",
            "감소량(기준-비교)",
            "감소율(%)",
        ],
    )


@st.cache_data
def build_folium_choropleth(map_table: pd.DataFrame, geojson: dict, geo_field: str, base_year: int, comp_year: int):
    m = folium.Map(location=[35.87, 128.60], zoom_start=10, tiles="cartodbpositron")

    vcol = "감소량(기준-비교)"
    vals = map_table[vcol].astype(float).to_list()
    vmin = float(np.nanmin(vals)) if len(vals) else 0.0
    vmax = float(np.nanmax(vals)) if len(vals) else 0.0
    if vmin == vmax:
        vmin -= 1.0
        vmax += 1.0

    absmax = max(abs(vmin), abs(vmax))
    vmin2, vmax2 = -absmax, absmax

    cmap = LinearColormap(["#2c7bb6", "#ffffbf", "#d7191c"], vmin=vmin2, vmax=vmax2)
    cmap.caption = f"감소량(기준-비교) : {base_year}년 - {comp_year}년"
    cmap.add_to(m)

    row_by_key = {r["geo_key"]: r for _, r in map_table.iterrows()}

    def style_function(feature):
        key = str(feature["properties"].get(geo_field, ""))
        row = row_by_key.get(key)
        if row is None:
            return {"fillOpacity": 0.15, "weight": 0.8, "color": "white", "fillColor": "#999999"}
        val = float(row.get("감소량(기준-비교)", 0.0))
        return {"fillOpacity": 0.7, "weight": 0.8, "color": "white", "fillColor": cmap(val)}

    def highlight_function(_):
        return {"weight": 2, "color": "#333333", "fillOpacity": 0.85}

    tooltip = folium.GeoJsonTooltip(fields=[geo_field], aliases=["시군구"], sticky=True)

    folium.GeoJson(
        geojson,
        name="choropleth",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m


# ─────────────────────────────────────
# 사이드바
# ─────────────────────────────────────
st.sidebar.markdown("## ⚙️ 분석 조건")

analysis_mode = st.sidebar.radio(
    "분석 탭 선택",
    ["인덕션 사용량 분석 1st", "인덕션 사용량 분석 2nd"],
    index=0,
)

df = load_data()

year_list = sorted(df["연도"].dropna().unique().tolist())
usage_list = sorted(df[COL_USAGE].dropna().unique().tolist())
product_list = sorted(df[COL_PRODUCT].dropna().unique().tolist())
district_list = sorted(df[COL_DISTRICT].dropna().unique().tolist())

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
# 분석1
# ─────────────────────────────────────
if analysis_mode == "인덕션 사용량 분석 1st":
    st.subheader("인덕션 사용량 분석 1st — 가스레인지 수 추이 및 군구별 감소량 지도")

    tab1, tab2 = st.tabs(["① 월별·연도별 추이", "② 군구별 감소량 지도"])

    with tab1:
        df_raw = df.copy()
        df_raw = df_raw[df_raw[COL_USAGE].isin(usage_sel)]
        df_raw = df_raw[df_raw[COL_PRODUCT].isin(product_sel)]
        if len(district_sel) > 0:
            df_raw = df_raw[df_raw[COL_DISTRICT].isin(district_sel)]

        if df_raw.empty:
            st.info("현재 필터 조건에 해당하는 데이터가 없어.")
        else:
            month_series = (
                df_raw.groupby(COL_YEAR_MONTH, as_index=False)[COL_RANGE_CNT]
                .sum()
                .sort_values(COL_YEAR_MONTH)
            )
            st.plotly_chart(
                px.line(month_series, x=COL_YEAR_MONTH, y=COL_RANGE_CNT, markers=True, title="월별 가스레인지 수(합계) 추이"),
                use_container_width=True
            )

            year_series = (
                df_raw.groupby("연도", as_index=False)[COL_RANGE_CNT]
                .sum()
                .sort_values("연도")
            )
            st.plotly_chart(
                px.bar(year_series, x="연도", y=COL_RANGE_CNT, title="연도별 가스레인지 수(연간합계)"),
                use_container_width=True
            )

            gu_year = (
                df_raw.groupby(["연도", COL_DISTRICT], as_index=False)[COL_RANGE_CNT]
                .sum()
                .sort_values(["연도", COL_DISTRICT])
            )
            if not gu_year.empty:
                st.plotly_chart(
                    px.line(gu_year, x="연도", y=COL_RANGE_CNT, color=COL_DISTRICT, markers=True,
                            title="시군구별 연도별 가스레인지 수 추이 (연간합계)"),
                    use_container_width=True
                )

    with tab2:
        st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

        map_table = build_map_table(df, usage_sel, product_sel, int(base_year), int(comp_year))
        if map_table.empty:
            st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
        else:
            if geojson is not None and GEO_NAME_FIELD is not None:
                map_table = _attach_geo_key(map_table, geojson, GEO_NAME_FIELD)
                st.caption(f"GeoJSON feature 개수: {len(geojson.get('features', []))}, 선택된 속성필드: {GEO_NAME_FIELD}")
            else:
                map_table["geo_key"] = map_table["시군구"]
                st.caption("GeoJSON을 못 읽어서 지도 대신 표만 표시될 수 있어.")

            c1, c2 = st.columns([2, 3])

            with c1:
                st.markdown(
                    f"**대구시 구·군 + 경산시 시군구별 가스레인지 수 및 변화 (연간합계 기준)**  \n"
                    f"(기준연도: {base_year}년, 비교연도: {comp_year}년)"
                )
                df_show = map_table.copy()
                for col in [f"{base_year}년 가스레인지 수(연간합계)", f"{comp_year}년 가스레인지 수(연간합계)", "감소량(기준-비교)"]:
                    df_show[col] = df_show[col].apply(lambda x: f"{int(x):,}")
                df_show["감소율(%)"] = df_show["감소율(%)"].apply(lambda x: "" if pd.isna(x) else f"{x:.1f}")
                st.dataframe(df_show.set_index("시군구"), use_container_width=True, height=450)

            with c2:
                if geojson is None or GEO_NAME_FIELD is None:
                    st.warning("GeoJSON이 없어서 지도를 표시할 수 없어.")
                else:
                    if FOLIUM_OK:
                        m = build_folium_choropleth(map_table, geojson, GEO_NAME_FIELD, int(base_year), int(comp_year))
                        st_folium(m, use_container_width=True, returned_objects=[], key=f"map1_{base_year}_{comp_year}")
                    else:
                        st.warning(f"folium 미설치로 Plotly 지도로 대체 표시 중이야. (에러: `{FOLIUM_ERR}`)")
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
                            title=f"{base_year}년 → {comp_year}년 대구시 구·군 + 경산시 시군구별 가스레인지 감소량",
                        )
                        fig_map.update_geos(fitbounds="locations", visible=False)
                        fig_map.update_layout(margin=dict(l=0, r=0, t=40, b=0))
                        st.plotly_chart(fig_map, use_container_width=True)


# ─────────────────────────────────────
# 분석2
# ─────────────────────────────────────
else:
    st.subheader("인덕션 사용량 분석 2nd — 인덕션(비가스레인지) 사용 추정 및 사용량 감소 분석")

    df_usage_raw = load_data_with_usage()
    if df_usage_raw is None:
        st.error(
            "분석2용 파일을 못 찾았어.\n"
            "- (ver3)...정보추가.xlsx 또는 (ver2)...사용량추가.xlsx 가 레포에 있어야 해."
        )
        st.stop()

    dfu = df_usage_raw.copy()
    dfu = dfu[dfu[COL_USAGE].isin(usage_sel)]
    dfu = dfu[dfu[COL_PRODUCT].isin(product_sel)]
    if len(district_sel) > 0:
        dfu = dfu[dfu[COL_DISTRICT].isin(district_sel)]

    if dfu.empty:
        st.info("현재 필터 조건에 해당하는 데이터가 없어.")
        st.stop()

    # 인덕션 추정
    if dfu["가스렌지연결_청구전수"].notna().any():
        dfu["추정_인덕션세대수"] = (dfu["전체청구전수"] - dfu["가스렌지연결_청구전수"]).clip(lower=0)
    else:
        dfu["추정_인덕션세대수"] = (dfu["전체청구전수"] - dfu[COL_RANGE_CNT]).clip(lower=0)

    tab_a, tab_b = st.tabs(
        ["① 연도별 인덕션 사용 및 사용량 감소 추정", "② 시군구·용도별 인덕션/감소 추정"]
    )

    with tab_a:
        year_agg = (
            dfu.groupby("연도", as_index=False)
            .agg(
                가스레인지수합=(COL_RANGE_CNT, "sum"),
                전체청구전수합=("전체청구전수", "sum"),
                사용량합=("사용량_기준", "sum"),
                인덕션세대합=("추정_인덕션세대수", "sum"),
            )
            .sort_values("연도")
        )

        year_agg["인덕션비중(%)"] = np.where(
            year_agg["전체청구전수합"] > 0,
            year_agg["인덕션세대합"] / year_agg["전체청구전수합"] * 100,
            np.nan
        ).round(2)

        year_agg["가스레인지세대합"] = (year_agg["전체청구전수합"] - year_agg["인덕션세대합"]).clip(lower=0)
        year_agg["가스레인지세대당평균사용량"] = np.where(
            year_agg["가스레인지세대합"] > 0,
            year_agg["사용량합"] / year_agg["가스레인지세대합"],
            np.nan
        )
        year_agg["추정_사용량감소"] = year_agg["가스레인지세대당평균사용량"] * year_agg["인덕션세대합"]

        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(
                px.line(year_agg, x="연도", y="인덕션비중(%)", markers=True, title="연도별 인덕션 비중(%)"),
                use_container_width=True
            )
        with c2:
            st.plotly_chart(
                px.bar(year_agg, x="연도", y="추정_사용량감소", title="연도별 추정 사용량 감소 (사용량_기준)"),
                use_container_width=True
            )

        st.dataframe(year_agg.set_index("연도"), use_container_width=True, height=320)

    with tab_b:
        grp = (
            dfu.groupby([COL_DISTRICT, COL_USAGE], as_index=False)
            .agg(
                가스레인지수합=(COL_RANGE_CNT, "sum"),
                전체청구전수합=("전체청구전수", "sum"),
                사용량합=("사용량_기준", "sum"),
                인덕션세대합=("추정_인덕션세대수", "sum"),
            )
        )
        grp["가스레인지세대수"] = (grp["전체청구전수합"] - grp["인덕션세대합"]).clip(lower=0)
        grp["가스레인지세대당평균사용량"] = np.where(
            grp["가스레인지세대수"] > 0,
            grp["사용량합"] / grp["가스레인지세대수"],
            np.nan
        )
        grp["추정_사용량감소"] = grp["가스레인지세대당평균사용량"] * grp["인덕션세대합"]

        st.markdown("### ② 시군구별 추정 사용량 감소")
        gu_agg = (
            grp.groupby(COL_DISTRICT, as_index=False)
            .agg(
                인덕션세대합=("인덕션세대합", "sum"),
                사용량합=("사용량합", "sum"),
                추정_사용량감소=("추정_사용량감소", "sum"),
            )
        )
        gu_agg["감소율(%)"] = np.where(
            gu_agg["사용량합"] > 0,
            gu_agg["추정_사용량감소"] / gu_agg["사용량합"] * 100,
            np.nan
        ).round(1)

        st.plotly_chart(
            px.bar(
                gu_agg.sort_values("추정_사용량감소", ascending=False),
                x=COL_DISTRICT, y="추정_사용량감소",
                hover_data=["인덕션세대합", "사용량합", "감소율(%)"],
                title="시군구별 추정 사용량 감소 (사용량_기준)"
            ),
            use_container_width=True
        )
        st.dataframe(gu_agg.set_index(COL_DISTRICT), use_container_width=True, height=320)

        st.markdown("---")
        st.markdown("### ▸ 연도 × 시군구 인덕션 비중(%) 히트맵")
        heat_ind = (
            dfu.groupby(["연도", COL_DISTRICT], as_index=False)
            .agg(
                전체청구전수합=("전체청구전수", "sum"),
                인덕션세대합=("추정_인덕션세대수", "sum"),
            )
        )
        heat_ind["인덕션비중(%)"] = np.where(
            heat_ind["전체청구전수합"] > 0,
            heat_ind["인덕션세대합"] / heat_ind["전체청구전수합"] * 100,
            np.nan
        )
        pivot_ind = heat_ind.pivot(index="연도", columns=COL_DISTRICT, values="인덕션비중(%)").sort_index()
        fig_ind_heat = px.imshow(
            pivot_ind,
            labels=dict(x="시군구", y="연도", color="인덕션비중(%)"),
            aspect="auto",
            title="연도 × 시군구 인덕션 비중(%) 히트맵",
            color_continuous_scale="Blues",
        )
        fig_ind_heat.update_xaxes(side="top")
        st.plotly_chart(fig_ind_heat, use_container_width=True)

        # ✅ 요청: 2nd 맨하단에 "군구별 감소량 지도(표+지도)" 추가
        st.markdown("---")
        st.markdown("## ④ 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

        map_table2 = build_map_table(df_usage_raw, usage_sel, product_sel, int(base_year), int(comp_year))
        if map_table2.empty:
            st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
        else:
            if geojson is not None and GEO_NAME_FIELD is not None:
                map_table2 = _attach_geo_key(map_table2, geojson, GEO_NAME_FIELD)
                st.caption(f"GeoJSON feature 개수: {len(geojson.get('features', []))}, 선택된 속성필드: {GEO_NAME_FIELD}")

            c1, c2 = st.columns([2, 3])

            with c1:
                df_show = map_table2.copy()
                for col in [f"{base_year}년 가스레인지 수(연간합계)", f"{comp_year}년 가스레인지 수(연간합계)", "감소량(기준-비교)"]:
                    df_show[col] = df_show[col].apply(lambda x: f"{int(x):,}")
                df_show["감소율(%)"] = df_show["감소율(%)"].apply(lambda x: "" if pd.isna(x) else f"{x:.1f}")
                st.dataframe(df_show.set_index("시군구"), use_container_width=True, height=450)

            with c2:
                if geojson is None or GEO_NAME_FIELD is None:
                    st.warning("GeoJSON이 없어서 지도를 표시할 수 없어.")
                else:
                    if FOLIUM_OK:
                        m2 = build_folium_choropleth(map_table2, geojson, GEO_NAME_FIELD, int(base_year), int(comp_year))
                        st_folium(m2, use_container_width=True, returned_objects=[], key=f"map2_{base_year}_{comp_year}")
                    else:
                        fig_map2 = px.choropleth(
                            map_table2,
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
                            title=f"{base_year}년 → {comp_year}년 대구시 구·군 + 경산시 시군구별 가스레인지 감소량",
                        )
                        fig_map2.update_geos(fitbounds="locations", visible=False)
                        fig_map2.update_layout(margin=dict(l=0, r=0, t=40, b=0))
                        st.plotly_chart(fig_map2, use_container_width=True)
