#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑飆大三百／一百／三百：融會貫通＋官方日 K 回測。結果寫 docs/expert_notes/飆客/fuse_700.md。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_fuse import run_fuse_700, save_snapshot  # noqa: E402
from config import get_db_path  # noqa: E402


def main() -> int:
    db = os.environ.get("WAYNE_DB_PATH") or get_db_path()
    snap = run_fuse_700(db)
    save_snapshot(snap)
    a = snap.get("round_a") or {}
    b = snap.get("round_b") or {}
    c = snap.get("round_c") or {}
    print(
        f"A {a.get('fused')}/{a.get('n')} fused  "
        f"B {b.get('answered')}/{b.get('n')}  "
        f"C bar {c.get('with_bar')}/{c.get('n')}  "
        f"posts={snap.get('n_posts')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
