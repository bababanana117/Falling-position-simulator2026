"""画面と音で共有するタイムライン。

BGM は 128 BPM で、1 小節 1.875 秒 × 16 小節 = 30 秒。2 小節ずつ 8 つのシーンにする。
効果音のタイミングもここで決めて、render.py と music.py の両方から読む。
"""

from __future__ import annotations

BPM = 128
BEAT = 60.0 / BPM
BAR = 4 * BEAT
DURATION = 16 * BAR          # 30.0 秒
FPS = 30
W, H = 1920, 1080

#: シーン名 → (開始, 終了) 秒
SCENES = {
    "intro": (0 * BAR, 2 * BAR),
    "balloon": (2 * BAR, 4 * BAR),
    "jet": (4 * BAR, 6 * BAR),
    "season": (6 * BAR, 8 * BAR),
    "roses": (8 * BAR, 10 * BAR),
    "map": (10 * BAR, 12 * BAR),
    "seto": (12 * BAR, 14 * BAR),
    "outro": (14 * BAR, 16 * BAR),
}


def beat(n: float) -> float:
    """曲の頭から n 拍目の時刻。"""
    return n * BEAT


#: 効果音。(時刻, 種類)。種類: pop / whoosh / burst / tick / ding / crash / swish
SFX: list[tuple[float, str]] = []

# シーンの切り替わりは whoosh
for _name, (t0, _t1) in list(SCENES.items())[1:]:
    SFX.append((t0 - 0.18, "whoosh"))

# 1. タイトル: 文字ごとのポップ
TITLE_CHARS = "上空の風を10年ぶん集めた"
TITLE_T0 = beat(0.5)
TITLE_STEP = 0.07
for k in range(0, len(TITLE_CHARS), 2):
    SFX.append((TITLE_T0 + k * TITLE_STEP, "pop"))
SFX.append((beat(4), "swish"))
SFX.append((beat(6), "pop"))

# 2. 気球: 上昇の swish、破裂、パラシュート
BALLOON_LAUNCH = SCENES["balloon"][0] + beat(0.25)
BALLOON_BURST = SCENES["balloon"][0] + beat(4.5)
SFX += [(BALLOON_LAUNCH, "swish"), (BALLOON_BURST, "burst"),
        (SCENES["balloon"][0] + beat(6), "pop")]

# 3. ジェット気流の棒グラフ: 拍ごとに 1 本
JET_T = [SCENES["jet"][0] + beat(0.5 + k) for k in range(3)]
SFX += [(t, "pop") for t in JET_T]
JET_BADGE = SCENES["jet"][0] + beat(4.5)
SFX.append((JET_BADGE, "ding"))

# 4. 季節の線
SEASON_DRAW = (SCENES["season"][0] + beat(0.25), SCENES["season"][0] + beat(4.25))
for k in range(8):
    SFX.append((SEASON_DRAW[0] + k * (SEASON_DRAW[1] - SEASON_DRAW[0]) / 8, "tick"))
SEASON_BADGE = SCENES["season"][0] + beat(4.75)
SFX.append((SEASON_BADGE, "pop"))

# 5. 風配図
ROSE_T = (SCENES["roses"][0] + beat(0.5), SCENES["roses"][0] + beat(2.5))
SFX += [(ROSE_T[0], "swish"), (ROSE_T[1], "swish")]
ROSE_TEXT = SCENES["roses"][0] + beat(5)
SFX.append((ROSE_TEXT, "pop"))

# 6. 地図
MAP_WINTER = SCENES["map"][0] + beat(0.5)
MAP_SUMMER = SCENES["map"][0] + beat(4.5)
SFX += [(MAP_WINTER, "swish"), (MAP_WINTER + beat(1), "pop"),
        (MAP_SUMMER, "swish"), (MAP_SUMMER + beat(1), "pop")]

# 7. 瀬戸内海
SETO_STAR = SCENES["seto"][0] + beat(0.25)
SETO_RAIN = (SCENES["seto"][0] + beat(0.75), SCENES["seto"][0] + beat(4.25))
SETO_P1 = SCENES["seto"][0] + beat(4.5)
SETO_P2 = SCENES["seto"][0] + beat(6)
SFX += [(SETO_STAR, "pop"), (SETO_P1, "ding"), (SETO_P2, "ding")]
for k in range(10):
    SFX.append((SETO_RAIN[0] + k * (SETO_RAIN[1] - SETO_RAIN[0]) / 10, "tick"))

# 8. 締め
OUTRO_TEXT = SCENES["outro"][0] + beat(0.5)
OUTRO_END = beat(63)
SFX += [(OUTRO_TEXT, "pop"), (OUTRO_TEXT + beat(1), "pop"), (OUTRO_END, "crash")]

SFX.sort()
