-- Assertions run at the end of every build.
--
-- Each statement must return ZERO rows. The build fails on the first one that
-- does not, and names it. Together they stand in for the primary keys and
-- foreign keys the fact tables deliberately do not declare -- DuckDB would
-- build an ART index for each, costing tens of megabytes on a 1.5-million-row
-- key for no analytical benefit, so the constraint is checked once at build
-- time instead of maintained forever.
--
-- Format: -- @name <identifier> on the line before each query.

-- @name row_count_fact_wind
SELECT 'fact_wind' AS t, count(*) AS n FROM fact_wind
HAVING count(*) <> (SELECT count(*) FROM dim_timebin) * (SELECT count(*) FROM dim_level)
                   * (SELECT count(*) FROM dim_grid);

-- @name row_count_speed_fit
SELECT 'fact_speed_fit' AS t, count(*) AS n FROM fact_speed_fit
HAVING count(*) <> 3 * (SELECT count(*) FROM fact_wind);

-- @name row_count_dir_fit
SELECT 'fact_dir_fit' AS t, count(*) AS n FROM fact_dir_fit
HAVING count(*) <> 3 * (SELECT count(*) FROM fact_wind);

-- @name row_count_rose
SELECT 'fact_wind_rose' AS t, count(*) AS n FROM fact_wind_rose
HAVING count(*) <> (SELECT count(*) FROM dim_timebin) * (SELECT count(*) FROM dim_level)
                   * (SELECT count(*) FROM dim_sector) * (SELECT count(*) FROM dim_speed_class);

-- @name row_count_diurnal
SELECT 'fact_wind_diurnal' AS t, count(*) AS n FROM fact_wind_diurnal
HAVING count(*) <> (SELECT count(*) FROM dim_timebin) * (SELECT count(*) FROM dim_hour)
                   * (SELECT count(DISTINCT level_id) FROM fact_wind_diurnal)
                   * (SELECT count(*) FROM dim_grid);

-- @name row_count_drift
SELECT 'fact_drift' AS t, count(*) AS n FROM fact_drift
HAVING count(*) <> (SELECT count(*) FROM dim_timebin) * (SELECT count(*) FROM dim_grid);

-- @name unique_fact_wind
SELECT timebin_id, level_id, cell_id, count(*) AS n
FROM fact_wind GROUP BY ALL HAVING count(*) > 1;

-- @name unique_speed_fit
SELECT timebin_id, level_id, cell_id, family, count(*) AS n
FROM fact_speed_fit GROUP BY ALL HAVING count(*) > 1;

-- @name unique_dir_fit
SELECT timebin_id, level_id, cell_id, family, count(*) AS n
FROM fact_dir_fit GROUP BY ALL HAVING count(*) > 1;

-- @name fk_wind_cell
SELECT DISTINCT w.cell_id FROM fact_wind w
ANTI JOIN dim_grid g USING (cell_id);

-- @name fk_wind_level
SELECT DISTINCT w.level_id FROM fact_wind w
ANTI JOIN dim_level l USING (level_id);

-- @name fk_wind_timebin
SELECT DISTINCT w.timebin_id FROM fact_wind w
ANTI JOIN dim_timebin t USING (timebin_id);

-- @name one_winner_speed
SELECT timebin_id, level_id, cell_id, sum(CASE WHEN is_selected THEN 1 ELSE 0 END) AS winners
FROM fact_speed_fit GROUP BY ALL HAVING winners <> 1;

-- @name one_winner_direction
SELECT timebin_id, level_id, cell_id, sum(CASE WHEN is_selected THEN 1 ELSE 0 END) AS winners
FROM fact_dir_fit GROUP BY ALL HAVING winners <> 1;

-- @name winner_has_zero_delta
SELECT timebin_id, level_id, cell_id, family, delta_aic
FROM fact_speed_fit WHERE is_selected AND delta_aic <> 0
UNION ALL
SELECT timebin_id, level_id, cell_id, family, delta_aic
FROM fact_dir_fit WHERE is_selected AND delta_aic <> 0;

-- @name all_families_failed
SELECT timebin_id, level_id, cell_id FROM fact_speed_fit
GROUP BY ALL HAVING sum(CASE WHEN converged THEN 1 ELSE 0 END) = 0;

-- @name sample_count_matches_expectation
SELECT w.timebin_id, w.n, t.n_analyses_expected
FROM fact_wind w JOIN dim_timebin t USING (timebin_id)
WHERE w.n <> t.n_analyses_expected;

-- @name fit_n_matches_wind_n
SELECT f.timebin_id, f.level_id, f.cell_id, f.n AS fit_n, w.n AS wind_n
FROM fact_speed_fit f
JOIN fact_wind w ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id
                AND w.cell_id = f.cell_id
WHERE f.n <> w.n;

-- @name direction_n_not_greater_than_wind_n
SELECT f.timebin_id, f.level_id, f.cell_id
FROM fact_dir_fit f
JOIN fact_wind w ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id
                AND w.cell_id = f.cell_id
WHERE f.n > w.n;

-- @name resultant_length_agrees_with_fact_wind
SELECT f.timebin_id, f.level_id, f.cell_id,
       f.resultant_length, w.resultant_length AS from_wind
FROM fact_dir_fit f
JOIN fact_wind w ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id
                AND w.cell_id = f.cell_id
WHERE abs(f.resultant_length - w.resultant_length) > 1e-5;

-- @name mu_agrees_with_dir_unit_mean
SELECT f.timebin_id, f.level_id, f.cell_id, f.mu_deg, w.dir_unit_mean_deg
FROM fact_dir_fit f
JOIN fact_wind w ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id
                AND w.cell_id = f.cell_id
WHERE f.family <> 'circular_uniform'
  AND w.dir_unit_mean_deg IS NOT NULL
  AND least(abs(f.mu_deg - w.dir_unit_mean_deg),
            360 - abs(f.mu_deg - w.dir_unit_mean_deg)) > 1e-3;

-- @name wrapped_normal_sigma_agrees_with_circ_sd
SELECT f.timebin_id, f.level_id, f.cell_id, f.wn_sigma_deg, w.circ_sd_deg
FROM fact_dir_fit f
JOIN fact_wind w ON w.timebin_id = f.timebin_id AND w.level_id = f.level_id
                AND w.cell_id = f.cell_id
WHERE f.family = 'wrapped_normal' AND w.circ_sd_deg IS NOT NULL
  AND abs(f.wn_sigma_deg - w.circ_sd_deg) > 1e-3;

-- @name circular_uniform_loglik_is_exact
SELECT timebin_id, level_id, cell_id, loglik, n
FROM fact_dir_fit
WHERE family = 'circular_uniform'
  AND abs(loglik + n * ln(2 * pi())) > 1e-6;

-- @name weibull_has_two_free_parameters
SELECT DISTINCT n_params, weibull_loc_ms FROM fact_speed_fit
WHERE family = 'weibull_min_loc0'
  AND (n_params <> 2 OR (converged AND weibull_loc_ms <> 0.0));

-- @name percentiles_are_ordered
SELECT timebin_id, level_id, cell_id FROM fact_wind
WHERE NOT (speed_p10 <= speed_p25 AND speed_p25 <= speed_p50
       AND speed_p50 <= speed_p75 AND speed_p75 <= speed_p90
       AND speed_p90 <= speed_p95 AND speed_p95 <= speed_max);

-- @name vector_mean_at_most_scalar_mean
SELECT timebin_id, level_id, cell_id, speed_vector_mean, speed_mean
FROM fact_wind
WHERE speed_vector_mean > speed_mean + 1e-4
   OR constancy < -1e-6 OR constancy > 1 + 1e-6;

-- @name n_eff_within_bounds
SELECT timebin_id, level_id, cell_id, n, n_eff FROM fact_wind
WHERE n_eff IS NOT NULL AND (n_eff <= 0 OR n_eff > n + 1e-6);

-- @name altitude_decreases_with_pressure
SELECT a.timebin_id, a.cell_id, a.level_hpa, a.alt_geom_mean_m
FROM fact_wind a
JOIN fact_wind b ON b.timebin_id = a.timebin_id AND b.cell_id = a.cell_id
                AND b.level_id = a.level_id + 1
WHERE a.alt_geom_mean_m <= b.alt_geom_mean_m;

-- @name drift_bearings_are_opposite
SELECT timebin_id, cell_id, bearing_deg, bearing_from_deg FROM fact_drift
WHERE bearing_deg IS NOT NULL
  AND abs(bearing_from_deg - ((bearing_deg + 180) - 360 * floor((bearing_deg + 180) / 360))) > 1e-3;

-- @name rose_counts_sum_to_n
SELECT r.timebin_id, r.level_id, sum(r.count) AS rose_total, max(w.n) AS wind_n
FROM fact_wind_rose r
JOIN fact_wind w ON w.timebin_id = r.timebin_id AND w.level_id = r.level_id
                AND w.cell_id = r.cell_id
GROUP BY ALL HAVING sum(r.count) <> max(w.n);

-- Base tables are documented column by column; views are documented as a
-- whole, because their columns are renamings of columns already described.
-- @name every_table_column_documented
SELECT c.table_name, c.column_name FROM duckdb_columns() c
JOIN duckdb_tables() t
  ON t.database_name = c.database_name AND t.schema_name = c.schema_name
 AND t.table_name = c.table_name
WHERE c.database_name = current_database() AND c.schema_name = 'main'
  AND NOT c.internal AND c.comment IS NULL;

-- @name every_view_documented
SELECT view_name FROM duckdb_views()
WHERE database_name = current_database() AND schema_name = 'main'
  AND NOT internal AND comment IS NULL;

-- @name dictionary_matches_catalogue
SELECT table_name, column_name, declared_type, actual_type
FROM v_column_dictionary
WHERE table_name IS NULL OR column_name IS NULL OR actual_type IS NULL;

-- @name licence_travels_with_the_data
SELECT count(*) AS n FROM meta_license
HAVING count(*) <> 2
    OR sum(CASE WHEN non_commercial AND share_alike AND attribution_required
                THEN 1 ELSE 0 END) <> 2;

-- The three table macros must exist and must run. A macro body is only parsed
-- when it is called, so a typo in one would otherwise ship unnoticed.
-- @name macros_exist
SELECT m.name FROM (VALUES ('nearest_cell'), ('profile_at'), ('fits_at')) AS m(name)
ANTI JOIN (SELECT function_name FROM duckdb_functions() WHERE NOT internal) f
  ON f.function_name = m.name;

-- 北から南、西から東の端まで、どの地点でも最寄り格子点が 1 つ見つかること。
-- 稚内・大樹町・東京・潮岬・那覇・与那国・父島
-- @name nearest_cell_finds_one_cell
SELECT q.name, count(*) AS n, max(c.distance_km) AS worst
FROM (VALUES ('wakkanai', 45.415, 141.673), ('taiki', 42.506, 143.440),
             ('tokyo', 35.681, 139.767), ('shionomisaki', 33.437, 135.762),
             ('naha', 26.212, 127.679), ('yonaguni', 24.467, 122.998),
             ('chichijima', 27.094, 142.192)) AS q(name, lat, lon),
     LATERAL (SELECT * FROM nearest_cell(q.lat, q.lon)) AS c
GROUP BY q.name
HAVING count(*) <> 1 OR max(c.distance_km) > 30;

-- @name fits_at_covers_every_level
SELECT count(*) AS n FROM fits_at(35.681, 139.767, 1, 1) HAVING count(*) <> 38;
