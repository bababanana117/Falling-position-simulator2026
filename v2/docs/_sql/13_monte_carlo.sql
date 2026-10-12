-- 逆関数法をデータベースの中だけで回す例。Weibull と一様は分位点関数が閉形式なので
-- SQL で書ける ("lambda" は DuckDB の予約語なので lam と綴る。正規分布の分位点関数は
-- SQL に無いため、正規が選ばれた面は Python 側で扱う)。
--
-- 標本平均が理論平均 lam*Gamma(1+1/k) に一致すれば、表の定数だけで分布を再現できた
-- ことになる。random() を使うので、標本平均は実行のたびに少し変わる。
WITH site AS (
    SELECT level_hpa, weibull_shape AS k, weibull_scale_ms AS lam
    FROM fits_at(33.437, 135.762, 10, 2)
    WHERE speed_family = 'weibull_min_loc0' AND level_hpa IN (300, 200)
),
draws AS (SELECT generate_series AS i FROM generate_series(1, 20000))
SELECT level_hpa,
       round(avg(lam * pow(-ln(1 - random()), 1.0 / k)), 2) AS sampled_mean_ms,
       round(any_value(lam) * gamma(1 + 1.0 / any_value(k)), 2) AS theoretical_mean_ms,
       count(*) AS draws
FROM site, draws GROUP BY level_hpa ORDER BY level_hpa DESC;
