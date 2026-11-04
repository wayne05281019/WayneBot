# 加權落底前多因子共現（實驗室）

寫入：`2026-11-04T08:38:55+08:00`（Asia/Taipei）。
TWII 柱：20061102→20261103 n=5423。
trough 定義：±15日最低低點，且之後 10 日內反彈 ≥4.0%。
前窗：含 trough 當日共 5 日。

- trough 數：**90**
- 共現≥3 因子：11（0.12222222222222222）
- 共現≥4 因子：2（0.022222222222222223）
- 全體 breadth 日共現≥3 基線：0.5128712871287129（n=505）

## 單因子命中率（trough 前窗 vs 基線）

- `vol_spike`：trough=0.15555555555555556 base=0.07722772277227723 lift=2.014
- `twii_lower_wick`：trough=0.6555555555555556 base=0.5742574257425742 lift=1.142
- `tsm_vol_spike`：trough=0.6666666666666666 base=0.3188118811881188 lift=2.091
- `tsm_lower_wick`：trough=0.4166666666666667 base=0.6118811881188119 lift=0.681
- `limit_down_spike`：trough=0.08333333333333333 base=0.041584158415841586 lift=2.004
- `down_dominate`：trough=1.0 base=0.8475247524752475 lift=1.18

## 缺／不准硬編

- 成交金額≥1.3兆×≥2日：本庫無兆元口徑官方序列
- 融資餘額大減：market_margin_daily 過短
- 主動式 ETF 投信轉賣：無專序列
- 台積／跌停：僅 2023-12 起可對齊 breadth／2330

不是買訊。不准寫回黃金買點／海選／洞燭／話筒預測。

JSONL：`docs/expert_notes/飆客/decade_lab/bottom_cooccur_latest.jsonl`
