# 觀測手冊目錄（BK-PHONE 讀取）

話筒「波浪位階」會讀此目錄組「觀測手冊摘要／今日觀測」。

## 已有

- `MISSION_LOCK_20261123.md`：邊界鎖（警語／掛位階／不准項）
- `AGENT_ALLOCATION_BIAOKE.md`：代理編制

## 手冊檔（BK-PHONE 讀取優先序）

| 檔（優先） | 負責軌 | 內容 |
|---|---|---|
| `atoms_latest.json` | BK-CORPUS | 觀測原子（方法／位／改口／三層／SOX／鐵律）＋出處戳 |
| `chain_playbook.json` | BK-CHAIN | 三層鏈當日勾選欄（夜盤→TX→加權＋SOX） |

別名（同義）：`observe_atoms.json`／`atoms.json`；`observe_chain.json`／`chain_ops.json`（見 `observe_manual.py` 候選清單）。  
裁決：`debate_arbitration_20261123.md`（SYNC-DEBATE；檔名以 CORPUS／CHAIN 產出為準，不准再寫「還缺 observe_*」）。

介面鍵穩定：`load_observe_atoms`／`load_observe_chain`／`format_wave_observe_slot`；缺檔回 placeholder，不准假資料。
