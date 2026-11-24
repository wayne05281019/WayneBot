#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可重跑 SYNC-RETRACT 開火句（上一句位→官方近窗→改口／還在等／未完）。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sync_retract import SAMPLE_PATH, run_sync_retract  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="SYNC-RETRACT 開火句可重跑")
    ap.add_argument(
        "--db",
        default=os.environ.get("WAYNE_DB_PATH") or str(ROOT / "data" / "wayne_market.db"),
    )
    ap.add_argument("--near-n", type=int, default=5)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--write", action="store_true", help="落 sync_retract_latest.json/md")
    ap.add_argument("--json", action="store_true", help="stdout JSON")
    args = ap.parse_args()
    payload = run_sync_retract(
        args.db,
        near_n=args.near_n,
        as_of=args.as_of,
        write_sample=bool(args.write),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload.get("fire_line") or "")
        print("status=", payload.get("status"))
        if args.write:
            print("wrote", SAMPLE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
