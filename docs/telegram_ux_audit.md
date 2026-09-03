# Telegram 話筒區 UX 實測紀錄

> **規則**：所有主選單功能須在 **Telegram 真實介面**（Reply Keyboard／話筒上方兩排）實測並截圖／錄影存檔。  
> **模擬角色**：偉權（重度）、哥哥（同機第二人）、新手、不懂股、亂按。  
> **自動化輔助**：`tests/test_bot_personas.py`、`tests/test_bot_ux_simulation.py`、`tests/test_telegram_menu_matrix.py`

---

## 五種使用者角色

| 角色 | 行為模式 | 重點觀察 |
|------|----------|----------|
| **偉權** | 決策卡→海選→持股→AI；有上次卡片 | 速度、不重複洗版、大盤/資金有即時回饋 |
| **哥哥** | 同聊天室不同 uid；按觀察、大盤 | pending／暫態訊息不互搶 |
| **新手** | 第一次 /start→選單→逐顆按 | 選單 v4 是否掛上、說明是否看得懂 |
| **不懂股** | 亂打字、空白、emoji | 友善「找不到」、不當成查股 spam |
| **亂按** | 快速連按、買入 pending 中按大盤 | pending 不被誤清、不 crash |

---

## 主選單全功能矩陣

| 按鈕 | 預期第一反應 | 實測 | 問題 |
|------|--------------|------|------|
| 決策卡 | 提示代號或上次卡 | | |
| 當沖 | 海選結果（當沖） | | |
| 持股 | 持股 HTML | | |
| 觀察 | 觀察清單 | | |
| 海選 | 海選進度／結果 | | |
| 隔日沖 | 隔日沖海選 | | |
| 資金 | **讀取當日資金移動…** → 輪動頁 | ✅ probe 9.9s | catch-up 期間僅一行狀態 |
| 說明 | 說明 hub（inline） | | |
| 選單 | 刷新兩排鍵盤 | | |
| 大盤 | **讀取大盤…** → 大盤頁 | ✅ probe 1.6s | |

---

## 實測 log（Telegram 真機）

### 2026-09-03 VM 登入成功 — **handler probe 全過**

| 時間 | 動作 | 結果 |
|------|------|------|
| 03:57 | 手機號碼登入 VM Chrome + 2FA | ✅ 登入成功（用戶確認「搞定了」） |
| 03:58 | `scripts/live_menu_probe.py` 五角色 × 主選單 | **FAIL: none**，大盤 ack 1.6s、資金 9.9s |
| 待補 | VM 真機話筒區錄影 | 進行中 |

**自動化報告**：`/opt/cursor/artifacts/live_menu_probe_report.json`

### 2026-09-03 第一次真機嘗試 — **失敗（未登入）**

| 時間 | 動作 | 結果 |
|------|------|------|
| 03:07 | 開 `web.telegram.org/k/#@WC_ai_trade_bot` | 停在 **Sign in to Telegram** 登入頁 |
| 03:07 | xdotool 送「大盤」 | 字打進 **電話號碼欄**，非 WayneBot 對話 |
| 03:08 | 等 30s／45s | 畫面仍為登入頁，**bot 無任何回應** |

**截圖證據**（artifacts）：
- `telegram_00_before_test.png` — 登入頁
- `telegram_market_after_30s.png` — 仍登入頁（非大盤內容）

**結論**：Cloud VM 的 Telegram Web **尚未登入你的帳號**，目前無法在話筒區對 @WC_ai_trade_bot 做真實按鈕測試。

**解除方式**：請在 VM 桌面 Chrome 用 **QR Code 登入 Telegram**（已請求 setup action），登入後回覆「已登入 Telegram」→ 我會立刻跑五角色全按鈕實測＋錄影。

### 待測（登入後執行）

- [ ] 偉權：大盤 → 資金 → 海選
- [ ] 哥哥：觀察 → 大盤（偉權 pending 中）
- [ ] 新手：/start → 選單 → 說明 → 大盤
- [ ] 不懂股：「股票」「asdf」→ 持股
- [ ] 亂按：記買入 pending → 連按大盤、資金

**截圖／錄影**：`/opt/cursor/artifacts/`（telegram_* 檔名）

---

## 已知問題（待修）

| ID | 嚴重度 | 現象 | 狀態 |
|----|--------|------|------|
| UX-1 | 高 | merge 後 Render 重啟 1～2 分鐘 polling 未開，按鈕全無反應 | ✅ PR #134 已合併 |
| UX-2 | 高 | 大盤/資金按了像沒反應（無「讀取中」） | ✅ PR #134 已合併 |
| UX-3 | 中 | 資金 catch-up 最長 180s，期間只有一行狀態 | 待優化進度 |

---

*最後更新：2026-09-03*
