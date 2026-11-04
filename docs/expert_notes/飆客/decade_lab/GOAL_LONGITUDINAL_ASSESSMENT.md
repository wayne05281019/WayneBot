# 二十年／十年回測｜縱和評估（對齊使用者三塊）

寫入：`2026-11-04`（Asia/Taipei）。  
性質：旁路實驗室總評＋可執行下一步；**不是買訊**；`phone_sync=blocked` 直到 `WAVE_NEURONS_MATCH` 且 integrity／§13 過閘。  
不准改黃金買點／海選／洞燭；不准發明 5／9 套個股。

**一句話總評：** 材料與分軌骨架已立，但測法曾把「方向 100%」灌漂亮、波浪神經元未對齊、幅度 small 與封印 OOS 未過——離「可回放判斷工場＋高準度大盤位階＋方向／幅度／失效」還有一整段測法收斂＋位階對質，不是再堆指標就能到。

---

## 0. 對照來源（已吸收）

| 來源 | 狀態 |
|---|---|
| `decade_backtest_master_spec.md` | 總規格鎖定；序 0→F |
| `path_forecast_summary.json`／scored | 已合 #790；稽核見 #800 |
| `biaoke_wave_learn_latest`／`wave8_dual_summary`／`wave_fib_targets_latest` | 雙套＋Fib 已落 |
| `phone_feedback_map.md` | 話筒回饋地圖；多數 blocked |
| `CONTINUOUS_REDO_PLAN.md`／`path_amp_small_vnext` | #798 |
| 位階柱對質 `level_bar_fwd5` | #799；≈0.64 採納；hybrid 未贏 |
| 本鍵 `path_score_integrity_v1` | 修測法：封印 OOS＋next_gates |

稽核結論（鎖）：dir 100% 有 range 稀釋／OOS 薄／前瞻（前瞻碼已修）；small amp≈0.4；`WAVE_NEURONS_MATCH=false`。

---

## 1. 對齊「希望學到／產出」（使用者第一塊）

| 目標 | 狀態 | 證據／缺口 |
|---|---|---|
| 可回放判斷工場（柱→標籤→外圍／量價／鐵律→改口） | **半成** | 每日 A→H 規格＋path 因素包＋錯單閘有；改口年表／多標籤消去未成閉環工場 |
| 完全懂波浪、跟得上飆大；八循環＋細微波高準度 | **半成／測法分軌** | textbook 八循環 hit≈0.74 採實驗室鍋；biaoke_degree≈0.47 不採用；細微波≈0.42；神經元未對齊 |
| 產出＝方向＋幅度（目標／失效／缺因） | **半成／測法錯過** | 欄位齊（bias／amp／target／invalidate／missing）；但 dir 滿被稀釋灌水，不准當已學成 |
| 波底↔頂 Fib×八浪；五件／細微波／他說過能量化 | **半成** | wave_fib nearest 0.786 hard；五件分工具有 hit；交叉叠位日仍薄；延伸樣稀 |
| 兩套驗證比準度，留較準 | **已學成（結構）** | wave8 textbook vs biaoke；path sealed vs legacy OOS 雙列 |
| 旁路上話筒前過閘；三鍋分標 | **已學成（硬鎖）** | 各摘要 `phone_sync=blocked`；鍋標分軌；地圖已畫禁餵區 |
| 勝率優先可換測法 | **進行中** | 本 PR 把測法閘升成 `gate_integrity`；未過不准慶祝 dir |

---

## 2. 對齊「編碼過程問題」驗收清單（第二塊）

### 開跑前

| 問 | 答（現況一句） |
|---|---|
| 會變強？ | 會，但前提是測法先收斂；假 100% 不變強 |
| 學到什麼？ | 外圍／法人／Michael 切片／錯單閘／八循環雙套／位階→柱 |
| 對照什麼？ | 官方柱＋他點過的位／錯案年表；OOS 封印後只驗 |
| 五件細微波？ | 有量化；細微波未過可用閘；交叉日不夠 |
| Fib+DC？ | Fib 回撤有；DC 擴延閘有樣；末端教材仍缺 |
| 成書順序？ | 序 0→F 已跑一批；E／F 多軌 n≪20 |
| 影響手機？ | 現況不上；地圖已標可加測／禁餵 |
| 能否像飆大預測？ | 還不能；神經元未對齊＝不准裝像 |

### 跑中

| 問 | 答 |
|---|---|
| 學到什麼進因子？ | path factor_pack 已納 wave／外圍／法人／籌碼／Fib 近旁／Michael／MTF |
| 落底共現？ | bottom_cooccur 有；台積量 spike lift 可加測顯示級 |
| 美台脫鉤？ | linkage／reusable 有旗；path 有票 |
| 段段預測缺什麼？ | 因素不足 93% 日觀望；OTC／融資長史缺（factor_gap） |
| 規則錯要重抓 20 年？ | **測法錯優先修**（本鍵）；規則本身未宣告作廢重抓 |
| 雙套驗證？ | 有；textbook 勝；位階 hybrid 未贏現況 |

### 加深／收尾

| 問 | 答 |
|---|---|
| 因素不足？加什麼提高勝率？ | 先修稀釋／OOS／small amp；再 walk-forward 票權；缺史標缺不腦補 |
| Michael 擴大變化？ | 多變體已進；同日窗與三日窗分軌 |
| Fib 點位有驗？ | 有；0.382 帶內略抬；nearest 主用 0.786 |
| 圖軌更準？ | 教具另軌；實驗室不冒充他說 |
| 回饋話筒案件？ | 見 phone_feedback_map；過閘前只文案級候選 |
| 回測完成？ | **未完成**（integrity 未過＋神經元 false） |
| 波浪學到什麼？ | 推進結束→反向進 ABC 可沿用；HTF20 略贏已換；細微波／他說程度未到 |
| 怎樣再提高？ | 見下方優先序；禁止空吹方向 100% |

---

## 3. 對齊「要求／同意指標」（第三塊）

| 指標族 | 狀態 |
|---|---|
| 波浪／Fib | 半成（結構有、神經元未對） |
| 外圍（那指費半台積油匯電子日夜） | 已進 path／freeze；可用 |
| 幅度 crash-bounce·wick·分市況 | 已切片；**small 弱＝主洞** |
| 量能廣度 | MTF／chips 有；OTC 長史缺 |
| 融資·外資·投信 | 有旗；融資日列偏短已入隊 |
| 美台聯動 | 有 |
| Michael 變體 | 有（語音＝mine／MTF 鍋） |
| OTC·融資長史缺則標缺 | 有 factor_gap；標缺正確 |
| as-of 防前瞻·OOS·分軌 | 前瞻碼已修；**封印 OOS 本鍵落地**；分軌持續 |

---

## 4. 優先序路線圖（一次一件｜3～5 步）

| 步 | 做什麼 | 測什麼 | 過閘 | 對齊 |
|---|---|---|---|---|
| **1（本件）** | 修測法：前瞻已修＋封印 OOS＋`gate_integrity`／`path_score_integrity_v1` | call_rate、sealed_ok、small amp 旗、禁止 dir100 宣稱 | method_integrity_ok；空名單不算 | 一工場／二雙套驗證／三 as-of·OOS |
| **2** | 厚庫重跑 path（Render／本機厚庫）→ 再跑 integrity | 計分日變厚後 sealed OOS 是否成立 | holdout≥20 且 in_sample≥20；仍不准上話筒 | 一產出欄真可覆核 |
| **3** | `path_amp_small_vnext`：只殺 small 幅度 | small 子集 n≥20 hit≥現況 | n≥20 且贏現況 small；不傷 mid／large／dir | 一幅度；三 crash-bounce／分市況 |
| **4** | 位階柱現況 `level_bar_fwd5` 續收；再生下一鍵（非 hybrid 已敗） | 他點位→後窗柱 對／偏 | 勝率升且可解釋；神經元對齊另閘 | 一跟飆大；二能否像飆大 |
| **5** | `path_score_integrity_vnext_walkforward` 票權 | as_of 前旗才投票 | integrity 仍過＋OOS 只驗 | 二因素／勝率；三 OOS·分軌 |

並行提醒（不算插隊產品件）：#798／#799／#800 合進後以 main 摘要為準；合完只做上表下一步。

---

## 5. 能立刻開跑的下一件（已寫進碼）

- 腳本：`scripts/decade_lab_path_score_integrity.py`
- 摘要鍵：`docs/expert_notes/飆客/decade_lab/path_score_integrity_latest.json`（`path_score_integrity_v1`）
- §13 再生：`path_score_integrity_vnext_walkforward`（票權 walk-forward；queued）
- path 主腳本預設改封印 OOS；`next_gates` 機器可讀；`gate_integrity` 與 `gate_n20` 分開

跑法：

```bash
python3 scripts/decade_lab_path_score_integrity.py
# 厚庫後：
# python3 scripts/decade_lab_path_forecast.py
# python3 scripts/decade_lab_path_score_integrity.py
```

---

## 6. 硬邊界（複誦）

- 不是買訊；三鍋不准混。
- `phone_sync=blocked` 直到 `WAVE_NEURONS_MATCH` 且過閘。
- 不准改黃金買點／海選／洞燭；不准個股 5／9。
- 對話不准報默默％過程；只有明確優化狀態可講一句。
