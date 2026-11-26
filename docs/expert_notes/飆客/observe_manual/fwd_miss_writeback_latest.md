# SYNC-FWD・miss → 手冊回寫

- written_at：`2026-11-26T14:01:39+0800`（Asia/Taipei）
- 現況鍵：`bk_fwd_v1_miss_map`
- 下一版：`bk_fwd_v4_intraday_break_close_reclaim`
- eod miss：**14**／可操作：**13**
- 話筒警語（固定）：`試標・推論／非他原文・非買訊・對質未過閘`
- 非買訊；`phone_sync=blocked`；勝率不准混海選／黃金買點。

## miss → 修正對照

| as_of | kind | prefer_path | rule_ids | code_fix（摘） |
|---|---|---|---|---|
| `20261109` | condition_defer | `-` | WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-OPS-TWO-BAR | 條件句『不過41760→很快再測週五低』：盤中刺穿但收未站穩時，回測時序可遞延，不准當日強制計B-b必發生 |
| `20261110` | condition_defer | `-` | WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-OPS-TWO-BAR | 條件句『未站穩41760→再測週五低』：若日盤開盤即穩壓上且全日低＞41760，當日取消N1必經、改標B-a_hold；下一窗優先回測41760撐與更高壓431 |
| `20261111` | hold_fail_escalate | `-` | WR-OPS-PRESS-TO-SUPPORT,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 條件句『站穩41760後回測41760』：若下一開市日開盤即貼／過更高壓43135，且全日低≫41760並收穩43135上，當日取消M1必經、標 post_ho |
| `20261112` | hold_fail_escalate | `-` | WR-OPS-PRESS-TO-SUPPORT,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 條件句『收穩43135後回測撐』：若回測當日收仍失43135，當日標 post_hold_fail，下一窗把41760升為必經回測；43000下若盤中觸及但收回 |
| `20261113` | hold_fail_escalate | `-` | WR-OPS-PRESS-TO-SUPPORT,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 條件句『收失43135後下一窗優先41760』：若下一開市日開盤即站回並全日低≫41760且收穩43135上，標 post_hold_reclaim，把pref |
| `20261116` | hold_fail_escalate | `-` | WR-OPS-PRESS-TO-SUPPORT,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 條件句『收復43135後下一窗優先回測當撐』：若下一開市日開盤後迅速失43135且日低遠低於41760，標 post_hold_43135_fail＋B-a_h |
| `20261117` | pending_not_veto | `M3_seek_37837_after_41760_fail` | WR-FWD-PENDING-NOT-VETO,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 未觸目標≠否決：標 pending＋N1_follow；L 靠近可升權 pending，仍非觸發。 |
| `20261118` | pending_not_veto | `M3_seek_37837_continue` | WR-FWD-PENDING-NOT-VETO,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 未觸目標≠否決：標 pending＋N1_follow；L 靠近可升權 pending，仍非觸發。 |
| `20261119` | pending_not_veto | `M3_seek_37837_continue` | WR-FWD-PENDING-NOT-VETO,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | 未觸目標≠否決：標 pending＋N1_follow；L 靠近可升權 pending，仍非觸發。 |
| `20261120` | level_broke_follow_oral_band | `N1_follow_through_below_band` | WR-OPS-FAKE-BREAK,WR-LEVEL-ORAL-ONLY,WR-FWD-LOOP,WR-SEGMENT-TRIAL-WARN | preferred＝測位且 L／收皆破 → 標觸發＋續弱 follow；下一窗改口頭已有之更低帶為對照、原位收回為假跌破觀察；不准發明未口述新低。 |
| `20261123` | target_touch_bounce_elevate_reclaim | `FB_reclaim_37837_watch` | WR-FWD-TOUCH-BOUNCE-RECLAIM,WR-OPS-FAKE-BREAK,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | preferred 續弱測口頭目標時：L 觸／切入帶＋收彈且仍＜收回位 → 標 M3_touched_then_bounce＋N1_partial，下一窗升權  |
| `20261124` | gap_reclaim_hold_elevate_w4 | `W4_reclaim_418_427_band` | WR-FWD-GAP-RECLAIM-HOLD,WR-OPS-FAKE-BREAK,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | preferred＝FB_reclaim：跳空 O＞收回位且全日 L／C＞收回位 → 標 FB_gap_reclaim_hold；下一窗升權 W4_reclai |
| `20261125` | intraday_break_close_reclaim_elevate_hold | `FB_hold_above_37837` | WR-FWD-INTRADAY-BREAK-CLOSE-RECLAIM,WR-OPS-FAKE-BREAK,WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | preferred＝W4_reclaim：H＜帶下沿且 L＜收回位但 C＞收回位 → 標 FB_intraday_break_close_reclaim；下一窗 |
| `20261126` | narrative_only | `-` | WR-FWD-LOOP,WR-LEVEL-ORAL-ONLY,WR-SEGMENT-TRIAL-WARN | preferred＝FB_hold 且全日 L＞37837、C＞37837 → 標 false_break_hold 通過；下一窗維持 FB_hold 優先；W |

## 當令敘述修正

- as_of / kind：`20261125` / `intraday_break_close_reclaim_elevate_hold`
- prefer_path：`FB_hold_above_37837`
- labels：FB_intraday_break_close_reclaim, false_break_hold, M3_resume_backup
- 修正：文敘：盤中失收回位、收站回；下一窗看守住 vs 再失；W4 降權；段號試標＋固定警語；非買訊。

## 硬禁

- 不准把反彈／收彈當新五波①
- 不准發明未口述之新低目標
- 不准改黃金買點／不當買訊
- DC／我估句不准寫成他說
