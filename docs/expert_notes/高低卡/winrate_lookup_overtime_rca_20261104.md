# 勝率／查股逾時 RCA 短結（2026-11-04）

話筒假逾時／進度錯 → #791 已合 `main` → Render。本檔只留根因／修法／驗證，**不再改碼、不改買訊**。

## 根因

1. **查股 overtime 進度錯標**  
   `_chart_progress_text(..., overtime=True)` 逾時後「現在」未強制對齊「下一張還沒送」的順序（高低卡→介紹→結構→大量→走勢）。高低卡還在渲時會跳寫「介紹圖」＝假進度。

2. **勝率長掃後立刻「已超過預估」**  
   名單重掃（`overtime_keep`、可到數百秒）結束後切出圖讀秒時，`fill_sec`／`paint_fill` 只估本頁出圖、**沒加已耗秒**。泡泡一換就變「已超過預估」＝假逾時。

3. **TimeoutError 範圍過寬**  
   名單重建的 `wait_for` 若連出圖／送圖一起包，後面階段逾時會冒充「名單重建逾時」。

## 修法（#791，不重做）

| 點 | 改動 |
|----|------|
| 查股進度 | overtime 時未送高低卡 →「現在：高低溫度卡」；`_bump_progress` 帶 `overtime` |
| 勝率出圖 fill | `paint_fill = spent + max(40, 25*n)`（`spent`＝自開場含重掃） |
| Timeout 邊界 | `TimeoutError` 只包 `resolve_button_rows` |

合入：`25160df9`（PR #791）；修提交 `d1e12f51`。

## 驗證

- 單元：`tests/test_lookup_image.py::test_chart_progress_overtime_starts_at_card_not_glance`；`tests/test_button_loading_countdown.py`（`paint_fill = spent`）；既有 overtime／`overtime_keep` 斷言。
- Render：`/health` `git_sha` 已含 #791 merge（見當時核對 `54b48bfa` 及之後 tip）。
- 範圍：未改黃金買點／leave_zero／海選買訊公式。

## 結論

**碼已收尾，不必再改。** 之後話筒若再報逾時，先對 `/health` `git_sha` 是否仍在 #791 之後，再另開 RCA；不要重開同修。
