-- JOIN は 2 つの表を共通の列でつなぐ。
-- fact_wind は時期を timebin_id という番号でしか持たない。日本語のラベルや
-- 季節が欲しければ、それらを持っている dim_timebin をつなぐ。
SELECT w.month, t.bin_label_ja, t.season_ja,
       round(avg(w.speed_mean), 1) AS avg_ms
FROM fact_wind w
JOIN dim_timebin t ON t.timebin_id = w.timebin_id
WHERE w.level_hpa = 200
GROUP BY w.month, t.bin_label_ja, t.season_ja
ORDER BY avg_ms DESC
LIMIT 4;
