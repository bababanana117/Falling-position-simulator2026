# Balloon Lab N07：有限地点の逐次探索PoC

**N07は既存アプリと別フォルダー・別保存先で動く管理ツールです。既存APIへ1件ずつ計算を依頼し、状態・全結果・距離順位を保存します。** 位置と海抜高度以外は固定。日時/ガス最適化、地図、安全判定はありません。

**Workの自動テストだけではN07完了ではありません。最後にWindows実GFS・50地点・復旧の受入試験が必要です。**

## ファイルの役割

| ファイル | 初心者向け説明 |
|---|---|
| cli.py | PowerShellから使う入口 |
| manager.py | 1件ずつ依頼し、停止・再開・結果保存を管理 |
| core.py | 入力検査、地点順序、SQLite保存 |
| api.py | 既存APIとの通信。自動POST再送なし |
| n06_distance.py | 作成済みN06のコードを無変更で同梱。WGS84距離 |
| examples/ | 入力形式の例。実条件・実高度の推奨ではない |
| tests/、evidence/ | 自動テストとWorkの検証証拠 |
| API_Investigation.md | 実装前に確認した既存APIの契約と保証の限界 |
| State_and_Storage.md | 状態、履歴、GFS固定、保存・再利用の仕様 |
| N07_Verification_Report.md | 成功/未実施/最終受入条件 |
| N08_Handoff.md | 次の担当に渡すデータと課題 |

接続解放の修正版です。WindowsのWinError 32への対応・既存環境の更新手順は `SQLite_Fix_Report.md` を参照してください。

## 1. 展開と専用Python環境

ZIPを `C:\Users\ytrgr\BalloonN07` へ「すべて展開」。次のファイルがある想定：
`C:\Users\ytrgr\BalloonN07\balloon_n07\cli.py`。

```powershell
Set-Location "$env:USERPROFILE\BalloonN07\balloon_n07"
py -3.12 --version
py -3.12 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
& $python -m pip install -r .\requirements.txt
```

N07依存はGeographicLib2.1のみ。既存API/エンジンのvenvは更新しない。N07は元 `flight.config.validate_config` を入力検査のためだけにimportします。simulateを直接import/実行しません。

## 2. モックテスト

```powershell
& $python -B -m unittest discover -s tests -v
```

Workでは56件成功。元validatorの接続確認テストはパス未指定なら1件skippedなので、通常は55成功/1skip。モックには架空の着地点・気象識別を使い、実GFS性能や着地精度の証明にはしません。HTTPモックは一時localhostだけ。

任意：元validatorのテストも行うには、本体の**実際のiwata_dir**を指定：

```powershell
$engine = Read-Host '既存Balloon Labのiwata_dirの絶対パス'
$env:N07_VALIDATOR_ROOT = $engine
& $python -B -m unittest discover -s tests -v
```

本体は固定コミットfbb1cc76c112d8c495d2044604b330f1c0f5c8d6が必要。既存作業コピーを勝手にcheckoutしない。変わっている場合は影響を確認してから再監査する。

## 3. 動作確認済みの隔離APIを起動

N05で使用した**検証専用**ポート8768/保存先を使ってください。通常環境のDB、fixture、設定を上書きしません。N07からGFSを取得・登録する機能はありません。

```powershell
$base = 'http://127.0.0.1:8768'
Invoke-RestMethod "$base/api/v1/health"
$sources = Invoke-RestMethod "$base/api/v1/weather-sources"
$sources.sources | Select-Object id,kind,sha256,run_utc
```

workers=1、flight_execution.available=true、対象の保存GFS sourceが実際にあることを確認。ここで接続できなければ、その先へ進まないでください。API起動はN05の動作済み手順を利用します。N07は既存FastAPIを別実装せず、本番APIへ接続しません。

## 4. 共通条件をN05の実結果から用意

N05直接結果の `result.config` を取り出します。元ファイルは読み取りのみ。

```powershell
New-Item -ItemType Directory -Force .\inputs | Out-Null
$n05path = Join-Path $env:USERPROFILE 'BalloonN05-results\hokkaido-result.json'
$n05 = Get-Content -Raw $n05path | ConvertFrom-Json
$config = $n05.result.config
if ($null -eq $config) { throw 'N05 result.configがありません。包装形式を確認してください。' }
$sourceId = Read-Host 'APIの一覧に実際にある北海道GFS source ID'
$source = $sources.sources | Where-Object { $_.id -eq $sourceId }
if ($null -eq $source) { throw 'source IDが一覧にありません。' }
@{ schema='n07.common/1'; weather_source_id=$sourceId; config=$config } |
    ConvertTo-Json -Depth 100 | Set-Content -Encoding UTF8 .\inputs\common.json
```

同じGFSであることはAPIのSHA・metadataから固定し、元N05結果のweather.sha256とも利用者が照合してください。N05の結果が別のGFSなら、その違いを黙って混ぜないでください。N07はAPIが返したsourceをその探索の正本として固定します。

## 5. 候補3地点と目標を用意

`examples/candidates.json`は形式例。例の高度100mは実地の高度を確認した値ではありません。**入力高度は海面基準の幾何学的ASL m**。GPS楕円体高、対地高度AGL、気圧高度をそのまま使わない。既存エンジンと高さの基準を確認してください。自動標高取得・高度補正はしません。

手動で候補JSONを作り、候補ごとに高度を確認する方法を推奨します。N04との直接統合はありません。次はN05位置を基準にした操作確認用の3地点作成例。N05で141.6度も動作したというユーザー報告を参考にしますが、3点それぞれの高さを実値として保証しません。

```powershell
$lat = [double]$config.launch.latitude_deg
$lon = [double]$config.launch.longitude_deg
# 各地点の海抜高度を確認して入力。空欄や文字ではなく数値m。
$textA = Read-Host 'Aの確認済み海抜高度ASL（m）。不明なら空欄'
$textB = Read-Host 'Bの確認済み海抜高度ASL（m）。不明なら空欄'
$textC = Read-Host 'Cの確認済み海抜高度ASL（m）。不明なら空欄'
$altA = if ([string]::IsNullOrWhiteSpace($textA)) { $null } else { [double]$textA }
$altB = if ([string]::IsNullOrWhiteSpace($textB)) { $null } else { [double]$textB }
$altC = if ([string]::IsNullOrWhiteSpace($textC)) { $null } else { [double]$textC }
@{
  schema='n07.candidates/1'; altitude_reference='geometric_ASL_m'
  candidates=@(
    @{candidate_id='A'; latitude_deg=$lat; longitude_deg=$lon; altitude_m=$altA},
    @{candidate_id='B'; latitude_deg=$lat; longitude_deg=($lon+0.05); altitude_m=$altB},
    @{candidate_id='C'; latitude_deg=$lat; longitude_deg=($lon+0.10); altitude_m=$altC}
  )
} | ConvertTo-Json -Depth 100 | Set-Content -Encoding UTF8 .\inputs\candidates-3.json
```

高度不明なら `altitude_m=null` とし、invalid_inputとして保存します。標準JSONの文字列座標や範囲外も地点単位でinvalid_input。JSON自体が破損/NaN/Infinityなら、ファイル全体が不正JSONとして事前停止します。ID欠落/重複は曖昧性を防ぐため探索全体を拒否。近接点は統合せず、全条件完全一致だけ結果を再利用します。

目標例（実運用希望点ではなく、編集が必要）：

```powershell
Copy-Item .\examples\target.json .\inputs\target.json
notepad .\inputs\target.json
```

座標を数値で編集し保存。targetはN06と同じ独立形式。距離は安全性・許可・実現性の判定ではありません。

## 6. 探索作成（この時点ではPOST計算なし）

N07保存先は既存APIの保存先と**必ず分けます**。SQLite DBファイル名もn07.sqlite3で独立。

```powershell
$store = Join-Path $env:USERPROFILE 'BalloonN07-state'
# $engineが未設定なら、手順2で設定してください。
$searchId = (& $python -B .\cli.py --store $store create --api $base --ack-isolated-api --engine-root $engine --common .\inputs\common.json --candidates .\inputs\candidates-3.json --target .\inputs\target.json).Trim()
$searchId
& $python -B .\cli.py --store $store status $searchId
```

CLIがエラーを出した場合はsearchIdを使わず、原因を確認。作成時に日時と最大飛行継続時間の全期間がGFSで支持されるか検査します。旧fixtureでも外挿しません。最大50、無効地点は実行順から除外。順序はWGS84で最も離れた2地点から始め、その後「選択済み集合からの最小距離」が最大の未選択点を追加。距離同値は入力順。開始時に固定保存し再開時に作り直さない。

## 7. 実行、進捗、通常中断

```powershell
& $python -B .\cli.py --store $store run $searchId --ack-isolated-api
```

1地点完了ごとにJSON進捗/暫定順位を表示。暫定1位は計算済みだけの比較。別PowerShellでstatusを確認できます。

```powershell
# 別PowerShell。変数を再設定してから。
Set-Location "$env:USERPROFILE\BalloonN07\balloon_n07"
$python = Join-Path $PWD '.venv\Scripts\python.exe'
$store = Join-Path $env:USERPROFILE 'BalloonN07-state'
$searchId = Read-Host '手順6で表示された探索ID'
& $python -B .\cli.py --store $store status $searchId
& $python -B .\cli.py --store $store pause $searchId
```

中断要求後は現在の1件の終了を待ってpausedになります。実行ターミナルのCtrl+Cも中断要求として扱います。**強制終了とCtrl+Cは別**。通信不能なら現在ケースを確定できないままpausedにし、次地点を送信しません。

再開：

```powershell
& $python -B .\cli.py --store $store resume $searchId --ack-isolated-api
```

landed/stopped/invalid/failedを未計算へ戻さず、既存activeのrun照会→残りpendingのみ。GFS/instance/version相違は停止。終端completedの通常再開は新POSTしません。

## 8. プログラム再起動と復旧

新しいPowerShellでも同じstore/searchIdでlist/status/resumeできます。

```powershell
& $python -B .\cli.py --store $store list
& $python -B .\cli.py --store $store detail $searchId
& $python -B .\cli.py --store $store resume $searchId --ack-isolated-api
```

sending/unknownは照会のみ。404でも自動再送しません。APIを再起動すると元APIはqueued/runningをinterruptedとする場合があります。N07はfailedとして履歴保持し、勝手に再計算しません。失敗再試行は次節の別操作。

**受付不明で照会404のままなら、初版には「絶対未受付と人が認定して同じ探索から再POSTする」操作はありません。** 不用意な重複を防ぐため保持・停止し、API台帳の確認を依頼してください。直接SQLiteを編集しない。新API DBへ接続して未知要求の安全性が回復したと扱わない。

## 9. 失敗地点だけ明示retry

```powershell
& $python -B .\cli.py --store $store retry $searchId --candidate A --ack-isolated-api
& $python -B .\cli.py --store $store resume $searchId --ack-isolated-api
```

選べるのはfailedだけ。stopped/invalid/unknown/実行中は不可。過去attemptは保持し、次の明示retryに新request IDを使う。無制限自動retryなし。入力・日時・GFSを変えるなら新しいcommon/candidatesを用意して手順6から別探索を作成します。

## 10. 完全結果と順位の確認

```powershell
& $python -B .\cli.py --store $store status $searchId
& $python -B .\cli.py --store $store verify $searchId
& $python -B .\cli.py --store $store result $searchId --candidate A
```

verifyは完全結果blobのSHA検査。resultはAPIへ接続せずN07保存物を読みます。全軌道records/eventsを含みます。APIジョブcompletedと科学landed/stoppedを区別。stoppedに距離は付けません。手順の結果表示はJSONなので、必要ならPowerShellの `| Set-Content -Encoding UTF8 <新規ファイル名>` で別途保存できます。

## 11. 目標だけ変更（飛行/APIなし）

```powershell
Copy-Item .\inputs\target.json .\inputs\target-b.json
notepad .\inputs\target-b.json
& $python -B .\cli.py --store $store target $searchId --file .\inputs\target-b.json
```

同じsearch IDで距離・順位だけ更新。目標とUTC評価時点・履歴を保存。日時/機体/GFS変更はこの操作を使わず別探索。

## 12. 50地点の最終受入

先に3地点・中断・再起動・別探索を確認。最後にN04または手動で用意した**確認済みASL高度付き50地点**を `inputs/candidates-50.json` に保存。形式は3地点と同じ。N07に自動格子生成・標高取得はありません。

```powershell
$search50 = (& $python -B .\cli.py --store $store create --api $base --ack-isolated-api --engine-root $engine --common .\inputs\common.json --candidates .\inputs\candidates-50.json --target .\inputs\target.json).Trim()
$timer = [System.Diagnostics.Stopwatch]::StartNew()
& $python -B .\cli.py --store $store run $search50 --ack-isolated-api
$timer.Stop()
$timer.Elapsed.TotalSeconds
& $python -B .\cli.py --store $store status $search50
& $python -B .\cli.py --store $store verify $search50
```

APIの受付・結果取得・N07保存を含む壁時計秒。途中中断/再開を含めた測定なら、累積実行区間と中断時間を別記録。Work/N05の速度から新しいN07時間を実測として埋めない。

合格：state=completed、total=50、processed=50、pending/sending/unknown/accepted/running=0、完全結果または理由付き終端記録が全件あり、landedのみWGS84順位、停止末尾距離なし。**50件全部landedは不要**。再利用があればPOST数は50未満になり得ます。detailのattemptsとreused_fromを照合して重複要求がなかったことを確認します。

## 13. 障害試験と記録

本番を壊して試さず、専用API/保存先で実施。

- N07強制終了：POST後のrun_idまたはrequest IDが保存された段階で終了→同storeで再開→照会して元runを使用。通信の送信境界をWindowsから正確に作る試験は別途手順調整が必要。Work側ではhook/実子プロセスクラッシュで確認済み。
- API停止/再起動：N07がpausedになること、復旧後に同じinstance/GFSを確認し、既存runを照会すること。APIの別DBへの切替はinstance不一致として拒否。
- GFS不一致：既存ファイルを改変しない。別GFSを登録した別検証API/保存先へ切り替えたときの拒否を確認。**GFS本体を上書きして試すことは禁止**。N07は元source ID/スナップショットを変更するコマンドを持たない。
- N07の固定条件不一致：元DBを手編集しない。WorkのコピーDBを用いた破損試験で確認済み。ユーザー側では別commonファイルから別探索を作り、旧探索が保持されることを確認。

提出すると判断しやすい記録：status/detail/verifyの出力、API health、source ID/SHA、実行秒、中断/再開の手順、attempt/request ID/run IDの対応。個人情報・キー・巨大軌道を無断公開しない。

初版の制約・受入未実施事項はN07_Verification_Report.mdに記載しています。
