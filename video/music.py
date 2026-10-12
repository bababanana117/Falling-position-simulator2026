"""30 秒の BGM と効果音を合成する（128 BPM、C メジャーの明るいハウス調）。

音源ファイルは使わず、すべて NumPy で作る。著作権の問題が起きない。

    python video/music.py          # video/build/audio.wav
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

from timeline import BAR, BEAT, DURATION, SFX

SR = 44100
HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "audio.wav"
RNG = np.random.default_rng(7)


def t_axis(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


# --- 楽器 ----------------------------------------------------------------------

def kick() -> np.ndarray:
    t = t_axis(0.4)
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = hp(RNG.standard_normal(t.size), 2000) * np.exp(-t * 300) * 0.3
    return np.tanh(1.6 * (body + click))


def clap() -> np.ndarray:
    t = t_axis(0.25)
    env = np.zeros_like(t)
    for d in (0.0, 0.011, 0.022):
        env += (t >= d) * np.exp(-np.clip(t - d, 0, None) * (60 if d < 0.02 else 18))
    return bp(RNG.standard_normal(t.size), 900, 6000) * env * 0.6


def hat(open_: bool = False) -> np.ndarray:
    t = t_axis(0.18 if open_ else 0.05)
    env = np.exp(-t * (18 if open_ else 90))
    return hp(RNG.standard_normal(t.size), 7000) * env * (0.25 if open_ else 0.2)


def saw(f: float, t: np.ndarray, detune: float = 0.0) -> np.ndarray:
    ph = (f * (1 + detune) * t + RNG.random()) % 1.0
    return 2 * ph - 1


def supersaw(freqs, dur: float, cutoff: float = 2600) -> np.ndarray:
    t = t_axis(dur)
    x = np.zeros_like(t)
    for f in freqs:
        for d in (-0.012, -0.006, 0.0, 0.006, 0.012):
            x += saw(f, t, d)
    x /= 5 * len(freqs)
    env = np.minimum(t / 0.004, 1) * np.exp(-t * 7)
    return lp(x, cutoff) * env


def bass(n: int, dur: float) -> np.ndarray:
    t = t_axis(dur)
    f = midi(n)
    x = 0.6 * saw(f, t) + 0.4 * np.sin(2 * np.pi * f / 2 * t)
    env = np.minimum(t / 0.003, 1) * np.exp(-t * 5)
    return lp(x, 700) * env


def pluck(n: int, dur: float = 0.18) -> np.ndarray:
    t = t_axis(dur)
    f = midi(n)
    x = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.sin(2 * np.pi * 2 * f * t) * 0.3
    return lp(x, 3500) * np.exp(-t * 16)


# --- 効果音 --------------------------------------------------------------------

def sfx(kind: str) -> np.ndarray:
    if kind == "pop":
        t = t_axis(0.09)
        f = 1400 * np.exp(-t * 40) + 350
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45) * 0.55
    if kind == "tick":
        t = t_axis(0.04)
        return np.sin(2 * np.pi * 2600 * t) * np.exp(-t * 120) * 0.25
    if kind in ("whoosh", "swish"):
        dur = 0.45 if kind == "whoosh" else 0.3
        t = t_axis(dur)
        noise = RNG.standard_normal(t.size)
        out = np.zeros_like(t)
        # 帯域を低から高へ動かす（ブロックごとに通す）
        n_blk = 12
        for k in range(n_blk):
            a, b = k * t.size // n_blk, (k + 1) * t.size // n_blk
            c = 300 * (12 ** (k / (n_blk - 1)))
            out[a:b] = bp(noise, c * 0.7, min(c * 1.6, SR / 2 - 100))[a:b]
        env = np.sin(np.pi * t / dur) ** 2
        return out * env * (0.5 if kind == "whoosh" else 0.35)
    if kind == "burst":
        t = t_axis(0.5)
        thump = np.sin(2 * np.pi * (80 + 60 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
        crack = hp(RNG.standard_normal(t.size), 1500) * np.exp(-t * 35)
        return np.tanh(1.5 * (thump * 0.8 + crack * 0.9)) * 0.9
    if kind == "ding":
        t = t_axis(1.0)
        x = sum(a * np.sin(2 * np.pi * 1318.5 * r * t) * np.exp(-t * d)
                for a, r, d in ((1.0, 1, 4), (0.5, 2.76, 7), (0.25, 5.4, 11)))
        return x * 0.35
    if kind == "crash":
        t = t_axis(2.0)
        return hp(RNG.standard_normal(t.size), 4000) * np.exp(-t * 2.2) * 0.45
    raise ValueError(kind)


# --- 曲 ------------------------------------------------------------------------

#: 1 小節ごとのコード（C G Am F を繰り返す）。根音の MIDI と和音
PROGRESSION = [
    (48, (60, 64, 67)), (43, (59, 62, 67)), (45, (60, 64, 69)), (41, (60, 65, 69)),
]


def place(buf: np.ndarray, x: np.ndarray, t: float, gain: float = 1.0) -> None:
    i = int(t * SR)
    if i >= buf.shape[-1]:
        return
    n = min(x.size, buf.shape[-1] - i)
    buf[..., i:i + n] += gain * x[:n]


def render() -> np.ndarray:
    n = int(DURATION * SR) + SR // 2
    drums = np.zeros(n)
    music = np.zeros(n)
    arp = np.zeros(n)
    fx = np.zeros(n)
    duck = np.ones(n)

    k, c, h_c, h_o = kick(), clap(), hat(), hat(True)
    for bar in range(16):
        t0 = bar * BAR
        root, chord = PROGRESSION[bar % 4]
        intro = bar < 2
        outro_last = bar == 15
        for b in range(4):
            tb = t0 + b * BEAT
            if not intro or b == 0:
                place(drums, k, tb, 1.0)
                i = int(tb * SR)
                m = min(int(0.22 * SR), n - i)
                duck[i:i + m] = np.minimum(duck[i:i + m], 0.35 + 0.65 * np.linspace(0, 1, m) ** 1.5)
            if not intro and b in (1, 3):
                place(drums, c, tb, 0.9)
            if not intro:
                place(drums, h_o if b % 2 else h_c, tb + BEAT / 2, 1.0)
                place(drums, h_c, tb + BEAT / 4, 0.5)
                place(drums, h_c, tb + 3 * BEAT / 4, 0.5)
            # ベース: 裏拍の 8 分
            if not intro:
                place(music, bass(root, BEAT / 2 * 0.9), tb + BEAT / 2, 0.8)
            # コードの刻み: 裏拍（イントロは小さく、フィルターを閉じる）
            cutoff = 900 + 2200 * min(1.0, (t0 + b * BEAT) / (2 * BAR)) if intro else 2800
            place(music, supersaw([midi(x) for x in chord], BEAT * 0.45, cutoff), tb + BEAT / 2,
                  0.35 if intro else 0.5)
        # アルペジオ: 7 小節目から 16 分で
        if 6 <= bar <= 13:
            notes = [x + 12 for x in chord] + [chord[0] + 24]
            for s in range(16):
                place(arp, pluck(notes[s % 4]), t0 + s * BEAT / 4, 0.22)
        # 2 小節目の最後にスネアのフィル
        if bar == 1:
            for s in range(8):
                place(drums, c, t0 + 2 * BEAT + s * BEAT / 4, 0.25 + 0.08 * s)
        if outro_last:
            pass

    # 最後の一撃: 63 拍目で和音と低音を伸ばす
    t_end = 63 * BEAT
    place(music, supersaw([midi(x) for x in (60, 64, 67, 72)], 1.0, 3200) * 1.0, t_end, 0.8)
    place(music, bass(36, 0.8), t_end, 1.0)
    place(drums, k, t_end, 1.0)

    # イントロの上昇音（ライザー）
    t = t_axis(2 * BAR)
    riser = bp(RNG.standard_normal(t.size), 400, 6000) * (t / t[-1]) ** 2 * 0.25
    place(fx, riser, 0.0)

    for tt, kind in SFX:
        place(fx, sfx(kind), max(tt, 0.0), 1.0)

    mix_l = drums * 0.95 + music * duck * 0.9 + arp * duck * 0.9 + fx
    mix_r = drums * 0.95 + music * duck * 0.9 + arp * duck * 0.75 + fx
    # アルペジオを少し左に、ハイハットの残響代わりに右へ少し遅らせる
    delay = int(0.012 * SR)
    mix_r[delay:] += 0.15 * drums[:-delay]
    stereo = np.stack([mix_l, mix_r])[:, :int(DURATION * SR)]
    # 最後の 0.4 秒でフェードアウト
    fade = int(0.4 * SR)
    stereo[:, -fade:] *= np.linspace(1, 0, fade)
    stereo = np.tanh(stereo * 1.2)
    stereo /= np.abs(stereo).max() / 0.89       # 約 -1 dBFS
    return stereo


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    x = render()
    wavfile.write(OUT, SR, (x.T * 32767).astype(np.int16))
    print(OUT, x.shape, float(np.abs(x).max()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
