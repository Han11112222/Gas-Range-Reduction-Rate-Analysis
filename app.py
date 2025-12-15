import streamlit as st
import geopandas as gpd
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import os
import numpy as np
import pandas as pd

# 1. 페이지 설정
st.set_page_config(page_title="대구 히트맵(Fix)", layout="wide")
st.title("🔥 대구광역시 가스 사용량 히트맵 (깜빡임 해결)")
st.caption("Session State를 사용하여 데이터가 계속 바뀌는 현상을 막았습니다.")

# 2. 데이터 로드 (지도 모양)
@st.cache_data
def load_data_heatmap():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shp_path = os.path.join(current_dir, '..', '지도', '국가기본도_시군구구역경계', 'TN_SIGNGU_BNDRY.shp')
    
    if not os.path.exists(shp_path): return None
    
    gdf = gpd.read_file(shp_path, encoding='cp949')
    daegu_gdf = gdf[gdf['LEGLCD_SE'].str.startswith('27')].copy()
    daegu_gdf = daegu_gdf.dissolve(by='ADZONE_NM', as_index=False).reset_index(drop=True)
    
    if daegu_gdf.crs is None: daegu_gdf.set_crs("EPSG:5179", inplace=True)
    daegu_gdf = daegu_gdf.to_crs(epsg=4326)
    
    return daegu_gdf

# 3. 가상의 점(Point) 데이터 생성 함수
def generate_random_points(gdf, total_points=1000):
    points = []
    
    for _, row in gdf.iterrows():
        center = row.geometry.centroid
        n_points = np.random.randint(50, 200)
        
        # NumPy 배열 생성
        latitudes = np.random.normal(center.y, 0.03, n_points)
        longitudes = np.random.normal(center.x, 0.03, n_points)
        weights = np.random.randint(1, 10, n_points)
        
        for lat, lon, w in zip(latitudes, longitudes, weights):
            # JSON 에러 방지용 형변환
            points.append([float(lat), float(lon), int(w)])
            
    return points

daegu_gdf = load_data_heatmap()

if daegu_gdf is None: 
    st.error("데이터 파일을 찾을 수 없습니다.")
    st.stop()

# -----------------------------------------------------------------------------
# [핵심 수정] Session State를 이용한 데이터 고정
# -----------------------------------------------------------------------------
# 'heat_data'라는 이름의 데이터가 임시 저장소에 없으면 -> 새로 만들고 저장
if 'heat_data' not in st.session_state:
    st.session_state['heat_data'] = generate_random_points(daegu_gdf)

# 버튼을 누르면 강제로 데이터를 다시 뽑기 (새로고침 기능)
if st.button("🎲 데이터 랜덤 재생성"):
    st.session_state['heat_data'] = generate_random_points(daegu_gdf)
    st.rerun() # 화면 즉시 새로고침

# 이제 변수에 저장된 데이터를 가져와서 씁니다. (새로 생성 X)
heat_data = st.session_state['heat_data']
# -----------------------------------------------------------------------------

st.sidebar.header("🔥 히트맵 설정")
st.sidebar.write(f"현재 포인트 개수: {len(heat_data)}개")
# 이제 슬라이더를 움직여도 데이터(heat_data)는 그대로라 안 깜빡임!
radius = st.sidebar.slider("반경 (Radius)", 10, 50, 25)
blur = st.sidebar.slider("번짐 (Blur)", 10, 50, 15)

# 지도 생성
m = folium.Map(location=[35.8714, 128.6014], zoom_start=11, tiles='CartoDB dark_matter')

HeatMap(
    heat_data,
    radius=radius,
    blur=blur,
    min_opacity=0.4,
    gradient={0.4: 'blue', 0.65: 'lime', 1: 'red'}
).add_to(m)

# returned_objects=[] : 지도에서 마우스 클릭 같은 정보를 안 받겠다는 뜻
# 이걸 넣으면 지도가 불필요하게 리로드 되는 걸 더 확실히 막아줌
st_folium(m, use_container_width=True, returned_objects=[])
