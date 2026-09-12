#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓缺的官方序列，四路對質飆客確認句。結果寫 witness.md。不進海選。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_archive import load_bundled_archive  # noqa: E402
from biaoke_witness import run_witness, save_snapshot, write_md  # noqa: E402
from config import get_db_path  # noqa: E402


def main() -> int:
    blob = load_bundled_archive()
    posts = list((blob or {}).get("posts") or [])
    db = os.environ.get("WAYNE_DB_PATH") or get_db_path()
    snap = run_witness(posts, fetch=True, db_path=db)
    save_snapshot(snap)
    write_md(snap)
    g = snap.get("gaps") or {}
    now = snap.get("now") or {}
    c2 = snap.get("confirm_aux2") or {}
    print(
        f"claims {snap.get('n_claims')} twii {g.get('twii')} tsmc {g.get('tsmc')} "
        f"sox {g.get('sox')} tx {g.get('tx_days')} night {g.get('tx_night')} "
        f"now {now.get('date')} aux {now.get('aux_n')} {now.get('infer')}"
    )
    from biaoke_verify import refresh_recent_twii  # noqa: E402

    try:
        n_twii = refresh_recent_twii(db, range_="2y")
        print(f"twii_db {n_twii}")
    except Exception as exc:
        print("twii_db", type(exc).__name__)
    try:
        from biaoke_ingest import ingest_public_posts

        ing = ingest_public_posts(db_path=db, max_ids=12, refresh_latest=3)
        print("ingest", {k: ing.get(k) for k in ("ok", "added", "updated", "replies", "n")})
    except Exception as exc:
        print("ingest", type(exc).__name__, exc)
    print(f"confirm+aux>=2 hold20 {c2.get('hold_pct')}% n={c2.get('n')} mean {c2.get('mean_ret')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
