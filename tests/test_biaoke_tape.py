# -*- coding: utf-8 -*-
"""捕獲發文立刻對官方日K建檔：點名檔才寫，IET＝IET-KY 4971，盤中未收不當官方收。"""
import inspect
import os
import sqlite3

from biaoke_ingest import _after_ingest_analyze
from biaoke_tape import glance_for, named_pairs, record_events
from biaoke_why import _NAME_SID


def _seed(path: str) -> None:
    conn = sqlite3.connect(path)
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
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
            volume REAL, pct_change REAL, updated_at TEXT,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "3105", "穩懋", 423.0, 451.0, 420.0, 444.0, 13412, 1.48),
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "3653", "健策", 5900.0, 5980.0, 5820.0, 5820.0, 800, -2.1),
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "3081", "聯亞", 2700.0, 2760.0, 2685.0, 2745.0, 1200, 1.2),
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "2455", "全新", 520.0, 538.0, 518.0, 535.0, 3000, 3.88),
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "4971", "IET-KY", 531.0, 559.0, 531.0, 531.0, 1378, -3.45),
    )
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260914", "TWII", 46010.0, 46050.0, 45398.0, 45862.0, 1, 0, "t"),
    )
    conn.commit()
    conn.close()


def test_named_pairs_maps_iet_to_iet_ky():
    pairs = named_pairs("InP：聯亞、全新、IET、穩懋還強")
    sids = {s for s, _n in pairs}
    names = {n for _s, n in pairs}
    assert "3081" in sids
    assert "2455" in sids
    assert "3105" in sids
    assert "4971" in sids
    assert "IET-KY" in names
    assert "IET" not in names
    assert _NAME_SID.get("IET") == "4971"
    assert _NAME_SID.get("IET-KY") == "4971"
    quoted = named_pairs('"健策要跌停了" 沒有，大盤還好')
    assert all(s != "3653" for s, _n in quoted)


def test_record_events_uses_last_official_when_intraday(tmp_path):
    db = str(tmp_path / "tape.db")
    _seed(db)
    n = record_events(
        db,
        [
            {
                "id": "184601742-132",
                "date": "2026-09-15",
                "time": "09:45",
                "kind": "reply",
                "text": "穩懋昨天跌破支撐立刻站回，近期會比台達電強",
            },
            {
                "id": "184601742-166",
                "date": "2026-09-15",
                "time": "10:24",
                "kind": "reply",
                "text": "InP：聯亞、全新、IET、穩懋還強",
            },
            {
                "id": "184601742-177",
                "date": "2026-09-15",
                "time": "10:47",
                "kind": "reply",
                "text": "大盤漲不動反而比較好；怕開牌前作逃命波也就是C-2",
            },
        ],
    )
    assert n >= 3
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT stock_id, bar_date, low, close, volume, note FROM biaoke_tape "
        "WHERE post_id='184601742-132' ORDER BY stock_id"
    ).fetchall()
    by = {r[0]: r for r in rows}
    assert "3105" in by
    assert by["3105"][1] == "20260914"
    assert by["3105"][2] == 420.0
    assert by["3105"][3] == 444.0
    assert by["3105"][4] == 13412
    assert "未收盤" in (by["3105"][5] or "")
    iet = conn.execute(
        "SELECT stock_id, stock_name, bar_date, low, close, volume FROM biaoke_tape "
        "WHERE stock_id='4971'"
    ).fetchone()
    assert iet is not None
    assert iet[1] == "IET-KY"
    assert iet[2] == "20260914"
    assert iet[3] == 531.0
    assert iet[4] == 531.0
    assert iet[5] == 1378
    sids = [
        r[0]
        for r in conn.execute("SELECT DISTINCT stock_id FROM biaoke_tape").fetchall()
    ]
    allowed = set(_NAME_SID.values()) | {"TWII"}
    assert all(s in allowed for s in sids)
    assert "4971" in sids
    tw = conn.execute(
        "SELECT stock_id, bar_date, low, close FROM biaoke_tape "
        "WHERE post_id='184601742-177' AND stock_id='TWII'"
    ).fetchone()
    assert tw is not None
    assert tw[1] == "20260914"
    assert tw[2] == 45398.0
    conn.close()
    g = glance_for(db, "3105")
    assert "即時建檔" in g
    assert "420" in g
    assert "444" in g


def test_ingest_hooks_tape_immediately():
    src = inspect.getsource(_after_ingest_analyze)
    assert "record_events" in src
    ingest_src = inspect.getsource(__import__("biaoke_ingest").ingest_public_posts)
    assert "_after_ingest_analyze" in ingest_src
