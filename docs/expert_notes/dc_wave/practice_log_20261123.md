# DC→我估 練習日誌（2026-11-23 台北）

> **三鍋分標（硬）**  
> - 本檔全部結果＝**MINE／我估**（DC 教規消化後工具）。  
> - **不准**寫成飆大「他說」；也不准把老師 1709／社團包當 DC 來源。  
> - 不是買訊；盤中未收不當收。

來源盤點：`sources/` 仍僅兩張（擴延 1618、前端傾斜）。Drive 2026-11-23 再搜：`直流變頻`／`前端傾斜`／`擴延波`／`Elliott Wave`／folder `dc_wave` → **真 DC 教包 0**（見 digest §5／§6）。末端傾斜教材仍缺 → `ending_diagonal.status=curriculum_pending`。

可重跑：`pytest tests/test_dc_wave_practice_samples.py tests/test_mine_wave_rules.py -q`  
純函式：`mine_wave_rules.analyze_motive_from_pivot_prices`／`detect_extension_1618`。

---

## 樣例表（官方已收轉折價；標 MINE）

| id | 標的 | as_of（台北） | 轉折日序 | 擴延閘 | ①④重疊 | 前端傾斜 | 末端 | 備註 |
|----|------|---------------|----------|--------|--------|----------|------|------|
| TWII-A | TWII | 2026-08-25 | 20260603→…→20260825 | **pass** ratio≈1.94 最長③ | true | candidate（未 confirmed；缺位置＋5-3-5-3-5） | curriculum_pending | 官方 `index_daily` OHLC 轉折 |
| TWII-B | TWII | 2026-09-08 | 20260611→…→20260908 | fail；`rare_ending_motive_variant` | true | candidate | curriculum_pending | ③最長但＜1.618×① 且⑤＜③ |
| TWII-C | TWII | 2026-09-14 | 20260623→…→20260914 | **pass** ratio≈4.03 最長① | true | candidate | curriculum_pending | ①價距遠大於③⑤ |
| TWII-D | TWII | 2025-04-09 | 20241205→…→20250409 | **pass** ratio≈4.32 最長⑤ | true | candidate | curriculum_pending | ⑤暴衝段；結構真偽仍要過其他 motive |
| TX-A | TX 日盤 | 2026-08-25 | 20260623→…→20260825 | **pass** ratio≈1.86 最長③ | true | candidate | curriculum_pending | `futures_daily` TX regular 量最大合約 |
| TX-B | TX 日盤 | 2026-10-07 | 20260729→…→20261007 | fail；`rare_motive_variant_w1_longest` | true | candidate | curriculum_pending | ①最長未達 1.618×次長 |

凍結價（便於無 DB 重跑；來自上述官方柱轉折，非假數）：

```
TWII-A prices: 46552.16, 42006.39, 48218.87, 39384.85, 46402.60, 44210.31
TWII-B prices: 42006.39, 48218.87, 39384.85, 46402.60, 44210.31, 47578.24
TWII-C prices: 48218.87, 39384.85, 46402.60, 44210.31, 47578.24, 45398.43
TWII-D prices: 23387.17, 22510.25, 23943.95, 22458.22, 23732.58, 17306.97
TX-A   prices: 48711, 44264, 47695, 39442, 46470, 44146
TX-B   prices: 39442, 46470, 44146, 47593, 45302, 50117
```

## 對質解讀（我估，不是他說）

1. **擴延閘過關 ≠ 自動標推進浪號上話筒**（§12／digest §3）。只證明五浪群價距像有擴延；還要其他 motive 鐵律。  
2. **①④ 重疊多＝candidate 前端傾斜**，缺位置（①或 A）＋內部 5-3-5-3-5 → **不准 confirmed**（防假陽性；對齊 boundary）。  
3. **末端**：教材未齊 → 一律 `curriculum_pending`，不准發明 ending_diagonal 結論。  
4. 與飆大課綱：標準推進 1–4 不重疊仍是**老師軌**；本表重疊只服務 **MINE 傾斜檢測**。

## 下一版靜默鍵（§13 再生）

- `mine_ext1618_v1`：累積獨立交易日 n；空窗不算。  
- `mine_lead_diag_v1`：只計 confirmed（需位置＋結構），candidate 不進勝率。  
- `mine_end_diag_v1`：**末端圖進 sources 後**才開收集。
