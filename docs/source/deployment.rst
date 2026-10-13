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

このリポジトリでは前者を選び、サーバー側で証明書を取る。

Docker Composeで動かす
~~~~~~~~~~~~~~~~~~~~~~

``backend/compose.yaml`` は ``backend/Dockerfile`` からバックエンドの
コンテナ ``api`` をビルドして起動する。

- ホストの ``/srv/clim`` を ``/data`` に読み取り専用でマウントし、
  ``BFPS_CLIMATOLOGY_DB=/data/jra3q_japan_wind_2016-2025_v2.duckdb`` を渡す。
- ポートは ``127.0.0.1:8080`` だけで待つ。外から直接はつながらないので、
  同じサーバーのWebサーバー(nginxかCaddy)からHTTPSを受けて転送する。
  ホスト側のポートは環境変数 ``BFPS_HOST_PORT`` で変えられる
  (例: ``BFPS_HOST_PORT=18080 docker compose up -d``)。

HTTPSを受けるWebサーバーは、サーバーの状況で選ぶ。

.. list-table::
   :header-rows: 1

   * - サーバーの状況
     - 使う設定
     - 起動
   * - 80/443番を既にnginxが使っている
     - ``backend/nginx/api.cusf2026.ddd3h.com.conf`` をnginxに足し、
       certbotで証明書を取る
     - ``docker compose up -d --build``
   * - 80/443番が空いている
     - ``backend/Caddyfile`` (Caddyのコンテナが証明書を自動で取る)
     - ``docker compose --profile caddy up -d --build``

80/443番が使われているサーバーで ``--profile caddy`` を付けると、Caddyの
起動が ``bind: address already in use`` で失敗する。使っているプログラムは
``sudo ss -ltnp | grep -E ':80 |:443 '`` で確かめられる。

サーバーで必要な準備と起動の手順は次のとおり。

1. Docker と Docker Compose を入れる。
2. ファイアウォールで80番と443番を開ける(80番は証明書の取得に使う)。
3. DNSで ``api.cusf2026`` のAレコードをサーバーのIPアドレスに向ける。
   CloudflareのDNSを使う場合は、プロキシをオフ(灰色のクラウド、
   DNS only)にする。オンのままだと上記の理由でHTTPSが通らない。
4. 統計風DuckDBをサーバーへコピーする。``sudo mkdir`` で作ったフォルダは
   rootの持ち物で書き込めないので、先に持ち主を自分に変える。

   .. code-block:: bash

      # サーバーで
      sudo mkdir -p /srv/clim
      sudo chown $USER:$USER /srv/clim
      # 手元のPCから(1.9GBあるので、途中から再開できるrsyncが便利)
      rsync -avP v2/jra3q_japan_wind_2016-2025_v2.duckdb server:/srv/clim/

5. リポジトリを取得し、``backend/`` でバックエンドを起動する。ビルドには
   一時的に1GBほど使うので、ディスクの空きを2GB以上にしておく
   (足りないと ``no space left on device`` で止まる。
   ``docker system prune`` で古いイメージを消せる)。

   .. code-block:: bash

      git clone https://github.com/ddd3h/Falling-position-simulator2026.git
      cd Falling-position-simulator2026/backend
      docker compose up -d --build
      curl localhost:8080/api/health     # {"status":"ok","version":"0.1.0"}

6. nginxを使う場合は、転送の設定を足して証明書を取る(Caddyを使う場合は
   5. で ``--profile caddy`` を付ければよく、この手順は要らない)。

   .. code-block:: bash

      sudo cp nginx/api.cusf2026.ddd3h.com.conf /etc/nginx/sites-available/
      sudo ln -s /etc/nginx/sites-available/api.cusf2026.ddd3h.com.conf /etc/nginx/sites-enabled/
      sudo nginx -t && sudo systemctl reload nginx
      sudo certbot --nginx -d api.cusf2026.ddd3h.com

   certbotが443番の ``server`` ブロックと、80番からHTTPSへの転送を設定に
   書き足す。証明書の更新もcertbotのタイマーが行う。

7. 外から確かめる。``{"status":"ok","version":"0.1.0"}`` が返れば、
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
