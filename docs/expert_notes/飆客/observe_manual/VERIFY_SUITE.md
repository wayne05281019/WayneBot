# BK-VERIFY 自測套件（觀測傳承・§13）

落檔位置（選 observe_manual，不與 decade_lab 混檔名）：

- 考題：`docs/expert_notes/飆客/observe_manual/cases/*.json`
- 結果：`verify_latest.json`／`verify_YYYYMMDD.json`／`verify_latest.md`
- 錯案鉤子：`verify_miss_hooks_latest.json`（有偏才寫）

對齊 decade_lab 的 `wave_forward_infer_*`／`wave_eod_verify_*`／`biaoke_level_bar_hit_*` 當樣例來源；本軌勝率**不准**混進海選／黃金買點。

## 四軌

| track | 考什麼 | 判決 |
|---|---|---|
| `chain_trio` | 夜盤 SOX／regime → TX 日盤 → 加權現貨 | 對／偏／未完 |
| `level_touch` | 他點過的位 → 後窗官方柱碰到沒 | 對／偏／未完 |
| `segment_bias` | forward 試標段／preferred 路徑 vs 當日官方柱 | 對／偏／未完 |
| `phone_stamp` | 話筒 brief／observe slot／stamp：三層／倒灌／期現／只認他位 | 對／偏／未完 |

空名單（無 levels／無 paths／空 brief+slot+stamp）→ `空名單`，不進 `n_decided`。

`phone_stamp` 違規碼：`layer_order`／`layer_skip`／`backflow`／`futures_spot_mix`／`invented_level`／`missing_disclaimer`／`buy_signal_leak`／`phone_sync_leak`。  
`phone_sync=blocked` 未過閘不准當買訊。

## 怎麼跑

```bash
python scripts/observe_verify_suite.py --write
pytest -q tests/test_observe_verify.py
```

環境：`WAYNE_DB_PATH` 可指官方庫；缺完整 OHLC＝未完（不准假數）。

## §13 再生

- 現況鍵：`bk_verify_v1_trio_level_seg`
- 下一版候選：`bk_verify_v2_chain_sox_strict`（SOX≤-1.5 才准弱鏈對；剔除 touch 灌水）
- 並列下一版（SYNC-VERIFY）：`bk_verify_v3_phone_brief_stamp`（話筒 brief／slot／stamp 違規閘）
- 錯案必有 `miss_analysis`（expected／actual／rule_patch／next_variant）
- 替換閘：獨立交易日 n≥20 **且** 贏該功能現況；`phone_sync=blocked`；未過閘不准當買訊

## 每日覆核

開市日盤後跑 `--write` → 看 `verify_latest.json` 分軌 `tracks.*` → 有 `miss_analysis` 就改下一版規則繼續收。BK-CHAIN／BK-WAVE 手冊齊了再加考題；依賴見各 case 的 `deps`。

## 樣例依賴

| case | 依賴 |
|---|---|
| `case_level_touch_20261103` | 本機 `index_daily` TWII 完整 OHLC |
| `case_chain_trio_20261105` | `us_overnight`＋`futures_daily` TX regular＋TWII |
| `case_segment_bias_20261120` | case 內凍結官方柱（來源 wave_eod_verify_20261120）；不依賴本機 DB 末日 |
| `case_empty_skip` | 無（空名單閘） |
| `case_phone_stamp_ok` | 無（乾淨 brief／slot／stamp 夾具） |
| `case_phone_stamp_backflow` | 無（倒灌夾具） |
| `case_phone_stamp_layer_skip` | 無（三層跳層／順序夾具） |
| `case_phone_stamp_futures_spot` | 無（期現混標夾具） |
| `case_phone_stamp_invent_level` | 無（只認他位夾具） |
| `case_phone_stamp_buy_leak` | 無（買訊／sync／警語夾具） |
