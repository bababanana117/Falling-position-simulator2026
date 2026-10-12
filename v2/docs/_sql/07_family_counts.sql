-- どの族がどれだけ選ばれたか。一様分布は当て馬ではなく本当の候補にしてある。
SELECT 'speed' AS quantity, family, count(*) AS cells,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct,
       round(100.0 * sum(CASE WHEN is_ambiguous THEN 1 ELSE 0 END) / count(*), 1) AS pct_ambiguous
FROM fact_speed_fit WHERE is_selected GROUP BY ALL
UNION ALL
SELECT 'direction', family, count(*),
       round(100.0 * count(*) / sum(count(*)) OVER (), 1),
       round(100.0 * sum(CASE WHEN is_ambiguous THEN 1 ELSE 0 END) / count(*), 1)
FROM fact_dir_fit WHERE is_selected GROUP BY ALL
ORDER BY quantity, cells DESC;
