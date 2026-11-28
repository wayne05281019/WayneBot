# 細微波型態庫（比對用・不上話筒）

`phone_sync=blocked`・非買訊・`wave_micro_pattern_catalog.json` 為準。

| id | 型態 | 結構碼 | 來源鍋 | 狀態 |
|---|---|---|---|---|
| MP-IMPULSE-5 | 推動五波 | 5 | public | skeleton |
| MP-DIAGONAL-LEADING | 引導楔形 | 5_wedge | public | skeleton |
| MP-DIAGONAL-ENDING | 終結楔形 | 5_wedge_end | public | skeleton |
| MP-ZZ-535 | 鋸齒 | 5-3-5 | public | skeleton |
| MP-FLAT-335 | 平坦 | 3-3-5 | public | skeleton |
| MP-FLAT-335-ATTACK | 335攻擊／奔走 | 3-3-5_running | user_memory | pending_source（南亞科） |
| MP-FLAT-EXPANDED | 擴大平坦 | 3-3-5_expanded | public | skeleton |
| MP-FAILED-C | 失敗 C | failed_c | public | skeleton |
| MP-TRIANGLE-33333 | 三角形 | 3-3-3-3-3 | public | skeleton |
| MP-COMBO-ABCX | 雙重複合 WXY | WXY | user_memory | pending_source |
| MP-COMBO-WXYXZ | 三重複合 | WXYXZ | public | skeleton |
| MP-EXT-W3 | ③擴延 | ext_3 | biaoke | partial |
| MP-EXT-W5 | ⑤擴延 | ext_5 | public | skeleton |
| MP-OVERLAP-EFFECTIVE | 有效1-4重疊 | ov_14_real | biaoke | partial |
| MP-FAKE-BREAK-DOWN | 假破底 | fake_break_low | biaoke | partial |
| MP-FAKE-BREAK-UP | 假突破 | fake_break_high | trial | pending_quant |

作業：日K釘頂 → 小時細拆 → 本表並列刪去 → 重疊真假量化。對到原文／官方柱才升 `verify_status`。
