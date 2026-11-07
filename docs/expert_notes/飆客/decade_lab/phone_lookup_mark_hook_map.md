# 查股五張圖標記掛鉤圖（實驗室；未過閘不上話筒）

Code prep only：`LOOKUP_LAB_MARKS_ENABLED=False`；`phone_sync=blocked`。
意圖 glyph：`LAB_BUY_W3_START`（起漲買）、`REL_HIGH_SELL`（20高／浪頂賣）。
不准改 leave_zero；不准發明話筒浪號 5／9。

## 五張順序（`bot_servers.WayneTelegramBot._send_card_to_locked`）

| # | 圖 | 入口 function | LAB stub |
| --- | --- | --- | --- |
| 1 | 高低溫度卡 | `wayne_navigator.render_decision_card_png` | `_maybe_lab_lookup_marks(..., chart_kind="card")`（savefig 前） |
| 2 | 介紹圖 | `wayne_navigator.render_first_glance_png` | `_maybe_lab_lookup_marks(..., chart_kind="glance")`（savefig 前） |
| 3 | 結構圖 | `three_in_one_chart.render_lookup_structure_result` → `biaoke_chart.render_biaoke_structure_png` | `_maybe_lab_lookup_marks(..., chart_kind="struct")`（止穩／外資標後） |
| 4 | 大量撐壓 | `vol_zone_chart.render_lookup_vol_result` → `_paint_volume_zone` → `wayne_navigator.overlay_nav_marks_on_zone` | overlay 尾 `chart_kind="vol"`；`_paint_volume_zone` 再留一層 |
| 5 | 當天走勢 | `intraday_open_close_chart.render_lookup_intraday_result` | `_maybe_lab_lookup_marks(..., chart_kind="intraday")`（render_path 前 no-op） |

編排註記：`bot_servers.WayneTelegramBot._send_card_to_locked` 在 `render_plan_kinds` 旁呼叫 `lab_marks_allowed()`（預設 False）。

## 共用日 K 畫記路徑

| file:function | 角色 |
| --- | --- |
| `wayne_navigator._nav_trade_marks` | 現況買賣 index API（leave_zero∪確認 ma60；賣＝直接減碼） |
| `wayne_navigator._paint_nav_buy_arrows` | 現況藍▲紅框 |
| `wayne_navigator._paint_nav_on_axes` | 導航完整進出標；尾端 LAB stub `chart_kind="nav"` |
| `wayne_navigator.overlay_nav_marks_on_zone` | 大量區疊同一套進出標；尾端 LAB stub `chart_kind="vol"` |
| `wayne_navigator._maybe_lab_lookup_marks` | 薄包裝 → `scripts.decade_lab_lookup_mark_flags.maybe_paint_lab_lookup_marks` |
| `buy_exclude.paint_buy_entry_indices` | 過閘後可 union 第三路 wave-start（現況不改） |

## 旗標模組

`scripts/decade_lab_lookup_mark_flags.py`

- `LOOKUP_LAB_MARKS_ENABLED=False`（預設）
- `PHONE_SYNC="blocked"`
- `LAB_BUY_W3_START` / `REL_HIGH_SELL` 常量
- `lab_marks_allowed()`：須 ENABLED **且** gate JSON `promote_to_lookup_display=True` **且** phone_sync≠blocked
- `paint_lab_buy_indices` / `paint_lab_sell_indices` / `maybe_paint_lab_lookup_marks`：關＝空／False

Gate 候選：`phone_curriculum_merged_decision.json`、`hsiao_promote_lookup_decision.json`、`phone_lookup_mark_promote_gate.json`（artifacts 或 decade_lab docs）。

## 現況買賣畫記（先保留）

- **買**：藍▲紅框 ← `buy_exclude.paint_buy_entry_indices` → `_nav_trade_marks` → `_paint_nav_buy_arrows`
- **賣**：橙▼ ← `sell_action==直接減碼`；如何賣／20高文字在第 1／2 張

## 閘

`phone_sync=blocked`；`promote_to_lookup_display=false` 直到獨立交易日 n≥20 且贏隨機＋leave_zero／現況。未過閘不准開旗標、不准改預設畫面。
