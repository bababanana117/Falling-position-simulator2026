.. _basics:

========================
データベースが初めてなら
========================

この章は、データベースも SQL も触ったことがない人のためのものです。すでに
``SELECT`` が書ける人は :doc:`quickstart` へ進んでください。

.. Furo puts an "On this page" panel beside the text, so a local
   contents here would duplicate it -- and some Furo versions refuse
   the directive outright. The PDF has no such panel, so the chapter
   table of contents is emitted for LaTeX only.

.. only:: latex

   .. contents:: この章の内容
      :local:

DuckDB とは
===========

**DuckDB は、1 つのファイルで完結するデータベースです。** サーバを立てる必要も、
ユーザ登録も、設定ファイルもありません。``.duckdb`` という拡張子のファイルが
1 つあり、それを開くだけで使えます。

.. code-block:: console

   $ pip install duckdb
   $ duckdb -readonly jra3q_hokkaido_wind_2016-2025_v1.duckdb

仕組みとしては SQLite に近く、用途が違います。SQLite は「1 行を読み書きする」
のが得意で、DuckDB は「何百万行を一度に集計する」のが得意です。この
データベースは 480 万行あり、そのほとんどは 1 行ずつではなく、まとめて
平均したり絞り込んだりして使うものなので、DuckDB が向いています。

表（テーブル）
==============

**テーブルは、行と列でできた表です。** 表計算ソフトの 1 シートだと思って
かまいません。違うのは、列ごとに型（整数、小数、文字列）が決まっていることと、
行数に上限が無いことです。

このデータベースには **18 のテーブル**\ が入っています。いちばん大きいのが
``fact_wind`` で、519,840 行あります。1 行が「ある時期・ある気圧面・ある
格子点」の統計値です。

.. sql-recipe:: 14_first_query.sql
   :caption: 表から 3 行だけ取り出す
   :limit: 3

``SELECT`` のあとに欲しい列を並べ、``FROM`` のあとに表の名前を書きます。
``*`` と書けば全列です（``fact_wind``\ なら 46 列返ってきます）。

行を絞る
--------

.. sql-recipe:: 15_where.sql
   :caption: WHERE で条件を付ける
   :limit: 5

``WHERE`` が条件、``ORDER BY`` が並べ替え、``LIMIT`` が件数です。
``ORDER BY ... DESC`` で降順になります。

まとめる
--------

.. sql-recipe:: 16_group_by.sql
   :caption: GROUP BY で気圧面ごとにまとめる
   :limit: 4

``GROUP BY level_hpa`` は「気圧面が同じ行をひとまとめにする」という意味です。
まとめたあとで ``avg()``\ （平均）や ``max()``\ （最大）、``count(*)``\ （行数）を
計算します。この種の関数を集計関数と呼びます。

つなぐ（結合・JOIN）
====================

このデータベースは、同じ情報を何度も書かないよう表を分けてあります。たとえば
``fact_wind`` は時期を ``timebin_id`` という 0--23 の番号でしか持っていません。
「1 月前半」という日本語のラベルや「冬」という季節は、``dim_timebin`` という
別の小さな表に 24 行だけ置いてあります。

この 2 つを結び付けるのが **JOIN** です。

.. sql-recipe:: 17_join.sql
   :caption: JOIN で番号にラベルを付ける
   :limit: 4

``ON t.timebin_id = w.timebin_id`` が「この列が一致する行どうしを並べる」と
いう指定です。同じ名前の列でつなぐときは ``USING (timebin_id)`` と短く書けます。

このように、番号を持つ側を\ **ファクト表**\ 、番号の意味を持つ側を\ **次元表**\ と
呼びます。名前の通り、``fact_`` で始まる表が前者、``dim_`` で始まる表が
後者です。詳しい構造は :doc:`datamodel` にあります。

ビュー
======

**ビューは、名前を付けて保存しておいたクエリです。** データの複製ではありません。
ビューを ``SELECT`` すると、その場で元の表から計算されます。

上の JOIN のような定型の書き方を毎回打ち直さずに済むよう、このデータベースには
**10 のビュー**\ が用意してあります。使うときはテーブルと同じように書けます。

.. code-block:: sql

   SELECT * FROM v_wind LIMIT 5;        -- fact_wind に時期のラベルを結合済み

名前が ``v_`` で始まるものがビューです。中身が何かは
``SELECT * FROM duckdb_views()`` で見られます。いちばん重要なのは
``v_speed_fit_selected`` で、当てはめた分布の式を、そのセルの定数を
埋め込んだ文字列として返します。

.. note::

   ビューは元の表を書き換えません。読むだけなので、何を実行しても
   データベースが壊れることはありません。``read_only=True`` を付けて
   開けば、そもそも書き込み自体ができなくなります。

マクロ
======

**マクロは、引数を取れるビューです。** このデータベースには 3 つあります。

.. code-block:: sql

   SELECT * FROM nearest_cell(42.506, 143.440);          -- 最寄り格子点
   SELECT * FROM profile_at(42.506, 143.440, 10, 2);     -- 鉛直プロファイル
   SELECT * FROM fits_at(42.506, 143.440, 10, 2);        -- 当てはめた分布

ビューは決まった中身しか返せませんが、マクロは呼ぶたびに違う地点や時期を
渡せます。緯度・経度・月・ビン（前半なら 1、後半なら 2）を渡してください。

行と列の型
==========

列には型があります。このデータベースで出てくるのは次の 4 つです。

``INTEGER`` / ``SMALLINT``
   整数。``month`` や ``n`` など。
``REAL``
   単精度の小数。元の NetCDF 由来の統計量はすべてこれです。有効数字は
   7 桁ほどなので、**等号で比較しないでください**\ （:ref:`caveats` 参照）。
``DOUBLE``
   倍精度の小数。当てはめの結果に使っています。
``VARCHAR`` / ``ENUM``
   文字列。``ENUM`` は「決まった候補のどれか」に限った文字列で、
   ``family`` 列などに使っています。綴りを間違えるとエラーになります。

NULL は「値が無い」という印です。0 ではありません。たとえば ``circ_sd_deg``
は風向が定まらない面で NULL になります。0（ばらつきが無い）と取り違えないで
ください。

結果を持ち出す
==============

Python から使う場合は、そのまま pandas に渡せます。

.. code-block:: python

   import duckdb

   con = duckdb.connect("jra3q_hokkaido_wind_2016-2025_v1.duckdb", read_only=True)
   df = con.execute("SELECT * FROM profile_at(42.506, 143.440, 10, 2)").fetchdf()
   print(df.head())

ファイルに書き出すこともできます。

.. sql-recipe:: 18_export.sql
   :caption: CSV や Parquet に書き出す
   :no-run:

Excel で開きたいなら CSV、別の解析に渡すなら Parquet が向いています。
Parquet は型と圧縮が保たれるので、書き出して読み直しても数値が変わりません。

困ったときに引く先
==================

**列の意味が分からない**
   ``SELECT * FROM v_column_dictionary WHERE column_name = 'constancy';``
   データベース自身が 240 列すべての説明と単位を持っています。

**どんな表があるか分からない**
   ``SELECT table_name, comment FROM duckdb_tables() WHERE NOT internal;``

**どんなビューがあるか分からない**
   ``SELECT view_name, comment FROM duckdb_views() WHERE NOT internal;``

**ライセンスを確認したい**
   ``SELECT * FROM v_license;``

**SQL そのものを学びたい**
   DuckDB の公式文書（https://duckdb.org/docs/）が短くて実用的です。
   ここで使っている構文は ``SELECT`` ``WHERE`` ``GROUP BY`` ``JOIN``
   ``ORDER BY`` ``LIMIT`` だけで、どれも標準 SQL と同じです。

用語のまとめは :doc:`glossary` にもあります。
