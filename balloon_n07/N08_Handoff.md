# N08以降への引き継ぎ（実装は未着手）

N07の最終受入後に判断する資料。地図・最適化のコードはこのPoCに含まれない。

## 渡せるデータ

- 探索ID、固定config/GFS、元入力順、確定空間順、候補ごとの状態。
- 軽量一覧：candidate_id、run_id、放球位置/ASL高度、正常着地点、WGS84距離、暫定順位、エラー。
- 完全JSON：result_refのローカル相対パス/SHA、API取得パス、source/weather snapshot、records/events。選択候補だけ読むことを想定。
- stopped/invalid/failed/pending/unknownは距離nullで区別。停止末尾を着地点マーカーへ使わない。
- target/evaluated_utc/評価履歴。targetだけ変更して飛行を再実行しない。

## 接続上の注意

1. N04ソースは未確認。本初版は新規候補JSON契約で、直接UI統合ではない。N04からは安定ID・度の座標・確認済み海面基準高度が必要。高度不明を0へ埋めない。
2. N06を無変更で同梱。仕事用のN06環境を上書きしない。内部file SHAはevidence/repository-integrity.jsonを参照。
3. 既存2D/3D・KML/GeoJSON・分散は変更していない。次のUIがAPI本体のrunとN07 searchを混同しないようにする。
4. N07のサーバー保存は独立ローカルSQLite。既存FastAPIに検索管理APIを追加したものではない。Webからの接続には別の契約設計が必要。
5. 長い全軌道JSONを全候補へ読み込む方式は避け、軽量一覧と選択軌道を分ける。本PoCにN08表示はない。
6. 異なるGFS・日時・機体条件は別探索。同一探索内だけの完全一致再利用であり、探索横断のキャッシュは未実装。
7. APIには「現在の実装fingerprintを実行前にGETする」「不明要求が絶対未受付と保証する」機能がない。UIで再送ボタンを無条件に追加しない。
8. Windows実GFS50地点、強制終了後の復旧、各result hash、全50件の終端/距離の受入確認がまだ必要。
9. 距離最小は計算済み候補の位置比較。安全・許可・飛行実現性・全球最適解ではない。ガス/日時/破裂条件の最適化は含めない。
