"""ナレーションの各行 wav を、拍（BPM）に合わせて時間軸に並べる。

build/tts/<scene>_<k>.wav（tts.py が作った行ごとの音声）を読み、
シーンが小節の頭から始まるように時刻を決めて、1本の wav にまとめる。
あわせて、後工程（映像・SE合わせ）が使う timeline.json と、
字幕用の subtitles.srt も書き出す。

タイミングの決め方:
  BAR = 4 拍 * 60 / BPM 秒（1 小節の長さ）
  シーン 0 だけは、2 小節分のイントロの後、
    先頭の行がちょうど 2*BAR の位置から始まる。
  それ以外のシーンは、シーンの開始（小節の頭）から 0.6 秒後に
    先頭の行が始まる。
  シーン内の行と行の間は 0.35 秒あける。
  シーンの終わりは、最後の行の終わりに 1.2 秒足した時刻以降で、
    最初に来る小節の頭。
  最後の outro シーンだけは、そこにさらに 3 小節を足して終わる
    （エンディング用の余白）。

使い方:
    python assemble.py
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SCRIPT_JSON = BUILD / "script.json"
TTS_DIR = BUILD / "tts"

OUT_WAV = BUILD / "narration.wav"
OUT_TIMELINE = BUILD / "timeline.json"
OUT_SRT = BUILD / "subtitles.srt"

BPM = 118
BAR = 4 * 60 / BPM  # 1 小節の長さ（秒）
LINE_GAP = 0.35
SCENE_HEAD_OFFSET = 0.6
SCENE_END_MARGIN = 1.2
OUTRO_EXTRA_BARS = 3
SAMPLE_RATE = 44100


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1, f"{path} はモノラルではありません"
        assert w.getsampwidth() == 2, f"{path} は16bitではありません"
        sr = w.getframerate()
        n = w.getnframes()
        data = w.readframes(n)
    samples = np.frombuffer(data, dtype="<i2")
    return samples, sr


def next_bar_boundary(t: float) -> float:
    n = math.ceil(round(t / BAR, 9))
    return n * BAR


def fmt_srt_time(t: float) -> str:
    t = max(t, 0.0)
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> int:
    scenes = json.loads(SCRIPT_JSON.read_text(encoding="utf-8"))

    # 各行の wav を読み、長さを控えておく
    line_audio: list[list[tuple[np.ndarray, float]]] = []
    for scene in scenes:
        scene_id = scene["id"]
        rows = []
        for idx, line in enumerate(scene["lines"]):
            wav_path = TTS_DIR / f"{scene_id}_{idx}.wav"
            samples, sr = read_wav(wav_path)
            if sr != SAMPLE_RATE:
                raise RuntimeError(f"{wav_path} のサンプリングレートが {sr} Hz (期待 {SAMPLE_RATE})")
            dur = len(samples) / sr
            rows.append((samples, dur))
        line_audio.append(rows)

    timeline_scenes = []
    cursor = 2 * BAR  # イントロ 2 小節ぶん

    n_scenes = len(scenes)
    for i, scene in enumerate(scenes):
        scene_id = scene["id"]
        scene_start = cursor
        is_first = i == 0
        is_last = i == n_scenes - 1

        t = scene_start if is_first else scene_start + SCENE_HEAD_OFFSET

        lines_out = []
        for idx, line in enumerate(scene["lines"]):
            _, dur = line_audio[i][idx]
            start = t
            end = start + dur
            lines_out.append({"text": line["text"], "start": start, "end": end})
            t = end + LINE_GAP

        last_line_end = lines_out[-1]["end"]
        boundary = next_bar_boundary(last_line_end + SCENE_END_MARGIN)
        if is_last:
            boundary += OUTRO_EXTRA_BARS * BAR
        scene_end = boundary

        n_bars = round((scene_end - scene_start) / BAR)
        start_bar = round(scene_start / BAR)

        timeline_scenes.append({
            "id": scene_id,
            "start": scene_start,
            "end": scene_end,
            "start_bar": start_bar,
            "n_bars": n_bars,
            "lines": lines_out,
        })

        cursor = scene_end

    total_duration = cursor
    total_bars = round(total_duration / BAR)

    # ---- narration.wav を書き出す ----
    n_total_samples = int(round(total_duration * SAMPLE_RATE))
    buf = np.zeros(n_total_samples, dtype=np.int32)

    for i, scene in enumerate(scenes):
        for idx, line in enumerate(scene["lines"]):
            samples, dur = line_audio[i][idx]
            start_sample = int(round(timeline_scenes[i]["lines"][idx]["start"] * SAMPLE_RATE))
            end_sample = start_sample + len(samples)
            if end_sample > len(buf):
                # 総尺が足りない場合は末尾に合わせて伸ばす（通常は起きない想定）
                extra = end_sample - len(buf)
                buf = np.concatenate([buf, np.zeros(extra, dtype=np.int32)])
            buf[start_sample:end_sample] += samples.astype(np.int32)

    clipped = np.clip(buf, -32768, 32767).astype(np.int16)
    with wave.open(str(OUT_WAV), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(clipped.tobytes())

    # ---- timeline.json ----
    timeline = {
        "bpm": BPM,
        "bar": BAR,
        "n_bars": total_bars,
        "duration": total_duration,
        "scenes": timeline_scenes,
        "sections": [],
        "sfx": [],
    }
    OUT_TIMELINE.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- subtitles.srt ----
    srt_lines = []
    n = 1
    for scene in timeline_scenes:
        for line in scene["lines"]:
            srt_lines.append(str(n))
            srt_lines.append(f"{fmt_srt_time(line['start'])} --> {fmt_srt_time(line['end'])}")
            srt_lines.append(line["text"])
            srt_lines.append("")
            n += 1
    OUT_SRT.write_text("\n".join(srt_lines), encoding="utf-8")

    # ---- レポート表示 ----
    print(f"{'scene':<14}{'start':>10}{'duration':>10}{'n_bars':>8}")
    for scene in timeline_scenes:
        dur = scene["end"] - scene["start"]
        print(f"{scene['id']:<14}{scene['start']:>10.2f}{dur:>10.2f}{scene['n_bars']:>8}")
    print(f"\ntotal duration: {total_duration:.2f} s ({total_duration/60:.2f} min), {total_bars} bars")
    print(f"wrote {OUT_WAV}")
    print(f"wrote {OUT_TIMELINE}")
    print(f"wrote {OUT_SRT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
