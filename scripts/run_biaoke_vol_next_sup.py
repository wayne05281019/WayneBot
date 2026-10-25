#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D4 破撐→下一撐靜默骨架跑（記憶體安全；避開尖峰）。

例：
  python3 scripts/run_biaoke_vol_next_sup.py --db data/wayne_market.db --limit 40
  python3 scripts/run_biaoke_vol_next_sup.py --db data/wayne_market.db --stocks 3081,3017

不准在 06:30／16:30／DC 03–04 重掃（--force 才略過）。非買訊。
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
    ap = argparse.ArgumentParser(description="biaoke vol next-support silent skeleton")
    ap.add_argument("--db", default=os.environ.get("WAYNE_MARKET_DB", "data/wayne_market.db"))
    ap.add_argument("--limit", type=int, default=40, help="最多幾檔（逐檔串流）")
    ap.add_argument("--max-events", type=int, default=20, help="每檔最多事件")
    ap.add_argument("--stocks", default="", help="逗號代號；空＝宇宙前 N＋錨檔")
    ap.add_argument("--force", action="store_true", help="尖峰也跑（預設跳過）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print(f"missing db: {db}", file=sys.stderr)
        return 2
    from biaoke_vol_next_sup_verify import run_skeleton

    stocks = [s.strip() for s in str(args.stocks or "").split(",") if s.strip()]
    out = run_skeleton(
        db,
        stock_ids=stocks or None,
        limit_stocks=int(args.limit),
        max_events_per_stock=int(args.max_events),
        skip_busy=not bool(args.force),
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(
            f"ok={out.get('ok')} events={out.get('events_written')} "
            f"stocks={out.get('stocks')} skipped={out.get('skipped')}"
        )
        tracks = (out.get("tracks") or {}) if isinstance(out, dict) else {}
        for k, v in list(tracks.items())[:8]:
            print(
                f"  {k}: days={v.get('unique_days')} "
                f"hit={v.get('hit_next_rate')} down={v.get('cont_down_rate')} "
                f"gate={v.get('gate_ready')}"
            )
    return 0 if out.get("ok") or out.get("skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
