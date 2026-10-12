# alpha: ERA5 の 1 時間値で時間帯の違いを見る

本文の統計（JRA-3Q、6 時間ごと）は、打ち上げの時間帯を区別していません。
その扱いでよいかを、1 時間ごとの ERA5 で 1 か月ぶん確かめる試験的な解析です。
結果はレポートの付録「ERA5 の 1 時間値で見た時間帯の違い」にまとめています。

## 手順

```bash
cd research
python alpha/fetch_era5.py --month 2025-07     # 約 30 分、約 380 MB
python alpha/diurnal.py    --month 2025-07     # 1 分ほど
```

- 取得元は NSF NCAR GDEX の ERA5（データセット `d633000`、0.25 度、37 気圧面）。
  OPeNDAP で北海道領域（北緯 40.0〜46.5 度、東経 138.0〜149.0 度）だけを切り出します。
  本文の JRA-3Q と同じ箱です。
- 取得したファイルは `alpha/data/` に 1 変数・1 日ずつ置きます（git の管理外）。
  途中で止めても、再実行すれば取っていない日だけを取ります。
- 図は `out/figures/alpha/`、数字は `alpha/results/` に出ます。

## 時間帯の切り方

日本時間で 6 時間ずつに分けます。

| 時間帯 | 日本時間 |
|---|---|
| 朝 | 05–10 時 |
| 昼 | 11–16 時 |
| 夕 | 17–22 時 |
| 晩 | 23–04 時 |

日々の天気の違いを取り除くため、各日（日本時間の 0–23 時）の平均からの偏差で
比べます。信頼区間は、日を 1 つの標本として計算しています（同じ日の 6 時間は
独立ではないため）。

## ライセンス

ERA5 は Copernicus Climate Change Service の製品です。図には
「Contains modified Copernicus Climate Change Service information 2025」の表示が要ります。
