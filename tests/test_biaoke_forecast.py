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


def _seed_twii(db: str, rows, *, close_last=None):
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
            volume REAL, pct_change REAL
        )
        """
    )
    conn.execute("DELETE FROM index_daily")
    for i, (d, o, h, lo, c) in enumerate(rows):
        if close_last is not None and i == len(rows) - 1:
            c = close_last
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", o, h, lo, c, 1, 0),
        )
    conn.commit()
    conn.close()


def _twii_rows(n=24, start=None, base=45000.0):
    day = start or date(2026, 8, 1)
    rows = []
    px = base
    for i in range(n):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        o, h, lo, c = px, px + 120, px - 80, px + 40
        rows.append((d, o, h, lo, c))
        px += 30
    return rows


def test_twii_snapshot_hides_try_from_glance_and_scores(tmp_path):
    from biaoke_forecast import KIND_TWII_TRY, glance_forecast, snapshot_and_score_twii, verify_due

    db = str(tmp_path / "tw.db")
    rows = _twii_rows()
    _seed_twii(db, rows)
    out = snapshot_and_score_twii(db, rows[-1][0])
    assert out.get("twii") == 1
    assert out.get("try") == 1
    g = glance_forecast(db, "TWII")
    assert "內部試畫" not in g
    assert "1-2-3-4-5" not in g
    assert "演算建檔" in g
    conn = sqlite3.connect(db)
    kinds = {r[0] for r in conn.execute("SELECT kind FROM biaoke_forecast").fetchall()}
    assert "twii" in kinds
    assert KIND_TWII_TRY in kinds
    try_mark = conn.execute(
        "SELECT mark, label FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()
    assert try_mark[0] == "內部試畫"
    assert "不進話筒" in try_mark[1]
    last = date(int(rows[-1][0][:4]), int(rows[-1][0][4:6]), int(rows[-1][0][6:8]))
    for i in range(10):
        d = (last + timedelta(days=i + 1)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            (d, "TWII", 44000, 44200, 43000, 43100, 1, 0),
        )
    conn.commit()
    conn.close()
    verify_due(db, "TWII")
    conn = sqlite3.connect(db)
    try_v = conn.execute(
        "SELECT verdict FROM biaoke_forecast WHERE kind=?",
        (KIND_TWII_TRY,),
    ).fetchone()[0]
    conn.close()
    assert "對得上" in try_v
    assert "還沒走完" not in try_v


def test_twii_snapshot_skips_zero_close(tmp_path):
    from biaoke_forecast import snapshot_and_score_twii

    db = str(tmp_path / "z.db")
    rows = _twii_rows()
    _seed_twii(db, rows, close_last=0)
    out = snapshot_and_score_twii(db, rows[-1][0])
    assert out.get("skipped") == "zero_close"
    assert out.get("twii") == 0
    assert out.get("try") == 0


def test_twii_forecast_hooks_fuse_not_telegram():
    from pathlib import Path

    src = Path("main_runner.py").read_text(encoding="utf-8")
    assert "snapshot_and_score_twii" in src
    i = src.find("def _refresh_twii_forecast_after_close")
    assert i > 0
    chunk = src[i : i + 700]
    assert "send_telegram" not in chunk
    assert "snapshot_and_score_twii" in chunk
    assert src.find("sync_index_daily") < src.find("_refresh_twii_forecast_after_close")
    try_src = Path("biaoke_forecast.py").read_text(encoding="utf-8")
    a = try_src.find("def record_twii_try")
    b = try_src.find("def _judge_stock", a)
    body = try_src[a:b]
    assert "內部試畫" in body
    assert "不進話筒" in body
    assert "1-2-3-4-5" not in body
    assert "第5波" not in body
    from biaoke_wave import format_twii_plain
    import inspect

    cap = inspect.getsource(format_twii_plain)
    assert "內部試畫" not in cap
