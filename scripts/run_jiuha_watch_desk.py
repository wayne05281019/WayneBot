#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""啾哈觀盤桌：今日盤後圖＋明日盤中檢查點（非買訊）。

  python3 scripts/jiuha_watch_desk.py
  python3 scripts/jiuha_watch_desk.py --asof 20261120
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiuha_watch_desk import write_watch_desk_artifacts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="", help="YYYYMMDD；空＝最新已收加權日")
    ap.add_argument("--market", default="/workspace/data/wayne_market.db")
    ap.add_argument("--out", default="/opt/cursor/artifacts/jiuha")
    args = ap.parse_args()
    res = write_watch_desk_artifacts(
        market_db=args.market, out_dir=args.out, asof=args.asof
    )
    print(
        json.dumps(
            {
                k: res.get(k)
                for k in ("ok", "asof", "md", "png", "n_tomorrow_intraday")
            },
            ensure_ascii=False,
        )
    )
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
