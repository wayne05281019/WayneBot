#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""啾哈對質官方欄補洞 CLI（非買訊）。

  python3 scripts/jiuha_official_heal.py
  python3 scripts/jiuha_official_heal.py --market data/wayne_market.db --sessions 60
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiuha_official_heal import coverage_report, heal_all  # noqa: E402

DEFAULT_MARKET = str(ROOT / "data" / "wayne_market.db")


def main() -> int:
    ap = argparse.ArgumentParser(description="啾哈對質官方欄補洞（非買訊）")
    ap.add_argument("--market", default=DEFAULT_MARKET)
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--from-ymd", default="", help="補洞起日 YYYYMMDD；空＝對質窗起")
    ap.add_argument("--margin-max-days", type=int, default=90)
    ap.add_argument("--otc-max-months", type=int, default=6)
    ap.add_argument("--usdtwd-range", default="6mo")
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument(
        "--coverage-only",
        action="store_true",
        help="只報覆蓋率，不抓網",
    )
    args = ap.parse_args()
    if args.coverage_only:
        rep = coverage_report(args.market, sessions_n=args.sessions)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep.get("ok") else 2
    res = heal_all(
        args.market,
        from_ymd=args.from_ymd,
        sessions_n=args.sessions,
        margin_max_days=args.margin_max_days,
        otc_max_months=args.otc_max_months,
        usdtwd_range=args.usdtwd_range,
        sleep_s=args.sleep,
    )
    # 精簡輸出：步驟 ok＋前後覆蓋
    slim = {
        "ok": res.get("ok"),
        "generated_at": res.get("generated_at"),
        "before": res.get("before"),
        "after": res.get("after"),
        "delta": res.get("delta"),
        "optional_unavailable": res.get("optional_unavailable"),
        "steps": {
            k: {
                kk: vv
                for kk, vv in (v or {}).items()
                if kk
                in (
                    "ok",
                    "wrote",
                    "wrote_rows",
                    "gap_fill_rows",
                    "foreign_tx_days",
                    "table_n",
                    "from",
                    "to",
                    "n_complete_ohlc",
                    "n_close_stamp",
                    "historical_ohlc",
                    "mis_ohlc",
                    "lag_vs_twii_days",
                    "source",
                    "status",
                    "reason",
                    "note_zh",
                    "errors",
                    "retries",
                )
            }
            for k, v in (res.get("steps") or {}).items()
        },
        "not_buy_signal": True,
        "timezone": "Asia/Taipei",
    }
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
