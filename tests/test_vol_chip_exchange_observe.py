# -*- coding: utf-8 -*-
"""近兩周爆量換手觀察：可測、非買訊。"""
from __future__ import annotations

import sqlite3

from vol_chip_exchange_observe import (
    BADGE_ZH,
    NOTE_ZH,
    attach_vol_chip_exchange_observe,
    detect_recent_vol_chip_exchange,
)
from wayne_db import ensure_core_schema


def _ins_bar(conn, *, d, sid, name, vol, hi, lo, o, c, fn=0, tn=0, dn=0):
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d, sid, name, "TW", o, hi, lo, c, int(vol), float(vol), 0.0, float(c), fn, tn, dn),
    )


def _seed(db: str) -> None:
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("9999", "測爆量", "TWSE", "STOCK", "測", "2026-11-13"),
    )
    for i in range(40):
        d = f"2026{1000 + i:04d}"
        vol = 100.0
        hi, lo, o, c = 110.0, 100.0, 102.0, 105.0
        fn = tn = dn = 0
        if i >= 30:
            if i in (32, 35, 38):
                vol = 5000.0 + i
                hi, lo = 120.0, 100.0
                fn, tn, dn = -200, 80, 10
            else:
                vol = 200.0
        _ins_bar(conn, d=d, sid="9999", name="測爆量", vol=vol, hi=hi, lo=lo, o=o, c=c, fn=fn, tn=tn, dn=dn)
    conn.commit()
    conn.close()


def test_detect_hits_synthetic_spike_exchange(tmp_path):
    db = str(tmp_path / "vce.db")
    _seed(db)
    hit = detect_recent_vol_chip_exchange(db, "9999")
    assert hit["hit"] is True
    assert hit["buy_signal"] is False
    assert hit["note_zh"] == NOTE_ZH
    assert hit["n_top"] >= 2
    assert hit["wide_dates"]


def test_attach_puts_badge_not_buy(tmp_path):
    db = str(tmp_path / "vce2.db")
    _seed(db)
    # remember_rows 要當日開高低收＋量齊；用種子最後一日當 as_of
    last = "20261039"
    card = {
        "stock_id": "9999",
        "stock_name": "測爆量",
        "badges": ["整理格局"],
        "close": 105.0,
        "gain_pct": 5.0,
        "latest_date": last,
    }
    attach_vol_chip_exchange_observe(card, db, "9999")
    assert card["vol_chip_exchange"]["hit"] is True
    assert BADGE_ZH in card["badges"]
    assert card["vol_chip_exchange"]["buy_signal"] is False
    from judge_tape import store_path

    import sqlite3 as _sq

    sp = store_path(db)
    conn = _sq.connect(sp)
    n = conn.execute(
        "SELECT COUNT(*) FROM live_judge WHERE kind='vol_chip_exchange' AND sid='9999'"
    ).fetchone()[0]
    conn.close()
    assert n >= 1


def test_no_hit_when_flat_volume(tmp_path):
    db = str(tmp_path / "flat.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("8888", "平量", "TWSE", "STOCK", "測", "2026-11-13"),
    )
    for i in range(40):
        d = f"2026{2000 + i:04d}"
        _ins_bar(conn, d=d, sid="8888", name="平量", vol=100, hi=10.2, lo=9.8, o=10, c=10)
    conn.commit()
    conn.close()
    hit = detect_recent_vol_chip_exchange(db, "8888")
    assert hit["hit"] is False
