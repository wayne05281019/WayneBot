# Phone V3 自主 hillclimb 因子包（下一輪）

`phone_sync=blocked`。不准發明話筒浪號 5／9。不准改 `leave_zero`。材料限既有 OHLC／量／均線／蕭 feat／TWII `mkt_feat_*`。

排名：`balanced_score = win × min(1, days/50)`；閘門獨立日 **n≥20** 且贏 random；若要比均衡核，需抬 `B_bal__M0__X0` 的 win（約 +0.5pt）且 days 仍夠。

---

## 1. 鎖死買核（sealed）

| 項 | 值 |
|---|---|
| 教義 | 波浪各波段**起漲**（主 W3；紅箭×W3 區可擴） |
| 編碼 | `core_w3_or_ma60w3 & (Vnear\|score55)` |
| 別名 | balanced **BAL_Vnear2∨S55**（Vnear 窗≈3；champion_v3 同形） |
| 封印成績 | n100：**76.0%／日50／B=0.760**（`phone_balanced_enlarge_decision`） |
| 對照薄頂 | W3×V／VT ≈87%@22；W3×S55×大盤閘 ≈95%@20 — **薄，不當主核** |
| 出場鎖 | 見下節 |

Vnear＝`_near(hsiao_V, 3)`；S55＝引擎 `hsiao_score_eff≥55`（bank `score55`）。核本身帶 `_room_mask`（進場時收未貼死 20 高）。

---

## 2. 鎖死賣（sealed）

| 項 | 值 |
|---|---|
| 教義 | 相對高點＝賣股票（使用者 2026-11-07） |
| 實作 | `hi20_or_wave_top`（蕭 20 高 ∨ 實驗室 W1／W3／W5_TOP 事件） |
| 已證抬勝率 | `hi20_or_desync`／`hi20_only` 在 winrate_boost ≈75–76%@74–110 日 |
| 勿用 | 過早 giveback；純 Elliott 狀態機當大盤閘（TWII 幾乎無 W3） |

---

## 3. 已試過：失敗／過薄／無效

| 因子／組合 | 結果 | 下一輪態度 |
|---|---|---|
| `V∧S55` | ≈87.5% 但日 **16** | 未過 n≥20；可當軟 OR 的一肢，不當硬 AND |
| W3×V／VT（thin） | ≈87%@22–25 | 天花板候選；厚薄折衷優先 Vnear∨S55 |
| W3×S55×`mkt_*` | ≈95%@20 | 薄；累積日數再說 |
| soft OR 加厚 | ≈79%@34；未超 S55／V 單項高點 | soft 軌無新 champion |
| nextlayer 引擎事件（breakaway／squeeze／ext_hold…） | **0** 過閘 | 引擎信號過稀；先擱 |
| barek 建設／挡套牢 | 非主抬勝率軸 | 可當輔閘，不當主核 |
| TWII Elliott 狀態機 `mkt_not_crash` | 幾乎恒真 | 改用 `mkt_feat_ok／safe／thrust／bull` |
| 拉回錘子厚樣本 | ≈75%@2700 未抬核 | 定義過寬，不當主買 |
| champion_and 硬 AND | 最高仍貼 S55@32 | 未贏均衡 B@50 |

V3 已掛上、待本輪／下輪量測（尚未宣稱贏均衡）：`V3_higher_structure`／`pull_ma20`／`vol_step`／`shrink_attack`／`time_align`／`struct_vol`／`pull_week`／`pack2`／`thrust_local`。

V2 已掃 extras：`immortal`／`hammer`／`not_kd_death`／`macd_turn`／`compress`／`week`／`bk_*`／`clean_hot`／`pack2` — 未封印新 ge50 冠軍。

---

## 4. 未進 champion 閘、可算的新因子（既有欄）

來源：`compute_hsiao_features`／`_wave_hsiao_bank`／`mkt_feat_*`。**不含**籌碼缺欄時的假數；`turnover_*`／`chip_*` 僅在欄位真有值時才閘。

閘法（每條一樣）：

1. entry = **鎖死買核** ∧（可選 mkt_feat）∧ **本因子** ∧ ¬`mkt_rel_high_risk`
2. 出 = `hi20_or_wave_top`
3. 獨立日 n≥20；`beats_random`；比對 `B_bal__M0__X0` 的 `balanced_score`（或至少 win↑ 且 days≥40）
4. 過閘 → 合進 extras／EXTRA_GATES 並**再生**下一版；不過 → 記失敗，不准上話筒

### A. 價／影線／結構

| ID | 一行公式 | 預期方向 | 閘 |
|---|---|---|---|
| `XG_no_lightning` | `¬is_long_upper_shadow_vol` | 避雷針日少追 → 抬勝率、略減日數 | n≥20 且 B≥均衡核 |
| `XG_prior5_break` | `Close > prior_high_5 ∧ vol_attack_ratio≥1.3` | 突破近高＋量 → 勝率↑ | 同上；防與 `is_key_bull` 共線 |
| `XG_body_thrust` | `candle_body_ratio≥0.55 ∧ Close>Open` | 實體攻勢 → 略抬勝率 | 同上 |
| `XG_hh_hl2` | `(H>H₁>H₂) ∧ (L>L₁)` | 結構轉強（V3_higher 的輕版） | 同上 |

### B. 量階／凹洞／流動性

| ID | 一行公式 | 預期方向 | 閘 |
|---|---|---|---|
| `XG_trough_day_V` | `had_trough_vol_10d ∧ is_attack_vol` | 凹洞後真攻（≈troughV，單欄重述） | 若 days 掉破 20 記薄 |
| `XG_vol_step3` | `V>V₁>V₂ ∧ Close>Open` | 三日量階梯 → 抬 E | 對質 vs `V3_vol_step` |
| `XG_no_illiquid` | `¬block_new_entries` | 擋處置／量斷崖 → 少假勝 | 密度高時應近似 X0 |
| `XG_shrink_bounce` | `vol_shrink_ratio<0.7 ∧ ret_1d>0 ∧ ¬is_exhaustion_vol` | 縮量紅＝回檔承接 | 對質 vs `V3_shrink_attack` |

### C. 時間／角度／均線（蕭四維未用盡）

| ID | 一行公式 | 預期方向 | 閘 |
|---|---|---|---|
| `XG_deduct_safe` | `¬deduction_accelerating ∧ ma20_time_safety>0` | 扣抵未惡化＋時間安全 → 勝率↑ | 主推 |
| `XG_ma60_up` | `ma60_angle > 0` | 月線斜率向上 → 厚樣本仍可抬 | 主推 |
| `XG_t60` | `ma60_time_safety > 0` | 月線時間安全（bank 有 T60，champion 核未 AND） | 主推 |
| `XG_w_stack` | `Close>W_MA13 ∧ W_MA13>W_MA26 ∧ ¬w_kd_high_passivation` | 週線多頭堆疊嚴於 `weekly_trend_bullish` | 對質 vs `hsiao_week` |
| `XG_w_safety` | `w_ma13_safety > -0.2 ∧ weekly_trend_bullish` | 週安全＋多頭 | 密度應接近 week |

### D. 動能／KD／缺口（負向過濾）

| ID | 一行公式 | 預期方向 | 閘 |
|---|---|---|---|
| `XG_no_kd_hot` | `¬kd_high_passivation` | 避日線高檔鈍化追價 | 主推 |
| `XG_macd_expand` | `MACD_HIST>MACD_HIST₁ ∧ DIF>0` | 柱擴＋多頭 | 對質 vs `hsiao_macd_turn` |
| `XG_gap_hold` | `gap_breakaway_candidate` 近3日 ∧ `¬gap_filled_within_3d` | 突破缺口未回補 | 可能薄 |
| `XG_no_limit_lock` | `¬is_limit_up_locked` | 不追一字漲停 | 密度高 |

### E. 大盤 TWII feat（已有欄，狀態機無效後的正路）

| ID | 一行公式 | 預期方向 | 閘 |
|---|---|---|---|
| `M_feat_ok` 等 | 見 `_twii_wave_pack`：`week∧¬過熱∧…` | 與個股核 AND 應略抬勝率或保厚 | 已在 v3 `mkt_opts`；繼續對質 ge50 |
| `M_feat_thrust` | TWII 週多＋攻擊／角度∧¬weaken | 大盤推力窗 | 薄則只當候選 |

### F. 明確不做

- 話筒／查股浪號 **5／9** 標籤當買訊
- 改 `leave_zero`／黃金買點公式
- 缺官方欄時捏外資／融資成本
- 用 TWII Elliott `WAVE_5_*` 狀態當進場（本期無對比力）

---

## 5. 本輪 EXTRA_GATES（腳本掛載）

`scripts/decade_lab_phone_champion_v3.py` 附加（不改 CLI 預設、不破 import）：

- `XG_no_lightning`
- `XG_deduct_safe`
- `XG_ma60_up`
- `XG_no_kd_hot`

與既有 `V3_*`／`M_feat_*` 正交；跑完以 `by_balanced_score`／`best_ge50` 一句回報。

---

## 6. 再生義務（§13）

任一 EXTRA／V3 因子 **n≥20 且贏均衡核 balanced_score** → 鎖進下一版 champion 核旁路，並立刻再開 2–4 個未試 ID（上表 A–D 未掛者）。不過閘 → 本檔改「已試」列，不准 promote lookup。
