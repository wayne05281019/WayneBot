# -*- coding: utf-8 -*-
from datetime import datetime
from zoneinfo import ZoneInfo

from tw_holidays import (
    closed_tw_session,
    holiday_banner_lines,
    lookup_tw_session,
    parse_dgpa_nds,
    parse_twse_holiday_rows,
    previous_tw_trading_day,
    refresh_tw_holiday_calendar,
    refresh_tw_typhoon_halt,
    roc_to_ymd,
    short_holiday_zh,
)

TW = ZoneInfo("Asia/Taipei")

_DGPA_NONE = """
<div class="Header_YMD">115年 9月 8日 天然災害停止上班及上課情形</div>
更新時間：2026/09/08 07:44:17
<TABLE id="Table"><TR><TD headers='city_Name' colspan='2'><h2>無停班停課訊息。</h2></TD></TR></TABLE>
"""

_DGPA_TAIPEI_FULL = """
<div class="Header_YMD">115年 7月 23日 天然災害停止上班及上課情形</div>
更新時間：2026/07/22 21:40:00
<TABLE id="Table">
<TR><TD headers='city_Name'>臺北市</TD><TD>停止上班、停止上課</TD></TR>
<TR><TD headers='city_Name'>新北市</TD><TD>停止上班、停止上課</TD></TR>
</TABLE>
"""

_DGPA_TAIPEI_TYPHOON = """
<div class="Header_YMD">115年 9月 22日 天然災害停止上班及上課情形</div>
<TABLE id="Table">
<TR><TD headers='city_Name'>台北市</TD><TD>因颱風停止上班及上課</TD></TR>
</TABLE>
"""

_DGPA_TAIPEI_PM = """
<div class="Header_YMD">115年 7月 23日 天然災害停止上班及上課情形</div>
<TABLE id="Table">
<TR><TD headers='city_Name'>臺北市</TD><TD>下午停止上班及上課</TD></TR>
</TABLE>
"""

_TWSE_ROWS = [
    {"Name": "勞動節", "Date": "1150501", "Description": "依規定放假1日。"},
    {"Name": "中秋節", "Date": "1150925", "Description": "依規定放假1日。"},
    {"Name": "農曆春節後開始交易日", "Date": "1150223", "Description": "農曆春節後開始交易。"},
    {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212", "Description": ""},
    {"Name": "農曆除夕及春節", "Date": "1150216", "Description": "依規定放假5日。"},
]


def test_roc_to_ymd_and_short_names():
    assert roc_to_ymd("1150925") == "20260925"
    assert short_holiday_zh("中秋節") == "中秋節"
    assert short_holiday_zh("市場無交易，僅辦理結算交割作業") == "僅結算"
    assert short_holiday_zh("中華民國開國紀念日") == "元旦"


def test_seed_named_closes():
    mid_autumn = lookup_tw_session("20260925")
    assert mid_autumn["kind"] == "full_close"
    assert mid_autumn["zh"] == "中秋節"
    labor = lookup_tw_session("20260501")
    assert labor["kind"] == "full_close"
    assert labor["zh"] == "勞動節"
    assert lookup_tw_session("20260901")["kind"] == "open"
    assert lookup_tw_session("20260905")["kind"] == "weekend"
    assert lookup_tw_session("20260223")["kind"] == "open"


def test_previous_skips_holiday_week():
    assert previous_tw_trading_day("20260925") == "20260924"
    assert previous_tw_trading_day("20260216") == "20260211"


def test_banner_mid_autumn():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=TW)
    closed = closed_tw_session(now)
    assert closed["ymd"] == "20260925"
    lines = holiday_banner_lines(closed)
    assert lines[0] == "20260925 台股中秋節休市"
    assert lines[1] == "上一收盤 20260924"


def test_parse_twse_skips_open_days():
    parsed = parse_twse_holiday_rows(_TWSE_ROWS)
    assert parsed["20260501"]["zh"] == "勞動節"
    assert parsed["20260925"]["zh"] == "中秋節"
    assert parsed["20260212"]["zh"] == "僅結算"
    assert parsed["20260216"]["zh"] == "春節"
    assert "20260223" not in parsed


def test_fetch_dgpa_prefers_utf8_over_latin1(monkeypatch):
    class _Resp:
        content = (
            "<div class='Header_YMD'>115年 9月 8日 天然災害停止上班及上課情形</div>"
            "更新時間：2026/09/08 07:59:16"
            "<h2>無停班停課訊息。</h2>"
        ).encode("utf-8")
        apparent_encoding = "ISO-8859-1"
        def raise_for_status(self):
            return None

    import tw_holidays

    monkeypatch.setattr(tw_holidays.requests, "get", lambda *a, **k: _Resp())
    html = tw_holidays.fetch_dgpa_nds_html()
    out = parse_dgpa_nds(html)
    assert out["ymd"] == "20260908"
    assert out["halt"] is False


def test_dgpa_none_is_open():
    out = parse_dgpa_nds(_DGPA_NONE)
    assert out["ymd"] == "20260908"
    assert out["halt"] is False


def test_dgpa_taipei_full_is_halt():
    out = parse_dgpa_nds(_DGPA_TAIPEI_FULL)
    assert out["ymd"] == "20260723"
    assert out["halt"] is True
    assert out["zh"] == "北市停班"


def test_dgpa_taipei_typhoon_wording():
    out = parse_dgpa_nds(_DGPA_TAIPEI_TYPHOON)
    assert out["halt"] is True
    assert out["zh"] == "颱風停班"


def test_dgpa_afternoon_only_not_halt():
    out = parse_dgpa_nds(_DGPA_TAIPEI_PM)
    assert out["halt"] is False


def test_refresh_writes_calendar_and_typhoon(tmp_path):
    db = str(tmp_path / "h.db")
    cal = refresh_tw_holiday_calendar(db, rows=_TWSE_ROWS)
    assert cal["ok"]
    assert lookup_tw_session("20260925", db)["zh"] == "中秋節"
    typh = refresh_tw_typhoon_halt(db, html=_DGPA_TAIPEI_FULL)
    assert typh["halt"] is True
    assert lookup_tw_session("20260723", db)["kind"] == "full_close"
    assert lookup_tw_session("20260723", db)["zh"] == "北市停班"
    none = refresh_tw_typhoon_halt(db, html=_DGPA_NONE)
    assert none["halt"] is False
    assert lookup_tw_session("20260723", db)["kind"] == "full_close"


def test_dgpa_none_clears_same_day_halt(tmp_path):
    db = str(tmp_path / "h.db")
    refresh_tw_typhoon_halt(db, html=_DGPA_TAIPEI_FULL)
    assert lookup_tw_session("20260723", db)["kind"] == "full_close"
    none_same = """
<div class="Header_YMD">115年 7月 23日 天然災害停止上班及上課情形</div>
更新時間：2026/07/23 07:00:00
<TABLE id="Table"><TR><TD headers='city_Name' colspan='2'><h2>無停班停課訊息。</h2></TD></TR></TABLE>
"""
    out = refresh_tw_typhoon_halt(db, html=none_same)
    assert out["halt"] is False
    assert lookup_tw_session("20260723", db)["kind"] == "open"


def test_outlook_shows_tw_holiday_not_open_high(tmp_path):
    from taiwan_market import format_screen_market_outlook_html

    html = format_screen_market_outlook_html(
        str(tmp_path / "o.db"),
        "20260924",
        snap={
            "ok": True,
            "as_of": "20260924",
            "close": 26500.0,
            "chg1_pct": 0.4,
            "vs_ma20_pct": 1.2,
            "regime": "neutral",
            "falling_risk": 10,
        },
        us_snap={"ok": True, "regime": "ok", "ixic_pct": 0.8, "sox_pct": 0.4, "vix": 14.0},
        now=datetime(2026, 9, 25, 6, 30, tzinfo=TW),
    )
    assert "20260925 台股中秋節休市" in html
    assert "上一收盤 20260924" in html
    assert "台股今天休市" in html
    assert "台股容易開高" not in html
    assert "電子鏈夜盤" not in html


def test_outlook_shows_us_holiday_banner():
    from taiwan_market import format_screen_market_outlook_html

    html = format_screen_market_outlook_html(
        ":memory:",
        "20260904",
        snap={
            "ok": True,
            "as_of": "20260904",
            "close": 26500.0,
            "chg1_pct": 0.4,
            "vs_ma20_pct": 1.2,
            "regime": "neutral",
            "falling_risk": 10,
        },
        us_snap={"ok": True, "regime": "ok", "ixic_pct": 0.8, "sox_pct": 0.4, "vix": 14.0},
        now=datetime(2026, 9, 7, 21, 0, tzinfo=TW),
    )
    assert "20260907 美股勞動節休市" in html
    assert "上一收盤 20260904" in html
    assert "電子鏈夜盤" not in html


def test_line_share_head_keeps_tw_holiday():
    from screening_engine import format_line_share_packs

    packs = format_line_share_packs(
        {"leave_zero": [], "golden_buy": []},
        "20260924",
        morning=True,
        now=datetime(2026, 9, 25, 8, 0, tzinfo=TW),
    )
    text = "\n".join(p["text"] for p in packs)
    assert "20260925 台股中秋節休市" in text
    assert "上一收盤 20260924" in text


def test_fuse_end_skips_national_holiday():
    from config import fuse_end_date

    closed = datetime(2026, 9, 25, 17, 0, tzinfo=TW)
    assert fuse_end_date(closed) == "20260924"


def test_market_page_tw_holiday_banner(tmp_path):
    from taiwan_market import format_taiwan_market_page_html
    from tests.test_market_menu_e2e import _seed_market_db

    db = str(tmp_path / "m.db")
    as_of = _seed_market_db(db)
    html = format_taiwan_market_page_html(
        db, as_of, now=datetime(2026, 9, 25, 10, 0, tzinfo=TW)
    )
    assert "20260925 台股中秋節休市" in html
    assert "上一收盤 20260924" in html
    assert "台股休市，庫內上一收盤" in html
    open_html = format_taiwan_market_page_html(
        db, as_of, now=datetime(2026, 9, 1, 10, 0, tzinfo=TW)
    )
    assert "中秋節休市" not in open_html


def test_market_page_us_regular_heading_when_tw_open(tmp_path):
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
            "us_session": "20260901",
            "us_phase": "regular",
            "vix": 14.0,
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
        db, as_of, now=datetime(2026, 9, 1, 22, 0, tzinfo=TW)
    )
    assert "美股盤中該看" in html
    assert "上一收盤日該看" not in html
