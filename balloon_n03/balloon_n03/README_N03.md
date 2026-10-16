# Balloon Lab weather N03 cache PoC

N01 + N02 を同梱した独立動作のN03版です。Balloon Lab本体の飛行計算コードは変更しません。

## 確定要件と実装
- メモリキャッシュ、TTL 30分、古い参考データは取得後6時間未満まで
- 上限200件、参照時にLRU順を更新し上限超過時に古い順に削除
- 同じ座標・JST取得日・予報条件の要求はSingle-flightで統合
- モデル、単位、予報期間などを変更可能にする際は `ForecastCache._key` も更新すること
- 10秒はAPI通信 **1試行あたり** のタイムアウト。再試行1回、待機1秒で計最大約21秒＋処理時間
- 一時的接続エラー、タイムアウト、HTTP 500/502/503/504のみ1回再試行。429等は再試行しない
- 同時Open-Meteo通信最大5件（待機キュー上限は未実装）
- `force=1` でも同じキーで通信中なら同じ結果を共有
- 同じ候補の放球時刻を変更しても再取得不要。ただしJST日付変更後は新規キー
- 取得失敗時、保持期間内かつ同じキーの旧データだけstale + last_refresh.failedとして返す
- ブラウザの表示用HTMLは開発用。商用ライセンス、本番サーバ統合、プロセス間キャッシュは未対応

## 準備
ZIP展開後の `balloon_n03` フォルダを `Chart-Balloon-Simulator` の中へ置く。
古いN01/N02サーバーの `8766` ポートを停止してから実行。

```powershell
cd C:\Users\ytrgr\Chart-Balloon-Simulator\balloon_n03
python -m unittest -v test_weather test_quality test_n03
python demo_server.py
```

ブラウザ http://127.0.0.1:8766/ から取得テスト。ブラウザのJSON `quality.cache_hit`, `quality.freshness`, `quality.last_refresh`, `cache_status` を確認。

## 備考
- 本リリースでのライブOpen-Meteoリクエストは未検証。ネット接続のあるWindows PCで確認してください。
- ダウンロードの結果がHTTP 200でもJSONフォーマット異常な場合は、現在のN01 `interpret()` が `api_error` を返します。形式破損に対する再試行の扱いは別途必要に応じて整備してください。
- `weather_service.fetch_raw` のtimeout値を15から10秒に変更しました。N01の飛行計算は存在しません。
