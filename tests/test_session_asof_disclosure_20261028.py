# -*- coding: utf-8 -*-
"""時段／資料日告知：按下台北時用詞（純文字；不渲圖）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TAIPEI = ZoneInfo("Asia/Taipei")


def _open_day_1513() -> datetime:
    return datetime(2026, 10, 28, 15, 13, tzinfo=TAIPEI)


def test_tw_cash_and_pre_fuse_windows():
    from trading_calendar import (
        speak_when_for_press,
        tw_cash_session_open,
        tw_post_cash_pre_fuse,
    )

    assert tw_cash_session_open(datetime(2026, 10, 28, 10, 0, tzinfo=TAIPEI))
    assert not tw_cash_session_open(datetime(2026, 10, 28, 13, 30, tzinfo=TAIPEI))
    assert tw_post_cash_pre_fuse(_open_day_1513())
    assert not tw_post_cash_pre_fuse(datetime(2026, 10, 28, 16, 30, tzinfo=TAIPEI))
    assert speak_when_for_press(_open_day_1513()) == "after"
    assert speak_when_for_press(datetime(2026, 10, 28, 10, 0, tzinfo=TAIPEI)) == "open"
    assert speak_when_for_press(datetime(2026, 10, 28, 8, 30, tzinfo=TAIPEI)) == "pre"


def test_fear_plain_speak_when_defaults_pre():
    from foreign_sell_display import EnvObserveStatus, _fear_plain

    st = EnvObserveStatus(
        as_of="20261028",
        fear_lit=False,
        fear_evaluable=True,
        fear_votes=0,
        fear_lead_sync="",
        fear_skip="",
        confirm_n=0,
        confirm_tags=[],
        calm_lit=False,
        calm_note="",
        buy_signal=False,
    )
    assert _fear_plain(st) == "開盤前，市場不怕。"
    assert _fear_plain(st, speak_when="after") == "收盤後，市場不怕。"
    assert _fear_plain(st, speak_when="open") == "盤中，市場不怕。"


def test_resolve_flow_as_of_discloses_pre_fuse(tmp_path):
    from money_flow import resolve_flow_as_of

    db = tmp_path / "flow.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, market TEXT, date TEXT, close REAL, "
        "volume INTEGER, pct_change REAL, foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
    )
    for i in range(900):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'TW', '20261027', 100, 1000, 1, 10, 0, 0)",
            (f"T{i:04d}",),
        )
    for i in range(700):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'OTC', '20261027', 50, 500, -1, -5, 0, 0)",
            (f"O{i:04d}",),
        )
    conn.commit()
    conn.close()
    as_of, lag = resolve_flow_as_of(str(db), now=_open_day_1513())
    assert as_of == "20261027"
    assert lag is not None
    assert "16:30" in lag
    assert "不是當下盤後定稿" in lag
    assert "2026/10/27" in lag


def test_dongzhu_query_stamp_keeps_press_date():
    from biaoke_field_scan import (
        _dongzhu_post_cash_pre_fuse_note,
        _dongzhu_query_stamp_line,
    )

    stamp = _dongzhu_query_stamp_line("20261027", now=_open_day_1513())
    assert stamp.startswith("查詢 ")
    assert "2026/10/28" in stamp
    assert "15:13" in stamp
    assert "已收盤" in stamp
    assert "13:30收盤" not in stamp
    note = _dongzhu_post_cash_pre_fuse_note("20261027", now=_open_day_1513())
    assert "今日盤後資料未齊" in note
    assert "16:30" in note


def test_market_page_after_cash_not_intraday_label(tmp_path, monkeypatch):
    from taiwan_market import format_taiwan_market_page_html

    db = str(tmp_path / "mkt.db")
    sqlite3.connect(db).close()
    monkeypatch.setattr(
        "taiwan_market.resolve_market_as_of", lambda *_a, **_k: "20261027"
    )
    snap = {
        "ok": True,
        "as_of": "20261027",
        "close": 46000.0,
        "chg1_pct": 1.0,
        "open": 45500.0,
        "high": 46200.0,
        "low": 45400.0,
        "prev_close": 45000.0,
    }
    html = format_taiwan_market_page_html(
        db,
        live={"close": 47035.0, "pct_change": 2.0, "update_time": "13:30:00"},
        snap=snap,
        now=_open_day_1513(),
    )
    head = html.split("環境觀察")[0]
    assert "盤中" not in head
    assert "已收盤" in head
    assert "不是當下盤後定稿" in head
    assert "開盤前，市場" not in html
    assert "收盤後，" in html
