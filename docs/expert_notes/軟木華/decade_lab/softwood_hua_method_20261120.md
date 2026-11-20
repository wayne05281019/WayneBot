# Softwood Hua／軟木華 — 2026-11-20 method

## 身份與邊界

- **軟木華**＝**阮慕驊**（網友戲稱 Softwood Hua）。
- 當日來源鎖：`video_id=v1bqKlXNVIo`（九八新聞台《財經一路發》）。
- **不是**黃培碩影音軌、**不是** recovery funnel、**不是**飆大語料。
- `not_buy_signal=true`；`phone_sync=blocked`。
- **不准**改黃金買點／`leave_zero`；**不准**發明個股 5／9 浪號。

## 當日教了什麼（口播）

**尚無法逐字還原。** 雲端 IP 被 YouTube bot 擋（`LOGIN_REQUIRED`／`RequestBlocked`）；自動字幕與 whisper 皆無音訊來源；Firstory／Apple 同日 Podcast 尚未上架。

僅能確認的**非口播**事實：

- 節目標題：外資賣出「台韓」；提問「股市終究華爾街做主？」
- 主持人：阮慕驊；播出日 2026-11-20（Asia/Taipei）
- 片長約 1350 秒（TVHTML5_SIMPLY 回傳）

→ 因此 **hard rules／soft opinions／examples 今日皆空**。不准用標題或盤勢新聞冒充他說過的準則。

## 準則分類法（取得字幕後照此填）

| 桶 | 定義 | 例子形狀 |
|----|------|----------|
| hard_rules | 他明確給可重複條件（均線／乖離／量／籌碼數字） | 「站上十日線才算築底」類（須他當日親口） |
| soft_opinions | 方向／情緒／機率語，無硬門檻 | 「難熬」「華爾街做主」語境 |
| examples | 點名個股／產業當例子 | 僅記代號＋當日他怎麼說 |

每條必填：`he_said_zh`（逐字或近逐字）、`source_span`（時間碼或字幕段）、`not_buy_signal=true`。

## 連續擴充（見同目錄 JSON）

優先用既有庫欄：

- `index_daily` TWII：`open/high/low/close/volume/pct_change/ma20/ma60`（可算 ma10／ma200／乖離）
- `market_inst_bfi_daily`／`market_inst_lots_daily`：外資／投信／自營
- `market_margin_daily`／`daily_margin`：融資去槓桿（**不准**發明成本價）

對質閘（§3／§13）：本軌獨立；空名單不算；n≥20 且贏**本軌**現況才換；換了必須再生下一版候選。

## 重跑 ingest

```bash
# Podcast 上架後（或本機有可用 cookies）
python3 scripts/softwood_hua_ingest_day.py --asof 20261120 --video-id v1bqKlXNVIo
```

成功後覆寫 `softwood_hua_oral_absorb_20261120.json` 的 `transcript`／`criteria_today`，並同步 `*_latest.json`。
