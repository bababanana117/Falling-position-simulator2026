# winter_sw: 1・2 月に西日本で「雪のない平野」に落とせる場所

関東より西・南で、1・2 月に

- 打ち上げ場所に雪がなく、
- 落下点が平野（標高 100 m 以下・傾斜 2° 以下）で、人口集中地区（DID）の外で、雪がない

打ち上げ場所を探す。海上回収は考えない（海に落ちたら失敗）。
結果はレポートの付録「1・2 月に西日本で『雪のない平野』に落とせる場所」にある。

## 手順

```bash
cd research
python -m windclim.cli fetch --box sw --months 1,2   # JRA-3Q、約 20 分、0.6 GB
python winter_sw/fetch_snow.py                       # ERA5 の積雪深、20 か月分
python winter_sw/fetch_did.py                        # 国土数値情報の DID、43 都府県
python winter_sw/analyze.py                          # 1 分ほど
python winter_sw/analyze.py --allow-seto             # 瀬戸内海への着水も成功に数える
```

`--allow-seto` の結果は `out/figures/winter_sw_seto/` と `winter_sw/results/seto/` に出る。
瀬戸内海は、関門海峡・豊予海峡（関崎〜佐田岬）・鳴門海峡・紀淡海峡の内側とし、
紀伊水道と豊後水道は含めない（`analyze.py` の `SETO_POLYGON`）。

- 地形（NOAA NCEI の DEM）は `analyze.py` が初回に取得して `data/terrain/` に置く。
- 取得したデータは `winter_sw/data/` と `data/raw/`（git の管理外）。
- 図は `out/figures/winter_sw/`、数値は `winter_sw/results/`。

## 判定

| 項目 | 定義 |
|---|---|
| 風 | JRA-3Q、2016–2025 年の 1・2 月、6 時間ごと（2360 回） |
| 落下点 | 本文と同じ閉形式。風は打ち上げ時刻・地点で固定 |
| 平野 | DEM（約 500 m 間隔）で標高 100 m 以下・傾斜 2° 以下の陸地 |
| 市街地 | 人口集中地区（2020 年） |
| 雪 | ERA5 の積雪深（水当量）1 mm 以上。その日の 12 時 JST |
| 飛行条件 | 上昇 5 / 8 m/s と破裂 20 / 25 / 30 km の 5 通り。降下は 6 m/s |

## 出典

- 風: JRA-3Q（気象庁、NSF NCAR GDEX d640000）
- 積雪: ERA5（Copernicus Climate Change Service の情報を加工したものを含む）
- 地形: NOAA NCEI DEM mosaic
- 市街地: 国土交通省 国土数値情報（人口集中地区データ）
