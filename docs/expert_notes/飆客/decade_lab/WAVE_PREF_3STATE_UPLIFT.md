# preferred 三態準度提升（靜默）

Asia/Taipei。不是買訊。`phone_sync=blocked`。

## 準度定義
下一窗 preferred 路徑在 **觸位／守位／失效改口** 是否對上官方已收柱。

## 現況鍵／下一版（§13）
| 軌 | 現況 | 下一版 | 閘 |
|---|---|---|---|
| SYNC-FWD miss 回寫 | `bk_fwd_v1_miss_map` | `bk_fwd_v4_intraday_break_close_reclaim` | n≥20 且贏現況才換 |
| preferred 三態 | `pref_3state_v1_verdict_map` | `pref_3state_v2_intraday_break_hold` | 同上 |

## 跑法
```bash
python3 -c "import wave_pref_path_confront as pc; pc.main()"
python3 -c "import wave_silent_deepen as wd; wd.main()"
python3 scripts/observe_sync_fwd_writeback.py --write
```

## 加深（靜默）
- 連鎖日 preferred（例：1124 gap_reclaim → 1125 intraday_break → 1126 FB_hold 通過）
- 次路徑三態校準（非只看 preferred）
- 巢狀口述（3-3轉3-4／細微波）vs 粗浪並記；`WAVE_NEURONS_MATCH=false`
- 現況 `deepen_v3_cross_mine_2023`；下一版候選 `deepen_v4_hold_chain_paint_2026`（守位連鎖＋靜默練畫）；n≥20 且贏現況才換
- 靜默練畫：`paint_open_day_hypothesis` 遠窗對官方柱；不上話筒

## 硬禁
不准當買訊、發明未口述價、未收當收、混海選／黃金買點勝率。
