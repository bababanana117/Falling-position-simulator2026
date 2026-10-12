-- 打ち上げに最も不利な時期はどれか。300 hPa の p90 が最大の半月を探す。
SELECT t.bin_label_ja, w.month, w.bin,
       round(max(w.speed_p90), 1)  AS worst_p90_ms,
       round(avg(w.speed_mean), 1) AS mean_ms
FROM fact_wind w JOIN dim_timebin t USING (timebin_id)
WHERE w.level_hpa = 300
GROUP BY ALL
ORDER BY worst_p90_ms DESC
LIMIT 5;
