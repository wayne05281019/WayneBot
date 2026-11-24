# 觀測手冊目錄（BK-PHONE 讀取）

話筒「波浪位階」會讀此目錄組「觀測手冊摘要／今日觀測」。

## 已有

- `MISSION_LOCK_20261123.md`：邊界鎖（警語／掛位階／不准項）
- `AGENT_ALLOCATION_BIAOKE.md`：代理編制

## 還缺（填滿摘要）

| 檔 | 負責軌 | 內容 |
|---|---|---|
| `observe_atoms.json` | BK-CORPUS | 觀測原子（方法／位／改口／三層／SOX／鐵律）＋出處戳 |
| `observe_chain.json` | BK-CHAIN | 三層鏈當日勾選欄（夜盤→TX→加權＋SOX） |

可選：`atoms.json`／`chain_ops.json` 等同義檔名（見 `observe_manual.py` 候選清單）。

介面鍵穩定：`load_observe_atoms`／`load_observe_chain`／`format_wave_observe_slot`；缺檔回 placeholder，不准假資料。
