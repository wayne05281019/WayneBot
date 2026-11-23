# SYNC-DEBATE 觀測產出衝突仲裁（2026-11-23 台北）

軌：`SYNC-DEBATE`（Wave2 #7）。邊界：`MISSION_LOCK_20261123` B3／B6／B9；三鍋分標；只留官方柱撐得住的；不准混鍋；`model` inherit。  
掃描來源：`bk-*`／`dc-*`／`observe-mission-lock`／`observe-sync-wave2-lock`。

機器可讀：同目錄 `debate_arbitration_20261123.json`。

## 總覽

| 項 | 數 |
|---|---|
| 掃描衝突 | **14** |
| 已裁決（可落地） | **11** |
| 本 PR 已修（小） | **3** |
| 留給後續 PR（大） | **3** |
| 標成非衝突／已分鍋 | **3** |

警語（話筒固定）：`試標・推論／非他原文・非買訊・對質未過閘`

---

## 逐條裁決

### C1｜原子把個股價／代號標成「夜盤／大盤觀測位」（同鍋污染）

- **衝突處：** `atoms_latest.json`／`ATOMS_INDEX.md`  
  例：`three_layer.night_level_1900_1800_1835`（台積電）、`level.lv_1865_1910`（台積電）、`night_level_21000_3227_8039`（指數＋股票代號混列）、`night_level_6000_2000`（「修正6000點」振幅）。
- **依據：** 官方柱對質只認加權／台指指數級；股價≠大盤位。MISSION A5／B6；CHAIN 儀器分標。
- **裁決：** **剔除**。大盤／三層夜盤位只留 `≥10000` 指數級；個股價改「個股觀測位（非大盤）」附檔；振幅「Ｎ點」不算位。
- **處置：** 本 PR 已修 `biaoke_observe_atoms.py`（`_is_tw_index_level`／`_STOCK_BATTLE`／`_AMPLITUDE_*`）並重跑原子。

### C2｜BK-PHONE README 檔名與 CORPUS／CHAIN 產出不一致

- **衝突處：** `README.md` 寫還缺 `observe_atoms.json`／`observe_chain.json`；實際產出＝`atoms_latest.json`／`chain_playbook.json`；`observe_manual.py` 候選已含後者。
- **裁決：** **以程式候選＋CORPUS／CHAIN 產出檔名為準**；README 改成優先序表，不准再寫「還缺 observe_*」。
- **處置：** 本 PR 已修 README。

### C3｜浪則卡「夜盤先於日盤」缺 e-mini 第一層（層序缺口）

- **衝突處：** `WR-OPS-NIGHT-LEADS.ops_check_zh` 只寫 TX 夜盤→現貨；`MISSION_LOCK`／`chain_playbook` 定式＝e-mini → TX 夜盤 → 早盤 TX → 加權。
- **裁決：** **對齊 MISSION／CHAIN 層序**；補外圍 e-mini；重申不准倒灌。
- **處置：** 本 PR 已補 `wave_rules_cards.json`。

### C4｜48218.87 圖對質「偏」vs 他口述波段高

- **衝突處：** `chart_learn_latest.json`：`48218.87` hint=TWII → verdict **偏**（近窗距 ~1888／3.9%）；來源 `20260723_60m_chart.jpg`（60 分波段高，儀器更像 TX）。
- **裁決：** **暫不採「他標錯」**。先標儀器未定／期現口徑（chart_learn_rules #4）；重跑應以 TX 近窗對；未對上前不准寫進話筒定論。
- **處置：** **大・後續** `SYNC-LEVELS`／`BK-CHART` 重標儀器＋再 confront。

### C5｜44210 同主題「對」與「還沒走完」並存

- **衝突處：** `chart_learn` 同價兩窗：一窗命中＝對；延續窗未觸＝還沒走完。
- **裁決：** **非真衝突**。必須帶 `as_of`／窗戳；禁止合併成單一「對／錯」。
- **處置：** 手冊／VERIFY 考題保留雙列。

### C6｜假跌破「他定義上車點」vs 主買訊硬鎖

- **衝突處：** `WR-OPS-FAKE-BREAK` his_words 含「上車點」；B3 主買訊＝leave_zero＋已過閘紅箭。
- **裁決：** **已分鍋**。卡內 `hard_forbid_zh`＝他的上車點≠WayneBot 主買訊；只對質用。
- **處置：** 維持；不准升格買訊。

### C7｜1–4 不重疊（他說）vs 前端傾斜（DC／我估）

- **衝突處：** 同現象兩判：老師＝標準推進禁止／趨勢化解；MINE＝`leading_diagonal` 特徵。
- **裁決：** **已分鍋**（`vs-biaoke-boundary`／`cross_pot_compare`／`wave_pot_boundary`）。永遠分標；impulse 失敗不准自動改前端傾斜。
- **處置：** 維持 DC-BOUND 牆；observe_manual 只讀。

### C8｜Fib 0.382／0.618／0.75（他）vs 擴延 1.618 閘（我估）

- **衝突處：** 數字家族相近易混標。
- **裁決：** **已分鍋**。`WR-FIB-REBOUND`≠`detect_extension_1618`；不准互寫課綱。
- **處置：** 維持。

### C9｜CHAIN 點名帶例「41900～42700」未綁有效原文窗

- **衝突處：** `chain_playbook.md` C3 示例帶；若他已改口／過期，同價不同判。
- **裁決：** **示例必須掛「僅當他仍有效點名」**（文內已有）；落庫勾選不准寫死此帶為永恆支撐。
- **處置：** 小・文案已夠；`SYNC-LEVELS` 灌位時讀最新 oral／digest，過期帶降級。

### C10｜Michael「近 15K／60 不做」寫進 CHAIN 只觀察

- **衝突處：** 旁軌精神進他說手冊風險。
- **裁決：** **可留**，但必須維持「Michael 軌不混標成他說」（文內已標）。
- **處置：** 維持；VERIFY 不准把此句當 his_words 考題答案。

### C11｜phone_sync=blocked vs MISSION B1 段號可上話筒

- **衝突處：** 各軌 JSON `phone_sync=blocked`；B1 允許段號＋警語。
- **裁決：** **閘門非衝突**。blocked＝對質未過閘前不准同步；過閘後才依 B1 上警語試標。
- **處置：** 維持；`BK-VERIFY` n≥20 且贏現況才談解禁（§13）。

### C12｜DC checklist／MISSION_PARALLEL 跨 PR 文案漂移

- **衝突處：** `dc-bound-pot-sep` vs `dc-digest-practice`／`mine-ext-gate`：checklist 勾選狀態、MISSION 平行鎖句子不一致。
- **裁決：** **以 DC-BOUND 加強版為準**（B6／B9＋observe_manual 只讀＋`cross_pot_compare`）；digest／mine 合主時對齊 BOUND，不准回寫飆大手冊。
- **處置：** **大・後續** DC 合流 PR 統一 checklist。

### C13｜Wave1 `BK-DEBATE` vs Wave2 `SYNC-DEBATE` 代號

- **衝突處：** 編制表兩名。
- **裁決：** **非衝突**。Wave2 深度仲裁＝本軌；職能等同編制 #7。
- **處置：** 本檔即交付。

### C14｜倒灌風險（日盤改寫夜盤假設）

- **衝突處：** CHAIN 明文禁止；浪則舊卡未寫；原子無倒灌閘。
- **裁決：** **硬禁止倒灌**。較晚層只確認／否決較早層；否決＝改口條件，不准回寫夜盤方向當「本來如此」。
- **處置：** 本 PR 併入 C3 卡文；VERIFY `chain_trio` 考題保持層序。

---

## 本 PR 已修

1. `biaoke_observe_atoms.py`：指數級過濾＋個股／振幅分鍋。  
2. `README.md`：檔名優先序對齊。  
3. `wave_rules_cards.json`：`WR-OPS-NIGHT-LEADS` 層序對齊。

## 留給後續 PR

| ID | 建議軌 | 要做 |
|---|---|---|
| C4 | BK-CHART／SYNC-LEVELS | 48218 儀器重標（TX）＋近窗再 confront |
| C12 | DC-BOUND 合流 | checklist／MISSION_PARALLEL 統一 |
| （延伸） | BK-CORPUS | 舊版 atoms 若他庫仍在，Render 重跑 extract |

## 不准

- 改黃金買點／leave_zero；未過閘紅箭當買訊。  
- DC／我估句寫成他說；社團原文上話筒。  
- 假柱；盤中未收當收；倒灌。
