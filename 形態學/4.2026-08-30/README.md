# 4.2026-08-30 已確認可用概念備份

這份資料夾是「形態學研討過程」裡**已經驗證能進正式 WayneBot** 的備份，不是把 Desktop 上每一個階段資料夾整包複製過來。

## 為什麼沒有整包同步 `/Users/waynewang/Desktop/形態學`

1. 那些資料夾是各階段程式概念研討存檔，**不一定能跑、也不該直接當正式碼**。
2. 這次雲端環境讀不到你電腦桌面路徑，不能從那邊搬檔。
3. 之後若某份草稿確認能用，再單獨放進下一個編號資料夾（例如 `5.日期`），不要整包覆蓋 `main`。

## 已確認可用（已在 GitHub 正式碼）

| 概念 | 正式檔 |
| --- | --- |
| 單一行情庫 `data/wayne_market.db` | `config.py` |
| 常駐 `/health` + Telegram；`--once` 盤後 | `main.py` |
| 現股 / KY / ETF 母體，排除權證牛熊特別股債券 | `universe.py` |
| 三大法人正確欄位、主力超比與 10 日累計 | `chips.py` |
| 真實日 K 決策卡、高低導航圖、粉紅預警滿 2 日 | `cary_navigator.py` |
| 四大選股 + 當沖 / 隔日沖 | `screening_engine.py` |
| 月營收 YoY/MoM、季報毛利率（官方 OpenAPI） | `fundamentals.py`（本階段新增） |

## 明確不做／不從形態學草稿搬上來

- Cary 溫度計裡沒公開公式的 PWave / VAM / ATRB / VPA
- 用亂數畫假 K 線當導航圖
- Colab 路徑 `/content/waynebot_data`、獨立 `wayne_market_master.db` 當正式庫
- 375MB sqlite 推進 GitHub

## 本階段正式功能

盤後流水線會抓：

- 上市月營收 `t187ap05_L`
- 上櫃月營收 `mopsfin_t187ap05_O`
- 上市綜合損益 `t187ap06_L_ci`（毛利／毛利率）
- 上櫃綜合損益 `mopsfin_t187ap06_O_ci`

Telegram：`/fund 2330`；打代號出的決策卡會附月營收與毛利率。
