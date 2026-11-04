# 20y 回測縱和評估（已吸收 Mine）

時區：Asia/Taipei。寫入：2026-11-04。  
**已吸收權威底：** [Mine 20y backtest user asks](https://cursor.com/agents/bc-7571cd21-16ec-58b7-99d4-97c3e09d94cc) ＝ `USER_ASKS_MINE.md`（PR #801）。  
對齊已吸收：`decade_backtest_master_spec.md`、`path_forecast_summary.json`、`biaoke_wave_learn_latest`／`wave8_dual`／wave_fib、`CONTINUOUS_REDO_PLAN`、PR #798–800。  
不是買訊。`phone_sync=blocked`。`WAVE_NEURONS_MATCH=false`。三鍋分標。不准寫回黃金買點／海選／洞燭。

**離目標一句：** 判斷工場骨架與多因子切片已半成，但測法灌水（dir「滿」）＋位階未對齊飆大 → **還不能說跟得上他，更談不上話筒。**

---

## A｜希望學到／產出（對 Mine §一）

| 目標 | 狀態 | 證據／缺口 |
|---|---|---|
| 完全懂波浪、跟得上飆大；高準度位階（八循環＋細微波） | **半成** | wave8 採 textbook hit≈0.74（n=43）＞ biaoke≈0.47（n=58）；細微波 hit≈0.42；level_bar 現況≈0.64（n=92）未贏 hybrid；`WAVE_NEURONS_MATCH=false` |
| 判斷工場（柱→標籤→外圍／鐵律→改口） | **半成** | path 有 bias／amp／target／invalidate／factors／missing；序 A–F 骨架落檔；改口年表薄（confront n=8） |
| 產出＝方向＋幅度（非只漲跌） | **測法錯→半成** | 有 amp_class／MAE；**禁止再報 dir 100% 當勝**：scored 24／wrote≈5419＝稀釋；small amp≈0.40 主洞 |
| Fib×八浪頂底對得上 | **半成** | wave_fib／seq_c 有回撤位；fib 正式旗 lit_days=0；末端教材未齊 |
| 五件／細微波／他說能量化 ≥10 可重用 | **半成偏成** | reusable_quant 17 條過閘；五件分工具 hit 不均（morph／keyk 弱）；交叉日仍少 |
| 兩套驗證留較準 | **半成** | wave8_dual textbook vs biaoke 已比；path 變體／Michael 切片有；walk-forward 封印未落地 |
| 旁路不過閘不上話筒；不是買訊；三鍋 | **已學成（工程）** | `phone_sync=blocked`；分鍋標註在規格／多數摘要 |
| 後期回饋話筒案件圖／濾網 | **未碰（硬擋）** | phone_feedback_map 只盤點；海選／黃金買點不准餵 |

---

## B｜問過的題（對 Mine §二）→ 答到哪

### 開跑前（u297–329）
| 題意 | 狀態 |
|---|---|
| 會變強？做完學到什麼？ | **半成**：學到可沿用切片與錯測法；尚未變「像他」 |
| 記得兩千多筆／只測加權＋對照？ | **半成**：TWII 長窗≈5400；外圍／台積／法人有進 pack；分鐘長史／OTC 標缺 |
| 五件／細微波／波浪＋Fib＋DC？ | **半成**：各有軌；DC 末端跳過；細微波未過電話筒閘 |
| 成書順序／漏了／影響手機？ | **已學成（約束）**：master_spec 序 0→F；旁路不動話筒／排程 |
| 訓練完能否像飆大預測？ | **未成**：神經元未對齊 |

### 跑中（u667–698）
| 題意 | 狀態 |
|---|---|
| 學到什麼／原則進大盤因子？ | **半成**：wave 主結構＋Michael／法人／籌碼進 path；飆大位階 hit 仍輸 textbook |
| 落底共現／美台脫鉤？ | **半成**：bottom_cooccur／linkage 有 lift；1.3 兆／融資長史標缺 |
| 符合波浪還缺什麼才能段段預測？ | **半成／主洞**：缺位階對齊＋small amp＋真 OOS |
| 找不出脈絡＝規則錯／重抓 20y？ | **測法錯優先**：#800 前瞻已修；稀釋／OOS 薄仍擋 integrity |
| 大回測＋飆大兩套差異？ | **半成**：dual 已量化差異；未換話筒說法 |

### 加深（u707–785）
| 題意 | 狀態 |
|---|---|
| 因素不足怎麼辦／還加什麼？ | **半成**：factor_gap_queue；≈93% unscored＝缺口不是再堆同質票 |
| Michael 擴大／變體？ | **半成**：多變體進 amp；有用勿輕棄；未單獨過封印 OOS |
| 勝率是否含 Fib 點位？ | **半成／偏弱**：目標可吃 fib 位；fib 正式旗未亮 |

### 收尾（u795–839）
| 題意 | 狀態 |
|---|---|
| 結構圖軌道箭頭會更準？ | **未碰／另軌**：圖務與 lab 分開；不准本 lab 改教具當勝率 |
| 20y 優化各案件？ | **未成**：feedback_map 標可加測；過閘前不上 |
| 還在做／學到什麼／怎再提高？ | **進行中**：CONTINUOUS_REDO A→B→C；**先修測法再堆指標** |
| 重讀希望／問過／加過指標？ | **本檔＋ USER_ASKS_MINE**＝權威答 |

---

## C｜指標（對 Mine §三）

| 類 | 狀態 | 註 |
|---|---|---|
| 八循環／位階／細微波／五件／W-X-Y／三鍋 | 半成 | dual＋learn＋level_bar；神經元未對 |
| Fib 0.382…／頂底×八浪 | 半成 | 有計算；正式旗弱 |
| DC／教材＋裸 K | 半成／薄 | seq_c／d；末端未齊；seq n≪20 |
| 外圍美股費半油匯／電子日夜 | 半成 | path factor_pack＋linkage |
| 落底共現／crash-bounce＋small amp／OOS | **測法錯＋主洞** | small≈0.4；OOS=5 假厚；本 PR 落地封印下一鍵 |
| ≥1.3 兆／台積巨量下引／跌停簇／台積軸 | 半成／缺 | tsm 有；兆元口徑標缺 |
| 融資／投信法人外資／主動 ETF | 半成／缺 | 法人旗有；融資長史薄；主動 ETF 無序 |
| 美台／日夜脫鉤 | 半成 | linkage 已切片 |
| Michael | 半成 | 已進；變體測中 |
| OTC／融資長史標缺 | **已學成（紀律）** | 標缺不腦補 |
| as-of／OOS／分軌／phone blocked | **測法錯→修中** | #800 as-of；本件 OOS 封印閘 |

---

## 與 #798–800 對齊（不重複空吹）

- **#798 CONTINUOUS_REDO**：A 測法／B small amp／C 位階三軌 — 本縱和採為執行序。  
- **#799 level_bar**：現況鍵採納；hybrid 未贏 — C 軌繼續，不上話筒。  
- **#800 path 稽核**：前瞻修＋`sample_audit.integrity_ok=false` — **dir 滿不准當過關**。  
- **本 PR**：Mine 縱和＋優先序；**立刻可跑**＝OOS 封印測法（修錯優先於再堆指標）＋§13 `path_oos_seal_vnext`。
