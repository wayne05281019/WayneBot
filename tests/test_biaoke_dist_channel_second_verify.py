# -*- coding: utf-8 -*-
"""D6／D7／D9 出貨痕跡／通道／第二段靜默骨架。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from biaoke_dist_channel_second_verify import (
    D6_BREAK,
    D6_DIST,
    D6_NEXT,
    D6_WASH,
    D7_BREAK,
    D7_NEXT,
    D9_NEXT,
    D9_SECOND,
    FACE_DEFAULT,
    KIND_D6,
    KIND_D7,
    KIND_D9,
    classify_path_at,
    find_spike_indices,
    gate_compare_d6,
    gate_compare_d7,
    gate_compare_d9,
    in_busy_window,
    rates_summary,
    remember_event,
    remember_outcomes,
    run_skeleton,
    scan_d6_stock,
    score_event,
)


def _mk_db(tmp_path):
    db = tmp_path / "dcs.db"
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
    day0 = date(2025, 1, 2)
    rows = []
    # 墊底：低量震盪
    for i in range(45):
        d = (day0 + timedelta(days=i)).strftime("%Y-%m-%d")
        px = 100.0 + (i % 5) * 0.3
        rows.append(("9993", d, px, px + 1, px - 1, px, 1000.0 + i, "測出貨"))
    # spike：爆大量日 hi=120 lo=100
    base = 45
    pattern = [
        (110, 120, 100, 115, 20000),  # spike
        (116, 122, 114, 121, 5000),  # 過壓
        (118, 119, 112, 113, 4000),
        (112, 113, 98, 99, 4500),  # 掉回撐下＝出貨確認
        (98, 100, 95, 96, 3000),
        (96, 97, 93, 94, 2800),
        (94, 95, 91, 92, 2600),
        (92, 93, 90, 91, 2500),
        (91, 92, 89, 90, 2400),
    ]
    for j, (o, h, l, c, v) in enumerate(pattern):
        d = (day0 + timedelta(days=base + j)).strftime("%Y-%m-%d")
        rows.append(("9993", d, o, h, l, c, float(v), "測出貨"))
    for j in range(5):
        d = (day0 + timedelta(days=base + len(pattern) + j)).strftime("%Y-%m-%d")
        rows.append(("9993", d, 90, 91, 88, 89, 2000.0, "測出貨"))
    con.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.execute(
        "INSERT INTO stock_universe VALUES ('9993','測出貨','TW','STOCK',1)"
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
    assert D6_NEXT == "dist_v2_over_vol"
    assert D7_NEXT == "desc_break_v2_from_mid"
    assert D9_NEXT == "second_v2_channel"


def test_classify_distribution_path():
    # spike at 0: hi=120 lo=100；其後過壓再掉回
    highs = [120, 122, 119, 113, 100]
    lows = [100, 114, 112, 98, 95]
    closes = [115, 121, 113, 99, 96]
    vols = [20000, 5000, 4000, 4500, 3000]
    info = classify_path_at(highs, lows, closes, vols, 0, within=4)
    assert info["path"] == "distribution"
    assert info["event_i"] == 3


def test_classify_wash_path():
    highs = [120, 115, 118, 125]
    lows = [100, 95, 102, 110]
    closes = [110, 98, 105, 120]  # 破後站回
    vols = [20000, 4000, 3500, 3000]
    info = classify_path_at(highs, lows, closes, vols, 0, within=3)
    assert info["path"] == "wash"


def test_d6_synthetic_scan_and_persist(tmp_path):
    db = _mk_db(tmp_path)
    from biaoke_dist_channel_second_verify import load_all_bars, scan_stock_history

    bars = load_all_bars(db, "9993")
    assert len(bars) >= 50
    vols = [float(b["volume"]) for b in bars]
    spikes = find_spike_indices(vols)
    assert spikes, "synthetic spike should exist"
    evs = scan_d6_stock(bars, "9993")
    dists = [e for e in evs if e.get("variant") == D6_DIST]
    assert dists, "distribution event should fire"
    ev = dists[0]
    remember_event(db, {k: v for k, v in ev.items() if not str(k).startswith("_")})
    outs = score_event(ev, bars)
    remember_outcomes(db, outs)
    assert len(outs) == 3
    summary = rates_summary(db, kind=KIND_D6)
    assert summary["kind"] == KIND_D6
    assert summary["face"] is False
    assert summary["next_variant"] == D6_NEXT

    pack = scan_stock_history(
        db, "9993", max_events_per_variant=5, persist=True, tracks=(KIND_D6,)
    )
    assert pack["n_wrote"] >= 1


def test_run_skeleton_skips_or_runs(tmp_path, monkeypatch):
    db = _mk_db(tmp_path)
    monkeypatch.setattr(
        "biaoke_dist_channel_second_verify.in_busy_window", lambda hhmm=None: True
    )
    out = run_skeleton(db, stock_ids=["9993"], skip_busy=True, tracks=(KIND_D6,))
    assert out.get("skipped") == "busy_window"

    monkeypatch.setattr(
        "biaoke_dist_channel_second_verify.in_busy_window", lambda hhmm=None: False
    )
    out2 = run_skeleton(
        db,
        stock_ids=["9993"],
        limit_stocks=1,
        max_events_per_stock=5,
        skip_busy=True,
        tracks=(KIND_D6,),
    )
    assert out2.get("ok") is True
    assert out2.get("face") is False


def test_gate_compare_structure():
    tracks_d6 = {
        f"{D6_DIST}:h5": {
            "unique_days": 30,
            "gate_ready": True,
            "cont_down_rate": 0.55,
        },
        f"{D6_WASH}:h5": {
            "unique_days": 28,
            "gate_ready": True,
            "cont_down_rate": 0.30,
        },
        f"{D6_BREAK}:h5": {
            "unique_days": 32,
            "gate_ready": True,
            "cont_down_rate": 0.50,
        },
        f"{D6_NEXT}:h5": {
            "unique_days": 25,
            "gate_ready": True,
            "cont_down_rate": 0.58,
        },
    }
    g6 = gate_compare_d6(tracks_d6)
    assert g6["beats_baseline"] is True
    assert g6["face"] is False
    assert g6["next_variant"] == D6_NEXT

    tracks_d7 = {
        f"{D7_BREAK}:h5": {
            "unique_days": 40,
            "gate_ready": True,
            "cont_down_rate": 0.60,
        },
        "vol_break:h5": {
            "unique_days": 45,
            "gate_ready": True,
            "cont_down_rate": 0.50,
        },
        "desc_mid:h5": {
            "unique_days": 40,
            "gate_ready": True,
            "transfer_rate": 0.35,
            "cont_down_rate": 0.45,
        },
        f"{D7_NEXT}:h5": {
            "unique_days": 22,
            "gate_ready": True,
            "cont_down_rate": 0.62,
        },
    }
    g7 = gate_compare_d7(tracks_d7)
    assert g7["beats_baseline"] is True
    assert g7["face"] is False

    tracks_d9 = {
        f"{D9_SECOND}:h5": {
            "unique_days": 25,
            "gate_ready": True,
            "cont_down_rate": 0.65,
            "mean_mae": -0.08,
        },
        "first_break_only:h5": {
            "unique_days": 40,
            "gate_ready": True,
            "cont_down_rate": 0.50,
            "mean_mae": -0.04,
        },
        f"{D9_NEXT}:h5": {
            "unique_days": 20,
            "gate_ready": True,
            "cont_down_rate": 0.66,
            "mean_mae": -0.09,
        },
    }
    g9 = gate_compare_d9(tracks_d9)
    assert g9["beats_baseline"] is True
    assert g9["face"] is False
    assert KIND_D7 and KIND_D9
