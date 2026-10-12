-- 自己相関の効き方。n は 600 だが、独立標本に換算すると桁が 1 つ落ちる高度がある。
SELECT level_hpa,
       round(avg(n_eff), 0)        AS n_eff_mean,
       round(min(n_eff), 0)        AS n_eff_min,
       round(avg(lag1_autocorr), 3) AS lag1_mean
FROM fact_wind
WHERE level_hpa IN (1000, 850, 500, 300, 200, 100, 30, 10)
GROUP BY ALL ORDER BY level_hpa DESC;
