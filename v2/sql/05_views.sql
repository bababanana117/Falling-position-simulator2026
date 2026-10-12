-- Views: the shapes people actually query.
--
-- The fact tables are normalised and wide. These are the joins that would
-- otherwise be retyped every time, plus the two that do the real work:
-- v_speed_fit_selected and v_dir_fit_selected render the chosen distribution
-- as a formula with its own constants substituted in, so a row of the result
-- is a complete, self-contained description of a distribution.

-- The shortest useful query in the database.
CREATE VIEW v_license AS SELECT * FROM meta_license;

-- Wind statistics with every dimension attribute spelled out.
CREATE VIEW v_wind AS
SELECT
    w.month, w.bin, t.bin_label_ja, t.season, t.season_ja,
    w.level_hpa, w.alt_geom_mean_km, w.lat, w.lon,
    w.n, w.n_eff,
    w.speed_mean, w.speed_vector_mean, w.speed_std,
    w.speed_p10, w.speed_p50, w.speed_p90, w.speed_max,
    w.dir_vector_mean_deg, w.constancy, w.circ_sd_deg, w.resultant_length,
    w.shear_mag,
    w.timebin_id, w.level_id, w.cell_id
FROM fact_wind w
JOIN dim_timebin t USING (timebin_id);

-- One launch point, one half-month: the profile a balloon actually flies
-- through, ordered by height rather than by pressure.
CREATE VIEW v_profile AS
SELECT
    w.month, w.bin, t.bin_label_ja, w.lat, w.lon,
    w.level_hpa, w.alt_geom_mean_km,
    w.speed_mean, w.speed_p90, w.dir_vector_mean_deg, w.constancy,
    w.cell_id, w.level_id, w.timebin_id
FROM fact_wind w
JOIN dim_timebin t USING (timebin_id)
ORDER BY w.timebin_id, w.cell_id, w.alt_geom_mean_km;

-- The selected speed distribution, rendered.
--
-- pdf_rendered and sample_recipe are the point of the whole database: they
-- carry the formula with this cell's own constants already substituted, so
-- the row can be used without joining to meta_fit_family and without reading
-- the documentation. delta_aic_effective deflates the AIC gap by the serial
-- correlation, which is the number a reader should actually judge by.
CREATE VIEW v_speed_fit_selected AS
SELECT
    f.month, f.bin, t.bin_label_ja, t.season_ja,
    f.level_hpa, w.alt_geom_mean_km, f.lat, f.lon,
    f.family, f.n, f.n_eff,
    f.mu_ms, f.sigma_ms, f.weibull_shape, f.weibull_scale_ms,
    f.uniform_a_ms, f.uniform_b_ms,
    f.loglik, f.aic, f.ks_stat, f.prob_negative, f.is_ambiguous,
    (SELECT min(g.delta_aic) FROM fact_speed_fit g
      WHERE g.timebin_id = f.timebin_id AND g.level_id = f.level_id
        AND g.cell_id = f.cell_id AND NOT g.is_selected) AS runner_up_delta_aic,
    (SELECT min(g.delta_aic) FROM fact_speed_fit g
      WHERE g.timebin_id = f.timebin_id AND g.level_id = f.level_id
        AND g.cell_id = f.cell_id AND NOT g.is_selected) * f.n_eff / f.n
        AS delta_aic_effective,
    CASE f.family
      WHEN 'normal' THEN printf(
          'f(x) = 1/(%.9g*sqrt(2*pi)) * exp(-(x-%.9g)^2/(2*%.9g^2)),  x in m/s',
          f.sigma_ms, f.mu_ms, f.sigma_ms)
      WHEN 'weibull_min_loc0' THEN printf(
          'f(x) = (%.9g/%.9g) * (x/%.9g)^(%.9g-1) * exp(-(x/%.9g)^%.9g),  x >= 0, x in m/s',
          f.weibull_shape, f.weibull_scale_ms, f.weibull_scale_ms,
          f.weibull_shape, f.weibull_scale_ms, f.weibull_shape)
      WHEN 'uniform' THEN printf(
          'f(x) = 1/(%.9g-%.9g) for %.9g <= x <= %.9g, else 0,  x in m/s',
          f.uniform_b_ms, f.uniform_a_ms, f.uniform_a_ms, f.uniform_b_ms)
    END AS pdf_rendered,
    CASE f.family
      WHEN 'normal' THEN printf('x = %.9g + %.9g * Phi_inv(u)', f.mu_ms, f.sigma_ms)
      WHEN 'weibull_min_loc0' THEN printf(
          'x = %.9g * pow(-ln(1-u), 1/%.9g)', f.weibull_scale_ms, f.weibull_shape)
      WHEN 'uniform' THEN printf(
          'x = %.9g + (%.9g-%.9g)*u', f.uniform_a_ms, f.uniform_b_ms, f.uniform_a_ms)
    END AS sample_recipe,
    f.timebin_id, f.level_id, f.cell_id
FROM fact_speed_fit f
JOIN dim_timebin t USING (timebin_id)
JOIN fact_wind w
  ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id AND w.cell_id = f.cell_id
WHERE f.is_selected;

CREATE VIEW v_dir_fit_selected AS
SELECT
    f.month, f.bin, t.bin_label_ja, t.season_ja,
    f.level_hpa, w.alt_geom_mean_km, f.lat, f.lon,
    f.family, f.estimator, f.n, f.n_eff,
    f.mu_deg, f.mu_rad, f.kappa, f.wn_sigma_deg, f.resultant_length,
    f.loglik, f.aic, f.kuiper_stat, f.is_ambiguous,
    (SELECT min(g.delta_aic) FROM fact_dir_fit g
      WHERE g.timebin_id = f.timebin_id AND g.level_id = f.level_id
        AND g.cell_id = f.cell_id AND NOT g.is_selected) * f.n_eff / f.n
        AS delta_aic_effective,
    CASE f.family
      WHEN 'von_mises' THEN printf(
          'f(theta) = exp(%.9g*cos(theta-(%.9g))) / (2*pi*I0(%.9g)),  theta in rad',
          f.kappa, f.mu_rad, f.kappa)
      WHEN 'wrapped_normal' THEN printf(
          'f(theta) = (1/(2*pi))*(1 + 2*sum_p %.9g^(p*p)*cos(p*(theta-(%.9g)))),  theta in rad',
          f.resultant_length, f.mu_rad)
      WHEN 'circular_uniform' THEN 'f(theta) = 1/(2*pi),  theta in rad'
    END AS pdf_rendered,
    f.timebin_id, f.level_id, f.cell_id
FROM fact_dir_fit f
JOIN dim_timebin t USING (timebin_id)
JOIN fact_wind w
  ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id AND w.cell_id = f.cell_id
WHERE f.is_selected;

-- One row per cell with all three families side by side, for comparing them.
CREATE VIEW v_speed_fit_wide AS
SELECT
    timebin_id, level_id, cell_id, month, bin, level_hpa, lat, lon, n, n_eff,
    max(CASE WHEN family = 'normal'           THEN delta_aic END) AS delta_aic_normal,
    max(CASE WHEN family = 'weibull_min_loc0' THEN delta_aic END) AS delta_aic_weibull,
    max(CASE WHEN family = 'uniform'          THEN delta_aic END) AS delta_aic_uniform,
    max(CASE WHEN family = 'normal'           THEN ks_stat END)   AS ks_normal,
    max(CASE WHEN family = 'weibull_min_loc0' THEN ks_stat END)   AS ks_weibull,
    max(CASE WHEN family = 'uniform'          THEN ks_stat END)   AS ks_uniform,
    max(CASE WHEN is_selected THEN family END)                    AS selected_family
FROM fact_speed_fit
GROUP BY ALL;

CREATE VIEW v_dir_fit_wide AS
SELECT
    timebin_id, level_id, cell_id, month, bin, level_hpa, lat, lon, n, n_eff,
    max(resultant_length) AS resultant_length,
    max(CASE WHEN family = 'von_mises'        THEN delta_aic END) AS delta_aic_von_mises,
    max(CASE WHEN family = 'wrapped_normal'   THEN delta_aic END) AS delta_aic_wrapped_normal,
    max(CASE WHEN family = 'circular_uniform' THEN delta_aic END) AS delta_aic_circular_uniform,
    max(CASE WHEN is_selected THEN family END)                    AS selected_family
FROM fact_dir_fit
GROUP BY ALL;

-- The wind rose with its bins labelled and counts turned into frequencies.
CREATE VIEW v_rose AS
SELECT
    r.month, r.bin, t.bin_label_ja, r.level_hpa,
    s.compass_16, s.centre_deg, c.label AS speed_class_label, c.lo_ms, c.hi_ms,
    r.count,
    100.0 * r.count / sum(r.count) OVER (PARTITION BY r.timebin_id, r.level_id)
        AS frequency_pct,
    r.timebin_id, r.level_id, r.sector, r.speed_class
FROM fact_wind_rose r
JOIN dim_timebin t USING (timebin_id)
JOIN dim_sector s USING (sector)
JOIN dim_speed_class c USING (speed_class);

-- The regional mean, weighted the way a regional mean must be weighted.
CREATE VIEW v_area_mean AS
SELECT
    w.month, w.bin, t.bin_label_ja, w.level_hpa,
    sum(w.speed_mean * g.gauss_weight) / sum(g.gauss_weight) AS speed_mean,
    sum(w.speed_vector_mean * g.gauss_weight) / sum(g.gauss_weight) AS speed_vector_mean,
    sum(w.constancy * g.gauss_weight) / sum(g.gauss_weight) AS constancy,
    sum(w.alt_geom_mean_m * g.gauss_weight) / sum(g.gauss_weight) AS alt_geom_mean_m,
    max(w.speed_mean) - min(w.speed_mean) AS speed_mean_spread,
    w.timebin_id, w.level_id
FROM fact_wind w
JOIN dim_grid g USING (cell_id)
JOIN dim_timebin t USING (timebin_id)
GROUP BY ALL;

-- Lets a reader see at a glance whether the column dictionary and the real
-- catalogue agree. 90_verify.sql turns a disagreement into a build failure.
CREATE VIEW v_column_dictionary AS
SELECT
    m.table_name, m.column_name, m.data_type AS declared_type,
    c.data_type AS actual_type, m.units, m.description, m.source,
    c.comment AS catalogue_comment
FROM meta_column m
FULL OUTER JOIN (
    -- Base tables only: view columns are renamings of these and are described
    -- by the comment on the view itself.
    SELECT c.table_name, c.column_name, c.data_type, c.comment
    FROM duckdb_columns() c
    JOIN duckdb_tables() t
      ON t.database_name = c.database_name AND t.schema_name = c.schema_name
     AND t.table_name = c.table_name
    WHERE c.database_name = current_database() AND c.schema_name = 'main'
      AND NOT c.internal
) c USING (table_name, column_name);


-- Views get a description of their own. Their columns are renamings and joins
-- of columns that meta_column already documents, so the explanation belongs
-- at the view level; 90_verify.sql checks base-table columns individually and
-- views as wholes.
COMMENT ON VIEW v_license IS 'ライセンス。このファイルを受け取った人が最初に実行すべきクエリ';
COMMENT ON VIEW v_wind IS '風の統計に時期ビンの属性を結合したもの。1 行 = (時期ビン, 気圧面, 格子点)';
COMMENT ON VIEW v_profile IS '1 地点 1 時期の鉛直プロファイル。気圧順ではなく高度順に並べてある';
COMMENT ON VIEW v_speed_fit_selected IS
  '風速で選ばれた分布。pdf_rendered に定数を埋め込んだ式が、sample_recipe に'
  '逆関数法の式が入っているので、この 1 行だけで分布を再現できる。'
  'delta_aic_effective は自己相関で割り引いた差で、判断はこちらで行う';
COMMENT ON VIEW v_dir_fit_selected IS '風向で選ばれた分布。式は pdf_rendered に入っている';
COMMENT ON VIEW v_speed_fit_wide IS '1 セル 1 行。3 族の delta_aic と KS を横に並べたもの';
COMMENT ON VIEW v_dir_fit_wide IS '1 セル 1 行。円周 3 族の delta_aic を横に並べたもの';
COMMENT ON VIEW v_rose IS '風配図。方位と風速階級にラベルを付け、度数を割合にしたもの';
COMMENT ON VIEW v_area_mean IS
  '領域平均。gauss_weight で重み付けしてある。speed_mean_spread は領域内の幅';
COMMENT ON VIEW v_column_dictionary IS
  'meta_column と実際のカタログの突き合わせ。食い違いがあればここに出る';
