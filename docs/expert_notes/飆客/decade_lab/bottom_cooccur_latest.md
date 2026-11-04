# 加權落底前多因子共現（實驗室）

寫入：`2026-11-04T08:21:22+08:00`（Asia/Taipei）。
TWII 柱：20161031→20261103 n=2432。
trough 定義：±15日最低低點，且之後 10 日內反彈 ≥4.0%。
前窗：含 trough 當日共 5 日。

- trough 數：**37**
- 共現≥3 因子：5（0.13513513513513514）
- 共現≥4 因子：1（0.02702702702702703）
- 全體 breadth 日共現≥3 基線：0.6356435643564357（n=505）

## 單因子命中率（trough 前窗 vs 基線）

- `vol_spike`：trough=0.21621621621621623 base=0.09702970297029703 lift=2.228
- `twii_lower_wick`：trough=0.7027027027027027 base=0.6356435643564357 lift=1.105
- `tsm_vol_spike`：trough=0.8333333333333334 base=0.36633663366336633 lift=2.275
- `tsm_lower_wick`：trough=0.3333333333333333 base=0.6871287128712872 lift=0.485
- `limit_down_spike`：trough=0.0 base=0.04554455445544554 lift=0.0
- `down_dominate`：trough=1.0 base=0.900990099009901 lift=1.11

## 缺／不准硬編

- 成交金額≥1.3兆×≥2日：本庫無兆元口徑官方序列
- 融資餘額大減：market_margin_daily 過短
- 主動式 ETF 投信轉賣：無專序列
- 台積／跌停：僅 2023-12 起可對齊 breadth／2330


## breadth 對齊子樣（約 2023-12 起）

- trough 數：6
- 共現≥3：5（0.8333333333333334）
- 解讀：單因不夠；看共現與相對基線的 lift。台積量突增／加權量突增 lift≈2.2；下引線 alone 幾乎無 lift。

不是買訊。不准寫回黃金買點／海選／洞燭／話筒預測。

JSONL：`docs/expert_notes/飆客/decade_lab/bottom_cooccur_latest.jsonl`
