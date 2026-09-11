#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""費半／1-4 重疊對 Yahoo ^SOX 與加權日 K。結果寫 docs/expert_notes/飆客/sox_14.md。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_desk import load_corpus  # noqa: E402
from biaoke_sox import run_sox_14, save_sox_snapshot  # noqa: E402
from config import get_db_path  # noqa: E402


def main() -> int:
    db = os.environ.get("WAYNE_DB_PATH") or get_db_path()
    posts = list((load_corpus(db) or {}).get("posts") or [])
    snap = run_sox_14(posts, db_path=db)
    save_sox_snapshot(snap)
    ov = snap.get("overlap_twii20") or {}
    print(
        f"overlap {snap.get('n_overlap')} sox_talk {snap.get('n_sox')}  "
        f"TWII hold {ov.get('hold')}% n={ov.get('n')} mean {ov.get('mean_ret')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
