# blog

Zenn に載せる記事。このディレクトリが Zenn のルートです。

```bash
cd blog
npx zenn-cli@latest preview      # http://localhost:8000
```

## 記事

| slug | 題 |
|---|---|
| `balloon-wind-1-forecast-limit` | 落下予測は 7 日先で止まる |
| `balloon-wind-2-building-climatology` | 再解析 10 年ぶんから統計風を作る |
| `balloon-wind-3-duckdb-distribution` | DuckDB で配る、そして使う |

3 本とも `published: false` です。公開するときに切り替えてください。

## 検査

公開前にこれを通してください。frontmatter・画像パス・リンク・強調の記法を見ます。

```bash
python check.py
```

とくに 2 つの落とし穴を拾います。どちらも Markdown としては正しいので、
Zenn も何も言いません。

- **画像パスが `../images/...` 以外**。記事は `../images/<slug>/xxx.png` の形に揃える
- **強調が閉じない**。`…します。**次の文` のように、閉じる `**` の直前が
  約物で直後が文字だと、CommonMark の規則でその `**` は閉じ記号と認められず、
  記号がそのまま出る。約物を `**` の外に出せば直る

## 図

図は 3 種類あります。

**データの図（ブログ用に描いたもの）** — `research/out/csv/` の CSV と配布用の
DuckDB から直接描きます。スライドの図はプレゼン用に文字が大きく、ブログの幅では
ラベルが重なるので、こちらで描き直しています。

```bash
python make_figures.py                    # 19 枚すべて
python make_figures.py --only jet-cycle
```

**概念図** — 説明のための絵。データではありません。

```bash
python make_diagrams.py                   # 6 枚すべて
python make_diagrams.py --only flight-stages
```

**そのまま借りてきた図** — スライドと研究側から持ってきたもの。いまは
風配図・落下点の散らばり・DuckDB の手引の図だけです。`research/out/` は
`out/csv/` を除いて git 管理外なので、記事と一緒に持ち歩けるようコピーします。

```bash
./copy_figures.sh
```

配色は 3 つとも揃えてあります（青 `#0072B2` / 朱 `#D55E00` / 灰 `#9CA3AF`、
白背景）。領域を並べる図は北海道 = 青、和歌山 = 朱、愛媛 = 青緑 `#009E73` で、
季節の 4 色とあわせて色覚特性の検査を通したものを使っています。

`ainan-landing` だけは `research/out/netcdf/` の愛媛の NetCDF を読みます
（落下点の共分散が CSV に無いため）。先に research 側で
`python -m windclim.cli all --region ehime` を済ませておいてください。

## 数字の出どころ

記事の数字は、research 側の**半月ビン版**の出力（`research/out/csv/` と
`research/out/netcdf/`）から取っています。`research/README.md` には古い週ビン版の
数字が残っているので、そちらを引かないでください。食い違うのは次の 3 つです。

| 項目 | 週ビン版（古い） | **半月ビン版（記事で使う）** |
|---|---|---|
| 1 日ずれの移動 | 30--50 km | **43--63 km**（北海道） |
| 軌道の本数 | 1,051,992（和歌山のみ） | **8,328,270**（北海道） |
| 有効標本数 | 生の 17 % | 生の **13 %**（中央値 77.2） |

200 hPa の季節平均（北海道）は **40.2 / 35.0 / 29.9 / 44.5 m/s**（冬春夏秋）。
23.8 km より上の寄与（7 月）は北海道 53.5 %、和歌山 110.8 %、愛媛 139.5 %。

比較のために出てくる和歌山と愛媛（愛南町）は、北海道と同じ手順で作った
統計です。配布予定なのは北海道の分だけです。

## ライセンス

図は JRA-3Q 再解析の派生物なので **CC BY-NC-SA 4.0**（表示・非商用・継承）です。
本文とコードは別。各記事の末尾に表示と引用を入れてあります。
詳しくは `research/LICENSE-DATA.md`。
