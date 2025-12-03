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

                # 지오 설정
                fig_map.update_geos(
                    fitbounds="locations",
                    visible=False,
                )

                # ★ 경계선(라인) 설정만 적용 – opacity 건드리지 않음 ★
                fig_map.update_traces(
                    selector=dict(type="choropleth"),
                    marker=dict(
                        line=dict(
                            width=1.2,
                            color="white",
                        )
                    ),
                )

                fig_map.update_layout(
                    margin=dict(l=0, r=0, t=40, b=0),
                    coloraxis_colorbar=dict(title="감소량"),
                    title=f"{base_year}년 → {comp_year}년 대구시 구·군 + 경산시 시군구별 가스레인지 감소량",
                )

                st.plotly_chart(fig_map, use_container_width=True)
