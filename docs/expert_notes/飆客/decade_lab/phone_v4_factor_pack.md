# Phone V4 因子包（等 v3 封口後啟用）

`phone_sync=blocked`。`as_of` 2026-11-07T23:34:57.974825+08:00

鎖死買／賣同 V3。若 v3 未贏 `B_bal__M0__X0` 均衡分，下一輪插：

- `V4_prior5_break`：`Close>prior_high_5 & vol_attack_ratio>=1.3` — 突破近高＋量
- `V4_body_thrust`：`candle_body_ratio>=0.55 & Close>Open` — 實體攻勢
- `V4_t60_safe`：`ma60_time_safety>0 & ~deduction_accelerating` — 月線時間安全
- `V4_week_stack`：`weekly_trend_bullish & w_ma13_safety>0 & ~w_kd_high_passivation` — 週線同向非過熱
- `V4_gap_hold`：`gap_breakaway_candidate & ~gap_filled_within_3d` — 缺口未回補
- `V4_no_fake_break`：`~fake_breakout_exit` — 擋假突破當日

閘：n≥20、beats_random、抬 balanced_score；過閘再生 v5。
