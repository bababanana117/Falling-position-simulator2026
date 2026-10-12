# 発表スライド「JRA-3Qを用いた高層風の統計的傾向の解析」

`research/` の解析結果から作る 16:9 の発表用 PDF（LuaLaTeX + Beamer）。
主結果は北海道、和歌山は比較用。

## ビルド

```bash
cd slide
make            # figures → latexmk → check（preview/pNN.png を書き出す）
make figures    # 図だけ描き直す（../research/out の CSV / NetCDF から）
make check      # PDF を 1 枚ずつ PNG にして、はみ出し・欠落グリフ・未定義引用を検査
```

必要なもの：TeX Live 2024（lualatex, beamer, luatexja, fontawesome5, tcolorbox）、
conda 環境 `jra3q`（matplotlib, pymupdf, xarray, pandas）。フォントは TeX Live 同梱の
HaranoAji Gothic と Fira Sans をファイル名で読むので、追加インストールは不要。

## 構成

| ファイル | 役割 |
|---|---|
| `main.tex` | 文書本体。`slides/*.tex` を順に `\input` |
| `beamerthemewindclim.sty` | テーマ。フォント、配色、見出し（左の縦棒＋右上の小見出し）、カード・大数字・フロー図・引用のマクロ |
| `slides/NN_*.tex` | 1 枚 1 ファイル |
| `refs.tex` | `\defref{Key+YY}{書誌}`。本文の `\src{Key+YY}` が灰色小字の `(Key+YY)` になり、参考文献ページには引用したものだけ並ぶ |
| `make_figures.py` | スライド用の図。レポートの図関数をスライドの配色・文字サイズで再描画するか、1 パネルに描き直す |
| `check.py` | `preview/` を生成し、log の Overfull・Missing character・未定義引用、PDF 上のページ外テキスト・フッタ侵入・フォールバックフォントを報告 |
| `design-guidelines.md` | 事前調査したスライド設計の規則（出典付き）と、この deck で採用した設計値 |
| `references.md` | 引用キーと完全な書誌 |
| `title-slide-background.png` | タイトルページの背景 |

## 設計値

- 見出し：HaranoAji Gothic Heavy 17 pt、1 文の主張、最大 2 行。左に青の縦棒、右上に小見出し（章）
- 本文 12 pt、補足 10.5 pt、出典・引用 9 pt（`#6B7280`）
- 色：文字 `#1A1A1A`、青 `#0072B2`（北海道・強調）、朱 `#D55E00`（和歌山・警告）、淡青 `#E3EEF8`
- 図は `make_figures.py` の `FS` で inch サイズを縮めてあり、スライド上で文字が 8.5 pt 以上になる

## 数値の出どころ

数値はすべて `research/report/` の本文と `research/out/csv/` から。
200 hPa の季節平均風速は半月ビン製品（`jra3q_windclim_hokkaido_2016-2025_v1.nc`）を
`summarise()` にかけた値（冬 40.2、春 35.0、夏 29.9、秋 44.5 m/s）。
レポート第 4 章の 40.3 / 29.8 は週ビン製品の値で、そちらが古い。
