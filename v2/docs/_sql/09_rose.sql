-- 風配図。代表 1 格子点のみ収録。1 月前半・300 hPa の上位 5 方位。
SELECT compass_16, speed_class_label, count,
       round(frequency_pct, 1) AS frequency_pct
FROM v_rose
WHERE month = 1 AND bin = 1 AND level_hpa = 300 AND count > 0
ORDER BY count DESC LIMIT 5;
