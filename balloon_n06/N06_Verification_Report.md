# N06 距離評価・候補比較の検証報告

確認日：2026-10-13 JST。作成範囲：独立N06フォルダーのみ。

## 実装・確認結果

**WGS84楕円体測地距離、明示的な保存結果アダプター、距離順の安定比較、目標変更だけの再評価を実装。34件の自動テスト成功。既存飛行・GFS・API・UI・分散は変更せず、今回simulate/APIを呼んでいない。**

GeographicLib2.1をN06専用の独立した依存保存先へ導入。既存環境の依存変更はしていない。Work実行はLinux/Python環境であり、Windows/PowerShell自体は未実行。READMEはWindowsユーザー向けに作成。

ブランチdev/balloon-analysis-app、ローカルとリモートHEADとも `fbb1cc76c112d8c495d2044604b330f1c0f5c8d6`。前回から差分なし。終了時のgit status/diffは変更なし。証拠はevidence/repository-integrity.json。

## 前提の更新：N05のユーザー実測

以下は**今回ユーザーが提示したWindowsローカル実測の報告**。Workでの再測定ではなく、対応する実JSON・実ログも今回未受領。

- Python3.12.10、北海道保存GFS、元simulateの呼出し成功。
- 単一ケースlanded、放球経度141.5→141.6に変更したケースもlanded。
- 10件20.83s・10着地、50件108.77s・50着地。同じ保存GFSを利用。
- 隔離API8768でcompleted/landed/complete=true。

前回の「Work側N05実GFS未検証」と矛盾しない。ユーザー環境では実行確認済みという追加情報。N06で速度を測り直したり、同じ値をWork性能として記録したりしていない。

## テスト

`PYTHONPATH=<独立GeographicLib保存先> python3 -B -m unittest discover -s tests -v`。

最終ログ：**34件成功、0失敗。全体0.075秒はテスト所要時間で、実データ比較の性能測定ではない。**

| 要求 | 確認 |
|---|---|
| 同一座標0m | 成功 |
| 既知距離 | WGS84赤道1度=111319.49079327357mと一致 |
| 北海道側 | 43,141.5→43.1,141.6をWGS84参照計算と照合 |
| 日付変更線 | 赤道179.9→−179.9の短い経路22263.898158653446mと一致 |
| 不正座標 | 文字列/bool/NaN/Inf/範囲外/巨大整数を拒否 |
| landed抽出 | N05直接、API、N05 API包装、raw resultで成功 |
| stopped除外 | records末尾・包装landing・矛盾するsummaryに座標があっても評価しない |
| 不正結果 | schema・complete・status・ID・job state矛盾を拒否 |
| JSON破損 | 重複キー・非有限値・UTF-8不正を拒否 |
| 複数比較 | 距離昇順＋評価不能別一覧、全候補保持 |
| 同距離 | 丸めず元入力順で安定整列 |
| 目標変更 | 同じ正規化済み結果を再利用し距離・順位だけ再評価 |
| 元結果不変 | deepcopy/元dict同一性・入力ファイルbytes保持 |
| 飛行/API呼出しゼロ | engine/backend import禁止・socket禁止下で正規化/目標変更評価成功 |
| CLI | 一時ファイルで結果生成・元ファイル保持・出力上書き拒否 |

テストの飛行resultは**包装・座標のテストダブル**。実シミュレーション結果ではない。距離計算はモックではなく実GeographicLib/WGS84。実北海道JSONをWorkで評価したとは主張しない。

## 既存契約の根拠

- `iwata_dir/balloon_sim/flight/trajectory.py:246–255`：schema/status/complete/summary.landing。
- `iwata_dir/backend/application.py:390–417`：job実行状態・run ID。
- 同 `426–437`：API結果envelopeとresult。
- N05 `run_case.py`、`n05_adapter.py:run_loaded`、`api_probe.py:Client.once/main`：直接結果/API結果の独立包装。

N06は既存moduleをimportせず、契約上の保存JSONを読む。raw result.jsonの数値を更新せず、距離評価を別成果物へ出す。詳細形式はResult_Formats.md。

## 未解決事項・N07引き継ぎ

1. ユーザー実JSONの評価はREADMEの2ファイル手順で実施。包装形式に差異があれば構造サンプルの確認が必要。
2. N07には正規化結果、candidate_id、元run_id/input_index、source hash、独立target、distance_definition、評価不能理由を渡す。N06の比較だけで飛行を再実行しない。
3. N04地図ピンとの接続、候補IDの正式な対応・重複政策、目標保存先は今後確認。UIは未実装。
4. 1000ファイル上限と単一64MiB上限は本PoCの読込制約。大量軌道JSONの読込・メモリ性能は未測定。地図操作ごとの再評価では正規化済み行を再利用する。
5. WGS84距離は地表の位置関係であり、安全性・飛行実現性・予報信頼度・到達保証ではない。N07でも停止結果は距離順位へ入れない。
6. アンサンブル・N05測定バッチ・未知包装は未対応。必要時に個別の契約を確認し、勝手に末尾や平均座標を着地点として採用しない。
7. API保存成果物の改ざん検知・正式DBとの再検証はN06の役割外。ファイルSHAを記録するが、正式サーバーの検査を代替しない。
8. push/deployなし。目標最適化・格子探索・安全判定・ガス・分散なし。N07へ自動的に着手しない。

**完了判断**：距離計算・保存形式変換・候補整列のN06機能はテスト済み。ユーザー実データでのローカル受入確認は残る。Windows実行・現場安全性・実飛行精度をWork試験成功で保証しない。
