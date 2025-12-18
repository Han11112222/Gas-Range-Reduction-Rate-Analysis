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
    page_title="가정용 가스레인지 감소 분석 (대구)",
    layout="wide"
)
st.title("🏠 가정용 가스레인지 감소 분석 (대구)")

# ─────────────────────────────────────
# 데이터 / GeoJSON 경로
# ─────────────────────────────────────
BASE_DIR = Path(__file__).parent

# 분석1에서 사용하던 기존 파일
DATA_PATH = BASE_DIR / "(ver2)가정용_가스레인지_사용유무.xlsx"

# 사용량·전체청구전수가 포함된 새 파일 (2015.01~2024.12) ─ v3(우선), v2(백업)
DATA_PATH_USAGE_V3 = BASE_DIR / "(ver3)가정용_가스레인지_사용유무(201501_202412)_정보추가.xlsx"
DATA_PATH_USAGE_V2 = BASE_DIR / "(ver2)가정용_가스레인지_사용유무(201501_202412)_사용량추가.xlsx"

# GeoJSON (네가 올린 구조: /data/daegu_gyeongsan_sgg.geojson)
GEO_PATH = BASE_DIR / "data" / "daegu_gyeongsan_sgg.geojson"

# 엑셀 공통 컬럼 이름(분석1, 분석2 모두 이 이름으로 맞춰 사용)
COL_YEAR_MONTH = "구분"         # 201501, 201502 …
COL_USAGE = "용도"              # 단독주택 / 공동주택
COL_PRODUCT = "상품"            # 취사용 / 취사난방용 / 개별난방용
COL_DISTRICT = "시군구"         # 중구 / 동구 / 경산시 …
COL_RANGE_CNT = "가스레인지수"   # 가스레인지 수

# 대구 + 경산 시군구(표/지도 정렬 기준)
TARGET_SIGUNGU = [
    "중구", "동구", "서구", "남구", "북구",
    "수성구", "달서구", "달성군",
    "경산시",
]

# ─────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────
def _to_int_series(s: pd.Series) -> pd.Series:
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

    # 첫 열에서 '구분' 행을 찾는다
    first_col = raw.iloc[:, 0].astype(str).str.strip()
    header_rows = first_col[first_col == COL_YEAR_MONTH].index.tolist()
    if not header_rows:
        st.error(f"엑셀에서 '{COL_YEAR_MONTH}' 헤더 행을 찾지 못했어. 엑셀 컬럼명을 확인해줘.")
        st.stop()
    header_idx = header_rows[0]

    # 헤더/데이터 분리
    header = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header
    df = df.dropna(how="all")

    # 구분 → 연도, 월
    df[COL_YEAR_MONTH] = df[COL_YEAR_MONTH].astype(str).str.strip()
    df["연도"] = df[COL_YEAR_MONTH].str[:4].astype(int)
    df["월"] = df[COL_YEAR_MONTH].str[4:6].astype(int)

    # 가스레인지 수 숫자 변환
    df[COL_RANGE_CNT] = _to_int_series(df[COL_RANGE_CNT])

    # 문자열 컬럼 정리
    for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
        df[c] = df[c].astype(str).str.strip()

    return df


# ─────────────────────────────────────
# 데이터 로딩 (분석2: 사용량·전체청구전수 포함 파일)
#   - v3: 여러 시트를 이용해 '전체청구전수', '가스렌지연결_청구전수' 계산
#   - v2: 이전 방식(단일 시트) 백업
# ─────────────────────────────────────
@st.cache_data
def load_data_with_usage():
    """
    사용량/전체청구전수를 포함한 파일 로딩.
    v3 파일이 존재하면 다음 논리를 사용:
      - 가스렌지수 시트: 기본 가스레인지 수 + 사용량
      - 계량기_가스렌지연결 시트: 가스레인지에 연결된 청구 계량기 수
      - 총청구계량기수 시트: 전체 청구 계량기 수
      → 추정 인덕션 세대수 = 총청구계량기수 − 계량기_가스렌지연결
    v3가 없고 v2만 있을 때는 기존 방식(전체청구전수 − 가스레인지수)을 사용.
    """
    # ───────────── v3 우선 사용 ─────────────
    if DATA_PATH_USAGE_V3.exists():
        # 1) 가스렌지수 시트 ─ 기본 틀 + 사용량
        df_gas = pd.read_excel(DATA_PATH_USAGE_V3, sheet_name="가스렌지수")

        rename_main = {}
        if "년월" in df_gas.columns:
            rename_main["년월"] = COL_YEAR_MONTH
        if "구분" in df_gas.columns:
            rename_main["구분"] = COL_YEAR_MONTH
        if "상품명" in df_gas.columns:
            rename_main["상품명"] = COL_PRODUCT
        if "상품" in df_gas.columns:
            rename_main["상품"] = COL_PRODUCT
        if "용도" in df_gas.columns:
            rename_main["용도"] = COL_USAGE
        if "시군구" in df_gas.columns:
            rename_main["시군구"] = COL_DISTRICT
        if "가스렌지수" in df_gas.columns:
            rename_main["가스렌지수"] = COL_RANGE_CNT

        df_gas = df_gas.rename(columns=rename_main)

        # 기본 문자열/날짜 컬럼 정리
        df_gas[COL_YEAR_MONTH] = df_gas[COL_YEAR_MONTH].astype(str).str.strip()
        df_gas["연도"] = df_gas[COL_YEAR_MONTH].str[:4].astype(int)
        df_gas["월"] = df_gas[COL_YEAR_MONTH].str[4:6].astype(int)

        for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
            if c in df_gas.columns:
                df_gas[c] = df_gas[c].astype(str).str.strip()

        # 가스레인지 수
        df_gas[COL_RANGE_CNT] = _to_int_series(df_gas[COL_RANGE_CNT])

        # 사용량(m3 / MJ) 컬럼 찾기
        col_m3 = next((c for c in df_gas.columns if "사용량" in c and "3" in c), None)
        col_mj = next(
            (c for c in df_gas.columns if "사용량" in c and ("MJ" in c or "mj" in c or "Mj" in c)),
            None,
        )

        if col_m3 is not None:
            df_gas["사용량_m3"] = pd.to_numeric(
                df_gas[col_m3].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)

        if col_mj is not None:
            df_gas["사용량_MJ"] = pd.to_numeric(
                df_gas[col_mj].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)

        if "사용량_MJ" in df_gas.columns:
            df_gas["사용량_기준"] = df_gas["사용량_MJ"]
        elif "사용량_m3" in df_gas.columns:
            df_gas["사용량_기준"] = df_gas["사용량_m3"]
        else:
            df_gas["사용량_기준"] = np.nan

        # 2) 계량기_가스렌지연결 시트 ─ 가스레인지 연결 청구전수
        df_conn = pd.read_excel(DATA_PATH_USAGE_V3, sheet_name="계량기_가스렌지연결")

        rename_conn = {}
        if "년월" in df_conn.columns:
            rename_conn["년월"] = COL_YEAR_MONTH
        if "구분" in df_conn.columns:
            rename_conn["구분"] = COL_YEAR_MONTH
        if "상품명" in df_conn.columns:
            rename_conn["상품명"] = COL_PRODUCT
        if "상품" in df_conn.columns:
            rename_conn["상품"] = COL_PRODUCT
        if "용도" in df_conn.columns:
            rename_conn["용도"] = COL_USAGE
        if "시군구" in df_conn.columns:
            rename_conn["시군구"] = COL_DISTRICT
        if "전수" in df_conn.columns:
            rename_conn["전수"] = "가스렌지연결_청구전수"

        df_conn = df_conn.rename(columns=rename_conn)
        key_cols = [COL_YEAR_MONTH, COL_USAGE, COL_PRODUCT, COL_DISTRICT]

        for c in key_cols:
            df_conn[c] = df_conn[c].astype(str).str.strip()

        df_conn["가스렌지연결_청구전수"] = _to_int_series(df_conn["가스렌지연결_청구전수"])
        df_conn_agg = (
            df_conn.groupby(key_cols, as_index=False)["가스렌지연결_청구전수"]
            .sum()
        )

        # 3) 총청구계량기수 시트 ─ 전체 청구전수
        df_total = pd.read_excel(DATA_PATH_USAGE_V3, sheet_name="총청구계량기수")

        rename_total = {}
        if "년월" in df_total.columns:
            rename_total["년월"] = COL_YEAR_MONTH
        if "구분" in df_total.columns:
            rename_total["구분"] = COL_YEAR_MONTH
        if "상품명" in df_total.columns:
            rename_total["상품명"] = COL_PRODUCT
        if "상품" in df_total.columns:
            rename_total["상품"] = COL_PRODUCT
        if "용도" in df_total.columns:
            rename_total["용도"] = COL_USAGE
        if "시군구" in df_total.columns:
            rename_total["시군구"] = COL_DISTRICT
        if "전수" in df_total.columns:
            rename_total["전수"] = "전체청구전수"

        df_total = df_total.rename(columns=rename_total)

        for c in key_cols:
            df_total[c] = df_total[c].astype(str).str.strip()

        df_total["전체청구전수"] = _to_int_series(df_total["전체청구전수"])
        df_total_agg = (
            df_total.groupby(key_cols, as_index=False)["전체청구전수"]
            .sum()
        )

        # 4) 메인 df에 병합
        for c in key_cols:
            df_gas[c] = df_gas[c].astype(str).str.strip()

        df = df_gas.merge(df_total_agg, on=key_cols, how="left")
        df = df.merge(df_conn_agg, on=key_cols, how="left")

        df["전체청구전수"] = df["전체청구전수"].fillna(0).astype(int)
        df["가스렌지연결_청구전수"] = df["가스렌지연결_청구전수"].fillna(0).astype(int)

        return df

    # ───────────── v2 백업 방식 ─────────────
    if DATA_PATH_USAGE_V2.exists():
        df = pd.read_excel(DATA_PATH_USAGE_V2)

        rename_map = {}
        if "년월" in df.columns:
            rename_map["년월"] = COL_YEAR_MONTH
        if "상품명" in df.columns:
            rename_map["상품명"] = COL_PRODUCT
        if "가스렌지수" in df.columns:
            rename_map["가스렌지수"] = COL_RANGE_CNT

        df = df.rename(columns=rename_map)

        df[COL_YEAR_MONTH] = df[COL_YEAR_MONTH].astype(str).str.strip()
        df["연도"] = df[COL_YEAR_MONTH].str[:4].astype(int)
        df["월"] = df[COL_YEAR_MONTH].str[4:6].astype(int)

        for c in [COL_USAGE, COL_PRODUCT, COL_DISTRICT]:
            if c in df.columns:
                df[c] = df[c].astype(str).str.strip()

        df[COL_RANGE_CNT] = _to_int_series(df[COL_RANGE_CNT])

        col_m3 = next((c for c in df.columns if "사용량" in c and "3" in c), None)
        col_mj = next(
            (c for c in df.columns if "사용량" in c and ("MJ" in c or "mj" in c or "Mj" in c)),
            None,
        )

        if col_m3 is not None:
            df["사용량_m3"] = pd.to_numeric(
                df[col_m3].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)

        if col_mj is not None:
            df["사용량_MJ"] = pd.to_numeric(
                df[col_mj].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0.0)

        if "사용량_MJ" in df.columns:
            df["사용량_기준"] = df["사용량_MJ"]
        elif "사용량_m3" in df.columns:
            df["사용량_기준"] = df["사용량_m3"]
        else:
            df["사용량_기준"] = np.nan

        if "전체청구전수" in df.columns:
            df["전체청구전수"] = _to_int_series(df["전체청구전수"])
        else:
            df["전체청구전수"] = np.nan

        # v2에는 '가스렌지연결_청구전수' 개념이 없으므로 NaN
        df["가스렌지연결_청구전수"] = np.nan

        return df

    # 둘 다 없으면 None
    return None


# ─────────────────────────────────────
# GeoJSON 로딩 (분석1 지도)
# ─────────────────────────────────────
@st.cache_data
def load_geojson():
    """대구+경산 시군구 GeoJSON 로딩 + 시군구 이름이 가장 잘 맞는 속성 필드 자동 선택"""
    try:
        with open(GEO_PATH, encoding="utf-8") as f:
            gj = json.load(f)
    except FileNotFoundError:
        return None, None

    features = gj.get("features", [])
    if not features:
        return gj, None

    props_keys = list(features[0]["properties"].keys())

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
            if d in name:
                return name
        return d

    mt["geo_key"] = mt["시군구"].apply(find_geo_name)
    return mt


def build_folium_choropleth(map_table: pd.DataFrame, geojson: dict, GEO_NAME_FIELD: str,
                            base_year: int, comp_year: int):
    """
    folium Choropleth + GeoJson 툴팁. (returned_objects=[]로 불필요 리로드 최소화)
    """
    center = [35.8714, 128.6014]
    m = folium.Map(location=center, zoom_start=10, tiles="CartoDB positron")

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

        v = row.get(vcol, np.nan)
        try:
            v = float(v)
        except Exception:
            v = np.nan

        return {
            "fillOpacity": 0.75,
            "weight": 0.8,
            "color": "white",
            "fillColor": cmap(v) if not np.isnan(v) else "#999999",
        }

    tooltip = folium.GeoJsonTooltip(
        fields=[GEO_NAME_FIELD],
        aliases=["시군구"],
        sticky=True
    )

    gj_layer = folium.GeoJson(
        geojson,
        name="choropleth",
        style_function=style_function,
        tooltip=tooltip,
    ).add_to(m)

    # 툴팁에 수치도 같이 보여주고 싶으면, 별도 Popup로 추가
    for feat in geojson.get("features", []):
        k = str(feat["properties"].get(GEO_NAME_FIELD, ""))
        row = row_by_key.get(k, None)
        if row is None:
            continue

        base_val = row.get(f"{base_year}년 가스레인지 수(연간합계)", 0)
        comp_val = row.get(f"{comp_year}년 가스레인지 수(연간합계)", 0)
        diff_val = row.get("감소량(기준-비교)", 0)
        rate_val = row.get("감소율(%)", np.nan)

        try:
            base_val = int(base_val)
        except Exception:
            base_val = 0
        try:
            comp_val = int(comp_val)
        except Exception:
            comp_val = 0
        try:
            diff_val = int(diff_val)
        except Exception:
            diff_val = 0

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
                tmp = folium.GeoJson(feat)
                # popup은 클릭 시 표시 (레이어 전체에 달면 과해져서 marker로 처리)
        except Exception:
            pass

    folium.LayerControl(collapsed=True).add_to(m)
    return m


# ─────────────────────────────────────
# 데이터 준비
# ─────────────────────────────────────
df_raw = load_data()
df_usage_raw = load_data_with_usage()
geojson, GEO_NAME_FIELD = load_geojson()

years = sorted(df_raw["연도"].unique())
usage_list = sorted(df_raw[COL_USAGE].unique())
product_list = sorted(df_raw[COL_PRODUCT].unique())
district_list = sorted(df_raw[COL_DISTRICT].unique())

# ─────────────────────────────────────
# 사이드바: 분석탭 선택을 최상단으로 + 공통 필터
# ─────────────────────────────────────
st.sidebar.header("⚙️ 분석 조건")

analysis_mode = st.sidebar.radio(
    "분석 탭 선택",
    ["1. 인덕션 사용량 분석 1st", "2. 인덕션 사용량 분석 2nd"],
    index=0,
)

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

# 공통 필터를 df_raw에 적용 (분석1 기본)
df = df_raw.copy()
df = df[df[COL_USAGE].isin(usage_sel)]
df = df[df[COL_PRODUCT].isin(product_sel)]
if len(district_sel) > 0:
    df = df[df[COL_DISTRICT].isin(district_sel)]

st.sidebar.markdown("---")
st.sidebar.write(f"데이터 행 수(분석1 기준): **{len(df):,}**")


# ─────────────────────────────────────
# 분석1: 기존 월별·연도별 추이 + 군구별 감소량 지도
# (인덕션 사용량 분석 1st)
# ─────────────────────────────────────
if analysis_mode.startswith("1."):
    st.subheader("인덕션 사용량 분석 1st ─ 가스레인지 수 추이 및 군구별 감소량 지도")

    tab1, tab2 = st.tabs(["① 월별·연도별 추이", "② 군구별 감소량 지도"])

    # ─────────────────────────────────
    # ① 월별·연도별 추이
    # ─────────────────────────────────
    with tab1:
        st.subheader("① 월별·연도별 가스레인지 수 추이")

        # 월 단위 집계
        month_series = (
            df.groupby(COL_YEAR_MONTH, as_index=False)[COL_RANGE_CNT]
            .sum()
        )
        month_series["date"] = pd.to_datetime(
            month_series[COL_YEAR_MONTH], format="%Y%m"
        )
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
            heat_pivot = monthly_for_heat.pivot(
                index="월", columns="연도", values=COL_RANGE_CNT
            )
            heat_pivot = heat_pivot.sort_index()

            fig_heat = px.imshow(
                heat_pivot,
                labels=dict(x="연도", y="월", color="가스레인지 수"),
                aspect="auto",
                title="연도 × 월 가스레인지 수 히트맵",
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
            df_raw=df_raw,
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
                map_table = _attach_geo_key(map_table, geojson, GEO_NAME_FIELD)

                geo_names = [
                    str(f["properties"].get(GEO_NAME_FIELD, ""))
                    for f in geojson.get("features", [])
                ]
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

            # 지도 (✅ 여기만 수정: folium 우선 + 없으면 plotly 백업)
            with c2:
                if geojson is None or GEO_NAME_FIELD is None:
                    st.warning(
                        f"대구+경산 GeoJSON({GEO_PATH})을 찾을 수 없거나, "
                        "시군구 이름이 들어 있는 속성 필드를 찾지 못해서 지도를 그릴 수 없어."
                    )
                else:
                    if FOLIUM_OK:
                        # Streamlit 재실행 시 “불필요 리로드” 줄이기 위한 key
                        map_key = f"folium_map_{base_year}_{comp_year}_" + "_".join(sorted(usage_sel)) + "_" + "_".join(sorted(product_sel))

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
                                f"{base_year}년 가스레인지 수(연간합계)": ":,",
                                f"{comp_year}년 가스레인지 수(연간합계)": ":,",
                                "감소량(기준-비교)": ":,",
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

    if df_usage_raw is None:
        st.warning(
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
            tab_a, tab_b = st.tabs(
                [
                    "① 연도별 인덕션 사용 및 사용량 감소 추정",
                    "② 시군구·용도별 인덕션/감소 추정",
                ]
            )

            # ─────────────────────────────
            # ① 연도별 인덕션 사용 및 사용량 감소
            # ─────────────────────────────
            with tab_a:
                st.markdown("### ① 연도별 인덕션 사용 및 사용량 감소 추정")

                # 연도별 집계
                agg_dict = {
                    "가스레인지수합": (COL_RANGE_CNT, "sum"),
                    "전체청구전수합": ("전체청구전수", "sum"),
                    "사용량합": ("사용량_기준", "sum"),
                }
                # v3인 경우: 가스렌지 연결 청구전수 집계
                if "가스렌지연결_청구전수" in dfu.columns:
                    agg_dict["가스렌지연결_청구전수합"] = ("가스렌지연결_청구전수", "sum")

                year_agg = (
                    dfu.groupby("연도", as_index=False)
                    .agg(**agg_dict)
                    .sort_values("연도")
                )

                # 인덕션(비가스레인지) 추정 세대
                if "가스렌지연결_청구전수합" in year_agg.columns:
                    base_induction = (
                        year_agg["전체청구전수합"] - year_agg["가스렌지연결_청구전수합"]
                    )
                else:
                    # v2 백업: 전체청구전수 − 가스레인지수
                    base_induction = (
                        year_agg["전체청구전수합"] - year_agg["가스레인지수합"]
                    )
                year_agg["추정_인덕션세대수"] = base_induction.clip(lower=0)

                # 인덕션 비중
                year_agg["인덕션비중(%)"] = np.where(
                    year_agg["전체청구전수합"] > 0,
                    year_agg["추정_인덕션세대수"]
                    / year_agg["전체청구전수합"]
                    * 100,
                    np.nan,
                ).round(1)

                # 가스레인지 1대당 평균 사용량
                year_agg["가스레인지당_평균사용량"] = np.where(
                    year_agg["가스레인지수합"] > 0,
                    year_agg["사용량합"] / year_agg["가스레인지수합"],
                    np.nan,
                )

                # 모든 세대가 가스레인지를 쓴다고 가정한 사용량
                year_agg["전세대_가정사용량"] = (
                    year_agg["가스레인지당_평균사용량"]
                    * year_agg["전체청구전수합"]
                )

                # 인덕션으로 인한 사용량 감소 추정 = (전세대 가정 사용량 - 실제 사용량)
                year_agg["추정_사용량감소"] = (
                    year_agg["전세대_가정사용량"] - year_agg["사용량합"]
                )
                year_agg["추정_사용량감소"] = year_agg["추정_사용량감소"].clip(lower=0)

                # 실제 사용량 대비 감소 비율
                year_agg["감소율(%)"] = np.where(
                    year_agg["사용량합"] > 0,
                    year_agg["추정_사용량감소"] / year_agg["사용량합"] * 100,
                    np.nan,
                ).round(1)

                unit_label = "MJ 또는 m³ 단위 (파일 기준)"

                c1, c2 = st.columns(2)

                # ─ 왼쪽 그래프: 전체 청구전 = 가스레인지 + 인덕션 (스택) + 인덕션 비중 라인
                with c1:
                    st.markdown("#### 연도별 전체 청구전 구성 (가스레인지 세대 + 추정 인덕션 세대)")

                    fig1 = go.Figure()
                    fig1.add_trace(
                        go.Bar(
                            x=year_agg["연도"],
                            y=year_agg["가스레인지수합"],
                            name="가스레인지 세대",
                            opacity=0.85,
                        )
                    )
                    fig1.add_trace(
                        go.Bar(
                            x=year_agg["연도"],
                            y=year_agg["추정_인덕션세대수"],
                            name="추정 인덕션 세대",
                            opacity=0.85,
                        )
                    )
                    fig1.add_trace(
                        go.Scatter(
                            x=year_agg["연도"],
                            y=year_agg["인덕션비중(%)"],
                            name="인덕션 비중(%)",
                            mode="lines+markers",
                            yaxis="y2",
                        )
                    )

                    fig1.update_layout(
                        title="연도별 전체 청구전수 구성 및 인덕션 비중",
                        xaxis_title="연도",
                        yaxis_title="세대 수 (전체 청구전)",
                        yaxis2=dict(
                            title="인덕션 비중(%)",
                            overlaying="y",
                            side="right",
                            showgrid=False,
                        ),
                        barmode="stack",
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1,
                        ),
                        margin=dict(l=40, r=40, t=70, b=50),
                    )
                    st.plotly_chart(fig1, use_container_width=True)

                # ─ 오른쪽 그래프: 사용량 + 감소량
                with c2:
                    st.markdown("#### 연도별 사용량 및 인덕션에 따른 추정 감소량")

                    fig2 = go.Figure()
                    fig2.add_trace(
                        go.Bar(
                            x=year_agg["연도"],
                            y=year_agg["사용량합"],
                            name=f"실제 사용량 ({unit_label})",
                            opacity=0.7,
                        )
                    )
                    fig2.add_trace(
                        go.Bar(
                            x=year_agg["연도"],
                            y=year_agg["추정_사용량감소"],
                            name="추정 감소량",
                            opacity=0.9,
                        )
                    )
                    fig2.update_layout(
                        title=f"연도별 사용량 및 인덕션에 따른 추정 감소량 ({unit_label})",
                        xaxis_title="연도",
                        yaxis_title=f"사용량 ({unit_label})",
                        barmode="stack",
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1,
                        ),
                        margin=dict(l=40, r=20, t=70, b=50),
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                # ─────────────────────────────
                # 연도별 인덕션 세대수 추이 (증감률 큰 연도 배경)
                # ─────────────────────────────
                st.markdown("#### 🔹 연도별 추정 인덕션 세대수 추이 (변동률이 큰 연도 배경 강조)")

                trend = year_agg[["연도", "추정_인덕션세대수"]].copy()
                if len(trend) >= 2:
                    trend["증감률(%)"] = trend["추정_인덕션세대수"].pct_change() * 100

                    peak_idx = trend["추정_인덕션세대수"].idxmax()
                    peak_year = int(trend.loc[peak_idx, "연도"])
                    peak_val = float(trend.loc[peak_idx, "추정_인덕션세대수"])
                    last_year = int(trend["연도"].iloc[-1])
                    last_val = float(trend["추정_인덕션세대수"].iloc[-1])
                    decline_pct = (last_val / peak_val - 1.0) * 100

                    fig_trend = go.Figure()

                    pre_mask = trend["연도"] <= peak_year
                    post_mask = trend["연도"] >= peak_year

                    fig_trend.add_trace(
                        go.Scatter(
                            x=trend.loc[pre_mask, "연도"],
                            y=trend.loc[pre_mask, "추정_인덕션세대수"],
                            mode="lines+markers",
                            name="정점 이전",
                            line=dict(color="lightgray", width=2, dash="dot"),
                            marker=dict(size=6),
                        )
                    )
                    fig_trend.add_trace(
                        go.Scatter(
                            x=trend.loc[post_mask, "연도"],
                            y=trend.loc[post_mask, "추정_인덕션세대수"],
                            mode="lines+markers",
                            name="정점 이후",
                            line=dict(color="royalblue", width=3),
                            marker=dict(size=7),
                        )
                    )

                    abs_changes = trend["증감률(%)"].dropna().abs()
                    if len(abs_changes) > 0:
                        threshold = np.percentile(abs_changes, 70)
                        for _, row in trend.iterrows():
                            year = int(row["연도"])
                            rate = row["증감률(%)"]
                            if pd.isna(rate) or abs(rate) < threshold:
                                continue
                            color = "LightSkyBlue" if rate > 0 else "MistyRose"
                            fig_trend.add_vrect(
                                x0=year - 0.5,
                                x1=year + 0.5,
                                fillcolor=color,
                                opacity=0.22,
                                layer="below",
                                line_width=0,
                            )

                    fig_trend.add_vline(x=peak_year, line_dash="dash", line_width=2)
                    fig_trend.add_vrect(
                        x0=peak_year,
                        x1=trend["연도"].iloc[-1],
                        fillcolor="LightSalmon",
                        opacity=0.12,
                        layer="below",
                        line_width=0,
                    )
                    fig_trend.add_annotation(
                        x=peak_year,
                        y=peak_val,
                        text=f"정점 {peak_year}",
                        showarrow=True,
                        arrowhead=2,
                        ax=0,
                        ay=-40,
                    )
                    fig_trend.add_annotation(
                        x=last_year,
                        y=last_val,
                        text=f"마지막 {last_year}년\n(정점 대비 {decline_pct:.1f}%)",
                        showarrow=True,
                        arrowhead=2,
                        ax=40,
                        ay=40,
                    )

                    fig_trend.update_layout(
                        title="연도별 추정 인덕션 세대수 추이\n(증감률이 큰 연도는 배경색으로 하이라이트)",
                        xaxis_title="연도",
                        yaxis_title="추정 인덕션 세대수",
                        hovermode="x unified",
                        margin=dict(l=40, r=20, t=80, b=40),
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1,
                        ),
                    )
                    st.plotly_chart(fig_trend, use_container_width=True)

                st.markdown("#### 🔹 연도별 요약표")

                tbl = year_agg.copy().set_index("연도")
                int_cols = [
                    "가스레인지수합",
                    "전체청구전수합",
                    "추정_인덕션세대수",
                ]
                float_cols = [
                    "사용량합",
                    "가스레인지당_평균사용량",
                    "전세대_가정사용량",
                    "추정_사용량감소",
                ]

                for c in int_cols:
                    tbl[c] = tbl[c].apply(lambda x: f"{int(x):,}")
                for c in float_cols:
                    tbl[c] = tbl[c].apply(lambda x: f"{x:,.1f}")
                tbl["감소율(%)"] = tbl["감소율(%)"].apply(
                    lambda x: "" if pd.isna(x) else f"{float(x):.1f}"
                )
                tbl["인덕션비중(%)"] = tbl["인덕션비중(%)"].apply(
                    lambda x: "" if pd.isna(x) else f"{float(x):.1f}"
                )
                if "가스렌지연결_청구전수합" in tbl.columns:
                    tbl["가스렌지연결_청구전수합"] = tbl["가스렌지연결_청구전수합"].apply(
                        lambda x: f"{int(x):,}"
                    )

                st.dataframe(tbl, use_container_width=True, height=380)

                st.markdown(
                    """
                    - **추정 인덕션 세대수** (v3 기준) = 총청구계량기수 − 가스렌지연결 청구계량기수  
                    - v2 파일만 있을 때는 **추정 인덕션 세대수 = 전체청구전수 − 가스레인지수** 로 계산됨  
                    - **가스레인지당 평균사용량** = 실제 사용량 ÷ 가스레인지수  
                    - **전세대 가정 사용량** = 가스레인지당 평균사용량 × 전체청구전수  
                    - **추정 사용량 감소** = 전세대 가정 사용량 − 실제 사용량  
                    - **인덕션 비중(%)** = 추정 인덕션 세대수 ÷ 전체청구전수 × 100  
                    """
                )

                # ─────────────────────────────
                # 구·군별 인덕션 사용가구 비교 (세대수/비중)
                # ─────────────────────────────
                st.markdown("---")
                st.markdown("### ②-1. 구·군별 인덕션 사용가구 비교 (세대수 및 비중)")

                year_sel_gu = st.selectbox(
                    "구·군별 인덕션 비교 대상 연도 선택",
                    options=year_agg["연도"].tolist(),
                    index=len(year_agg["연도"]) - 1,
                    key="year_sel_gu_induction",
                )

                dfu_year = dfu[dfu["연도"] == year_sel_gu]

                if dfu_year.empty:
                    st.info(f"{year_sel_gu}년에 해당하는 데이터가 없어.")
                else:
                    agg_args = {
                        "가스레인지수합": (COL_RANGE_CNT, "sum"),
                        "전체청구전수합": ("전체청구전수", "sum"),
                    }
                    if "가스렌지연결_청구전수" in dfu_year.columns:
                        agg_args["가스렌지연결_청구전수합"] = ("가스렌지연결_청구전수", "sum")

                    gu_house = (
                        dfu_year.groupby(COL_DISTRICT, as_index=False)
                        .agg(**agg_args)
                    )

                    if "가스렌지연결_청구전수합" in gu_house.columns:
                        base_induction_gu = (
                            gu_house["전체청구전수합"]
                            - gu_house["가스렌지연결_청구전수합"]
                        )
                    else:
                        base_induction_gu = (
                            gu_house["전체청구전수합"] - gu_house["가스레인지수합"]
                        )

                    gu_house["추정_인덕션세대수"] = base_induction_gu.clip(lower=0)
                    gu_house["인덕션비중(%)"] = np.where(
                        gu_house["전체청구전수합"] > 0,
                        gu_house["추정_인덕션세대수"]
                        / gu_house["전체청구전수합"]
                        * 100,
                        np.nan,
                    ).round(1)

                    gu_house_sorted = gu_house.sort_values(
                        "인덕션비중(%)", ascending=False
                    )

                    g1, g2 = st.columns([2, 1.6])

                    # 스택 바 + 비중 라인
                    with g1:
                        fig_gu_stack = go.Figure()
                        fig_gu_stack.add_trace(
                            go.Bar(
                                x=gu_house_sorted[COL_DISTRICT],
                                y=gu_house_sorted["가스레인지수합"],
                                name="가스레인지 세대",
                                opacity=0.85,
                            )
                        )
                        fig_gu_stack.add_trace(
                            go.Bar(
                                x=gu_house_sorted[COL_DISTRICT],
                                y=gu_house_sorted["추정_인덕션세대수"],
                                name="추정 인덕션 세대",
                                opacity=0.85,
                            )
                        )
                        fig_gu_stack.add_trace(
                            go.Scatter(
                                x=gu_house_sorted[COL_DISTRICT],
                                y=gu_house_sorted["인덕션비중(%)"],
                                name="인덕션 비중(%)",
                                mode="lines+markers",
                                yaxis="y2",
                            )
                        )

                        fig_gu_stack.update_layout(
                            title=f"{year_sel_gu}년 구·군별 전체세대 구성 및 인덕션 비중",
                            xaxis_title="구·군",
                            yaxis_title="세대 수",
                            yaxis2=dict(
                                title="인덕션 비중(%)",
                                overlaying="y",
                                side="right",
                                showgrid=False,
                            ),
                            barmode="stack",
                            legend=dict(
                                orientation="h",
                                yanchor="bottom",
                                y=1.02,
                                xanchor="right",
                                x=1,
                            ),
                            margin=dict(l=40, r=40, t=70, b=70),
                        )
                        st.plotly_chart(fig_gu_stack, use_container_width=True)

                    # 인덕션 비중 순위 (가로 막대)
                    with g2:
                        fig_gu_share = px.bar(
                            gu_house_sorted,
                            x="인덕션비중(%)",
                            y=COL_DISTRICT,
                            orientation="h",
                            text="인덕션비중(%)",
                            title=f"{year_sel_gu}년 구·군별 인덕션 비중(%) 순위",
                        )
                        fig_gu_share.update_layout(
                            xaxis_title="인덕션 비중(%)",
                            yaxis_title="구·군",
                            margin=dict(l=40, r=20, t=70, b=40),
                        )
                        fig_gu_share.update_traces(
                            texttemplate="%{text:.1f}%", textposition="outside"
                        )
                        st.plotly_chart(fig_gu_share, use_container_width=True)

                    # 표 (세대수 중심)
                    st.markdown("#### 구·군별 인덕션 사용가구 요약 (세대수 기준)")
                    df_show_gu = gu_house_sorted.copy()
                    df_show_gu["가스레인지수합"] = df_show_gu["가스레인지수합"].apply(
                        lambda x: f"{int(x):,}"
                    )
                    df_show_gu["전체청구전수합"] = df_show_gu["전체청구전수합"].apply(
                        lambda x: f"{int(x):,}"
                    )
                    df_show_gu["추정_인덕션세대수"] = df_show_gu["추정_인덕션세대수"].apply(
                        lambda x: f"{int(x):,}"
                    )
                    df_show_gu["인덕션비중(%)"] = df_show_gu["인덕션비중(%)"].apply(
                        lambda x: "" if pd.isna(x) else f"{float(x):.1f}"
                    )
                    if "가스렌지연결_청구전수합" in df_show_gu.columns:
                        df_show_gu["가스렌지연결_청구전수합"] = df_show_gu[
                            "가스렌지연결_청구전수합"
                        ].apply(lambda x: f"{int(x):,}")

                    st.dataframe(
                        df_show_gu.set_index(COL_DISTRICT),
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
                if "가스렌지연결_청구전수" in dfu.columns:
                    agg_dict2["가스렌지연결_청구전수합"] = ("가스렌지연결_청구전수", "sum")

                grp = (
                    dfu.groupby(["연도", COL_DISTRICT, COL_USAGE], as_index=False)
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

                grp["가스레인지당_평균사용량"] = np.where(
                    grp["가스레인지수합"] > 0,
                    grp["사용량합"] / grp["가스레인지수합"],
                    np.nan,
                )
                grp["전세대_가정사용량"] = (
                    grp["가스레인지당_평균사용량"] * grp["전체청구전수합"]
                )
                grp["추정_사용량감소"] = (
                    grp["전세대_가정사용량"] - grp["사용량합"]
                )
                grp["추정_사용량감소"] = grp["추정_사용량감소"].clip(lower=0)

                year_options = sorted(grp["연도"].unique())
                year_sel = st.selectbox(
                    "상세 분석 연도 선택",
                    options=year_options,
                    index=len(year_options) - 1,
                )

                grp_year = grp[grp["연도"] == year_sel]

                # 시군구별 합계
                gu_agg = (
                    grp_year.groupby(COL_DISTRICT, as_index=False)
                    .agg(
                        가스레인지수합=("가스레인지수합", "sum"),
                        전체청구전수합=("전체청구전수합", "sum"),
                        추정_인덕션세대수=("추정_인덕션세대수", "sum"),
                        사용량합=("사용량합", "sum"),
                        추정_사용량감소=("추정_사용량감소", "sum"),
                    )
                )
                gu_agg["감소율(%)"] = np.where(
                    gu_agg["사용량합"] > 0,
                    gu_agg["추정_사용량감소"] / gu_agg["사용량합"] * 100,
                    np.nan,
                ).round(1)

                st.markdown(f"#### 🔹 {year_sel}년 시군구별 인덕션 및 사용량 감소 추정")
                fig_gu2 = px.bar(
                    gu_agg.sort_values("추정_사용량감소", ascending=False),
                    x=COL_DISTRICT,
                    y="추정_사용량감소",
                    hover_data=[
                        "가스레인지수합",
                        "전체청구전수합",
                        "추정_인덕션세대수",
                        "사용량합",
                        "감소율(%)",
                    ],
                    title=f"{year_sel}년 시군구별 추정 사용량 감소 ({unit_label})",
                )
                fig_gu2.update_layout(
                    xaxis_title="시군구",
                    yaxis_title=f"추정 사용량 감소 ({unit_label})",
                    margin=dict(l=40, r=20, t=60, b=40),
                )
                st.plotly_chart(fig_gu2, use_container_width=True)

                st.dataframe(
                    gu_agg.set_index(COL_DISTRICT),
                    use_container_width=True,
                    height=360,
                )

                st.markdown("---")
                st.markdown(f"#### 🔹 {year_sel}년 용도별 인덕션 및 사용량 감소 추정")

                use_agg = (
                    grp_year.groupby(COL_USAGE, as_index=False)
                    .agg(
                        가스레인지수합=("가스레인지수합", "sum"),
                        전체청구전수합=("전체청구전수합", "sum"),
                        추정_인덕션세대수=("추정_인덕션세대수", "sum"),
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
                        "추정_인덕션세대수",
                        "사용량합",
                        "감소율(%)",
                    ],
                    title=f"{year_sel}년 용도별 추정 사용량 감소 ({unit_label})",
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
                st.markdown("### ③ 인덕션 비중 연도 × 시군구 히트맵 (추세 파악용)")

                heat_ind = (
                    grp.groupby(["연도", COL_DISTRICT], as_index=False)
                    .agg(
                        전체청구전수합=("전체청구전수합", "sum"),
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
