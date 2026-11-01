# DC 規則啟用清單（self_pred／靜默對質 hooks）

> 本檔＝配線清單。規則本體見 `dc-wave-digest.md`。純函式見 repo 根目錄 `mine_wave_rules.py`（本批新增；主 agent 合 git）。

時區：`Asia/Taipei`。2026-11-01。

---

## A. 該呼叫的既有入口

| Hook | 檔／函式 | 怎麼接 |
|------|----------|--------|
| 我估價位包 | `biaoke_level_learn._build_self_pred_levels` | 在回傳 dict 加可選欄 `mine_wave`：`{"extension":..., "leading_diagonal":...}`；**不要**把結果塞進 `pred_levels`（那是他原文抽出）。 |
| 我估暗色圖 | `_render_twii_self_pred_dark` | 讀 `pack["self_pred"]["mine_wave"]`；過關才畫註「我估｜擴延1618」／「我估｜前端傾斜」。 |
| 標籤工廠 | `_self_pred_label(price, basis)` | basis 用短句：`擴延1618·③`、`前端傾斜1-4重疊`。 |
| DC 情境分軌 | `dc_scenario_silent_verify`（`dc_sf_*` 表） | 只當 **同學圖對質** 參考；可遷移句進 `dc_sf_rules.learn_transfer` 時標 `origin=dc_teach`，**不准**寫 `biaoke_posts`。 |
| 個股情境臉 | `scenario_forecast_chart.py` | 已有 DC 視覺／1.618 路徑比例；擴延閘用 `mine_wave_rules` 當可選結構檢查，失敗不改買訊、只降置信。 |
| 靜默對質鍵 | 新建建議 | `mine_ext1618_v1`、`mine_lead_diag_v1`（分軌；§13 再生下一版）。 |

---

## B. 欄位建議（self_pred 附加）

```json
{
  "mine_wave": {
    "extension": {
      "pass": true,
      "ratio": 1.72,
      "longest": "3",
      "second": "1",
      "lengths": {"1": 1200.0, "3": 2064.0, "5": 800.0},
      "variant": null,
      "basis": "L_max≥1.618×L_2nd"
    },
    "leading_diagonal": {
      "candidate": true,
      "w1_w4_overlap": true,
      "position_hint": "wave1_or_A",
      "structure_hint": "5-3-5-3-5",
      "implication": "continuation",
      "vs_ending": "ending=termination"
    }
  }
}
```

- `source` 一律 `"mine"`。  
- 與 `his_aux`／`pred_levels` 並列、不互寫。

---

## C. 不准混進飆大 thesis 回覆

| 禁止 | 原因 |
|------|------|
| 把「前端傾斜＝持續」寫成飆大結論句 | 語料／聲音隔離；他未必這麼講 |
| 用 DC 教學圖句頂替他原文 | 老師路徑只認他講過＋官方柱 |
| 標準 impulse 1–4 重疊失敗 ⇔ 自動標前端傾斜 | 還要位置＋內部結構；否則假陽性 |
| 擴延 161.8% 過關 → 發明個股 5／9 上話筒 | 證據閘未開（AGENTS §12） |
| 寫回黃金買點／海選／洞燭 | §4／§7 |
| 與 `biaoke_alert`「可能擴延」原文警報混鍵 | 那是他用語擷取；本閘是結構檢測 |

---

## D. 啟用步驟（主 agent）

1. [x] 落 digest＋sources（本目錄）。  
2. [x] 純函式 `mine_wave_rules.py`＋`tests/test_mine_wave_rules.py`（未 commit）。  
3. [ ] `_build_self_pred_levels` 可選呼叫（最小 diff；失敗吞掉、不擋出圖）。  
4. [ ] 靜默對質排程鍵掛上（n 累積；過程不進對話）。  
5. [ ] 話筒／飆大路徑 grep 確認無 `leading_diagonal`／`擴延1618` 洩漏進「他說」。  
6. [ ] Drive：本批教學圖若還有完整 DC 包，補進 `docs/expert_notes/dc_wave/sources/`（目前 Drive MCP 搜尋空）。

---

## E. 與先前後浪包的關係

| 既有 | 內容 | 本批增量 |
|------|------|----------|
| `docs/expert_notes/飆客/wave_fib_morph_curriculum.md` | 飆大課綱：八浪、1–4 不重疊、Fib 0.382／0.618／0.75 | 老師軌；不動 |
| `/opt/cursor/artifacts/wave_curriculum/*` | 先前波浪基本圖（含八浪示意） | 無 161.8 擴延閘、無前端傾斜專頁 |
| `_build_self_pred_levels` 的 `ext1618` | C 段 1.618 **目標價** | 保留；另加 **結構擴延檢測** |
| `dc_scenario_silent_verify` | DC 發文×情境圖對質 | 同學軌；教規本批進 mine 工具，不改他文 |
