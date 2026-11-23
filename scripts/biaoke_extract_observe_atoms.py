#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BK-CORPUS：1709＋overlay＋社團後台 → 觀測原子 JSON／MD 索引。

用法：
  python3 scripts/biaoke_extract_observe_atoms.py
  WAYNE_DB_PATH=/path/to/wayne_market.db python3 scripts/biaoke_extract_observe_atoms.py

不進海選、不改黃金買點、社團不准上話筒原文。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_observe_atoms import run_extract  # noqa: E402
from config import get_db_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract biaoke observe atoms")
    ap.add_argument("--db", default="", help="wayne_market.db（讀 biaoke_posts overlay）")
    ap.add_argument("--out-json", default="", help="atoms_latest.json 路徑")
    ap.add_argument("--out-md", default="", help="ATOMS_INDEX.md 路徑")
    ap.add_argument("--no-club", action="store_true", help="略過社團後台包")
    args = ap.parse_args(argv)

    db = args.db or os.environ.get("WAYNE_DB_PATH") or get_db_path()
    payload = run_extract(
        db_path=db,
        out_json=args.out_json,
        out_md=args.out_md,
        include_club=not args.no_club,
    )
    cov = payload.get("coverage") or {}
    meta = payload.get("corpus") or {}
    print(
        f"atoms {payload.get('atom_n')} core {cov.get('core_n')} "
        f"merged {meta.get('merged_n')} "
        f"{meta.get('from')}→{meta.get('to')} "
        f"themes {cov.get('by_theme')}"
    )
    for g in cov.get("gaps") or []:
        print("gap:", g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
