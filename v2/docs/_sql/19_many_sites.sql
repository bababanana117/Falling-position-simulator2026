-- 全国の地点を一度に。VALUES で地点を並べ、それぞれの最寄り格子点を引く。
-- 1 月前半・200 hPa（約 12 km、ジェット気流の高さ）の平均風速と定常度。
SELECT q.name, round(c.distance_km, 1) AS dist_km,
       round(w.speed_mean, 1) AS speed_mean_ms,
       round(w.dir_vector_mean_deg, 0) AS dir_from_deg,
       round(w.constancy, 2) AS constancy
FROM (VALUES ('稚内', 45.415, 141.673), ('大樹町', 42.506, 143.440),
             ('仙台', 38.268, 140.870), ('東京', 35.681, 139.767),
             ('潮岬', 33.437, 135.762), ('福岡', 33.590, 130.402),
             ('那覇', 26.212, 127.679), ('父島', 27.094, 142.192)) AS q(name, lat, lon),
     LATERAL (SELECT * FROM nearest_cell(q.lat, q.lon)) AS c
JOIN fact_wind w ON w.cell_id = c.cell_id
WHERE w.month = 1 AND w.bin = 1 AND w.level_hpa = 200
ORDER BY q.lat DESC;
