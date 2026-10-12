-- 公称飛行 1 本ぶんの水平移動。bearing_deg は機体が「進む」向きで、
-- ほかの列の風向 (吹いてくる向き) とは 180 度ずれる。
SELECT t.bin_label_ja,
       round(d.dist_mean_km, 1)     AS dist_mean_km,
       round(d.dist_p95_km, 1)      AS dist_p95_km,
       round(d.bearing_deg, 0)      AS travel_to_deg,
       round(d.bearing_from_deg, 0) AS wind_from_deg
FROM fact_drift d JOIN dim_timebin t USING (timebin_id)
WHERE d.cell_id = (SELECT cell_id FROM nearest_cell(33.437, 135.762))
ORDER BY d.dist_mean_km DESC LIMIT 5;
