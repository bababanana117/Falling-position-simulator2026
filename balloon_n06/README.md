# N06：保存済み着地点と目標点の距離比較

**飛行計算を実行せず、保存済みJSONだけを読みます。** 目標点と予想着地点のWGS84楕円体上の地表距離をmで計算し、比較可能な候補を近い順に出します。高さ・飛行経路長・安全性・着地確率は評価しません。

Balloon Lab本体やN05を起動する必要はありません。APIへの通信もありません。N05で生成したファイルは上書きしません。

## 1. ZIPを展開

ダウンロードしたZIPを、エクスプローラーの「すべて展開」で次の場所へ展開してください。

```text
C:\Users\ytrgr\BalloonN06
```

次のファイルがあることを確認してください。

```text
C:\Users\ytrgr\BalloonN06\n06-verification\compare.py
```

ユーザー名が異なる場合も、以下では `$env:USERPROFILE` が自分のユーザーフォルダーを指します。

## 2. 準備（PowerShellに順番にコピー）

```powershell
Set-Location "$env:USERPROFILE\BalloonN06\n06-verification"
py -3.12 --version
py -3.12 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
& $python -m pip install -r .\requirements.txt
```

必要な外部ライブラリは**GeographicLib 2.1だけ**。既存Balloon Labの宣言と同じ版です。N05・既存アプリの仮想環境やライブラリを更新しません。NumPy、SciPy、GFS、APIサーバーはN06の実行に不要です。

## 3. テスト

```powershell
& $python -B -m unittest discover -s tests -v
```

今回の検証では **34 tests / OK**。テスト内の座標と飛行結果は構造確認用のテストデータであり、実飛行結果ではありません。距離計算自体は実際のGeographicLib/WGS84を使用します。

## 4. N05の実結果2ファイルを指定

ユーザーから提示された場所を使います。実際のファイルが別の場所なら、次の2行だけ変更してください。

```powershell
$original = Join-Path $env:USERPROFILE 'BalloonN05-results\hokkaido-result.json'
$changed = Join-Path $env:USERPROFILE 'BalloonN05-results\hokkaido-changed.json'
Test-Path $original
Test-Path $changed
```

両方 `True` なら次へ。`False` の場合はエクスプローラーで実ファイルを探し、正しいパスを設定してください。Work側ではこの実JSONを受領しておらず、その数値や包装を実ファイルから確認したわけではありません。対応形式は元のN05実装と既存APIコードから確認しています。

次に比較対象をまとめたmanifest（入力ファイル一覧）を作成します。**元の結果は編集しません。**

```powershell
New-Item -ItemType Directory -Force .\inputs | Out-Null
$manifest = @{
    schema = 'n06.inputs/1'
    candidates = @(
        @{ candidate_id = 'hokkaido-original'; path = $original },
        @{ candidate_id = 'hokkaido-changed'; path = $changed }
    )
}
$manifest | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 .\inputs\manifest.json
```

`candidate_id` は比較時の識別子。N05の直接実行には元のrun_idがないので、その出力はnullです。manifestのIDは元結果に書き込みません。同じIDを複数回使っても、input_indexで入力順を区別します。N04とのID契約は今後確認します。

## 5. 目標点を独立したJSONへ保存

次は**操作確認用の目標座標例**です。実運用の希望着地点や安全な地点を意味しません。自分の希望座標へ数値を書き換えてください。緯度・経度は度です。

```powershell
@'
{
  "schema": "n06.target/1",
  "target_latitude_deg": 43.0,
  "target_longitude_deg": 141.5
}
'@ | Set-Content -Encoding UTF8 .\inputs\target-a.json
```

JSONでは座標を `"43.0"` のような文字列にしないでください。数値・有限値のみ。緯度−90〜90、経度−180〜180に対応し、NaN/Infinity/bool/空値は拒否します。UTF-8 BOM付きPowerShell出力にも対応します。

## 6. 比較を実行

```powershell
& $python -B .\compare.py --manifest .\inputs\manifest.json --target .\inputs\target-a.json --out .\outputs\comparison-a.json
```

ターミナルに候補名・距離m・入力順が出ます。詳しいJSONを見るには：

```powershell
Get-Content -Raw .\outputs\comparison-a.json
```

結果の `ranked` は距離順、`not_evaluated` は評価できなかった全候補、`best_candidate` は最も近い1候補です。目標から離れた候補も破棄しません。評価可能な着地がない場合、best_candidateはnullで、失敗理由は残ります。

同距離はmanifestの元の順序を維持します。表示は小数3桁ですが、並べ替えには丸め前のm値を使います。同じ距離の再現性は、同じ入力順・同じ依存版を前提とします。

## 7. 目標だけを変更して再評価

次も操作確認用の別目標例です。

```powershell
@'
{
  "schema": "n06.target/1",
  "target_latitude_deg": 43.1,
  "target_longitude_deg": 141.6
}
'@ | Set-Content -Encoding UTF8 .\inputs\target-b.json

& $python -B .\compare.py --manifest .\inputs\manifest.json --target .\inputs\target-b.json --out .\outputs\comparison-b.json
```

同じ2つの保存結果を読み、別目標への距離を計算するだけ。`simulate`、GFS取得、APIは一切呼びません。比較JSONの `flight_computations=0`, `api_calls=0` はこの構造を示す宣言であり、実フライト回数の測定値ではありません。

数値をCLIで直接指定することもできます：

```powershell
& $python -B .\compare.py --manifest .\inputs\manifest.json --target-latitude-deg 43.0 --target-longitude-deg 141.5 --out .\outputs\comparison-cli.json
```

目標JSONとCLI座標は同時指定しないでください。同じ出力名が既にある場合は拒否します。再実行時は新しい出力名を指定してください。既存Gitリポジトリ内への出力も拒否します。

## 8. 元ファイルが変わっていないことを確認（任意）

評価前と評価後に以下を実行し、Hashが同じことを確認できます。

```powershell
Get-FileHash -Algorithm SHA256 $original
Get-FileHash -Algorithm SHA256 $changed
```

比較出力の各候補にもsource_path/source_sha256を記録します。APIからのrun_idがある場合はそれも保持します。

## 9. 対応している保存形式

詳細は `Result_Formats.md` を参照。入力は**単一ケース**の保存結果です。

- N05 `run_case.py` の直接実行JSON：provenance/state/result。
- N05 `api_probe.py --execute` の保存JSON：mode=isolated_api_single、run、envelope.result。
- 既存GET `/api/v1/runs/{id}/result` のJSON：run_id/kind=single_run/result。
- 元exportの `result.json`：schema=balloon.flight.result/1。
- 既存GET `/api/v1/runs/{id}` のジョブ情報だけ：着地点の結果ではないため距離null。

APIジョブ情報がcompletedでも、それだけで正常着地とは判断しません。保存API結果のrun_idとジョブのrun_idが矛盾すると拒否します。stoppedは、末尾のrecordsやN05包装のlandingに座標があっても**距離を計算しません**。

N05の `benchmark.json`、API要求プレビュー、アンサンブル、任意のresult包みは未対応です。未知形式から座標を推測して拾いません。N05測定データを使いたい場合は単一ケースの `run_case.py` 出力を使ってください。N06から飛行を新規実行することはありません。

## 10. エラーの読み方

| error.code | 意味 |
|---|---|
| FLIGHT_STOPPED | 途中停止。着地点として評価しない。stop_reasonも確認 |
| NO_SAVED_FLIGHT_RESULT | ジョブ情報/エラー記録のみで科学結果なし |
| MISSING_LANDING | landedと書かれているがsummary.landingなし |
| INVALID_COORDINATE | 座標の型・範囲・有限性が不正 |
| STATUS_CONFLICT / WRAPPER_STATUS_CONFLICT | status/complete/包装が矛盾 |
| IDENTITY_MISMATCH / JOB_RESULT_CONFLICT | APIジョブと結果のID・状態が矛盾 |
| UNSUPPORTED_FORMAT / UNSUPPORTED_FLIGHT_SCHEMA | 未対応形式。推測して読まない |
| INVALID_JSON | JSON破損、重複キー、非有限値など |
| INPUT_FILE_ERROR | ファイルがない/読み込めない |
| FILE_SIZE_LIMIT | 単一JSONが64MiBを超える |
| OUTPUT_EXISTS | 出力名が既にある。別名にする |

候補1つが読めなくても他候補の比較は継続し、評価不能一覧に残します。目標・manifest全体が不正ならCLI終了コード2。比較JSON生成成功は0ですが、全候補評価不能でも0なのでcountsとnot_evaluatedを確認してください。

## 11. 将来のプログラム接続（今回UIなし）

Pythonの `load_candidates()` で結果を共通形式に読み込んだ後、`evaluate_candidates(rows, target)` に別目標を渡せます。目標変更のたびに飛行計算やファイル読込をする必要はありません。CLIは起動ごとにファイルを読みますが、再シミュレーションはしません。

N07の一括探索、自動最適化、地図、ガス、落下分散、安全判定はN06に含まれません。
