# winter_japan: 12–2 月にスペースバルーンを上げる場所を日本全国から探す

毎朝 9 時（JST）に上げると仮定し、2016–2025 年の 12–2 月 903 日について
「実施できる日」の割合を、日本の陸地 15,324 点（0.05 度間隔）で計算した。
レポートは `winter_launch_japan.pdf`（`report/main.tex`）。

## 判定

| 条件 | 定義 |
|---|---|
| 打ち上げ地点 | 陸地・標高 200 m 以下。ERA5 の積雪深（水当量）1 mm 未満 |
| 地上気象 | 9 時の 10 m 風速 5 m/s 以下、9–12 時の降水 0.5 mm 未満（ERA5。壱岐・平戸・唐津はアメダスでも） |
| 落下点 | 平野（標高 100 m 以下・傾斜 2° 以下、DID の外、雪なし）／瀬戸内海／海岸から 3 km 以内の海 |
| 飛行 | 標準（上昇 5 m/s・破裂 30 km）と短時間（8 m/s・20 km）。降下 6 m/s（海面等価） |
| 軌道 | JRA-3Q 00 UTC の風を位置ごとに双線形補間。上位 16 地点は飛行条件を 64 通り振る |

## 手順

```bash
cd research
python winter_japan/prep_wind.py      # JRA-3Q の 00 UTC を取り出す（windclim fetch --box jp 済みが前提）
python winter_japan/fetch_era5.py     # ERA5 の積雪・地上風・降水・陸海マスク
python winter_japan/fetch_amedas.py   # アメダス 芦辺・平戸・唐津の 9 時
python winter_japan/simulate.py       # 全候補の落下点（約 1 分）
python winter_japan/evaluate.py       # 全候補の確率 → results/screen_*.csv
python winter_japan/ensemble.py       # results/sites.csv の地点を 64 通りで
python winter_japan/stats.py          # 信頼区間・土日 → results/stats.json
python winter_japan/amedas_adjust.py  # アメダスで地上気象 → results/stats_amedas.json
python winter_japan/sens.py           # 判定基準の感度
python winter_japan/osm_sites.py winter_japan/results/sites.csv --out winter_japan/results/osm_sites.csv
python winter_japan/figures.py        # 図 → figures/
python winter_japan/make_tables.py    # 表 → report/tables/
cd winter_japan/report && make
```

DID と DEM は `winter_sw/data/did/`（47 都道府県）と `data/terrain/` を使う。

## 出典

JRA-3Q（気象庁、NSF NCAR GDEX d640000）、ERA5（Copernicus Climate Change Service、GDEX d633000）、
気象庁アメダス、NOAA NCEI DEM、国土数値情報 人口集中地区（2020）、© OpenStreetMap contributors。
JRA-3Q から作った図と数値は CC BY-NC-SA 4.0（非商用）。
