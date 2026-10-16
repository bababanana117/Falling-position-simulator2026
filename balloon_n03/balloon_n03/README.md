# N01 放球地点の気象情報取得（最小検証版）

- 既存飛行計算に変更なし。外部ライブラリ不要（Python 3.10+）。
- `weather_service.py`: N01 予報取得・入力検証・時刻抽出・欠測処理
- `weather_cache.py`: N03を先取りした30分メモリキャッシュ、期限切れフォールバック（暫定実装）
- `demo_server.py`, `index.html`: ブラウザ用最小検証画面
- `test_weather.py`: API通信なしの自動テスト

## 起動（Windows PowerShell）

```powershell
cd C:\Users\ytrgr\Chart-Balloon-Simulator\balloon_n01
python -m unittest -v test_weather
python demo_server.py
```

ブラウザで `http://127.0.0.1:8766/` を開く。別ターミナルの既存サーバー8450/8451や気象PoC8765を停止する必要はない。

## 備考
- Open-Meteo `/v1/forecast` の `forecast_days=7`, `timezone=Asia/Tokyo`, `models=best_match` を使用。
- 予報の有効期間は「取得時点のJST当日を含む7暦日」。前後のどちらかの時刻が欠ける場合は `partial` とする。
- 同じ予報時刻なら `before` のみ返し `after:null` とする。
- モデル基準時刻はAPI標準レスポンスから推測せず、取得時刻を `fetched_at` として保持する。
- Open-Meteoの `wind_gusts_10m` は予報値。時間的集計の定義は使用モデルによって異なる場合がある。
- 期限切れキャッシュは `cache_status:stale` で返す。ユーザー向け運用時は明確に警告すること。
- N03正式実装では、競合リクエストの排他、候補多数の負荷制御、座標丸めの方針、永続キャッシュを検討する。
- API利用条件、商用利用可否を別途確認すること。


## N02 品質管理追加版（2026-10）

- `weather_quality.py` は独立した検証モジュール。N01の `weather_service.py` は**変更していない**。
- `weather_cache.py` で、既存N01形式のJSONに `quality` を付加する（A方式）。
- 不正な数値はその項目だけ `null` にし、欠測・不正・極端値・未定義天気コードを時刻ごとの `issues` に記録する。
- `freshness` と `last_refresh` を別々に保持。`cache_hit` は今回キャッシュを利用したかを示す。
- 設定変更は Python から `ForecastCache(thresholds={'wind_speed_ms': {'max': 30.0}})` のように行う。閾値は物理的危険度を意味しない。
- `model_run_time` は取得不可能な場合 `null`。`fetched_at` はAPI取得時刻。
- 例外: `api_error` / `invalid_input` / `out_of_range` でも `quality` を返す。

### テスト

```powershell
python -m unittest -v test_weather test_quality
python demo_server.py
```

HTMLは `http://127.0.0.1:8766/`。N01サーバーを起動中なら `Ctrl+C` で止め、更新版のフォルダから起動し直す。

### 現段階の制約

- 30分キャッシュはN03の**暫定メモリ実装**でサーバー再起動により消える。複数アクセス時の排他は未実装。
- 既にN01で変換・欠測化された値の由来を復元するため、N02では元のAPI配列も参照している。
- Open-MeteoのライブAPIと画面表示の動作はユーザー環境で要検証。
- 商用利用の契約・利用条件は本番導入までに確認すること。
