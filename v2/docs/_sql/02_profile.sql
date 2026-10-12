-- 10 月後半、潮岬上空の鉛直プロファイル。気球が下から通る順に並ぶ。
SELECT level_hpa, round(alt_geom_mean_km, 2) AS alt_km,
       round(speed_mean, 1) AS speed_mean_ms,
       round(speed_p90, 1)  AS speed_p90_ms,
       round(dir_vector_mean_deg, 0) AS dir_from_deg,
       round(constancy, 2)  AS constancy
FROM profile_at(33.437, 135.762, 10, 2)
WHERE level_hpa IN (1000, 850, 500, 300, 200, 100, 30, 10)
ORDER BY level_hpa DESC;
