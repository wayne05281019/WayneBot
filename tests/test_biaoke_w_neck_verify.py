# -*- coding: utf-8 -*-
"""D2 W底破頸線（站上）靜默骨架／偵測。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from biaoke_w_neck_verify import (
    FACE_DEFAULT,
    KIND,
    VARIANT_BASELINE,
    VARIANT_NEXT,
    VARIANT_W_NECK,
    detect_w_structure,
    event_w_neck_at,
    gate_compare,
    in_busy_window,
    pivots_hi_lo,
    rates_summary,
    remember_event,
    remember_outcomes,
    run_skeleton,
    score_event,
)


def _mk_db(tmp_path):
    db = tmp_path / "w.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT,
            market_type TEXT,
            asset_type TEXT,
            is_active INTEGER
        );
        CREATE TABLE daily_quotes (
            stock_id TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            stock_name TEXT
        );
        """
    )
    # 合成 W 底：左底 → 峰 → 右底（縮量）→ 站上頸
    day0 = date(2025, 1, 2)
    rows = []
    for i in range(40):
        d = (day0 + timedelta(days=i)).strftime("%Y-%m-%d")
        px = 100.0 + (i % 5) * 0.2
        rows.append(("9993", d, px, px + 1, px - 1, px, 1000.0, "測W"))
    base = 40
    pattern = [
        # drop to left trough
        (98, 99, 95, 96, 2000),
        (96, 97, 90, 91, 5000),  # left trough low=90
        (92, 98, 91, 97, 3000),
        (97, 105, 96, 104, 2500),  # neck peak high~105
        (103, 104, 98, 99, 2200),
        (99, 100, 91, 92, 1800),  # right trough low=91 similar, shrink vol
        (93, 98, 92, 97, 1500),
        (98, 107, 97, 106, 2800),  # stand above neck ~105
        (105, 108, 104, 107, 2000),
        (106, 109, 105, 108, 1800),
        (107, 110, 106, 109, 1700),
        (108, 111, 107, 110, 1600),
        (109, 112, 108, 111, 1500),
    ]
    for j, (o, h, l, c, v) in enumerate(pattern):
        d = (day0 + timedelta(days=base + j)).strftime("%Y-%m-%d")
        rows.append(("9993", d, o, h, l, c, float(v), "測W"))
    for j in range(5):
        d = (day0 + timedelta(days=base + len(pattern) + j)).strftime("%Y-%m-%d")
        rows.append(("9993", d, 110, 112, 109, 111, 1400.0, "測W"))
    con.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.execute(
        "INSERT INTO stock_universe VALUES ('9993','測W','TW','STOCK',1)"
    )
    con.commit()
    con.close()
    return str(db)


def test_busy_window_helper():
    assert in_busy_window(630) is True
    assert in_busy_window(1630) is True
    assert in_busy_window(305) is True
    assert in_busy_window(1000) is False


def test_face_default_false():
    assert FACE_DEFAULT is False
    assert VARIANT_NEXT == "w_neck_v2_vol_confirm"
    assert VARIANT_BASELINE == "break_20high"


def test_pivots_and_w_detect():
    highs = [12, 11, 10, 9, 11, 12, 13, 12, 11, 10, 9.2, 11, 12, 14, 14]
    lows = [11, 10, 9, 8, 9, 10, 11, 10, 9, 8.1, 8, 9, 10, 12, 13]
    vols = [1, 1, 1, 5, 2, 2, 2, 2, 2, 2, 3, 2, 2, 4, 4]
    hi_p, lo_p = pivots_hi_lo(highs, lows, left=2)
    assert lo_p
    struct = detect_w_structure(highs, lows, vols, len(highs) - 1, trough_tol=0.05)
    assert struct is None or struct["neck"] > 0


def test_synthetic_w_stand_roundtrip(tmp_path):
    db = _mk_db(tmp_path)
    from biaoke_w_neck_verify import load_all_bars, scan_stock_history

    bars = load_all_bars(db, "9993")
    assert len(bars) >= 50
    found = None
    for i in range(40, len(bars)):
        ev = event_w_neck_at(bars, i, sid="9993")
        if ev:
            found = ev
            break
    assert found is not None, "synthetic W neck stand-above should fire"
    assert found["variant"] == VARIANT_W_NECK
    assert found["neck"] > 0
    remember_event(db, found)
    outs = score_event(db, found)
    remember_outcomes(db, outs)
    assert len(outs) == 3
    summary = rates_summary(db)
    assert summary["kind"] == KIND
    assert summary["face"] is False
    assert summary["next_variant"] == VARIANT_NEXT

    pack = scan_stock_history(db, "9993", max_events_per_variant=5, persist=True)
    assert pack["n_wrote"] >= 1
    assert VARIANT_BASELINE in (pack.get("counts") or {})


def test_run_skeleton_skips_or_runs(tmp_path, monkeypatch):
    db = _mk_db(tmp_path)
    monkeypatch.setattr(
        "biaoke_w_neck_verify.in_busy_window", lambda hhmm=None: True
    )
    out = run_skeleton(db, stock_ids=["9993"], skip_busy=True)
    assert out.get("skipped") == "busy_window"

    monkeypatch.setattr(
        "biaoke_w_neck_verify.in_busy_window", lambda hhmm=None: False
    )
    out2 = run_skeleton(
        db, stock_ids=["9993"], limit_stocks=1, max_events_per_stock=5, skip_busy=True
    )
    assert out2.get("ok") is True
    assert out2.get("kind") == KIND
    assert out2.get("face") is False


def test_gate_compare_structure():
    tracks = {
        "w_neck:h5": {
            "unique_days": 25,
            "gate_ready": True,
            "cont_up_rate": 0.6,
            "false_break_rate": 0.2,
        },
        "break_20high:h5": {
            "unique_days": 30,
            "gate_ready": True,
            "cont_up_rate": 0.5,
            "false_break_rate": 0.3,
        },
        "w_neck_v2_vol_confirm:h5": {
            "unique_days": 22,
            "gate_ready": True,
            "cont_up_rate": 0.62,
            "false_break_rate": 0.18,
        },
    }
    g = gate_compare(tracks, horizon=5)
    assert g["beats_baseline"] is True
    assert g["face"] is False
    assert g["next_variant"] == VARIANT_NEXT
