# 同題三鍋對照（他說／DC／我估）

時區：`Asia/Taipei`。2026-11-23。  
軌：`DC-BOUND`。對齊 `vs-biaoke-boundary.md`、MISSION_LOCK **B6／B9**。  
機器可讀：同目錄 `cross_pot_compare.json`。

**硬規則：** 三欄永遠分開；不准合併成一鍋；交叉對照不互寫。  
飆大 `observe_manual` 產出＝**只讀**，不准改寫成 DC。

| 題目 | 他說（飆大／老師） | DC（同學頂標） | 我估（mine） |
|------|-------------------|----------------|--------------|
| 1–4 重疊 | 標準推進禁止；重疊→趨勢化解／再一組跌 | 前端傾斜教材特徵（①或A＋5-3-5-3-5）；原文不准當他說 | `leading_diagonal_flags`；confirmed 要位置＋結構；話筒「我估｜前端傾斜」 |
| Fib 0.382／0.618／0.75 | 公開反彈壓價位表（可修訂） | 同學若講同比率＝教材；不准把飆大價表標成 DC | `fib_retracement_levels` 工具；≠他公開反彈壓表 |
| 1.618 | 「可能擴延／第五波擴延」戰術用語；9波敘事 | 教學圖：L_max≥1.618×L_2nd | `detect_extension_1618`；「我估｜擴延1618」；≠C段目標價 |
| 擴延閘 vs C目標價 | 他點的擴延／C-7～C-9＝原文敘事 | 同學圖教結構檢測；不准抄進他說 | 結構閘與 Fib 投影分欄；同屬我估不互代 |
| 浪號上話筒 | 大盤他點過才標；不准發明個股5／9 | 浪號只供對質；不准冒充他原文 | 同樣證據閘；必須「我估｜…」 |
| 買訊 | 不是買訊 | 不是買訊；`dc_sf_*` 分軌 | 不是買訊；不准寫回黃金買點／海選／洞燭 |
| 語料寫入 | `biaoke_posts`／`pred_levels`；observe_manual 只讀 | `dc_sf_*`／`dc_wave/sources`；不准吃 1709／手冊當同學文 | `self_pred`／`mine_wave`；可讀、不准回寫他的 |
| 前端 vs 末端傾斜 | 主講標準 1–4 不重疊 | Leading＝持續／Ending＝終結；不准混標 | continuation；末端教材未齊不准標 ending |

## 不准

1. DC 句 →「他說」氣泡  
2. 飆大 Fib 反彈壓 → 標成 DC／寫進 `dc_sf_*`  
3. impulse 1–4 失敗 → 自動前端傾斜  
4. mine 擴延閘 → 改老師課綱 Fib 表  
5. observe_manual ↔ DC digest／sources 互寫  
