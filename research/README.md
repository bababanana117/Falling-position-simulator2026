# windclim — JRA-3Q wind climatology

What the wind usually does over Hokkaido and Wakayama, as a function of
**altitude, location and week of the year**, computed from ten years of the
JRA-3Q reanalysis.

## Why this exists

The simulator's two wind sources are both forecasts, and neither can answer a
planning question.

- `backend/bfps/core/wind.py:21` — Open-Meteo, whose pressure levels stop at
  **30 hPa (about 23.8 km)**. Above that the top level's wind is simply held
  constant. With a 30 km burst that gap is 17 % of the flight time.
- `frontend/src/api/tawhiri.ts:9` — SondeHub Tawhiri, i.e. GFS, valid from twelve
  hours ago to seven days ahead.

So there is no way to ask "if we launch from VOISING in the first half of March,
what is the wind likely to do between the ground and 35 km?". This package
answers that from JRA-3Q, which reaches 3 hPa (about 40 km) and goes back to
1947.

Its output is **not** wired into the web app. It produces data files, figures and
a report.

## Running it

```bash
conda env create -f environment.yml
conda activate jra3q

cd research                      # required: libnetcdf reads ./.dodsrc

python -m windclim.cli fetch --dry-run | wc -l     # 2160
python -m windclim.cli fetch --years 2016-2025     # ~2.5 h, resumable
python -m windclim.cli all --region wakayama
python -m windclim.cli all --region hokkaido
python -m windclim.cli compare
python -m windclim.cli validate --region wakayama   # is the signal there at all?
python -m windclim.cli fidelity --region wakayama   # ~7 min; flies 1.05 M trajectories
```

`fetch` is safe to interrupt and re-run: completed files are skipped, partial
ones are discarded and re-queued. `--verify` re-hashes instead of trusting the
recorded shape.

Tests:

```bash
pytest              # offline, ~550 tests, no network
pytest -m network   # checks the constants against the live GDEX archive
```

## How it works

| Stage | Module | What it does |
|---|---|---|
| fetch | `windclim/fetch/` | OPeNDAP hyperslab per source file into `data/raw/`, with an atomic write, a JSON sidecar and an append-only manifest |
| normalise | `windclim/fetch/normalize.py` | the single boundary: hyphenated names → `u`/`v`/`z`, latitude flipped to ascending, fill values → NaN, then a physical validation of every slab |
| aggregate | `windclim/stats/aggregate.py` | one calendar month at a time, all ten years at once, split into week bins |
| output | `windclim/outputs/` | NetCDF (canonical), Parquet (convenient), six CSV tables |
| figures | `windclim/figures/` | twelve figures, PNG and PDF |

### Decisions worth knowing about

**One fetch, both regions.** The server's cost is set by its internal chunking
(`anl_p` is chunked `(1, 23, 240, 480)`), so asking for two small boxes separately
costs it exactly what one containing box costs — it only doubles the requests. A
single master box, 30–48 N / 132–150 E, is downloaded and the regions are cut out
of it locally. Adding a third region later needs no network at all.

**OPeNDAP, not the kerchunk references.** GDEX publishes kerchunk references, and
they looked like the fast path. They are not: with that chunking, a client-side
byte-range read of even a tiny box pulls two whole chunks — roughly 9 MB
compressed — for each of the 14 610 analyses, about **260 GB**. Letting the server
decompress and cut turns that into about 7 MB per five-day file.

**Six workers.** The first guess was that concurrency would buy nothing, since
each request makes the server decompress ~420 MB. Measurement disagreed: one
worker took 13.7 s per file, three workers still averaged 13.7 s, six reached
4.3 s. Six is used because it is measurably faster and still a modest number of
connections on a public service.

**Moments are stored; shapes are derived.** The NetCDF holds `u_var`, `v_var` and
`uv_cov`, never an ellipse; `u_mean` and `v_mean`, never a direction. Directions
and ellipses are computed in `windclim/outputs/derive.py` at export time. This is
structural, not stylistic: because no direction ever reaches the accumulator,
the classic "average of 359° and 1° is 180°" error has nowhere to happen.

**`n_eff`, not `n`.** A week bin holds 280 six-hourly analyses, but consecutive
analyses six hours apart are nearly the same weather and a synoptic system takes
two to five days to pass. The effective count is typically 20–40, so every
uncertainty is built from `n_eff = n(1−r₁)/(1+r₁)` rather than `n`. Using `n`
would overstate confidence roughly threefold.

**Direction is masked below 0.3 constancy.** Over Japan the stratospheric wind
reverses around April–May and September–October. In those weeks the mean wind is
near zero with enormous variance, and a confident-looking arrow would be the most
misleading thing this pipeline could draw. Figure F7's wind roses are the honest
display for those weeks.

**No cartopy.** For a ten-degree box, plate carrée with the aspect corrected by
`1/cos(lat)` is honest to a few percent, and `ax.coastlines()` *downloads*
Natural Earth data at render time — a runtime network dependency inside a
pipeline whose premise is that it works offline. The coastline comes from
`frontend/public/geo/land.json`, which the web app already uses, so the figures
and the map agree.

### Week bins

`W1` = days 1–7, `W2` = 8–14, `W3` = 15–21, `W4` = 22 to the end of the month.
Not ISO weeks: these say the same days every year, which is how a campaign is
actually planned. The cost is that W4 is 7–10 days, so it holds more analyses
than the others — which is why `n` is stored beside every statistic and plotted
as figure F0. Expected counts over 2016–2025:

| bin | days | analyses |
|---|---|---|
| W1–W3 | 7 | 280 |
| January W4 | 10 | 400 |
| February W4 | 7 or 8 | 292 |
| April W4 | 9 | 360 |

## Is the signal actually there?

The week bin was chosen because it is how a campaign is planned, not because
anything said the data supports it. `windclim validate` asks the question
properly, by leave-one-year-out cross-validation: build the climatology from
nine years, predict the tenth, and plot the error against bin width. The
training error falls monotonically as bins narrow (that is overfitting); the
validation error bottoms out and rises again, and **its minimum is the finest
time unit the data supports**.

A weekday placebo runs first and is reported alongside every result. The free
atmosphere does not know what day of the week it is, so skill there would mean
the cross-validation is broken. It comes out at −0.0001 and −0.0002, while the
same machinery detects a planted weekday effect at skill > 0.9 — so the zero is
a real negative, not a blunt instrument.

| | Hokkaido | Wakayama |
|---|---|---|
| error with no seasonal information | 93.6 km | 118.2 km |
| best achievable | 78.1 km | 64.9 km |
| error reduction | 17 % | **45 %** |
| indistinguishable bin widths | **7–30 days** | **5–15 days** |
| 1 day, vs best | +2.22 km (+6.9 SE) | +1.50 km (+6.5 SE) |
| 7 days, vs best | +0.29 km (+1.4 SE) | +0.00 km (+0.0 SE) |
| 30 days, vs best | +0.08 km (+0.5 SE) | +1.61 km (+5.4 SE) |

**Daily resolution is not supported anywhere.** Wakayama does need the week —
a month is 5.4 standard errors worse. Hokkaido does not: a month is
indistinguishable from the best, so the weekly numbers there carry no more
information than the monthly ones.

Two findings sharpen this further:

- **A smooth curve beats the bins.** Six annual harmonics (a 30-day resolution)
  reach 64.2 km over Wakayama, below the best of any bin width. So what exists
  is a smooth 1–2 month seasonal cycle, and a weekly bin is a staircase
  approximation to it — not evidence of week-scale structure.
- **The answer depends on the season more than on anything else.** Within
  winter, knowing the sub-seasonal timing is worth *nothing* over Wakayama
  (0 % error reduction); in autumn it is worth 34 %. The week matters in the
  transition seasons, not in the depths of winter.

And on altitude: the climatology reduces the 850 hPa wind error by only 4–6 %.
**Launch-day surface wind has to come from a forecast, not from this.**

### Significant is not the same as useful

Over Hokkaido, three methods appear to disagree about whether the week adds
anything to the month:

| method | what it measures | answer |
|---|---|---|
| block permutation test | probability the week label carries *no* information | p = 0.007 |
| paired cross-validation | how much predicting by week actually improves | +0.5 SE (no gain) |
| split-half of the within-month residual | whether another decade shows the same weekly pattern | r = +0.19 |

They are not in conflict; they measure different things. With 14 610 samples a
vanishingly small effect is still significant. Had only the permutation test
been run, the honest-looking report would have said "the weekly signal over
Hokkaido is significant (p = 0.007)" — true, and misleading, because using the
week instead of the month improves the landing prediction by nothing at all.
Over Wakayama all three agree (p = 0.003, month is 5.4 SE worse, residual
r = +0.54). Choosing cross-validation over a p-value as the primary method is
what makes that distinction visible.

Reproduce any of this with `windclim validate --region <r>`; the tables land in
`out/csv/timescale_*.csv` and `validation_summary_*.txt`.

## Does the simulator match reality, and when?

`windclim fidelity` asks a second question the climatology cannot: **which
season does the prediction come true in?** It flies 1,051,992 trajectories
(10 years x 6-hourly x 72 launch cells) four ways and compares the landing
points.

The simulator freezes the wind at the launch point and the launch time. Both
freezes are removable — `trajectory.py:87-91` already receives the flight time
and throws it away, and the RK4 already threads the position through — so the
question is whether removing them would be worth the work.

**It would not.** The error from both freezes together is 2.8-5.3 km,
which is 2-5% of the flight. A launch slipping by one day moves the landing
point 30-50 km, an order of magnitude more, and the forecast error (which this
cannot measure, because that needs an archive of past forecasts rather than
past weather) is likely larger still.

Two findings that were not expected:

* **In winter the two freezes partly cancel.** Freezing both (5.3 km) is
  *better* than freezing place alone (6.1 km). In a westerly flow the weather
  pattern moves east at roughly the speed the payload does, so "the wind
  downstream, later" resembles "the wind here, now". In summer there is no
  travelling pattern and the two errors simply add.
* **Summer's wind anomalies persist for 10-17 days but its direction wanders
  four times as much as winter's** (21.9 deg/day vs 5.4 at 200 hPa). Both are
  true: the summer jet is weak, so the same anomaly turns it much further. The
  direction table is the one that matters operationally.

The answer to "which season" depends on what is being asked. Summer for the
smallest absolute miss (2.8 km, 63 km flight, 29.7 km per day of slip); winter
for proportional fidelity (2.0% of the flight, direction steadiest); avoid
spring, which is worst on every measure.

A by-product: `drift.displacements` sums `u_k T_k` straight into metres and has
no latitude in it, so it misses the changing `1/cos(lat)` factor as the payload
drifts north or south. Against the spherical integrator the gap is 0.44 km
median in a Wakayama winter, 3.45 km at worst over ten years. Every drift figure
in chapters 5 and 6 carries that much systematic error. It does not affect
week-to-week comparison; it does matter for a single flight.

Reproduce with `windclim fidelity --region wakayama`; tables land in
`out/csv/fidelity_*.csv` and `out/csv/variability_*.csv`.

## What came out of it

Numbers from the 2016-2025 run, for the flight the drift model assumes (5 m/s up,
burst at 30 km, 6 m/s sea-level-equivalent down; about 138 minutes).

**The Open-Meteo ceiling matters far less in winter, and far more in summer, than
the motivation above suggests.** Weighting each level by the time the payload
spends in it, the share of the horizontal displacement contributed by the layer
above 23.8 km is:

| | Jan | Apr | Jul | Aug | Nov |
|---|---|---|---|---|---|
| Hokkaido | 4.6 % | 4.9 % | **58 %** | 22 % | 7.1 % |
| Wakayama | 1.0 % | 3.6 % | **145 %** | 101 % | 2.0 % |

In winter the tropospheric jet is so much stronger that the missing layer barely
moves the answer. In summer it dominates — and Wakayama's 145 % is above 100 %
because the denominator is the *net* displacement: the stratospheric easterly
partly cancels the flow below, so ignoring it gets the direction wrong, not just
the distance. Summer is also when the flight is shortest and a launch is most
attractive, so the existing implementation is least reliable exactly when it
would be used.

**Flight distance, region mean:**

| | calmest week | roughest week | annual mean |
|---|---|---|---|
| Hokkaido | 56 km, Jul W3, bearing 118° | 234 km, Dec W1, bearing 72° | 143 km |
| Wakayama | 46 km, Aug W3, bearing **279°** | 289 km, Feb W1, bearing 86° | 158 km |

Wakayama's summer bearing is westward, inland; Hokkaido's is south-east, out to
sea. The two regions need different recovery plans in the same season.

**Other findings:**

- The ISA conversion in `backend/bfps/core/atmosphere.py` is off by up to 1048 m
  over Hokkaido in summer (531 m in winter), 811 m over Wakayama.
- Effective sample size is 17 % of the raw count: 280 six-hourly analyses carry
  about 50 independent observations.
- Over Hokkaido the within-region spread of mean wind speed reaches 36 m/s, so a
  single representative column does *not* describe it. Over Wakayama it is 13 m/s
  and one column is adequate.
- At 10 hPa in midwinter the wind over this longitude band is *easterly*, against
  the zonal-mean intuition, because the stratospheric Aleutian High sits over the
  North Pacific. A sanity check written for the zonal mean was wrong here.

## Outputs

```
out/netcdf/jra3q_windclim_<region>_2016-2025_v1.nc   canonical, CF-1.10
out/parquet/windclim/region=<r>/month=<m>/           long format, zstd
out/csv/                                             six curated tables
out/figures/<region>/                                F0-F10, PNG + PDF
out/figures/compare/                                 F11
out/figures/validation/                              V1-V6
out/figures/fidelity/                                G1-G7
```

`data/` is gitignored, and so is everything under `out/` except `out/csv/`. The
curated CSV tables and the report PDF are committed because they are small and
are the part a reader might want to check; the NetCDF (over 100 MB), Parquet and
figures belong in a release asset instead. `data_inventory.csv` is also left out
— it is one row per downloaded file, useful locally and noise in a diff.

## Licence

JRA-3Q is **CC BY-NC-SA 4.0**: non-commercial, share-alike, attribution required.
Everything produced here is a derivative work and carries the same licence, which
is *not* the licence of the rest of this repository — one of the reasons this
directory is kept separate from the deployed app. See `LICENSE-DATA.md`.
