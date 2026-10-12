-- 結果をファイルに書き出す。COPY の行き先で形式が決まる。
COPY (
    SELECT level_hpa, alt_geom_mean_km, speed_mean, dir_vector_mean_deg
    FROM profile_at(33.437, 135.762, 10, 2)
) TO 'shionomisaki_oct_h2.csv' (HEADER, DELIMITER ',');

-- Parquet なら型と圧縮が保たれる。
COPY (SELECT * FROM v_speed_fit_selected) TO 'speed_fits.parquet' (FORMAT parquet);
