#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D10／D11a／D11g 價量路徑靜默骨架。非買訊；預設不上臉。

例：
  python3 scripts/run_biaoke_pv_path.py --db data/wayne_market.db \\
    --from-json /tmp/pv_deepdive.json
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("WAYNE_MARKET_DB", "data/wayne_market.db"))
    ap.add_argument("--from-json", default="", help="deepdive JSON 匯入示意列")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    from biaoke_pv_path_verify import run_skeleton

    out = run_skeleton(db, json_snapshot=str(args.from_json or ""))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"ok={out.get('ok')} imported={out.get('imported_rows')} face={out.get('face_default')}")
        for kind, pack in (out.get("tracks") or {}).items():
            vars_ = (pack or {}).get("variants") or {}
            print(f"  {kind}: variants={list(vars_.keys())}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
