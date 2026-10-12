-- Table macros: the lookups that are easy to get wrong.
--
-- JRA-3Q is a Gaussian grid, so the latitudes are 39.8959, 40.2708, 40.6458 ...
-- and never a round number. `WHERE lat = 42.5` returns zero rows, silently.
-- Anyone asking about a launch site has a decimal latitude, not a grid index,
-- so the nearest-cell lookup belongs in the database rather than in every
-- notebook that touches it.

-- Nearest grid point to a decimal latitude and longitude, with the distance.
-- Haversine on a sphere of radius 6371 km; the grid spacing is about 33 km, so
-- the choice of Earth model cannot change which cell wins.
CREATE MACRO nearest_cell(qlat, qlon) AS TABLE
SELECT
    cell_id, lat, lon, lon_0_360, gauss_weight,
    2 * 6371.0 * asin(sqrt(
        pow(sin(radians(lat - qlat) / 2), 2)
        + cos(radians(qlat)) * cos(radians(lat))
          * pow(sin(radians(lon - qlon) / 2), 2)
    )) AS distance_km
FROM dim_grid
ORDER BY distance_km
LIMIT 1;

-- The vertical profile a balloon launched from (qlat, qlon) flies through in
-- one half-month, ordered by height. Wraps nearest_cell so the caller never
-- has to know the grid.
CREATE MACRO profile_at(qlat, qlon, qmonth, qbin) AS TABLE
SELECT
    p.level_hpa, p.alt_geom_mean_km,
    p.speed_mean, p.speed_p90, p.dir_vector_mean_deg, p.constancy,
    p.bin_label_ja, p.lat, p.lon, n.distance_km,
    p.cell_id, p.level_id, p.timebin_id
FROM nearest_cell(qlat, qlon) n
JOIN v_profile p USING (cell_id)
WHERE p.month = qmonth AND p.bin = qbin
ORDER BY p.alt_geom_mean_km;

-- The selected speed and direction distributions at one launch site, one
-- half-month, every level: the table a Monte-Carlo simulation reads.
-- pdf_rendered and sample_recipe carry this cell's own constants, so no join
-- back to meta_fit_family is needed.
CREATE MACRO fits_at(qlat, qlon, qmonth, qbin) AS TABLE
SELECT
    s.level_hpa, s.alt_geom_mean_km,
    s.family AS speed_family, s.mu_ms, s.sigma_ms,
    s.weibull_shape, s.weibull_scale_ms, s.uniform_a_ms, s.uniform_b_ms,
    s.prob_negative, s.is_ambiguous AS speed_ambiguous,
    s.pdf_rendered AS speed_pdf, s.sample_recipe AS speed_sample,
    d.family AS dir_family, d.mu_deg, d.kappa, d.wn_sigma_deg,
    d.resultant_length, d.is_ambiguous AS dir_ambiguous,
    d.pdf_rendered AS dir_pdf,
    s.n, s.n_eff, n.distance_km, s.lat, s.lon,
    s.cell_id, s.level_id, s.timebin_id
FROM nearest_cell(qlat, qlon) n
JOIN v_speed_fit_selected s USING (cell_id)
JOIN v_dir_fit_selected d
  ON d.timebin_id = s.timebin_id AND d.level_id = s.level_id AND d.cell_id = s.cell_id
WHERE s.month = qmonth AND s.bin = qbin
ORDER BY s.alt_geom_mean_km;
