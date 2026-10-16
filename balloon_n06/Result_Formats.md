# N06が受け付ける既存結果形式

確認コード：Balloon Lab固定コミット fbb1cc76c112d8c495d2044604b330f1c0f5c8d6、および今回作成済みN05コード。ユーザーのWindows実ファイルは未受領。

## 科学結果の共通部分

既存 `iwata_dir/balloon_sim/flight/trajectory.py:246–255`：

```text
schema = balloon.flight.result/1
status = landed または stopped
complete = true または false
config.launch.latitude_deg / longitude_deg
summary.landing.latitude_deg / longitude_deg（正常着地のみ）
stop_reason（途中停止の理由）
records（末尾を着地点に代用しない）
```

評価可能にはlanded、complete=true、stop_reasonなし、放球座標とsummary.landingの有効な座標が必要。元エンジンの物理config全体をN06が再検証するわけではない。N06は保存座標の意味を変更せず、ソースの科学精度・実飛行適合・暗号学的な正式run整合を保証しない。

## 明示的に対応する包装

| source_format | 判別・読込箇所 | ID・状態 |
|---|---|---|
| balloon_raw_result | トップschema=balloon.flight.result/1 | run_idなし。manifestでcandidate_id指定 |
| n05_direct_record | provenanceオブジェクト＋N05既知state＋result | scientific stateとresult.statusの一致必須。run_idは通常null |
| balloon_api_result | run_id＋kind=single_run＋result | run_id保持。ジョブ状態は付随しないのでjob_state=null |
| n05_api_record | mode=isolated_api_single＋envelope.result＋任意run | run.stateと科学statusを別保持。run IDが違う、または結果ありでjobが未完了/failedなら拒否 |
| balloon_api_job_only | run_id＋既知job state＋resultなし | completedでも評価しない。distance=null |

根拠：N05 `run_case.py:34–35`付近のwrite_new、`n05_adapter.py:run_loaded`、`api_probe.py:main/Client.once`。既存 `backend/application.py:390–417` のjob詳細と `426–437` のget_resultを分ける。GET結果にはkindがsingle_run/ensemble_trialの区別もある。N06は単一ケースのみ扱い、ensemble_trial包装は未対応として明示する。

## 共通候補行

```text
candidate_id（manifestの識別子）
run_id（API結果に存在する場合）
input_index（0始まりの元入力順）
source_path / source_sha256 / source_format
launch_latitude_deg / launch_longitude_deg
landing_latitude_deg / landing_longitude_deg
distance_to_target_m（評価不能ならnull）
flight_status（landed/stopped。ジョブのみならnull）
job_state（completed/failed等。直接結果には通常なし）
evaluable / error
```

rankedは距離・input_indexで安定整列しrankを追加。not_evaluatedは元入力順。元の結果JSON、入力識別子、全候補を破棄・編集しない。複数ファイルが同じrun_id/candidate_idを参照しても、各行のinput_index・source_pathで追跡する。正式なID照合・重複管理の政策はN07以降で決める。

目標は独立した `n06.target/1`：target_latitude_deg/target_longitude_deg。比較出力は `n06.comparison/1`：target、distance_definition、ranked、not_evaluated、best_candidate、counts、入力manifestのhash。

## 非対応・保守的な拒否

- N05測定バッチ全体、API要求プレビュー、アンサンブル集合、任意の深いresult包装。
- landedなのに着地点なし、座標が文字列/NaN/Infinity/範囲外、completeとの矛盾。
- 不正JSON、UTF-8以外、重複キー、64MiB超の単一ファイル。
- 存在しない元データから座標を推測すること、stopped末尾の着地扱い。

ジョブ情報だけなら、対応する科学結果を既存保存経路から別途受領する必要がある。N06はAPIへ自動アクセスしない。ユーザー実ファイルが説明と異なる場合は、個人情報・キーを除いた構造サンプルを確認してから新アダプターの必要性を判断する。
