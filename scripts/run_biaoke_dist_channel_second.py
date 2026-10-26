#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D6／D7／D9 出貨痕跡／通道／第二段下殺靜默回測（記憶體安全；避開尖峰）。

例：
  python3 scripts/run_biaoke_dist_channel_second.py --db data/wayne_market.db --limit 40
  python3 scripts/run_biaoke_dist_channel_second.py --db data/wayne_market.db --full --force \\
    --json-out internal/biaoke-dcs-full-YYYYMMDD.json

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
    ap = argparse.ArgumentParser(description="biaoke D6/D7/D9 silent backtest")
    ap.add_argument("--db", default=os.environ.get("WAYNE_MARKET_DB", "data/wayne_market.db"))
    ap.add_argument("--limit", type=int, default=40, help="骨架模式最多幾檔")
    ap.add_argument("--max-events", type=int, default=20, help="骨架每檔每變體最多事件")
    ap.add_argument("--stocks", default="", help="逗號代號；空＝宇宙")
    ap.add_argument("--full", action="store_true", help="全宇宙長窗（不截斷事件）")
    ap.add_argument("--persist", action="store_true", help="全量時也寫 evolve 表（預設否）")
    ap.add_argument("--force", action="store_true", help="尖峰也跑")
    ap.add_argument(
        "--tracks",
        default="d6,d7,d9",
        help="逗號：d6／d7／d9（預設全開）",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-out", default="", help="結果寫入路徑")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"missing db: {db}", file=sys.stderr)
        return 2
    from biaoke_dist_channel_second_verify import (
        KIND_D6,
        KIND_D7,
        KIND_D9,
        run_full_backtest,
        run_skeleton,
    )

    track_map = {"d6": KIND_D6, "d7": KIND_D7, "d9": KIND_D9}
    tracks = []
    for t in str(args.tracks or "").split(","):
        k = track_map.get(t.strip().lower())
        if k and k not in tracks:
            tracks.append(k)
    if not tracks:
        tracks = [KIND_D6, KIND_D7, KIND_D9]

    stocks = [s.strip() for s in str(args.stocks or "").split(",") if s.strip()]
    if args.full:
        out = run_full_backtest(
            db,
            stock_ids=stocks or None,
            limit_stocks=0 if not stocks else len(stocks),
            persist=bool(args.persist),
            skip_busy=not bool(args.force),
            tracks=tracks,
        )
    else:
        out = run_skeleton(
            db,
            stock_ids=stocks or None,
            limit_stocks=int(args.limit),
            max_events_per_stock=int(args.max_events),
            skip_busy=not bool(args.force),
            tracks=tracks,
        )
    if args.json_out:
        parent = os.path.dirname(os.path.abspath(args.json_out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(
            f"ok={out.get('ok')} face={out.get('face')} "
            f"stocks={out.get('stocks')} skipped={out.get('skipped')} "
            f"elapsed={out.get('elapsed_sec')}"
        )
        if out.get("event_counts"):
            print(f"  events={out.get('event_counts')}")
        kinds = out.get("kinds") or {}
        for kind, pack in kinds.items():
            g = pack.get("gate") or {}
            gh = pack.get("gate_holdout") or {}
            print(
                f"  {kind}: would_pass={pack.get('would_pass_gate')} "
                f"next={pack.get('next_variant')} "
                f"n_ok={g.get('n_ok')} beats={g.get('beats_baseline')} "
                f"holdout_beats={gh.get('beats_baseline')} "
                f"cand_days={g.get('candidate_unique_days')}"
            )
        if out.get("tracks") and not kinds:
            for k, v in (out.get("tracks") or {}).items():
                print(f"  skeleton {k}: face={v.get('face')} next={v.get('next_variant')}")
    return 0 if out.get("ok") or out.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
