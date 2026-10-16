# N05：既存飛行計算への独立接続・性能検証

**対象コミット：fbb1cc76c112d8c495d2044604b330f1c0f5c8d6**。新しい飛行エンジン、気象場、探索・距離計算・比較UI・ガス式は含みません。既存リポジトリとは別のフォルダーへ展開してください。ZIPにBalloon Labソースや実GFSは含まれません。

## 1. ファイル構成

| ファイル | 役割 |
|---|---|
| n05_adapter.py | 外部の元エンジンをimport。座標変更、検査、着地/停止区別、出典・hash記録 |
| run_case.py | 保存GFSで1ケースを実行し結果JSONへ保存 |
| benchmark.py | 1/10/50ケースの逐次測定。ロード済み場共有と毎回ロードを比較 |
| api_probe.py | 既存APIの要求準備、任意の隔離localhostへ1件送信・状態/結果取得 |
| tests/ | モック単体・HTTPテスト、入力提供時のみ動く実GFS統合テスト |
| N05_Verification_Report.md | 実施結果、未測定項目、接続根拠、引き継ぎ |
| evidence/ | 今回のテストログ、元エンジンimport/検査、リポジトリ状態 |

## 2. 最初に必要なもの

- Windows、Python **3.12**、Git。PowerShellで `py -3.12 --version` を確認。
- 指定コミットのリポジトリ。既存の作業コピーを勝手にcheckout・上書きしない。以下は新規クローンが必要な場合だけ行う。

```powershell
# パスは自分の環境に合わせる。N05フォルダーとリポジトリを分ける。
New-Item -ItemType Directory -Force C:\BalloonN05 | Out-Null
Set-Location C:\BalloonN05
git clone --branch dev/balloon-analysis-app https://github.com/ddd3h/Falling-position-simulator2026.git BalloonLab
# 新しく作った検証専用クローンだけを固定コミットにする。
git -C .\BalloonLab checkout --detach fbb1cc76c112d8c495d2044604b330f1c0f5c8d6
```

ZIPを `C:\BalloonN05\n05-verification` へ展開した想定：

```powershell
Set-Location C:\BalloonN05\n05-verification
py -3.12 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
$engine = 'C:\BalloonN05\BalloonLab\iwata_dir'
$env:PYTHONDONTWRITEBYTECODE = '1'
```

モックテスト・APIクライアントはPython標準ライブラリだけで動きます。実計算は**既存コードの依存**を使います。新しい依存更新は提案しません。

```powershell
# モックだけなら、このインストールは不要。
# 実GFSテストの前に、既存コードの固定依存を検証専用venvへ入れる。
& $python -m pip install -r "$engine\backend\requirements.lock"
```

既存宣言：Python>=3.12,<3.13、NumPy2.4.4、SciPy1.17.1、GeographicLib2.1、FastAPI0.116.2、Uvicorn0.35.0、ecCodes2.48.0など。取得できない固定版がある場合は停止し、勝手に最新へ置換しない。元コードの `backend/requirements.lock` が正本です。N05は依存を自動インストールしません。

## 3. テスト（実データなしで実行可能）

```powershell
& $python -B -m unittest discover -s tests -v
```

実GFS環境変数を指定しなければ、2件の実統合テストはskippedとなります。モック成功は実GFS成功ではありません。標準ライブラリHTTPテストは自分のPC内の一時モックサーバーだけへ接続します。外部API・本番APIへは接続しません。

## 4. 不足する実データを準備

作成者・運用担当者から次を受領してください。N05が架空データを生成することはありません。

1. **保存済み正規GFS bundle**：既存 `balloon_sim.environment.storage.load_weather()` が読めるJSON/gzip。`metadata.source`がGFSを示し、`metadata.run_utc`と有効時刻・空間・高度の支持範囲を含むもの。GRIB単体やOpen-Meteoの地上予報JSONは不可。
2. **対応する正規config JSON**：既存の `balloon.flight.config/1`。UTC、ASL高度、対応モデル・単位を確認。元の完成結果フォルダーの `input.json` は候補。ただし内容と気象の対応を運用担当者に確認。
3. **検証座標リスト**：選んだGFSの対応範囲に入る10/50地点。緯度経度だけ変えても放球高度は自動調整しないので、各地点のASL高度と地表の整合を確認。無効な地点は修正せず停止・エラーとして記録。

既存の保存 `provenance.json` に記載されたweather_bundleのパス/SHAを手掛かりに、同じ保存GFSを運用担当者から提供してもらう。存在しないテストfixtureを実データとして作り直さない。

ファイルは例として `C:\BalloonN05\inputs` に保存。**このZIPに、その実ファイルは含まれません。**

## 5. 単一ケースと座標変更

```powershell
$config = 'C:\BalloonN05\inputs\approved-config.json'
$weather = 'C:\BalloonN05\inputs\approved-weather.json.gz'

& $python -B .\run_case.py --engine-root $engine --config $config --weather $weather --out .\outputs\single-original.json
# 次の緯度経度は検証担当者が承認した別地点に置換。値を推奨していません。
$lat = Read-Host '承認済み検証地点の緯度（度）'
$lon = Read-Host '承認済み検証地点の経度（度）'
& $python -B .\run_case.py --engine-root $engine --config $config --weather $weather --latitude $lat --longitude $lon --out .\outputs\single-changed.json
```

`state=landed`だけ着地点を設定。`stopped`は正常に返された途中停止結果であり、最後の軌道位置を着地点へ変換しません。`input_error`、`weather_load_error`、`engine_exception`は別状態。停止時の元 `stop_reason.code` を保持します。終了コード0はlanded、2は停止・エラー。正常な途中停止でもCLI終了2となる仕様です。

結果JSONは元エンジンの `result` をそのまま内包し、正規化以外の物理値加工をしません。追加メタデータとして元入力・変更config・時刻・使用ファイルSHA・ソースSHA・ライブラリ版・実行秒を記録。出力は新規ファイルのみ。既存出力を上書きしません。エンジンのリポジトリ内への出力は拒否します。

## 6. 実GFS統合テスト

```powershell
$env:N05_ENGINE_ROOT = $engine
$env:N05_CONFIG = $config
$env:N05_WEATHER = $weather
$env:N05_TEST_LAT = $lat
$env:N05_TEST_LON = $lon
& $python -B -m unittest discover -s tests -v
```

元 `simulate` への直接呼出し、アダプター、同じアダプター再実行の **結果dict全体の厳密一致** を確認します。時刻測定メタデータは比較対象外。範囲不足でstoppedになった場合も同一性検証はできますが、実着地成功の証明ではありません。違う座標の統合テストも、承認座標を指定しない限りskippedです。

## 7. 1・10・50ケースの測定

`approved-sites.json`をユーザー側で準備。形式は以下。`LAT1`等の文字列は実際の数値へ置換してください。この説明は実座標・実入力ファイルではありません。

```text
[
  {"latitude_deg": LAT1, "longitude_deg": LON1},
  {"latitude_deg": LAT2, "longitude_deg": LON2}
]
```

地点数は最大測定件数以上必要。自動格子生成・探索はしません。同一地点を意図的に複数回含める場合は、繰り返し入力の再現性測定であることを記録してください。

```powershell
& $python -B .\benchmark.py --engine-root $engine --config $config --weather $weather --sites C:\BalloonN05\inputs\approved-sites.json --counts 1 10 50 --compare-reload --out .\outputs\benchmark.json
```

このコマンドは共有/毎回読込それぞれ1+10+50=61、合計**122ケースの逐次**実行。まず `--counts 1`、次に10、最後に50を別出力名で実行しても構いません。毎回ロード比較不要なら `--compare-reload` を外します。外部GFSを取得しません。各バッチ終了時に別名チェックポイントを残します。

- load_seconds：保存場の解凍・検査・構築。前後のファイルhash時間を含まない。
- simulate_seconds：元simulate呼出しの壁時計時間。元simulate内の検証は含む。
- validation_seconds：アダプター側の座標・元validator事前検証。
- batch_seconds：バッチ内のロード、hash、検証、計算、記録保持等。最終ファイル書出し・バッチ後のソース検査は含まない。
- sharedはバッチごとに1回ロード、reloadはケースごと。初回reloadはshared初回と同じロードを利用し、余分なロードをしない。
- 状態別件数を出力。`stopped`の内訳は各ケースのerror.codeで確認。

OSファイルキャッシュ、初回import、反復順、数値環境の影響があるので、1回の比率を普遍的な速度向上としません。この測定は直接関数方式であり、既存APIワーカーの毎回ロード・成果物保存・待機の総時間とは異なります。CPU/RSSの自動測定は今回未実装。全resultを保持するので50ケースのメモリ・ディスクを確認してください。

## 8. 既存API接続（任意・1件だけ）

今回は実Balloon Lab APIの疎通・飛行を実施していません。以下は再実行手順です。**自分専用の検証サーバーを別ポート・別data_dirで起動した場合だけ**送信してください。本番サーバーへ接続しないでください。

既存リポジトリ側の起動を使用し、設定ファイルを書き換えず、環境変数で保存先を分離する例：

```powershell
# 別のPowerShellで。新規検証専用サーバーだけを起動する。
$engine = 'C:\BalloonN05\BalloonLab\iwata_dir'
$python = 'C:\BalloonN05\n05-verification\.venv\Scripts\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:BALLOON_DATA_DIR = 'C:\BalloonN05\isolated-api-state'
$env:PYTHONPATH = $engine
Set-Location C:\BalloonN05\n05-verification
# この値は起動時だけこのプロセスに渡す。元のappや設定は変更しない。
& $python -B -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8768
```

**重要**：サーバーへGFS sourceを登録する既存正規経路・保存assetが必要です。裸bundleをN05側でDBへ書き込んだり、既存リポジトリのfixtureを上書きしたりしません。GET `/api/v1/weather-sources` に出てこないsource_idを推測して送信しないでください。入力不足ならAPI検証はそこで停止します。専用保存先が空ならsourcesが空になる可能性があります。

```powershell
# 元のN05ターミナルで。まずGETだけで確認。
Invoke-RestMethod http://127.0.0.1:8768/api/v1/health
Invoke-RestMethod http://127.0.0.1:8768/api/v1/weather-sources
$sourceId = Read-Host '検証サーバーが実際に返した保存気象source ID'

# デフォルトは要求JSON保存だけ。通信・計算なし。
& $python -B .\api_probe.py --config $config --source-id $sourceId --out .\outputs\api-request-preview.json

# 検証専用サーバーだと確認できた場合のみ、1件送信。
& $python -B .\api_probe.py --config $config --source-id $sourceId --execute --ack-isolated-server --out .\outputs\api-single.json
```

localhost限定、リダイレクト・プロキシ不使用、1POST、最大120秒の結果待機。待機期限はサーバー側の取消ではありません。timeoutは受付済みの可能性があるため自動再送しません。要求は `.intent.json` に送信前保存。http_rejected（422/429/5xx等）とcommunication_unknownを区別。429を無制限再試行しません。

通信不明時は、intentにある**同じrequest ID**をGETで照会：

```powershell
$requestId = Read-Host 'intentに保存されたclient_request_id'
$instanceId = Read-Host '結果に保存された検証サーバーinstance_id'
& $python -B .\api_probe.py --lookup --request-id $requestId --instance-id $instanceId --out .\outputs\api-lookup.json
```

404はその照会時点で未受付を意味し、元POST失敗確定の証明ではありません。N05は自動再送しません。API台帳のcompletedは処理完了であり、返る科学結果はlandedまたはstoppedです。

## 9. 制約と次の判断

- 現時点で実GFS飛行・実計算性能・実Balloon API実行は未検証。
- ZIPのモックテストにあるconfig・結果座標は、テストダブルの識別用。実気象・実飛行・推奨条件ではない。
- パッケージ版・原コードhashを保存。現在のホスト測定結果はVPS性能ではない。
- 同一commitの元コードをimportし、計算値を改変しない。別commitは再監査が必要として拒否。
- N06以降の距離評価・探索、UI比較、ガス連携は含まない。
