"""The metadata tables, including the distribution definitions.

``meta_fit_family`` is the important one. It carries, for every family, the
density, the parameter list, the estimator, the log-likelihood expression and
the inverse CDF -- as text, inside the database. A reader who never opens the
PDF can still reconstruct the distribution from a row of ``fact_speed_fit``
joined to this table, which is what "anyone can reproduce it" has to mean.

The licence and citation strings are imported from the aggregation pipeline
that produced the NetCDF rather than retyped, and a test asserts they are
still equal, so the database and the NetCDF cannot drift apart.
"""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from windclim.config import DEFAULT_PRODUCT, LEVEL_MIN_HPA, YEARS
from windclim.outputs.netcdf_out import LICENCE, REFERENCES
from windclim.regions import REGIONS

from ..config import DB_STEM, PERIOD, PRODUCT_VERSION, REGION
from ..schema import iter_columns

__all__ = [
    "build_meta_column",
    "build_meta_dataset",
    "build_meta_fit_family",
    "build_meta_license",
    "build_meta_reference",
]

CC_BY_NC_SA = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
KOSAKA = (
    "Kosaka, Y. and co-authors, 2024: The JRA-3Q Reanalysis. "
    "J. Meteor. Soc. Japan, 102, 49-109, doi:10.2151/jmsj.2024-004."
)


def build_meta_dataset(ds, source_path, source_sha) -> pd.DataFrame:
    box = REGIONS[REGION]
    rows: list[tuple[str, str, str | None]] = [
        ("title", "日本全国の高層風 統計データベース v2 (JRA-3Q 2016-2025)", None),
        ("db_stem", DB_STEM, None),
        ("product_version", PRODUCT_VERSION, None),
        ("region", REGION, None),
        ("bbox", f"{box.south}-{box.north}N / {box.west}-{box.east}E", None),
        ("period", PERIOD, "10 年、6 時間ごと、14,610 解析"),
        ("source_product", DEFAULT_PRODUCT, "JRA-3Q の等圧面解析値"),
        ("source_netcdf", Path(source_path).name,
         "入力ファイル名。所在は作った人の計算機ごとに違うので記録しない"),
        ("source_sha256", source_sha, None),
        ("bin_scheme", str(ds.attrs.get("bin_scheme", "half")),
         "1 か月を前半 (1-15 日) と後半 (16 日-月末) に分ける"),
        ("date_convention", str(ds.attrs.get("date_convention", "utc")), None),
        ("level_min_hpa", str(LEVEL_MIN_HPA), "3 hPa ≒ 40 km で打ち切っている"),
        ("grid_resolution_deg", "0.375", "約 40 km"),
        ("years", f"{min(YEARS)}-{max(YEARS)}", None),
        (
            "lon_convention", "signed (-180, 180]",
            "元の NetCDF に合わせた。0-360 表記は lon_0_360 列にある",
        ),
        (
            "direction_convention",
            "meteorological FROM-direction, north = 0, clockwise",
            "唯一の例外は fact_drift.bearing_deg で、機体が進む向き (180 度逆)",
        ),
        ("flight_ascent_rate_ms", str(ds.attrs.get("flight_ascent_rate_ms", 5.0)), None),
        ("flight_burst_altitude_m", str(ds.attrs.get("flight_burst_altitude_m", 30000.0)), None),
        ("flight_descent_rate_ms", str(ds.attrs.get("flight_descent_rate_ms", 6.0)), None),
        ("rose_cell_lat", str(ds.attrs.get("rose_cell_lat")), "風配図を記録している代表格子点"),
        ("rose_cell_lon", str(ds.attrs.get("rose_cell_lon")), None),
        (
            "aic_weibull_penalty_note",
            "Weibull の自由パラメータは 2 (loc は 0 に固定)",
            "この統計を作った上流のパイプラインは 3 として +6 を課しており、"
            "この DB より Weibull に 2 AIC 単位不利になっている",
        ),
        (
            "uniform_candidate_note",
            "一様分布は本当の候補として AIC 比較に参加している",
            "上流のパイプラインでは比較用に計算するだけで、勝てない実装になっていた",
        ),
        (
            "aicc_note", "AICc は保存していない",
            "n >= 532、k <= 2 では補正項が 0.023 AIC 単位以下で、勝者を変えることがない",
        ),
        (
            "neff_note",
            "AIC の差は n/n_eff だけ水増しされている",
            "6 時間ごとの解析はほぼ同じ空気で、ラグ 1 自己相関が高い。"
            "尤度は独立標本として計算しているので、族の差を読むときは n_eff で割り引くこと。"
            "倍率は fact_wind の n と n_eff から格子点ごとに確かめられる。"
            "is_ambiguous 列と v_speed_fit_selected.delta_aic_effective がその補正を持つ",
        ),
        (
            "samples_note", "個々の解析値そのものは収録していない",
            f"{ds.sizes['lat'] * ds.sizes['lon']} 格子点 × 38 面 × 14,610 解析 × 2 成分で"
            f"約 {ds.sizes['lat'] * ds.sizes['lon'] * 38 * 14610 * 2 * 4 / 1e9:.0f} GB になるため。"
            "パーセンタイルと当てはめたパラメータがその要約",
        ),
        ("license_spdx", "CC-BY-NC-SA-4.0", "非商用限定・継承・表示"),
        ("built_at", datetime.now(UTC).isoformat(timespec="seconds"), None),
        ("builder", "jpduck", None),
        ("host", platform.node(), None),
    ]
    return pd.DataFrame(rows, columns=["key", "value", "note"])


def build_meta_column() -> pd.DataFrame:
    rows = [
        {
            "table_name": table.name,
            "column_name": column.name,
            "data_type": column.type,
            "units": column.unit,
            "description": column.comment,
            "source": column.source,
        }
        for table, column in iter_columns()
    ]
    return pd.DataFrame(rows)


def build_meta_fit_family() -> pd.DataFrame:
    """Density, parameters, estimator, likelihood and sampler for each family."""
    rows = [
        {
            "quantity": "speed_ms",
            "family": "normal",
            "included": True,
            "exclusion_reason": None,
            "n_params": 2,
            "support": "(-inf, inf); 実際の風速は非負なので prob_negative 列を見ること",
            "density_unit": "(m/s)^-1",
            "param_columns": "mu_ms, sigma_ms",
            "pdf_plain": "f(x) = 1/(sigma*sqrt(2*pi)) * exp(-(x-mu)^2/(2*sigma^2))",
            "pdf_latex": r"f(x)=\frac{1}{\sigma\sqrt{2\pi}}"
                         r"\exp\!\left[-\frac{(x-\mu)^2}{2\sigma^2}\right]",
            "cdf_plain": "F(x) = Phi((x-mu)/sigma)",
            "ppf_plain": "x = mu + sigma * Phi^{-1}(u),  u ~ U(0,1)",
            "loglik_plain": "-n/2 * (ln(2*pi*sigma^2) + 1)",
            "estimator": "mle",
            "estimator_note": "mu = 標本平均、sigma = 標本標準偏差 (ddof=0、最尤推定)。"
                              "fact_wind.speed_std は ddof=1 なのでわずかに異なる",
            "gof_stat": "Kolmogorov-Smirnov D",
            "scipy_equivalent": "scipy.stats.norm(loc=mu_ms, scale=sigma_ms)",
            "reference": "標準的な結果",
        },
        {
            "quantity": "speed_ms",
            "family": "weibull_min_loc0",
            "included": True,
            "exclusion_reason": None,
            "n_params": 2,
            "support": "[0, inf)",
            "density_unit": "(m/s)^-1",
            "param_columns": "weibull_shape (k), weibull_scale_ms (lambda); "
                             "weibull_loc_ms は常に 0",
            "pdf_plain": "f(x) = (k/lambda) * (x/lambda)^(k-1) * exp(-(x/lambda)^k),  x >= 0",
            "pdf_latex": r"f(x)=\frac{k}{\lambda}\left(\frac{x}{\lambda}\right)^{k-1}"
                         r"\exp\!\left[-\left(\frac{x}{\lambda}\right)^{k}\right]",
            "cdf_plain": "F(x) = 1 - exp(-(x/lambda)^k)",
            "ppf_plain": "x = lambda * (-ln(1-u))^(1/k),  u ~ U(0,1)",
            "loglik_plain": "n*ln(k) - n*k*ln(lambda) + (k-1)*sum(ln x_i) - sum((x_i/lambda)^k)"
                            "  (最尤点では最後の項はちょうど n)",
            "estimator": "mle",
            "estimator_note": "k は sum(x^k ln x)/sum(x^k) - 1/k - mean(ln x) = 0 の解 "
                              "(scipy.optimize.newton)。次に lambda = (mean(x^k))^(1/k)。"
                              "loc は 0 に固定しているので自由パラメータは 2 つ",
            "gof_stat": "Kolmogorov-Smirnov D",
            "scipy_equivalent":
                "scipy.stats.weibull_min(c=weibull_shape, loc=0.0, scale=weibull_scale_ms)",
            "reference": "標準的な結果。初期値は Cohen の白色化近似 k0 = 0.9874/sd(ln x)",
        },
        {
            "quantity": "speed_ms",
            "family": "uniform",
            "included": True,
            "exclusion_reason": None,
            "n_params": 2,
            "support": "[a, b]",
            "density_unit": "(m/s)^-1",
            "param_columns": "uniform_a_ms, uniform_b_ms",
            "pdf_plain": "f(x) = 1/(b-a) for a <= x <= b, else 0",
            "pdf_latex": r"f(x)=\frac{1}{b-a}\quad (a\le x\le b)",
            "cdf_plain": "F(x) = (x-a)/(b-a)",
            "ppf_plain": "x = a + (b-a)*u,  u ~ U(0,1)",
            "loglik_plain": "-n * ln(b-a)",
            "estimator": "mle",
            "estimator_note": "a = 標本最小値、b = 標本最大値。この推定値はパラメータ空間の"
                              "境界にあるので AIC の正則条件を厳密には満たさない。"
                              "当て馬ではなく正規・Weibull と同じ基準で比べた本当の候補。"
                              "実測では 519,840 面のうち 7 面 "
                              "(すべて 7 月前半・領域南東端の 175-225 hPa) で勝っており、"
                              "うち 5 面は is_ambiguous",
            "gof_stat": "Kolmogorov-Smirnov D",
            "scipy_equivalent":
                "scipy.stats.uniform(loc=uniform_a_ms, scale=uniform_b_ms-uniform_a_ms)",
            "reference": "標準的な結果",
        },
        {
            "quantity": "direction_rad",
            "family": "von_mises",
            "included": True,
            "exclusion_reason": None,
            "n_params": 2,
            "support": "(-pi, pi]",
            "density_unit": "rad^-1",
            "param_columns": "mu_rad, kappa",
            "pdf_plain": "f(theta) = exp(kappa*cos(theta-mu)) / (2*pi*I0(kappa))",
            "pdf_latex": r"f(\theta)=\frac{e^{\kappa\cos(\theta-\mu)}}{2\pi I_0(\kappa)}",
            "cdf_plain": "閉形式なし。F(d) = 1/2 + d/(2pi) + (1/pi)*sum_p (I_p/I_0)*sin(p*d)/p、"
                         "または scipy.stats.vonmises.cdf",
            "ppf_plain": "閉形式なし。scipy.stats.vonmises(kappa, loc=mu_rad).rvs() を使う",
            "loglik_plain": "n*(kappa*Rbar - kappa - ln(2*pi) - ln(i0e(kappa)))"
                            "  (i0e は指数スケールした I0。大きな kappa でも溢れない)",
            "estimator": "mle",
            "estimator_note": "mu = atan2(mean sin, mean cos)。kappa は I1(kappa)/I0(kappa) = Rbar "
                              "の解 (scipy.optimize.newton + scipy.special.i0e/i1e)",
            "gof_stat": "Kuiper V",
            "scipy_equivalent": "scipy.stats.vonmises(kappa=kappa, loc=mu_rad)",
            "reference": "Mardia & Jupp 2000; 初期値は Fisher 1993",
        },
        {
            "quantity": "direction_rad",
            "family": "wrapped_normal",
            "included": True,
            "exclusion_reason": None,
            "n_params": 2,
            "support": "(-pi, pi]",
            "density_unit": "rad^-1",
            "param_columns": "mu_rad, wn_sigma_rad",
            "pdf_plain": "f(theta) = (1/(sigma*sqrt(2*pi)))"
                         " * sum_j exp(-(theta-mu+2*pi*j)^2/(2*sigma^2))"
                         "  = (1/(2*pi)) * (1 + 2*sum_p Rbar^(p^2) * cos(p*(theta-mu)))",
            "pdf_latex": r"f(\theta)=\frac{1}{2\pi}\left[1+2\sum_{p\ge1}"
                         r"\bar R^{\,p^{2}}\cos p(\theta-\mu)\right]",
            "cdf_plain": "F(d) = 1/2 + d/(2pi) + (1/pi)*sum_p Rbar^(p^2)*sin(p*d)/p",
            "ppf_plain": "閉形式なし。theta = mu + sigma*Phi^{-1}(u) を (-pi, pi] に巻き戻せばよい",
            "loglik_plain": "sum_i ln f(theta_i)。Rbar > 0.5 では空間和を |j| <= 3 で、"
                            "それ以下では Fourier 形を p <= 12 で打ち切る",
            "estimator": "mom",
            "estimator_note": "モーメント法。mu は円周平均、sigma = sqrt(-2 ln Rbar) で、"
                              "第 1 三角モーメントを厳密に一致させる。"
                              "巻き付け正規に閉形式の最尤推定量は無く、実装したライブラリも無いため、"
                              "AIC は準 AIC であり von Mises との比較は形式的には厳密でない",
            "gof_stat": "Kuiper V",
            "scipy_equivalent": "なし (scipy に巻き付け正規は無い)",
            "reference": "Mardia & Jupp 2000",
        },
        {
            "quantity": "direction_rad",
            "family": "circular_uniform",
            "included": True,
            "exclusion_reason": None,
            "n_params": 0,
            "support": "(-pi, pi]",
            "density_unit": "rad^-1",
            "param_columns": "なし",
            "pdf_plain": "f(theta) = 1/(2*pi)",
            "pdf_latex": r"f(\theta)=\frac{1}{2\pi}",
            "cdf_plain": "F(d) = (d + pi)/(2*pi)",
            "ppf_plain": "theta = -pi + 2*pi*u,  u ~ U(0,1)",
            "loglik_plain": "-n * ln(2*pi)",
            "estimator": "mle",
            "estimator_note": "推定するものが無い。帰無モデル (向きに偏りが無い) であり、"
                              "線形の一様分布と違って境界の問題が無いので AIC は厳密に正当",
            "gof_stat": "Rayleigh Z = n*Rbar^2 / Kuiper V",
            "scipy_equivalent": "scipy.stats.uniform(loc=-pi, scale=2*pi)",
            "reference": "Mardia & Jupp 2000",
        },
        {
            "quantity": "direction_rad",
            "family": "weibull_min_loc0",
            "included": False,
            "exclusion_reason":
                "Weibull の台は [0, inf) で、角度の原点を回しても不変ではない。"
                "円周上では 359 度と 1 度は 2 度しか離れていないが、直線上では 358 度離れている。"
                "原点を北から東に移すだけで形状と尺度が変わってしまう。"
                "角度の分布は周期的でなければならず、Weibull はそうではない。"
                "当てはまりが悪いからではなく、量の性質に合わないので候補から外している",
            "n_params": 2,
            "support": "[0, inf)",
            "density_unit": "rad^-1",
            "param_columns": "なし (当てはめていない)",
            "pdf_plain": "(当てはめていない)",
            "pdf_latex": "",
            "cdf_plain": None,
            "ppf_plain": None,
            "loglik_plain": "(当てはめていない)",
            "estimator": "mle",
            "estimator_note": None,
            "gof_stat": None,
            "scipy_equivalent": None,
            "reference": None,
        },
    ]
    return pd.DataFrame(rows)


def build_meta_reference() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"kind": "source dataset", "citation": KOSAKA,
             "doi": "10.2151/jmsj.2024-004", "url": None},
            {"kind": "data distributor",
             "citation": "NSF NCAR Geoscience Data Exchange, dataset d640000",
             "doi": None, "url": "https://gdex.ucar.edu/datasets/d640000/"},
            {"kind": "circular statistics",
             "citation": "Mardia, K. V. and Jupp, P. E., 2000: Directional Statistics. Wiley.",
             "doi": None, "url": None},
            {"kind": "von Mises kappa start",
             "citation": "Fisher, N. I., 1993: Statistical Analysis of Circular Data. CUP.",
             "doi": None, "url": None},
            {"kind": "goodness of fit",
             "citation": "Kuiper, N. H., 1960: Tests concerning random points on a circle. "
                         "Proc. K. Ned. Akad. Wet. A, 63, 38-47.",
             "doi": None, "url": None},
            {"kind": "model selection",
             "citation": "Akaike, H., 1974: A new look at the statistical model identification. "
                         "IEEE Trans. Automat. Contr., 19, 716-723.",
             "doi": "10.1109/TAC.1974.1100705", "url": None},
            {"kind": "effective sample size",
             "citation": "Wilks, D. S., 2011: Statistical Methods in the Atmospheric Sciences, "
                         "3rd ed. Academic Press.",
             "doi": None, "url": None},
            {"kind": "geopotential to geometric",
             "citation": "List, R. J., 1968: Smithsonian Meteorological Tables. "
                         "Smithsonian Misc. Coll., 114.",
             "doi": None, "url": None},
        ]
    )


def build_meta_license() -> pd.DataFrame:
    attribution = (
        "JRA-3Q reanalysis, Japan Meteorological Agency, distributed by NSF NCAR GDEX "
        f"(dataset d640000). {KOSAKA} Licensed CC BY-NC-SA 4.0."
    )
    return pd.DataFrame(
        [
            {
                "applies_to": "source_data",
                "spdx_id": "CC-BY-NC-SA-4.0",
                "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
                "url": CC_BY_NC_SA,
                "non_commercial": True,
                "share_alike": True,
                "attribution_required": True,
                "inherits_from": None,
                "attribution_text": attribution,
                "full_notice": LICENCE + " " + REFERENCES,
            },
            {
                "applies_to": "database",
                "spdx_id": "CC-BY-NC-SA-4.0",
                "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
                "url": CC_BY_NC_SA,
                "non_commercial": True,
                "share_alike": True,
                "attribution_required": True,
                "inherits_from": "source_data",
                "attribution_text": attribution,
                "full_notice":
                    "このデータベースは JRA-3Q の派生物であり、継承条項により同じ "
                    "CC BY-NC-SA 4.0 が適用される。リポジトリ本体のライセンスではない。"
                    "非商用限定、再配布時は同じライセンスと出典表示が必要。" + LICENCE,
            },
        ]
    )
