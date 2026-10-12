-- pdf_rendered と sample_recipe は、そのセルの定数を埋め込んだ式を文字列で返す。
-- この 2 つと一様乱数だけで分布を再現できる。
SELECT level_hpa, speed_pdf, speed_sample
FROM fits_at(42.506, 143.440, 10, 2)
WHERE level_hpa IN (300, 100);
