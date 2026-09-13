#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從飆大發文起始（2023-12-01）把官方上市櫃日K補進本機庫。

已齊的交易日不重抓。不把 wayne_market.db 寫進 git。
一次可限 max_days，下次接著跑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data_fetcher import BIAOKE_QUOTE_BACKFILL_START, DataFetcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="回補發文起始起的官方日K")
    parser.add_argument("--start", default=BIAOKE_QUOTE_BACKFILL_START)
    parser.add_argument("--end", default="")
    parser.add_argument("--max-days", type=int, default=40)
    parser.add_argument("--sleep", type=float, default=0.85)
    parser.add_argument("--db", default="")
    args = parser.parse_args()
    db = args.db or os.path.join(ROOT, "data", "wayne_market.db")
    fetcher = DataFetcher(db_path=db)
    stats = fetcher.fill_historical_market_days(
        start_date=args.start,
        end_date=args.end or None,
        max_days=max(1, int(args.max_days)),
        sleep_s=float(args.sleep),
        skip_chips=True,
    )
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
