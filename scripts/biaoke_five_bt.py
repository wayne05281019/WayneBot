#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五件工具對官方柱回測。結果寫 docs/expert_notes/飆客/five_bt.md。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_five_bt import one_liner, run_five_bt, save_snapshot  # noqa: E402
from config import get_db_path  # noqa: E402


def main() -> int:
    db = os.environ.get("WAYNE_DB_PATH") or get_db_path()
    snap = run_five_bt(db)
    if not snap.get("ok"):
        print(snap.get("error") or "fail")
        return 1
    save_snapshot(snap)
    print(one_liner(snap))
    t = snap.get("tools") or {}
    for k in ("wave", "morph", "vol", "keyk", "leader"):
        b = t.get(k) or {}
        print(f"  {k} n={b.get('n')} hit={b.get('hit')} miss={b.get('miss')} pending={b.get('pending')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
