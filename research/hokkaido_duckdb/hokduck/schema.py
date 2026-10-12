"""The database schema, as data.

Every column is declared once here, with its type, its unit and the sentence
that explains it. Both the ``CREATE TABLE`` and the ``COMMENT ON`` are
generated from this one list, so a column cannot exist without a description
and a description cannot describe a column that is not there. The
documentation reads the comments back out of the built file, which closes the
loop: the schema chapter of the PDF cannot drift from the database.

Conventions, fixed here and recorded in ``meta_dataset``:

* Longitude is **signed**, matching the source NetCDF. ``lon_0_360`` is
  carried alongside so nobody has to guess which convention a query wants.
* Direction is the **meteorological FROM-direction**: north is 0, increasing
  clockwise, so a westerly is 270. The single exception is
  ``fact_drift.bearing_deg``, which is the direction the payload travels
  towards; it is named differently and carries a shouting comment, and
  ``bearing_from_deg`` sits next to it for anyone who wants the usual
  convention.
* Surrogate keys (``cell_id``, ``level_id``, ``timebin_id``) *and* the natural
  values (``month``, ``bin``, ``level_hpa``, ``lat``, ``lon``) appear on every
  fact row. The redundancy costs almost nothing after compression and means
  ``WHERE month = 1 AND level_hpa = 200`` needs no join. That is the point of
  the deliverable.
* Values that came from the NetCDF are ``REAL`` because they were float32
  there; widening them would claim precision that does not exist. Fit outputs
  are ``DOUBLE`` because AIC differences of 0.01 matter against totals of
  5000.
* Primary keys are declared on the dimensions only. DuckDB builds an ART
  index for every key constraint, which on a 780k-row four-column key costs
  tens of megabytes and buys nothing for analytical scans -- the zone maps
  already prune, because rows are inserted in key order. Uniqueness and
  referential integrity are checked by ``sql/90_verify.sql`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "ENUMS",
    "TABLES",
    "Column",
    "Table",
    "comment_statements",
    "create_statements",
    "iter_columns",
]


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    comment: str
    unit: str | None = None
    nullable: bool = True
    check: str | None = None

    @property
    def source(self) -> str:
        """Where the value came from; recorded in ``meta_column``."""
        return self._source

    _source: str = "netcdf"

    def ddl(self) -> str:
        parts = [f"{self.name} {self.type}"]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.check:
            parts.append(f"CHECK ({self.check})")
        return " ".join(parts)

    def full_comment(self) -> str:
        return f"{self.comment} [{self.unit}]" if self.unit else self.comment


def col(
    name: str,
    type_: str,
    comment: str,
    unit: str | None = None,
    *,
    nullable: bool = True,
    check: str | None = None,
    source: str = "netcdf",
) -> Column:
    return Column(name, type_, comment, unit, nullable, check, source)


@dataclass(frozen=True)
class Table:
    name: str
    comment: str
    columns: list[Column]
    primary_key: tuple[str, ...] = ()
    unique: tuple[tuple[str, ...], ...] = ()
    order_by: tuple[str, ...] = ()
    extra: list[str] = field(default_factory=list)

    def ddl(self) -> str:
        body = [c.ddl() for c in self.columns]
        if self.primary_key:
            body.append(f"PRIMARY KEY ({', '.join(self.primary_key)})")
        for u in self.unique:
            body.append(f"UNIQUE ({', '.join(u)})")
        body.extend(self.extra)
        inner = ",\n  ".join(body)
        return f"CREATE TABLE {self.name} (\n  {inner}\n);"


# --------------------------------------------------------------- enums ----
ENUMS: dict[str, tuple[str, ...]] = {
    "bin_half": ("H1", "H2"),
    "season_code": ("DJF", "MAM", "JJA", "SON"),
    "speed_family": ("normal", "weibull_min_loc0", "uniform"),
    "dir_family": ("von_mises", "wrapped_normal", "circular_uniform"),
    "fit_estimator": ("mle", "mom"),
}

# ---------------------------------------------------------- dimensions ----
_KEYS_CELL = [
    col("timebin_id", "SMALLINT", "時期ビンの代理キー。dim_timebin を参照", None,
        nullable=False, source="derived"),
    col("level_id", "SMALLINT", "気圧面の代理キー。dim_level を参照", None,
        nullable=False, source="derived"),
    col("cell_id", "SMALLINT", "格子点の代理キー。dim_grid を参照", None,
        nullable=False, source="derived"),
    col("month", "TINYINT", "月 (1-12)", None, nullable=False, source="derived"),
    col("bin", "TINYINT", "月内のビン。1 = 前半 (1-15 日)、2 = 後半 (16 日-月末)", None,
        nullable=False, source="derived"),
    col("level_hpa", "DOUBLE", "気圧面", "hPa", nullable=False, source="derived"),
    col("lat", "DOUBLE", "緯度 (北が正)", "degrees_north", nullable=False, source="derived"),
    col("lon", "DOUBLE", "経度。符号付き (-180, 180] で格納", "degrees_east",
        nullable=False, source="derived"),
]

TABLES: list[Table] = [
    Table(
        "dim_grid",
        "解析に使った格子点。北海道の箱 40.0-46.5N / 138.0-149.0E を 0.375 度格子で切った 570 点",
        [
            col("cell_id", "SMALLINT", "格子点の代理キー。lat_idx * 30 + lon_idx", None,
                nullable=False, source="derived"),
            col("lat_idx", "SMALLINT", "緯度方向の添字 (0-18、南から北へ)", None,
                nullable=False, check="lat_idx BETWEEN 0 AND 18", source="derived"),
            col("lon_idx", "SMALLINT", "経度方向の添字 (0-29、西から東へ)", None,
                nullable=False, check="lon_idx BETWEEN 0 AND 29", source="derived"),
            col("lat", "DOUBLE", "緯度。ガウス格子なので間隔は一定でない (約 0.3746 度)",
                "degrees_north", nullable=False),
            col("lon", "DOUBLE", "経度。符号付き (-180, 180]、間隔はちょうど 0.375 度",
                "degrees_east", nullable=False),
            col("lon_0_360", "DOUBLE", "同じ経度を 0-360 の慣習で表したもの", "degrees_east",
                nullable=False, source="derived"),
            col("gauss_weight", "DOUBLE",
                "ガウス求積の緯度重み。領域平均を取るときはこれで重み付けする。"
                "cos(lat) で代用しないこと",
                "1", nullable=False),
            col("is_rose_cell", "BOOLEAN",
                "fact_wind_rose が記録している代表格子点かどうか。ちょうど 1 点だけが真",
                None, nullable=False, source="derived"),
        ],
        primary_key=("cell_id",),
        unique=(("lat_idx", "lon_idx"),),
        order_by=("cell_id",),
    ),
    Table(
        "dim_level",
        "気圧面 38 枚。1000 hPa (地表付近) から 3 hPa (約 40 km) まで",
        [
            col("level_id", "SMALLINT", "気圧面の代理キー。0 = 3 hPa (最上層)、37 = 1000 hPa",
                None, nullable=False, source="derived"),
            col("level_hpa", "DOUBLE", "気圧", "hPa", nullable=False,
                check="level_hpa BETWEEN 3.0 AND 1000.0"),
            col("alt_geom_mean_m", "DOUBLE",
                "この気圧面の幾何高度の領域・期間平均 (gauss_weight 加重)。"
                "セルごとの正確な値は fact_wind.alt_geom_mean_m にある", "m", source="derived"),
            col("alt_geom_mean_km", "DOUBLE", "同じものを km で", "km", source="derived"),
            col("alt_geom_min_m", "DOUBLE", "全セル・全時期での幾何高度の最小", "m",
                source="derived"),
            col("alt_geom_max_m", "DOUBLE", "全セル・全時期での幾何高度の最大", "m",
                source="derived"),
            col("z_mean_gpm", "DOUBLE",
                "ジオポテンシャル高度の平均。幾何高度ではない (45N・30 km で約 140 m 違う)",
                "gpm", source="derived"),
            col("isa_alt_m", "DOUBLE",
                "国際標準大気での対応高度。季節によらない目盛りとして併記", "m", source="derived"),
            col("is_diurnal_level", "BOOLEAN",
                "fact_wind_diurnal に含まれるか (300 hPa 以下のみ)", None,
                nullable=False, source="derived"),
        ],
        primary_key=("level_id",),
        unique=(("level_hpa",),),
        order_by=("level_id",),
    ),
    Table(
        "dim_timebin",
        "時期の区切り。1 か月を前半 (1-15 日) と後半 (16 日-月末) に割った 24 ビン。"
        "交差検証の結果 15 日がデータの支えられる最小単位だったため",
        [
            col("timebin_id", "SMALLINT", "時期ビンの代理キー。(month - 1) * 2 + (bin - 1)",
                None, nullable=False, source="derived"),
            col("month", "TINYINT", "月 (1-12)", None, nullable=False,
                check="month BETWEEN 1 AND 12"),
            col("bin", "TINYINT", "1 = 前半、2 = 後半", None, nullable=False,
                check="bin IN (1, 2)"),
            col("bin_short", "bin_half", "H1 または H2", None, nullable=False, source="derived"),
            col("bin_label_ja", "VARCHAR", "日本語のラベル", None, nullable=False),
            col("bin_label_en", "VARCHAR", "英語のラベル", None, nullable=False, source="derived"),
            col("start_day", "TINYINT", "ビンの開始日 (1 または 16)", None, nullable=False),
            col("end_day_min", "TINYINT", "2016-2025 でのビン終了日の最小 (2 月後半は 28)",
                None, nullable=False, source="derived"),
            col("end_day_max", "TINYINT", "同じく最大 (2 月後半は 29)", None,
                nullable=False, source="derived"),
            col("n_days_total", "INTEGER", "10 年ぶんを合計した日数", "d",
                nullable=False, source="derived"),
            col("n_analyses_expected", "INTEGER", "期待される解析値の数 = n_days_total * 4",
                None, nullable=False, source="derived"),
            col("season", "season_code", "季節コード", None, nullable=False, source="derived"),
            col("season_ja", "VARCHAR", "季節の日本語名", None, nullable=False, source="derived"),
            col("season_order", "TINYINT", "季節の並び順 (0 = 冬)", None,
                nullable=False, source="derived"),
        ],
        primary_key=("timebin_id",),
        unique=(("month", "bin"),),
        order_by=("timebin_id",),
    ),
    Table(
        "dim_hour",
        "解析時刻。JRA-3Q は 1 日 4 回",
        [
            col("hour_utc", "TINYINT", "解析時刻 (UTC)", "h", nullable=False,
                check="hour_utc IN (0, 6, 12, 18)"),
            col("hour_jst", "TINYINT", "同じ時刻を日本標準時で", "h", nullable=False,
                source="derived"),
            col("jst_next_day", "BOOLEAN",
                "JST にすると翌日になるか。18 UTC = 翌日 03 JST だけが真", None,
                nullable=False, source="derived"),
        ],
        primary_key=("hour_utc",),
        order_by=("hour_utc",),
    ),
    Table(
        "dim_sector",
        "風配図の方位区分 16 枚。区分は方位の中心に合わせてあり、境界ではない",
        [
            col("sector", "SMALLINT", "方位区分の番号 (0 = 北)", None, nullable=False,
                check="sector BETWEEN 0 AND 15"),
            col("centre_deg", "DOUBLE", "区分の中心方位。sector * 22.5", "degree",
                nullable=False, source="derived"),
            col("lo_deg", "DOUBLE", "区分の下端 = (中心 - 11.25) mod 360", "degree",
                nullable=False, source="derived"),
            col("hi_deg", "DOUBLE", "区分の上端 = 中心 + 11.25", "degree",
                nullable=False, source="derived"),
            col("wraps_north", "BOOLEAN",
                "北をまたぐ区分か。sector 0 (348.75-11.25 度) だけが真", None,
                nullable=False, source="derived"),
            col("compass_16", "VARCHAR", "16 方位の記号 (N, NNE, ...)", None,
                nullable=False, source="derived"),
        ],
        primary_key=("sector",),
        order_by=("sector",),
    ),
    Table(
        "dim_speed_class",
        "風配図の風速階級 6 段。最上段は上限なし",
        [
            col("speed_class", "SMALLINT", "階級番号", None, nullable=False,
                check="speed_class BETWEEN 0 AND 5"),
            col("lo_ms", "DOUBLE", "階級の下限 (以上)", "m s-1", nullable=False),
            col("hi_ms", "DOUBLE", "階級の上限 (未満)。最上段は上限なしなので NULL", "m s-1"),
            col("label", "VARCHAR", "表示用のラベル", None, nullable=False, source="derived"),
        ],
        primary_key=("speed_class",),
        order_by=("speed_class",),
    ),
    # ------------------------------------------------------------ facts ---
    Table(
        "fact_wind",
        "風の統計の本体。1 行が (時期ビン, 気圧面, 格子点) の組に対応し、"
        "その組に入る 10 年ぶん 520-640 個の 6 時間ごと解析値を要約したもの",
        [
            *_KEYS_CELL,
            col("n", "INTEGER", "このビンに入った解析値の数", None, nullable=False,
                check="n > 0"),
            col("n_eff", "REAL",
                "有効標本数 n(1-r1)/(1+r1)。6 時間ごとの解析はほぼ同じ空気なので、"
                "n の 3-8 % しかない。信頼区間を出すときは n ではなくこちらを使う", "1"),
            col("lag1_autocorr", "REAL",
                "風速のラグ 1 自己相関。年をまたがずに各年の連続区間だけで計算", "1"),
            col("u_mean", "REAL", "東向き風速の平均", "m s-1"),
            col("v_mean", "REAL", "北向き風速の平均", "m s-1"),
            col("u_var", "REAL", "東向き風速の分散", "m2 s-2"),
            col("v_var", "REAL", "北向き風速の分散", "m2 s-2"),
            col("uv_cov", "REAL", "東西と南北の共分散。分散楕円を復元できる", "m2 s-2"),
            col("u_unit_mean", "REAL", "単位風ベクトルの東向き成分の平均 (各解析を等重みで)", "1"),
            col("v_unit_mean", "REAL", "単位風ベクトルの北向き成分の平均", "1"),
            col("speed_mean", "REAL",
                "スカラー平均風速。各解析の風速を平均したもので、ふつうどれくらい強いか", "m s-1"),
            col("speed_vector_mean", "REAL",
                "ベクトル平均風速 hypot(u_mean, v_mean)。正味どれだけ運ばれるか。"
                "常に speed_mean 以下", "m s-1"),
            col("speed_std", "REAL", "風速の標準偏差 (ddof=1)", "m s-1"),
            col("speed_max", "REAL", "風速の最大", "m s-1"),
            col("speed_se", "REAL", "風速平均の標準誤差 speed_std / sqrt(n_eff)", "m s-1"),
            col("speed_p10", "REAL", "風速の 10 パーセンタイル", "m s-1"),
            col("speed_p25", "REAL", "風速の 25 パーセンタイル", "m s-1"),
            col("speed_p50", "REAL", "風速の中央値", "m s-1"),
            col("speed_p75", "REAL", "風速の 75 パーセンタイル", "m s-1"),
            col("speed_p90", "REAL", "風速の 90 パーセンタイル", "m s-1"),
            col("speed_p95", "REAL", "風速の 95 パーセンタイル", "m s-1"),
            col("exceed_gt10", "REAL", "風速が 10 m/s を超えた解析の割合", "1"),
            col("exceed_gt20", "REAL", "風速が 20 m/s を超えた解析の割合", "1"),
            col("exceed_gt30", "REAL", "風速が 30 m/s を超えた解析の割合", "1"),
            col("exceed_gt40", "REAL", "風速が 40 m/s を超えた解析の割合", "1"),
            col("constancy", "REAL",
                "定常度 speed_vector_mean / speed_mean。1 なら平均風向を信用してよく、"
                "0.3 を切ると平均風向という量に意味がない", "1"),
            col("dir_vector_mean_deg", "REAL",
                "平均風向。吹いてくる向き、北 0 度から時計回り。風速で重み付けされている",
                "degree", source="derived"),
            col("dir_unit_mean_deg", "REAL",
                "同じく平均風向だが、各解析を等重みで扱ったもの", "degree", source="derived"),
            col("resultant_length", "REAL",
                "平均合成長 R。0 なら風向がばらばら、1 ならすべて同じ向き", "1", source="derived"),
            col("circ_sd_deg", "REAL",
                "循環標準偏差 sqrt(-2 ln R)。R < 0.1 では NULL。"
                "二峰分布のときに実在しない値を出さないための表示上の措置で、"
                "fact_dir_fit.wn_sigma_deg にはこのマスクをかけていない",
                "degree", source="derived"),
            col("ellipse_major", "REAL", "分散楕円の長半径 (1 シグマ)", "m s-1", source="derived"),
            col("ellipse_minor", "REAL", "分散楕円の短半径 (1 シグマ)", "m s-1", source="derived"),
            col("ellipse_angle_deg", "REAL", "分散楕円の傾き。東から反時計回り、[0, 180)",
                "degree", source="derived"),
            col("z_mean_gpm", "REAL", "ジオポテンシャル高度の平均", "gpm"),
            col("z_std_gpm", "REAL", "ジオポテンシャル高度の標準偏差", "gpm"),
            col("alt_geom_mean_m", "REAL",
                "幾何高度の平均。ジオポテンシャル高度から緯度依存の重力と地球半径で換算したもの",
                "m"),
            col("alt_geom_mean_km", "REAL", "同じものを km で", "km", source="derived"),
            col("shear_mag", "REAL", "鉛直シアーの大きさ。隣接気圧面のベクトル平均の差",
                "m s-1 km-1", source="derived"),
        ],
        order_by=("timebin_id", "level_id", "cell_id"),
    ),
    Table(
        "fact_speed_fit",
        "風速に当てはめた分布。1 セルにつき 3 行 (正規・Weibull・一様)。"
        "パラメータ・対数尤度・AIC をそのまま持っているので、この表だけで分布を再現できる",
        [
            *_KEYS_CELL,
            col("family", "speed_family", "分布族", None, nullable=False, source="fitted"),
            col("n", "INTEGER", "当てはめに使った有限値の数。3 族とも同一", None,
                nullable=False, source="fitted"),
            col("n_eff", "REAL", "有効標本数 (fact_wind から複写)。AIC を割り引くときに使う",
                "1", source="fitted"),
            col("n_params", "TINYINT",
                "自由パラメータの数。Weibull は loc を 0 に固定しているので 3 ではなく 2",
                None, nullable=False, source="fitted"),
            col("mu_ms", "DOUBLE", "正規分布の平均", "m s-1", source="fitted"),
            col("sigma_ms", "DOUBLE", "正規分布の標準偏差 (最尤推定なので ddof=0)", "m s-1",
                source="fitted"),
            col("weibull_shape", "DOUBLE", "Weibull の形状パラメータ k", "1", source="fitted"),
            col("weibull_scale_ms", "DOUBLE", "Weibull の尺度パラメータ lambda", "m s-1",
                source="fitted"),
            col("weibull_loc_ms", "DOUBLE",
                "Weibull の位置パラメータ。常に 0 に固定。scipy の 3 引数呼び出しを"
                "曖昧にしないために明示的に格納している", "m s-1", source="fitted"),
            col("uniform_a_ms", "DOUBLE", "一様分布の下限 = 標本最小値", "m s-1", source="fitted"),
            col("uniform_b_ms", "DOUBLE", "一様分布の上限 = 標本最大値", "m s-1", source="fitted"),
            col("loglik", "DOUBLE",
                "対数尤度。自然対数、密度の単位は (m/s)^-1、n 個の観測の総和", "1",
                source="fitted"),
            col("aic", "DOUBLE", "赤池情報量規準 -2 loglik + 2 n_params", "1", source="fitted"),
            col("delta_aic", "DOUBLE",
                "このセルで収束した族の最小 AIC との差。勝者は 0", "1", source="fitted"),
            col("ks_stat", "DOUBLE",
                "コルモゴロフ・スミルノフ統計量。p 値は付けていない -- "
                "同じ標本からパラメータを推定しているので標準の帰無分布が使えないため", "1",
                source="fitted"),
            col("prob_negative", "DOUBLE",
                "正規分布のみ。当てはめた分布が負の風速に置いてしまう確率 Phi(-mu/sigma)",
                "1", source="fitted"),
            col("converged", "BOOLEAN",
                "推定が収束したか。偽なら分布が退化しており、尤度と AIC は NULL", None,
                nullable=False, source="fitted"),
            col("is_selected", "BOOLEAN", "このセルで AIC 最小だったか", None,
                nullable=False, source="fitted"),
            col("is_ambiguous", "BOOLEAN",
                "勝者だが差が小さい。2 位との AIC 差に n_eff/n を掛けた値が 2 未満のとき真。"
                "自己相関を考えると族を区別できていないという印", None,
                nullable=False, source="fitted"),
        ],
        order_by=("timebin_id", "level_id", "cell_id", "family"),
    ),
    Table(
        "fact_dir_fit",
        "風向に当てはめた分布。1 セルにつき 3 行 (von Mises・巻き付け正規・円周一様)。"
        "Weibull は角度に意味がないので候補に入れていない (meta_fit_family に理由がある)",
        [
            *_KEYS_CELL,
            col("family", "dir_family", "分布族", None, nullable=False, source="fitted"),
            col("n", "INTEGER",
                "当てはめに使った有限値の数。無風の解析は向きを持たないので落とす", None,
                nullable=False, source="fitted"),
            col("n_eff", "REAL", "有効標本数 (fact_wind から複写)", "1", source="fitted"),
            col("n_params", "TINYINT", "自由パラメータの数。円周一様は 0", None,
                nullable=False, source="fitted"),
            col("estimator", "fit_estimator",
                "推定法。巻き付け正規だけはモーメント法 -- 閉形式の最尤推定量が存在しない",
                None, nullable=False, source="fitted"),
            col("mu_deg", "DOUBLE",
                "平均方向。吹いてくる向き、北 0 度から時計回り", "degree", source="fitted"),
            col("mu_rad", "DOUBLE",
                "同じ角度を (-pi, pi] のラジアンで。密度の式はこちらを使う", "rad",
                source="fitted"),
            col("kappa", "DOUBLE", "von Mises の集中度", "1", source="fitted"),
            col("wn_sigma_rad", "DOUBLE", "巻き付け正規の標準偏差", "rad", source="fitted"),
            col("wn_sigma_deg", "DOUBLE",
                "同じものを度で。fact_wind.circ_sd_deg と同じ量だが、"
                "R < 0.1 でもマスクせず必ず埋めてある (AIC 比較を欠けさせないため)",
                "degree", source="fitted"),
            col("resultant_length", "DOUBLE",
                "平均合成長 R。3 族が共有する十分統計量", "1", nullable=False, source="fitted"),
            col("loglik", "DOUBLE",
                "対数尤度。自然対数、密度の単位は rad^-1、n 個の観測の総和。"
                "度で当てはめると n ln(180/pi) ずれるので、風速の対数尤度とは比較できない",
                "1", source="fitted"),
            col("aic", "DOUBLE", "赤池情報量規準", "1", source="fitted"),
            col("delta_aic", "DOUBLE", "このセルで収束した族の最小 AIC との差", "1",
                source="fitted"),
            col("kuiper_stat", "DOUBLE",
                "カイパー統計量 V = D+ + D-。円の回転に対して不変なので、"
                "KS ではなくこちらを使う", "1", source="fitted"),
            col("converged", "BOOLEAN", "推定が収束したか", None, nullable=False, source="fitted"),
            col("is_selected", "BOOLEAN", "このセルで AIC 最小だったか", None,
                nullable=False, source="fitted"),
            col("is_ambiguous", "BOOLEAN", "勝者だが有効標本数で割り引くと差が 2 未満", None,
                nullable=False, source="fitted"),
        ],
        order_by=("timebin_id", "level_id", "cell_id", "family"),
    ),
    Table(
        "fact_wind_rose",
        "風配図の度数。代表 1 格子点のみ (dim_grid.is_rose_cell が真の点)。"
        "全格子点ぶん持つと他のすべてを合わせたより大きくなるため",
        [
            col("timebin_id", "SMALLINT", "時期ビン", None, nullable=False, source="derived"),
            col("level_id", "SMALLINT", "気圧面", None, nullable=False, source="derived"),
            col("month", "TINYINT", "月", None, nullable=False, source="derived"),
            col("bin", "TINYINT", "1 = 前半、2 = 後半", None, nullable=False, source="derived"),
            col("level_hpa", "DOUBLE", "気圧面", "hPa", nullable=False, source="derived"),
            col("sector", "SMALLINT", "方位区分", None, nullable=False, source="derived"),
            col("speed_class", "SMALLINT", "風速階級", None, nullable=False, source="derived"),
            col("cell_id", "SMALLINT", "代表格子点", None, nullable=False, source="derived"),
            col("count", "INTEGER", "この方位・風速階級に入った解析の数", None,
                nullable=False, check="count >= 0"),
        ],
        primary_key=("timebin_id", "level_id", "sector", "speed_class"),
        order_by=("timebin_id", "level_id", "sector", "speed_class"),
    ),
    Table(
        "fact_wind_diurnal",
        "解析時刻ごとの風。300 hPa 以下のみ。時刻で割るとビンの標本が 4 分の 1 になるため、"
        "パーセンタイルは持たせていない",
        [
            col("timebin_id", "SMALLINT", "時期ビン", None, nullable=False, source="derived"),
            col("level_id", "SMALLINT", "気圧面", None, nullable=False, source="derived"),
            col("cell_id", "SMALLINT", "格子点", None, nullable=False, source="derived"),
            col("month", "TINYINT", "月", None, nullable=False, source="derived"),
            col("bin", "TINYINT", "1 = 前半、2 = 後半", None, nullable=False, source="derived"),
            col("hour_utc", "TINYINT", "解析時刻 (UTC)", "h", nullable=False, source="derived"),
            col("level_hpa", "DOUBLE", "気圧面", "hPa", nullable=False, source="derived"),
            col("lat", "DOUBLE", "緯度", "degrees_north", nullable=False, source="derived"),
            col("lon", "DOUBLE", "経度 (符号付き)", "degrees_east", nullable=False,
                source="derived"),
            col("n", "INTEGER", "この時刻に入った解析の数", None, nullable=False),
            col("u_mean", "REAL", "東向き風速の平均", "m s-1"),
            col("v_mean", "REAL", "北向き風速の平均", "m s-1"),
            col("speed_mean", "REAL", "スカラー平均風速", "m s-1"),
            col("speed_std", "REAL", "風速の標準偏差", "m s-1"),
            col("constancy", "REAL", "定常度", "1"),
            col("dir_vector_mean_deg", "REAL",
                "平均風向 (吹いてくる向き)。u_mean と v_mean から導出", "degree",
                source="derived"),
        ],
        order_by=("timebin_id", "level_id", "cell_id", "hour_utc"),
    ),
    Table(
        "fact_drift",
        "公称飛行 1 本 (上昇 5 m/s、破裂 30 km、降下 6 m/s) での落下位置。"
        "気圧面をまたいで積算した量なので気圧面の次元を持たない",
        [
            col("timebin_id", "SMALLINT", "時期ビン", None, nullable=False, source="derived"),
            col("cell_id", "SMALLINT", "打ち上げ格子点", None, nullable=False, source="derived"),
            col("month", "TINYINT", "月", None, nullable=False, source="derived"),
            col("bin", "TINYINT", "1 = 前半、2 = 後半", None, nullable=False, source="derived"),
            col("lat", "DOUBLE", "打ち上げ点の緯度", "degrees_north", nullable=False,
                source="derived"),
            col("lon", "DOUBLE", "打ち上げ点の経度 (符号付き)", "degrees_east",
                nullable=False, source="derived"),
            col("n", "INTEGER", "計算に使った飛行の数", None),
            col("east_m", "REAL", "東向きの平均変位", "m"),
            col("north_m", "REAL", "北向きの平均変位", "m"),
            col("east_var_m2", "REAL", "東向き変位の分散", "m2"),
            col("north_var_m2", "REAL", "北向き変位の分散", "m2"),
            col("cov_m2", "REAL", "東西と南北の変位の共分散", "m2"),
            col("dist_mean_km", "REAL", "飛行距離の平均", "km"),
            col("dist_p50_km", "REAL", "飛行距離の中央値", "km"),
            col("dist_p90_km", "REAL", "飛行距離の 90 パーセンタイル", "km"),
            col("dist_p95_km", "REAL", "飛行距離の 95 パーセンタイル", "km"),
            col("dist_max_km", "REAL", "飛行距離の最大", "km"),
            col("bearing_deg", "REAL",
                "注意: これだけは機体が進んでいく方位で、"
                "この DB の他のすべての方位 (吹いてくる向き) とちょうど 180 度逆である。"
                "西風は風向 270 度だが、機体を 90 度の方へ運ぶ", "degree"),
            col("bearing_from_deg", "REAL",
                "上を 180 度回して他の方位列と揃えたもの = (bearing_deg + 180) mod 360",
                "degree", source="derived"),
            col("flight_time_s", "REAL", "飛行時間", "s"),
        ],
        primary_key=("timebin_id", "cell_id"),
        order_by=("timebin_id", "cell_id"),
    ),
    # --------------------------------------------------------- metadata ---
    Table(
        "meta_dataset",
        "このデータベース全体についての事実。出自・規約・既知の注意点",
        [
            col("key", "VARCHAR", "項目名", None, nullable=False, source="derived"),
            col("value", "VARCHAR", "値", None, nullable=False, source="derived"),
            col("note", "VARCHAR", "補足", None, source="derived"),
        ],
        primary_key=("key",),
        order_by=("key",),
    ),
    Table(
        "meta_column",
        "列の辞書。この表が全テーブルの全列の意味と単位を持っている。"
        "ドキュメントのスキーマ章はここと COMMENT ON から生成される",
        [
            col("table_name", "VARCHAR", "テーブル名", None, nullable=False, source="derived"),
            col("column_name", "VARCHAR", "列名", None, nullable=False, source="derived"),
            col("data_type", "VARCHAR", "型", None, nullable=False, source="derived"),
            col("units", "VARCHAR", "単位。無次元やラベルの列は NULL", None, source="derived"),
            col("description", "VARCHAR", "意味", None, nullable=False, source="derived"),
            col("source", "VARCHAR",
                "値の出どころ。netcdf = 元の統計プロダクト、derived = そこから導出、"
                "fitted = この DB で当てはめた", None, nullable=False, source="derived"),
        ],
        primary_key=("table_name", "column_name"),
        order_by=("table_name", "column_name"),
    ),
    Table(
        "meta_fit_family",
        "分布族の定義。密度・パラメータ・推定量・対数尤度・乱数の作り方を式として持つ。"
        "この表があるので、PDF を読まなくても表だけから分布を再現できる",
        [
            col("quantity", "VARCHAR", "対象量。speed_ms または direction_rad", None,
                nullable=False, source="derived"),
            col("family", "VARCHAR", "族の名前", None, nullable=False, source="derived"),
            col("included", "BOOLEAN", "候補に入れているか", None, nullable=False,
                source="derived"),
            col("exclusion_reason", "VARCHAR", "候補に入れていない場合その理由", None,
                source="derived"),
            col("n_params", "TINYINT", "自由パラメータの数", None, nullable=False,
                source="derived"),
            col("support", "VARCHAR", "台 (値の取りうる範囲)", None, nullable=False,
                source="derived"),
            col("density_unit", "VARCHAR", "密度の単位。AIC を比較してよい範囲を決める", None,
                nullable=False, source="derived"),
            col("param_columns", "VARCHAR", "パラメータが入っている列の名前", None,
                nullable=False, source="derived"),
            col("pdf_plain", "VARCHAR", "確率密度関数 (ASCII)", None, nullable=False,
                source="derived"),
            col("pdf_latex", "VARCHAR", "同じものを LaTeX で", None, nullable=False,
                source="derived"),
            col("cdf_plain", "VARCHAR", "累積分布関数 (ASCII)。閉形式が無い場合はその旨",
                None, source="derived"),
            col("ppf_plain", "VARCHAR",
                "分位点関数。一様乱数からこの分布に従う値を作る式", None, source="derived"),
            col("loglik_plain", "VARCHAR", "loglik 列に入っている値の式", None,
                nullable=False, source="derived"),
            col("estimator", "VARCHAR", "推定法 (mle または mom)", None, nullable=False,
                source="derived"),
            col("estimator_note", "VARCHAR", "推定法についての注意", None, source="derived"),
            col("gof_stat", "VARCHAR", "適合度統計量の名前", None, source="derived"),
            col("scipy_equivalent", "VARCHAR",
                "同じ分布を scipy で作るときの式", None, source="derived"),
            col("reference", "VARCHAR", "出典", None, source="derived"),
        ],
        primary_key=("quantity", "family"),
        order_by=("quantity", "family"),
    ),
    Table(
        "meta_provenance",
        "ビルドの記録。いつ・何を読んで・どれだけかかったか",
        [
            col("step", "VARCHAR", "工程", None, nullable=False, source="derived"),
            col("tool", "VARCHAR", "使ったもの", None, nullable=False, source="derived"),
            col("tool_version", "VARCHAR", "そのバージョン", None, nullable=False,
                source="derived"),
            col("started_at", "TIMESTAMP", "開始時刻", None, nullable=False, source="derived"),
            col("finished_at", "TIMESTAMP", "終了時刻", None, source="derived"),
            col("host", "VARCHAR", "実行したホスト", None, source="derived"),
            col("input_name", "VARCHAR", "入力ファイル名 (所在は記録しない)", None,
    source="derived"),
            col("input_sha256", "VARCHAR", "入力の SHA-256", None, source="derived"),
            col("rows_written", "BIGINT", "書き出した行数", None, source="derived"),
            col("peak_rss_mb", "DOUBLE", "ピークメモリ", "MB", source="derived"),
            col("note", "VARCHAR", "補足", None, source="derived"),
        ],
        order_by=("started_at",),
    ),
    Table(
        "meta_reference",
        "引用すべき文献",
        [
            col("kind", "VARCHAR", "種別", None, nullable=False, source="derived"),
            col("citation", "VARCHAR", "書誌", None, nullable=False, source="derived"),
            col("doi", "VARCHAR", "DOI", None, source="derived"),
            col("url", "VARCHAR", "URL", None, source="derived"),
        ],
        order_by=("kind",),
    ),
    Table(
        "meta_license",
        "ライセンス。このデータベースは JRA-3Q の派生物であり、同じ条件を継承する",
        [
            col("applies_to", "VARCHAR", "対象。source_data または database", None,
                nullable=False, source="derived"),
            col("spdx_id", "VARCHAR", "SPDX 識別子", None, nullable=False, source="derived"),
            col("name", "VARCHAR", "ライセンス名", None, nullable=False, source="derived"),
            col("url", "VARCHAR", "全文の URL", None, nullable=False, source="derived"),
            col("non_commercial", "BOOLEAN", "非商用限定か", None, nullable=False,
                source="derived"),
            col("share_alike", "BOOLEAN", "継承条項があるか", None, nullable=False,
                source="derived"),
            col("attribution_required", "BOOLEAN", "表示が必要か", None, nullable=False,
                source="derived"),
            col("inherits_from", "VARCHAR", "どこから継承したか", None, source="derived"),
            col("attribution_text", "VARCHAR", "そのまま使える表示文", None, nullable=False,
                source="derived"),
            col("full_notice", "VARCHAR", "全文の告知", None, nullable=False, source="derived"),
        ],
        primary_key=("applies_to",),
        order_by=("applies_to",),
    ),
]

TABLES_BY_NAME = {t.name: t for t in TABLES}


def iter_columns():
    """``(table, column)`` for every declared column."""
    for table in TABLES:
        for column in table.columns:
            yield table, column


def create_statements() -> list[str]:
    """``CREATE TYPE`` then ``CREATE TABLE`` for the whole schema."""
    out = []
    for name, values in ENUMS.items():
        members = ", ".join(f"'{v}'" for v in values)
        out.append(f"CREATE TYPE {name} AS ENUM ({members});")
    out.extend(t.ddl() for t in TABLES)
    return out


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def comment_statements() -> list[str]:
    """``COMMENT ON`` for every table and every column.

    Generated from the same declarations as the DDL, so a column can never be
    created without its description.
    """
    out = []
    for table in TABLES:
        out.append(f"COMMENT ON TABLE {table.name} IS {_quote(table.comment)};")
        for column in table.columns:
            out.append(
                f"COMMENT ON COLUMN {table.name}.{column.name} "
                f"IS {_quote(column.full_comment())};"
            )
    return out
