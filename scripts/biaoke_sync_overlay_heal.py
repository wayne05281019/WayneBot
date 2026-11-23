#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SYNC-OVERLAY heal：補公開主文＋自回＋附圖 URL 至今日。

用法：
  python3 scripts/biaoke_sync_overlay_heal.py
  python3 scripts/biaoke_sync_overlay_heal.py --db data/wayne_market.db
  python3 scripts/biaoke_sync_overlay_heal.py --since 2026-09-10 --no-replies
  python3 scripts/biaoke_sync_overlay_heal.py --skip-atoms --skip-charts

Render 永久碟：WAYNE_DB_PATH=/opt/render/project/src/data/wayne_market.db
不准搶正式 TELEGRAM getUpdates；不准假圖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_overlay_sync import ARCHIVE_END, run_heal  # noqa: E402
from config import get_db_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Heal biaoke overlay to today")
    ap.add_argument("--db", default="", help="wayne_market.db 路徑")
    ap.add_argument(
        "--since",
        default=ARCHIVE_END,
        help=f"起日（含；預設 {ARCHIVE_END}＝1709 末日）",
    )
    ap.add_argument("--no-replies", action="store_true", help="略過討論串自回")
    ap.add_argument("--max-pages", type=int, default=80, help="Member-All 最大頁數")
    ap.add_argument("--skip-atoms", action="store_true", help="不重抽 atoms")
    ap.add_argument("--skip-charts", action="store_true", help="不併 chart_index")
    args = ap.parse_args(argv)

    db = args.db or os.environ.get("WAYNE_DB_PATH") or get_db_path()
    report = run_heal(
        db_path=db,
        since_date=args.since,
        fetch_replies=not args.no_replies,
        max_pages=int(args.max_pages),
        extract_atoms=not args.skip_atoms,
        merge_charts=not args.skip_charts,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sync = report.get("sync") or {}
    if not sync.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
