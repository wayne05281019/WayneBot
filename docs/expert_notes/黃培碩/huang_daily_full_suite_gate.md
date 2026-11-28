# 黃培碩每日影片查閱・流程序（S1→S27）

非買訊。  
**來源：** `huang_master_consolidate.md` §0.0b／§0.0c。  
**本檔＝每一天查閱必做的全部事情。**

## 名次（使用者 2026-11-28 鎖）

- **一件＝有序流程**，不是 27 條並列「最高」。  
- 唯一最高＝「當天跑完 S1→S27」；單步不是各自最高、不准挑做、不准平行略過。  
- 不准把 S1–S27 拆成多件同時開；不准標「可平行以後再補」。

## 硬規則

1. 每天依 **S1→S27** 順序做完，才准 `day_complete=true`。  
2. 漏一步＝該日作廢，不准進下一日。  
3. S4（停看登錄）可在讀片中途插入，不得略過。  
4. S22 寫預估前不准偷看隔日官方柱。  
5. D 節（ASR 腳本／飆大補丁／話筒弱提醒）**不准插入打斷**本序。  
6. 本機連做；一段落才推／CI（CI 不是每日序）。  
7. **大盤＋個股量化同步**（§0.0c）：每日必填 `market_power`＋`stock_quant`；少做從 `0102` 回頭補；不准以 blocked 少做。

## 流程序

| 序 | 必做 | 落檔 |
|---|---|---|
| S1 | 當日片有／absent_open＋開市日 | `meta.film_status` |
| S2 | ASR／影格可讀（無片仍判） | `asr_status` |
| S3 | 解盤主波＋細微波 | `regime_D`＋`wave_def_draw` |
| S4 | 新點立刻停登錄 | `teach_expand`／`undiscussed_gap` |
| S5 | 紙圖／口播點位凍 | `kill`／`confirm`／`paper_levels` |
| S6 | 同片改口鏈 | `retract_chain_zh` |
| S7 | 刪去表 | `elim_rows` |
| S8 | 量價（價方向＋量vs20日均；廣度不准代替量） | `quant.vol_price`（含數字） |
| S9 | TWII＋SOX＋TX日夜＋TE日夜（缺＝missing） | `sync_*` |
| S10 | 廣度官方凍 | `breadth_official` |
| S11 | 點名股官方 OHLC＋量 | `named_stocks_ohlcv` |
| S12 | 振幅／**黃金切割＋等幅度必算**＋幅度數字帶 | `quant.fib_used`／`equal_amp`＋forecast amp |
| S13 | 升 TF 原因 | `tf_escalate` |
| S14 | 族群鏈（有講才填） | `peer_chain` |
| S15 | 出場學（無則「無」） | `exit_learn_zh` |
| S16 | 浪頂／回檔／反彈帶 | `wave_progress` |
| S17 | 夜盤一句 | `night_morning_line` |
| S18 | 持股環境閘 | `holdings_env_gate` |
| S19 | 五件＋費半聯動（要有文字） | `five_vol_sox_note_zh` |
| S20 | 飆大交叉六桶（要有文字） | `biaoke_cross.buckets` |
| S21 | 隔夜美股已收／未收 | `us_session_for_forecast` |
| S22 | 雙分支隔日預估（未偷看） | `forecast_for_next` |
| S23 | 樣本登錄觸碰 | `sample_register_touch_zh` |
| S24 | 隔日官方柱對質 | `confront_official` |
| S25 | 失誤找因＋成長＋交叉覆核 | `miss_anatomy_zh`／`rolling_fix`／`cross_learn_zh` |
| S26 | audit＋`full_suite_evidence_ok`＋`market_power`＋`stock_quant` | `no_forget_audit` |
| S27 | 分數板／原則帳／個股總帳／vnext 更新 → 才開下一日 | scoreboard＋stock_ledger＋vnext |

## DONE 才准下一日

`full_suite_evidence_ok` ∧ confront ∧ miss_anatomy ∧ `market_power` ∧ `stock_quant` ∧ scoreboard 當日列 → 下一開市日。
