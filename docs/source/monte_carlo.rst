モンテカルロ・統計分析
========================

概要
----

「モンテカルロ設定」パネル(``frontend/src/components/mc/MonteCarloPanel.tsx``)
から、上昇速度・破裂高度・降下速度を確率的にばらつかせた多数のTawhiri
予測を実行し、着地点の散らばりを可視化する機能である。予報窓を超えた
日時では、統計モード(:doc:`climatology`)に切り替わり、風そのものの
統計的な散らばりから着地点を求める。

.. important::

   予報窓内のモンテカルロは、サーバー側で風の不確実性まで含めて
   モンテカルロを回しているわけではない。ブラウザ側で上昇速度・
   破裂高度・降下速度だけを乱数で動かし、Tawhiriへ個別にリクエストを
   送って結果を集計している。したがって、各標本はTawhiri側では同じ
   GFS風データを参照している(:doc:`known_issues` 参照)。

実行の流れ (``useMonteCarlo``)
------------------------------------

``frontend/src/mc/useMonteCarlo.ts`` の ``run()`` が次の手順で実行する。

1. 摂動なしの中心値でTawhiriに1回リクエストし、中心予測(``mcCentral``)
   として保存する
2. 指定したサンプル数(最大500、``MC_MAX_SAMPLES``)を、CPUコア数に応じた
   個数(最大4)のWeb Worker(``frontend/src/mc/mcWorker.ts``)に分配する
3. 各Workerは割り当てられたサンプルについて、``perturbationForIndex()``
   (``frontend/src/mc/sampling.ts``)で決定的な乱数(シード+サンプル
   番号から生成するPRNG、``mulberry32``)を使い、パラメータを摂動した
   うえでTawhiriにリクエストする。Worker内でもセマフォで同時実行数を
   制限する
4. 全Workerの結果が集まったら、着地点の統計(信頼楕円等)と安全判定を
   行う(``finishStatsAndSafety()``)

摂動モデル (``perturbationForIndex``)
--------------------------------------------

.. list-table::
   :header-rows: 1

   * - モデル
     - 対象パラメータ
     - 分布
   * - 正規分布 (既定)
     - 上昇速度・破裂高度・降下速度
     - それぞれ指定したσ(破裂高度はσを中心値への割合[%]で指定)の
       正規分布
   * - Weibull
     - 破裂高度のみ(上昇速度・降下速度は固定)
     - 形状パラメータ3.0固定、尺度パラメータは指定した破裂高度

着地点の統計と信頼楕円
--------------------------

``frontend/src/stats/landing.ts`` の ``computeLandingStats()`` が、
着地点群を平均を原点とした局所ENU平面(メートル単位)に投影し、2x2共分散
行列を固有分解して次を求める。

- 平均着地点
- 50% / 90% / 95%の信頼楕円(2自由度のカイ二乗分布から半径係数を求める)
- 平均からの距離の50 / 90 / 95パーセンタイル半径

信頼楕円は地図上にポリゴンとして描画される
(``frontend/src/components/map/EllipseLayer.tsx``)。着地点が多い場合は
ヒートマップ表示(``HeatmapLayer.tsx``、leaflet.heat)も使える。

安全判定
--------

``frontend/src/safety/landingSafety.ts`` の ``classify()`` が、各着地点を
次の優先順で分類する。

1. 海(``frontend/public/geo/land.json``、Natural Earth 50m陸地ポリゴンに
   対するpoint-in-polygon判定。陸地でなければ「海」)
2. 制限区域(空港・自衛隊基地等、``geo/restricted.json``)
3. 住宅街(``geo/towns.json`` の市街地に近接)
4. 標高不明(Open-Meteo Elevation APIから標高が取得できなかった場合)
5. 山地(標高が閾値、既定500m以上)
6. 安全

標高が取得できなかった点は「安全」ではなく「標高不明」として数える。
これは、標高APIのレート制限(429)で取得に失敗した点を安全着地率に
含めてしまうバグを修正した結果である(:doc:`known_issues` の
Open-Meteoに関する項目も参照)。

グラフ
------

「グラフ」パネル(``ChartsPanel.tsx``)は、結果がある場合にPlotly.jsの
グラフを遅延ロードして表示する。

- **高度プロファイル** (``AltitudeProfile.tsx``): 単発予測・時系列予測の
  各時刻・モンテカルロの各標本(最大30本に間引き)・中心予測を、時刻
  (横軸)と高度(縦軸)の折れ線として重ねて描画する
- **着地分布** (``LandingScatter.tsx``、標本5件以上で表示): 着地点の
  散布図とマージナルヒストグラムを表示する。マーカーの色は各標本の
  破裂高度(``perturbed.burstAltitude``)で塗り分ける
- **距離ヒストグラム** (``DistanceHistogram.tsx``、標本5件以上で表示):
  中心(または平均)着地点までの距離の分布

関連機能: 発射条件最適化
----------------------------

「最適化」パネル(``frontend/src/components/optimizer/OptimizerPanel.tsx``)
は、発射地点(複数選択可)×破裂高度(ガス量スイープ、
:doc:`ascent_calculator` の計算を内部で使う)×発射時刻のグリッドサーチ
である(``frontend/src/optimizer/gridSearch.ts``)。目的関数
(``objectives.ts``)は次の3種類から選べる。

- ``avoidSea``: 海に着水したら大きなペナルティ、陸なら発射地点からの距離
- ``minDistance``: 指定した回収目標地点までの距離(+海ペナルティ)
- ``safeLanding``: 着地安全判定のカテゴリ(海・住宅街・制限区域・山地・
  標高不明)ごとのペナルティ+発射地点からの距離

全セルのTawhiriリクエストは300コールごとのバッチに分け、バッチ間に3秒の
休止を挟むことで、何セルでも実行できるようにしている
(``OPTIMIZER_BATCH_SIZE`` / ``OPTIMIZER_BATCH_PAUSE_MS``)。
``safeLanding`` 目的関数のときは、全セルの飛行が終わった後にまとめて
着地点の標高を取得してから採点する。

関連機能: 感度分析
--------------------

「感度分析を実行」ボタン(``frontend/src/components/charts/TornadoChart.tsx``、
``frontend/src/hooks/useSensitivity.ts``)は、現在の発射条件を中心に、
上昇速度・破裂高度・降下速度をそれぞれ±1σだけ動かした場合の着地点変位を
計測する One-at-a-time 感度分析である。中心予測1回+各パラメータ2方向×3
パラメータ=計7回のTawhiriリクエストを行い、結果をトルネード図(横棒
グラフ)として表示する。標準プロファイルのみ対応で、統計モードには対応
していない。
