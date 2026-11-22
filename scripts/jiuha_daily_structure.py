#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""啾哈每日盤勢結構觀察（非買訊）。用法：

  python3 scripts/jiuha_daily_structure.py
  python3 scripts/jiuha_daily_structure.py --asof 20261120
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiuha_observe import write_daily_artifacts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="", help="YYYYMMDD；空＝最新已收加權日")
    ap.add_argument(
        "--corpus",
        default="/workspace/data/jiuha_corpus/jiuha.sqlite",
    )
    ap.add_argument("--market", default="/workspace/data/wayne_market.db")
    ap.add_argument("--out", default="/opt/cursor/artifacts/jiuha")
    args = ap.parse_args()
    res = write_daily_artifacts(
        corpus_db=args.corpus,
        market_db=args.market,
        out_dir=args.out,
        asof=args.asof,
    )
    print(json.dumps({k: res.get(k) for k in ("ok", "asof", "md", "n_posts")}, ensure_ascii=False))
    print(res.get("md"))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
