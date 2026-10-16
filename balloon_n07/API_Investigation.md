# N07実装前API調査と設計

2026-10-13 JST。dev/balloon-analysis-app。ローカルbranch/HEAD/リモートHEAD確認：fbb1cc76c112d8c495d2044604b330f1c0f5c8d6。開始時git status空。前回との差分なし。

## 確認した既存契約

| 項目 | 実コード（iwata_dir相対） | 確認事項 |
|---|---|---|
| 要求 | backend/contracts.py:10–17 | client_request_id,candidate_id,candidate_revision,label,weather_source_id,configのみ。独自search_idを足さない |
| 受付 | backend/app.py:195–212 / application.py:321–361 | POST runs→202、run_id/job_id/state/frozen_input_hash |
| 冪等性 | application.py:328–332 / storage.py:63–69 | 同じrequest ID/本文は元受付。同ID/別本文409。registryにUNIQUE制約 |
| 受付照会 | application.py:418–424 / app.py:203–205 | GET run-requests?client_request_id。未発見404は照会時点のみ |
| 状態と結果 | application.py:390–437 | queued/running/completed/failed/cancelled/interrupted等。completedと科学landed/stoppedは別 |
| エラー | app.py:33–47 | JSON error.code/message。X-Balloon-Instance-Id、Content-Type application/json |
| 計算上限 | application.py:47,128,355–357,516–537 | 実計算1、標準待機4、QUEUE_FULL 429。future.resultにN07用timeoutはない |
| 再起動 | application.py:101–128 | 同registryのinstance_idを保持。既存結果復旧後、queued/runningをinterrupted。自動再送しない |
| GFS識別 | application.py:163–204,269–272 / weather/service.py:434–444 | ID,SHA256,bytes,run UTC,valid times,bounds,metadata。保存fixtureとacquired_gfsで付随フィールドは異なる |
| 気象検査 | application.py:334–354 / worker.py:35–49 | source登録情報、投入時file SHA、worker前後SHA。GET weather-sources自体は毎回実ファイルを再hashしない |
| 完全結果保存 | storage.py:105–149 / application.py:426–437 | APIは結果ファイル＋manifest/hashを検査して返す。再起動後参照可。ただし削除・ディスク故障・保存期間のサービス保証なし |
| 科学結果 | balloon_sim/flight/trajectory.py:246–255 | schema flight.result/1、landed/stopped、complete、summary.landing。停止末尾を着地点としない |
| 実装同一性 | worker.py:17–32 | run spec/result source_snapshotにファイルhash・数値環境。healthには現在のfingerprintを返すAPIがない |

## 実装前方針

- 独立SQLiteのトランザクションとsynchronous=FULLで状態と送信意図を確定。実行者はOSファイルロックで保存先全体につき1つ。
- POST直前に全文とrequest IDを保存。通信切断・クラッシュ後は同IDのGET照会だけ。404でも自動再POSTしない。
- APIの冪等受付は同一registryに依存する。削除/新DB/ID変更/ディスク故障を跨ぐExactly-onceは保証しない。
- source IDだけでなくSHA/有効時刻/領域/元metadataを固定し、各送信・再開で照合。現行GETは実ファイル同一性の証明ではないため、accepted spec/resultも照合。気象変更/共通障害は停止。
- 最初のaccepted runからsource_snapshotを固定。その後は同じsnapshotのrun/resultだけ受理。**先に現在のsource hashをGETで保証する機能はない**ので、異なる実装でAPIが計算を始める可能性を完全には防げない。検出時は停止・再利用しない。
- 1〜50の地点を決定的farthest-first（最遠を順に埋める）で処理。WGS84距離。海抜高度は既存の幾何学的ASL mとして明示。測量/標高基準変換を新規追加しない。
- N06の既存正規化/距離コードを無改変で同梱し、元ファイルhashを記録。目標変更は保存着地点の再評価だけ。
- 全結果をAPI参照＋独立JSON保存。原子的rename、内容hash、SQLite参照。クラッシュ後の未参照blobは保持し、再送で修復しない。
- 通常再開は未計算と既受付ジョブの照合のみ。failedの明示retryは別IDの新attempt、履歴保持。stopped/invalid/unknownはretry対象外。

## 利用可能・不足

n05-verification、n06-verificationの作成済みローカル成果物を読み確認。ユーザー指定のballoon_n04/05/06という名前の本番統合物があるとは仮定しない。N04コードは未確認なので新しい受渡しJSON契約だけ定義。Windows実GFS/50地点受入はユーザー環境での未実施試験として残る。Workでは既存fixtureが不足し、実APIは起動・送信せずモックAPIで検証する。
