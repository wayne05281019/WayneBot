# 黃培碩二月起大回測硬規格（使用者 2026-11-28 鎖）

`phone_sync=blocked`・非買訊・不准改黃金買點。  
設計來源：多代理討論（刪去／雙分支、量化總帳、上片前作業）＋使用者補「開市無片仍每日判斷」。

**目標長相（不准降級）：**  
讀完二月→現在之後，必須能**實際解盤**：釘頂→巢狀→型態刪去→雙分支機率→振幅／Fib／量價（必要時 60 分 K）→隔日可對質→失敗碼進化。  
禁止結案句：「沒學到怎麼判」「還沒辦法進步到某地步」「資料不足所以不判」。缺欄＝當天無效，不是能力免責。

---

## 0. 硬順序（偷看＝作廢）

1. 開市日 D：有片則吸片；無片則 `absent_open` 仍用官方柱解盤  
2. 填完整 `regime_D`＋刪去表＋量化最低欄  
3. **先**寫 D+1 高／低機率（`written_before_peek=true`）  
4. 打開 D+1 **官方** OHLC（＋規定的量欄）對質  
5. 若 D+1 有片，再讀他改口／延續  
6. 更新原則帳／失敗碼／分數板  

ASR／下載可平行預取，但 **forecast→confront 單線**；預取物密封，未寫完預估不准拆封 D+1。

---

## 1. 每日盤勢定義 `regime_D`（缺一＝當日無效）

| 欄位 | 必填 |
|---|---|
| `asof_D` | 台北開市日 YYYYMMDD |
| `film_status` | `present` \| `absent_open` \| `closed` |
| `anchor_peak` / `anchor_trough` | 釘頂／釘底＋日（他點或官方） |
| `degree_now` | 主級／次級／細微（只寫當層） |
| `phase_label` | 例：上升③中、下降 C、ABC-B… |
| `nest_state` | ①③⑤=5／②④=3；A=5\|3、B=3、C=must5 |
| `relay_bin` | `N_up` \| `range_chop` \| `unknown` |
| `iron_gate_14` | `pass`\|`fail`\|`diagonal_exempt`\|`unknown` |
| `iron_gate_w3` | `pass`\|`fail`\|`unknown` |
| `named_symbols[]` | 他點名才填；沒點＝`[]`，不准發明 |
| `us_link_hyp` | 美股聯動一句＋隔日台股假設（摘要；細節見 §1b） |
| `kill_levels[]` | ≥1 殺分支價 |
| `confirm_levels[]` | ≥1 活分支價 |

體制一行：`{degree} {phase}｜中繼={relay}｜14={…}｜W3={…}｜殺／活=…`

**開市無片：** 仍填上表；材料＝官方大盤 OHLC＋量；前窗已點名教具股可帶；`film_status=absent_open` **計入**對質 n（休市 `closed` 才跳過）。

### 1b. 同步比對鏈（使用者 2026-11-28 確認要納入）

每天解盤／隔日預估**不准只看加權**。必須同步填（有官方收才凍；盤中未收不當收）：

| 鏈 | 必比對 | 怎麼用 |
|---|---|---|
| **美股／美指** | 費半（SOX）、台積 ADR；他當日點名的美股（例美光） | 結構段位＋相對高低；對台股隔日假設寫進高／低分支；破底／假跌破要標 |
| **台指期** | 日盤指數＋**夜盤**指數（有官方／可核對來源才寫） | 與加權同窗對齊：夜盤「有驚無險／破底」是否在隔日日盤兌現 |
| **加權 TWII** | 開高低收＋量 | 主對質柱（既有） |

欄位（進 `huang_days/YYYYMMDD.json`）：

- `sync_us[]`：`{symbol, ohlc?, structure_note, vs_prior_low_high, link_to_tw_hyp}`
- `sync_tx`：`{day_session{...}, night_session{...}, vs_twii, note_zh}`
- 缺資料＝`status=missing`＋原因；**不准假數**。缺美股或夜盤不得假裝「已同步」。

隔日對質：除 TWII 外，若預估綁定了美股破底／夜盤方向，該鏈也要打 hit／partial／miss（可 `partial` 若只台股對、美股／夜盤未驗證）。

### 1c. 美股→台股龍頭→同族群（使用者 2026-11-28 確認要納入）

黃常例：**美光（MU）→ 南亞科（2408）→ 記憶體同族群**。這不是只記兩檔代號，而是**波浪對照＋族群擴散**學習鏈：

1. **美股教具**：他畫的美股結構（段位／3-3-5／買點錨／破底）先記  
2. **台灣對照龍頭**：對到他點名的台股同類型龍頭（例 MU↔南亞科），用**同一套巢狀／型態刪去**畫／判（官方柱；不准發明浪號進話筒）  
3. **同族群展開**：以該龍頭為錨，看同族群相對強弱／是否同步段位（他點名的才進名單；沒點不准自己發明一籃）  
4. **隔日預估**：高／低機率可寫「龍頭先／族群跟」或「美股破底→台股龍頭／族群」分支；對質時龍頭＋（若有點名）族群樣本一併打分  

欄位 `peer_chain[]`（進當日 day 檔）：

```
{ us_symbol, tw_leader, group_zh, peers_named[],
  structure_align: same|lag|diverge|unknown,
  wave_draw_refs[],  # 振幅／Fib／型態 id
  forecast_link_zh, confront_next? }
```

硬規則：

- 他當日若講了美股教具＋台股對照 → **必填** `peer_chain`（缺＝當日 regime 不完整）  
- 只准用他點名／畫過的對照；不准把「同族群」擴成海選買訊  
- 學習目標＝會畫、會判相對位階；`phone_sync=blocked`  
- 範例鎖：`MU → 2408 南亞科 → 記憶體族群（僅他點名者）`

---

## 2. 型態刪去（對 `wave_micro_pattern_catalog` 全表）

每天每條 MP-* 填：`status=pass|fail|unknown`＋`fail_reason_code`＋`evidence_refs`。  
`fail` 須鐵律／巢狀硬違；資料不足＝`unknown` 不得冒充 `pass`。  
當日 `pass` 數必須 ∈ **[1,3]**；0 或 >3＝表作廢重填。

---

## 3. 雙分支（預設不准單支）

對 `pass` 候選打分（鐵律、巢狀、等幅／交替、Fib、量價、他口語同向；`range_chop` 讀築底翻多重罰）。

- `high_prob`＝最高分（建議 ≥55 且分差 ≥8）  
- `low_prob`＝次高**互斥**路徑（至少一個 kill 與高分支相反）  
- 分差 <8 → 仍雙寫，`confidence=split`  
- 僅當分差 ≥25 **且** 鐵律無 unknown **且** 無口語對立 → 才准 `single_branch_ok`（預設 false）

每分支必有可對質 `ohlc_test`：方向／深度帶／破前高前低／跳空預期。

---

## 4. 每日最低量化（沒做＝不准寫預估）

1. **振幅比**：`r_w3_w1`、`r_w5_w1`、`r_C_A`；等幅容差 8%  
2. **Fib**：至少 2 列 `{from,to,ratio,level,role}` 或寫 `fib_skip_reason`  
3. **日量價**：`vol` / `vol_ma20` → confirm\|deny\|neutral  
4. **升 60 分 K 閘**（任一即升）：鐵律 unknown、他畫細微、中繼爭議、振幅灰區 8–12%、假突破／有效重疊分流  
5. **微浪教具**：他點名才記 `micro_example`；蓋牌 6442 靜默

---

## 5. 對質尺（只認官方柱）

- **hit**：方向＋深度帶＋（若有約束）破位／跳空皆合  
- **partial**：方向對但深度偏一階，或破位／跳空錯但主腳仍在劇本  
- **miss**：方向錯，或約束破位反向，或低分支才是主路徑（記 `F-BRANCH-SWAP`）

深度帶相對前波幅 R：shallow≤0.35R、mid、deep、to_level（±0.25%）。  
雙分支分開打分；日結果以高機率支為準。

---

## 6. 總帳檔（可撐 180+ 日）

| 檔 | 用途 |
|---|---|
| `huang_chrono_index.json` | 游標／resume |
| `huang_days/YYYYMMDD.json` | 一日一檔：regime＋刪去＋預估＋對質 |
| `huang_scoreboard.json` | 滾動命中／校正／失敗衰減／原則提升（可重算） |
| `huang_judgment_principles_quant.json` | HP-*／F-* 計數 |
| `huang_sample_register.json` | 教具股（含 silent 蓋牌） |
| 既有 `wave_micro_pattern_catalog.json` | MP-* |

分數板窗 W∈{20,40,all}：嚴格命中、含部分、高機率校正、失敗碼密度↓、原則 lift（n_fired≥5）。

---

## 7. 作業流（上片前／上片後）

**可平行：** Drive 掃檔登記、下載＋ASR 預取（密封）、官方柱補洞、60 分暖機、休市曆。  
**單線：** 游標、預估寫入、對質、原則升降、總帳合併。

每 **20** 個已對質開市日（含 `absent_open`）過閘：分數板、原則升／失敗修、ASR 噪音抽樣、欄位審計；仍 `phone_sync=blocked`；再生下一版靜默候選。

---

## 8. 反隨便結案閘（沒過＝只能寫 collecting）

宣稱「會判／有進步／pack 完成」前必須**同時**成立：

1. `n_valid_confronted` ≥20（空表／偷看日／休市不算；**開市無片有對質要算**）  
2. `dual_branch_rate` ≥0.90（除合法 `single_branch_ok`）  
3. `regime_complete_rate` = 1.0  
4. 每日刪去表覆蓋 catalog 全列  
5. 滾動命中相對標題基線不退步，且至少一條失敗碼密度下降  
6. ≥10 條可重用 HP-* ＋ ≥5 條穩定 F-* 對策  
7. ≥80% 有片日有「他改口 vs 我預估」對照句  
8. 抽樣盲測 ≥3 日：密封 absorb 後預估與已掛高／低支一致  

缺任一 → 狀態 `collecting`。**禁止**用「讀完仍不會」當結論——那是漏填或偷看，要修流程再跑。

---

## 9. 不准

- 偷看 D+1 片／柱再補預估  
- 單分支預設、高／低同義改寫  
- 空吸收（只有標題）  
- 發明浪號／未點名個股／黃觀察當黃金買點  
- 無片日放假跳過判斷  
- 跳片、倒序、vibes 蓋鐵律分數  
- 整包影音塞 Render 5GB  

---

## 10. DONE（二月包＝判斷力，不是檔案堆）

- Drive 二月→最新開市日：有片已登記或明示 `absent_open`  
- 自最早缺日 chrono到現在，無偷看污染  
- 對質閘與 §8 全過  
- 能用他的詞彙說清：等／勿追／拉回／續推／回馬槍／擴延——且有分數，不是日記  
- `/tmp` 清乾淨；話筒仍 blocked  
