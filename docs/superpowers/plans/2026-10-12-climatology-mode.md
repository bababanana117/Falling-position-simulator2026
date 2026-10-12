# 統計モード（気候値による落下予測）実装計画

> **実装する人（エージェント）へ:** この計画はタスクごとに進める。superpowers:subagent-driven-development（推奨）か superpowers:executing-plans を使う。各手順はチェックボックス（`- [ ]`）で進み具合を記録する。

**目的:** 打ち上げ日時が Tawhiri の予報窓（+7 日）より先のとき、日本全国の統計風 DuckDB から落下点の分布と平均の軌道を出す。

**構成:** FastAPI バックエンドに `bfps/climatology/`（DuckDB 読み出し・純粋な計算・平均軌道）と `POST /api/climatology/predict` を足す。フロントエンドは発射時刻を「予報 / 統計 / エラー」に分け、統計のときはこの API を呼び、結果を既存の `Flight`・モンテカルロの落下点の型に直して既存の表示（楕円・ヒートマップ・安全判定）にそのまま流す。

**使う技術:** Python 3.12, FastAPI, numpy, duckdb (Python), pytest / React 19, TypeScript, Zustand, vitest.

**設計書:** `docs/superpowers/specs/2026-10-12-climatology-mode-design.md`

## 全体の決まりごと

- DuckDB は `v2/jra3q_japan_wind_2016-2025_v2.duckdb`（約 1.9 GB、git 管理外）。パスは環境変数 `BFPS_CLIMATOLOGY_DB` で変えられる。既定は `../v2/jra3q_japan_wind_2016-2025_v2.duckdb`（`backend/` から見た相対パス）。
- DuckDB は読み取り専用で開く。
- 半月ビン: JST の日付で 1–15 日が前半（bin=1）、16 日以降が後半（bin=2）。`timebin_id = (month - 1) * 2 + (bin - 1)`。
- 標準の飛行（ρ を解く基準）: 上昇 5 m/s・破裂 30000 m・降下 6 m/s（海面換算）・打ち上げ高度 0 m。
- 降下速度: $d\sqrt{\rho_0/\rho(z)}$、$\rho$ は `bfps.core.atmosphere.density_isa`、$\rho_0$ は `RHO0_ISA`、$\rho$ の下限 1e-4。
- 標本数: 10–2000、既定 500。乱数の種: 既定 42。
- 最寄り格子点が 60 km より遠ければ 422。DuckDB が無ければ 503「統計データベースが見つかりません」。
- 予報窓: 現在 −12 時間〜+7 日。+7 日より先が統計モード、−12 時間より前はエラー（今と同じ文言）。
- 統計モードの帯の文言: 「統計モード（気候値・{label}、2016–2025 年）— 予報ではありません」
- バックエンドが無いとき（`VITE_API_BASE` 未設定）の文言: 「統計モードにはバックエンドが必要です（VITE_API_BASE を設定してください）」
- 毎時モード・最適化・感度解析・float プロファイルは変更しない。
- コメント・docstring は日本語、既存のファイルの書き方に合わせる。

---

## ファイルの構成

```
backend/
  pyproject.toml                         modify: duckdb を依存に追加
  bfps/config.py                         modify: climatology_db を追加
  bfps/climatology/__init__.py           create
  bfps/climatology/model.py              create: 純粋な計算（層の時間・平均・共分散・ρ・標本・ENU→緯度経度）
  bfps/climatology/store.py              create: DuckDB 読み出し（格子点・時期・層・fact_drift）
  bfps/climatology/trajectory.py         create: 平均の軌道
  bfps/climatology/predict.py            create: 上の 3 つを組み合わせる
  bfps/models/schemas.py                 modify: ClimatologyRequest / ClimatologyResponse
  bfps/api/routes_climatology.py         create: POST /api/climatology/predict
  bfps/main.py                           modify: router 登録
  tests/climatology_fixture.py           create: 合成 DuckDB を作る関数
  tests/test_climatology_model.py        create
  tests/test_climatology_store.py        create
  tests/test_climatology_api.py          create
frontend/src/
  time/forecastWindow.ts                 create: classifyLaunchTime
  time/forecastWindow.test.ts            create
  api/climatology.ts                     create: 型・requestClimatology・変換関数
  api/climatology.test.ts                create
  hooks/useRunPrediction.ts              modify: 単発の実行を分岐
  mc/useMonteCarlo.ts                    modify: runClimatology を追加
  components/mc/MonteCarloPanel.tsx      modify: 分岐と注意書き
  store/resultsStore.ts                  modify: mode と climatologyInfo
  components/ScenarioInfo.tsx            modify: 帯
README.md                                modify: 統計モードの説明
```

---

### タスク 0: バックエンドの開発環境

**ファイル:**
- 変更: `backend/pyproject.toml`

`uv` はこの環境に無い。`backend/.venv`（git 管理外、`backend/.gitignore` に `.venv/` あり）を作って使う。

- [ ] **手順 1: duckdb を依存に足す**

`backend/pyproject.toml` の `dependencies` に 1 行足す:

```toml
    "joblib>=1.4",
    "duckdb>=1.1",
]
```

- [ ] **手順 2: 仮想環境を作って入れる**

```bash
cd backend
python3.12 -m venv .venv || python3 -m venv .venv
.venv/bin/pip install -q -e . pytest pytest-asyncio ruff
.venv/bin/python -c "import duckdb, fastapi; print(duckdb.__version__)"
```

期待する結果: duckdb のバージョンが表示される。

- [ ] **手順 3: 既存のテストが通ることを確かめる**

実行: `cd backend && .venv/bin/pytest -q`
期待する結果: すべて成功（network マーカーは除外）。

- [ ] **手順 4: コミット**

```bash
git add backend/pyproject.toml
git commit -m "build(backend): add duckdb dependency for climatology mode"
```

---

### タスク 1: 純粋な計算（model.py）

**ファイル:**
- 新規: `backend/bfps/climatology/__init__.py`（空）
- 新規: `backend/bfps/climatology/model.py`
- テスト: `backend/tests/test_climatology_model.py`

**受け渡し:**
- Produces:
  - `FlightSettings(ascent_rate: float, burst_altitude: float, descent_rate: float, launch_altitude: float = 0.0)` (変更不可の dataclass)
  - `STANDARD_FLIGHT: FlightSettings`（5.0, 30000.0, 6.0, 0.0）
  - `LevelStats(alt_m, u_mean, v_mean, u_var, v_var, uv_cov)`（すべて shape (L,) の np.ndarray、高度の低い順）
  - `layer_seconds(alt_m: np.ndarray, f: FlightSettings) -> np.ndarray`（shape (L,)）
  - `mean_drift(levels: LevelStats, T: np.ndarray) -> tuple[float, float]`（東, 北 [m]）
  - `drift_covariance(levels: LevelStats, T: np.ndarray, rho: float) -> np.ndarray`（2×2 [m²]）
  - `solve_rho(levels: LevelStats, T_std: np.ndarray, east_var: float, north_var: float) -> float`
  - `sample_offsets(mean: tuple[float, float], cov: np.ndarray, n: int, seed: int | None) -> np.ndarray`（shape (n, 2)、東・北 [m]）
  - `offset_to_latlon(lat0: float, lon0: float, east_m: np.ndarray, north_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]`

- [ ] **手順 1: 失敗するテストを書く**

`backend/tests/test_climatology_model.py`:

```python
import numpy as np
import pytest

from bfps.climatology.model import (
    STANDARD_FLIGHT,
    FlightSettings,
    LevelStats,
    drift_covariance,
    layer_seconds,
    mean_drift,
    offset_to_latlon,
    sample_offsets,
    solve_rho,
)

ALT = np.array([100.0, 1500.0, 5000.0, 10000.0, 16000.0, 24000.0, 31000.0, 40000.0])


def levels(u=10.0, v=0.0, su=3.0, sv=2.0, c=0.0):
    n = ALT.size
    return LevelStats(
        alt_m=ALT,
        u_mean=np.full(n, u),
        v_mean=np.full(n, v),
        u_var=np.full(n, su**2),
        v_var=np.full(n, sv**2),
        uv_cov=np.full(n, c),
    )


def test_layer_seconds_ascent_only_matches_rise_time():
    # 降下を非常に速くすると、滞在時間の合計は上昇時間 (破裂高度 - 打ち上げ高度) / 上昇速度 に近づく
    f = FlightSettings(ascent_rate=5.0, burst_altitude=30000.0, descent_rate=1e6)
    T = layer_seconds(ALT, f)
    assert T.shape == ALT.shape
    assert T.sum() == pytest.approx(30000.0 / 5.0, rel=1e-3)
    assert T[-1] == 0.0  # 40 km の層は破裂高度より上


def test_layer_seconds_respects_launch_altitude():
    f = FlightSettings(ascent_rate=5.0, burst_altitude=30000.0, descent_rate=1e6,
                       launch_altitude=2000.0)
    T = layer_seconds(ALT, f)
    assert T.sum() == pytest.approx((30000.0 - 2000.0) / 5.0, rel=1e-3)


def test_mean_drift_constant_wind():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    e, n = mean_drift(levels(u=10.0, v=-2.0), T)
    assert e == pytest.approx(10.0 * T.sum())
    assert n == pytest.approx(-2.0 * T.sum())


def test_covariance_limits():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels(su=3.0, sv=2.0)
    indep = drift_covariance(lv, T, 0.0)
    full = drift_covariance(lv, T, 1.0)
    assert indep[0, 0] == pytest.approx((T**2).sum() * 9.0)
    assert full[0, 0] == pytest.approx((T.sum() * 3.0) ** 2)
    assert full[1, 1] == pytest.approx((T.sum() * 2.0) ** 2)
    assert indep[0, 1] == pytest.approx(0.0, abs=1e-6)


def test_solve_rho_recovers_known_value():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels(su=4.0, sv=3.0, c=1.5)
    cov = drift_covariance(lv, T, 0.42)
    assert solve_rho(lv, T, cov[0, 0], cov[1, 1]) == pytest.approx(0.42, abs=1e-9)


def test_solve_rho_is_clipped():
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    lv = levels()
    assert solve_rho(lv, T, 0.0, 0.0) == 0.0
    assert solve_rho(lv, T, 1e20, 1e20) == 1.0


def test_sample_offsets_moments():
    cov = np.array([[4.0e8, 1.0e8], [1.0e8, 2.0e8]])
    s = sample_offsets((1.0e5, -2.0e4), cov, 20000, seed=1)
    assert s.shape == (20000, 2)
    assert s.mean(axis=0) == pytest.approx([1.0e5, -2.0e4], rel=0.02, abs=500)
    assert np.cov(s.T) == pytest.approx(cov, rel=0.05)


def test_offset_to_latlon_one_degree_north():
    lat, lon = offset_to_latlon(33.0, 130.0, np.array([0.0]), np.array([111195.0]))
    assert lat[0] == pytest.approx(34.0, abs=1e-3)
    assert lon[0] == pytest.approx(130.0, abs=1e-9)
```

- [ ] **手順 2: 失敗を確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_model.py -q`
期待する結果: 失敗（`ModuleNotFoundError: No module named 'bfps.climatology'`）

- [ ] **手順 3: 実装する**

`backend/bfps/climatology/__init__.py`: 空ファイル。

`backend/bfps/climatology/model.py`:

```python
"""統計モードの計算（DuckDB に依らない純粋な関数）。

落下点の東・北の移動は、層 k の平均風と滞在時間 T_k の和になる。散らばりは、層ごとの風の
共分散 Σ_k と、層どうしの相関 ρ（一定）から作る。ρ は標準の飛行の実際の散らばり
（DuckDB の fact_drift）を再現するように解く。式は spec の「計算の方法」を参照。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.atmosphere import RHO0_ISA, density_isa

M_PER_DEG = 111195.0


@dataclass(frozen=True)
class FlightSettings:
    ascent_rate: float
    burst_altitude: float
    descent_rate: float          # 海面換算
    launch_altitude: float = 0.0


STANDARD_FLIGHT = FlightSettings(5.0, 30000.0, 6.0, 0.0)


@dataclass(frozen=True)
class LevelStats:
    """1 格子点・1 時期の気圧面ごとの統計。すべて高度の低い順。"""
    alt_m: np.ndarray
    u_mean: np.ndarray
    v_mean: np.ndarray
    u_var: np.ndarray
    v_var: np.ndarray
    uv_cov: np.ndarray


def descent_speed(alt_m: np.ndarray, sea_level_rate: float) -> np.ndarray:
    rho = np.array([max(density_isa(max(float(a), 0.0)), 1e-4) for a in alt_m])
    return sea_level_rate * np.sqrt(RHO0_ISA / rho)


def layer_seconds(alt_m: np.ndarray, f: FlightSettings) -> np.ndarray:
    """各気圧面の層（隣の面との中点で区切る）に、上昇と降下で合わせて何秒いるか。"""
    alt = np.asarray(alt_m, dtype=float)
    mid = 0.5 * (alt[:-1] + alt[1:])
    lower = np.concatenate([[-1.0e4], mid])
    upper = np.concatenate([mid, [1.0e5]])
    up = np.maximum(np.clip(upper, f.launch_altitude, f.burst_altitude)
                    - np.clip(lower, f.launch_altitude, f.burst_altitude), 0.0)
    down = np.maximum(np.clip(upper, 0.0, f.burst_altitude)
                      - np.clip(lower, 0.0, f.burst_altitude), 0.0)
    return up / f.ascent_rate + down / descent_speed(alt, f.descent_rate)


def mean_drift(levels: LevelStats, T: np.ndarray) -> tuple[float, float]:
    return float((T * levels.u_mean).sum()), float((T * levels.v_mean).sum())


def _sqrt_2x2(u_var: float, v_var: float, c: float) -> np.ndarray:
    """2×2 の共分散行列の対称な平方根（負の固有値は 0 にする）。"""
    w, q = np.linalg.eigh(np.array([[u_var, c], [c, v_var]]))
    return (q * np.sqrt(np.clip(w, 0.0, None))) @ q.T


def _parts(levels: LevelStats, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """独立な部分 A = Σ T_k² Σ_k と、完全相関の部分 B = M Mᵀ（M = Σ T_k L_k）。"""
    A = np.zeros((2, 2))
    M = np.zeros((2, 2))
    for k in range(T.size):
        if T[k] == 0.0:
            continue
        S = np.array([[levels.u_var[k], levels.uv_cov[k]],
                      [levels.uv_cov[k], levels.v_var[k]]])
        A += T[k] ** 2 * S
        M += T[k] * _sqrt_2x2(levels.u_var[k], levels.v_var[k], levels.uv_cov[k])
    return A, M @ M.T


def drift_covariance(levels: LevelStats, T: np.ndarray, rho: float) -> np.ndarray:
    A, B = _parts(levels, T)
    return (1.0 - rho) * A + rho * B


def solve_rho(levels: LevelStats, T_std: np.ndarray, east_var: float,
              north_var: float) -> float:
    """標準の飛行の分散（fact_drift）を再現する ρ。東西・南北で解いて平均し 0〜1 に収める。"""
    A, B = _parts(levels, T_std)
    vals = []
    for i, obs in ((0, east_var), (1, north_var)):
        den = B[i, i] - A[i, i]
        if abs(den) > 1e-9 * max(B[i, i], 1.0):
            vals.append((obs - A[i, i]) / den)
    if not vals:
        return 0.0
    return float(np.clip(np.mean(vals), 0.0, 1.0))


def sample_offsets(mean: tuple[float, float], cov: np.ndarray, n: int,
                   seed: int | None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.multivariate_normal(np.asarray(mean, dtype=float), cov, size=n,
                                   method="eigh")


def offset_to_latlon(lat0: float, lon0: float, east_m: np.ndarray,
                     north_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = lat0 + np.asarray(north_m) / M_PER_DEG
    lon = lon0 + np.asarray(east_m) / (M_PER_DEG * np.cos(np.radians(lat0)))
    return lat, lon
```

- [ ] **手順 4: テストが通ることを確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_model.py -q`
期待する結果: 8 件成功

- [ ] **手順 5: コミット**

```bash
git add backend/bfps/climatology/__init__.py backend/bfps/climatology/model.py backend/tests/test_climatology_model.py
git commit -m "feat(backend): climatology drift model (mean, covariance, layer correlation)"
```

---

### タスク 2: DuckDB の読み出し（store.py）と合成 DB

**ファイル:**
- 新規: `backend/bfps/climatology/store.py`
- 新規: `backend/tests/climatology_fixture.py`
- テスト: `backend/tests/test_climatology_store.py`

**受け渡し:**
- 使うもの: `LevelStats`（タスク 1）
- Produces:
  - `class ClimatologyStore`: `__init__(self, path: str | Path)`（無ければ `FileNotFoundError`）
    - `nearest_cell(lat: float, lon: float) -> tuple[int, float, float, float]`（cell_id, lat, lon, distance_km）
    - `levels(cell_id: int, timebin_id: int) -> LevelStats`（結果をキャッシュする）
    - `drift_var(cell_id: int, timebin_id: int) -> tuple[float, float]`（east_var_m2, north_var_m2）
  - `timebin_for(dt_utc: datetime) -> tuple[int, int, int, str]`（timebin_id, month, bin, label 例 "1月前半"）
  - `tests/climatology_fixture.py`: `make_db(path, *, u=10.0, v=0.0, su=3.0, sv=2.0, c=0.0, rho=0.5) -> None`
    （格子 2×2 = 北緯 33.0/33.5 × 東経 130.0/130.5、全 24 時期、高度は model テストと同じ 8 面、
    fact_drift の分散は標準の飛行・指定の ρ で `drift_covariance` から作る）

- [ ] **手順 1: 合成 DB を作る関数を書く**

`backend/tests/climatology_fixture.py`:

```python
"""テスト用の小さな統計 DuckDB（本物と同じ列名の一部だけを持つ）。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from bfps.climatology.model import (
    STANDARD_FLIGHT,
    LevelStats,
    drift_covariance,
    layer_seconds,
)

ALT = np.array([100.0, 1500.0, 5000.0, 10000.0, 16000.0, 24000.0, 31000.0, 40000.0])
LEVEL_HPA = np.array([1000.0, 850.0, 500.0, 250.0, 100.0, 30.0, 10.0, 3.0])
CELLS = [(0, 33.0, 130.0), (1, 33.0, 130.5), (2, 33.5, 130.0), (3, 33.5, 130.5)]


def make_db(path: str | Path, *, u: float = 10.0, v: float = 0.0, su: float = 3.0,
            sv: float = 2.0, c: float = 0.0, rho: float = 0.5) -> None:
    n = ALT.size
    lv = LevelStats(ALT, np.full(n, u), np.full(n, v), np.full(n, su**2),
                    np.full(n, sv**2), np.full(n, c))
    T = layer_seconds(ALT, STANDARD_FLIGHT)
    cov = drift_covariance(lv, T, rho)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE dim_grid (cell_id SMALLINT, lat DOUBLE, lon DOUBLE)")
    con.executemany("INSERT INTO dim_grid VALUES (?, ?, ?)", CELLS)
    con.execute("""CREATE TABLE fact_wind (timebin_id SMALLINT, cell_id SMALLINT,
        level_hpa DOUBLE, alt_geom_mean_m DOUBLE, u_mean DOUBLE, v_mean DOUBLE,
        u_var DOUBLE, v_var DOUBLE, uv_cov DOUBLE)""")
    con.execute("""CREATE TABLE fact_drift (timebin_id SMALLINT, cell_id SMALLINT,
        east_var_m2 DOUBLE, north_var_m2 DOUBLE)""")
    rows, drows = [], []
    for tb in range(24):
        for cid, _, _ in CELLS:
            for k in range(n):
                rows.append((tb, cid, LEVEL_HPA[k], ALT[k], u, v, su**2, sv**2, c))
            drows.append((tb, cid, float(cov[0, 0]), float(cov[1, 1])))
    con.executemany("INSERT INTO fact_wind VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.executemany("INSERT INTO fact_drift VALUES (?, ?, ?, ?)", drows)
    con.close()
```

- [ ] **手順 2: 失敗するテストを書く**

`backend/tests/test_climatology_store.py`:

```python
from datetime import datetime, timezone

import numpy as np
import pytest

from bfps.climatology.store import ClimatologyStore, timebin_for
from climatology_fixture import ALT, make_db


@pytest.fixture()
def store(tmp_path):
    p = tmp_path / "clim.duckdb"
    make_db(p, u=12.0, rho=0.4)
    return ClimatologyStore(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ClimatologyStore(tmp_path / "none.duckdb")


def test_nearest_cell(store):
    cid, lat, lon, dist = store.nearest_cell(33.45, 130.40)
    assert cid == 3 and lat == 33.5 and lon == 130.5
    assert 5.0 < dist < 15.0


def test_levels_sorted_by_altitude(store):
    lv = store.levels(3, 0)
    assert np.all(np.diff(lv.alt_m) > 0)
    assert lv.alt_m == pytest.approx(ALT)
    assert lv.u_mean == pytest.approx(np.full(ALT.size, 12.0))


def test_drift_var(store):
    ev, nv = store.drift_var(3, 5)
    assert ev > 0 and nv > 0


@pytest.mark.parametrize("iso,expected", [
    ("2027-01-10T03:00:00+00:00", (0, 1, 1, "1月前半")),
    ("2027-01-15T14:59:00+00:00", (0, 1, 1, "1月前半")),   # JST 1/15 23:59
    ("2027-01-15T15:00:00+00:00", (1, 1, 2, "1月後半")),   # JST 1/16 00:00
    ("2027-12-31T15:30:00+00:00", (0, 1, 1, "1月前半")),   # JST 2028/1/1
    ("2027-02-28T00:00:00+00:00", (3, 2, 2, "2月後半")),
])
def test_timebin_for(iso, expected):
    assert timebin_for(datetime.fromisoformat(iso)) == expected


def test_timebin_naive_is_utc():
    assert timebin_for(datetime(2027, 7, 20, 0, 0)) == (13, 7, 2, "7月後半")
    assert timebin_for(datetime(2027, 7, 20, 0, 0, tzinfo=timezone.utc))[0] == 13
```

`backend/tests/conftest.py` が無ければ作り、tests ディレクトリを import できるようにする:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
```

- [ ] **手順 3: 失敗を確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_store.py -q`
期待する結果: 失敗（`No module named 'bfps.climatology.store'`）

- [ ] **手順 4: 実装する**

`backend/bfps/climatology/store.py`:

```python
"""統計風 DuckDB（JRA-3Q 2016–2025、日本全国 v2）の読み出し。

読み取り専用で 1 つの接続を使い回す。格子点は dim_grid を起動時に読み込み、最寄りは
numpy で探す（本物の DB のマクロ nearest_cell に依らないので、テスト用の小さな DB でも動く）。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np

from .model import LevelStats

JST = timezone(timedelta(hours=9))
EARTH_RADIUS_KM = 6371.0


def timebin_for(dt: datetime) -> tuple[int, int, int, str]:
    """日時 → (timebin_id, month, bin, ラベル)。日付は JST で数える。tz が無ければ UTC とみなす。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    j = dt.astimezone(JST)
    b = 1 if j.day <= 15 else 2
    return (j.month - 1) * 2 + (b - 1), j.month, b, f"{j.month}月{'前半' if b == 1 else '後半'}"


class ClimatologyStore:
    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        self.path = p
        self._con = duckdb.connect(str(p), read_only=True)
        self._lock = threading.Lock()
        g = self._con.execute("SELECT cell_id, lat, lon FROM dim_grid ORDER BY cell_id").fetchnumpy()
        self._cell = g["cell_id"].astype(int)
        self._lat = g["lat"].astype(float)
        self._lon = g["lon"].astype(float)
        self.levels = lru_cache(maxsize=4096)(self._levels)

    def nearest_cell(self, lat: float, lon: float) -> tuple[int, float, float, float]:
        la1, lo1 = np.radians(lat), np.radians(lon)
        la2, lo2 = np.radians(self._lat), np.radians(self._lon)
        h = (np.sin((la2 - la1) / 2) ** 2
             + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
        d = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h))
        i = int(np.argmin(d))
        return int(self._cell[i]), float(self._lat[i]), float(self._lon[i]), float(d[i])

    def _query(self, sql: str, params: list) -> dict:
        with self._lock:
            return self._con.execute(sql, params).fetchnumpy()

    def _levels(self, cell_id: int, timebin_id: int) -> LevelStats:
        r = self._query(
            """SELECT alt_geom_mean_m, u_mean, v_mean, u_var, v_var, uv_cov
               FROM fact_wind WHERE cell_id = ? AND timebin_id = ?
               ORDER BY level_hpa DESC""", [cell_id, timebin_id])
        if r["alt_geom_mean_m"].size == 0:
            raise KeyError((cell_id, timebin_id))
        return LevelStats(*(np.asarray(r[k], dtype=float) for k in
                            ("alt_geom_mean_m", "u_mean", "v_mean", "u_var", "v_var", "uv_cov")))

    def drift_var(self, cell_id: int, timebin_id: int) -> tuple[float, float]:
        r = self._query("""SELECT east_var_m2, north_var_m2 FROM fact_drift
                           WHERE cell_id = ? AND timebin_id = ?""", [cell_id, timebin_id])
        if r["east_var_m2"].size == 0:
            raise KeyError((cell_id, timebin_id))
        return float(r["east_var_m2"][0]), float(r["north_var_m2"][0])
```

- [ ] **手順 5: テストが通ることを確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_store.py -q`
期待する結果: 10 件成功

- [ ] **手順 6: コミット**

```bash
git add backend/bfps/climatology/store.py backend/tests/climatology_fixture.py backend/tests/test_climatology_store.py backend/tests/conftest.py
git commit -m "feat(backend): read-only climatology DuckDB store and half-month bins"
```

---

### タスク 3: 平均の軌道（trajectory.py）

**ファイル:**
- 新規: `backend/bfps/climatology/trajectory.py`
- テスト: `backend/tests/test_climatology_trajectory.py`

**受け渡し:**
- 使うもの: `ClimatologyStore.nearest_cell`, `ClimatologyStore.levels`（タスク 2）、`FlightSettings`, `descent_speed`, `M_PER_DEG`（タスク 1）
- 作るもの: `mean_trajectory(store: ClimatologyStore, timebin_id: int, lat0: float, lon0: float, f: FlightSettings, dt: float = 30.0) -> tuple[list[tuple[float, float, float, float]], int]`
  （点のリスト (lat, lon, alt_m, time_s) と、破裂の点の添字）

- [ ] **手順 1: 失敗するテストを書く**

`backend/tests/test_climatology_trajectory.py`:

```python
import pytest

from bfps.climatology.model import STANDARD_FLIGHT, layer_seconds, mean_drift
from bfps.climatology.store import ClimatologyStore
from bfps.climatology.trajectory import mean_trajectory
from climatology_fixture import make_db


def test_constant_wind_matches_layer_sum(tmp_path):
    p = tmp_path / "c.duckdb"
    make_db(p, u=10.0, v=0.0)
    store = ClimatologyStore(p)
    pts, burst = mean_trajectory(store, 0, 33.0, 130.0, STANDARD_FLIGHT, dt=10.0)
    lat, lon, alt, t = pts[-1]
    assert alt == 0.0
    assert pts[burst][2] == pytest.approx(30000.0)
    lv = store.levels(0, 0)
    T = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    e, _ = mean_drift(lv, T)
    east_m = (lon - 130.0) * 111195.0 * 0.8387  # cos(33°)
    # 合成 DB は 8 面しかなく層が厚いので、層ごとに一定の降下速度とみなす layer_seconds と、
    # 30 秒きざみで密度を変える軌道とで飛行時間が数 % ずれる。風は一定なので距離も同じだけずれる
    assert east_m == pytest.approx(e, rel=0.1)
    assert east_m / t == pytest.approx(10.0, rel=1e-6)
    assert lat == pytest.approx(33.0, abs=1e-6)
    assert t == pytest.approx(T.sum(), rel=0.1)
```

- [ ] **手順 2: 失敗を確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_trajectory.py -q`
期待する結果: 失敗（`No module named 'bfps.climatology.trajectory'`）

- [ ] **手順 3: 実装する**

`backend/bfps/climatology/trajectory.py`:

```python
"""平均の風で飛ばした 1 本の軌道（地図に描く用）。

dt 秒ごとに高さを進め、その時点の位置の最寄り格子点・その高さを含む層の平均風で
水平に動かす。層は fact_wind の平均高度の中点で区切る（model.layer_seconds と同じ）。
"""

from __future__ import annotations

import numpy as np

from .model import M_PER_DEG, FlightSettings, descent_speed
from .store import ClimatologyStore


def _wind_at(store: ClimatologyStore, timebin_id: int, lat: float, lon: float,
             alt: float) -> tuple[float, float]:
    cid, _, _, _ = store.nearest_cell(lat, lon)
    lv = store.levels(cid, timebin_id)
    mid = 0.5 * (lv.alt_m[:-1] + lv.alt_m[1:])
    k = int(np.searchsorted(mid, alt))
    return float(lv.u_mean[k]), float(lv.v_mean[k])


def mean_trajectory(store: ClimatologyStore, timebin_id: int, lat0: float, lon0: float,
                    f: FlightSettings, dt: float = 30.0
                    ) -> tuple[list[tuple[float, float, float, float]], int]:
    lat, lon, alt, t = lat0, lon0, f.launch_altitude, 0.0
    pts = [(lat, lon, alt, t)]
    # 上昇
    while alt < f.burst_altitude:
        step = min(dt, (f.burst_altitude - alt) / f.ascent_rate)
        u, v = _wind_at(store, timebin_id, lat, lon, alt + 0.5 * f.ascent_rate * step)
        lat += v * step / M_PER_DEG
        lon += u * step / (M_PER_DEG * np.cos(np.radians(lat)))
        alt = min(f.burst_altitude, alt + f.ascent_rate * step)
        t += step
        pts.append((lat, lon, alt, t))
    burst_index = len(pts) - 1
    # 降下
    while alt > 0.0:
        w = float(descent_speed(np.array([alt]), f.descent_rate)[0])
        step = min(dt, alt / w)
        u, v = _wind_at(store, timebin_id, lat, lon, alt - 0.5 * w * step)
        lat += v * step / M_PER_DEG
        lon += u * step / (M_PER_DEG * np.cos(np.radians(lat)))
        alt = max(0.0, alt - w * step)
        t += step
        pts.append((lat, lon, alt, t))
    return pts, burst_index
```

- [ ] **手順 4: テストが通ることを確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_trajectory.py -q`
期待する結果: 1 件成功

- [ ] **手順 5: コミット**

```bash
git add backend/bfps/climatology/trajectory.py backend/tests/test_climatology_trajectory.py
git commit -m "feat(backend): mean-wind trajectory for climatology mode"
```

---

### タスク 4: API（predict.py・schemas・route・config）

**ファイル:**
- 新規: `backend/bfps/climatology/predict.py`
- 新規: `backend/bfps/api/routes_climatology.py`
- 変更: `backend/bfps/models/schemas.py`（末尾に追加）
- 変更: `backend/bfps/config.py`
- 変更: `backend/bfps/main.py`
- テスト: `backend/tests/test_climatology_api.py`

**受け渡し:**
- 使うもの: タスク 1–3 の関数すべて
- 作るもの（HTTP）: `POST /api/climatology/predict`。リクエスト・レスポンスは下の `ClimatologyRequest` / `ClimatologyResponse`。フロントエンド（タスク 6）はこの JSON の名前に合わせる。

- [ ] **手順 1: 失敗するテストを書く**

`backend/tests/test_climatology_api.py`:

```python
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bfps.api import routes_climatology
from bfps.main import app
from climatology_fixture import make_db

REQ = {
    "launch_latitude": 33.0,
    "launch_longitude": 130.0,
    "launch_altitude": 0,
    "launch_datetime": "2027-01-10T00:00:00Z",
    "ascent_rate": 5.0,
    "burst_altitude": 30000,
    "descent_rate": 6.0,
    "n_samples": 300,
    "seed": 7,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    p = tmp_path / "c.duckdb"
    make_db(p, u=10.0, v=1.0, rho=0.5)
    monkeypatch.setattr(routes_climatology, "_store", None)
    monkeypatch.setattr(routes_climatology.settings, "climatology_db", str(p))
    return TestClient(app)


def test_predict_ok(client):
    r = client.post("/api/climatology/predict", json=REQ)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["timebin"] == {"month": 1, "bin": 1, "label": "1月前半", "period": "2016–2025"}
    assert b["cell"]["latitude"] == 33.0 and b["cell"]["distance_km"] < 1.0
    assert len(b["samples"]) == 300
    assert b["rho"] == pytest.approx(0.5, abs=1e-6)
    assert b["mean_landing"]["longitude"] > 130.0
    assert b["trajectory"][0]["altitude"] == 0.0
    assert b["trajectory"][b["burst_index"]]["altitude"] == pytest.approx(30000.0)
    assert b["flight_time_s"] > 5000
    assert b["warnings"] == []


def test_predict_warns_high_burst(client):
    r = client.post("/api/climatology/predict", json={**REQ, "burst_altitude": 44000})
    assert r.status_code == 200
    assert any("40 km" in w for w in r.json()["warnings"])


def test_predict_outside_domain(client):
    r = client.post("/api/climatology/predict",
                    json={**REQ, "launch_latitude": 40.0, "launch_longitude": 140.0})
    assert r.status_code == 422


def test_predict_without_db(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_climatology, "_store", None)
    monkeypatch.setattr(routes_climatology.settings, "climatology_db",
                        str(tmp_path / "none.duckdb"))
    r = TestClient(app).post("/api/climatology/predict", json=REQ)
    assert r.status_code == 503
    assert "統計データベースが見つかりません" in r.json()["detail"]


REAL_DB = Path(__file__).resolve().parents[2] / "v2" / "jra3q_japan_wind_2016-2025_v2.duckdb"


@pytest.mark.skipif(not REAL_DB.exists(), reason="本物の DuckDB が無い")
def test_real_db_standard_flight_matches_fact_drift():
    import duckdb

    from bfps.climatology.model import STANDARD_FLIGHT, drift_covariance, layer_seconds, mean_drift, solve_rho
    from bfps.climatology.store import ClimatologyStore

    store = ClimatologyStore(REAL_DB)
    cid, _, _, _ = store.nearest_cell(33.78, 129.72)       # 壱岐
    con = duckdb.connect(str(REAL_DB), read_only=True)
    e_obs, n_obs, ev, nv = con.execute(
        "SELECT east_m, north_m, east_var_m2, north_var_m2 FROM fact_drift "
        "WHERE cell_id = ? AND timebin_id = 0", [cid]).fetchone()
    lv = store.levels(cid, 0)
    T = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    e, n = mean_drift(lv, T)
    assert e == pytest.approx(e_obs, rel=1e-3)
    assert n == pytest.approx(n_obs, rel=1e-2, abs=200)
    rho = solve_rho(lv, T, ev, nv)
    cov = drift_covariance(lv, T, rho)
    assert cov[0, 0] + cov[1, 1] == pytest.approx(ev + nv, rel=0.05)
```

- [ ] **手順 2: 失敗を確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_api.py -q`
期待する結果: 失敗（`cannot import name 'routes_climatology'`）

- [ ] **手順 3: config に設定を足す**

`backend/bfps/config.py` の `Settings` に 1 行足す（`tawhiri_url` の下）:

```python
    climatology_db: str = "../v2/jra3q_japan_wind_2016-2025_v2.duckdb"
```

- [ ] **手順 4: schemas を足す**

`backend/bfps/models/schemas.py` の末尾に追加:

```python
class ClimatologyRequest(BaseModel):
    launch_latitude: float = Field(ge=-90, le=90)
    launch_longitude: float = Field(ge=-180, le=360)
    launch_altitude: float = 0.0
    launch_datetime: datetime
    ascent_rate: float = Field(gt=0, le=15)
    burst_altitude: float = Field(gt=1000, le=45000)
    descent_rate: float = Field(gt=0, le=30)
    n_samples: int = Field(default=500, ge=10, le=2000)
    seed: int | None = 42


class TimebinOut(BaseModel):
    month: int
    bin: int
    label: str
    period: str


class CellOut(BaseModel):
    latitude: float
    longitude: float
    distance_km: float


class LatLonOut(BaseModel):
    latitude: float
    longitude: float


class ClimatologyResponse(BaseModel):
    timebin: TimebinOut
    cell: CellOut
    mean_landing: LatLonOut
    covariance_m2: list[list[float]]
    rho: float
    samples: list[list[float]]
    trajectory: list[TrajectoryPointOut]
    burst_index: int
    flight_time_s: float
    warnings: list[str] = []
```

- [ ] **手順 5: predict.py を書く**

`backend/bfps/climatology/predict.py`:

```python
"""統計モードの予測: 格子点と時期を決め、平均・散らばり・標本・平均の軌道をまとめる。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .model import (
    STANDARD_FLIGHT,
    FlightSettings,
    drift_covariance,
    layer_seconds,
    mean_drift,
    offset_to_latlon,
    sample_offsets,
    solve_rho,
)
from .store import ClimatologyStore, timebin_for
from .trajectory import mean_trajectory

MAX_CELL_DISTANCE_KM = 60.0
PERIOD = "2016–2025"


class OutsideDomainError(ValueError):
    pass


@dataclass
class Prediction:
    timebin: tuple[int, int, str]                 # month, bin, label
    cell: tuple[float, float, float]              # lat, lon, distance_km
    mean_landing: tuple[float, float]
    covariance: np.ndarray
    rho: float
    samples: np.ndarray                           # (n, 2) lat, lon
    trajectory: list[tuple[float, float, float, float]]
    burst_index: int
    flight_time_s: float
    warnings: list[str]


def predict(store: ClimatologyStore, lat: float, lon: float, launch: datetime,
            f: FlightSettings, n_samples: int, seed: int | None) -> Prediction:
    if lon > 180:
        lon -= 360
    cid, clat, clon, dist = store.nearest_cell(lat, lon)
    if dist > MAX_CELL_DISTANCE_KM:
        raise OutsideDomainError(
            f"打ち上げ地点が統計データの範囲外です（最寄りの格子点まで {dist:.0f} km）")
    tb, month, b, label = timebin_for(launch)
    lv = store.levels(cid, tb)
    T = layer_seconds(lv.alt_m, f)
    T_std = layer_seconds(lv.alt_m, STANDARD_FLIGHT)
    ev, nv = store.drift_var(cid, tb)
    rho = solve_rho(lv, T_std, ev, nv)
    mean = mean_drift(lv, T)
    cov = drift_covariance(lv, T, rho)
    off = sample_offsets(mean, cov, n_samples, seed)
    s_lat, s_lon = offset_to_latlon(lat, lon, off[:, 0], off[:, 1])
    m_lat, m_lon = offset_to_latlon(lat, lon, np.array([mean[0]]), np.array([mean[1]]))
    traj, burst_index = mean_trajectory(store, tb, lat, lon, f)
    warnings = []
    if f.burst_altitude > float(lv.alt_m[-1]):
        warnings.append(
            f"破裂高度が統計データの最上層（約 {lv.alt_m[-1] / 1000:.0f} km）より上です。"
            "それより上の風は最上層の値で代用しています")
    return Prediction(
        timebin=(month, b, label), cell=(clat, clon, dist),
        mean_landing=(float(m_lat[0]), float(m_lon[0])), covariance=cov, rho=rho,
        samples=np.column_stack([s_lat, s_lon]), trajectory=traj, burst_index=burst_index,
        flight_time_s=float(T.sum()), warnings=warnings)
```

注: 破裂高度が最上層より上のとき、`layer_seconds` は最上層の上側の境界を 1e5 m にしているので、
最上層の風がそのまま使われる。warnings の文言はそれを説明している。テストは「40 km」を含むことを
確かめる（合成 DB の最上層は 40000 m）。

- [ ] **手順 6: route を書く**

`backend/bfps/api/routes_climatology.py`:

```python
"""統計モード（気候値）の予測 API。DuckDB は最初の呼び出しで開いて使い回す。"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from ..climatology.model import FlightSettings
from ..climatology.predict import PERIOD, OutsideDomainError, predict
from ..climatology.store import ClimatologyStore
from ..config import settings
from ..models.schemas import (
    CellOut,
    ClimatologyRequest,
    ClimatologyResponse,
    LatLonOut,
    TimebinOut,
    TrajectoryPointOut,
)

router = APIRouter()
_store: ClimatologyStore | None = None
_lock = threading.Lock()


def get_store() -> ClimatologyStore:
    global _store
    with _lock:
        if _store is None:
            try:
                _store = ClimatologyStore(settings.climatology_db)
            except FileNotFoundError as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"統計データベースが見つかりません: {settings.climatology_db}",
                ) from e
        return _store


@router.post("/api/climatology/predict", response_model=ClimatologyResponse)
def climatology_predict(req: ClimatologyRequest) -> ClimatologyResponse:
    store = get_store()
    f = FlightSettings(req.ascent_rate, req.burst_altitude, req.descent_rate,
                       req.launch_altitude)
    try:
        p = predict(store, req.launch_latitude, req.launch_longitude,
                    req.launch_datetime, f, req.n_samples, req.seed)
    except OutsideDomainError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    month, b, label = p.timebin
    return ClimatologyResponse(
        timebin=TimebinOut(month=month, bin=b, label=label, period=PERIOD),
        cell=CellOut(latitude=p.cell[0], longitude=p.cell[1], distance_km=p.cell[2]),
        mean_landing=LatLonOut(latitude=p.mean_landing[0], longitude=p.mean_landing[1]),
        covariance_m2=p.covariance.tolist(),
        rho=p.rho,
        samples=p.samples.round(5).tolist(),
        trajectory=[TrajectoryPointOut(latitude=a, longitude=o, altitude=z, time_s=t)
                    for a, o, z, t in p.trajectory],
        burst_index=p.burst_index,
        flight_time_s=p.flight_time_s,
        warnings=p.warnings,
    )
```

`backend/bfps/main.py` の import と include に足す:

```python
from .api import routes_climatology, routes_health, routes_optimize, routes_simulate
...
    app.include_router(routes_climatology.router)
```

- [ ] **手順 7: テストが通ることを確かめる**

実行: `cd backend && .venv/bin/pytest tests/test_climatology_api.py -q`
期待する結果: 5 件成功（本物の DB がある環境）。無い環境では 4 件成功・1 件スキップ。

- [ ] **手順 8: 全テストと lint**

実行: `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check bfps tests`
期待する結果: すべて成功、ruff の指摘なし。

- [ ] **手順 9: 本物の DB で手で叩く**

```bash
cd backend && .venv/bin/uvicorn bfps.main:app --port 8000 &
sleep 3
curl -s -X POST localhost:8000/api/climatology/predict -H 'content-type: application/json' \
  -d '{"launch_latitude":33.78,"launch_longitude":129.72,"launch_datetime":"2027-01-10T00:00:00Z","ascent_rate":5,"burst_altitude":30000,"descent_rate":6,"n_samples":50}' \
  | python3 -c "import json,sys; b=json.load(sys.stdin); print(b['timebin'], b['cell'], b['mean_landing'], round(b['rho'],2), len(b['samples']), b['flight_time_s'])"
kill %1
```

期待する結果: `1月前半`、壱岐の格子点（距離 30 km 以内）、平均落下点が東へ約 2.3 度（瀬戸内海の西）、ρ が 0.3–0.7。

- [ ] **手順 10: コミット**

```bash
git add backend/bfps
git add backend/tests/test_climatology_api.py
git commit -m "feat(backend): POST /api/climatology/predict"
```

---

### タスク 5: 発射時刻の 3 分類（frontend）

**ファイル:**
- 新規: `frontend/src/time/forecastWindow.ts`
- テスト: `frontend/src/time/forecastWindow.test.ts`

**受け渡し:**
- Produces:
  - `type LaunchTimeClass = { kind: 'forecast' } | { kind: 'climatology' } | { kind: 'error'; message: string }`
  - `classifyLaunchTime(launchDatetimeIso: string, nowMs?: number): LaunchTimeClass`
  - 定数 `FORECAST_PAST_MS = 12 * 3600 * 1000`, `FORECAST_FUTURE_MS = 7 * 24 * 3600 * 1000`

- [ ] **手順 1: 失敗するテストを書く**

`frontend/src/time/forecastWindow.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  classifyLaunchTime,
  FORECAST_FUTURE_MS,
  FORECAST_PAST_MS,
} from './forecastWindow'

const NOW = Date.parse('2026-10-12T00:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

describe('classifyLaunchTime', () => {
  it('予報窓の中は forecast', () => {
    expect(classifyLaunchTime(iso(NOW), NOW)).toEqual({ kind: 'forecast' })
    expect(classifyLaunchTime(iso(NOW + FORECAST_FUTURE_MS), NOW)).toEqual({ kind: 'forecast' })
    expect(classifyLaunchTime(iso(NOW - FORECAST_PAST_MS), NOW)).toEqual({ kind: 'forecast' })
  })
  it('+7 日より先は climatology', () => {
    expect(classifyLaunchTime(iso(NOW + FORECAST_FUTURE_MS + 1000), NOW)).toEqual({
      kind: 'climatology',
    })
    expect(classifyLaunchTime('2027-06-01T00:00:00Z', NOW)).toEqual({ kind: 'climatology' })
  })
  it('-12 時間より前はエラー', () => {
    const r = classifyLaunchTime(iso(NOW - FORECAST_PAST_MS - 1000), NOW)
    expect(r.kind).toBe('error')
  })
})
```

- [ ] **手順 2: 失敗を確かめる**

実行: `cd frontend && npx vitest run src/time/forecastWindow.test.ts`
期待する結果: 失敗（`Failed to resolve import "./forecastWindow"`）

- [ ] **手順 3: 実装する**

`frontend/src/time/forecastWindow.ts`:

```ts
// 発射時刻を「予報 (Tawhiri) / 統計 (気候値) / エラー」に分ける。
// Tawhiri (GFS) の予報窓は 現在 -12h 〜 +7日。それより先は統計モードで扱う。

export const FORECAST_PAST_MS = 12 * 3600 * 1000
export const FORECAST_FUTURE_MS = 7 * 24 * 3600 * 1000

export type LaunchTimeClass =
  | { kind: 'forecast' }
  | { kind: 'climatology' }
  | { kind: 'error'; message: string }

export function classifyLaunchTime(
  launchDatetimeIso: string,
  nowMs: number = Date.now(),
): LaunchTimeClass {
  const t = Date.parse(launchDatetimeIso)
  if (t < nowMs - FORECAST_PAST_MS) {
    return { kind: 'error', message: '発射時刻が過去すぎます (気象モデル範囲外)' }
  }
  if (t > nowMs + FORECAST_FUTURE_MS) return { kind: 'climatology' }
  return { kind: 'forecast' }
}
```

- [ ] **手順 4: テストが通ることを確かめる**

実行: `cd frontend && npx vitest run src/time/forecastWindow.test.ts`
期待する結果: 3 件成功

- [ ] **手順 5: コミット**

```bash
git add frontend/src/time/forecastWindow.ts frontend/src/time/forecastWindow.test.ts
git commit -m "feat(frontend): classify launch time into forecast/climatology/error"
```

---

### タスク 6: 統計モードの API クライアントと変換（frontend）

**ファイル:**
- 新規: `frontend/src/api/climatology.ts`
- テスト: `frontend/src/api/climatology.test.ts`

**受け渡し:**
- 使うもの: `backendBaseUrl()`（`api/backend.ts`）、`Flight`, `TrajectoryPoint`（`api/tawhiriTypes.ts`）、タスク 4 の JSON
- Produces:
  - `interface ClimatologyRequest { launch_latitude; launch_longitude; launch_altitude; launch_datetime; ascent_rate; burst_altitude; descent_rate; n_samples; seed }`（number / string）
  - `interface ClimatologyResponse`（タスク 4 のレスポンスと同じ名前）
  - `interface ClimatologyInfo { label: string; period: string; cellLat: number; cellLon: number; cellDistanceKm: number; rho: number; warnings: string[] }`
  - `const BACKEND_REQUIRED_MESSAGE = '統計モードにはバックエンドが必要です（VITE_API_BASE を設定してください）'`
  - `requestClimatology(req: ClimatologyRequest, opts?: { signal?: AbortSignal; baseUrl?: string | null }): Promise<ClimatologyResponse>`
  - `toFlight(res: ClimatologyResponse, launchIso: string): Flight`
  - `toSampleFlights(res: ClimatologyResponse, launchIso: string): Flight[]`（各標本の着地点だけを持つ Flight）
  - `toInfo(res: ClimatologyResponse): ClimatologyInfo`

- [ ] **手順 1: 失敗するテストを書く**

`frontend/src/api/climatology.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import {
  BACKEND_REQUIRED_MESSAGE,
  requestClimatology,
  toFlight,
  toInfo,
  toSampleFlights,
} from './climatology'
import type { ClimatologyRequest, ClimatologyResponse } from './climatology'

const LAUNCH = '2027-01-10T00:00:00.000Z'
const RES: ClimatologyResponse = {
  timebin: { month: 1, bin: 1, label: '1月前半', period: '2016–2025' },
  cell: { latitude: 33.7, longitude: 129.75, distance_km: 9.1 },
  mean_landing: { latitude: 33.9, longitude: 132.4 },
  covariance_m2: [[1e9, 0], [0, 4e8]],
  rho: 0.48,
  samples: [[33.8, 132.0], [34.0, 132.6]],
  trajectory: [
    { latitude: 33.78, longitude: 129.72, altitude: 0, time_s: 0 },
    { latitude: 33.8, longitude: 130.9, altitude: 30000, time_s: 6000 },
    { latitude: 33.9, longitude: 132.3, altitude: 0, time_s: 8200 },
  ],
  burst_index: 1,
  flight_time_s: 8200,
  warnings: [],
}
const REQ: ClimatologyRequest = {
  launch_latitude: 33.78, launch_longitude: 129.72, launch_altitude: 0,
  launch_datetime: LAUNCH, ascent_rate: 5, burst_altitude: 30000, descent_rate: 6,
  n_samples: 500, seed: 42,
}

describe('toFlight', () => {
  it('平均の軌道を上昇・降下に分け、時刻を付ける', () => {
    const f = toFlight(RES, LAUNCH)
    expect(f.ascent).toHaveLength(2)
    expect(f.descent).toHaveLength(2)
    expect(f.burst?.altitude).toBe(30000)
    expect(f.landing.longitude).toBe(132.3)
    expect(f.landing.datetime).toBe('2027-01-10T02:16:40.000Z')
    expect(f.flightTimeS).toBe(8200)
  })
})

describe('toSampleFlights', () => {
  it('標本ごとに着地点だけの Flight を作る', () => {
    const fs = toSampleFlights(RES, LAUNCH)
    expect(fs).toHaveLength(2)
    expect(fs[1].landing).toMatchObject({ latitude: 34.0, longitude: 132.6, altitude: 0 })
    expect(fs[1].launch.latitude).toBe(33.78)
    expect(fs[1].ascent).toEqual([])
  })
})

describe('toInfo', () => {
  it('表示用の情報', () => {
    expect(toInfo(RES)).toEqual({
      label: '1月前半', period: '2016–2025', cellLat: 33.7, cellLon: 129.75,
      cellDistanceKm: 9.1, rho: 0.48, warnings: [],
    })
  })
})

describe('requestClimatology', () => {
  it('バックエンドが無ければエラー', async () => {
    await expect(requestClimatology(REQ, { baseUrl: null })).rejects.toThrow(
      BACKEND_REQUIRED_MESSAGE,
    )
  })
  it('POST して JSON を返す。エラーは detail を出す', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(RES), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '範囲外' }), { status: 422 }))
    vi.stubGlobal('fetch', fetchMock)
    const r = await requestClimatology(REQ, { baseUrl: 'http://x' })
    expect(r.rho).toBe(0.48)
    expect(fetchMock.mock.calls[0][0]).toBe('http://x/api/climatology/predict')
    await expect(requestClimatology(REQ, { baseUrl: 'http://x' })).rejects.toThrow('範囲外')
    vi.unstubAllGlobals()
  })
})
```

- [ ] **手順 2: 失敗を確かめる**

実行: `cd frontend && npx vitest run src/api/climatology.test.ts`
期待する結果: 失敗（`Failed to resolve import "./climatology"`）

- [ ] **手順 3: 実装する**

`frontend/src/api/climatology.ts`:

```ts
// 統計モード (気候値) のクライアント。バックエンドの POST /api/climatology/predict を呼び、
// 結果をアプリ共通の Flight とモンテカルロの落下点に直す。
// スキーマは backend/bfps/models/schemas.py の ClimatologyRequest / ClimatologyResponse と対応。

import { backendBaseUrl } from './backend'
import type { Flight, TrajectoryPoint } from './tawhiriTypes'

export const BACKEND_REQUIRED_MESSAGE =
  '統計モードにはバックエンドが必要です（VITE_API_BASE を設定してください）'

export interface ClimatologyRequest {
  launch_latitude: number
  launch_longitude: number
  launch_altitude: number
  launch_datetime: string
  ascent_rate: number
  burst_altitude: number
  descent_rate: number
  n_samples: number
  seed: number
}

export interface ClimatologyResponse {
  timebin: { month: number; bin: number; label: string; period: string }
  cell: { latitude: number; longitude: number; distance_km: number }
  mean_landing: { latitude: number; longitude: number }
  covariance_m2: number[][]
  rho: number
  samples: number[][]
  trajectory: { latitude: number; longitude: number; altitude: number; time_s: number }[]
  burst_index: number
  flight_time_s: number
  warnings: string[]
}

export interface ClimatologyInfo {
  label: string
  period: string
  cellLat: number
  cellLon: number
  cellDistanceKm: number
  rho: number
  warnings: string[]
}

export async function requestClimatology(
  req: ClimatologyRequest,
  opts: { signal?: AbortSignal; baseUrl?: string | null } = {},
): Promise<ClimatologyResponse> {
  const base = opts.baseUrl === undefined ? backendBaseUrl() : opts.baseUrl
  if (!base) throw new Error(BACKEND_REQUIRED_MESSAGE)
  const res = await fetch(`${base}/api/climatology/predict`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(req),
    signal: opts.signal,
  })
  if (!res.ok) {
    let detail = `統計モードの計算に失敗しました (HTTP ${res.status})`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // 本文が JSON でなければ既定の文言
    }
    throw new Error(detail)
  }
  return (await res.json()) as ClimatologyResponse
}

function atTime(launchIso: string, seconds: number): string {
  return new Date(Date.parse(launchIso) + seconds * 1000).toISOString()
}

export function toFlight(res: ClimatologyResponse, launchIso: string): Flight {
  const pts: TrajectoryPoint[] = res.trajectory.map((p) => ({
    latitude: p.latitude,
    longitude: p.longitude,
    altitude: p.altitude,
    datetime: atTime(launchIso, p.time_s),
  }))
  const b = res.burst_index
  return {
    ascent: pts.slice(0, b + 1),
    descent: pts.slice(b),
    launch: pts[0],
    burst: pts[b],
    landing: pts[pts.length - 1],
    flightTimeS: res.flight_time_s,
  }
}

export function toSampleFlights(res: ClimatologyResponse, launchIso: string): Flight[] {
  const launch: TrajectoryPoint = {
    latitude: res.trajectory[0].latitude,
    longitude: res.trajectory[0].longitude,
    altitude: res.trajectory[0].altitude,
    datetime: launchIso,
  }
  const landingTime = atTime(launchIso, res.flight_time_s)
  return res.samples.map(([lat, lon]) => ({
    ascent: [],
    descent: [],
    launch,
    burst: null,
    landing: { latitude: lat, longitude: lon, altitude: 0, datetime: landingTime },
    flightTimeS: res.flight_time_s,
  }))
}

export function toInfo(res: ClimatologyResponse): ClimatologyInfo {
  return {
    label: res.timebin.label,
    period: res.timebin.period,
    cellLat: res.cell.latitude,
    cellLon: res.cell.longitude,
    cellDistanceKm: res.cell.distance_km,
    rho: res.rho,
    warnings: res.warnings,
  }
}
```

- [ ] **手順 4: テストが通ることを確かめる**

実行: `cd frontend && npx vitest run src/api/climatology.test.ts`
期待する結果: 5 件成功

- [ ] **手順 5: コミット**

```bash
git add frontend/src/api/climatology.ts frontend/src/api/climatology.test.ts
git commit -m "feat(frontend): climatology API client and converters"
```

---

### タスク 7: 画面への組み込み（frontend）

**ファイル:**
- 変更: `frontend/src/store/resultsStore.ts`
- 変更: `frontend/src/hooks/useRunPrediction.ts`
- 変更: `frontend/src/mc/useMonteCarlo.ts`
- 変更: `frontend/src/components/mc/MonteCarloPanel.tsx`
- 変更: `frontend/src/components/ScenarioInfo.tsx`

**受け渡し:**
- 使うもの: `classifyLaunchTime`（タスク 5）、`requestClimatology`, `toFlight`, `toSampleFlights`, `toInfo`, `ClimatologyInfo`（タスク 6）
- Produces:
  - `resultsStore`: `mode: 'forecast' | 'climatology'`, `climatologyInfo: ClimatologyInfo | null`, `setClimatology(info: ClimatologyInfo | null)`（`mode` も同時に切り替える）
  - `buildClimatologyRequest(nSamples: number, seed: number): ClimatologyRequest`（`useRunPrediction.ts`）
  - `useMonteCarlo().runClimatology(nSamples: number, seed: number): Promise<void>`

- [ ] **手順 1: resultsStore に mode と情報を足す**

`frontend/src/store/resultsStore.ts`:

```ts
import type { ClimatologyInfo } from '../api/climatology'
```

`ResultsState` に:

```ts
  mode: 'forecast' | 'climatology'
  climatologyInfo: ClimatologyInfo | null
  setClimatology: (info: ClimatologyInfo | null) => void
```

初期値と実装に:

```ts
  mode: 'forecast',
  climatologyInfo: null,
  setClimatology: (info) =>
    set({ climatologyInfo: info, mode: info ? 'climatology' : 'forecast' }),
```

`clearAll` の set に `mode: 'forecast', climatologyInfo: null,` を足す。

- [ ] **手順 2: 単発の実行を分岐する**

`frontend/src/hooks/useRunPrediction.ts`:

- import を足す:

```ts
import { requestClimatology, toFlight, toInfo } from '../api/climatology'
import type { ClimatologyRequest } from '../api/climatology'
import { classifyLaunchTime } from '../time/forecastWindow'
```

- `validateLaunchTime` を `classifyLaunchTime` を使う形に書き換える（毎時モードは今と同じ挙動: 予報窓の外ならエラー）:

```ts
/** 発射時刻の妥当性チェック (GFSモデル窓: 現在-12h 〜 +7日)。毎時モード用 */
export function validateLaunchTime(launchDatetimeIso: string): string | null {
  const c = classifyLaunchTime(launchDatetimeIso)
  if (c.kind === 'error') return c.message
  if (c.kind === 'climatology') return '発射時刻が未来すぎます (気象モデル範囲外)'
  return null
}

/** 統計モードのリクエスト (フォームの値から) */
export function buildClimatologyRequest(nSamples: number, seed: number): ClimatologyRequest {
  const p = useParamsStore.getState()
  return {
    launch_latitude: p.latitude,
    launch_longitude: p.longitude,
    launch_altitude: p.launchAltitude,
    launch_datetime: jstInputToUtcIso(p.launchTimeJst),
    ascent_rate: p.ascentRate,
    burst_altitude: p.burstAltitude,
    descent_rate: p.descentRate,
    n_samples: nSamples,
    seed,
  }
}
```

- `runSingle` の冒頭を置き換える:

```ts
  const runSingle = useCallback(async () => {
    const results = useResultsStore.getState()
    const req = buildBaseRequest()
    const cls = classifyLaunchTime(req.launch_datetime)
    if (cls.kind === 'error') {
      results.setError(cls.message)
      return
    }
    abortRef.current = new AbortController()
    results.clearAll()
    results.setRunning(true)
    try {
      if (cls.kind === 'climatology') {
        if (req.profile !== 'standard_profile') {
          throw new Error('統計モードは標準プロファイルのみ対応です')
        }
        const res = await requestClimatology(buildClimatologyRequest(10, 42), {
          signal: abortRef.current.signal,
        })
        results.setSingle(toFlight(res, req.launch_datetime))
        useResultsStore.getState().setClimatology(toInfo(res))
      } else {
        const flight = await tawhiriSemaphore.run(() =>
          requestPrediction(req, { signal: abortRef.current!.signal }),
        )
        results.setSingle(flight)
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        results.setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      results.setRunning(false)
    }
  }, [])
```

- [ ] **手順 3: モンテカルロに統計モードを足す**

`frontend/src/mc/useMonteCarlo.ts`:

import を足す:

```ts
import { requestClimatology, toFlight, toInfo, toSampleFlights } from '../api/climatology'
import { buildClimatologyRequest } from '../hooks/useRunPrediction'
```

`run` の「統計計算」以降（landings の集計から安全判定まで）を関数 `finishStatsAndSafety()` に切り出し、`run` の末尾でそれを呼ぶ:

```ts
async function finishStatsAndSafety(): Promise<void> {
  const store = useResultsStore.getState()
  const landings = store.mcSamples.map((s) => ({
    lat: s.flight.landing.latitude,
    lon: s.flight.landing.longitude,
  }))
  if (landings.length >= 5) {
    store.setMcStats(computeLandingStats(landings))
  }
  try {
    const baseUrl = import.meta.env.BASE_URL
    await Promise.all([loadLandData(baseUrl), loadSafetyData(baseUrl)])
    const samplesSnapshot = useResultsStore.getState().mcSamples
    const elevations = await fetchElevations(
      samplesSnapshot.map((s) => ({
        lat: s.flight.landing.latitude,
        lon: s.flight.landing.longitude,
      })),
    )
    const categories = new Map<number, SafetyCategory>()
    const breakdown = emptyBreakdown()
    samplesSnapshot.forEach((s, i) => {
      const cat = classify(s.flight.landing.latitude, s.flight.landing.longitude, elevations[i])
      categories.set(s.index, cat)
      breakdown[cat]++
    })
    const finalStore = useResultsStore.getState()
    finalStore.applyCategories(categories)
    finalStore.setMcSafety(breakdown)
  } catch {
    // 安全判定はベストエフォート (データ取得失敗でもMC結果自体は有効)
  }
}
```

（`run` の中の同じ処理は `await finishStatsAndSafety()` に置き換え、その後に `setRunning(false)`。）

`useMonteCarlo` の中に `runClimatology` を足し、戻り値に含める:

```ts
  const runClimatology = useCallback(async (nSamples: number, seed: number) => {
    const results = useResultsStore.getState()
    results.clearAll()
    results.setRunning(true)
    try {
      const req = buildClimatologyRequest(Math.min(2000, Math.max(10, nSamples)), seed)
      const res = await requestClimatology(req)
      const store = useResultsStore.getState()
      store.setMcCentral(toFlight(res, req.launch_datetime))
      toSampleFlights(res, req.launch_datetime).forEach((flight, index) =>
        store.addMcSample({
          index,
          flight,
          perturbed: {
            ascentRate: req.ascent_rate,
            burstAltitude: req.burst_altitude,
            descentRate: req.descent_rate,
          },
        }),
      )
      store.setClimatology(toInfo(res))
      await finishStatsAndSafety()
    } catch (e) {
      useResultsStore.getState().setError(e instanceof Error ? e.message : String(e))
    } finally {
      useResultsStore.getState().setRunning(false)
    }
  }, [])

  return { run, runClimatology, cancel }
```

注: 標本を 1 点ずつ `addMcSample` すると最大 2000 回 set が走る。遅ければ `resultsStore` に
`setMcSamples(samples: MCSampleResult[])` を足して一度に入れる（その場合は Step 1 の Interfaces に追記）。

- [ ] **手順 4: モンテカルロのパネルを分岐する**

`frontend/src/components/mc/MonteCarloPanel.tsx`:

```ts
import { classifyLaunchTime } from '../../time/forecastWindow'
import { jstInputToUtcIso } from '../../time/jst'
```

`const { run, cancel } = useMonteCarlo()` を `const { run, runClimatology, cancel } = useMonteCarlo()` にし、
`start` を:

```ts
  const start = () => {
    const base = buildBaseRequest()
    if (base.profile !== 'standard_profile') return
    const cls = classifyLaunchTime(base.launch_datetime)
    if (cls.kind === 'error') {
      useResultsStore.getState().setError(cls.message)
      return
    }
    if (cls.kind === 'climatology') {
      void runClimatology(samples, seed)
      return
    }
    void run({
      base,
      samples,
      sigma: {
        ascentRate: sigmaAscent,
        burstAltitudePct: sigmaBurstPct,
        descentRate: sigmaDescent,
      },
      burstModel,
      seed,
    })
  }
```

`validateLaunchTime` の import は消す。発射時刻が統計モードのとき、設定欄の上に注意書きを出す:

```tsx
  const launchTimeJst = useParamsStore((s) => s.launchTimeJst)
  const isClimatology =
    classifyLaunchTime(jstInputToUtcIso(launchTimeJst)).kind === 'climatology'
  ...
      {isClimatology && (
        <p className="mc-note">
          統計モード: 7 日より先なので、予報の代わりに 2016–2025 年の統計風で計算します。
          散らばりは風のばらつきから出すため、下の上昇速度などのばらつきは使いません
          (試行回数は最大 2000)。
        </p>
      )}
```

統計モードのときは試行回数の上限を 2000 にする（`max={isClimatology ? 2000 : MC_MAX_SAMPLES}`、
`onChange` の上限も同じ）。

- [ ] **手順 5: ScenarioInfo に帯を出す**

`frontend/src/components/ScenarioInfo.tsx`:

```ts
  const info = useResultsStore((s) => s.climatologyInfo)
```

`<h3>シナリオ情報</h3>` の直後に:

```tsx
      {info && (
        <div className="climatology-banner" role="status">
          <b>
            統計モード（気候値・{info.label}、{info.period} 年）— 予報ではありません
          </b>
          <div>
            使った格子点: {info.cellLat.toFixed(2)}, {info.cellLon.toFixed(2)}（
            {info.cellDistanceKm.toFixed(0)} km）/ 層どうしの相関 ρ = {info.rho.toFixed(2)}
          </div>
          {info.warnings.map((w) => (
            <div key={w} className="climatology-warning">{w}</div>
          ))}
        </div>
      )}
```

`frontend/src/index.css`（または App.css。既存の `.scenario-info` が定義されているファイル）に:

```css
.climatology-banner {
  background: #fff4d6;
  border: 1px solid #e0a800;
  border-radius: 6px;
  padding: 0.5em 0.75em;
  margin-bottom: 0.5em;
  font-size: 0.9em;
}
.climatology-warning {
  color: #a15c00;
}
.mc-note {
  font-size: 0.85em;
  color: #6b5200;
}
```

- [ ] **手順 6: 型・lint・テスト**

実行: `cd frontend && npx tsc -b && npm run lint && npx vitest run`
期待する結果: エラーなし、すべて成功。

- [ ] **手順 7: 動かして確かめる**

```bash
npm run dev    # リポジトリのルートで。frontend :5173 と backend :8000
```

ブラウザで http://localhost:5173 を開き:

1. 発射時刻を 1 か月先にして「単発実行」→ 地図に平均の軌道、ScenarioInfo に統計モードの帯が出る。
2. 同じ時刻でモンテカルロ（試行 500）→ 楕円・ヒートマップ・安全着地率が出る。注意書きが出ている。
3. 発射時刻を明日に戻すと、帯が消え、これまでどおり Tawhiri で計算される。
4. バックエンドを止めて 1. をやると「統計モードの計算に失敗しました」系のエラーが出る（落ちない）。

画面の確認はスクリーンショットを撮って目視する。

- [ ] **手順 8: コミット**

```bash
git add frontend/src
git commit -m "feat(frontend): climatology mode beyond the Tawhiri forecast window"
```

---

### タスク 8: README

**ファイル:**
- 変更: `README.md`

- [ ] **手順 1: 統計モードの節を足す**

`README.md` のバックエンドの説明の近くに追記:

```markdown
### 統計モード（7 日より先）

発射時刻が Tawhiri の予報窓（現在 −12 時間〜+7 日）より先のとき、単発実行とモンテカルロは
バックエンドの `POST /api/climatology/predict` を使い、JRA-3Q 2016–2025 年の統計風
（日本全国、半月ごと）から落下点の分布と平均の軌道を出す。予報ではない。

- 必要なもの: バックエンド（`npm run dev` で一緒に起動）と統計風 DuckDB
  `v2/jra3q_japan_wind_2016-2025_v2.duckdb`（git 管理外。作り方は `research/wind-climatology` ブランチの `v2/README.md`）。
  場所は環境変数 `BFPS_CLIMATOLOGY_DB` で変えられる。
- 計算の方法: `docs/superpowers/specs/2026-10-12-climatology-mode-design.md`
- データ: JRA-3Q（気象庁）。派生物は CC BY-NC-SA 4.0（非商用）。
```

- [ ] **手順 2: コミット**

```bash
git add README.md
git commit -m "docs: describe climatology mode"
```
