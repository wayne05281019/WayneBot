# 查股五張圖標記過閘候選（草案；仍 blocked）

`as_of` 台北 `2026-11-07T23:23:01+08:00`。本檔只合併已封口 decade-lab 決策；**不是買訊**；`phone_sync=blocked`；`promote_to_lookup_display=false`。

## 現況冠軍（買）

均衡核（`phone_balanced_enlarge`／`phone_curriculum_merged`，n100、日≥50）：

- 鍵：`core_w3_or_ma60w3__BAL_Vnear2_or_S55__hi20_or_desync`
- 勝率 **76.0%**／獨立日 **50**／均衡分 **B=0.76**／期望 **E≈0.0193**／母體 **100** 檔
- 進場：W3 起漲 ∪ 確認紅箭×W3，再過近窗量 Vnear2 ∨ 引擎分 S55
- 對照：同跑 leave_zero 基線勝率≈65.1%（日 1965）；本鍵 beats_random／beats_leave_zero／lifts_core 皆真（封口 latest）

薄樣天花板（不當主推）：extreme `core_w3_start__V__hi20_or_desync` **86.96%@22**；大盤閘 `E_w3_start__mkt_ok_pull_or_impulse__F_hsiao_S55__hi20_or_desync` **95%@20**（B=0.38）。厚樣 MACD：`core_w3_or_ma60w3__hsiao_macd__hi20_or_desync` **78.05%@80**。

## 相對高點賣

使用者鎖死：相對高點就賣＝蕭 20 高。封口出場腿多為 **`hi20_or_desync`**（亦有 `hi20_only`）；winrate_boost 頂鍵 `w3_start__hi20_or_desync` 勝率 76.32%／日 74。浪頂 vs 20 高的 `relhigh_sell` 專軌**尚未封口**（跑失敗、無決策 JSON）→ `gate_status=awaiting_relhigh_seal`。

## 大盤同步（誠實）

TWII 狀態機本期幾乎無 W3（`n_w3_start=0`，推動佔比≈0.39%）；單靠 Elliott 當大盤閘不夠。有效輔助看週線＋非過熱／拉回推動窗；W3×S55×大盤可見極高勝率但日僅 20，先當候選累積，不當顯示主軸。

## 五張圖過閘條件

要開 `LAB_BUY_W3_START`／`REL_HIGH_SELL` 畫記，須同時：旗標顯式開、`promote_to_lookup_display=true`、`phone_sync≠blocked`；且獨立交易日 n≥20、贏隨機＋leave_zero／現況。**不准改 leave_zero／ma60_lower 公式**；現況藍▲／確認紅箭先保留（hsiao 長窗 h5≈五成，promote=NO）。

## 為何仍 blocked

相對高點專軌未封；薄樣不可當主推；TWII 浪閘無對比力；所有 sealed 皆 `promote_lookup=NO`；旗標與 sync 維持關。候選 JSON：`phone_lookup_mark_promote_gate.json`（docs＋artifacts）。
