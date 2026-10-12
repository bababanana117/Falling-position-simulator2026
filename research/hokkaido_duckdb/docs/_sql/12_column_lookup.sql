-- 列の意味を忘れたとき。データベース自身が辞書を持っている。
SELECT table_name, column_name, declared_type, units, description
FROM v_column_dictionary
WHERE column_name IN ('constancy', 'n_eff', 'bearing_deg')
ORDER BY table_name, column_name;
