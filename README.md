# Falling-position-simulator

高高度バルーンの着地位置予測・確率分布シミュレーター。
CUSF/SondeHubのTawhiri予測APIをベースに、モンテカルロ確率分布・各種グラフ・発射条件最適化を備えたWebアプリです。

## 構成

```
frontend/   React + TypeScript + Vite 製フロントエンド (GitHub Pages配信)
backend/    FastAPI 製バックエンド (大規模モンテカルロ・自前軌道計算・最適化、開発中)
legacy/     旧jQuery版アプリ (参照用に保存)
docs/       Sphinxドキュメント (仕組み解説 + 技術提案書)
```

## 主な機能

- **単発予測 / 時系列予測**: Tawhiri API (GFS風データ) による軌道予測をLeaflet地図に表示
- **モンテカルロ確率分布**: 上昇速度・バースト高度・降下速度を正規分布/Weibull分布で摂動 (試行回数・σ・シード設定可) し、着地点の50/90/95%信頼楕円・ヒートマップ・ヒストグラムを表示
- **バルーン計算**: ペイロード質量・バルーン型番・ガス種別から上昇速度/バースト高度/必要ガス量を算出
- **発射条件最適化**: 発射地点 × ガス量 × 発射時刻のグリッドサーチで「海に落とさない」「回収しやすい」条件を提案
- **感度分析**: 各パラメータ±1σでの着地点変位をトルネード図で表示
- **JST対応**: 入力・表示は日本標準時 (内部はUTC)

## 起動方法

### クイックスタート (front + back 一括起動)

Node.js 22以降 + Python 3.12以降 + [uv](https://docs.astral.sh/uv/) が必要。

```bash
npm install        # 初回のみ (concurrently等)
npm run setup      # 初回のみ (frontend依存 + backend依存を一括インストール)
npm run dev        # フロント (http://localhost:5173) とバックエンド (http://localhost:8000) を同時起動
```

その他の一括コマンド:

```bash
npm run test       # フロント+バックエンドの全テスト
npm run build      # フロントエンド本番ビルド
npm run dev:frontend   # フロントのみ
npm run dev:backend    # バックエンドのみ
```

### フロントエンド単体 (バックエンド不要)

Node.js 22以降が必要。

```bash
cd frontend
npm install        # 初回のみ
npm run dev        # 開発サーバー起動 → http://localhost:5173
```

その他のコマンド:

```bash
npm run test       # テスト実行 (vitest)
npm run build      # 本番ビルド → frontend/dist/
npm run preview    # ビルド結果の確認サーバー
```

フロントエンドは単体で動作します (Tawhiri APIを直接呼ぶため、バックエンド不要)。

### バックエンド (任意・開発中)

Python 3.12以降 + [uv](https://docs.astral.sh/uv/) が必要。

```bash
cd backend
uv sync                                        # 初回のみ (依存インストール)
uv run uvicorn bfps.main:app --reload --port 8000
```

動作確認:

```bash
curl localhost:8000/api/health
```

テスト:

```bash
uv run pytest              # ネットワーク不要のテストのみ (既定)
```

フロントエンドからバックエンドを使う場合は環境変数を設定してビルド/起動:

```bash
cd frontend
VITE_API_BASE=http://localhost:8000 npm run dev
```

### バックエンドの公開（Docker）

公開版のフロントエンドは `https://api.cusf2026.ddd3h.com` のバックエンドを呼ぶ。
サーバーでは `backend/compose.yaml` がバックエンドと Caddy を起動し、Caddy が
Let's Encrypt の証明書を自動で取る。

1. サーバーに Docker を入れ、80/443 番を開ける
2. DNS で `api.cusf2026` の A レコードをサーバーへ向ける（Cloudflare なら DNS only・灰色のクラウド）
3. 統計風 DuckDB を `/srv/clim/` に置く
4. 起動して確認する

```bash
cd backend
docker compose up -d --build
curl https://api.cusf2026.ddd3h.com/api/health   # {"status":"ok",...}
```

詳しくは `docs/source/deployment.rst`（Sphinx の「デプロイ・配信の仕組み」）。

### 統計モード（7 日より先）

発射時刻が Tawhiri の予報窓（現在 −12 時間〜+7 日）より先のとき、単発実行とモンテカルロは
バックエンドの `POST /api/climatology/predict` を使い、JRA-3Q 2016–2025 年の統計風
（日本全国、半月ごと）から落下点の分布と平均の軌道を出す。予報ではない。
降下は地表の標高ではなく海面（0 m）まで計算し、結果は発射日が属する半月ビン（年は使わない）の
ものになる。

- 必要なもの: バックエンド（`npm run dev` で一緒に起動）と統計風 DuckDB
  `v2/jra3q_japan_wind_2016-2025_v2.duckdb`（git 管理外。作り方は `research/wind-climatology` ブランチの `v2/README.md`）。
  場所は環境変数 `BFPS_CLIMATOLOGY_DB` で変えられる。
- 計算の方法: `docs/superpowers/specs/2026-10-12-climatology-mode-design.md`
- データ: JRA-3Q（気象庁）。派生物は CC BY-NC-SA 4.0（非商用）。

### ドキュメント

```bash
pip install -r docs/requirements.txt
python -m sphinx -b html docs/source docs/_build/html
# → docs/_build/html/index.html をブラウザで開く
```

## デプロイ

mainブランチへのpushでGitHub Actionsが `frontend/` をビルドしGitHub Pagesへ自動デプロイします
(Settings > Pages > Source を "GitHub Actions" に設定)。
Sphinxドキュメントも `/docs/` 配下に同時デプロイされます。

## License

GNU General Public License
