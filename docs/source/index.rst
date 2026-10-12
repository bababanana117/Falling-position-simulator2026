Falling-position-simulator ドキュメント
=========================================

Falling-position-simulator (Balloon Falling Position Simulator) は、
高高度気球の打ち上げ条件から着地位置を予測するWebアプリです。
フロントエンドはReact + TypeScriptで書かれたブラウザアプリで、着地予測は
CUSF/SondeHubのTawhiri APIを直接呼び出して行います。さらに、Tawhiriの
予報期間(現在から7日先まで)を超える日時を指定した場合は、過去の統計風
データから落下分布を見積もる「統計モード」に切り替わります。統計モードは
FastAPI製のバックエンドが必要です。

このドキュメントは、現在のリポジトリの構成と各機能の仕組みを説明します。
以前このリポジトリにあったjQuery/Leaflet版の静的サイトと、それに対する
リニューアル提案書は、コミット ``94887cb`` でReact+TypeScriptフロントエンドと
FastAPIバックエンドへの全面的な書き換えに置き換わりました。その提案書は
「リニューアル前の検討資料」として本ドキュメントの末尾に残しています。

.. toctree::
   :maxdepth: 2
   :caption: 現在の仕組み

   architecture
   ascent_calculator
   trajectory_prediction
   monte_carlo
   climatology
   deployment
   known_issues

.. toctree::
   :maxdepth: 2
   :caption: リニューアル前の検討資料

   proposal
