# BK-VERIFY 自測覆核

寫入：`2026-11-24T00:59:15`（Asia/Taipei）。
現況鍵 `bk_verify_v1_trio_level_seg` → 下一版 `bk_verify_v2_chain_sox_strict`／phone `bk_verify_v3_phone_brief_stamp`（§13 再生）。

- 考題數：10；分軌：chain_trio, level_touch, phone_stamp, segment_bias
- 總覽 n_decided=9 hit_rate=1.0（僅目錄，不准混軌）
- miss 鉤子：0
- phone_sync=blocked；不是買訊；不准混海選／黃金買點

## 怎麼跑

```bash
python scripts/observe_verify_suite.py --write
pytest -q tests/test_observe_verify.py
```

## 每日覆核

- 開市日盤後跑 suite 落 `verify_latest.json`／`verify_YYYYMMDD.json`
- 有偏 → 讀 `miss_analysis` → 改下一版候選規則繼續收
- phone_stamp：三層／倒灌／期現／只認他位；未過閘不准當買訊
- 空名單不算；缺官方完整柱＝未完

