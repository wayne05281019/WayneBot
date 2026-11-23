# CI 佇列／併發策略（2026-11-23）

狀態：**惡性循環成立**。本檔給父代理／合主節奏用；不自動關別人 PR、不自動合。

## 證據（當日 `gh run list --workflow "Unit Tests" --limit 100`）

| 指標 | 觀測 |
|------|------|
| completed | 76／76 全是 `cancelled`；**success=0 failure=0** |
| 活躍 | ~13 queued + 2 pending + 9 in_progress（與開著的 feature PR 同量級） |
| 同分支重跑 | 多支 3–8 次（例：`wave-forward-verify-1123` 8 次、7 次 cancelled；`drop-jiuha-desk` 7 次） |
| job 時長（歷史綠跑 #889） | `smoke-no-db` ≈ **60 分**；`full-suite` ≈ **127 分**；兩者**並行** |

結論：不是「偶發取消」，是空 commit／重推在 **job 還在 queued 或未真掛死** 時觸發 `cancel-in-progress`，把已佔到的 runner 進度丟掉，新跑再排到隊尾 → 無人綠。

佐證：開著的 PR 上已有 **≥56** 則 `ci: re-kick after ≥100m job stall`／`>100m in-progress stall` 類標題；歷史綠跑單 job 本來就要 60–127 分，**100 分仍屬正常窗**，當踢死條件＝把健康跑取消。

## 現況 workflow（`.github/workflows/test.yml`）

```yaml
concurrency:
  group: unit-tests-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

- **per-PR group**（不是 per-repo）：同 PR 新推才取消舊跑。這段設計本身正確，問題在「何時推」。
- **雙 job 並行**：`smoke-no-db` 與 `full-suite` 無 `needs`。註解已寫 smoke「與 full-suite 同量級」。
- 容量粗算：24 PR × 2 jobs ≈ **48 個 job 搶 GitHub free／org 併發**。佇列長度 ≈（待跑 job 數）／（可用 runner 槽）× 單 job 時長；空 commit 每踢一次就把進行中進度歸零並加長隊尾。

## 空 commit 重觸是否在惡化？

**是。** 只該踢「真掛死 step」（例如同一 step 卡死遠超預期、log 無輸出、runner lost），**不要**踢：

- `queued`／`pending`／剛拿到 runner 的 `in_progress`
- 只因「超過 N 分還沒 success」（在 60–180 分正常窗內）
- 整批 PR 週期性空 commit

父代理條件建議（可落地）：

1. `status == queued|pending` → **永不**空 commit。
2. `in_progress` → 讀最新 job step；僅當 step 已跑 > 預期上限（例如單一 pytest step > 150 分且 log 停滯）才 `gh run cancel` 後再推；否則等。
3. 同 PR 24h 內空 commit ≤ 1；第二次改人工／改真碼。
4. 優先 `gh run rerun --failed`（失敗後）而非空 commit（會取消整組 concurrency）。

## 擇優排序（可落地）

### P0 — 立刻停火（不等合 workflow）

1. **暫停空 commit 重觸**：父代理改條件如上；正在 queued 的跑讓它排到。
2. **Draft／暫關非關鍵 PR**（釋放 check 壓力；**本策略代理不代關**）：lab／舊日 forward／撞牆藍▲／非今日主線。Draft 後可不再推碼。
3. **合併窗口串行**：先合純 docs／極小 diff（例 #1014 僅 1 檔 docs），一次一支；合進 `main` 後等 Unit Tests 綠再下一支。不要 24 支同時等綠。

### P1 — workflow 明確增益（本分支 `cursor/ci-queue-strategy-cec6` 已改）

`full-suite` 加 `needs: smoke-no-db`：

（若並行代理另開 `ci-first-cut` 同類改動，合一支即可，勿雙開空 commit 互踢。）

- **好處**：每 PR 同時只佔 **1** runner 槽（原 2）；smoke 紅則 full-suite 直接 skip，少燒 127 分級 job。
- **代價**：綠 PR 牆鐘 ≈ 60+127 ≈ 187 分（原並行 ≈ 127）；可接受，因為現在牆鐘被取消循環打成無限。
- **不要**改成 per-repo concurrency（會變全球串行、合主更慢）。
- **保留** per-PR `cancel-in-progress: true`（多 agent 同 PR 疊跑仍要取消）。

### P2 — 合併／分流

| 手段 | 說明 | 風險 |
|------|------|------|
| path filters（`docs/**`、`*.md`） | docs-only 不跑雙重測 | 若 branch protection 要求 `smoke-no-db`／`full-suite`，skip 可能卡合；要先改 required checks 或加 always-green stub |
| 真・快速 smoke | 另開 `pytest -q -m "smoke"` 或子集 5–10 分擋明顯壞 | 要選 marker、防漏回歸；屬下一版 |
| full-suite 只跑 `production_db` | smoke 已跑過 not production_db，避免重跑 | 改變 full-suite 語意；需確認 required checks／本機腳本 |

### P3 — 不建議

- 對逾 100 分仍 `queued` 的 job 空 commit「叫醒」。
- 把 concurrency group 改成整 repo 一把鎖。
- 為清佇列批量 merge 紅／未測 PR。
- 關掉 `cancel-in-progress`（真碼連推會疊滿 runner）。
- 用正式 `TELEGRAM_BOT_TOKEN` 或換模型「加速 CI」（與最高指令衝突且無效）。

## 立刻可做的 3 步

1. **父代理立刻停空 commit**（queued／正常 in_progress 不踢）。
2. **合進本分支的 `needs: smoke`**（或等效），讓每 PR 只佔一槽。
3. **串行清窗**：Draft 非關鍵 → 先讓 2–3 支主線跑完拿到 **success** → 再擴。

## 不建議做的事

- 繼續對 in_progress>100 分一律空 commit。
- 亂合／關別人 PR「清場」。
- 指望 path filter 單獨救場卻不調 required checks。
- 以為 smoke 已是「幾十秒快篩」——註解與時長證明它仍是重測；`needs` 是為了**減併發**，不是變快。
