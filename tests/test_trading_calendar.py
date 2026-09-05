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


def test_resolve_flow_as_of_uses_today_after_close_when_db_has_cap(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from money_flow import resolve_flow_as_of

    db = tmp_path / "flow2.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, market TEXT, date TEXT, close REAL, "
        "volume INTEGER, pct_change REAL, foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
    )
    for day in ("20260901", "20260902"):
        for i in range(900):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'TW', ?, 100, 1000, 1, 10, 0, 0)",
                (f"T{i:04d}", day),
            )
        for i in range(700):
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?, 'OTC', ?, 50, 500, -1, -5, 0, 0)",
                (f"O{i:04d}", day),
            )
    conn.commit()
    conn.close()
    now = datetime(2026, 9, 2, 17, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    as_of, lag = resolve_flow_as_of(str(db), now=now)
    assert as_of == "20260902"
    assert lag is None


def test_resolve_flow_as_of_warns_when_cap_missing_after_close(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from money_flow import resolve_flow_as_of

    db = tmp_path / "flow3.db"
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
    now = datetime(2026, 9, 2, 17, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    as_of, lag = resolve_flow_as_of(str(db), now=now)
    assert as_of == "20260901"
    assert lag is not None
    assert "2026/09/02" in lag
    assert "2026/09/01" in lag


def test_sector_rotation_title_uses_resolved_not_stale_as_of(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from import_health import MIN_TWO, MIN_TW
    from money_flow import format_sector_rotation_html
    from wayne_db import ensure_core_schema

    db = tmp_path / "rot.db"
    ensure_core_schema(str(db))
    conn = sqlite3.connect(db)
    for day in ("20260901", "20260902"):
        for i in range(MIN_TW):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
                (day, f"{1000+i:04d}", "TW", "TW"),
            )
        for i in range(MIN_TWO):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
                (day, f"{6000+i:04d}", "上櫃", "TWO"),
            )
    conn.commit()
    conn.close()
    now = datetime(2026, 9, 2, 17, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    html = format_sector_rotation_html(str(db), "20260901", now=now)
    assert "2026/09/02（三）" in html


def test_overnight_list_heading_not_intraday_after_hours():
    from trading_calendar import overnight_list_heading

    pre_t, pre_s = overnight_list_heading("pre")
    assert "開盤前預覽" in pre_t
    assert "盤中即時" not in pre_t
    after_t, after_s = overnight_list_heading("after")
    assert "收盤後參考" in after_t
    assert "不是叫你再買" in after_s
    week_t, week_s = overnight_list_heading("weekend")
    assert "假日參考" in week_t
    assert "不是叫你現在買" in week_s


def test_daytrade_closed_title_not_intraday():
    from trading_calendar import daytrade_closed_title, daytrade_closed_message

    weekend = daytrade_closed_title("weekend")
    assert "假日" in weekend
    assert "盤中即時" not in weekend
    assert "盤中即時" not in daytrade_closed_title("pre")
    assert "尚未開盤" in daytrade_closed_title("pre")
    assert "已收盤" in daytrade_closed_title("after")
    msg = daytrade_closed_message("weekend")
    assert msg.startswith("假日。")
    assert "09:00" in msg
