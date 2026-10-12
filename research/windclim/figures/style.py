"""Shared figure styling: fonts, palettes, colormaps and axis furniture.

Colour is assigned by the job it does, not by taste:

* **Wind speed** is a magnitude, so it gets one hue light-to-dark (blue). Never a
  rainbow -- a rainbow invents boundaries the data does not have.
* **Wind direction** is genuinely circular, so it gets a *cyclic* map
  (``twilight``). A sequential map on a circular variable puts a false
  discontinuity at 0/360 deg, and that is the single most common error in this
  kind of figure.
* **Weeks W1-W4** are identities, so they get a fixed categorical order, never
  cycled. The four hues were validated for colour-vision deficiency separation;
  two of them sit below 3:1 against a white page, so lines carrying them are
  always directly labelled as well as legended.
* **Differences between regions** have a polarity, so they get a diverging map
  with a neutral grey middle.

Japanese labels need a CJK font, which matplotlib does not ship. TeX Live's
HaranoAji Gothic is used when present; otherwise the figure falls back rather
than failing, and says so.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib as mpl
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, ListedColormap

__all__ = [
    "CATEGORICAL",
    "CMAP_CONSTANCY",
    "CMAP_DIFF",
    "CMAP_DIRECTION",
    "CMAP_SPEED",
    "CYCLIC_CMAPS",
    "GRID_KW",
    "MASK_COLOR",
    "INK",
    "HALF_LABELS",
    "apply_style",
    "register_japanese_font",
]

log = logging.getLogger(__name__)

FONT_CANDIDATES = (
    Path("/usr/local/texlive/2024/texmf-dist/fonts/opentype/public/haranoaji/"
         "HaranoAjiGothic-Regular.otf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
)

#: Fixed categorical order. Assigned by slot, never cycled.
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")

#: Fallback only. The real labels travel with the dataset (``bin_labels``), so
#: a figure describes the binning the numbers were actually computed under
#: rather than whatever the code last happened to default to.
HALF_LABELS = ("前半 (1-15日)", "後半 (16日-月末)")

#: Single-hue magnitude ramp, light to dark.
_BLUE_STEPS = (
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
)
_NEUTRAL = "#f0efec"
_RED_POLE = "#8c1f1f"

INK = {
    "primary": "#0b0b0b",
    "secondary": "#52514e",
    "muted": "#8b8a84",
    "grid": "#e3e2de",
    "surface": "#fcfcfb",
}

GRID_KW = {"color": INK["grid"], "linewidth": 0.6, "zorder": 0}

CMAP_SPEED = LinearSegmentedColormap.from_list("windclim_speed", _BLUE_STEPS)
CMAP_CONSTANCY = LinearSegmentedColormap.from_list("windclim_constancy", _BLUE_STEPS)
CMAP_DIFF = LinearSegmentedColormap.from_list(
    "windclim_diff", [_BLUE_STEPS[-1], _BLUE_STEPS[6], _NEUTRAL, "#e34948", _RED_POLE]
)

#: Direction must use one of these. Asserted in the tests.
CYCLIC_CMAPS = frozenset({"twilight", "twilight_shifted", "hsv", "windclim_direction"})
#: Masked cells must read as "deliberately not shown", not as "no data". On a
#: near-white page an unset cell is invisible, so masked cells are painted a
#: definite grey that matches what the captions say.
MASK_COLOR = "#c9c8c3"

CMAP_DIRECTION = ListedColormap(
    mpl.colormaps["twilight"](np.linspace(0, 1, 256)), name="windclim_direction"
).with_extremes(bad=MASK_COLOR)

#: Below this constancy the mean direction is not worth drawing; it is masked.
CONSTANCY_MASK = 0.3


def register_japanese_font() -> str | None:
    """Make a CJK font available to matplotlib. Returns the family name, or None."""
    from matplotlib import font_manager

    for path in FONT_CANDIDATES:
        if not path.exists():
            continue
        try:
            font_manager.fontManager.addfont(str(path))
            return font_manager.FontProperties(fname=str(path)).get_name()
        except Exception as exc:  # noqa: BLE001 - a missing font must not stop a run
            log.warning("could not register %s: %s", path, exc)
    log.warning(
        "no CJK font found; Japanese labels will render as boxes. Looked in: %s",
        ", ".join(str(p) for p in FONT_CANDIDATES),
    )
    return None


def apply_style(japanese: bool = True) -> str | None:
    """Set the global matplotlib style. Returns the CJK family in use, if any."""
    family = register_japanese_font() if japanese else None
    mpl.rcParams.update(
        {
            "figure.facecolor": INK["surface"],
            "axes.facecolor": INK["surface"],
            "savefig.facecolor": INK["surface"],
            "axes.edgecolor": INK["muted"],
            "axes.linewidth": 0.8,
            "axes.labelcolor": INK["secondary"],
            "axes.titlecolor": INK["primary"],
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.grid": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK["secondary"],
            "ytick.color": INK["secondary"],
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "legend.frameon": False,
            "legend.fontsize": 8,
            "lines.linewidth": 2.0,
            "lines.markersize": 4.0,
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "font.size": 9,
        }
    )
    if family:
        mpl.rcParams["font.family"] = [family, "DejaVu Sans"]
    return family


def recessive_grid(ax, axis: str = "both") -> None:
    ax.set_axisbelow(True)
    ax.grid(True, axis=axis, **GRID_KW)
