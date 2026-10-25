#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""止穩◆現況 hold_l60 vs 緊版 hold_l60_tight 對質收斂。

本庫官方日 K；Asia/Taipei；空名單不算；盤中未收不當收。
n≥20 且緊版贏現況 → 才准換畫圖規則並再生下一版（§13）；否則只落測量。
不准改 leave_zero／golden_buy／買訊。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stabilize_verify import (  # noqa: E402
    TAG_CURRENT,
    TAG_NEXT,
    backfill_recent_days,
    confront_summary,
)

TP = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--trading-days", type=int, default=55)
    ap.add_argument("--end", default="", help="YYYYMMDD 上緣（含）；空＝庫內最新已收")
    ap.add_argument(
        "--out",
        default="/opt/cursor/artifacts/stabilize-diamond-20261025",
    )
    ap.add_argument(
        "--skip-backfill",
        action="store_true",
        help="只讀既有 tape 寫裁決（不重掃母體）",
    )
    args = ap.parse_args()
    if not os.path.isfile(args.db):
        print("缺庫", file=sys.stderr)
        return 2
    out = args.out.rstrip("/")
    os.makedirs(out, exist_ok=True)
    ran = {}
    if not args.skip_backfill:
        print(
            f"+ backfill trading_days={args.trading_days} end={args.end or 'latest'}",
            flush=True,
        )
        ran = backfill_recent_days(
            args.db,
            trading_days=int(args.trading_days),
            end=str(args.end or ""),
        )
        print(
            f"== days={len(ran.get('days') or [])} scored={ran.get('scored')} "
            f"line={ran.get('line')}",
            flush=True,
        )
    summary = confront_summary(args.db)
    summary["generated_at"] = _now()
    summary["ran_backfill"] = not args.skip_backfill
    summary["trading_days"] = int(args.trading_days)
    summary["end"] = str(args.end or "")
    summary["backfill_days"] = [
        {"as_of": d.get("as_of"), "wrote": d.get("wrote")}
        for d in (ran.get("days") or [])
    ]
    path_json = os.path.join(out, "stabilize_confront_converge.json")
    path_md = os.path.join(out, "stabilize_confront_converge_zh.md")
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    md_lines = [
        "# 止穩◆現況 vs 緊版對質",
        "",
        f"- 產生：`{summary['generated_at']}`（Asia/Taipei）",
        f"- 現況：`{TAG_CURRENT}`；緊版：`{TAG_NEXT}`；主窗 h{summary['primary_h']}",
        f"- n_days 現況={summary['n_days_current']}／緊版={summary['n_days_next']}（門檻 {summary['min_n']}）",
        f"- 緊版贏現況：{'是' if summary['beats_current'] else '否'}",
        f"- 閘：{'通過' if summary['gate_ok'] else '未過'}（通過才准換畫圖；永遠非買訊）",
        "",
        f"**一句：** {summary['line']}",
        "",
    ]
    md = "\n".join(md_lines)
    with open(path_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(md, flush=True)
    print(f"== 寫入 {path_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
