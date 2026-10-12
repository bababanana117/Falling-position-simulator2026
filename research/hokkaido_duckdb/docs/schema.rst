============
表と列の一覧
============

この章は手で書いていません。文書を組み立てるたびに実際のデータベースを開き、
``duckdb_tables()``、``duckdb_columns()`` と、データベースに保存されている
``COMMENT ON`` の文面から生成しています。そのため、この一覧が実物とずれることは
ありません。

同じ内容はデータベースの中からも引けます。

.. code-block:: sql

   SELECT table_name, column_name, declared_type, units, description
   FROM v_column_dictionary
   ORDER BY table_name, column_name;

次元表
======

.. duckdb-schema::
   :tables: dim_timebin, dim_level, dim_grid, dim_hour, dim_sector, dim_speed_class

ファクト表
==========

.. duckdb-schema::
   :tables: fact_wind, fact_speed_fit, fact_dir_fit, fact_wind_diurnal, fact_wind_rose, fact_drift

メタデータ表
============

.. duckdb-schema::
   :tables: meta_dataset, meta_column, meta_fit_family, meta_provenance, meta_reference, meta_license

ビュー
======

ビューの列は元の表の列を並べ替えたり名前を付け替えたりしたものです。列ごとの
説明は元の表を見てください。

.. duckdb-schema::
   :views:

マクロ
======

表マクロが 3 つ入っています。``duckdb_functions()`` では本体が見えないので、
ここに書いておきます。

``nearest_cell(緯度, 経度)``
   指定した地点に最も近い格子点を 1 行返します。``cell_id``、``lat``、``lon``、
   ``gauss_weight``、``distance_km`` が入っています。距離は半径 6371 km の球面での
   大円距離です。

``profile_at(緯度, 経度, 月, ビン)``
   最寄り格子点の鉛直プロファイルを、幾何高度の昇順で返します。``nearest_cell`` を
   内部で呼んでいるので、格子の並びを知らなくても使えます。

``fits_at(緯度, 経度, 月, ビン)``
   最寄り格子点で選ばれた風速と風向の分布を、38 面ぶんまとめて返します。
   ``speed_pdf`` と ``speed_sample`` には定数を埋め込んだ式が入っています。

ビンは前半が 1、後半が 2 です。

.. code-block:: sql

   SELECT * FROM fits_at(42.506, 143.440, 10, 2);   -- 10 月後半
