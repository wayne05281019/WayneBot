# SYNC-STRUCT-VOL｜結構圖／大量撐壓圖註規則（2026-11-23 台北）

警語（固定）：`試標・推論／非他原文・非買訊・對質未過閘`

三鍋：`他說`／`官方`／`試標推論`。不准改黃金買點／leave_zero。

## 開關

- 環境：`WAYNE_STRUCT_VOL_NOTES=1` 開；`0` 關（預設關）
- 決策卡：`card["struct_vol_notes"]=True/False` 覆寫環境
- 掛點：`biaoke_chart.render_biaoke_structure_png`、`vol_zone_chart._paint_volume_zone`、圖說旁註

## 註記規則（浪則卡）

| kind | 浪則卡 | 偵測（官方柱） | 標句 |
|---|---|---|---|
| `eff_pierce_up/down` | `WR-OPS-EFF-PIERCE` | 連 2 收過／破位 | 有效穿刺 |
| `pierce_touch` | `WR-OPS-EFF-PIERCE` | 影線碰到、未連 2 收 | 觸及未確認 |
| `fake_breakdown` | `WR-OPS-FAKE-BREAK` | 近窗戳破低後收回 | 假跌破 |
| `resist_to_support` | `WR-OPS-PRESS-TO-SUPPORT` | 連 2 收站上壓＋近窗曾在壓下 | 壓轉撐 |
| `vol_dry_decline` | `WR-VOL-NO-STABILIZE` | 綠跌＋量相對中位縮 | 無量下跌≠止穩 |
| `no_chip_exchange` | `WR-VOL-NO-STABILIZE` | 破低但量未放 | 沒爆量＝沒換籌碼 |

參考位：大量區／結構爆大量壓撐＝官方層試標；**有他點名位才疊他位水平線**（`his_named_levels`／`biaoke_named_levels`／`oral_levels`）。

## 不准

- 當買訊；改 leave_zero／紅箭公式
- DC／我估句寫成他說
- 沒他點名就發明他價線
- 盤中未收當官方收

## 程式

- `sync_struct_vol_notes.py`
- 樣張：`python3 scripts/render_sync_struct_vol_samples.py`
