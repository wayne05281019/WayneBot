# 可沿用量化（多透鏡）

寫入：`2026-11-04T08:41:40+08:00`。對齊日 n=5419；基線後3日均=0.1221%。
可沿用 **17** 條（目標 ≥10）。不是買訊。

## 可沿用

- `after_tw_down2_with_wick`（L5_recovery）n=21 fwd3=1.134 edge3=1.012
- `fx_up_tw_down`（L1_diverge）n=99 fwd3=-0.647 edge3=-0.769
- `us_up_tw_down+brent_up_tw_down`（L2_combo）n=21 fwd3=-0.583 edge3=-0.706
- `tw_vol_spike+tw_lower_wick`（L2_combo）n=20 fwd3=-0.583 edge3=-0.705
- `dxy_up_tw_down`（L1_diverge）n=145 fwd3=-0.520 edge3=-0.642
- `us_risk_off_tw_green+tw_lower_wick`（L2_combo）n=36 fwd3=0.698 edge3=0.576
- `us_up_tw_down`（L1_diverge）n=101 fwd3=0.696 edge3=0.574
- `after_tw_down2_us_up`（L5_recovery）n=39 fwd3=0.680 edge3=0.558
- `after_tw_down2_vol_spike`（L5_recovery）n=25 fwd3=0.607 edge3=0.485
- `us_risk_off_tw_green`（L1_diverge）n=142 fwd3=0.568 edge3=0.446
- `us_down_tw_hold+us_risk_off_tw_green`（L2_combo）n=142 fwd3=0.568 edge3=0.446
- `tw_vol_spike`（L1_diverge）n=125 fwd3=0.534 edge3=0.412
- `brent_up_tw_down`（L1_diverge）n=135 fwd3=-0.278 edge3=-0.401
- `us_risk_off_tw_green+vix_spike_tw_hold`（L2_combo）n=84 fwd3=0.482 edge3=0.359
- `us_down_tw_hold`（L1_diverge）n=269 fwd3=0.477 edge3=0.355
- `tw_crash_3pct`（L3_extreme）n=107 fwd3=0.431 edge3=0.309
- `after_tw_down3_event`（L5_recovery）n=107 fwd3=0.431 edge3=0.309

## 各透鏡

- `L1_diverge` 美股×台股單旗背離／量影：keep=7/12
- `L2_combo` 強單旗兩兩 AND：keep=11/36
- `L3_extreme` 報酬／VIX 分位尾與急跌：keep=1/9
- `L4_leadlag` 台積／費半／輝達領先滯後：keep=0/6
- `L5_recovery` 急跌事件日後續：keep=4/6
- `L6_streak` 連兩日同向／反向：keep=0/5

多輪不同切法；可沿用閘 n≥20 且 |edge3|≥0.25；目標 ≥10 條。不是買訊。
