# N07検証報告

2026-10-13 JST。**N07のWindows実GFS・50地点の最終受入は未実施。初版完了とは判断しない。**

## SQLite接続解放の追補

Windowsで報告された49件中46件のWinError 32を確認。Storeの接続がwith終了時に閉じない不備を修正し、直接接続するテストもclosingで解放。既存49件＋新規7件をWorkで再試験した。修正内容・Windows再実行はSQLite_Fix_Report.md。修正後のWindows成功はまだ確認していない。

## 実施範囲と結果

- 指定branch/HEAD/remoteを確認。いずれもfbb1cc76c112d8c495d2044604b330f1c0f5c8d6、開始・終了git status空。
- 既存API調査と方針を先に保存/説明し、その後独立balloon_n07に実装。
- N05/n06-verificationの利用可能な実コードを確認。N04の名前だけから存在/互換を仮定しない。
- 作成：単一APIの逐次管理、固定入力/GFS、最遠点ペア＋farthest-first、SQLite永続化、原子的結果保存、状態復旧、明示retry、完全一致再利用、N06距離/目標再評価、CLI/資料。
- Workでは実Balloon API・実GFSを起動/投入していない。全ネットワーク試験はlocalhostのモックAPI。

## 自動試験

最終実行ログ：evidence/unit-tests.txt。**56件成功、0失敗**。Linux/Python実行。元config validatorのimport/検査も含む。Windowsの既定コマンドでは環境変数N07_VALIDATOR_ROOTがなければ、その1件だけskipped。

テスト時間はモック試験全体であり、実50地点の性能ではない。正確な秒数はログを参照。例のconfig/着地点/GFS識別はTEST_DOUBLE/MOCKとして明示。架空の実飛行・実GFS・実性能を提出していない。

| 要件 | 試験・結果 |
|---|---|
| 1〜50/51以上、ID/座標/高度 | 成功。重複/不明IDは計画全体拒否、地点不備はinvalid、他地点継続 |
| 正規共通条件 | 元validator接続成功。モック拒否でも新探索を作らない |
| 空間順・日付変更線 | 成功。最遠点ペア、決定的追加、順序を保存 |
| 逐次・50軽量/完全結果 | モック50ケース完了・最大active1・全blob読込/hash・順位50件の整合確認 |
| landed/stopped/地点失敗 | 成功。停止は距離なし。構造化した地点エラーは継続 |
| 共通GFS障害/接続不能/instance変更 | 成功。自動切替/新送信せずpaused |
| 目標変更・既完了再開 | 成功。新POSTなし。旧結果/履歴保持 |
| 完全一致/近接/高度差 | 成功。完全一致だけreuse。ID・入力順は保持 |
| 中断・保存先再open・通常resume | 成功。未計算だけ進む。Ctrl+C自体のWindows運用は未実行 |
| POST受理後応答喪失 | FakeApiと**実HTTP接続切断**の両方で成功。unknown保存→同ID照会→新POSTなしで復旧 |
| POST前意図保存後クラッシュ | hookおよび**実子プロセスos._exit**で成功。404でも再送しない |
| run中/完了/API再起動interrupted | モック成功。interruptedをfailed保存。勝手に再試行しない |
| 状態トランザクション | 例外rollbackと**実SQLite未commit更新後の子プロセスクラッシュ**から旧状態復旧 |
| 結果file rename失敗/rename後クラッシュ | 成功。元run GETで復旧し、二重POSTなし。未参照blobは残す |
| 破損状態/固定条件改変/donor blob破損 | 成功。検出し、無視した再利用・状態初期化なし |
| retry選択・履歴 | 成功。failedのみ新attempt。stopped/invalid/unknown不可 |
| 他探索のunknownとrunner lock | 成功。同じ保存先で未解決要求がある間、別探索を送信しない |
| 同条件の元候補・別条件の独立探索 | 成功。位置/ASL高度だけ変更、共通機体/日時保持。別IDで履歴独立 |
| 有限wait/開始前pause | 成功。既受付run保持、復旧は元run照会。次要求前pauseはPOSTなし |
| 既存APIのHTTP契約 | localhostモックでJSON/instanceヘッダー、正式6フィールドのみ確認 |

## Workで未実施

1. ユーザーWindowsにある北海道GFS/正規APIの実動作。ファイル/サーバーがWorkに提供されていない。
2. Windows実GFS50地点・実壁時計秒・全候補終端確認・実結果照合。
3. Windowsのmsvcrtロック・原子的rename・Ctrl+C・プロセス再起動の実環境受入。
4. 本番DB並みの電源断/ディスク障害/ネットワークファイルシステム試験。適用保証を広げない。
5. 新しいsource fingerprintが実行前に取得できないAPI制約の解消。本体APIは変更しない。
6. N04への直接統合、UI、ガス/日時/破裂最適化、分散、安全判定。

## 保証の限界

- 既存APIの同request ID重複受付防止は同一registry内に限定。API保存先消失・別DB・ディスク喪失に跨ぐExactly-onceは保証しない。
- Unknown要求は照会のみ。404のままなら停止。初版には利用者認定による未知要求の再POST/放棄解決機能はなく、API台帳の確認が必要。
- weather-sourcesは登録snapshot。毎GETの実ファイル検証ではない。submit/worker検査とrun/result snapshot照合に依存。
- 現在のengine hashを事前GETできないため、最初のrunから固定。後続差異を検出すると止めるが、APIが差異のあるコードで既に実行した可能性を否定できない。
- EXECUTION_FAILEDは原因の分類保証がないため保守的停止。明確に構造化された地点固有失敗だけ自動継続。
- 再利用は同探索内、完全config/GFS/source同一かつ完全blob hash確認済みのみ。探索横断再利用は未実装。
- 全科学JSONを保存するがCSV/KML/HTML等の元API補助成果物の全コピーではない。API元resultsは変更しない。
- 保存先は独立SQLiteで、既存FastAPIにN07 APIを追加したものではない。ブラウザ/localStorageは使っていない。

## 最終受入チェック

READMEの3地点→中断→再起動→別探索→障害確認→50地点をWindowsで実行。

- total=50 / processed=50 / state=completed。
- 全候補がlanded/stopped/invalid_input/failedの理由付き終端。unknown/active/pendingが残る場合は未完了。
- 完全結果blobまたは失敗記録、request/run対応、エラー/再開履歴が保持される。
- verify成功、landedのみ距離順位、同距離入力順、停止末尾評価なし。
- 実行秒、accepted request IDs/run IDs、再利用元を照合。すべてlandedである必要なし。
- 途中経過と再開が正しく、同じ条件を勝手に再計算していない。

受入ログ確認後にN08へ進むか判断する。**本報告書はWork側の実装・試験報告であり、N07最終完了の宣言ではない。**
