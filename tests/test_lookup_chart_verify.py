# -*- coding: utf-8 -*-
"""查股結構／導航精確度靜默對質骨架（不改買訊）。"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from wayne_db import ensure_core_schema


def test_px_rounds_rail_to_twse_tick():
    from biaoke_chart import _fmt_axis_int, _px, _twse_tick

    assert _twse_tick(6320.74) == 5.0
    assert _px(6320.74) == "6320"
    assert _px(4579.56) == "4580"
    assert _px(6115) == "6115"
    assert _px(12.34) == "12.35" or _px(12.34) == "12.3"  # tick 0.05
    assert _fmt_axis_int(0) == "0"
    assert _fmt_axis_int(-0.1) == "0"
    assert _fmt_axis_int(1859) == "1,859"
    assert "-" not in _fmt_axis_int(0)


def test_structure_chart_no_orphan_yan_suan_tick():
    import biaoke_chart as bc

    src = open(bc.__file__, encoding="utf-8").read()
    assert 'labels.append("演算")' not in src
    assert "EVOLUTION_ZONE_LABEL" in src
    assert "axes.unicode_minus" in src
    assert "_fmt_axis_int" in src


def test_structure_levels_match_official_spike(tmp_path):
    from datetime import datetime, timedelta

    from lookup_chart_verify import structure_levels_from_bars, verify_structure_levels

    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    end = datetime(2026, 10, 10)
    # 造 40 根；倒數第二根量大＝爆大量（近窗不含最後一根）
    for i in range(40):
        d = (end - timedelta(days=39 - i)).strftime("%Y%m%d")
        spike = i == 38
        vol = 5000 if spike else 1000
        hi = 110.0 if spike else 105.0
        lo = 90.0 if spike else 95.0
        conn.execute(
            """
            INSERT INTO daily_quotes(
                date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (d, "9999", "測", "TSE", 100.0, hi, lo, 100.0 + (i % 3), vol, 0, 0, 100.0),
        )
    conn.commit()
    conn.close()
    st = verify_structure_levels(db, "9999", "20261010")
    assert st.get("ok") is True
    assert st.get("press_ok") and st.get("hold_ok")
    levels = structure_levels_from_bars(
        [
            {
                "date": f"202610{j:02d}",
                "stock_name": "測",
                "open": 100,
                "high": 110 if j == 9 else 105,
                "low": 90 if j == 9 else 95,
                "close": 101,
                "volume": 5000 if j == 9 else 800,
            }
            for j in range(1, 11)
        ]
    )
    assert levels is not None
    assert abs(levels["press"] - 110) < 0.01
    assert abs(levels["hold"] - 90) < 0.01


def test_gate_never_promotes_buy_signals(tmp_path):
    from lookup_chart_verify import gate_status, optimize_status_one_liner

    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    g = gate_status(db)
    assert g["promote_buy_signals"] is False
    assert g["promote_ready"] is False
    assert "不准" in g["note"] or "尚未" in g["note"] or "收集" in g["note"]
    line = optimize_status_one_liner(db)
    assert "查股" in line
    assert "買訊" in line or "改碼" in line


def test_night_tick_wired_and_catalog_mentions_track():
    import button_silent_verify as bsv
    import judge_tape

    # 與壓撐／大量區／盤中離零同一條 night_tick 掛點
    mod = open(judge_tape.__file__, encoding="utf-8").read()
    assert "lookup_chart_verify" in mod
    assert "lookup_chart_night_tick" in mod
    row = next(r for r in bsv.BUTTON_CATALOG if r.get("btn") == "查股")
    assert "lookup_chart" in row.get("kinds", ())
    assert "lookup_chart_verify" in str(row.get("pipe") or "")
    assert "不准改買訊" in str(row.get("note") or "")


def test_night_tick_empty_lookup_ok(tmp_path):
    from lookup_chart_verify import night_tick

    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    out = night_tick(db, "20261008")
    assert "snap" in out and "gate" in out
    assert out["snap"].get("n", 0) == 0
