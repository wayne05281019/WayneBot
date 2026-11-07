# 20y 加權 path 一次做滿交卷（封印 OOS）

寫於台北 2026-11-07（測法閘 A→B 重跑後更新）。不是買訊。`phone_sync=blocked`。

## 一句狀態
- n20=夠；封印 OOS=有；soft_range 灌水指紋=已清（命中未≥90%）；call_rate／small／神經元仍擋 → **不准換話筒／不准當買訊**

## 全窗（本輪重跑）
- wrote≈5419 日；閘前有方向 attempted≈948；soft_kill≈459
- 方向計分 n=47（hit_rate≈0.66）
- 幅度計分見 summary；small amp：n=6 hit_rate=0.5（要 n≥20 才談換）

## 封印 OOS（holdout≥20 只驗不調）
- sealed_ok=True holdout_n=20

## integrity 擋門（方法）
- `call_rate_too_low_range_dilution`（對 attempted 仍偏稀）
- `small_amp_gate_fail`
- `WAVE_NEURONS_MATCH_false`（非方法、硬鎖）

已清：`soft_range_dominates_calls`、`oos_holdout_too_thin`

## 結論
誠實全窗已重跑：**不過閘**。下一件＝幅度 small 專殺＋提高 attempted→計分留存（排程 C）。仍不上話筒。
