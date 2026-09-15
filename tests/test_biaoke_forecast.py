# -*- coding: utf-8 -*-
"""演算延伸建檔：尚未走完的路徑先存，官方柱到了再對質。"""
import sqlite3
from datetime import date, timedelta

from biaoke_forecast import glance_forecast, record_stock, verify_due


def _wash_rows():
    day = date(2026, 7, 1)
    rows = []
    px = 100.0
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 130, 148, 120, 140, 20000
        elif i == 15:
            o, h, l, c, v = 128, 130, 110, 118, 4000
        elif i == 18:
            o, h, l, c, v = 120, 126, 118, 124, 1800
        elif i == 24:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 30:
            o, h, l, c, v = 128, 132, 124, 126, 1600
        else:
            px = 100 + i * 1.2
            o, h, l, c, v = px, px + 3, px - 3, px + 1, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return rows


def _seed_quotes(db: str, rows) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (
                r["date"],
                r.get("stock_id") or "3035",
                r.get("stock_name") or "智原",
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
            ),
        )
    conn.commit()
    conn.close()


def test_record_stock_pending_then_hits_target(tmp_path):
    rows = _wash_rows()
    db = str(tmp_path / "fc.db")
    _seed_quotes(db, rows)
    rec = record_stock(db, "3035", rows)
    assert rec.get("key") == "wash"
    assert rec.get("as_of") == str(rows[-1]["date"]).replace("-", "")[:8]
    verify_due(db, "3035")
    g0 = glance_forecast(db, "3035")
    assert "還沒走完" in g0
    assert "對得上" not in g0
    last = date(int(rec["as_of"][:4]), int(rec["as_of"][4:6]), int(rec["as_of"][6:8]))
    conn = sqlite3.connect(db)
    for i in range(10):
        d = (last + timedelta(days=i + 1)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (d, "3035", "智原", 140, 150, 138, 149, 1800),
        )
    conn.commit()
    conn.close()
    verify_due(db, "3035")
    g1 = glance_forecast(db, "3035")
    assert "對得上" in g1
    assert "還沒走完" not in g1
