デプロイ・配信の仕組み
========================

フロントエンドのCloudflare Workers自動デプロイ
---------------------------------------------------

フロントエンドは、Cloudflare Workersの静的アセット配信機能で公開する
(以前はGitHub Pagesで配信していたが、現在はCloudflare Workersに
切り替えている)。配信先の設定は ``frontend/wrangler.jsonc`` にある。

.. code-block:: text

   {
     "name": "falling-position-simulator",
     "compatibility_date": "2026-08-01",
     "assets": {
       "directory": "./dist",
       "not_found_handling": "single-page-application"
     },
     "routes": [
       { "pattern": "cusf2026.ddd3h.com", "custom_domain": true }
     ]
   }

``.github/workflows/deploy.yml`` により、``main`` ブランチへのpush
(または手動 ``workflow_dispatch``)をトリガーに、以下の手順で
``frontend/`` をビルドしてCloudflare Workersへ配信する。

.. mermaid::

   flowchart LR
       A["push to main"] --> B["actions/checkout@v4"]
       B --> C["npm ci (frontend/)"]
       C --> D["npm run test -- --run<br/>(vitest)"]
       D --> E["npm run build<br/>VITE_API_BASE=https://api.cusf2026.ddd3h.com"]
       E --> F["Sphinxドキュメントを<br/>frontend/dist/docs へビルド<br/>(失敗しても続行)"]
       F --> G["cloudflare/wrangler-action@v3<br/>command: deploy"]
       G --> H["Cloudflare Workers公開<br/>https://cusf2026.ddd3h.com<br/>(wrangler.jsoncのcustom domain)"]

ポイント:

- テストが落ちるとビルド自体が止まる (``npm run test -- --run`` が
  ``npm run build`` より前にある)。Sphinxドキュメントのビルドは
  ``continue-on-error: true`` のため、失敗してもアプリ本体のデプロイは
  止まらない
- ``VITE_API_BASE`` をビルド時に埋め込むことで、公開されたフロントエンドは
  ``https://api.cusf2026.ddd3h.com`` のバックエンドを統計モードで使う。
  この変数が未設定だと統計モードは「バックエンドが必要です」という
  エラーになる (:doc:`climatology`)
- デプロイ (``cloudflare/wrangler-action@v3``、``command: deploy``) には
  リポジトリのsecretsとして ``CLOUDFLARE_API_TOKEN``
  (Workersの編集権限を持つAPIトークン)と ``CLOUDFLARE_ACCOUNT_ID`` が
  必要。未設定だとデプロイの手順が ``In a non-interactive environment,
  it's necessary to set a CLOUDFLARE_API_TOKEN environment variable``
  で失敗する。設定の手順は次のとおり

  1. Cloudflareのダッシュボードで「My Profile → API Tokens → Create
     Token」を開き、テンプレート「Edit Cloudflare Workers」でトークンを
     作る
  2. アカウントIDは、ダッシュボードの「Workers & Pages」の右側にある
     「Account ID」をコピーする
  3. GitHubのリポジトリで「Settings → Secrets and variables → Actions →
     New repository secret」から、上の2つをそれぞれ
     ``CLOUDFLARE_API_TOKEN`` と ``CLOUDFLARE_ACCOUNT_ID`` の名前で登録する
  4. 「Actions」タブで失敗した実行を開き、「Re-run jobs」でやり直す
- 配信先は ``not_found_handling: "single-page-application"`` により、
  存在しないパスへのアクセスは ``index.html`` にフォールバックする
  (SPA向けの設定)
- 同時実行は ``concurrency: group: "deploy", cancel-in-progress: true``
  でグループ化し、同時デプロイの競合を防ぐ

手動デプロイするときは、``frontend`` ディレクトリで次を実行する(初回は
``npx wrangler login`` が必要)。

.. code-block:: bash

   cd frontend
   npm run deploy:cf   # VITE_API_BASE=https://api.cusf2026.ddd3h.com でビルドし、wrangler deploy する

独自ドメインとDNS
--------------------

公開URLは独自ドメイン ``https://cusf2026.ddd3h.com`` である。この
ドメインは ``frontend/wrangler.jsonc`` の ``routes`` に
``custom_domain: true`` で設定したCloudflare Workersのカスタムドメインで
あり、対応するDNSレコードはCloudflareが自動的に用意する。GitHub Pages
使用時にあった ``frontend/public/CNAME`` やリポジトリのPages設定は
不要になり、現在は存在しない。

バックエンドのデプロイ
--------------------------

バックエンド (``backend/``) はCloudflare Workersでは配信できない
(Pythonプロセスを常駐させる必要があるため)。``https://api.cusf2026.ddd3h.com``
として、Workersとは別のサーバーで動かす。このサーバーの用意と運用は
リポジトリの外で行う (運用者が用意したサーバーを前提とする)。

**コンテナ化**: ``backend/Dockerfile`` は ``python:3.12-slim`` をベースに
``uv`` で依存をインストールし、``uvicorn`` を8080番ポートで起動する。

.. code-block:: text

   FROM python:3.12-slim
   WORKDIR /app
   COPY pyproject.toml ./
   RUN pip install --no-cache-dir uv && uv pip install --system .
   COPY bfps ./bfps
   EXPOSE 8080
   CMD ["uvicorn", "bfps.main:app", "--host", "0.0.0.0", "--port", "8080"]

**統計風DuckDBの配置**: 統計モードが読む
``v2/jra3q_japan_wind_2016-2025_v2.duckdb`` はサイズが大きく(約1.9GB)、
Gitで管理していない。バックエンドを動かすサーバーに別途このファイルを
コピーし、環境変数 ``BFPS_CLIMATOLOGY_DB`` でそのパスを指定する(既定値は
``../v2/jra3q_japan_wind_2016-2025_v2.duckdb``、``backend/`` からの相対
パス)。ファイルが見つからない、または壊れていて開けない場合、APIは
503を返す (``backend/bfps/api/routes_climatology.py``)。

**環境変数**:

.. list-table::
   :header-rows: 1

   * - 変数名
     - 意味
     - 既定値
   * - ``BFPS_CLIMATOLOGY_DB``
     - 統計風DuckDBファイルのパス
     - ``../v2/jra3q_japan_wind_2016-2025_v2.duckdb``
   * - ``BFPS_ALLOWED_ORIGINS``
     - CORSで許可するオリジン (``Settings.allowed_origins``、
       ``BFPS_`` プレフィクスの環境変数として渡す)
     - ``https://cusf2026.ddd3h.com``、``http://localhost:5173``、
       ``http://localhost:8080``
   * - ``BFPS_MC_MAX_SAMPLES``
     - バックエンド側モンテカルロの上限サンプル数 (現在フロントエンドは
       未使用)
     - ``2000``

**HTTPSについての注意**: ``api.cusf2026.ddd3h.com`` のように、ベースドメイン
から見て2階層目のサブドメイン(セカンドレベルサブドメイン)は、Cloudflareの
無料 Universal SSL の対象にならないことがある。Universal SSLは
``ddd3h.com`` と ``*.ddd3h.com`` (1階層目のワイルドカード)はカバーするが、
``*.cusf2026.ddd3h.com`` のような2階層目のワイルドカードはカバーしない
ためである。バックエンドをHTTPSで公開する場合は、次のいずれかにする必要が
ある。

- Cloudflareのプロキシ(オレンジ色のクラウド)をオフにして、サーバー側で
  証明書(Let's Encrypt等)を用意する
- ``api.cusf2026.ddd3h.com`` ではなく ``api-cusf2026.ddd3h.com`` のような
  1階層目のサブドメインにする

このリポジトリでは前者を選び、次の Docker Compose の構成で Caddy に
証明書を取らせる。

Docker Composeで動かす
~~~~~~~~~~~~~~~~~~~~~~

``backend/compose.yaml`` は2つのコンテナを起動する。

- ``api``: ``backend/Dockerfile`` からビルドしたバックエンド。ホストの
  ``/srv/clim`` を ``/data`` に読み取り専用でマウントし、
  ``BFPS_CLIMATOLOGY_DB=/data/jra3q_japan_wind_2016-2025_v2.duckdb`` を渡す。
  ポートはホストに公開しない。
- ``caddy``: ``backend/Caddyfile`` に従って ``api.cusf2026.ddd3h.com`` への
  HTTPS を受け、``api:8080`` へ転送する。Let's Encrypt の証明書は Caddy が
  自動で取得・更新し、ボリューム ``caddy_data`` に保存する。

サーバーで必要な準備と起動の手順は次のとおり。

1. Docker と Docker Compose を入れる。
2. ファイアウォールで80番と443番を開ける(80番は証明書の取得に使う)。
3. DNSで ``api.cusf2026`` のAレコードをサーバーのIPアドレスに向ける。
   CloudflareのDNSを使う場合は、プロキシをオフ(灰色のクラウド、
   DNS only)にする。オンのままだと上記の理由でHTTPSが通らない。
4. 統計風DuckDBをサーバーへコピーする。

   .. code-block:: bash

      sudo mkdir -p /srv/clim
      scp v2/jra3q_japan_wind_2016-2025_v2.duckdb server:/srv/clim/

5. リポジトリを取得し、``backend/`` で起動する。

   .. code-block:: bash

      git clone https://github.com/ddd3h/Falling-position-simulator2026.git
      cd Falling-position-simulator2026/backend
      docker compose up -d --build

6. 動作を確かめる。``{"status":"ok","version":"0.1.0"}`` が返れば、
   バックエンドはHTTPSで公開できている。統計モードがDuckDBを読めるかは、
   フロントエンド (``https://cusf2026.ddd3h.com``) で8日以上先の日時を
   選んで実行すると分かる(読めないときは503のエラーが出る)。

   .. code-block:: bash

      curl https://api.cusf2026.ddd3h.com/api/health

コードを更新したときは ``git pull`` のあとに ``docker compose up -d --build``
を、ログを見るときは ``docker compose logs -f`` を実行する。DuckDBを
差し替えたときは ``docker compose restart api`` で読み直させる。

ローカル開発
------------

Node.js 22以降、Python 3.12以降、`uv <https://docs.astral.sh/uv/>`_ が必要
(``README.md`` 参照)。

.. code-block:: bash

   npm install        # 初回のみ (concurrently等)
   npm run setup      # 初回のみ (frontend依存 + backend依存を一括インストール)
   npm run dev        # フロント (http://localhost:5173) とバックエンド (http://localhost:8000) を同時起動

ルートの ``package.json`` の ``dev`` は ``concurrently`` で
``dev:frontend`` と ``dev:backend`` を並行実行する。``dev:frontend`` は
``VITE_API_BASE=http://localhost:8000`` を設定して ``frontend`` の
Viteサーバーを起動し、``dev:backend`` は ``backend`` で
``uv run uvicorn bfps.main:app --reload --port 8000`` を実行する。

フロントエンドはバックエンドが無くても単体で動く(予報窓内の予測は
Tawhiriを直接呼ぶため)。``VITE_API_BASE`` を設定しない場合、統計モードは
使えず、予報窓を超えた日時を指定するとエラーになる。

テストは ``npm run test`` でフロントエンド(vitest)とバックエンド(pytest)
をまとめて実行する。
