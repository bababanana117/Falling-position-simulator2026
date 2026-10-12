"""A figure comparing the reanalyses this project could have used.

The data chapter lists reasons for choosing JRA-3Q in prose. Two of those
reasons -- "the height is enough" and "the resolution is enough" -- are numbers,
and numbers are easier to check on a pair of axes than in a sentence.

Where the numbers come from
---------------------------
Only the JRA-3Q row is measured. Its grid spacing, level count and top level
are read straight off the files this pipeline downloaded, so they describe the
data actually used rather than a specification. Every other row is the
published specification of that product's **pressure-level** product, entered
by hand from the provider's documentation.

That distinction matters and the caption says it. A specification can be out of
date, and several of these products are still being extended; a reader planning
their own study should check the current figures rather than trust this table.

The comparison is also deliberately narrow. It asks only "can this product
describe a balloon flight over Japan", which is two questions -- does it reach
the burst altitude, and does it resolve the region -- and says nothing about
which reanalysis is better in general. ERA5 is the finer of the two leading
candidates and is not being criticised by sitting lower on the ceiling axis:
its pressure-level product simply stops at 1 hPa, which is still well above
anything a latex balloon reaches.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib.figure import Figure

from ..stats.altitude import isa_altitude_from_pressure
from .style import CATEGORICAL, INK, recessive_grid

__all__ = ["PRODUCTS", "Reanalysis", "fig_reanalysis_comparison"]


@dataclass(frozen=True)
class Reanalysis:
    """One product's pressure-level specification."""

    name: str
    centre: str
    deg: float                 # nominal horizontal spacing in degrees
    top_hpa: float             # highest (lowest-pressure) level in the product
    n_levels: int
    start_year: int
    end_year: int | None       # None means it is still being extended
    hours: float               # analysis interval
    measured: bool = False     # read from our own files rather than a spec sheet

    @property
    def km(self) -> float:
        """Grid spacing in km at 43 N, the latitude this project cares about."""
        return self.deg * 111.195 * float(np.cos(np.radians(43.0)))

    @property
    def top_km(self) -> float:
        return float(isa_altitude_from_pressure(self.top_hpa)) / 1000.0


#: Coarsest first, which is also the order the right-hand panel stacks in.
PRODUCTS: tuple[Reanalysis, ...] = (
    Reanalysis("NCEP/NCAR R1", "NCEP", 2.5, 10.0, 17, 1948, None, 6.0),
    Reanalysis("JRA-55", "気象庁", 1.25, 1.0, 37, 1958, 2023, 6.0),
    Reanalysis("MERRA-2", "NASA", 0.625, 0.1, 42, 1980, None, 3.0),
    Reanalysis("ERA5", "ECMWF", 0.25, 1.0, 37, 1940, None, 1.0),
    Reanalysis("JRA-3Q", "気象庁", 0.375, 0.01, 45, 1947, None, 6.0, measured=True),
)

#: What a balloon flight needs: reach the burst altitude, and resolve a region
#: a few hundred km across.
BURST_KM = 30.0
REGION_KM = 300.0


def fig_reanalysis_comparison(products=PRODUCTS, *, highlight: str = "JRA-3Q") -> Figure:
    """Two panels: what each product can reach, and when it covers."""
    fig = Figure(figsize=(10.2, 4.6), dpi=160)
    left, right = fig.subplots(1, 2, width_ratios=(1.15, 1.0))

    # --- left: resolution against ceiling ---------------------------------
    left.axhspan(0, BURST_KM, color=CATEGORICAL[1], alpha=0.10, zorder=0)
    left.annotate(
        f"破裂高度 {BURST_KM:.0f} km に届かない",
        xy=(0.98, BURST_KM - 1.5), xycoords=("axes fraction", "data"),
        ha="right", va="top", fontsize=8.5, color=CATEGORICAL[1],
    )
    left.axhline(BURST_KM, color=CATEGORICAL[1], linewidth=1.2, linestyle="--", zorder=2)

    for p in products:
        colour = INK["primary"] if p.name == highlight else CATEGORICAL[0]
        size = 150 if p.name == highlight else 70
        left.scatter(p.km, p.top_km, s=size, color=colour, zorder=4,
                     edgecolor=INK["surface"], linewidth=1.2)
        left.annotate(
            p.name, xy=(p.km, p.top_km), xytext=(0, 11), textcoords="offset points",
            ha="center", fontsize=9,
            fontweight="bold" if p.name == highlight else "normal",
            color=colour,
        )
    left.set_xscale("log")
    # Explicit ticks only: matplotlib's log minor labels (2x10^1 and friends)
    # crowd the axis and say nothing a reader of this figure wants.
    left.set_xticks([25, 50, 100, 200])
    left.set_xticklabels(["25", "50", "100", "200"])
    left.set_xticks([], minor=True)
    # Finer to the right, higher up: the top-right corner is the one that suits
    # this job, so "better for a balloon" is a direction rather than a lookup.
    left.set_xlim(260, 16)
    left.set_xlabel("水平格子間隔 [km]（北緯 43 度、細かいほうが右）")
    left.set_ylabel("気圧面プロダクトの上端 [km]")
    left.set_ylim(0, 100)
    left.set_title("届く高さと、解ける細かさ", fontsize=10, color=INK["secondary"])
    recessive_grid(left)

    # --- right: coverage ---------------------------------------------------
    now = 2026
    for i, p in enumerate(products):
        end = p.end_year or now
        colour = INK["primary"] if p.name == highlight else CATEGORICAL[0]
        right.barh(i, end - p.start_year, left=p.start_year, height=0.5,
                   color=colour, zorder=3)
        tail = "" if p.end_year is None else f"–{p.end_year}"
        right.annotate(
            f"{p.start_year}{tail}  {p.n_levels} 面  {p.hours:g} 時間ごと",
            xy=(end + 1.5, i), va="center", fontsize=8.5, color=INK["secondary"],
        )
    right.set_yticks(range(len(products)))
    right.set_yticklabels([p.name for p in products])
    right.set_xlim(1935, now + 46)
    right.set_xticks([1940, 1960, 1980, 2000, 2020])
    right.set_xlabel("対象期間")
    right.set_title("いつからいつまで", fontsize=10, color=INK["secondary"])
    recessive_grid(right, axis="x")
    for side in ("top", "right"):
        right.spines[side].set_visible(False)

    fig.suptitle("再解析プロダクトの比較（気圧面プロダクトの公表仕様）",
                 color=INK["primary"], fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig
