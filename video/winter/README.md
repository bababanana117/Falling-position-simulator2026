# video/winter: 冬の打ち上げ適地の紹介動画（4 分 26 秒、ナレーションつき）

`winter_launch_video.mp4` — 1920×1080、30 fps、AAC ステレオ（約 -14 LUFS）。
レポート `research/winter_japan/winter_launch_japan.pdf` の結果を、After Effects 風の
モーショングラフィックスで紹介する。絵・BGM・効果音はすべてスクリプトで作っている。

## 作り方

```bash
cd research && python ../video/winter/prepare_data.py   # 研究の出力 → build/data.json, data.npz
cd ../video/winter
python script.py                    # 台本 → build/script.json
python tts.py                       # VOICEVOX（127.0.0.1:50021）で 1 文ずつ合成 → build/tts/
python assemble.py                  # 小節に合わせて並べる → build/narration.wav, timeline.json, subtitles.srt
python render.py --audio-timeline   # 効果音と BGM の区間を timeline.json に書き足す
python mix.py --timeline build/timeline.json --narration build/narration.wav --out build/audio.wav
python render.py                    # 映像を描いて音と合わせる（16 並列で数分）
python render.py --sheet iki        # 1 シーンを 8 枚並べた確認用の画像
```

- シーンの長さはナレーションで決まり、各シーンは小節（118 BPM）の頭から始まる。
- 絵は `engine.py`（道具・字幕・場面転換）と `scenes_a/b/c.py`（13 シーン）。
- 数字はすべて `prepare_data.py` が研究の出力から集める。手で書いた値は使わない。
- 壱岐の確率は、地上気象をアメダス芦辺の観測で判定した値（レポート 5 章）。

## 権利

- ナレーション: VOICEVOX:四国めたん（動画内にクレジットを表示）
- データ: JRA-3Q（気象庁）、ERA5（Copernicus Climate Change Service）、アメダス（気象庁）、
  国土数値情報（人口集中地区）、© OpenStreetMap contributors
- JRA-3Q の派生物なので、動画は CC BY-NC-SA 4.0（非商用）で扱うこと。
