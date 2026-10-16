# N05 既存飛行シミュレーター接続・性能検証報告

作成：2026-10-13 JST。対象：ddd3h/Falling-position-simulator2026、dev/balloon-analysis-app、iwata_dir。

## 結論と完了境界

**元の計算エンジンを変更せず、緯度・経度だけを変えたconfigを逐次渡す独立アダプターを作成した。元エンジンのimportと入力検査、モック単体・HTTPテストは成功。実GFS飛行・着地成功・実性能・実Balloon Lab API実行は未検証。**

N05の構造確認は完了したが、実データによる受入検証は残る。N06以降の距離計算・探索・UI・ガス連携は実装していない。N01〜N04、本番コード、API、GFS処理、分散処理を変更していない。

## 1. ブランチ・コミット

- ローカルbranch：dev/balloon-analysis-app。
- ローカルHEAD：`fbb1cc76c112d8c495d2044604b330f1c0f5c8d6`。
- 今回の `git ls-remote origin refs/heads/dev/balloon-analysis-app` 応答も同じSHA。
- 前回報告書と一致。今回の接続に影響するコミット差分はない。
- 作業開始・終了時のgit statusは変更なし。N05は既存リポジトリ外に作成。
- 前回報告書 `Balloon_Target_Landing_Search_Research.md` の冒頭・実装根拠を参照し、今回のAPI/結果契約を実コードで確認。

## 2. 実装したもの

| 実装 | 動作・境界 |
|---|---|
| EngineBinding | ユーザーのiwata_dirをimport対象に追加。コピーしたエンジンは使わない。実際のimport元と固定commitを検査 |
| change_location | deepcopyしlaunch.latitude_deg/longitude_degだけ変更。UTC・高度・機体・数値設定は保持 |
| run_loaded | 元validate_configを使用し、元simulateへ引き渡す。試験用DIは単体テストだけで利用 |
| extract_landing | landedかつcompleteなsummary.landingだけ採用。stopped末尾の軌道は採用しない |
| run_case.py | 保存GFSを1回読み単一ケース。元結果dictを内包した追跡可能JSON。元入力/気象/ソースのhash記録 |
| benchmark.py | 承認済み座標リストを1/10/50件逐次実行。場ロード1回と毎回ロードを比較。自動座標生成なし |
| api_probe.py | デフォルト通信なしの要求準備。任意の隔離loopbackサーバーへ最大1POST。要求を先に保存。自動再送なし |
| tests | モック、loopback HTTPモック、実GFS提供時だけの統合テスト |

strict_jsonは重複キー、NaN/Infinity、1e999の非有限値を拒否。座標のbool・文字列・無限大・範囲外を拒否。他の物理入力は独自実装せず元validatorに任せる。

出力ファイルは新規作成だけ。run_case/benchmarkは既存リポジトリ内への出力を拒否し、元ソース・入力・場が変わっていないか確認。Pythonのpycacheも元リポジトリへ作成しない。N05結果ファイルは独立した検証記録であり、既存DBへ登録した正式なrun成果物と同一形式ではない。元simulateの数値結果を改変しない。

## 3. 実施したテスト

今回の最終実行：`python3 -B -m unittest discover -s tests -v`。

**27件のうち25件成功、実GFS統合2件スキップ。テスト全体0.516秒は試験コードの時間で、気球飛行1ケースの性能ではない。** 実行ログは evidence/unit-tests.txt。

| 検証 | 種類 | 結果 |
|---|---|---|
| 座標だけ変更、元config保持、ネストdeepcopy | モック単体 | 成功 |
| 無効座標・欠落config・元validator拒否時に計算しない | モック単体 | 成功 |
| モックsimulatorが入力を変更しても元入力保持 | モック単体 | 成功 |
| landed抽出、stoppedに着地点なし、不正結果拒否 | モック単体 | 成功 |
| 同じ入力・同じweather引数で結果一致 | **モック単体のみ** | 成功。実GFS再現性の証明ではない |
| TIME_OUT_OF_RANGEの途中停止とRuntimeErrorの計算例外を区別 | モック単体 | 成功 |
| 非有限JSON・重複キー拒否、既存出力上書き拒否 | 単体 | 成功 |
| 10件共有ロード1回、10件reload10回、地点不足、気象hash変化 | モックフロー | 成功。時間測定は実性能として採用しない |
| API要求形式、インスタンス不一致、POST通信失敗で再送なし | モック単体 | 成功 |
| localhostのHTTPモックへ1POST、JSONヘッダー、instanceヘッダー、状態/結果GET | **HTTPモック** | 成功。実Balloon API検証ではない |
| 元のtrajectory.pyを実際にimport | **元コード接続** | 成功。飛行を実行していない |
| 元validate_configが非正上昇速度を拒否 | **元入力検査** | INVALID_CONFIG確認。飛行を実行していない |
| 正規GFSでadapterと直接simulate・同条件再実行の全dict一致 | 実統合 | 入力未提供でスキップ |
| 正規GFSで別座標のadapterと直接simulateの全dict一致 | 実統合 | 入力未提供でスキップ |
| run_case/benchmark/api_probeのCLI help | CLI | すべて実行成功 |

evidence/engine-binding.json は元import先、commit、ソースSHA、環境、入力検査結果を含む。生成した気象bundle、模擬数値場、架空の計算時間は存在しない。モックテスト内の結果・座標はテストダブルとして明示している。

## 4. 測定環境・実測できない理由

ローカルLinux/Python環境。正確なplatform/python/packagesは evidence/engine-binding.jsonを参照。今回NumPy2.3.5、SciPy1.17.0で、元指定NumPy2.4.4/SciPy1.17.1と異なる。GeographicLibの配布メタデータは未導入（null）として記録。元trajectoryのimport/validatorは成功したが、元依存一式の導入成功とは言わない。

初回のimport確認時、環境記録で未導入GeographicLibのmetadata取得が失敗した。N05側のみ修正し、未導入をnullと記録するようにした。元依存や元ソースは変更していない。READMEでは正規の検証専用venvへ既存固定lockを導入する手順を示した。

公開取得物にはテスト参照 `references/flight_fixture/wakayama-weather.json.gz` と `examples/` が存在しない。使用権・対応条件を確認した正規GFS/configも未提供。架空の場や条件で測定を埋めない。

| 性能項目 | 今回の値 |
|---|---|
| 保存GFS読込時間 | 未測定 |
| 単一飛行simulate時間 | 未測定 |
| 10ケース逐次時間・着地/停止件数 | 未測定 |
| 50ケース逐次時間・着地/停止件数 | 未測定 |
| 同一ロード済みGFSの再利用速度改善 | 未測定。ロード回数の制御だけモック試験で確認 |
| APIの受付・待機・結果保存時間 | 未測定 |
| VPS 8GB/4vCPU/25GBのCPU/RSS | 未測定。VPSへ接続していない |

測定はREADME第7節のコマンドで実行可能。各バッチに読込秒、simulate秒、状態件数、元result、気象hashを記録する。共有と毎回ロードの比較順によるOSキャッシュ効果がある。実測後、中央値・停止理由・初回/後続・場サイズ・モデル・経路記録数を併記する。

## 5. API契約と確認範囲

既存 `backend/contracts.py:10–17` のRunRequest：

```text
client_request_id: 一意の要求ID
candidate_id: 候補ID
candidate_revision: 0以上の整数
label: 1..200文字
weather_source_id: サーバーが実際に登録した保存気象ID
config: 正規の飛行config
```

- POST `/api/v1/runs` →202、run_id/job_id/state/frozen_input_hash。
- GET `/api/v1/runs/{run_id}` →queued/running/completed等の実行状態・result_available。
- GET `/api/v1/runs/{run_id}/result` →元結果を含むenvelope。completedの科学結果もstoppedの場合がある。
- GET `/api/v1/run-requests?client_request_id=...` →受付不明時の照会。自動POST再送しない。
- `Content-Type: application/json`。`X-Balloon-Instance-Id`を健康確認のinstance_idで固定。
- 正常な要求であっても未知sourceは422、気象有効期間不足は422 WEATHER_WINDOW_UNSUPPORTED、満杯は429 QUEUE_FULL。
- サーバー1ワーカー・標準待機4を維持。同時送信しない。

**今回実Balloon Labサーバーを起動・送信していない。API契約とクライアントのHTTPモック試験まで。** localhost制限と明示フラグは本番誤接続を減らすが、localhost上の本番と検証サーバーを自動識別できない。運用者が別data_dir/ポートを確認する。登録済み保存sourceがなければそこで検証を止める。

READMEの検証サーバー起動例はユーザー側での手順であり、今回の起動成功結果ではない。N05から直接DB登録・気象取得・既存fixtureへの配置はしない。

## 6. 接続根拠（固定コミットのiwata_dir相対）

| 根拠 | ファイル・行・関数 |
|---|---|
| 独立した計算入口 | balloon_sim/flight/trajectory.py:18 simulate |
| landed/stoppedとsummary.landing | 同:246–255 |
| 元入力検証・UTC/座標/高度/モデル | balloon_sim/flight/config.py:51–157 validate_config |
| 保存場の通信なし読込 | balloon_sim/environment/storage.py:35–44 load_weather |
| GFS metadataの既存仕様 | balloon_sim/environment/gfs.py:171–180 decode_gfsのmetadata/bundle |
| 保存GFSアダプター | balloon_sim/environment/bundle.py:6–16 WeatherField |
| API要求 | backend/contracts.py:10–17 RunRequest |
| APIルート | backend/app.py:195–212 |
| instanceヘッダー・JSON指定 | backend/app.py:33–43 |
| 入力固定・気象期間・キュー | backend/application.py:321–361 submit |
| 1ワーカー・逐次実行 | 同:128,516–537 |
| 結果取得形式 | 同:426–437 get_result |
| APIワーカーの毎回ロード・hash | backend/worker.py:35–49 execute_run |
| 公開取得物にないfixture参照 | backend/tests/test_application.py:164 |

元APIは毎ケース場ロード・結果保存を行う。N05直接アダプターの共有ロード結果が、元API性能と同じだと主張しない。今回はアダプター側でGFS取得・補間・数値解法を再実装していない。

## 7. 未解決事項と引き継ぎ

1. 正規保存GFS、対応config、承認済み別地点を受領し、実GFS統合2テストを実行。
2. 元の固定依存環境を用意し1→10→50の順に計測。変更地点でもASL/地表の整合を確認。高度自動補正はN05にない。
3. 隔離APIの保存source準備経路を運用担当者と確認。空の検証DBへ未知sourceを送っても計算できない。
4. CPU/RSS、全result保持とJSON書出しの負荷は追加測定が必要。50件結果を巨大な実場で無制限に保持しない。
5. adapterではstoppedを保持し、input_error/weather_load_error/engine_exceptionと区別。N06はlandedだけを距離評価の入力にし、停止末尾を流用しない。
6. N06に渡すべきもの：元config/変更config、weather SHA/run、有効範囲、engine commit/source SHA、結果status、正常着地点、stop_reason、測定環境。今回距離計算はない。
7. ガス逆算式・探索アルゴリズム・条件ランキング・候補比較UI・既存アンサンブル接続は今回実装していない。

**受入の位置づけ**：単体テストと元コード接続の基礎は確認済み。実計算の成功・再現性と実性能の受入はデータ提供後。これらを混同してN06以降の性能前提を確定しない。
