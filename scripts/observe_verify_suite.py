#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BK-VERIFY／SYNC-VERIFY CLI：可重跑自測／常態覆核落檔。

用法：
  python scripts/observe_verify_suite.py --write
  python scripts/observe_verify_suite.py --cases-dir docs/expert_notes/飆客/observe_manual/cases

落檔：docs/expert_notes/飆客/observe_manual/verify_*.json
軌：chain_trio／level_touch／segment_bias／phone_stamp（話筒 brief・slot・stamp）。
勝率不准混海選／黃金買點；phone_sync=blocked；未過閘不准當買訊。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from observe_verify import CASES_DIR, MARKET_DB, OUT_DIR, run_suite  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BK-VERIFY observe self-test suite")
    ap.add_argument("--db", type=Path, default=MARKET_DB)
    ap.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--write", action="store_true", help="寫入 verify_*.json／md")
    ap.add_argument("--json", action="store_true", help="stdout 印完整 JSON")
    args = ap.parse_args(argv)

    summary = run_suite(
        db_path=args.db,
        cases_dir=args.cases_dir,
        out_dir=args.out_dir,
        write=bool(args.write),
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        tracks = summary.get("tracks") or {}
        print(
            "GATE",
            f"bk_verify cases={summary.get('cases_n')} "
            f"variant={summary.get('current_variant')} "
            f"next={((summary.get('next_variant') or {}).get('variant'))} "
            f"miss={len(summary.get('miss_analysis') or [])} "
            f"phone_sync={summary.get('phone_sync')}",
        )
        for t, sc in sorted(tracks.items()):
            print(
                "TRACK",
                t,
                f"n_decided={sc.get('n_decided')} hit_rate={sc.get('hit_rate')} "
                f"outcomes={sc.get('outcome_counts')}",
            )
        for r in summary.get("rows") or []:
            print(
                "CASE",
                r.get("case_id"),
                r.get("track"),
                r.get("verdict"),
                f"ok={r.get('ok')}",
            )
        if args.write:
            print("WROTE", args.out_dir / "verify_latest.json")
    return 0 if not summary.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
