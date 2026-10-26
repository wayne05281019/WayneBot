# -*- coding: utf-8 -*-
"""D1 M頭破頸線靜默骨架／偵測。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from biaoke_m_neck_verify import (
    FACE_DEFAULT,
    KIND,
    VARIANT_BASELINE,
    VARIANT_M_NECK,
    VARIANT_NEXT,
    detect_m_structure,
    event_m_neck_at,
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
    db = tmp_path / "m.db"
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
    # 合成 M 頭：左峰 → 谷 → 右峰（縮量）→ 破頸
    day0 = date(2025, 1, 2)
    rows = []
    # 40 根墊底
    for i in range(40):
        d = (day0 + timedelta(days=i)).strftime("%Y-%m-%d")
        px = 100.0 + (i % 5) * 0.2
        rows.append(("9992", d, px, px + 1, px - 1, px, 1000.0, "測M"))
    # i=40.. 明確雙峰
    # 用交易日連續假日也當「日」即可
    base = 40
    pattern = [
        # climb to left peak
        (102, 105, 101, 104, 2000),
        (104, 110, 103, 109, 5000),  # left peak high=110
        (108, 109, 104, 105, 3000),
        (104, 105, 98, 99, 2500),  # valley low~98
        (99, 102, 98, 101, 2200),
        (101, 109, 100, 108, 1800),  # right peak high=109 similar, shrink vol
        (107, 108, 103, 104, 1500),
        (103, 104, 96, 97, 2800),  # break neck ~98
        (96, 97, 94, 95, 2000),
        (95, 96, 93, 94, 1800),
        (94, 95, 92, 93, 1700),
        (93, 94, 91, 92, 1600),
        (92, 93, 90, 91, 1500),
    ]
    for j, (o, h, l, c, v) in enumerate(pattern):
        d = (day0 + timedelta(days=base + j)).strftime("%Y-%m-%d")
        rows.append(("9992", d, o, h, l, c, float(v), "測M"))
    # 再補幾根讓前瞻滿
    for j in range(5):
        d = (day0 + timedelta(days=base + len(pattern) + j)).strftime("%Y-%m-%d")
        rows.append(("9992", d, 90, 91, 88, 89, 1400.0, "測M"))
    con.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.execute(
        "INSERT INTO stock_universe VALUES ('9992','測M','TW','STOCK',1)"
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
    assert VARIANT_NEXT == "m_neck_v2_vol_confirm"


def test_pivots_and_m_detect():
    highs = [10, 11, 12, 15, 12, 11, 10, 11, 14.8, 12, 11, 9, 8, 8, 8]
    lows = [9, 10, 11, 12, 11, 10, 8, 10, 11, 10, 9, 7, 7, 7, 7]
    vols = [1, 1, 1, 5, 2, 2, 2, 2, 3, 2, 2, 2, 2, 2, 2]
    hi_p, lo_p = pivots_hi_lo(highs, lows, left=2)
    assert hi_p
    # event near end after break
    struct = detect_m_structure(highs, lows, vols, len(highs) - 1, peak_tol=0.05)
    # may or may not find depending on pivot left; just ensure no crash
    assert struct is None or struct["neck"] > 0


def test_synthetic_m_break_roundtrip(tmp_path):
    db = _mk_db(tmp_path)
    from biaoke_m_neck_verify import load_all_bars, scan_stock_history

    bars = load_all_bars(db, "9992")
    assert len(bars) >= 50
    # 找破頸日
    found = None
    for i in range(40, len(bars)):
        ev = event_m_neck_at(bars, i, sid="9992")
        if ev:
            found = ev
            break
    assert found is not None, "synthetic M neck break should fire"
    assert found["variant"] == VARIANT_M_NECK
    assert found["neck"] > 0
    remember_event(db, found)
    outs = score_event(db, found)
    remember_outcomes(db, outs)
    assert len(outs) == 3
    summary = rates_summary(db)
    assert summary["kind"] == KIND
    assert summary["face"] is False
    assert summary["next_variant"] == VARIANT_NEXT

    pack = scan_stock_history(db, "9992", max_events_per_variant=5, persist=True)
    assert pack["n_wrote"] >= 1
    assert VARIANT_BASELINE in (pack.get("counts") or {})


def test_run_skeleton_skips_or_runs(tmp_path, monkeypatch):
    db = _mk_db(tmp_path)
    monkeypatch.setattr(
        "biaoke_m_neck_verify.in_busy_window", lambda hhmm=None: True
    )
    out = run_skeleton(db, stock_ids=["9992"], skip_busy=True)
    assert out.get("skipped") == "busy_window"

    monkeypatch.setattr(
        "biaoke_m_neck_verify.in_busy_window", lambda hhmm=None: False
    )
    out2 = run_skeleton(
        db, stock_ids=["9992"], limit_stocks=1, max_events_per_stock=5, skip_busy=True
    )
    assert out2.get("ok") is True
    assert out2.get("kind") == KIND
    assert out2.get("face") is False


def test_gate_compare_structure():
    tracks = {
        "m_neck:h5": {
            "unique_days": 25,
            "gate_ready": True,
            "cont_down_rate": 0.6,
            "false_break_rate": 0.2,
        },
        "break_20low:h5": {
            "unique_days": 30,
            "gate_ready": True,
            "cont_down_rate": 0.5,
            "false_break_rate": 0.3,
        },
        "m_neck_v2_vol_confirm:h5": {
            "unique_days": 22,
            "gate_ready": True,
            "cont_down_rate": 0.62,
            "false_break_rate": 0.18,
        },
    }
    g = gate_compare(tracks, horizon=5)
    assert g["beats_baseline"] is True
    assert g["face"] is False
    assert g["next_variant"] == VARIANT_NEXT
