# DC → 我的判斷工具：擴延波／前端傾斜（digest）

> **語料隔離（硬）**  
> - 來源臉＝同學 **D.C直流變頻** 教學圖（技術分析學習資源／波浪重點摘要）。  
> - 消化後規則＝**我的** motive／diagonal 檢測工具（`source=mine`）。  
> - **不准**把本檔句子寫進飆大話筒回覆當「他說」；也不准把飆大原文標成 DC。  
> - 飆大＝老師參考；DC＝同學頂標教材；輸出仍分「他說／飆預測」vs「我估」。

時區：`Asia/Taipei`。落檔日：2026-11-01；**推進日：2026-11-23**（練習日誌＋可測點再開）。  
來源圖（本批）：`sources/extension_1618_guide.jpg`、`sources/leading_diagonal_summary.jpg`  
（附件三張裡兩張擴延指南 md5 相同，已去重。）  
並行鎖：`MISSION_LOCK_PARALLEL_20261123.md`。練習：`practice_log_20261123.md`。

---

## 1. 擴延波檢測（真正推進波群）

### 定義與用途
- **擴延**＝一組五浪推進裡的「最長那一浪」（價距）。
- 是 motive（推進）的基本要件之一；用來分辨 **推進行為 vs 調整行為**。
- 分析分岔：過關才較敢當推進群；不過關→多半是調整或特殊變體。

### 核心規則（可量化）
在候選五浪群裡，量 **1／3／5** 的價格長度（絕對價距）：

```
L_max ≥ 1.618 × L_second_max
```

- `L_i = |終點價 − 起點價|`（本指南用價距，不是時間根數）。
- 通常候選擴延在 **3／4／5** 區間討論；實務上最長常落在 3（或 5），但規則是比長度，不是先指定浪號。

### 例外（長度未達 161.8%）
1. **① 最長但略短於 1.618×③**：稀有推進變體（仍要過其他 motive 鐵律）。
2. **③ 最長但 <1.618×①，且 ⑤＜③**：稀有「末端推進」變體（常對齊末端傾斜／終結型，不是標準擴延推進）。

### 注意
- **過 161.8% 仍不夠**：若違反其他推進規則（標準 impulse 下 1–4 重疊等）→ 仍當調整或特殊變體。
- 一律再核對完整 motive 規則集。

### 與現況程式的關係
- `_build_self_pred_levels` 已有「B高 − 1.618×(⑤−A)」的 **C 目標延伸**＝Fib 投影價位，**≠** 本條「五浪群內擴延檢測」。
- 本條是 **結構閘**：候選 1–5 是否像真推進；前者是 **目標價**。兩者都屬「我估」，但欄位／用途分開。
- 純函式：`mine_wave_rules.detect_extension_1618`／`analyze_motive_from_pivot_prices`／`mine_wave_from_impulse_nodes`。
- `infer_dc_wave_scenario`（2026-11-23）回傳附加 `mine_wave`（source=mine）；**失敗不改買訊**、不准寫進「他說」。

---

## 2. 前端傾斜 Leading Diagonal

| 項目 | 規則 |
|------|------|
| 位置 | 偶發於 **推進①** 或 **鋸齒 A** |
| 重疊 | **① 與 ④ 重疊**（④ 的價區進入① 價區）——標準 impulse 禁止的事，在這裡是特徵 |
| 內部 | **5-3-5-3-5**（①③⑤ 各為五小波；②④ 為三波） |
| 外型 | 收斂楔形（兩條趨勢線夾住） |
| 市場意涵 | **持續（continuation）** —— 走完後趨勢多半延續 |
| vs 末端傾斜 | Ending Diagonal＝**終結（termination）**；意涵相反，不准混標 |
| 速度特徵 | 第五次級波＝價變「緩步」；相對 ①② 短線速度「增加」、幅度「擴大」 |

### 末端傾斜 Ending Diagonal（教材缺口・2026-11-23）
- **意涵**：終結（termination）；位置末端 ⑤ 或 C；常伴 ①④ 重疊＋收斂楔形＋內部 5-3-5-3-5。
- **現況**：`sources/` **無**末端完整頁 → `ending_diagonal_flags(curriculum_ready=False)` 永不 `confirmed`，`status=curriculum_pending`。
- **不准**：用 rare_ending_motive_variant 或單純 1–4 重疊 **自動升格** ending_diagonal。
- 上傳末端頁後再開 `mine_end_diag_v1` 收集（§13）。

### 與飆大鐵律的對照（勿混語料）
- 飆大課綱／knowhow：標準推進 **1–4 不重疊**；重疊常當趨勢化解／末升失敗訊號。
- **我的工具**：若結構符合前端傾斜（位置＋重疊＋5-3-5-3-5），重疊＝允許特徵，標 `kind=leading_diagonal`，**不准**抄成「他說 1-4 重疊＝空」。
- 話筒「他說」路徑仍只用他點過的位與原文；本檢測只進 **我估／靜默對質**。

---

## 3. 怎麼用在 TWII／SOX（證據閘）

### 准做（靜默／我估）
1. 官方已收柱切出候選轉折點 → 算 `detect_extension_1618`／`check_leading_diagonal_overlap`。
2. 結果寫進 `self_pred` 或獨立 `mine_wave` 欄：`kind`、`ratio`、`pass`、`evidence`（起訖價／日）。
3. TWII 與 SOX／費半可 **分開** 跑同一純函式；勝率／對質分軌，不准混。
4. 圖上若畫：標籤必須「我估｜擴延1618」或「我估｜前端傾斜」——禁止「飆大」「DC原文」字樣。

### 不准做（證據閘未過）
- **不准發明 5／9 浪號上話筒**（AGENTS §12／§4；神經元未對到真的跟老師一樣前，個股／細微波段號不上公開回覆）。
- 盤中未收柱不當官方收。
- 不准把本規則寫回黃金買點／海選／洞燭名單。
- 不准用 DC 教學句當飆大 thesis 回覆。

### 建議對質鍵（再生下一版用；§13）
- **現況話筒鍵**
  - `mine_ext1618_v1`：`L_max≥1.618×L_2nd`
  - `mine_lead_diag_v1`：①④ 重疊→candidate；confirmed 要位置＋5-3-5-3-5
- **下一版候選（同件再生，已開收集）**
  - `mine_ext1618_v2`：v1 ＋ ③非最短 ＋ 禁把標準 impulse 1–4 重疊當擴延 pass
  - `mine_lead_diag_v2`：重疊深度≥8% ＋ 位置或結構至少一項才 candidate
- 獨立交易日 n≥20 **且** 贏該功能現況才換；空名單不算；**勝率只記我估鍋**。
- 落檔：`mine_practice_*.json`（對／偏／未完）＋`mine_practice_next_keys.json`。

---

## 4. 一頁決策樹（我估用）

```
候選五浪價距齊了？
  ├─ L_max/L_2nd ≥ 1.618 且其他 motive OK → 標「推進＋擴延浪=argmax」
  ├─ 未達 1.618 且 ①最長略短 → rare_motive_variant（低置信）
  ├─ ③最長但 <1.618×① 且 ⑤<③ → rare_ending_motive（對照末端傾斜）
  └─ 1–4 重疊？
        ├─ 在 ① 或 A 位＋內部像 5-3-5-3-5 → leading_diagonal（持續）
        ├─ 在末端 ⑤／C 位＋楔形 → ending_diagonal（終結）— 本批圖只對照，細節待下一包
        └─ 否則 → 不當標準 impulse；可能調整
```

---

## 5. Drive 廣搜補記（2026-11-01 二次）

查詢：`直流變頻`、`變頻`、`艾略特`、`波浪理論 擴延`、`前端傾斜 161.8`、`Elliott Wave Leading Diagonal`、title-only `艾略特波浪理論`／`前端傾斜`／`擴延波`／`D.C`、folder `dc_wave`、shared/starred `波浪`。

### 結論：**Drive 無真實 DC 艾略特教包**

| 查詢 | 原始 hits（約） | 有用？ |
|------|-----------------|--------|
| 直流變頻 | 1 | **否** — 建案摸彩文宣「米家直流變頻電風扇」 |
| 變頻 | 30+（分頁） | **否** — 大金空調／日立冰箱等報價 |
| 艾略特 | 4 | **否** — 客運段個案 xlsx 誤中 |
| 波浪理論 擴延 | 2 | **否（本目錄）** — 飆大 1709／社團72 語料（老師軌；不准拷進 `dc_wave/sources/`） |
| 前端傾斜／161.8／Elliott Leading Diagonal／title 教規詞 | 0 | — |
| D.C title | 多 | **否** — 檔名雜湊含 `DC` 字元 |
| shared／starred／dc_wave folder | 0 | — |

**有用 DC 教規來源仍僅：** 使用者本批附圖（已存 `sources/extension_1618_guide.jpg`、`leading_diagonal_summary.jpg`）。

### 請使用者上傳到 Drive 或直接附檔（建議檔名）
1. 末端傾斜（Ending Diagonal）完整頁（與前端對照）。  
2. 擴延例外／稀有變體補充、Motive 全規則表。  
3. DC 本人波浪／黃金切割連載圖或 PDF（標明作者 D.C直流變頻）。  
4. 若已有資料夾，給 **folder id 或分享連結**（全盤關鍵字搜不到專包）。

上傳後放進 `docs/expert_notes/dc_wave/sources/`，digest 再追加；消化結果仍標 **MINE**，不准混進飆大「他說」。

---

## 6. 2026-11-23 推進（停滯補齊）

### 盤點缺口 → 本批動作

| 缺口 | 狀態 |
|------|------|
| digest 停在 11-01／約 11-02 | **已推進**本節＋練習日誌 |
| sources 僅擴延＋前端兩圖 | 未變；Drive 再搜仍 **0** 真 DC 包 |
| 末端／motive 全表 | 末端仍缺圖；函式骨架已留、不准假 confirmed |
| 官方柱練習 | **已開**：TWII×4＋TX×2 凍結轉折樣例（`practice_log_20261123.md`） |
| `infer_dc_wave_scenario` 接擴延閘 | **已接** `mine_wave` 欄（MINE） |
| 靜默鍵 n≥20 | 再生鍵名已列；收集中、過程不進對話 |

### Drive 再搜（2026-11-23）
- `直流變頻`／`直流變頻 波浪`／`前端傾斜`／`擴延波`／`Elliott Wave`／folder `dc_wave`：**真教包 0**。
- title `D.C` 仍誤中雜湊檔名含 `DC` 的相片／建案 PDF → **不下載、不進 sources**。
- 飆大 1709／社團包屬老師軌 → **不准**拷進本目錄（boundary §硬禁止 5）。

### 可測點
- `tests/test_mine_wave_rules.py`：擴延／前端／末端 pending／`analyze_motive_from_pivot_prices`。
- `tests/test_dc_wave_practice_samples.py`：上表凍結官方轉折價對質（標 pot=DC→我估）。
- `tests/test_scenario_forecast.py`：`infer_dc_wave_scenario` 帶 `mine_wave.source==mine`。
