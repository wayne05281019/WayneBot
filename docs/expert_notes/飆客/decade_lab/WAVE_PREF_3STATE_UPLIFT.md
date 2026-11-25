# preferred 三態準度提升（靜默）

Asia/Taipei。不是買訊。`phone_sync=blocked`。

## 準度定義
下一窗 preferred 路徑在 **觸位／守位／失效改口** 是否對上官方已收柱。

## 現況鍵／下一版（§13）
| 軌 | 現況 | 下一版 | 閘 |
|---|---|---|---|
| SYNC-FWD miss 回寫 | `bk_fwd_v1_miss_map` | `bk_fwd_v3_gap_reclaim_hold` | n≥20 且贏現況才換 |
| preferred 三態 | `pref_3state_v1_verdict_map` | `pref_3state_v2_gap_reclaim_w4` | 同上 |

## 跑法
```bash
python3 -c "import wave_pref_path_confront as pc; pc.main()"
python3 scripts/observe_sync_fwd_writeback.py --write
```

## 硬禁
不准當買訊、發明未口述價、未收當收、混海選／黃金買點勝率。
