# 統計モード（気候値による落下予測）の設計

日付: 2026-10-12
状態: 合意済み（実装前）

## 目的

打ち上げ日時が Tawhiri の予報窓（現在 −12 時間〜+7 日）より先のとき、今はエラーになって
何も出ない。このとき、日本全国の統計風データベース
（`v2/jra3q_japan_wind_2016-2025_v2.duckdb`、JRA-3Q 2016–2025 年、半月ごと）から、
その時期の落下点の分布と平均の軌道を出す。

## 決めたこと

- データは FastAPI のバックエンドで読む（DuckDB は 1.9 GB で、静的サイトには置けない）。
- 出すものは「落下点の分布（平均・50/90/95 % 楕円・ヒートマップ・安全判定）」と
  「平均の軌道」。毎時比較と最適化は対象外。
- 計算は「層ごとの風の統計を足し合わせ、層どうしの相関を実際の散らばりで合わせる」方式。

## 計算の方法

入力: 打ち上げの緯度・経度・高度、日時、上昇速度 $a$、破裂高度 $z_b$、降下速度（海面換算）$d$。

1. **時期と格子点**: 日時（UTC）を JST に直し、月と半月ビン（1–15 日が前半、16 日以降が後半）を
   決める。年は使わない。打ち上げ地点の最寄り格子点を `nearest_cell(lat, lon)` で引く。
2. **層ごとの滞在時間 $T_k$**: その格子点・時期の 38 気圧面の平均高度
   （`fact_wind.alt_geom_mean_m`）で層を区切る（隣の面との中点が境界）。上昇は $a$、降下は
   空気の密度で変わる速さ $d\sqrt{\rho_0/\rho(z)}$（`bfps.core.atmosphere` の ISA）で通る。
   打ち上げ高度より下と破裂高度より上は 0。これは DuckDB を作ったときの式と同じ。
3. **平均の流され方**: $\bar{E} = \sum_k T_k \bar{u}_k$、$\bar{N} = \sum_k T_k \bar{v}_k$。
4. **散らばり**: 層 $k$ の風ベクトルの共分散行列
   $\Sigma_k = \begin{pmatrix} \sigma_{u,k}^2 & c_k \\ c_k & \sigma_{v,k}^2 \end{pmatrix}$
   （`u_var`, `uv_cov`, `v_var`）の対称な平方根を $L_k$ とし、層の風を
   $w_k = \bar{w}_k + L_k z_k$（$z_k$ は標準正規、層どうしの相関は $\mathrm{corr}(z_k, z_l) = \rho I$）
   と置くと、落下点の共分散は
   $$\Sigma = (1-\rho)\sum_k T_k^2 \Sigma_k + \rho\, M M^\top,\qquad M = \sum_k T_k L_k$$
   になる。$\Sigma_k$ が対角なら東西成分は
   $(1-\rho)\sum_k T_k^2\sigma_{u,k}^2 + \rho(\sum_k T_k\sigma_{u,k})^2$ に戻る。
5. **$\rho$ の決め方**: 同じ格子点・時期の `fact_drift`（標準の飛行: 上昇 5 m/s・破裂 30 km・
   降下 6 m/s での実際の落下点の分散 `east_var_m2`, `north_var_m2`）を再現するように、
   標準の飛行の $T_k$ で $\Sigma_{EE}(\rho)$ と $\Sigma_{NN}(\rho)$ をそれぞれ $\rho$ について解き
   （どちらも $\rho$ の 1 次式）、2 つの平均を 0〜1 に収める。その $\rho$ をフォームの飛行条件の
   $T_k$ にそのまま使う。
6. **標本**: 平均 $(\bar{E},\bar{N})$、共分散 $\Sigma$ の 2 次元正規分布から $n$ 点（既定 500、
   最大 2000、乱数の種つき）を引き、緯度経度に直して返す。
7. **平均の軌道**: 30 秒きざみで上昇・降下させ、その時点の位置の最寄り格子点・その高さの層の
   平均風で進める。終点は 3. の平均落下点と一致しない（空間変化を入れるため）ので、
   地図には両方を出す。

### 確かめたこと（2026-10-12）

日本全国から 60 格子点 × 4 時期を抜き出し、標準の飛行で計算した:

- 平均の東向き移動と飛行時間は `fact_drift` と一致した（比 1.000）。
- 解いた $\rho$ は東西 0.34–0.63、南北 0.33–0.62（5–95 %）で、両方向がほぼ同じ値になった。

## API

`POST /api/climatology/predict`

リクエスト（JSON）:

| 名前 | 型 | 説明 |
|---|---|---|
| launch_latitude, launch_longitude | float | 打ち上げ地点 |
| launch_altitude | float | m、既定 0 |
| launch_datetime | datetime | UTC |
| ascent_rate | float | m/s、0 < x ≤ 15 |
| burst_altitude | float | m、1000 < x ≤ 45000 |
| descent_rate | float | m/s（海面換算）、0 < x ≤ 30 |
| n_samples | int | 10–2000、既定 500 |
| seed | int \| null | 既定 42 |

レスポンス:

| 名前 | 説明 |
|---|---|
| timebin | `{month, bin, label}`（例 "1月前半"）と期間 "2016–2025" |
| cell | 使った格子点の緯度経度と、打ち上げ地点からの距離 km |
| mean_landing | `{latitude, longitude}` |
| covariance_m2 | `[[EE, EN], [EN, NN]]` |
| rho | 使った層間の相関 |
| samples | `[[lat, lon], ...]` |
| trajectory | `[{latitude, longitude, altitude, time_s}]`（平均の軌道） |
| flight_time_s | 飛行時間 |
| warnings | 文字列の配列 |

エラー:

- DuckDB が無い: 503「統計データベースが見つかりません」
- 範囲外（最寄り格子点が 60 km より遠い）: 422
- 破裂高度が最上層（3 hPa、約 40 km）より上: 計算はするが warnings に入れる

## バックエンドの構成

```
backend/bfps/climatology/
  store.py       DuckDB を読み取り専用で開き、1 つの接続を使い回す。
                 パスは環境変数 BFPS_CLIMATOLOGY_DB（既定 ../v2/jra3q_japan_wind_2016-2025_v2.duckdb）
                 格子点・時期の層データ（38 面）と fact_drift の 1 行を引く関数
  model.py       層の滞在時間、平均、共分散、ρ の解、標本（純粋な関数。DuckDB に依らない）
  trajectory.py  平均の軌道（store から格子点の層データを引いて積分）
backend/bfps/api/routes_climatology.py
backend/bfps/models/schemas.py に ClimatologyRequest / ClimatologyResponse を追加
```

`duckdb` を backend の依存に足す。

## フロントエンドの変更

- `src/hooks/useRunPrediction.ts` の `validateLaunchTime()` を
  `classifyLaunchTime()` に変え、`"forecast" | "climatology" | {error}` を返す。
  +7 日より先は `"climatology"`、−12 時間より前はこれまでどおりエラー。
- `src/api/climatology.ts`（新規）: `requestClimatology(req)` で上の API を呼ぶ。
  `VITE_API_BASE` が無ければ「統計モードにはバックエンドが必要です」というエラー。
- 単発の実行とモンテカルロの実行は、`"climatology"` のとき Tawhiri の代わりに
  `requestClimatology` を呼び、結果を今の型に直して `resultsStore` に入れる。
  - 平均の軌道 → `Flight`（`singleFlight` / `mcCentral`）
  - 標本 → モンテカルロの落下点（`mcSamples`）。統計は既存の `computeLandingStats`、
    安全判定は既存の `classify()` をそのまま使う。
  - モンテカルロのパネルで指定する上昇速度などのばらつきは、統計モードでは使わない
    （風のばらつきで散らばりを出すため）。パネルにその旨を表示する。
- `resultsStore` に `mode: "forecast" | "climatology"` と `climatologyInfo`（時期・格子点・ρ・warnings）を持つ。
- `components/ScenarioInfo.tsx` の上に帯を出す:
  「統計モード（気候値・1月前半、2016–2025 年）— 予報ではありません」
- 毎時モードと最適化はこれまでどおり（予報窓の外の時刻は飛ばす）。

## テスト

バックエンド（pytest）:

- 合成の小さな DuckDB をテスト中に作る（一定の風、既知の分散）。
  - 平均落下点が手計算と一致する。
  - 既知の $\rho$ で `fact_drift` の分散を作り、解いた $\rho$ が元に戻る。
  - 標本の平均・共分散が指定値に近い（乱数の種固定）。
  - API: 正常、DB 無しで 503、範囲外で 422。
- 実データ（`v2/...duckdb` がある時だけ。無ければ skip）:
  - 標準の飛行で、平均と分散が `fact_drift` と一致する。

フロントエンド（vitest）:

- `classifyLaunchTime()` の 3 通り（境界の値を含む）。
- API の応答を `Flight` と落下点の配列に直す関数。

## 範囲外

- 本番のサーバー（Cloud Run など）の用意。今回は `npm run dev` でバックエンドも起動して使う。
- 毎時モード・最適化・感度解析の統計モード対応。
- 浮遊（float）プロファイル。

## main の後片付け

研究の作業は `research/wind-climatology` ブランチに移した。main に残っている
大きなファイル（DuckDB、アーカイブ、動画、キャッシュ）が未追跡として出ないよう、
ルートの `.gitignore` に `research/`, `slide/`, `blog/`, `video/`, `v2/` を足す。
バックエンドは DuckDB をこの `v2/` の場所から読む（パスは環境変数で変えられる）。
