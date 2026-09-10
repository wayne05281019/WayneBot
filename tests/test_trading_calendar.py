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
    from trading_calendar import format_md_weekday, format_trading_date_zh

    assert format_trading_date_zh("20260828") == "2026/08/28（五）"
    assert format_trading_date_zh("20260830") == "2026/08/30（日）"
    assert format_md_weekday("20260909") == "9/9（三）"
    assert format_md_weekday("20260910") == "9/10（四）"


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


def test_tw_equity_session_skips_national_holiday():
    from trading_calendar import (
        is_tw_equity_session,
        is_tw_market_holiday,
        is_tw_open_calendar_day,
        tw_session_phase,
    )

    tz = ZoneInfo("Asia/Taipei")
    # 2026/09/25 五 中秋：平日 10:30 也不是盤中
    assert is_tw_market_holiday("20260925")
    assert not is_tw_open_calendar_day("20260925")
    assert not is_tw_equity_session(datetime(2026, 9, 25, 10, 30, tzinfo=tz))
    assert tw_session_phase(datetime(2026, 9, 25, 10, 30, tzinfo=tz)) == "weekend"
    # 春節後開始交易日不是休市
    assert not is_tw_market_holiday("20260223")
    assert is_tw_open_calendar_day("20260223")
    assert is_tw_equity_session(datetime(2026, 2, 23, 10, 0, tzinfo=tz))


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
    assert "休市參考" in week_t
    assert "不是叫你現在買" in week_s


def test_daytrade_closed_title_not_intraday():
    from trading_calendar import daytrade_closed_title, daytrade_closed_message

    weekend = daytrade_closed_title("weekend")
    assert "休市" in weekend
    assert "盤中即時" not in weekend
    assert "盤中即時" not in daytrade_closed_title("pre")
    assert "尚未開盤" in daytrade_closed_title("pre")
    assert "已收盤" in daytrade_closed_title("after")
    msg = daytrade_closed_message("weekend")
    assert msg.startswith("休市。")
    assert "09:00" in msg


def test_daytrade_list_heading_tail_says_what_to_do_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from trading_calendar import daytrade_list_heading, is_tw_tail_session

    open_t, open_s = daytrade_list_heading("open")
    assert "盤中" in open_t
    assert "沒進場" in open_s
    assert "現在不要貴過" in open_s
    tail_t, tail_s = daytrade_list_heading("tail")
    assert "尾盤" in tail_t
    assert "12:45" in tail_s
    assert "不要再進當沖" in tail_s
    assert "隔日沖" in tail_s
    assert "漲到這裡先出" in tail_s
    taipei = ZoneInfo("Asia/Taipei")
    morning = datetime(2026, 9, 10, 10, 0, tzinfo=taipei)
    tail = datetime(2026, 9, 10, 12, 50, tzinfo=taipei)
    after = datetime(2026, 9, 10, 14, 0, tzinfo=taipei)
    assert not is_tw_tail_session(morning)
    assert is_tw_tail_session(tail)
    assert not is_tw_tail_session(after)
