.. _distributions:

==========
分布の定義
==========

この章がこのデータベースの中心です。風速と風向に当てはめた 6 つの族について、
密度・パラメータ・推定量・対数尤度・AIC・適合度を同じ並びで書いてあります。ここに
書かれた式と、表に入っている定数があれば、当てはめた分布を手元で再現できます。

.. Furo puts an "On this page" panel beside the text, so a local
   contents here would duplicate it -- and some Furo versions refuse
   the directive outright. The PDF has no such panel, so the chapter
   table of contents is emitted for LaTeX only.

.. only:: latex

   .. contents:: この章の内容
      :local:
      :depth: 2

当てはめの手順
==============

各セル（時期ビン × 気圧面 × 格子点、全 3,605,136 通り）について、次の手順を踏んで
います。

1. そのビンに入る 600 本または 640 本の 6 時間解析値から、風速
   :math:`x_i = \sqrt{u_i^2 + v_i^2}` と風向 :math:`\theta_i` を作る
2. 風速には 3 族、風向には 3 族を、それぞれ最尤法（巻き付け正規のみモーメント法）
   で当てはめる
3. 各族の AIC を計算し、最小のものを ``is_selected = TRUE`` とする
4. 2 位との差を ``delta_aic`` に、自己相関で縮めた差を ``delta_aic_effective`` に
   入れる

AIC は次の定義です。

.. math::

   \mathrm{AIC} = -2\ln L + 2k

ここで :math:`k` は自由パラメータの数です。Weibull は ``loc`` を 0 に固定して
いるので :math:`k = 2` であり、3 ではありません。円周一様は :math:`k = 0` です。

.. important::

   風速の尤度は m/s あたりの密度、風向の尤度は **ラジアンあたり** の密度で
   計算しています。基準が違うので、``fact_speed_fit`` と ``fact_dir_fit`` の AIC を
   比べてはいけません。:ref:`caveats` を参照してください。

風速の 3 族
===========

正規分布
--------

.. math::

   f(x) = \frac{1}{\sigma\sqrt{2\pi}}
          \exp\!\left[-\frac{(x-\mu)^2}{2\sigma^2}\right]

.. duckdb-params:: normal speed_ms

最尤推定量は標本平均と標本標準偏差（``ddof=0``）です。``fact_wind.speed_std`` は
``ddof=1`` で計算してあるので、``fact_speed_fit.sigma_ms`` とはわずかに違います。
どちらを使うかで結果が変わるほどの差ではありませんが、一致しないこと自体は
意図したものです。

正規分布は負の値に確率を与えます。その確率を ``prob_negative`` に入れてあるので、
モンテカルロに使う前に確認してください。

Weibull 分布（loc = 0）
-----------------------

.. math::

   f(x) = \frac{k}{\lambda}\left(\frac{x}{\lambda}\right)^{k-1}
          \exp\!\left[-\left(\frac{x}{\lambda}\right)^{k}\right],
   \qquad x \ge 0

.. duckdb-params:: weibull_min_loc0 speed_ms

位置パラメータを 0 に固定しているので、自由パラメータは形状 :math:`k` と尺度
:math:`\lambda` の 2 つです。

形状パラメータは次の方程式の解です。閉形式では解けないので、
``scipy.optimize.newton`` で反復して求めています。

.. math::

   \frac{\sum_i x_i^{k}\ln x_i}{\sum_i x_i^{k}}
   - \frac{1}{k} - \frac{1}{n}\sum_i \ln x_i = 0

:math:`k` が求まれば、尺度は閉形式で決まります。

.. math::

   \lambda = \left(\frac{1}{n}\sum_i x_i^{k}\right)^{1/k}

.. note::

   実装上の注意が 1 つあります。風速は最大 118 m/s、形状は最大 15 程度なので、
   :math:`x^k` をそのまま計算すると倍精度で溢れます。そこで、各セルの最大値で
   風速を割ってから計算しています。上のスコア方程式はこの変換で値が変わらない
   ので、解は同じです。

一様分布
--------

.. math::

   f(x) = \frac{1}{b-a}, \qquad a \le x \le b

.. duckdb-params:: uniform speed_ms

.. warning::

   最尤推定量 :math:`\hat a = \min_i x_i`、:math:`\hat b = \max_i x_i` は
   パラメータ空間の境界にあります。AIC の導出はパラメータが内点にあることを
   前提としているので、この族のペナルティは甘すぎます。:ref:`uniform-wins` を
   読んでから使ってください。

風向の 3 族
===========

角度は :math:`(-\pi, \pi]` のラジアンで扱います。度で当てはめると対数尤度が
:math:`n\ln(180/\pi)` だけずれるので、表に入っている値と一致しません。

3 族すべてに共通する統計量が 2 つあります。

.. math::

   \bar C = \frac{1}{n}\sum_i \cos\theta_i, \qquad
   \bar S = \frac{1}{n}\sum_i \sin\theta_i, \qquad
   \bar R = \sqrt{\bar C^2 + \bar S^2}, \qquad
   \hat\mu = \operatorname{atan2}(\bar S, \bar C)

:math:`\bar R` は平均合成長で、``resultant_length`` 列に入っています。向きが毎回
同じなら 1、ばらばらなら 0 に近づきます。

von Mises 分布
--------------

.. math::

   f(\theta) = \frac{e^{\kappa\cos(\theta-\mu)}}{2\pi I_0(\kappa)}

.. duckdb-params:: von_mises

集中度 :math:`\kappa` は次の方程式の解です。

.. math::

   A(\kappa) \equiv \frac{I_1(\kappa)}{I_0(\kappa)} = \bar R

これも閉形式では解けないので ``scipy.optimize.newton`` で解いています。
:math:`\kappa` が 100 を超えると :math:`I_0(\kappa)` は倍精度で溢れるため、
指数スケールした ``scipy.special.i0e`` と ``i1e`` を使っています。比を取るので
スケール因子は打ち消し合います。

対数尤度は溢れない形に整理してあります。

.. math::

   \ln L = n\left[\kappa\bar R - \kappa - \ln 2\pi - \ln i_{0e}(\kappa)\right]

巻き付け正規分布
----------------

.. math::

   f(\theta) = \frac{1}{2\pi}\left[1 + 2\sum_{p\ge1}
               \bar R^{\,p^{2}}\cos p(\theta-\mu)\right]

.. duckdb-params:: wrapped_normal

正規分布を円周に巻き付けた分布です。次の 2 つの表現は同じものですが、収束の
速さが逆になります。

.. math::

   f(\theta) = \frac{1}{\sigma\sqrt{2\pi}}\sum_{j=-\infty}^{\infty}
               \exp\!\left[-\frac{(\theta-\mu+2\pi j)^2}{2\sigma^2}\right]
   \qquad\text{(空間和)}

集中しているとき（:math:`\bar R` が大きく :math:`\sigma` が小さいとき）は空間和が
数項で収束し、広がっているときは Fourier 形が数項で収束します。そこで
:math:`\bar R = 0.5` を境に表現を切り替え、空間和は :math:`|j|\le 3`、Fourier 形は
:math:`p\le 12` で打ち切っています。両方を 801 項の総当たりと比べて、差が
:math:`8.9\times10^{-16}` 以下であることを確認してあります。

.. warning::

   この族だけはモーメント法です。:math:`\hat\sigma = \sqrt{-2\ln\bar R}` は第 1
   三角モーメントを厳密に一致させますが、最尤推定量ではありません。したがって
   この族の AIC は準 AIC です。

円周一様分布
------------

.. math::

   f(\theta) = \frac{1}{2\pi}

.. duckdb-params:: circular_uniform

パラメータがないので :math:`k = 0`、対数尤度は :math:`-n\ln 2\pi` です。
向きに偏りがないという帰無モデルで、線形の一様分布と違って境界の問題がないので、
AIC は厳密に正当です。

なぜ風向に Weibull を当てはめないのか
=====================================

風速と同じ 3 族を風向にも当てはめれば揃いが良さそうに見えます。しかしながら、
Weibull を角度に当てはめることには意味がありません。

.. duckdb-params:: weibull_min_loc0 direction_rad

要点は周期性です。円周上で 359 度と 1 度は 2 度しか離れていませんが、Weibull が
乗っている直線上では 358 度離れています。角度の原点を北から東に移すだけで、
推定される形状と尺度が変わってしまいます。当てはまりが悪いから外したのではなく、
量の性質に合わないので候補にしていません。

適合度
======

風速には Kolmogorov--Smirnov 統計量を使っています。

.. math::

   D = \max_i \max\!\left(
       \frac{i}{n} - F(x_{(i)}),\;
       F(x_{(i)}) - \frac{i-1}{n}\right)

風向には Kuiper 統計量を使っています。KS 統計量は原点の取り方に依存するので、
円周上では使えません。Kuiper 統計量は上方向と下方向のずれを足すため、回転に対して
不変です。実際に原点を回して確かめたところ、値の変化は :math:`1.4\times10^{-17}`
でした。

.. math::

   V = D^{+} + D^{-}

.. warning::

   p 値は保存していません。同じ標本からパラメータを推定して、その標本で適合度を
   測っているので、教科書の帰無分布は使えません。統計量そのものは、面どうしの
   当てはまりを比べる目的には使えます。

表の 1 行から分布を再現する
===========================

この章の内容が正しいことは、次のコードで確かめられます。データベースから 1 行
取り出し、上の式で対数尤度を計算し直して、保存されている値と比べます。

.. testcode::

   import numpy as np
   from scipy import stats

   row = con.execute("""
       SELECT f.family, f.n, f.loglik, f.aic,
              f.weibull_shape, f.weibull_scale_ms, f.mu_ms, f.sigma_ms
       FROM fact_speed_fit f
       WHERE f.is_selected AND f.family = 'weibull_min_loc0'
       ORDER BY f.timebin_id, f.level_id, f.cell_id
       LIMIT 1
   """).fetchdf().iloc[0]

   # 保存された定数だけで密度を組み立てる
   k, lam = row.weibull_shape, row.weibull_scale_ms
   pdf = lambda x: (k / lam) * (x / lam) ** (k - 1) * np.exp(-((x / lam) ** k))

   x = np.linspace(0.0, 200.0, 200001)
   print("密度の積分が 1:", np.isclose(np.trapezoid(pdf(x), x), 1.0, atol=1e-6))
   print("scipy と一致:", np.allclose(pdf(x[1:]), stats.weibull_min.pdf(x[1:], k, 0.0, lam)))
   print("AIC = -2lnL + 4:", np.isclose(row.aic, -2 * row.loglik + 4))

.. testoutput::

   密度の積分が 1: True
   scipy と一致: True
   AIC = -2lnL + 4: True

風向についても同じことができます。

.. testcode::

   row = con.execute("""
       SELECT family, n, loglik, kappa, mu_rad, resultant_length
       FROM fact_dir_fit
       WHERE is_selected AND family = 'von_mises'
       ORDER BY timebin_id, level_id, cell_id
       LIMIT 1
   """).fetchdf().iloc[0]

   from scipy.special import i0e
   kappa, rbar, n = row.kappa, row.resultant_length, row.n
   loglik = n * (kappa * rbar - kappa - np.log(2 * np.pi) - np.log(i0e(kappa)))
   print("対数尤度が一致:", np.isclose(loglik, row.loglik, rtol=1e-10))

.. testoutput::

   対数尤度が一致: True

この 2 つが通るかぎり、この章の式と表の定数は食い違っていません。
