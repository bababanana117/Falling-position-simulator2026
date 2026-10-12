#!/usr/bin/env bash
# 記事に貼る図を集める。
#
# research/out/ は out/csv/ を除いて git 管理外なので、図はローカルにしか無い。
# 記事と一緒に持ち歩けるよう blog/images/ にコピーする。
# 出典とライセンスは各記事の末尾に書いてある（CC BY-NC-SA 4.0）。
set -euo pipefail
cd "$(dirname "$0")/.."

A1=blog/images/balloon-wind-1-forecast-limit
A2=blog/images/balloon-wind-2-building-climatology
A3=blog/images/balloon-wind-3-duckdb-distribution
mkdir -p "$A1" "$A2" "$A3"

copy() { cp -f "$1" "$2"; printf '  %s\n' "${2#blog/}"; }

echo "第 1 回"
copy research/out/figures/wakayama/A2_landing_clouds.png "$A1/landing-scatter-models.png"
# 上端の図タイトルは記事のキャプションと重複するので落とす。
python - "$A1/landing-scatter-models.png" <<'PY'
import sys
from PIL import Image
path = sys.argv[1]
im = Image.open(path)
w, h = im.size
im.crop((0, int(h * 0.075), w, h)).save(path)
PY

# 高度×時期のヒートマップ・定常度の年変化・1 月の面図は、スライド版だと
# ブログ幅で文字が重なるので make_figures.py で描き直している。
echo "第 2 回"
copy slide/figures/S_roses_10hpa.png       "$A2/roses-10hpa.png"

echo "第 3 回"
D=research/hokkaido_duckdb/docs/_figures
copy "$D/fitted_pdf.png"       "$A3/fitted-pdf.png"
copy "$D/ambiguity.png"        "$A3/ambiguity.png"
copy "$D/effective_sample.png" "$A3/effective-sample.png"
copy "$D/seasonal_heatmap.png" "$A3/seasonal-heatmap.png"

echo "できました"
