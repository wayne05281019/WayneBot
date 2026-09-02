# 台灣加權指數深度研究｜進度看板

> 最後更新：2026-09-02（台灣）  
> 這份檔案 = 紅框 Goal 的「進度條」；每完成一期我會自己更新並 push。

## 總進度

```
████████████████████████  100%
```

| 階段 | 狀態 | 說明 |
|------|------|------|
| 藍圖 | ✅ 完成 | `taiwan_index_depth.md` |
| v0 骨架 | ✅ 完成 | `taiwan_market.py` regime／桶權重／晨間一句 |
| **P0** 官方加權指數寫庫 | ✅ 完成 | MI_INDEX + Yahoo 差異告警（PR #115） |
| **P1** 漲跌家數廣度 | ✅ 完成 | `index_breadth_daily` + regime（PR #120） |
| **P2** falling_risk／高低檔 | ✅ 完成 | PR #122 risk_zone + 海選降權 |
| **P3** 台指期＋基差 | ✅ 完成 | `futures_daily` + 基差 + `futures_lead` + 大盤期現行 |
| **P4** Regime+ 狀態機 | ✅ 完成 | 6 態滯後確認 + 海選權重 v2 + 大盤頁／決策卡提示 |
| **P5** 回測＋大盤頁 | ✅ 完成 | Regime+ 回測自動化 + β 降權 + 大盤頁 |

## 已併入 main

| 項目 | PR | 狀態 |
|------|-----|------|
| P0–P3、選單隔離、大盤頁 | #115–#128 | ✅ |
| P4 Regime+ | #128 | ✅ |
| P5 收尾（β + Regime+ 回測） | — | ✅ 2026-09-02 |

## P5 交付摘要（2026-09-02）

| 項目 | 實作 |
|------|------|
| 個股 β | `compute_stock_betas`：60 日 cov/var 對加權 |
| β 降權 | `trend_down`／`trend_up_late` 時高 β 股排序降權（`apply_market_weights`） |
| Regime+ 回測 | `backtest_bucket_win_rate_by_regime_plus` → 大盤頁／晨間 brief |
| 海選串接 | `screening_engine` 傳 `db_path` 啟用 β 排序 |

## 驗證紀錄（2026-09-02）

- Release 庫 `20260902`：加權 46164.7、Regime+ 多頭延伸、廣度 50.8%
- 單元測試：β 計算、高 β 降權排序、Regime+ 回測空庫覆蓋
- 大盤頁：Regime／Regime+ 雙軌海選復盤區塊

## 研究外（飆客筆記，非本 Goal）

- 千張／四百張大戶籌碼條件 → 待資料源，見 `docs/expert_notes/飆客/`

---

**Goal 狀態：完成** — 藍圖 P0–P5 已全部落地；後續僅維護與樣本外檢視。
