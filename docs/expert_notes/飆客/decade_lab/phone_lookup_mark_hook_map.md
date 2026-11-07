# 查股五張圖標記掛鉤圖（實驗室；未過閘不上話筒）

來源：[Map lookup five charts marks](bc-5983bff9-6d9c-54fb-bc6a-f0bbb2711ede) 對碼結果。

## 五張順序（`bot_servers.WayneTelegramBot._send_card_to_locked`）
1. 高低溫度卡 — `wayne_navigator.render_decision_card_png`
2. 介紹圖 — `wayne_navigator.render_first_glance_png`
3. 結構圖 — `three_in_one_chart.render_lookup_structure_result` → `biaoke_chart.render_biaoke_structure_png`
4. 大量撐壓 — `vol_zone_chart.render_lookup_vol_result` → `wayne_navigator.overlay_nav_marks_on_zone`
5. 當天走勢 — `intraday_open_close_chart.render_lookup_intraday_result`（無 leave_zero／紅箭買箭）

## 現況買賣畫記
- **買**：藍▲紅框 ← `buy_exclude.paint_buy_entry_indices`（leave_zero ∪ 確認 ma60）→ `_nav_trade_marks` → `_paint_nav_buy_arrows`（主在第 4 張＋導航）
- **賣**：橙▼ ← `sell_action==直接減碼` 最後一根；如何賣／20高文字在第 1／2 張

## 過閘後掛新記號（不准改 leave_zero 公式）
| 優先 | 掛鉤 | 用途 |
| --- | --- | --- |
| 1 | `wayne_navigator._nav_trade_marks` | 統一買賣 index API |
| 2 | `buy_exclude.paint_buy_entry_indices` | 第三路 union：wave-start（promote 後） |
| 3 | `_paint_nav_buy_arrows`／橙▼ 區塊 | 若需與現況藍▲／橙▼區分視覺 |
| 4 | `render_biaoke_structure_png` 尾端 | 結構圖補齊買賣箭（現無 trade marks） |
| 5 | 第 1／2 張文字 | 相對高點賣協助文案 |

## 閘
`phone_sync=blocked`；`promote_to_lookup_display=false` 直到 n≥20 且贏隨機＋leave_zero。旗標模組見 `scripts/decade_lab_lookup_mark_flags.py`（預設關）。
