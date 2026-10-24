#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外資恐懼鏈｜全量回測收斂（escalate＋calm 分軌；不是買訊）。

本庫優先、密窗全日非抽樣。預設起點＝外資 T86 連續密窗。
跑完寫 converge JSON／中文摘要；不改 leave_zero／海選／藍▲紅框。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foreign_fear_chain import (  # noqa: E402
    DENSE_FOREIGN_START,
    converge_md,
    converge_verdict,
)

TP = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TP).isoformat(timespec="seconds")


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return int(subprocess.call(cmd))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/wayne_market.db")
    ap.add_argument("--start", default=DENSE_FOREIGN_START)
    ap.add_argument("--end", default="20261022")
    ap.add_argument(
        "--out",
        default="/opt/cursor/artifacts/foreign-fear-chain-20261025",
    )
    ap.add_argument(
        "--skip-run",
        action="store_true",
        help="只讀既有 artifact 寫裁決（不重跑回測）",
    )
    ap.add_argument(
        "--with-extreme",
        action="store_true",
        help="順便跑極端 D+（分軌；不與 escalate／calm 混％）",
    )
    args = ap.parse_args()
    if not os.path.isfile(args.db):
        print("缺庫", file=sys.stderr)
        return 2
    out = args.out.rstrip("/")
    os.makedirs(out, exist_ok=True)
    py = sys.executable
    if not args.skip_run:
        rc = _run(
            [
                py,
                str(ROOT / "scripts/foreign_sell_escalate_backtest.py"),
                "--db",
                args.db,
                "--start",
                args.start,
                "--end",
                args.end,
                "--out",
                f"{out}/escalate",
            ]
        )
        if rc != 0:
            return rc
        rc = _run(
            [
                py,
                str(ROOT / "scripts/foreign_sell_calm_backtest.py"),
                "--db",
                args.db,
                "--start",
                args.start,
                "--end",
                args.end,
                "--out",
                f"{out}/calm",
            ]
        )
        if rc != 0:
            return rc
        if args.with_extreme:
            rc = _run(
                [
                    py,
                    str(ROOT / "scripts/foreign_sell_extreme_backtest.py"),
                    "--db",
                    args.db,
                    "--start",
                    args.start,
                    "--end",
                    args.end,
                    "--out",
                    f"{out}/extreme",
                ]
            )
            if rc != 0:
                return rc
    verdict = converge_verdict(args.db, artifact_root=out)
    verdict["generated_at"] = _now()
    verdict["ran_backtests"] = not args.skip_run
    verdict["with_extreme"] = bool(args.with_extreme)
    path_json = os.path.join(out, "foreign_fear_chain_converge.json")
    path_md = os.path.join(out, "foreign_fear_chain_converge_zh.md")
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    md = converge_md(verdict)
    with open(path_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(md, flush=True)
    print(f"== 寫入 {path_json}", flush=True)
    # 未過閘＝成功收斂紀錄；不准假裝過閘
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
