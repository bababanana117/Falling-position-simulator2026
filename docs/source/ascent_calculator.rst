バルーン計算 (physics/balloon.ts)
====================================

概要
----

``frontend/src/physics/balloon.ts`` は、打ち上げ前にバルーンサイズを決める
ための、ブラウザ内で完結する計算である。UIは
``frontend/src/components/params/CalcPanel.tsx``\ (「バルーン計算」パネル)
で、ペイロード質量・バルーン型番・ガス種別・目標値を入力すると、
Reactの ``useMemo`` により入力が変わるたびに再計算される。Tawhiri APIは
呼ばない。

この計算は、旧実装(``legacy/js/calc/calc.js``)の計算式を移植したもので
ある。旧実装は三次方程式をCardanoの解法で解いていたが、場合分けの一部に
未定義変数(``K``)を参照する実行時エラーがあった。現在の実装はこれを
汎用の二分法(``solveCubicLaunchRadius``)に置き換えて解消している。

入力パラメータ
----------------

.. list-table::
   :header-rows: 1

   * - パラメータ
     - 意味
     - 備考
   * - ペイロード質量 [g]
     - ``payloadMassG``
     - 20g〜20kgの範囲でUI入力
   * - バルーン型番
     - ``balloonModel``
     - Kaymont / Hwoyeeの型番。バースト直径と抗力係数を
       ``frontend/src/physics/balloonData.ts`` の内蔵テーブルから引く
   * - ガス種別
     - ``gas``
     - ヘリウム(0.1786 kg/m³) / 水素(0.0899 kg/m³) / メタン
       (0.6672 kg/m³)。``frontend/src/physics/constants.ts`` の
       ``GAS_DENSITY``
   * - 目標
     - ``target``
     - 「破裂高度」または「上昇速度」のどちらか一方を指定する(排他)
   * - 空気密度 [kg/m³]
     - ``AIR_DENSITY_SL``
     - 既定値1.205 (上書き可)
   * - 大気密度スケール高 [m]
     - ``ATMOSPHERE_SCALE_HEIGHT``
     - 既定値7238.3 (指数大気モデルのパラメータ、上書き可)
   * - 重力加速度 [m/s²]
     - ``GRAVITY``
     - 既定値9.80665

計算の流れ (``computeBalloon``)
------------------------------------

1. バースト時のバルーン体積を球体として算出する。

   .. math::

      V_{burst} = \frac{4}{3}\pi \left(\frac{d_{burst}}{2}\right)^3

2. **目標が破裂高度の場合**: 指数大気モデルで打ち上げ時体積を逆算する。

   .. math::

      V_{launch} = V_{burst} \cdot e^{-h_{target}/H}

   ここで :math:`H` は大気密度スケール高(``ATMOSPHERE_SCALE_HEIGHT``)
   である。
3. **目標が上昇速度の場合**: 浮力・抗力・重力のつり合いから導かれる、
   打ち上げ半径 :math:`r` についての三次方程式

   .. math::

      g(\rho_{air}-\rho_{gas})\frac{4}{3}\pi r^3
      - \frac{1}{2} v^2 C_d \rho_{air} \pi r^2 - (m_p+m_b) g = 0

   を ``solveCubicLaunchRadius(a, b, c, d)`` で解く。この関数は、符号が
   反転する区間を指数的に広げて探し、その区間を二分法で詰めることで
   正の実根(最小のもの)を1つ返す。気球の問題では係数が
   :math:`a>0, d<0` になるため、正の実根は必ず存在する
4. 打ち上げ体積・半径から各種出力値を算出する。

   .. math::

      \begin{aligned}
      A_{launch} &= \pi r^2 \\
      GrossLift &= V_{launch} (\rho_{air} - \rho_{gas}) \\
      NeckLift &= (GrossLift - m_{balloon}) \times 1000 \\
      FreeLift &= (GrossLift - (m_{payload}+m_{balloon})) \cdot g \\
      AscentRate &= \sqrt{\dfrac{FreeLift}{0.5\, C_d\, A_{launch}\, \rho_{air}}} \\
      BurstAltitude &= -H \ln\!\left(\dfrac{V_{launch}}{V_{burst}}\right) \\
      TimeToBurst &= \dfrac{BurstAltitude}{AscentRate \times 60}
      \end{aligned}

   浮力が不足する(``FreeLift <= 0``)、または目標高度に到達できない
   構成の場合は ``BalloonPhysicsError`` を投げ、CalcPanelはその
   エラーメッセージを表示する。

出力
----

- 上昇速度 [m/s]
- 破裂高度 [m]
- 破裂到達時間 [分]
- ネックリフト [g]
- 打ち上げ時ガス体積 [m³ / L]

CalcPanelの「この値を発射条件に反映」ボタンで、計算した上昇速度と破裂高度
を ``useParamsStore`` 経由でメインの発射条件フォーム
(:doc:`trajectory_prediction`)にそのまま反映できる。同じ計算
(``computeBalloon``)は、発射条件最適化(``frontend/src/optimizer/``)で
破裂高度のスイープ(ガス量スイープ)から上昇速度を逆算する際にも使われて
いる。
