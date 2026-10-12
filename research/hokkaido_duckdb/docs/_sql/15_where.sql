-- WHERE で行を絞る。条件は AND でつなぐ。
-- 1 月前半・200 hPa・北緯 42 度より北、風速の強い順に 5 行。
SELECT round(lat, 2) AS lat, lon, round(speed_mean, 1) AS speed_mean
FROM fact_wind
WHERE month = 1 AND bin = 1 AND level_hpa = 200 AND lat > 42.0
ORDER BY speed_mean DESC
LIMIT 5;
