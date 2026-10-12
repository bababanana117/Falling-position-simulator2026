"""冬の打ち上げ適地の紹介動画を描いて、音と合わせる。

    python script.py                       # 台本 → build/script.json
    python tts.py                          # ナレーション → build/narration.wav, timeline.json
    python render.py --audio-timeline      # 効果音と BGM の区間を timeline.json に書き足す
    python mix.py --timeline build/timeline.json --narration build/narration.wav --out build/audio.wav
    python render.py                       # 映像 → winter_launch_video.mp4

確かめるとき:

    python render.py --still 42.0                  # 動画の頭から 42 秒の 1 枚
    python render.py --scene iki --at 3.5          # シーンの頭から 3.5 秒の 1 枚
    python render.py --sheet iki                   # そのシーンを 8 枚並べた確認用の画像
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from multiprocessing import Pool
from pathlib import Path

from PIL import Image, ImageDraw

import engine as E
import scenes_a
import scenes_b
import scenes_c

SCENE_FUNCS = {**scenes_a.SCENES, **scenes_b.SCENES, **scenes_c.SCENES}
SFX_FUNCS = {**scenes_a.SFX, **scenes_b.SFX, **scenes_c.SFX}
OUT = E.HERE / "winter_launch_video.mp4"


def sfx_events() -> list[tuple[float, str]]:
    """全シーンの効果音（動画の頭からの秒）。場面転換には whoosh を入れる。"""
    ev = []
    for s in E.TL["scenes"]:
        c = E.ctx_at(s["start"] + 1e-6)
        if s is not E.TL["scenes"][0]:
            ev.append((s["start"] - 0.2, "whoosh"))
        f = SFX_FUNCS.get(s["id"])
        if f:
            ev += [(s["start"] + t, kind) for t, kind in f(c)]
    return sorted((round(t, 3), k) for t, k in ev if 0 <= t < E.DURATION)


_SFX = None


def shake(T: float) -> tuple[float, float]:
    global _SFX
    if _SFX is None:
        _SFX = sfx_events()
    amp = 0.0
    for tt, kind in _SFX:
        if kind in ("burst", "ding", "crash") and 0 <= T - tt < 0.3:
            amp = max(amp, (1 - (T - tt) / 0.3) * (18 if kind == "burst" else 8))
    return amp * math.sin(T * 90), amp * math.cos(T * 77)


def frame(T: float) -> Image.Image:
    img = E.new_frame()
    c = E.ctx_at(T)
    E.background(img, c.id, T)
    SCENE_FUNCS[c.id](img, c)
    E.chapter(img, c)
    E.subtitle(img, c)
    E.transition(img, c)
    dx, dy = shake(T)
    out = img.resize((E.W, E.H), Image.LANCZOS).convert("RGB")
    if dx or dy:
        out = out.transform(out.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                            resample=Image.BILINEAR, fillcolor=E.NAVY)
    return out


def _bytes(i: int) -> bytes:
    return frame(i / E.FPS).tobytes()


def sheet(scene: str, n: int = 8) -> Path:
    s = next(x for x in E.TL["scenes"] if x["id"] == scene)
    ts = [s["start"] + (s["end"] - s["start"]) * (k + 0.5) / n for k in range(n)]
    thumbs = [frame(t).resize((640, 360)) for t in ts]
    img = Image.new("RGB", (640 * 4, 360 * math.ceil(n / 4) + 0), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for k, (t, th) in enumerate(zip(ts, thumbs, strict=True)):
        x, y = 640 * (k % 4), 360 * (k // 4)
        img.paste(th, (x, y))
        d.text((x + 8, y + 8), f"{scene} +{t - s['start']:.1f}s", fill=(255, 0, 0))
    out = E.BUILD / f"sheet_{scene}.png"
    img.save(out)
    return out


def write_audio_timeline() -> Path:
    tl = json.loads((E.BUILD / "timeline.json").read_text(encoding="utf-8"))
    tl["sections"] = [[s["start_bar"], E.MUSIC[s["id"]]] for s in tl["scenes"]]
    tl["sections"][0][0] = 0
    tl["sfx"] = [[t, k] for t, k in sfx_events()]
    p = E.BUILD / "timeline.json"
    p.write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--still", type=float)
    ap.add_argument("--scene")
    ap.add_argument("--at", type=float, default=0.0)
    ap.add_argument("--sheet")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--audio-timeline", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--from", dest="t_from", type=float, default=0.0)
    ap.add_argument("--to", dest="t_to", type=float)
    a = ap.parse_args(argv)
    E.BUILD.mkdir(parents=True, exist_ok=True)
    if a.audio_timeline:
        print(write_audio_timeline())
        return 0
    if a.sheet:
        print(sheet(a.sheet))
        return 0
    if a.still is not None or a.scene:
        T = a.still if a.still is not None else \
            next(s["start"] for s in E.TL["scenes"] if s["id"] == a.scene) + a.at
        out = a.out or E.BUILD / f"still_{T:.2f}.png"
        frame(T).save(out)
        print(out)
        return 0
    t_to = a.t_to if a.t_to is not None else E.DURATION
    i0, i1 = round(a.t_from * E.FPS), round(t_to * E.FPS)
    silent = E.BUILD / "video_silent.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{E.W}x{E.H}", "-r", str(E.FPS), "-i", "-", "-c:v", "libx264",
           "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", str(silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(a.workers) as pool:
        for k, buf in enumerate(pool.imap(_bytes, range(i0, i1), chunksize=4)):
            proc.stdin.write(buf)
            if k % 300 == 0:
                print(f"frame {k}/{i1 - i0}", flush=True)
    proc.stdin.close()
    proc.wait()
    audio = E.BUILD / "audio.wav"
    if not audio.exists() or a.t_from > 0 or a.t_to is not None:
        print(silent)
        return 0
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT)],
                   check=True)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
