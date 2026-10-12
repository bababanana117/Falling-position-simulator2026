-- GROUP BY でまとめる。まとめたあとの計算が avg() や max() などの集計関数。
-- 気圧面ごとに、570 格子点 × 24 ビンの平均と最大を出す。
SELECT level_hpa,
       count(*)                 AS rows,
       round(avg(speed_mean), 1) AS avg_ms,
       round(max(speed_p95), 1)  AS worst_p95_ms
FROM fact_wind
WHERE level_hpa IN (1000, 500, 200, 50)
GROUP BY level_hpa
ORDER BY level_hpa DESC;
