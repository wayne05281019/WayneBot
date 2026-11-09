# 查股五張圖標記過閘候選（草案；仍 blocked）

`as_of` 台北 `2026-11-07T23:27:00+08:00`。本檔只合併已封口 decade-lab 決策；**不是買訊**；`phone_sync=blocked`；`promote_to_lookup_display=false`；`gate_status=collecting_v3_and_feat`。

## 現況冠軍（買）

均衡核（`phone_balanced_enlarge`／`phone_curriculum_merged`，n100、日≥50）：

- 鍵：`core_w3_or_ma60w3__BAL_Vnear2_or_S55__hi20_or_desync`
- 勝率 **76.0%**／獨立日 **50**／均衡分 **B=0.76**／期望 **E≈0.0193**／母體 **100** 檔
- 進場：W3 起漲 ∪ 確認紅箭×W3，再過近窗量 Vnear2 ∨ 引擎分 S55
- 對照：同跑 leave_zero 基線勝率≈65.1%（日 1965）；本鍵 beats_random／beats_leave_zero／lifts_core 皆真（封口 latest）

薄樣天花板（不當主推）：extreme `core_w3_start__V__hi20_or_desync` **86.96%@22**；大盤閘 `E_w3_start__mkt_ok_pull_or_impulse__F_hsiao_S55__hi20_or_desync` **95%@20**（B=0.38）。厚樣 MACD：`core_w3_or_ma60w3__hsiao_macd__hi20_or_desync` **78.05%@80**。

提早量（`phone_mark_earliness`）：`core_w3_start` 均衡最佳≈**75.9%／57日**、均約 17 根後碰上 20高且贏隨機；`ma60_lower_confirmed` 更早但勝率較低。顯示仍 blocked。

## 相對高點賣

使用者鎖死：相對高點就賣＝蕭 20 高。`relhigh_sell` **已封口**：`w3_or_ma60__SELL_hi20_or_desync` ≈**75%／94日** 贏隨機；`bal_Vnear_or_S55__SELL_hi20_or_wave_top` ≈**74%／50日**。出場主腿仍認 **`hi20_or_desync`**／`hi20_only`；浪頂併列僅實驗室、未單獨贏到可上查股。

## 大盤同步（誠實）

TWII 狀態機本期幾乎無 W3（`n_w3_start=0`）；feat-regime 再同步後錘子×`mkt_feat_safe` 最厚，W3 薄高檔需再累日。不當顯示主軸。

## 五張圖過閘條件

要開 `LAB_BUY_W3_START`／`REL_HIGH_SELL` 畫記，須同時：旗標顯式開、`promote_to_lookup_display=true`、`phone_sync≠blocked`；且獨立交易日 n≥20、贏隨機＋leave_zero／現況。**不准改 leave_zero／ma60_lower 公式**；現況藍▲／確認紅箭先保留。paint stub 已掛五張（旗標預設關）。

## 為何仍 blocked

promote 必須維持 false；薄樣不可當主推；TWII 浪閘無對比力；champion_v3（bal×relhigh×feat×barek／XG）尚在對質。候選 JSON：`phone_lookup_mark_promote_gate.json`（docs＋artifacts）。
