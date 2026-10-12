全体アーキテクチャ
====================

概要
----

Falling-position-simulator は、フロントエンド(``frontend/``)とバックエンド
(``backend/``)に分かれたWebアプリです。フロントエンドはReact 19 +
TypeScript + Viteで書かれ、Cloudflare Workersの静的アセット配信機能で
配信されます。
バックエンドはPython + FastAPIで書かれており、統計モード(:doc:`climatology`)
のときだけフロントエンドから呼び出されます。通常の予測(単発予測・時系列
予測・モンテカルロ)はバックエンドを経由せず、ブラウザから外部のTawhiri
APIを直接呼び出します。

.. mermaid::

   flowchart LR
       User["利用者<br/>(ブラウザ)"]
       Frontend["フロントエンド<br/>React + TypeScript (Vite)"]
       Tawhiri["Tawhiri API<br/>api.v2.sondehub.org/tawhiri<br/>(SondeHubホスティング, GFS風データ)"]
       Backend["バックエンド<br/>FastAPI (統計モードのみ)"]
       DuckDB["統計風DuckDB<br/>JRA-3Q 2016-2025 (git管理外)"]
       OpenMeteo["Open-Meteo<br/>Elevation API"]

       User -->|"発射地点・日時・上昇速度等を入力"| Frontend
       Frontend -->|"予報窓内 現在-12h〜+7日 HTTP GET /tawhiri"| Tawhiri
       Tawhiri -->|"軌道点列 緯度経度高度時刻"| Frontend
       Frontend -->|"予報窓より先 バックエンドが設定されている場合 POST /api/climatology/predict"| Backend
       Backend -->|"読み取り専用で開く"| DuckDB
       Backend -->|"平均軌道・落下点の標本・統計情報"| Frontend
       Frontend -->|"着地点ごとに標高を取得"| OpenMeteo
       OpenMeteo -->|"標高 取得できない場合はnull"| Frontend
       Frontend -->|"地図・グラフとして表示"| User

ポイント:

- 軌道の積分計算そのものは本リポジトリでは行わない。予報窓内は
  **すべてTawhiri側(外部サーバー)で計算する**\ 。本リポジトリはリクエストを
  組み立てて結果を地図とグラフに描画する
- バックエンドは統計モードのときだけ使われる。予報窓内の予測・モンテカルロ・
  時系列予測・最適化・感度分析はいずれもバックエンドを経由しない
- 着地点の安全判定(陸海・住宅街・制限区域・標高)に使う陸地データ
  (``frontend/public/geo/land.json``、Natural Earth 50m)や施設データは
  静的ファイルとしてフロントエンドに同梱されており、外部APIへの問い合わせは
  発生しない。標高だけはOpen-Meteoから取得する

ディレクトリ構成
----------------

.. code-block:: text

   Falling-position-simulator2026/
   ├── frontend/                    # React + TypeScript + Vite フロントエンド
   │   ├── wrangler.jsonc            # Cloudflare Workers配信設定 (独自ドメイン等)
   │   ├── public/
   │   │   ├── geo/                   # land.json / towns.json / restricted.json
   │   │   └── sites.json             # 地域別の発射地点プリセット
   │   └── src/
   │       ├── api/                   # tawhiri.ts, backend.ts, climatology.ts
   │       ├── time/                  # jst.ts, forecastWindow.ts
   │       ├── mc/                    # モンテカルロ (Web Worker, 摂動生成)
   │       ├── stats/                 # 着地点統計・信頼楕円
   │       ├── safety/                # 着地安全判定・標高取得
   │       ├── optimizer/             # 発射条件グリッドサーチ
   │       ├── physics/               # バルーンサイジング計算
   │       ├── store/                 # Zustandストア
   │       ├── hooks/                 # useRunPrediction, useSensitivity
   │       └── components/            # 地図・グラフ・入力パネル
   ├── backend/                     # FastAPI バックエンド (統計モードのみ使用)
   │   ├── bfps/
   │   │   ├── main.py                # FastAPIアプリ本体、CORS設定
   │   │   ├── config.py              # 環境変数 (BFPS_ プレフィクス)
   │   │   ├── api/                   # ルーター (health/simulate/optimize/climatology)
   │   │   ├── climatology/           # 統計モードの計算本体
   │   │   ├── core/                  # 大気・軌道・モンテカルロ・最適化の自前実装
   │   │   └── models/                # リクエスト/レスポンスのPydanticモデル
   │   └── Dockerfile
   ├── docs/                        # このSphinxドキュメント
   └── .github/workflows/deploy.yml # Cloudflare Workers自動デプロイ

.. note::

   ``backend/bfps/core`` や ``bfps/api/routes_simulate.py`` /
   ``routes_optimize.py`` には、自前の軌道積分・モンテカルロ・最適化の実装が
   あるが、現在のフロントエンドはこれらを呼び出していない。フロントエンドが
   バックエンドに投げるのは統計モードの ``/api/climatology/predict`` のみ
   である。

技術スタック
------------

.. list-table::
   :header-rows: 1

   * - 領域
     - 使用技術
   * - フロントエンド言語/ビルド
     - TypeScript、Vite、React 19
   * - 状態管理
     - Zustand
   * - 2D地図
     - Leaflet (react-leaflet)、ヒートマップ表示に leaflet.heat
   * - 3D地図
     - three.js (``@navaramap/three`` 経由)。2D/3Dは切替可能
   * - グラフ
     - Plotly.js (react-plotly.js)
   * - モンテカルロ実行
     - Web Worker (複数) でTawhiriへの並列リクエストを分散
   * - 日時
     - date-fns / date-fns-tz。入力・表示はJST、内部はUTC
   * - 着地予測 (予報窓内)
     - 外部Tawhiri API (ブラウザから直接呼び出し、自前実装なし)
   * - 着地予測 (統計モード)
     - バックエンドの ``POST /api/climatology/predict``
   * - 標高取得
     - Open-Meteo Elevation API
   * - バックエンド
     - Python 3.12、FastAPI、Pydantic、NumPy/SciPy、DuckDB
   * - ホスティング (フロントエンド)
     - Cloudflare Workers (静的アセット配信、GitHub Actionsでビルドして
       ``wrangler deploy``、独自ドメイン)
   * - ホスティング (バックエンド)
     - リポジトリ外の運用者提供サーバー (Docker、:doc:`deployment` 参照)

外部依存
--------

- **Tawhiri API**: ``https://api.v2.sondehub.org/tawhiri``
  (SondeHubがホストするCUSF Tawhiriのインスタンス。GFS風データを用いて
  気球の上昇・降下軌道を数値積分する)。APIキー不要で、ブラウザから直接
  ``fetch`` している (``frontend/src/api/tawhiri.ts``)
- **Open-Meteo Elevation API**: 着地点の標高を取得し、安全判定
  (:doc:`monte_carlo`) に使う。1分あたりのリクエスト数に上限があり、
  429応答時は1回だけ待って再試行する (``frontend/src/safety/elevation.ts``)
- **JRA-3Q統計風データ**: 統計モードのみで使用。気象庁のJRA-3Q再解析データ
  から作成したDuckDBファイルで、リポジトリには含まれない
  (:doc:`climatology` 参照)
