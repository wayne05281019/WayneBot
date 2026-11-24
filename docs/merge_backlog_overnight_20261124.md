# 隔夜心血合主清單（2026-11-24 鎖死・不准遺漏）

暫關只為清檢查機席，**不是作廢**。所有下列結果必須依序重開並合進 `main` → Render → 話筒。  
CI 三刀已併入 [#1027](https://github.com/wayne05281019/WayneBot/pull/1027)，合完後**不要**再重開 #1024／#1025／#1026。

## Phase 0 — CI 解卡（已合）

| PR | 分支 | 狀態 |
|----|------|------|
| #1027 | `cursor/ci-unblock-bundle-d6f7` | **已合** `b8de3d6d`（2026-11-24 台北 11:18） |

## Phase 1 — 產品話筒（#1027 綠合後依序・一次一席）

| 序 | PR | 分支 | 內容 |
|----|-----|------|------|
| 1 | #1028（接 #1001；token 無法 reopen） | `cursor/drop-jiuha-desk-d6f7` | 撤啾哈觀盤（版面 v43）・進行中 |
| 2 | #1002 | `cursor/biaoke-narrative-trio-fresh-d6f7` | 文敘／三窗最新主文 |
| 3 | #1003 | `cursor/combo-screen-audit-d6f7` | 海選同源紅箭／剛離零臉 |
| 4 | #999 | `cursor/wave-forward-verify-1123-d6f7` | 20261123 forward 對質 |
| 5 | #1000 | `cursor/theme-chain-preview-d6f7` | 產業卡主題鏈加層 |

## Phase 2 — 觀測傳承邊界

| 序 | PR | 分支 |
|----|-----|------|
| 6 | #1004 | `cursor/observe-mission-lock-d6f7` |

## Phase 3 — BK 第一波（#1005 先於 #1015）

| 序 | PR | 分支 |
|----|-----|------|
| 7 | #1005 | `cursor/bk-verify-suite-d6f7` |
| 8 | #1006 | `cursor/bk-wave-rules-evidence-d6f7` |
| 9 | #1007 | `cursor/bk-chain-playbook-d6f7` |
| 10 | #1008 | `cursor/bk-corpus-observe-atoms-d6f7` |
| 11 | #1009 | `cursor/bk-chart-learn-d6f7` |
| 12 | #1010 | `cursor/bk-phone-wave-fast-d6f7` |

## Phase 4 — DC

| 序 | PR | 分支 |
|----|-----|------|
| 13 | #1011 | `cursor/dc-digest-practice-d6f7` |
| 14 | #1012 | `cursor/mine-ext-gate-d6f7` |
| 15 | #1013 | `cursor/dc-bound-pot-sep-d6f7` |

## Phase 5 — SYNC wave2（#1015 在 #1005 之後）

| 序 | PR | 分支 |
|----|-----|------|
| 16 | #1014 | `cursor/observe-sync-wave2-lock-d6f7` |
| 17 | #1015 | `cursor/sync-verify-phone-stamp-d6f7` |
| 18 | #1017 | `cursor/sync-retract-fire-d6f7` |
| 19 | #1018 | `cursor/sync-levels-drawable-d6f7` |
| 20 | #1019 | `cursor/sync-narrative-phone-d6f7` |
| 21 | #1020 | `cursor/sync-debate-observe-d6f7` |
| 22 | #1021 | `cursor/sync-fwd-miss-manual-d6f7` |
| 23 | #1022 | `cursor/sync-struct-vol-notes-d6f7` |
| 24 | #1023 | `cursor/sync-overlay-heal-d6f7` → 合後 Render heal |

## 執行規則

1. **不准遺漏**：上表 24 項（外加 #1027）全要進 `main` 或明確記「已併入他 PR」。
2. **一次一席**：重開下一個前，當下那支要綠合或記衝突解完。
3. **重開＝** `gh pr reopen N`（或 ManagePullRequest `status: open`）→ 等 CI → `gh pr merge --merge`。
4. **衝突**：合 `origin/main` 解完再推，不准丟著。
5. **手機核對**：每波產品合完 `curl` Render `/health` 的 `git_sha`。
6. **分支現況（2026-11-24）**：上表全 `OK` 仍在 origin，未刪。

## 不算重開

- #1024／#1025／#1026：內容已在 #1027，合 #1027 即算完成。
