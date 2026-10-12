# このデータベースのライセンス

`jra3q_hokkaido_wind_2016-2025_v1.duckdb` とその中身は
**CC BY-NC-SA 4.0**（表示 – 非営利 – 継承 4.0 国際）で提供される。
これは**リポジトリ本体のライセンスではない**。

<https://creativecommons.org/licenses/by-nc-sa/4.0/>

## なぜこのライセンスになるのか

元データは気象庁の第 3 次長期再解析 **JRA-3Q** で、NSF NCAR GDEX
（データセット `d640000`）から CC BY-NC-SA 4.0 で配布されている。
このデータベースはそれを集計し分布を当てはめた**派生物**なので、
継承条項によって同じライセンスが付く。

`../LICENSE-DATA.md` に元データ側の説明がある。本ファイルはその帰結を
このデータベースについて具体的に書いたもの。

## 三つの帰結

1. **非営利限定。** 商用利用はできない。
2. **継承。** このデータベース、その一部、あるいはここから作った派生物を
   再配布する場合、同じ CC BY-NC-SA 4.0 を付けなければならない。
3. **表示が必要。** 下の出典表記を添えること。

そして 4 つ目、このリポジトリに固有のもの:

4. **Web アプリのビルドに混ぜないこと。** 継承条項があるため、
   `research/` の出力は意図的にアプリケーションのビルドから外してある。
   このデータベースも同じ扱いとする。

## 出典表記

そのまま使える形:

> JRA-3Q reanalysis, Japan Meteorological Agency, distributed by NSF NCAR GDEX
> (dataset d640000). Kosaka, Y. and co-authors, 2024: The JRA-3Q Reanalysis.
> *J. Meteor. Soc. Japan*, **102**, 49–109, doi:10.2151/jmsj.2024-004.
> Licensed CC BY-NC-SA 4.0.

BibTeX:

```bibtex
@article{kosaka2024jra3q,
  author  = {Kosaka, Yu and others},
  title   = {The {JRA-3Q} Reanalysis},
  journal = {Journal of the Meteorological Society of Japan},
  volume  = {102}, number = {1}, pages = {49--109}, year = {2024},
  doi     = {10.2151/jmsj.2024-004},
}
```

## データベースの中からも読める

同じ内容がデータベース自身に入っているので、ファイルだけを受け取った人でも
確認できる:

```sql
SELECT * FROM v_license;
```
