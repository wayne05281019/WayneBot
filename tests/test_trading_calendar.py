from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def test_fuse_end_skips_weekend_before_1630():
    from config import fuse_end_date

    # 2026/8/31 一 14:35 → 日曆昨日是 8/30 日 → 應回到 8/28 五
    mid = datetime(2026, 8, 31, 14, 35, tzinfo=ZoneInfo("Asia/Taipei"))
    assert fuse_end_date(mid) == "20260828"


def test_fuse_end_monday_after_close():
    from config import fuse_end_date

    closed = datetime(2026, 8, 31, 16, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    assert fuse_end_date(closed) == "20260831"


def test_latest_complete_skips_weekend_in_db(tmp_path):
    import sqlite3

    from import_health import latest_complete_quote_date

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, market TEXT, date TEXT, close REAL)"
    )
    # 週日假資料（不應當基準日）
    for i in range(900):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'TW', '20260830', 100)",
            (f"T{i:04d}",),
        )
    for i in range(700):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'OTC', '20260830', 100)",
            (f"O{i:04d}",),
        )
    # 週五真資料
    for i in range(900):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'TW', '20260828', 100)",
            (f"A{i:04d}",),
        )
    for i in range(700):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'OTC', '20260828', 100)",
            (f"B{i:04d}",),
        )
    conn.commit()
    conn.close()
    now = datetime(2026, 9, 1, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    assert latest_complete_quote_date(str(db), now=now) == "20260828"


def test_format_trading_date_zh():
    from trading_calendar import format_trading_date_zh

    assert format_trading_date_zh("20260828") == "2026/08/28（五）"
    assert format_trading_date_zh("20260830") == "2026/08/30（日）"


def test_tw_equity_session_open_hours():
    from trading_calendar import is_tw_equity_session, tw_session_phase

    tz = ZoneInfo("Asia/Taipei")
    assert is_tw_equity_session(datetime(2026, 9, 1, 10, 30, tzinfo=tz))
    assert tw_session_phase(datetime(2026, 9, 1, 10, 30, tzinfo=tz)) == "open"
    assert not is_tw_equity_session(datetime(2026, 9, 1, 14, 0, tzinfo=tz))
    assert tw_session_phase(datetime(2026, 9, 1, 14, 0, tzinfo=tz)) == "after"
    assert not is_tw_equity_session(datetime(2026, 9, 1, 8, 30, tzinfo=tz))
    assert tw_session_phase(datetime(2026, 9, 1, 8, 30, tzinfo=tz)) == "pre"
    assert not is_tw_equity_session(datetime(2026, 8, 30, 10, 0, tzinfo=tz))
    assert tw_session_phase(datetime(2026, 8, 30, 10, 0, tzinfo=tz)) == "weekend"


def test_resolve_flow_as_of_prefers_today_after_close(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from money_flow import resolve_flow_as_of

    db = tmp_path / "flow.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, market TEXT, date TEXT, close REAL, "
        "volume INTEGER, pct_change REAL, foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
    )
    for i in range(900):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'TW', '20260901', 100, 1000, 1, 10, 0, 0)",
            (f"T{i:04d}",),
        )
    for i in range(700):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'OTC', '20260901', 50, 500, -1, -5, 0, 0)",
            (f"O{i:04d}",),
        )
    conn.commit()
    conn.close()
    now = datetime(2026, 9, 1, 16, 55, tzinfo=ZoneInfo("Asia/Taipei"))
    as_of, lag = resolve_flow_as_of(str(db), now=now)
    assert as_of == "20260901"
    assert lag is None
