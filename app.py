# ─────────────────────────────────────
# ② 군구별 감소량 지도 (대구 전 구·군 + 경산시)
# ─────────────────────────────────────
with tab2:
    st.subheader("② 기준연도 대비 군구별 가스레인지 감소량 지도 (대구 + 경산)")

    # usage / product 필터 적용 + 대구+경산 시군구만 사용
    df_map = df_raw.copy()
    df_map = df_map[df_map[COL_USAGE].isin(usage_sel)]
    df_map = df_map[df_map[COL_PRODUCT].isin(product_sel)]
    df_map = df_map[df_map[COL_DISTRICT].isin(TARGET_SIGUNGU)]

    # ── GeoJSON에 공통 키(geo_key) 추가 ──
    if geojson is not None:
        for feat in geojson["features"]:
            # GeoJSON 쪽 시군구 이름 정리
            name = str(feat["properties"].get("시군구", "")).strip()
            # 공백 제거해서 통일
            name_clean = name.replace(" ", "")
            feat["properties"]["geo_key"] = name_clean

        # 데이터프레임 쪽도 같은 규칙으로 정리
        df_map["geo_key"] = (
            df_map[COL_DISTRICT]
            .astype(str)
            .str.strip()
            .str.replace(" ", "", regex=False)
        )
    else:
        df_map["geo_key"] = df_map[COL_DISTRICT]

    # 기준연도 / 비교연도만 사용
    map_df = df_map[df_map["연도"].isin([base_year, comp_year])]

    if map_df.empty:
        st.info("현재 필터 조건에 해당하는 대구+경산 시군구 데이터가 없어.")
    else:
        grouped = (
            map_df.groupby(["연도", COL_DISTRICT, "geo_key"], as_index=False)[COL_RANGE_CNT]
            .sum()
        )

        pivot_map = (
            grouped
            .pivot(index=[COL_DISTRICT, "geo_key"], columns="연도", values=COL_RANGE_CNT)
            .reindex(index=pd.MultiIndex.from_product(
                [TARGET_SIGUNGU,
                 sorted(grouped["geo_key"].unique())],
                names=[COL_DISTRICT, "geo_key"]
            ))
        )

        # index 를 다시 정리 (시군구, geo_key 둘 다 컬럼으로)
        pivot_map = pivot_map.reset_index()

        # 기준/비교 연도가 없으면 0으로 채움
        if base_year not in pivot_map.columns:
            pivot_map[base_year] = 0
        if comp_year not in pivot_map.columns:
            pivot_map[comp_year] = 0

        # 대구+경산 9개만 남기도록 필터
        pivot_map = pivot_map[pivot_map[COL_DISTRICT].isin(TARGET_SIGUNGU)]

        # 감소량, 감소율 계산
        pivot_map["감소량(기준-비교)"] = pivot_map[base_year] - pivot_map[comp_year]
        pivot_map["감소율(%)"] = np.where(
            pivot_map[base_year] > 0,
            pivot_map["감소량(기준-비교)"] / pivot_map[base_year] * 100,
            np.nan,
        )
        pivot_map["감소율(%)"] = pivot_map["감소율(%)"].round(1)

        map_table = pivot_map.rename(
            columns={
                COL_DISTRICT: "시군구",
                base_year: f"{base_year}년 가스레인지 수(연간합계)",
                comp_year: f"{comp_year}년 가스레인지 수(연간합계)",
            }
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

        # 지도
        with c2:
            if geojson is None:
                st.warning(
                    f"대구+경산 GeoJSON({GEO_PATH})을 찾을 수 없어서 지도를 그릴 수 없어.  "
                    "daegu_gyeongsan_sgg.geojson 파일이 data 폴더에 있는지 확인해줘."
                )
            else:
                # 색상 스케일을 대칭으로 맞추기
                vmax = map_table["감소량(기준-비교)"].abs().max()
                vmax = max(vmax, 1)
                vmax = np.ceil(vmax / 50000) * 50000
                vmax_abs = float(vmax)

                # 디버그용: GeoJSON 시군구 목록과 feature 개수 보여주기
                geo_names = sorted({
                    str(f["properties"].get("시군구", "")).strip()
                    for f in geojson["features"]
                })
                st.caption(
                    f"GeoJSON feature 개수: {len(geojson['features'])}, "
                    f"시군구 목록: {', '.join(geo_names)}"
                )

                fig_map = px.choropleth(
                    map_table,
                    geojson=geojson,
                    locations="geo_key",                 # 공통 키
                    featureidkey="properties.geo_key",   # GeoJSON 쪽 공통 키
                    color="감소량(기준-비교)",
                    color_continuous_scale="RdBu_r",
                    range_color=[-vmax_abs, vmax_abs],
                    hover_name="시군구",
                    hover_data={
                        f"{base_year}년 가스레인지 수(연간합계)": ":,",
                        f"{comp_year}년 가스레인지 수(연간합계)": ":,",
                        "감소량(기준-비교)": ":,",
                        "감소율(%)": True,
                    },
                    title=f"{base_year}년 → {comp_year}년 대구시 구·군 + 경산시 시군구별 가스레인지 감소량",
                )
                fig_map.update_geos(fitbounds="locations", visible=False)
                fig_map.update_layout(
                    margin=dict(l=0, r=0, t=40, b=0),
                    coloraxis_colorbar=dict(title="감소량"),
                )
                st.plotly_chart(fig_map, use_container_width=True)

        st.markdown(
            """
            - **감소량(기준-비교)** : 기준연도 연간 가스레인지 수 − 비교연도 연간 가스레인지 수  
            - **감소율(%)** : 감소량 ÷ 기준연도 연간 가스레인지 수 × 100  
            - 시군구 선택 필터와 무관하게, 대구 8개 구·군 + 경산시만 지도/표에 표시됨.
            """
        )
