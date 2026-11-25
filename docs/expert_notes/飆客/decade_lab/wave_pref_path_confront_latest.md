# preferred 路徑三態對質（靜默）

寫入：`2026-11-25T15:06:41+0800`（Asia/Taipei）。
軌：`wave_pref_path_3state`｜現況 `pref_3state_v1_verdict_map`｜下一版 `pref_3state_v2_intraday_break_hold`

- n_decided=8 hit_rate=0.625 gate_n20=False replace=False
- state_counts={'fail': 3, 'hit': 5, 'unknown': 3, 'partial': 2}
- 警語：`試標・推論／非他原文・非買訊・對質未過閘`

不是買訊。不上話筒定案。WAVE_NEURONS_MATCH=false。

## 列

| as_of | preferred | state | hit |
|---|---|---|---|
| `20261109` | `P1_must_retest_friday` | fail | False |
| `20261110` | `N1_still_retest_friday` | hit | True |
| `20261111` | `M1_retest_41760_as_support` | fail | False |
| `20261112` | `M1_retest_43135_as_support` | unknown | None |
| `20261113` | `M2_reclaim_43135` | hit | True |
| `20261116` | `M3_lose_41760_then_friday` | hit | True |
| `20261117` | `M3_seek_37837_after_41760_fail` | unknown | None |
| `20261118` | `M3_seek_37837_continue` | unknown | None |
| `20261119` | `M3_seek_37837_continue` | partial | None |
| `20261120` | `M3_seek_37837_continue` | hit | True |
| `20261123` | `M3_extend_toward_35579` | partial | None |
| `20261124` | `FB_reclaim_37837_watch` | hit | True |
| `20261125` | `W4_reclaim_418_427_band` | fail | False |
