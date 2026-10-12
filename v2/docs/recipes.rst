==========
使い方の例
==========

この章の SQL は、``docs/_sql/`` に入っている実際のファイルです。文書を組み立てる
ときに実行しているので、ここに載っている結果は実際の出力です。書いてあるとおりに
コピーすれば同じものが返ります。

.. Furo puts an "On this page" panel beside the text, so a local
   contents here would duplicate it -- and some Furo versions refuse
   the directive outright. The PDF has no such panel, so the chapter
   table of contents is emitted for LaTeX only.

.. only:: latex

   .. contents:: この章の内容
      :local:

打ち上げ地点の風を引く
======================

.. sql-recipe:: 01_nearest_cell.sql
   :caption: 最寄り格子点を探す

.. sql-recipe:: 02_profile.sql
   :caption: 鉛直プロファイル

.. sql-recipe:: 03_fits_at.sql
   :caption: 当てはめた分布

時期を選ぶ
==========

.. sql-recipe:: 05_seasonal_cycle.sql
   :caption: 200 hPa の年変化
   :limit: 24

.. sql-recipe:: 06_strongest_bin.sql
   :caption: 300 hPa がいちばん荒れる半月
   :limit: 5

12 月前半の 300 hPa では、領域内のどこかで p90 が 77 m/s に達します。一方で、
同じビンの領域平均は 43 m/s です。領域内の差が大きいので、平均だけで判断せず、
打ち上げ地点の格子点で引いてください。

分布を使う
==========

.. sql-recipe:: 04_pdf_rendered.sql
   :caption: 定数を埋め込んだ式を取り出す
   :limit: 2

.. sql-recipe:: 13_monte_carlo.sql
   :caption: データベースの中で逆関数法を回す

Python から落下計算に渡すときは、族ごとに分岐するより ``scipy`` の分布オブジェクトを
組み立てるほうが簡単です。

.. code-block:: python

   import duckdb
   import numpy as np
   from scipy import stats

   con = duckdb.connect("jra3q_japan_wind_2016-2025_v2.duckdb", read_only=True)
   rows = con.execute(
       "SELECT * FROM fits_at(33.437, 135.762, 10, 2) ORDER BY alt_geom_mean_km"
   ).fetchdf()

   def speed_dist(r):
       if r.speed_family == "weibull_min_loc0":
           return stats.weibull_min(r.weibull_shape, 0.0, r.weibull_scale_ms)
       if r.speed_family == "normal":
           return stats.norm(r.mu_ms, r.sigma_ms)
       return stats.uniform(r.uniform_a_ms, r.uniform_b_ms - r.uniform_a_ms)

   def direction_dist(r):
       if r.dir_family == "von_mises":
           return stats.vonmises(r.kappa, loc=np.radians(r.mu_deg))
       if r.dir_family == "wrapped_normal":
           # scipy に巻き付け正規は無い。正規から引いて巻き戻す。
           return None
       return stats.uniform(-np.pi, 2 * np.pi)

   rng = np.random.default_rng(0)
   for _, r in rows.iterrows():
       speed = speed_dist(r).rvs(1000, random_state=rng)
       if r.dir_family == "wrapped_normal":
           raw = rng.normal(np.radians(r.mu_deg), np.radians(r.wn_sigma_deg), 1000)
           theta = (raw + np.pi) % (2 * np.pi) - np.pi
       else:
           theta = direction_dist(r).rvs(1000, random_state=rng)

.. warning::

   上の書き方は各気圧面を独立に引いています。実際の大気では、ある面で風が強い日は
   その上下でも強く、鉛直方向に強い相関があります。独立に引くと、上下の風が
   打ち消し合って落下位置の散らばりを小さく見積もります。層どうしの連動を保ちたい
   場合は、観測された順位相関からガウス・コピュラを作り、各面の周辺分布は当てはめた
   まま結び付けてください。

風配図と時刻別
==============

.. sql-recipe:: 09_rose.sql
   :caption: 風配図
   :limit: 5

.. sql-recipe:: 11_diurnal.sql
   :caption: 時刻別の平均風速
   :limit: 4

落下位置
========

.. sql-recipe:: 10_drift.sql
   :caption: 公称飛行の水平移動
   :limit: 5

``fact_drift`` は上昇速度と到達高度を固定した仮定計算です。実際の飛行計画の
代わりにはなりませんが、時期ごとの相対比較には使えます。

列の意味を調べる
================

.. sql-recipe:: 12_column_lookup.sql
   :caption: データベース自身に列の意味を尋ねる
   :limit: 6

``v_column_dictionary`` には全 :dbq:`SELECT count(*) FROM meta_column` 列の
説明・単位・出所が入っています。手元に
この文書が無くても、データベースだけで列の意味が分かります。

品質を確かめる
==============

.. sql-recipe:: 07_family_counts.sql
   :caption: 族の選ばれ方と曖昧率
   :limit: 6

.. sql-recipe:: 08_effective_sample.sql
   :caption: 高度ごとの有効標本数
   :limit: 8
