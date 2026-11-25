# 浪則卡（BK-WAVE）

- as_of：`2026-11-25T13:19:06+0800`（Asia/Taipei）
- 卡數：**25**
- 話筒警語（固定）：`試標・推論／非他原文・非買訊・對質未過閘`
- 非買訊；`phone_sync=blocked`；離開敘事不准進產品；DC句不准寫成他說。

| id | 類別 | 出處鍋 | 標題 |
|---|---|---|---|
| `WR-IRON-14-OVERLAP` | iron_law | his_words | 鐵律・1 與 4 不重疊 |
| `WR-IRON-W3-NOT-SHORTEST` | iron_law | his_words | 鐵律・③非最短 |
| `WR-LIVE-W5-GT-B` | iron_law | his_words | 活畫硬卡・⑤高＞B高 |
| `WR-MICRO-4STEPS` | method | his_words | 細微波四步 |
| `WR-OPS-NIGHT-LEADS` | ops | his_words | 夜盤先於日盤 |
| `WR-OPS-MULTI-LABEL` | ops | his_words | 多標籤並存・台積電量價決勝 |
| `WR-OPS-EFF-PIERCE` | ops | his_words | 有效穿刺閘 |
| `WR-OPS-FAKE-BREAK` | ops | his_words | 假跌破（他定義） |
| `WR-OPS-TWO-BAR` | key_k | his_words | 兩根收盤確認 |
| `WR-OPS-PRESS-TO-SUPPORT` | ops | his_words | 壓轉撐 |
| `WR-OPS-TRACK-CONNECT` | ops | his_words | 軌道連點 |
| `WR-FIB-REBOUND` | fib | his_words | 他公開 Fib 反彈壓 |
| `WR-EXT-7-9` | extension | his_words | 擴延 7／9（他用語） |
| `WR-EXT-CRISIS` | extension | his_words | 跌5／擴延危機與化解 |
| `WR-MORPH-CROSS` | five_piece | his_words | 形態／量價／關鍵K／碎形交叉 |
| `WR-VOL-NO-STABILIZE` | vol_price | his_words | 無量下跌≠止穩・沒爆量＝沒換籌碼 |
| `WR-SOX-14-LEAD` | peripheral | his_words | 費半先行／費半1-4 |
| `WR-RETRACT-COND` | retract | his_words | 改口／重訂位階條件 |
| `WR-SEGMENT-NEST` | segment | his_words | 級別同一性／嵌套 |
| `WR-LEVEL-ORAL-ONLY` | level | his_words | 只認他點過的位 |
| `WR-SEGMENT-TRIAL-WARN` | segment | trial_infer | 試標段號警語層 |
| `WR-FWD-LOOP` | verify | trial_infer | Forward 對質迴圈 |
| `WR-FWD-TOUCH-BOUNCE-RECLAIM` | verify | trial_infer | 目標觸及後收彈→升權假跌破收回 |
| `WR-FWD-PENDING-NOT-VETO` | verify | trial_infer | 未觸及≠路徑否決（pending 升權） |
| `WR-FWD-GAP-RECLAIM-HOLD` | verify | trial_infer | 跳空開盤已站回→標 gap_reclaim_hold、下一窗升權 W4 |

## 與現況 wave 碼落差

- **iron_laws**：現況＝wave8_* JSON 鎖＋teach phrase 標籤；無純函式強制①④／③非最短 → 卡＝WR-IRON-* → 下一步＝對質閘過後才考慮可執行 check；仍≠買訊
- **mine_vs_biaoke**：現況＝mine_wave_rules＝擴延1618／前端傾斜（DC→我估） → 卡＝WR-FIB-REBOUND / WR-EXT-* 分鍋註記 → 下一步＝永遠分標；不准DC句寫成他說
- **forward_verify**：現況＝segments_provisional 必標；未掛浪則卡 id／證據桶 → 卡＝WR-FWD-LOOP + observe_wave_rules.attach_* → 下一步＝BK-FWD miss→手冊鍵已掛；BK-VERIFY 吃證據桶；phone_sync 仍 blocked
- **five_piece_cross**：現況＝課綱有、教具語有；無同窗交叉對質函式 → 卡＝WR-MORPH-CROSS → 下一步＝BK-CHART 圖註解齊了再可執行化
- **phone**：現況＝phone_sync=blocked；段號上話筒需警語（MISSION B1） → 卡＝WR-SEGMENT-TRIAL-WARN → 下一步＝BK-PHONE 掛手冊摘要＋警語試標
- **sync_fwd_writeback**：現況＝eod miss_analysis 有 rule_patch，未自動回寫手冊鍵 → 卡＝WR-FWD-TOUCH-BOUNCE-RECLAIM / WR-FWD-PENDING-NOT-VETO → 下一步＝observe_sync_fwd 落 fwd_miss_writeback_*＋證據桶；§13 下一版鍵收集中
