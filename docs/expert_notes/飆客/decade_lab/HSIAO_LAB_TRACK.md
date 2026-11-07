# 蕭氏量價時間角度 × 八浪｜學習旁路定版 V7（2026-11-07）

**不是買訊。`phone_sync=blocked`。不准改黃金買點／海選／洞燭／leave_zero。不上話筒。**

使用者確認：整套只幫實驗室學習；**沒過閘不准上手機**。

## 硬邊界
- 與 path／level_bar／飆大語料分軌記、分軌對質，勝率不准混。
- 個股八浪狀態僅實驗室對質；不過閘不准當操作句、不准發明話筒 5／9。
- 無未來函數；盤中未收不當收；時區 `Asia/Taipei`。
- 全部測試在 Cursor 雲端 VM 本機跑；不碰正式 Telegram token／Render。

## 模組地圖（V1→V7）
| 模組 | 路徑 | 重點 |
|---|---|---|
| 還原／減資消毒 | `scripts/decade_lab_hsiao_data_preprocessor.py` | Ratio-Adj、Continuous_OHLC、corporate_action_sanitizer |
| 特徵 | `scripts/decade_lab_hsiao_quant_features.py` | 週共振、糾結／扣抵／過熱、漲跌停制度、缺口、KD、MACD、真凹洞量、籌碼可選 |
| 狀態機 | `scripts/decade_lab_hsiao_wave_engine.py` | 對數浪、延長／交替、失敗5、楔形、X浪鎖、錘子／仙人指路／避雷針、C浪放空 |
| 預測 | `scripts/decade_lab_hsiao_predictor.py` | 對數 Fib 目標 |
| 回測 | `scripts/decade_lab_hsiao_backtest.py` | Tick滑價、風險平價、棘輪、一字鎖死延遲、多方vs多空 |
| 族群 | `scripts/decade_lab_hsiao_sector_momentum.py` | sector_bull_ratio 前30% |
| Walk-Forward | `scripts/decade_lab_hsiao_walk_forward.py` | Expanding＋60日 embargo |
| 入口 | `scripts/decade_lab_hsiao_main_pipeline.py` | 一鍵跑完 |

## 系統架構檢核表
- [x] 不上話筒／不改買訊硬閘（每模組 `phone_sync=blocked`）
- [x] Continuous_OHLC＋減資裂口消毒
- [x] 2015-06-01 漲跌幅制度自適應
- [x] 週線 shift(1) 防未來函數
- [x] 對數波段＋鐵律3＋Fib 目標
- [x] 風險平價部位＋試單60/加碼40
- [x] Tick 滑價＋開盤破防＋棘輪
- [x] 一字漲跌停無法成交延遲
- [x] 純多方 vs 多空雙向對比
- [x] Walk-Forward expanding＋embargo
- [ ] n≥20 誠實 integrity 過閘後才談話筒（尚未；維持 blocked）

## 執行指令（雲端 VM）
```bash
# 單元測試
python -m pytest tests/test_decade_lab_hsiao_lab.py -q

# 一鍵管線（CSV 需含 Open/High/Low/Close/Volume，可選 Adj Close）
python -m scripts.decade_lab_hsiao_main_pipeline --csv /path/to/ohlcv.csv --symbol 2330

# 純多方 vs 多空對比（在 Python）
from scripts.decade_lab_hsiao_backtest import compare_long_only_vs_long_short
compare_long_only_vs_long_short(df, symbol="2330")
```

## 資料誠實（2026-11-07）
- 官方 `daily_quotes` 上市深史在本雲端常被證交所 WAF 擋；上櫃可用櫃買月表補到該檔實際最長。
- `scripts/decade_lab_hsiao_max_history_fill.py`：各檔取真實最長窗（官方優先；Yahoo 長史寫 `lab_daily` 並與官方短窗對齊；對齊失敗標 suspicious 不用）。
- 不足 20 年＝用該檔實際 years／n_bars 測，摘要寫明 source；**不准捏柱、不准冒充官方**。
- `load_stock_ohlcv(prefer_longest=True)` 自動選較長真史；attrs 帶 source／years。

## 過閘才談下一步
獨立交易日 n≥20 且誠實 integrity 過，並對得上飆大點過的位，才再生「要不要上大盤說法」下一版；**仍不是買訊**。查股顯示異動同樣要過閘。
