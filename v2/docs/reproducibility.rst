==========
再現の手順
==========

この章は、このファイルがどう作られたか、その途中の判断がどこに記録されているか、
そして数字が正しいことをどう確かめたかを説明します。

作り直す
========

配布物には、できあがったデータベースとそれを作る ``jpduck`` が入っています。
一方で、入力は入っていません。作り直すには次の 2 つを別途用意してください。

1. JRA-3Q の 6 時間ごとの解析値（NSF NCAR GDEX の ``d640000``）
2. それを半月ビンに集計する上流のパイプライン（``research/windclim``）

リポジトリの中なら、次の順で作れます。

.. code-block:: console

   $ cd research
   $ python -m windclim.cli fetch --box jp               # JRA-3Q、約 100 分、8 GB
   $ python -m windclim.cli aggregate --region japan     # 約 15 分、ピーク 8.6 GB
   $ cd ../v2
   $ PYTHONPATH=.:../research python -m jpduck.build --stage all

最後のビルドは、18 コアの計算機で約 40 分、ピークの常駐メモリは約 6.9 GB です。
できあがるファイルは約 2.0 GB です。

段階は 4 つに分かれていて、それぞれ単独で走らせ直せます。

``--stage facts``
   配布用 NetCDF を行の形に組み替え、Parquet に書き出します。約 1 分。
``--stage fits``
   6 時間ごとのキャッシュを読み直し、全セルに 6 族を当てはめます。月ごとに
   Parquet を書くので、``--months 7`` のように 1 か月だけやり直せます。約 38 分
   （1 か月あたり約 3 分）。
``--stage load``
   スキーマを作り、Parquet を読み込み、説明文とメタデータを付け、ビューと
   マクロを作り、最後に圧縮し直します。約 1 分。
``--stage verify``
   ``sql/90_verify.sql`` の 37 個の検査を走らせます。1 つでも失敗すると、
   ビルドは成功を名乗らずに終了コード 1 を返します。

検査の中身
==========

検査はすべて「0 行が返れば合格」という形の SQL で、4 つの種類に分かれます。

**数の検査**
   各表の行数がちょうど期待値であること。``fact_wind`` なら 24 × 38 × 3,953 = 3,605,136 行。
   期待値は数字を書き込まず、次元表の行数から計算します。
**関係の検査**
   すべての ``cell_id`` が ``dim_grid`` にあること、当てはめの標本数が
   ``fact_wind`` の標本数と一致すること、勝者が各セルにちょうど 1 つあること。
**物理の検査**
   分位点が順序どおりであること、ベクトル平均がスカラー平均を超えないこと、
   気圧が高い面ほど高度が低いこと、``bearing_deg`` と ``bearing_from_deg`` が
   ちょうど 180 度ずれていること。
**説明の検査**
   すべての表の列に ``COMMENT ON`` が付いていること、すべてのビューに説明が
   あること、``meta_column`` の宣言とカタログの実体が食い違っていないこと。

最後の種類があるので、列を足して説明を書き忘れるとビルドが落ちます。

数値の妥当性
============

ベクトル化した推定量が正しいことは、``scipy`` の 1 標本ずつの当てはめと突き合わせて
確認してあります。

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - 量
     - 一致の度合い
     - 備考
   * - Weibull 形状 :math:`k`
     - 相対 :math:`9.3\times10^{-6}`
     - ``weibull_min.fit(x, floc=0)`` との比較
   * - Weibull 尺度 :math:`\lambda`
     - 相対 :math:`7.5\times10^{-6}`
     -
   * - Weibull の対数尤度
     - 常に scipy 以上
     - :math:`7\times10^{-10}` から :math:`1.9\times10^{-7}` だけ良い
   * - von Mises :math:`\kappa`
     - 相対 :math:`2.5\times10^{-12}`
     - ``vonmises.fit`` との比較
   * - von Mises :math:`\mu`
     - :math:`1.3\times10^{-15}` rad
     -
   * - 巻き付け正規の 2 表現
     - :math:`8.9\times10^{-16}`
     - 801 項の総当たりとの比較

対数尤度が scipy より小さくならないのは、同じ最適点により正確に到達している
ためです。

出所の記録
==========

``meta_provenance`` に、各段階の開始時刻・終了時刻・計算機名・ピークメモリ、
そしてビルドした時点のソースの版が入っています。``meta_dataset`` には入力
NetCDF の SHA-256 が入っています。

.. code-block:: sql

   SELECT step, started_at, finished_at, host, peak_rss_mb, note
   FROM meta_provenance ORDER BY started_at;

   SELECT source_sha256, source_created_at FROM meta_dataset;

手元のファイルが誰かの手で書き換えられていないかは、検査を掛ければ分かります。

.. code-block:: console

   $ PYTHONPATH=.:../research python -m jpduck.verify --db jra3q_japan_wind_2016-2025_v2.duckdb

北海道版 v1 との突き合わせ
==========================

v1（北海道、570 格子点）と v2 は、同じ JRA-3Q から同じ手順で作っています。
範囲が重なる 408 格子点（372,096 行）で両者を比べると、次のとおり一致します。

* 平均風速・p90・恒常度・有効標本数は完全に一致する
* 当てはめた分布の定数の差は :math:`7\times10^{-15}` 以下（丸め誤差）
* 選ばれた族は 1 面も食い違わない

範囲の取り方が違うだけで、同じ格子点では同じ数字が得られる、ということです。
