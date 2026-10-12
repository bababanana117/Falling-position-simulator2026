-- 同じ地点・同じ時期で選ばれた分布。1 行が 1 つの分布の完全な定義になっている。
SELECT level_hpa, speed_family, dir_family,
       round(coalesce(weibull_shape, sigma_ms), 2) AS k_or_sigma,
       round(coalesce(weibull_scale_ms, mu_ms), 1) AS lam_or_mu,
       round(mu_deg, 0) AS dir_mu_deg,
       round(kappa, 1)  AS kappa
FROM fits_at(33.437, 135.762, 10, 2)
WHERE level_hpa IN (850, 500, 300, 200, 100)
ORDER BY level_hpa DESC;
