-- 200 hPa の領域平均風速の年変化。冬にジェットが強まる。
SELECT bin_label_ja, month, bin,
       round(speed_mean, 1)        AS area_mean_ms,
       round(speed_vector_mean, 1) AS vector_mean_ms,
       round(constancy, 2)         AS constancy,
       round(speed_mean_spread, 1) AS spread_ms
FROM v_area_mean
WHERE level_hpa = 200
ORDER BY month, bin;
