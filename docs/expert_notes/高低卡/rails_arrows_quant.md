# 圖軌／箭頭（rails／arrows）量化盤點

寫入：`2026-11-04`（Asia/Taipei）。  
性質：編碼／量化入口盤點；**不是買訊**；未過閘不准改黃金買點／海選／話筒買臉。

---

## 1. 圖上有什麼

| 圖面 | 軌／箭／標 | 編碼入口 | 話筒出現處 |
|---|---|---|---|
| 高低卡／導航 | 藍▲紅框＝leave_zero；純藍▲＝60低；綠／粉高低觸箭 | `wayne_navigator` 導航訊號；`_nav_buy_arrow_alphas` | 查股①②③、勝率買點 |
| 導航低點首觸 | l60／l20 向上箭（紅箭代理材料） | `red_arrow_quant.nav_low_arrow_first_mask` | 導航圖；確認後海選桶 `ma60_lower` |
| 大量撐壓 | 平行雙軌＋軌標（上升軌／平行壓 或 下降壓／平行撐） | `biaoke_chart.infer_parallel_channel` → `vol_zone_chart.infer_vol_zone_parallel_channel`／`paint_vol_zone_parallel_channel` | 查股④、壓撐觀察、大盤大量區 |
| 結構圖 | 同套平行通道＋智能標 | `biaoke_chart._paint_parallel_channel`／note 排位 | 查股③ |
| 大盤教具 | 遠／近／超近縮圖K；點過的轉折線可畫；不准發明 5／9 | `biaoke_level_learn`／`market_biaoke_wave` | 波浪位階／飆大附圖 |
| 止穩◆／橘六角 | 觀察標（非買） | `foreign_sell_*`／stabilize marks | 大量區疊導航 |
| 智能標 | 壓／撐／軌／均／量標座位 | `smart_label_metrics`；`audit_smart_label_placement` | 查股④／大盤大量區 |

---

## 2. 已能量化（有回測／對質入口）

| 軌 | 模組 | 現況 | 上話筒？ |
|---|---|---|---|
| 紅箭代理 `ma60_lower` | `red_arrow_quant`；`scripts/red_arrow_backtest.py` | 已過閘＋使用者確認＝進場買訊；下一版 `ma60_lower_tight` 未贏 | 是（確認後） |
| 買點▲同帶淡化 | `buy_arrow_quant`；`scripts/buy_arrow_backtest.py` | `first_only_paint` 未贏全畫；只動呈現不准改公式 | 否（未過閘） |
| 下降通道破平行撐 D7 | `biaoke_dist_channel_second_verify` | face=false；下一版 `desc_break_v2_from_mid` | 否 |
| 出貨痕跡 D6／第二段 D9 | 同上 | face=false | 否 |
| 智能標底線 | `smart_label_metrics` | 壓K／互壓／孤字／裁切＝硬 fail | 合碼閘（排版） |
| 升軌失效改判 WB-28 | `infer_parallel_channel` reclass | 官方收破升軌→改畫下降；未改畫須明說 | 已合（圖／文） |
| **本輪**通道現況句準度 | `channel_rail_text_verify` | 幾何一致＋靠近下軌守軌 vs 無通道；`PRODUCT_ENTRY=False` | 不准當買訊；腳註誠實可合 |

---

## 3. 不能量化／停筆記（不准上話筒當新買訊）

| 項目 | 原因 |
|---|---|
| CaryBot 原文「紅色箭頭」人工標 | 無公開可複製公式；只能量化 OHLC 代理 |
| 紫箭頭／沿 5／10 抱 | 作者密技；AGENTS／高低卡 README 明確不准 |
| 飆大點名升軌「變成他」以外的發明軌 | 沒說過的價不准補；個股不准數 5／9 |
| DC／我估波浪教具當個股操作 | 三鍋不准混；教具≠買訊 |
| 通道「現況靠近平行撐」當進場 | 僅文字／觀察準度；未過閘且永遠不當買訊 |
| 平行軌寬度美感 | 可評測座位，不是預測勝率 |

---

## 4. 本輪安全修（非買訊）

- 大量區開了 `with_parallel_channel` 但推不出軌：腳註／淡灰藍短行改「本圖推不出合格平行軌」，不准假寫「雙線／淡灰藍虛線＝平行趨勢」。
- 失效升軌且未改畫下降：腳註固定「本圖未畫下降壓」，不准因 label 已含同句就退回「改畫下降壓」。
- 入口：`vol_zone_parallel_rail_foot_bits`／`channel_has_drawable_rails`。
