# Softwood Hua／軟木華 — 2026-11-20 method

## 身份與邊界

- **軟木華**＝**阮慕驊**（網友戲稱 Softwood Hua）。
- 當日來源鎖：`video_id=v1bqKlXNVIo`（九八新聞台《財經一路發》）；使用者上傳 MP4 本機 Whisper tiny。
- **不是**黃培碩影音軌、**不是** recovery funnel、**不是**飆大語料。
- `not_buy_signal=true`；`phone_sync=blocked`。
- **不准**改黃金買點／`leave_zero`；**不准**發明個股 5／9 浪號。

## 當日教了什麼（口播已落地）

主軸：外資／華爾街對台韓抽流動性；用**回吐倍數＋均線乖離＋跨市見頂時序**說明櫃買／韓／金比加權更慘、更早。

| 桶 | 今日重點（詳 absorb `criteria_today`） |
|----|----------------------------------------|
| hard_rules | H1 多方須站年線；H2 韓漲幅回吐 88%；H3 櫃買均線乖離矩陣；H4 三年線破／五年線近；H5 櫃買跌點≥1.07×漲點；H6 黃金領先頂鏈；H7 加權 ATH 與櫃買／費半脫鉤；H8 套取流動性＝賣無跌停權值／市值 ETF；H9 空段反彈不超過 15% |
| soft_opinions | 華爾街提款仍大；櫃買本土賣壓；投信贖回；韓／櫃買中期難回高；金回吐更慘；櫃買史上級重創 |
| examples | 當日法人數字；2330／0050／3037；KOSPI／OTC／GOLD／SOX／TWII 路徑數 |

畫面代理無音訊；數字與準則以 ASR 校正稿為準（見 absorb `asr_typo_map_zh`）。

## 連續擴充

見 `softwood_hua_continuous_extensions_20261120.json`：以今日口播閾值開 silent collect（OTC 年線乖離、韓 88%、金領先頂、TWII–OTC–SOX 脫鉤、流動性提款）。對質閘 n≥20、本軌獨立、過閘換碼並再生下一版；仍不准改 leave_zero。

## 重跑 ingest

```bash
python3 scripts/softwood_hua_ingest_day.py --asof 20261120 --video-id v1bqKlXNVIo
```

有更新字幕／Podcast 時覆寫 absorb／`*_latest`；已有 whisper 準則則合併、不准清空。
