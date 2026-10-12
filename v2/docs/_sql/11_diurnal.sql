-- 時刻別。18 UTC は翌日 03 JST になる (jst_next_day が真)。
SELECT h.hour_utc, h.hour_jst, h.jst_next_day,
       round(avg(d.speed_mean), 2) AS speed_mean_ms
FROM fact_wind_diurnal d JOIN dim_hour h USING (hour_utc)
WHERE d.level_hpa = 850 AND d.month = 7
GROUP BY ALL ORDER BY h.hour_utc;
