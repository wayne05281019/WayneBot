#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""平行軌圖／文字準度回測（非買訊）。

  .venv/bin/python scripts/channel_rail_text_backtest.py --db data/wayne_market.db --limit 40
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from channel_rail_text_verify import run_skeleton  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--max-events", type=int, default=20)
    args = ap.parse_args()
    out = run_skeleton(
        args.db, limit_stocks=int(args.limit), max_events=int(args.max_events)
    )
    g = out.get("gate") or {}
    print(
        json.dumps(
            {
                "ok": out.get("ok"),
                "events": out.get("events"),
                "stocks": out.get("stocks"),
                "promote_ready": g.get("promote_ready"),
                "text_promote_ready": g.get("text_promote_ready"),
                "geom": g.get("geom"),
                "n_unique_days": g.get("n_unique_days"),
                "n_sids": g.get("n_sids"),
                "near_beats_none_hold": g.get("near_beats_none_hold"),
                "next_candidate": g.get("next_candidate"),
                "product_entry": out.get("product_entry"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
