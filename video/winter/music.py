"""~5 分のナレーション動画用 BGM と効果音を合成する（118 BPM、明るいハウス調）。

音源ファイルは使わず、すべて NumPy で作る。著作権の問題が起きない。
楽器・効果音の作り方は video/music.py（30 秒版）と同じ発想で、
セクション（intro / verse / build / drop / break / outro）ごとに
コード進行と楽器の密度を変えて、5 分聴いても単調にならないようにする。

使い方（ライブラリとして）:

    from music import render_bgm, sfx
    bgm = render_bgm(n_bars=150, sections=[(0, "intro"), (4, "verse"), ...], bpm=118.0)

単体で動かすと、各セクションの試聴用ファイルを build/ に書き出す。

    python video/winter/music.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 44100
HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEST_BUILD = BUILD / "test"  # 試聴・テスト用のダミー出力はここに置く（本番の build/ 直下とは分ける）
RNG = np.random.default_rng(11)


# --- 基本ユーティリティ ---------------------------------------------------------

def t_axis(sec: float, sr: int = SR) -> np.ndarray:
    return np.arange(int(sec * sr)) / sr


def lp(x, f, sr: int = SR, order: int = 2):
    return sosfilt(butter(order, f, "low", fs=sr, output="sos"), x)


def hp(x, f, sr: int = SR, order: int = 2):
    return sosfilt(butter(order, f, "high", fs=sr, output="sos"), x)


def bp(x, lo, hi, sr: int = SR, order: int = 2):
    hi = min(hi, sr / 2 - 100)
    return sosfilt(butter(order, [lo, hi], "band", fs=sr, output="sos"), x)


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


# --- 楽器（video/music.py と同じ作り方） -----------------------------------------

def kick(sr: int = SR) -> np.ndarray:
    t = t_axis(0.4, sr)
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / sr
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = hp(RNG.standard_normal(t.size), 2000, sr) * np.exp(-t * 300) * 0.3
    return np.tanh(1.6 * (body + click))


def clap(sr: int = SR) -> np.ndarray:
    t = t_axis(0.25, sr)
    env = np.zeros_like(t)
    for d in (0.0, 0.011, 0.022):
        env += (t >= d) * np.exp(-np.clip(t - d, 0, None) * (60 if d < 0.02 else 18))
    return bp(RNG.standard_normal(t.size), 900, 6000, sr) * env * 0.6


def hat(open_: bool = False, sr: int = SR) -> np.ndarray:
    t = t_axis(0.18 if open_ else 0.05, sr)
    env = np.exp(-t * (18 if open_ else 90))
    return hp(RNG.standard_normal(t.size), 7000, sr) * env * (0.25 if open_ else 0.2)


def saw(f: float, t: np.ndarray, detune: float = 0.0) -> np.ndarray:
    ph = (f * (1 + detune) * t + RNG.random()) % 1.0
    return 2 * ph - 1


def supersaw(freqs, dur: float, cutoff: float = 2600, sr: int = SR) -> np.ndarray:
    t = t_axis(dur, sr)
    x = np.zeros_like(t)
    for f in freqs:
        for d in (-0.012, -0.006, 0.0, 0.006, 0.012):
            x += saw(f, t, d)
    x /= 5 * len(freqs)
    env = np.minimum(t / 0.004, 1) * np.exp(-t * 7)
    return lp(x, cutoff, sr) * env


def pad(freqs, dur: float, cutoff: float = 1200, sr: int = SR) -> np.ndarray:
    """持続する和音（break・intro 用）。アタックとリリースをゆっくりにする。"""
    t = t_axis(dur, sr)
    if t.size == 0:
        return t
    x = np.zeros_like(t)
    for f in freqs:
        for d in (-0.01, -0.004, 0.0, 0.004, 0.01):
            x += saw(f, t, d)
    x /= 5 * len(freqs)
    x = lp(x, cutoff, sr)
    a_n = min(int(0.35 * sr), t.size // 2)
    r_n = min(int(0.5 * sr), t.size // 2)
    env = np.ones_like(t)
    if a_n > 0:
        env[:a_n] = np.linspace(0, 1, a_n) ** 1.5
    if r_n > 0:
        env[-r_n:] *= np.linspace(1, 0, r_n) ** 1.5
    return x * env * 0.8


def bass(n: int, dur: float, sr: int = SR) -> np.ndarray:
    t = t_axis(dur, sr)
    if t.size == 0:
        return t
    f = midi(n)
    x = 0.6 * saw(f, t) + 0.4 * np.sin(2 * np.pi * f / 2 * t)
    env = np.minimum(t / 0.003, 1) * np.exp(-t * 5)
    return lp(x, 700, sr) * env


def pluck(n: int, dur: float = 0.18, sr: int = SR) -> np.ndarray:
    t = t_axis(dur, sr)
    f = midi(n)
    x = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.sin(2 * np.pi * 2 * f * t) * 0.3
    return lp(x, 3500, sr) * np.exp(-t * 16)


# --- 効果音（video/music.py と同じ種類） -----------------------------------------

def sfx(kind: str, sr: int = SR) -> np.ndarray:
    if kind == "pop":
        t = t_axis(0.09, sr)
        f = 1400 * np.exp(-t * 40) + 350
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 45) * 0.55
    if kind == "tick":
        t = t_axis(0.04, sr)
        return np.sin(2 * np.pi * 2600 * t) * np.exp(-t * 120) * 0.25
    if kind in ("whoosh", "swish"):
        dur = 0.45 if kind == "whoosh" else 0.3
        t = t_axis(dur, sr)
        noise = RNG.standard_normal(t.size)
        out = np.zeros_like(t)
        n_blk = 12
        for k in range(n_blk):
            a, b = k * t.size // n_blk, (k + 1) * t.size // n_blk
            c = 300 * (12 ** (k / (n_blk - 1)))
            out[a:b] = bp(noise, c * 0.7, min(c * 1.6, sr / 2 - 100), sr)[a:b]
        env = np.sin(np.pi * t / dur) ** 2
        return out * env * (0.5 if kind == "whoosh" else 0.35)
    if kind == "burst":
        t = t_axis(0.5, sr)
        thump = np.sin(2 * np.pi * (80 + 60 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
        crack = hp(RNG.standard_normal(t.size), 1500, sr) * np.exp(-t * 35)
        return np.tanh(1.5 * (thump * 0.8 + crack * 0.9)) * 0.9
    if kind == "ding":
        t = t_axis(1.0, sr)
        x = sum(a * np.sin(2 * np.pi * 1318.5 * r * t) * np.exp(-t * d)
                for a, r, d in ((1.0, 1, 4), (0.5, 2.76, 7), (0.25, 5.4, 11)))
        return x * 0.35
    if kind == "crash":
        t = t_axis(2.0, sr)
        return hp(RNG.standard_normal(t.size), 4000, sr) * np.exp(-t * 2.2) * 0.45
    raise ValueError(kind)


# --- コード進行 ------------------------------------------------------------------
# 各要素は (ベースのルート音の MIDI 番号, 和音のボイシング(MIDI 番号のタプル))。
# セクションの種類ごとに違う進行を使うので、5 分聴いてもループ感が薄い。

PROG_VERSE = [(48, (60, 64, 67)), (43, (59, 62, 67)), (45, (60, 64, 69)), (41, (60, 65, 69))]   # C - G - Am - F
PROG_BUILD = [(41, (60, 65, 69)), (43, (59, 62, 67)), (40, (64, 67, 71)), (45, (60, 64, 69))]   # F - G - Em - Am
PROG_BREAK = [(45, (60, 64, 69)), (41, (60, 65, 69)), (48, (60, 64, 67)), (43, (59, 62, 67))]   # Am - F - C - G

PROG_BY_KIND = {
    "intro": PROG_VERSE,
    "verse": PROG_VERSE,
    "build": PROG_BUILD,
    "drop": PROG_BUILD,
    "break": PROG_BREAK,
    "outro": PROG_VERSE,
}

KINDS = ("intro", "verse", "build", "drop", "break", "outro")


def place(buf: np.ndarray, x: np.ndarray, t: float, gain: float = 1.0, sr: int = SR) -> None:
    i = int(t * sr)
    if i >= buf.shape[-1] or x.size == 0:
        return
    n = min(x.size, buf.shape[-1] - i)
    if n <= 0:
        return
    buf[..., i:i + n] += gain * x[:n]


def _runs(n_bars: int, sections: list[tuple[int, str]]) -> list[tuple[int, int, str, int]]:
    """sections を (開始小節, 終了小節, 種類, 同じ種類の何回目か) のリストにする。"""
    sections = sorted(sections, key=lambda s: s[0])
    seen: dict[str, int] = {}
    out = []
    for i, (start, kind) in enumerate(sections):
        if kind not in KINDS:
            raise ValueError(f"unknown section kind: {kind!r}")
        end = sections[i + 1][0] if i + 1 < len(sections) else n_bars
        end = max(end, start + 1)
        occ = seen.get(kind, 0)
        seen[kind] = occ + 1
        out.append((start, min(end, n_bars), kind, occ))
    return out


def render_bgm(n_bars: int, sections: list[tuple[int, str]], bpm: float = 118.0,
                sr: int = 44100) -> np.ndarray:
    """BGM 全体（ステレオ, shape=(2, N)）をレンダリングする。

    sections は (開始小節, 種類) のリスト。種類は
    intro / verse / build / drop / break / outro のいずれか。
    """
    beat = 60.0 / bpm
    bar = 4 * beat
    duration = n_bars * bar
    n = int(duration * sr) + int(3.0 * sr)  # 余韻ぶんの余白

    drums = np.zeros(n, dtype=np.float64)
    tonal = np.zeros(n, dtype=np.float64)
    arp = np.zeros(n, dtype=np.float64)
    fx = np.zeros(n, dtype=np.float64)
    duck = np.ones(n, dtype=np.float64)

    k_snd, c_snd, h_c, h_o = kick(sr), clap(sr), hat(False, sr), hat(True, sr)

    for start, end, kind, occ in _runs(n_bars, sections):
        prog = PROG_BY_KIND[kind]
        run_len = end - start
        variant = occ % 2  # 同じ種類が繰り返し出てきたときのパターン違い

        if kind == "intro":
            # フィルターがかかった和音のみ。キックなし。最初にライザーを 1 回。
            t0 = start * bar
            riser_dur = min(run_len * bar, 8.0)
            t = t_axis(riser_dur, sr)
            riser = bp(RNG.standard_normal(t.size), 400, 6000, sr) * (t / max(t[-1], 1e-9)) ** 2 * 0.22
            place(fx, riser, t0, 1.0, sr)
            for lb in range(run_len):
                root, chord = prog[lb % len(prog)]
                progress = (lb + 1) / run_len
                cutoff = 500 + 2200 * progress
                tb0 = (start + lb) * bar
                place(tonal, pad([midi(x) for x in chord], bar * 0.98, cutoff, sr), tb0, 0.32, sr)
                place(tonal, pad([midi(root)], bar * 0.98, min(cutoff, 500), sr), tb0, 0.25, sr)

        elif kind == "verse":
            for lb in range(run_len):
                bar_i = start + lb
                t0 = bar_i * bar
                root, chord = prog[lb % len(prog)]
                for b in range(4):
                    tb = t0 + b * beat
                    place(drums, k_snd, tb, 0.9 if b in (0, 2) else 0.65, sr)
                    # ソフトなハイハット。1〜4kHz 帯はあまり使わない（ナレーションのため）。
                    if variant == 0:
                        place(drums, h_c, tb + beat / 2, 0.55, sr)
                    else:
                        place(drums, h_c, tb + beat / 2, 0.45, sr)
                        place(drums, h_c, tb + beat / 4, 0.3, sr)
                    if b == 2 and variant == 1:
                        place(drums, c_snd, tb, 0.35, sr)
                # ベース: 裏拍中心。バリアントでリズムを変える。
                if variant == 0:
                    place(tonal, bass(root, beat * 0.9, sr), t0 + beat / 2, 0.55, sr)
                    place(tonal, bass(root, beat * 0.9, sr), t0 + 2.5 * beat, 0.5, sr)
                else:
                    for b in (0, 1, 2, 3):
                        place(tonal, bass(root, beat * 0.5, sr), t0 + b * beat, 0.4, sr)
                # 和音はミュート気味（カットオフを低く）。
                place(tonal, supersaw([midi(x) for x in chord], beat * 1.6, 1300, sr),
                      t0 + beat / 2, 0.28, sr)

        elif kind == "build":
            for lb in range(run_len):
                bar_i = start + lb
                t0 = bar_i * bar
                root, chord = prog[lb % len(prog)]
                progress = lb / max(run_len - 1, 1)
                for b in range(4):
                    tb = t0 + b * beat
                    place(drums, k_snd, tb, 1.0, sr)
                    place(drums, h_o if (b % 2 == 0 and progress > 0.5) else h_c,
                          tb + beat / 2, 0.6 + 0.3 * progress, sr)
                    if progress > 0.35:
                        place(drums, h_c, tb + beat / 4, 0.3 * progress, sr)
                        place(drums, h_c, tb + 3 * beat / 4, 0.3 * progress, sr)
                    if b in (1, 3) and progress > 0.4:
                        place(drums, c_snd, tb, 0.5 + 0.3 * progress, sr)
                place(tonal, bass(root, beat / 2 * 0.9, sr), t0 + beat / 2, 0.7, sr)
                place(tonal, bass(root, beat / 2 * 0.9, sr), t0 + 2.5 * beat, 0.6, sr)
                cutoff = 1400 + 1800 * progress
                place(tonal, supersaw([midi(x) for x in chord], beat * 0.9, cutoff, sr),
                      t0 + beat / 2, 0.35 + 0.15 * progress, sr)
                # アルペジオ
                notes = [x + 12 for x in chord] + [chord[0] + 24]
                steps = 8 if (variant == 0) else 16
                for s in range(steps):
                    place(arp, pluck(notes[s % len(notes)], sr=sr), t0 + s * beat * 4 / steps,
                          0.18 + 0.1 * progress, sr)
                # 最後の小節はスネア(クラップ)ロールでドロップへつなぐ
                if lb == run_len - 1:
                    for s in range(16):
                        g = 0.15 + 0.45 * (s / 15) ** 1.5
                        place(drums, c_snd, t0 + s * beat / 4, g, sr)

        elif kind == "drop":
            for lb in range(run_len):
                bar_i = start + lb
                t0 = bar_i * bar
                root, chord = prog[lb % len(prog)]
                for b in range(4):
                    tb = t0 + b * beat
                    place(drums, k_snd, tb, 1.0, sr)
                    if b in (1, 3):
                        place(drums, c_snd, tb, 0.85, sr)
                    place(drums, h_o if b % 2 else h_c, tb + beat / 2, 0.8, sr)
                    place(drums, h_c, tb + beat / 4, 0.4, sr)
                    place(drums, h_c, tb + 3 * beat / 4, 0.4, sr)
                if variant == 0:
                    place(tonal, bass(root, beat / 2 * 0.9, sr), t0 + beat / 2, 0.85, sr)
                    place(tonal, bass(root, beat / 2 * 0.9, sr), t0 + 2.5 * beat, 0.75, sr)
                else:
                    for b in range(4):
                        place(tonal, bass(root, beat / 2 * 0.85, sr), t0 + b * beat, 0.6, sr)
                place(tonal, supersaw([midi(x) for x in chord], beat * 0.45, 2700, sr),
                      t0 + beat / 2, 0.5, sr)
                # アルペジオは控えめに、密度を上げすぎない
                if lb % 2 == variant:
                    notes = [x + 12 for x in chord] + [chord[0] + 24]
                    for s in range(8):
                        place(arp, pluck(notes[s % len(notes)], sr=sr), t0 + s * beat / 2, 0.2, sr)

        elif kind == "break":
            # パッドだけ。スカスカにする。
            chord_bars = 2  # 2 小節に 1 回コードを変える
            lb = 0
            while lb < run_len:
                span = min(chord_bars, run_len - lb)
                t0 = (start + lb) * bar
                root, chord = prog[(lb // chord_bars) % len(prog)]
                place(tonal, pad([midi(x) for x in chord], bar * span * 0.95, 900, sr), t0, 0.4, sr)
                place(tonal, pad([midi(root - 12)], bar * span * 0.95, 350, sr), t0, 0.3, sr)
                if variant == 1:
                    place(drums, h_o, t0 + beat * 0.5, 0.2, sr)
                lb += span

        elif kind == "outro":
            t0 = start * bar
            tail = run_len * bar
            root, chord = prog[0]
            place(tonal, pad([midi(x) for x in chord] + [midi(chord[0] + 12)], tail, 2200, sr), t0, 0.55, sr)
            place(tonal, bass(root, min(tail, 1.2), sr), t0, 0.9, sr)
            place(drums, k_snd, t0, 1.0, sr)
            place(fx, sfx("crash", sr), t0, 0.8, sr)

        # サイドチェイン風のダッキング: キックのたびに一瞬音量を落とす（verse/build/drop のみ意味を持つ）
        if kind in ("verse", "build", "drop"):
            for lb in range(run_len):
                t0 = (start + lb) * bar
                for b in range(4):
                    tb = t0 + b * beat
                    i = int(tb * sr)
                    m = min(int(0.2 * sr), n - i)
                    if m > 0:
                        duck[i:i + m] = np.minimum(duck[i:i + m], 0.4 + 0.6 * np.linspace(0, 1, m) ** 1.5)

    mix_l = drums * 0.95 + tonal * duck * 0.9 + arp * duck * 0.9 + fx
    mix_r = drums * 0.95 + tonal * duck * 0.9 + arp * duck * 0.75 + fx
    delay = int(0.012 * sr)
    mix_r[delay:] += 0.12 * drums[:-delay]
    stereo = np.stack([mix_l, mix_r])[:, :int(duration * sr)]
    fade = min(int(0.4 * sr), stereo.shape[-1])
    if fade > 0:
        stereo[:, -fade:] *= np.linspace(1, 0, fade)
    stereo = np.tanh(stereo * 1.2)
    peak = np.abs(stereo).max()
    if peak > 0:
        stereo /= peak / 0.89  # 約 -1 dBFS
    return stereo


def main() -> int:
    """各セクション種類の試聴用ファイルを書き出す(耳で確認する用、テスト専用ディレクトリに置く)。"""
    TEST_BUILD.mkdir(parents=True, exist_ok=True)
    bpm = 118.0
    for kind in KINDS:
        n_bars = 8
        x = render_bgm(n_bars, [(0, kind)], bpm=bpm)
        out = TEST_BUILD / f"preview_{kind}_standalone.wav"
        wavfile.write(out, SR, (x.T * 32767).astype(np.int16))
        print(out, x.shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
