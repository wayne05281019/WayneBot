#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 W底破頸線（站上）靜默回測／骨架跑（記憶體安全；避開尖峰）。

例：
  python3 scripts/run_biaoke_w_neck.py --db data/wayne_market.db --limit 40
  python3 scripts/run_biaoke_w_neck.py --db data/wayne_market.db --full --json-out /tmp/w_neck.json

不准在 06:30／16:30／DC 03–04 重掃（--force 才略過）。非買訊；face=false。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="biaoke W-neck silent backtest")
    ap.add_argument("--db", default=os.environ.get("WAYNE_MARKET_DB", "data/wayne_market.db"))
    ap.add_argument("--limit", type=int, default=40, help="骨架模式最多幾檔")
    ap.add_argument("--max-events", type=int, default=20, help="骨架每檔每變體最多事件")
    ap.add_argument("--stocks", default="", help="逗號代號；空＝宇宙")
    ap.add_argument("--full", action="store_true", help="全宇宙長窗（不截斷事件）")
    ap.add_argument("--persist", action="store_true", help="全量時也寫 evolve 表（預設否）")
    ap.add_argument("--force", action="store_true", help="尖峰也跑")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-out", default="", help="結果寫入路徑")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"missing db: {db}", file=sys.stderr)
        return 2
    from biaoke_w_neck_verify import run_full_backtest, run_skeleton

    stocks = [s.strip() for s in str(args.stocks or "").split(",") if s.strip()]
    if args.full:
        out = run_full_backtest(
            db,
            stock_ids=stocks or None,
            limit_stocks=0 if not stocks else len(stocks),
            persist=bool(args.persist),
            skip_busy=not bool(args.force),
        )
    else:
        out = run_skeleton(
            db,
            stock_ids=stocks or None,
            limit_stocks=int(args.limit),
            max_events_per_stock=int(args.max_events),
            skip_busy=not bool(args.force),
        )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(
            f"ok={out.get('ok')} kind={out.get('kind')} face={out.get('face')} "
            f"stocks={out.get('stocks')} skipped={out.get('skipped')} "
            f"next={out.get('next_variant')}"
        )
        if out.get("event_counts"):
            print(f"  events={out.get('event_counts')}")
        if out.get("gate"):
            g = out["gate"]
            print(
                f"  gate n_ok={g.get('n_ok')} beats={g.get('beats_baseline')} "
                f"cand_days={g.get('candidate_unique_days')} "
                f"base_days={g.get('baseline_unique_days')}"
            )
        if out.get("would_pass_gate") is not None:
            print(
                f"  would_pass_gate={out.get('would_pass_gate')} "
                f"promote_face={out.get('promote_face')} "
                f"holdout_from={out.get('holdout_from')}"
            )
        tracks = (out.get("tracks") or {}) if isinstance(out, dict) else {}
        for k in sorted(tracks.keys()):
            v = tracks[k]
            print(
                f"  {k}: days={v.get('unique_days')} n_done={v.get('n_done')} "
                f"up={v.get('cont_up_rate')} fake={v.get('false_break_rate')} "
                f"med_ret={v.get('median_ret')}"
            )
    return 0 if out.get("ok") or out.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
