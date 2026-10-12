==========
ライセンス
==========

.. warning::

   このデータベースは **非商用** です。JRA-3Q の派生物なので、元データと同じ
   条件が継承されます。

条件
====

.. sql-recipe:: 00_license.sql
   :caption: データベースに入っているライセンス情報

``meta_license`` には 2 行入っています。1 行目が元データ（JRA-3Q）、2 行目が
このデータベース自身です。``inherits_from`` 列が、2 行目の条件が 1 行目から
継承されたものであることを示します。

**CC BY-NC-SA 4.0** の 3 つの条件は次のとおりです。

表示（BY）
   出典を示してください。文面は下の :ref:`citation` にあります。
非商用（NC）
   商用目的で使えません。
継承（SA）
   これを改変したものを配布するときは、同じライセンスを付けてください。

全文は https://creativecommons.org/licenses/by-nc-sa/4.0/ にあります。

.. _citation:

引用
====

このデータベースを使った成果を公表するときは、JRA-3Q の論文を引用してください。

.. code-block:: text

   Kosaka, Y., S. Kobayashi, Y. Harada, C. Kobayashi, H. Naoe, K. Yoshimoto,
   M. Harada, N. Goto, J. Chiba, K. Miyaoka, R. Sekiguchi, M. Deushi,
   H. Kamahori, T. Nakaegawa, T. Y. Tanaka, T. Tokuhiro, Y. Sato, Y. Matsushita,
   and K. Onogi, 2024: The JRA-3Q Reanalysis. J. Meteor. Soc. Japan, 102,
   49-109, doi:10.2151/jmsj.2024-004.

データそのものの出所は次のとおりです。

.. code-block:: text

   JRA-3Q reanalysis, Japan Meteorological Agency, distributed by
   NSF NCAR GDEX (dataset d640000). Licensed CC BY-NC-SA 4.0.

参考文献の一覧は ``meta_reference`` にも入っています。

.. code-block:: sql

   SELECT citation_key, authors, year, title, doi FROM meta_reference;

配布するとき
============

``.duckdb`` ファイルの隣に ``jra3q_japan_wind_2016-2025_v2.LICENSE.md`` を
置いてあります。ビルドが毎回書き出すので、ファイルを渡すときはこの 2 つを
一緒に渡してください。

ライセンスの文面はデータベースの中にも入っているので、サイドカーを失っても
``SELECT * FROM v_license`` で確認できます。

.. note::

   このデータベースはウェブアプリの配布物には含めていません。非商用条件が
   アプリ全体に及ぶことを避けるためです。解析用の成果物として、この
   ディレクトリの中だけで扱ってください。
