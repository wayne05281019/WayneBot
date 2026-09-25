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
    assert _NAME_SID.get("上詮") == "3363"
    assert _NAME_SID.get("波若威") == "3163"
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
    assert "queue_absorb_events" in src
    assert "record_neuron_events" in src
    assert "ingest_why_events" in src
    assert "verify_due" in src
    assert "record_from_events" in src
    ingest_src = inspect.getsource(__import__("biaoke_ingest").ingest_public_posts)
    assert "_after_ingest_analyze" in ingest_src
    assert "refresh_published_official" in ingest_src


def _chi_bars():
    rows = []
    for d, o, h, l, c, v in [
        ("20260826", 2880, 3155, 2850, 3155, 5242),
        ("20260827", 3305, 3440, 3265, 3340, 6114),
        ("20260828", 3360, 3450, 3320, 3360, 4035),
        ("20260831", 3280, 3425, 3250, 3425, 4468),
        ("20260901", 3435, 3465, 3350, 3410, 3084),
        ("20260902", 3365, 3490, 3280, 3310, 3136),
        ("20260903", 3395, 3525, 3290, 3300, 4418),
        ("20260904", 3465, 3570, 3410, 3570, 4515),
        ("20260907", 3595, 3595, 3410, 3420, 3303),
        ("20260908", 3455, 3455, 3245, 3285, 3350),
        ("20260915", 3265, 3300, 3100, 3115, 3217),
        ("20260917", 3285, 3350, 3175, 3185, 3034),
        ("20260923", 3425, 3590, 3410, 3470, 2649),
    ]:
        rows.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return rows


def test_chi_gate_structure_vs_official_and_forecast(tmp_path):
    from biaoke_forecast import glance_forecast
    from biaoke_tape import structure_vs_spoken

    db = str(tmp_path / "chi.db")
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
    for r in _chi_bars():
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,0)",
            (
                r["date"],
                "3017",
                "奇鋐",
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
            ),
        )
    conn.commit()
    conn.close()
    spoken = "奇鋐已經出現股票噴出前 關前整理量價結構確認完成訊號，下星期就開啟主升段。"
    extra = structure_vs_spoken(spoken, "3017", _chi_bars())
    assert "近窗" in extra
    assert "3595" in extra
    assert "關前" in extra
    assert "不是轉弱K" in extra or "量縮" in extra
    assert "待驗證" in extra
    assert "不是買訊" in extra
    n = record_events(
        db,
        [
            {
                "id": "184931175",
                "date": "2026-09-24",
                "time": "08:57",
                "kind": "post",
                "text": spoken,
            }
        ],
    )
    assert n >= 1
    conn = sqlite3.connect(db)
    note = conn.execute(
        "SELECT note FROM biaoke_tape WHERE post_id='184931175' AND stock_id='3017'"
    ).fetchone()[0]
    conn.close()
    assert "3590" in note
    assert "3470" in note
    assert "2649" in note
    assert "未收盤" in note
    assert "3595" in note
    fc = glance_forecast(db, "3017")
    assert "關前" in fc
    assert "對質" in fc or "還沒" in fc


def test_named_stock_always_gets_window_even_without_keyword():
    from biaoke_tape import structure_vs_spoken, window_vs_bars

    win = window_vs_bars(_chi_bars())
    assert "近窗" in win
    assert "3595" in win
    generic = structure_vs_spoken("今天特別關注這檔", "3017", _chi_bars())
    assert "近窗" in generic
    assert "不是買訊" in generic


def test_c2_c3_without_dapan_word_still_tapes_twii(tmp_path):
    db = str(tmp_path / "t.db")
    _seed(db)
    n = record_events(
        db,
        [
            {
                "id": "184601742-209-1",
                "date": "2026-09-15",
                "time": "14:47",
                "kind": "reply",
                "text": "Yes 如果真的發生C-2 轉 C-3 布局股票該抽出的時候還是要抽出來",
            }
        ],
    )
    assert n >= 1
    conn = sqlite3.connect(db)
    tw = conn.execute(
        "SELECT stock_id FROM biaoke_tape "
        "WHERE post_id='184601742-209-1' AND stock_id='TWII'"
    ).fetchone()
    conn.close()
    assert tw is not None


def test_refresh_published_official_skips_before_close(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_tape import refresh_published_official

    db = str(tmp_path / "t.db")
    _seed(db)
    st = refresh_published_official(
        db, now=datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    assert st.get("skipped") == "session"


def test_chi_sep24_wick_is_not_main_rise():
    from biaoke_tape import structure_vs_spoken

    bars = _chi_bars() + [
        {
            "date": "20260924",
            "open": 3460,
            "high": 3600,
            "low": 3455,
            "close": 3555,
            "volume": 2261,
        }
    ]
    extra = structure_vs_spoken(
        "奇鋐已經出現股票噴出前 關前整理量價結構確認完成訊號，下星期就開啟主升段。",
        "3017",
        bars,
    )
    assert "3595" in extra
    assert "3600" in extra
    assert "3555" in extra
    assert "碰到" in extra
    assert "不是主升" in extra
    assert "待驗證" in extra
    assert "9/24 高碰到≠確認" in extra
    assert "不是保證" in extra
