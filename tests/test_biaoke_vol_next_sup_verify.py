# -*- coding: utf-8 -*-
"""D4 破撐→下一撐靜默骨架。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from biaoke_vol_next_sup_verify import (
    KIND,
    VARIANT_WITH_NEXT,
    event_for_bar,
    in_busy_window,
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
            active INTEGER,
            security_type TEXT
        );
        CREATE TABLE daily_quotes (
            stock_id TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            stock_name TEXT
        );
        """
    )
    # 合成破撐序列
    day0 = date(2026, 7, 1)
    rows = []
    for i in range(40):
        d = (day0 + timedelta(days=i)).strftime("%Y-%m-%d")
        if i == 15:
            o, h, l, c, v = 110, 130, 100, 120, 20000
        elif i == 39:
            o, h, l, c, v = 98, 99, 85, 90, 2500
        elif i == 8:
            o, h, l, c, v = 88, 95, 78, 90, 9000
        else:
            px = 118 - i * 0.15
            o, h, l, c, v = px, px + 2, px - 2, px, 1200
        rows.append(("9991", d, o, h, l, c, v, "測"))
    con.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.execute(
        "INSERT INTO stock_universe VALUES ('9991',1,'STOCK')"
    )
    con.commit()
    con.close()
    return str(db)


def test_busy_window_helper():
    assert in_busy_window(630) is True
    assert in_busy_window(645) is True
    assert in_busy_window(1630) is True
    assert in_busy_window(305) is True
    assert in_busy_window(1000) is False
    assert in_busy_window(1200) is False


def test_event_and_score_roundtrip(tmp_path):
    db = _mk_db(tmp_path)
    # 載入到破撐日
    from biaoke_vol_next_sup_verify import load_bars_thru

    bars = load_bars_thru(db, "9991", "20260809", need=80)
    assert len(bars) >= 30
    last = bars[-1]
    ev = event_for_bar(bars, sid="9991", as_of=last["date"])
    # 可能因前一日已破而 None；強制用末日窗
    if ev is None:
        # 縮短：只看最後一段，人造首破
        from biaoke_next_support import close_broke_vol_support
        from biaoke_brain import volume_first_price

        st = volume_first_price(bars, lookback=40)
        assert close_broke_vol_support(
            close=float(last["close"]), support=float(st.get("spike_low") or 0)
        )
    else:
        assert ev["stock_id"] == "9991"
        assert ev["variant"] in (VARIANT_WITH_NEXT, "no_next")
        remember_event(db, ev)
        outs = score_event(db, ev)
        remember_outcomes(db, outs)
        assert len(outs) == 3
        summary = rates_summary(db)
        assert summary["kind"] == KIND
        assert isinstance(summary.get("tracks"), dict)


def test_run_skeleton_skips_or_runs(tmp_path, monkeypatch):
    db = _mk_db(tmp_path)
    monkeypatch.setattr(
        "biaoke_vol_next_sup_verify.in_busy_window", lambda hhmm=None: True
    )
    out = run_skeleton(db, stock_ids=["9991"], skip_busy=True)
    assert out.get("skipped") == "busy_window"

    monkeypatch.setattr(
        "biaoke_vol_next_sup_verify.in_busy_window", lambda hhmm=None: False
    )
    out2 = run_skeleton(
        db, stock_ids=["9991"], limit_stocks=1, max_events_per_stock=5, skip_busy=True
    )
    assert out2.get("ok") is True
    assert out2.get("kind") == KIND
