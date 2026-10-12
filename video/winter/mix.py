"""BGM・効果音・ナレーションを混ぜて、最終的な音声ファイルを作る。

timeline.json は別のスクリプトが書き出す想定で、次のような形をしている。

    {"bpm": 118, "n_bars": 150, "duration": 305.1,
     "sections": [[0, "intro"], [4, "verse"], ...],
     "sfx": [[12.3, "pop"], ...]}

やること:
  1. music.render_bgm() で BGM を作り、duration に合わせて長さを揃える。
  2. 効果音を timeline の時刻に重ねる。
  3. ナレーション（モノラル wav）を読み込み、44.1kHz に揃えて中央（両chに同じ音）で混ぜる。
     ナレーションの音量に合わせて BGM をダッキング（サイドチェイン）し、
     BGM の 2〜4kHz 付近を少し削って声を聞き取りやすくする。
  4. ffmpeg の loudnorm（2パス）でラウドネスを -14 LUFS 付近、
     true peak を -1 dBTP 以下に揃え、44.1kHz 16bit ステレオ wav で書き出す。

    python mix.py --timeline build/timeline.json --narration build/narration.wav --out build/audio.wav
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from music import render_bgm, sfx

SR = 44100

# ダッキングの設定（ナレーションに合わせて BGM を下げる量とスピード）
DUCK_DB = -10.0          # ナレーションが乗っているところでの最大減衰量
DUCK_ATTACK_S = 0.080    # 下げ始める速さ
DUCK_RELEASE_S = 0.350   # 戻る速さ

# BGM のプレゼンス（2〜4kHz）を少し削って声のスペースを作る
PRESENCE_FREQ = 3000.0
PRESENCE_GAIN_DB = -3.0
PRESENCE_Q = 1.0

LOUDNESS_I = -14.0   # 目標ラウドネス(LUFS, integrated)
# loudnorm の2パス目は TP を厳密には守り切らないことがあるため、
# 要件(<= -1 dBTP)に対して少し余裕を持たせておく。
LOUDNESS_TP = -1.5   # true peak の上限(dBTP)
LOUDNESS_LRA = 11.0


# --- 信号処理のこまごま ----------------------------------------------------------

def peaking_eq(x: np.ndarray, f0: float, gain_db: float, q: float, sr: int = SR) -> np.ndarray:
    """RBJ Audio EQ Cookbook のピーキング(パラメトリック)フィルタ。

    gain_db が負なら、f0 を中心にその帯域だけをゆるく削るディップになる
    （急峻なノッチではなく、なだらかなプレゼンスカット）。
    """
    from scipy.signal import lfilter

    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)

    b0 = 1 + alpha * A
    b1 = -2 * cos_w0
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * cos_w0
    a2 = 1 - alpha / A

    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return lfilter(b, a, x)


def envelope_follower(x: np.ndarray, attack_s: float, release_s: float, sr: int = SR,
                       ctrl_hz: float = 400.0) -> np.ndarray:
    """整流波形を一次遅れ(アタック/リリース非対称)で追従させる。

    サンプルごとに枝分かれするループは 300 秒級の音声には遅すぎるので、
    アタック/リリースの時定数よりずっと細かい制御レートまで間引いてから
    ループし、最後に線形補間で元のサンプル数へ戻す。
    """
    rect = np.abs(x)
    n = rect.size
    step = max(1, int(sr / ctrl_hz))
    ctrl = rect[::step].astype(np.float64)
    ctrl_sr = sr / step
    a_coef = np.exp(-1.0 / (attack_s * ctrl_sr))
    r_coef = np.exp(-1.0 / (release_s * ctrl_sr))

    env_ctrl = np.empty_like(ctrl)
    e = 0.0
    for i, v in enumerate(ctrl):
        coef = a_coef if v > e else r_coef
        e = coef * e + (1 - coef) * v
        env_ctrl[i] = e

    ctrl_t = np.arange(env_ctrl.size) * step
    env = np.interp(np.arange(n), ctrl_t, env_ctrl)
    return env


def place_stereo(buf: np.ndarray, x_mono: np.ndarray, t: float, gain: float = 1.0, sr: int = SR) -> None:
    """モノラルの効果音をステレオバッファ buf(shape=(2, N)) の時刻 t (秒) に足し込む。"""
    i = int(t * sr)
    n = buf.shape[-1]
    if i >= n or x_mono.size == 0:
        return
    m = min(x_mono.size, n - i)
    if m <= 0:
        return
    buf[:, i:i + m] += gain * x_mono[:m][None, :]


def fit_length(x: np.ndarray, n: int) -> np.ndarray:
    """1次元/多チャンネル配列を長さ n に切り詰め/ゼロ埋めする。"""
    cur = x.shape[-1]
    if cur == n:
        return x
    if cur > n:
        return x[..., :n]
    pad_width = [(0, 0)] * (x.ndim - 1) + [(0, n - cur)]
    return np.pad(x, pad_width)


def fade_edges(x: np.ndarray, sr: int = SR, fade_in_s: float = 0.01, fade_out_s: float = 0.15) -> None:
    """両端をわずかにフェードして、切り出しによるクリックを防ぐ(in-place)。"""
    n = x.shape[-1]
    fi = min(int(fade_in_s * sr), n // 2)
    fo = min(int(fade_out_s * sr), n // 2)
    if fi > 0:
        x[..., :fi] *= np.linspace(0, 1, fi)
    if fo > 0:
        x[..., -fo:] *= np.linspace(1, 0, fo)


def load_narration(path: Path, sr: int = SR) -> np.ndarray:
    """モノラル wav を読み込み、float [-1, 1] にして sr へリサンプルする。"""
    in_sr, data = wavfile.read(path)
    if data.dtype.kind == "i":
        x = data.astype(np.float64) / np.iinfo(data.dtype).max
    elif data.dtype.kind == "u":
        x = (data.astype(np.float64) - 128) / 128
    else:
        x = data.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if in_sr != sr:
        from math import gcd
        g = gcd(in_sr, sr)
        x = resample_poly(x, sr // g, in_sr // g)
    return x


# --- ラウドネス正規化（ffmpeg loudnorm 2パス） -------------------------------------

def loudnorm_two_pass(src_wav: Path, dst_wav: Path, i: float = LOUDNESS_I,
                       tp: float = LOUDNESS_TP, lra: float = LOUDNESS_LRA) -> None:
    filt1 = f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json"
    p1 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src_wav), "-af", filt1, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    text = p1.stderr
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("loudnorm measurement failed:\n" + text[-2000:])
    meas = json.loads(text[start:end + 1])

    filt2 = (
        f"loudnorm=I={i}:TP={tp}:LRA={lra}:"
        f"measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
        f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
        f"offset={meas['target_offset']}:linear=true:print_format=summary"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src_wav), "-af", filt2,
         "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", str(dst_wav)],
        capture_output=True, text=True, check=True,
    )


# --- ミックス本体 ----------------------------------------------------------------

def mix(timeline: dict, narration_path: Path | None, out_path: Path, sr: int = SR) -> np.ndarray:
    bpm = float(timeline["bpm"])
    n_bars = int(timeline["n_bars"])
    duration = float(timeline["duration"])
    sections = [(int(s), str(k)) for s, k in timeline["sections"]]
    sfx_events = [(float(t), str(k)) for t, k in timeline.get("sfx", [])]

    n_out = int(round(duration * sr))

    bgm = render_bgm(n_bars, sections, bpm=bpm, sr=sr)
    bgm = fit_length(bgm, n_out)

    for t, kind in sfx_events:
        if t < 0:
            continue
        place_stereo(bgm, sfx(kind, sr), t, 1.0, sr)

    # BGM のプレゼンス帯を少し削る（声の通り道を作る）
    bgm_eq = np.stack([peaking_eq(ch, PRESENCE_FREQ, PRESENCE_GAIN_DB, PRESENCE_Q, sr) for ch in bgm])

    narration = np.zeros(n_out, dtype=np.float64)
    if narration_path is not None:
        narr = load_narration(narration_path, sr)
        narr = fit_length(narr, n_out)
        narration = narr

    duck_floor = 10 ** (DUCK_DB / 20)
    env = envelope_follower(narration, DUCK_ATTACK_S, DUCK_RELEASE_S, sr)
    ref = np.percentile(env[env > 1e-6], 90) if np.any(env > 1e-6) else 1.0
    ref = max(ref, 1e-6)
    env_norm = np.clip(env / ref, 0.0, 1.0)
    duck_gain = 1.0 - (1.0 - duck_floor) * env_norm

    bgm_ducked = bgm_eq * duck_gain[None, :]

    narration_gain = 0.9
    stereo = bgm_ducked + narration[None, :] * narration_gain
    fade_edges(stereo, sr)

    peak = np.abs(stereo).max()
    if peak > 0.98:
        stereo *= 0.98 / peak

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".prenorm.wav")
    wavfile.write(tmp_path, sr, stereo.T.astype(np.float32))
    loudnorm_two_pass(tmp_path, out_path)
    tmp_path.unlink(missing_ok=True)

    return stereo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeline", type=Path, required=True)
    ap.add_argument("--narration", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
    mix(timeline, args.narration, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
