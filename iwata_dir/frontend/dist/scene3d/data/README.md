# 3D表示の高度基準：EGM96

`WW15MGH.DAC` は、3D表示でモデルのASL高度をWGS84楕円体高へ換算するための、全球15分格子のジオイド高データである。DEM、Googleの地形データ、予測誤差のモデルではない。追加API、APIキー、外部ランタイムは必要ない。

## 表示の規約と境界

`parseEgm96(buffer).heightOffset(lonDeg, latDeg)` は、WGS84楕円体からEGM96ジオイドまでの高さ `N` をメートルで返す。表示用の座標だけを次式で作る。

```text
h_ellipsoid = z_model_ASL + N_EGM96(longitude, latitude)
```

`N > 0` はジオイドが楕円体より上にあることを意味する。例えば格子点43°N, 141.5°Eでは `N = +31.33 m`、モデルASL高度30,000 mの表示用楕円体高は30,031.33 mとなる。負の `N` も符号のまま加える。[Cesiumの高度定義](https://cesium.com/learn/cesiumjs/ref-doc/Cartesian3.html#fromDegrees)、[ジオイド高の符号](https://cesium.com/learn/cesium-native/ref-doc/classCesiumGeospatial_1_1EarthGravitationalModel1996Grid.html)を参照。

現在の飛行核の `z_model_ASL` は球面近似に基づく幾何ASL高度であり、測量で得た厳密な正標高ではない。この換算は、その既存値を**表示時にEGM96基準の高さとして扱う規約**である。気象場の鉛直再構成や科学的な高度精度を改訂・保証するものではない。[理論ガイド編集元](../../../docs/THEORY_GUIDE.tex)のASL・ジオポテンシャル高度の区別を維持し、ここでジオポテンシャル高度への変換をもう一度行わない。

- 飛行結果、入力、CSV/GeoJSON、KMLへ保存した元のASL高度を変更しない。KMLのabsolute高度はEGM96基準という[OGC KML仕様](https://docs.ogc.org/is/12-007r2/12-007r2.html)との接続を目的とする。
- Cesiumが描画済みメッシュから返した地表の高さは既に楕円体基準である。地表投影や人工AGLの上端を求める地物高に `N` を二重加算しない。
- 地形・建物との数メートル単位の離隔、着地衝突判定、科学的な高度精度の根拠にはしない。気象モデル地表と写真3Dの地表が一致することも保証しない。
- 読込みや検証に失敗したら、この換算を使う立体軌道表示を失敗として扱う。`N=0` への黙った代替や別ジオイドへの自動切替はしない。

## 固定データと取得元

取得確認日：2026-10-02。実行時に外部配布元へ問い合わせず、同梱ファイルを一度読み込んで再利用する。

| 項目 | 値 |
| --- | --- |
| 同梱ファイル | `WW15MGH.DAC` |
| 内容 | NGA EGM96、全球15分格子、ジオイド高 |
| バイト数 | 2,076,480（約1.98 MiB） |
| SHA-256 | `9dcaf4efd6857aaa2e1e2e2c574d3f5264eacf47024cdcd5291c40ddad5e5acc` |
| 配布物を取得した固定commit | CesiumGS/cesium-native `1bca8021711294cc83a5a032599ac72d9b3166c9` |
| Git blob | `894449e1a32e39311a44094ab7a8eaef2e52ea71` |
| 行 | 721行、90°Nから90°Sへ0.25°ずつ |
| 列 | 1440列、0°Eから359.75°Eへ0.25°ずつ |
| 値 | ヘッダーなし、行優先、符号付き16 bit、big-endian、単位cm |

[同梱DACの取得URL（固定commit）](https://raw.githubusercontent.com/CesiumGS/cesium-native/1bca8021711294cc83a5a032599ac72d9b3166c9/data/WW15MGH.DAC)。データの原配布元は[NGA EGM96 15 Minute Interpolation Grid](https://earth-info.nga.mil/php/download.php?file=egm-96interpolation)。今回取得したNGA ZIPは2,870,765 bytes、SHA-256 `f051316cdf794a87e8291bcb7aee82d0e49a99c35301b6b82462fbe5078b7216`。このZIP内の旧実行ファイルは実行も同梱もしていない。

NGAの `WW15MGH.GRD` は721×1441点のミリメートル表記で、最終列360°Eは先頭列0°Eと全行同じだった。重複列を除く全1,038,240点をDACと照合し、絶対差の最大値は **0.006 m** だった。テキスト値を単純にcmへ丸めた配列とのbyte一致は成立しなかったため、同一bytesとは扱わない。上記SHAのDACを変更せず同梱する。これらは格子の来歴・量子化の確認であり、実地の高さに対する誤差上限ではない。

## 利用条件・帰属

データ原作者：US National Geospatial-Intelligence Agency（NGA）、EGM96。NGA由来のEGM96全球15分格子の利用条件は、[PROJ-data公式のNGAデータ説明](https://raw.githubusercontent.com/OSGeo/PROJ-data/master/us_nga/us_nga_README.txt)で **Public Domain** と明記されている。取得時の同説明のSHA-256は `73bf524a13a3b38b27ab3f1748128445aed1d247ab87e4312b84fa58a085ac12`。データへCesiumのソフトウェアライセンスを取り違えて適用しない。

形式の確認と検査座標の参考はCesiumGS/cesium-nativeの[実装](https://github.com/CesiumGS/cesium-native/blob/1bca8021711294cc83a5a032599ac72d9b3166c9/CesiumGeospatial/src/EarthGravitationalModel1996Grid.cpp)と[公式テスト](https://github.com/CesiumGS/cesium-native/blob/1bca8021711294cc83a5a032599ac72d9b3166c9/CesiumGeospatial/test/TestEarthGravitationalModel1996Grid.cpp)。同ソフトウェアは[Apache License 2.0](https://github.com/CesiumGS/cesium-native/blob/1bca8021711294cc83a5a032599ac72d9b3166c9/LICENSE)、帰属はCesiumGS / Cesium Native contributors。ライセンス本文は既存の[THIRD_PARTY_NOTICES.txt](../THIRD_PARTY_NOTICES.txt)にも収録されている。本実装はこの形式と双一次補間式から書いた独立したJavaScriptで、C++コードの移植ではない。参考テストから選んだ座標・数値については、同テストにUNAVCOの計算器由来との記述があることを明示し、今回UNAVCOへ照会した結果とは扱わない。

## 補間と入力契約

実装：[vertical-datum.js](../src/vertical-datum.js)。4つの隣接格子値を双一次補間し、cmからmへ換算する。球面調和展開や補間依存の大型ライブラリは追加しない。

`parseEgm96` は **ArrayBufferかつ正確なバイト数** を要求し、南北極の各行が経度によらず同じ値であることを検査する。末尾追加・途中切断・不整合の極行は拒否する。内部にbytesを複写し、呼出し側のbufferの変更が読み込んだ表示基準を変えないようにする。任意の正しいサイズのファイルの出自まで判定するAPIではなく、同梱データの同一性は上記SHAと試験で固定する。

`heightOffset(lonDeg, latDeg)` は有限の数値のみ受け付け、緯度は閉区間[-90,90]外を拒否する。経度は360°周期で正規化し、負経度と0〜360°表現の双方を扱う。359.75°の東隣は**同じ緯度行の0°**であり、配列上の次行へは進まない。±180°は同じ位置、南北極は経度によらず同じ値となる。

双一次補間の高さは連続だが、その勾配は格子境界で滑らかとは限らない。15分解像度・cm量子化のEGM96モデルは細かな地形の代替にならない。EGM2008や日本の地域ジオイドへ変更すると高度規約自体が変わるため、データだけを交換して精度向上とみなさない。

## 確認方法

[scene3d-datum.test.ts](../../src/scene3d-datum.test.ts)を既存Vitestで実行する。外部通信は不要。

- 配布物のバイト数・SHA、NGA原GRDの符号の異なる格子点、日本の地点、南北極を照合する。
- Cesium公式テストが保存しているUNAVCO由来の格子間参照値と0.01 m以内で照合する。この許容値は参照値の再現確認であり、実地の精度保証ではない。
- 合成した非対称格子で、0/360°付近の隣接行への誤参照を検出する。実格子で日付変更線、周期、極への接近、正負の補正を検査する。
- 不正座標、不正サイズ、不正な極行、呼出し後の入力bytesの変更を検査する。

立体軌道・地表投影・カーテンの描画、既存GUIとの往復、写真3D上の見え方は呼出し側の検証範囲であり、この変換器の単体試験だけで完了とはしない。
