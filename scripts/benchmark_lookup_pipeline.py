#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機量測查股流水線各段秒數（不含 Telegram 上傳）。Asia/Taipei 僅供報告註記。"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import get_db_path


def _timed(label: str, fn):
    t0 = time.monotonic()
    out = fn()
    return out, time.monotonic() - t0, label


def benchmark_sid(sid: str, db: str) -> dict[str, float]:
    from chip_tape import build_tape
    from vol_zone_chart import (
        ensure_official_volume_window,
        lookup_vol_ensure_days,
        prepare_lookup_structure_bars,
        prepare_volume_zone,
        render_lookup_vol_result,
    )
    from three_in_one_chart import render_lookup_structure_result
    from wayne_navigator import (
        NavigatorEngine,
        render_decision_card_png,
        render_first_glance_png,
        submit_mpl_paint,
        run_mpl_paint,
    )

    seg: dict[str, float] = {}
    engine = NavigatorEngine(db)

    def ensure():
        return ensure_official_volume_window(
            sid, db, days=lookup_vol_ensure_days(), stock_name=sid
        )

    stats, seg["ensure"], _ = _timed("ensure", ensure)

    def build_card():
        card = engine.get_decision_card(sid, lookback=20, merge_live=False)
        ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
        return card, ohlc

    (card, ohlc), seg["get_decision_card"], _ = _timed("get_decision_card", build_card)
    if card.get("error"):
        return seg

    def do_tape():
        return build_tape(db, sid, merge_live=False) or {}

    tape, seg["build_tape"], _ = _timed("build_tape", do_tape)

    td = tempfile.mkdtemp(prefix="lk-bench-")
    card_p = os.path.join(td, f"{sid}-card.png")
    glance_p = os.path.join(td, f"{sid}-glance.png")
    struct_p = os.path.join(td, f"{sid}-struct.png")
    vol_p = os.path.join(td, f"{sid}-vol.png")

    def paint_card():
        return render_decision_card_png(card, card_p)

    _, seg["paint_card"], _ = _timed("paint_card", lambda: run_mpl_paint(paint_card))

    def paint_glance():
        return render_first_glance_png(sid, card, tape, glance_p, db, ohlc=ohlc)

    _, seg["paint_glance"], _ = _timed("paint_glance", lambda: run_mpl_paint(paint_glance))

    def prep_struct():
        return prepare_lookup_structure_bars(sid, sid, db, vol_ensure=stats)

    bars_pack, seg["prep_struct_bars"], _ = _timed("prep_struct_bars", prep_struct)

    def paint_struct():
        render_lookup_structure_result(
            sid, sid, db, struct_p, card=card, pack=bars_pack, live_quote=None
        )

    _, seg["paint_struct"], _ = _timed("paint_struct", lambda: run_mpl_paint(paint_struct))

    t_prep_vol0 = time.monotonic()
    zone_pack = prepare_volume_zone(
        sid, sid, db, preloaded_work=bars_pack.get("work"), known_ensure=stats
    )
    seg["prep_vol_zone"] = time.monotonic() - t_prep_vol0

    def paint_vol():
        render_lookup_vol_result(sid, sid, db, vol_p, card=card, pack=zone_pack)

    _, seg["paint_vol"], _ = _timed("paint_vol", lambda: run_mpl_paint(paint_vol))

    from bot_servers import WayneTelegramBot

    for kind, path in (
        ("card", card_p),
        ("glance", glance_p),
        ("struct", struct_p),
        ("vol", vol_p),
    ):
        if os.path.isfile(path):
            t0 = time.monotonic()
            WayneTelegramBot._prepare_lookup_album_photo(path, kind)
            seg[f"prep_send_{kind}"] = time.monotonic() - t0

    seg["paint_total"] = (
        seg.get("paint_card", 0)
        + seg.get("paint_glance", 0)
        + seg.get("paint_struct", 0)
        + seg.get("paint_vol", 0)
    )
    seg["pipeline_cpu"] = (
        seg.get("ensure", 0)
        + seg.get("get_decision_card", 0)
        + seg.get("prep_struct_bars", 0)
        + seg.get("prep_vol_zone", 0)
        + seg.get("paint_total", 0)
    )
    return seg


def main():
    db = get_db_path()
    if not os.path.isfile(db):
        print(f"no db at {db}", file=sys.stderr)
        sys.exit(1)
    sids = sys.argv[1:] or ["1303", "2330"]
    rows = []
    for sid in sids:
        print(f"=== {sid} ===", flush=True)
        seg = benchmark_sid(sid, db)
        for k in sorted(seg.keys()):
            print(f"  {k}: {seg[k]:.3f}s")
        rows.append((sid, seg))
    return rows


if __name__ == "__main__":
    main()
