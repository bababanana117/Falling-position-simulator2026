-- いちばん簡単なクエリ。表から 3 行だけ取り出す。
-- SELECT に列名、FROM に表の名前、LIMIT に取り出す行数を書く。
SELECT month, bin, level_hpa, lat, lon, speed_mean
FROM fact_wind
LIMIT 3;
