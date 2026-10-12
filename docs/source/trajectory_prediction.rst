着地位置予測 (Tawhiriクライアント)
========================================

概要
----

発射条件フォーム(``frontend/src/components/params/ParameterForm.tsx``)で
入力した打ち上げ条件を、Tawhiri API形式のリクエストに変換して問い合わせ、
返ってきた軌道点列を地図とグラフに描画する。軌道の物理計算そのものは
行わず、あくまでTawhiriクライアントである(予報窓を超えた日時は
:doc:`climatology` の統計モードに切り替わる)。

.. mermaid::

   sequenceDiagram
       participant U as 利用者
       participant UI as ParameterForm / useRunPrediction
       participant API as Tawhiri API

       U->>UI: 発射地点・日時・上昇速度・破裂高度等を入力
       U->>UI: 「単発予測」または「時系列予測」をクリック
       UI->>UI: buildBaseRequest() で入力値をTawhiriリクエストに整形
       UI->>UI: classifyLaunchTime() で予報窓内/統計モード/エラーを判定
       UI->>API: GET /tawhiri?launch_latitude=...&profile=...
       API-->>UI: {prediction: [ascent軌道, descent軌道]}
       UI->>UI: parseFlight() で軌道点列をFlight型に変換
       UI->>U: 地図上に飛行経路・打上/破裂/着地マーカー、高度プロファイルを表示

入力パラメータ
----------------

``buildBaseRequest()`` (``frontend/src/hooks/useRunPrediction.ts``) が
``useParamsStore`` の値からTawhiriリクエストを組み立てる。

.. list-table::
   :header-rows: 1

   * - パラメータ
     - 説明
   * - ``launch_latitude`` / ``launch_longitude``
     - 発射地点。地図クリック・マーカーのドラッグ・緯度経度の数値入力・
       地域別プリセット(``sites.json``、``SitePicker.tsx``)のいずれでも
       設定できる
   * - ``launch_altitude``
     - 発射地点の標高 [m]
   * - ``launch_datetime``
     - 発射日時。入力フォームはJST表記で、``jstInputToUtcIso()``
       (``frontend/src/time/jst.ts``、``date-fns-tz`` を使用)でUTCの
       ISO文字列に変換する
   * - ``ascent_rate``
     - 上昇速度 [m/s] (:doc:`ascent_calculator` の結果を反映可能)
   * - ``profile``
     - ``standard_profile`` (打上→破裂→降下) または ``float_profile``
       (指定高度で浮遊、終了時刻は発射時刻+24時間)
   * - ``burst_altitude`` + ``descent_rate``
     - ``standard_profile`` 時のみ指定

発射時刻の判定は ``classifyLaunchTime()`` が行う
(:doc:`climatology` の表を参照)。現在−12時間より過去はエラー、
現在+7日より先は統計モード(バックエンドが無ければエラー)、それ以外は
通常のTawhiri予測になる。

予測モード
------------

.. list-table::
   :header-rows: 1

   * - モード
     - 動作
   * - 単発予測 (``runSingle``)
     - Tawhiriへ1回だけリクエストし、飛行経路を1本描画する。予報窓より
       先であれば統計モードの軌道に切り替わる
   * - 時系列予測 (``runHourly``)
     - 発射時刻を指定した間隔(既定・最大168時間まで調整可能)でずらし
       ながら繰り返しリクエストし、各時刻の飛行経路を高度プロファイル
       グラフに重ねて描画する。予報窓を超えた時刻は静かにスキップする
       (旧実装と同じ挙動)

時系列予測は、全オフセットを ``Promise.all`` で並行実行するが、
``frontend/src/api/semaphore.ts`` の ``tawhiriSemaphore``
(同時実行数上限5、429/503応答時は全体を10秒停止)でTawhiriへの負荷を
抑えている。各リクエストの開始前には50〜150msのジッタ(``jitterMs()``)
も入れている。

レスポンス処理
----------------

Tawhiriのレスポンスは ``prediction[0].trajectory`` (上昇脚)と
``prediction[1].trajectory`` (降下または浮遊脚)の2本の軌道配列を持つ
(各要素は ``{latitude, longitude, altitude, datetime}``)。
``parseFlight()`` (``frontend/src/api/tawhiri.ts``)はこれを以下の
``Flight`` 型にまとめる。

- 経度0〜360度表記を-180〜180度に正規化(``normalizeLon()``)
- 先頭点=打上、上昇脚末尾(降下/浮遊脚がある場合)=破裂、末尾の脚の
  末尾=着地としてマーカー用の点を抽出
- 打上から着地までの飛行時間を計算

失敗時の扱い:

- Tawhiriが5xxを返した場合は最大2回まで再試行する(1秒、3秒後)
- 4xxは再試行しない(予報窓外や不正なパラメータが主な原因)
- リクエストが中断(``AbortSignal``)された場合はそのまま例外を投げる

表示
----

- 地図(2D: Leaflet、3D: three.js)上に飛行経路のポリライン、打上・破裂・
  着地のマーカー(``frontend/src/components/map/TrajectoryLayer.tsx``、
  ``Map3D.tsx``)
- 「シナリオ情報」パネル(``ScenarioInfo.tsx``): 着地予測の緯度経度、
  着地時刻(JST表示)、飛行距離(ハーバサイン)、飛行時間
- 高度プロファイル(``AltitudeProfile.tsx``、Plotly.js): 時刻を横軸、
  高度を縦軸に、単発予測・時系列予測の各時刻・モンテカルロの各標本を
  重ねて描画する

CSV/KMLのダウンロードは、Tawhiriへのクエリパラメータに ``&format=csv`` /
``&format=kml`` を付与して、Tawhiri自身が生成したファイルを直接ダウンロード
させる(``exportUrls()``)。本リポジトリ側ではファイル生成をしていない。

Tawhiri APIエンドポイント
----------------------------

``https://api.v2.sondehub.org/tawhiri`` (``frontend/src/api/tawhiri.ts``
の ``TAWHIRI_URL``)。APIキー不要で、ブラウザから直接 ``fetch`` している
(CORSはTawhiri側が許可している)。
