# 20y 加權 path 一次做滿交卷（封印 OOS）

寫於台北 2026-11-05 01:06。不是買訊。`phone_sync=blocked`。

## 一句狀態
- n20=夠；integrity=不過；神經元=未對齊 → **不准換話筒／不准當買訊**

## 全窗
- wrote=5419 日；方向計分 n=45（hit_rate=0.6888888888888889）
- 幅度計分 n=31（hit_rate=0.7419354838709677）
- small amp：n=6 hit_rate=0.5（要 n≥20 才談換）

## 封印 OOS（holdout≥20 只驗不調）
- sealed_ok=True holdout_n=20
- in_sample dir=0.6 amp=0.4666666666666667
- holdout dir=0.8 amp=1.0

## integrity 擋門
- `call_rate_too_low_range_dilution`
- `soft_range_dominates_calls`
- `small_amp_gate_fail`
- `WAVE_NEURONS_MATCH_false`

## next_gates
- [ ] small_amp_n20: small amp 子集 n≥20 且 hit_rate≥0.55（不輸 mid／全窗才談換）
- [x] oos_sealed_n20: 封印 OOS holdout≥20 計分日（或末20%）只驗不調
- [ ] call_rate_not_diluted: 方向計分 call_rate 不可被 range／soft_range 稀釋灌水
- [ ] wave_neurons_match: WAVE_NEURONS_MATCH=true 才談話筒；現況 false

## 結論
一次做滿已交卷：**不過閘**。主因 call_rate 被 range／soft_range 稀釋、small n 不足、神經元未對齊。
OOS 封印窗形式有過（holdout=20），但 integrity 未過 → 不准報過關、不上話筒。

詳見 `full_seal_pass_latest.json`。
