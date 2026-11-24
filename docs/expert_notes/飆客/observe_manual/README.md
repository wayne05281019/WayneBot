# 觀測手冊目錄（BK-PHONE／SYNC-NARRATIVE 讀取）

話筒「波浪位階」會讀此目錄組「觀測手冊摘要／今日觀測」；台股大盤頁尾／三窗 caption 同口徑。

## 已有

- `MISSION_LOCK_20261123.md`：邊界鎖（警語／掛位階／不准項）
- `AGENT_ALLOCATION_BIAOKE.md`：代理編制
- `AGENT_ALLOCATION_SYNC_WAVE2.md`：第二波全開（含 SYNC-NARRATIVE）
- `chain_playbook.json`／`chain_playbook.md`：三層觀測操作手（定式／勾選／期現／SOX）

## 還缺（填滿摘要）

| 檔 | 負責軌 | 內容 |
|---|---|---|
| `atoms_latest.json` | BK-CORPUS | 觀測原子（方法／位／改口／三層／SOX／鐵律）＋出處戳 |
| 當日勾選欄 | BK-CHAIN | 三層鏈當日 hit／miss（夜盤→TX→加權＋SOX） |

可選：`observe_atoms.json`／`atoms.json`／`observe_chain.json`／`chain_ops.json`（見 `observe_manual.py` 候選清單）。

介面鍵穩定：`load_observe_atoms`／`load_observe_chain`／`format_wave_observe_slot`／`chain_one_liner`／`format_market_observe_footer`；缺檔回 playbook／lock placeholder，不准假資料。

固定警語：`試標・推論／非他原文・非買訊・對質未過閘`

- `debate_arbitration_20261123.md`／`.json`：SYNC-DEBATE 仲裁（C1/C2/C3）
