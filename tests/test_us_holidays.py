# -*- coding: utf-8 -*-
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from us_holidays import (
    closed_us_session,
    holiday_banner_lines,
    lookup_us_session,
    parse_nyse_calendar,
    previous_trading_day,
    refresh_us_holiday_calendar,
    us_calendar_ymd,
)

NY = ZoneInfo("America/New_York")
FIXTURE = Path(__file__).parent / "fixtures" / "nyse_hours_calendars.html"


def test_official_2026_named_closes():
    labor = lookup_us_session("20260907")
    assert labor["kind"] == "full_close"
    assert labor["zh"] == "勞動節"
    thanks = lookup_us_session("20261126")
    assert thanks["kind"] == "full_close"
    assert thanks["zh"] == "感恩節"
    assert lookup_us_session("20260901")["kind"] == "open"
    assert lookup_us_session("20260905")["kind"] == "weekend"
    assert lookup_us_session("20261127")["kind"] == "early_close"
    assert "提早收盤" in lookup_us_session("20261127")["zh"]


def test_previous_trading_day_skips_weekend_and_holiday():
    assert previous_trading_day("20260907") == "20260904"
    assert previous_trading_day("20261126") == "20261125"
    assert previous_trading_day("20261225") == "20261224"


def test_banner_labor_day_then_prior_close():
    now = datetime(2026, 9, 7, 21, 30, tzinfo=NY)
    closed = closed_us_session(now)
    assert closed is not None
    assert closed["ymd"] == "20260907"
    assert closed["zh"] == "勞動節"
    assert closed["prev_ymd"] == "20260904"
    lines = holiday_banner_lines(closed)
    assert lines[0] == "20260907 美股勞動節休市"
    assert lines[1] == "上一收盤 20260904"


def test_banner_thanksgiving():
    now = datetime(2026, 11, 26, 10, 0, tzinfo=NY)
    closed = closed_us_session(now)
    assert closed["zh"] == "感恩節"
    assert holiday_banner_lines(closed)[0] == "20261126 美股感恩節休市"


def test_open_weekday_has_no_banner():
    now = datetime(2026, 9, 8, 10, 0, tzinfo=NY)
    assert closed_us_session(now) is None
    assert holiday_banner_lines(None) == []


def test_early_close_is_not_full_close():
    now = datetime(2026, 11, 27, 10, 0, tzinfo=NY)
    assert closed_us_session(now) is None


def test_parse_nyse_fixture_matches_seed():
    html = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_nyse_calendar(html)
    full = parsed["full_close"]
    assert full["20260907"]["zh"] == "勞動節"
    assert full["20261126"]["zh"] == "感恩節"
    assert full["20260703"]["zh"] == "獨立紀念日"
    assert "20280101" not in full
    early = parsed["early_close"]
    assert early["20261127"]["zh"] == "感恩節隔日提早收盤"
    assert early["20261224"]["zh"] == "聖誕夜提早收盤"
    assert early["20280703"]["zh"] == "獨立紀念日前日提早收盤"
    assert "20261126" not in early


def test_refresh_writes_sqlite(tmp_path):
    db = str(tmp_path / "h.db")
    html = FIXTURE.read_text(encoding="utf-8")
    out = refresh_us_holiday_calendar(db, html=html)
    assert out["ok"]
    assert out["full"] >= 20
    assert lookup_us_session("20261126", db)["zh"] == "感恩節"


def test_us_calendar_ymd_uses_new_york():
    tw = datetime(2026, 9, 8, 1, 18, tzinfo=ZoneInfo("Asia/Taipei"))
    assert us_calendar_ymd(tw) == "20260907"


def test_market_page_holiday_keeps_prior_close(tmp_path):
    from taiwan_market import format_taiwan_market_page_html
    from tests.test_market_menu_e2e import _seed_market_db
    from us_overnight import save_us_overnight

    db = str(tmp_path / "m.db")
    as_of = _seed_market_db(db)
    save_us_overnight(
        db,
        as_of,
        {
            "ok": True,
            "regime": "ok",
            "us_session": "20260904",
            "us_phase": "overnight",
            "vix": 14.0,
            "vix_pct": -1.0,
            "dji_pct": 0.4,
            "dji_chg": 80.0,
            "spx_pct": 0.3,
            "spx_chg": 12.0,
            "ixic_pct": 0.5,
            "ixic_chg": 90.0,
            "sox_pct": 0.2,
            "sox_chg": 5.0,
        },
    )
    html = format_taiwan_market_page_html(
        db, as_of, now=datetime(2026, 9, 7, 22, 0, tzinfo=NY)
    )
    assert "20260907 美股勞動節休市" in html
    assert "上一收盤 20260904" in html
    assert "上一收盤日該看" in html
    assert "上一收盤指數" in html
    assert "美股時段" not in html
    assert "前一晚該看" not in html
    assert "道瓊" in html
    assert "+0.40%" in html
    assert "現金盤中" not in html
    open_html = format_taiwan_market_page_html(
        db, as_of, now=datetime(2026, 9, 8, 10, 0, tzinfo=NY)
    )
    assert "勞動節休市" not in open_html
    assert "指數收盤" in open_html


def test_format_us_html_holiday_then_prior_tape():
    from us_overnight import format_us_html

    snap = {
        "regime": "ok",
        "vix": 15.0,
        "dji_pct": 0.1,
        "dji_chg": 10.0,
        "spx_pct": 0.0,
        "spx_chg": 0.0,
        "ixic_pct": 0.2,
        "ixic_chg": 20.0,
        "sox_pct": -0.5,
        "sox_chg": -5.0,
        "us_phase": "overnight",
        "us_session": "20260904",
    }
    html = format_us_html(snap, now=datetime(2026, 9, 7, 21, 0, tzinfo=NY))
    assert "20260907 美股勞動節休市" in html
    assert "上一收盤 20260904" in html
    assert "上一收盤指數" in html
    assert "+0.10%（+10.00點）" in html
    assert "美股交易日" not in html
    assert "美股時段" not in html
    open_html = format_us_html(snap, now=datetime(2026, 9, 1, 17, 0, tzinfo=NY))
    assert "勞動節休市" not in open_html
    assert "美股交易日" in open_html


def test_tape_phase_closed_on_labor_day():
    from us_overnight import us_tape_phase

    assert us_tape_phase(datetime(2026, 9, 7, 11, 30, tzinfo=NY)) == "overnight"
    assert us_tape_phase(datetime(2026, 9, 1, 11, 30, tzinfo=NY)) == "regular"
    assert us_tape_phase(datetime(2026, 11, 27, 14, 0, tzinfo=NY)) == "post"
