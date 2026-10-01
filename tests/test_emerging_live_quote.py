# -*- coding: utf-8 -*-
"""興櫃查股現價：櫃買 OpenAPI LatestPrice（今日列）→ Yahoo .TWO；15:00 收盤標籤。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from live_quote import (
    board_session_label,
    fetch_emerging_live_quote,
    fetch_emerging_tpex_quote,
    fetch_lookup_quote,
    format_quote_clock_line,
    is_emerging_market,
    lookup_price_label,
)


def test_is_emerging_market_codes():
    assert is_emerging_market("EM")
    assert is_emerging_market("興櫃")
    assert is_emerging_market("", db_hit={"market": "EM"})
    assert not is_emerging_market("TW")
    assert not is_emerging_market("TWO")


def test_board_session_label_emerging_1500():
    assert board_session_label("14:59:00", emerging=True) == "盤中"
    assert board_session_label("15:00:00", emerging=True) == "收盤"
    assert board_session_label("13:30:00", emerging=False) == "收盤"
    assert board_session_label("13:29:00", emerging=False) == "盤中"


def test_lookup_price_label_emerging_session():
    tz = ZoneInfo("Asia/Taipei")
    rt = {"source": "yahoo", "update_time": "14:20:00", "close": 100.0}
    mid = datetime(2026, 9, 4, 14, 20, tzinfo=tz)
    after = datetime(2026, 9, 4, 15, 5, tzinfo=tz)
    assert lookup_price_label(rt, emerging=True, now=mid) == "現價"
    assert lookup_price_label(rt, emerging=True, now=after) == "收盤"
    assert lookup_price_label({"source": "yahoo"}, emerging=False, now=mid) == "收盤"


def test_format_quote_clock_line_emerging():
    line = format_quote_clock_line("14:20:11", source="yahoo", emerging=True)
    assert "盤中" in line and "奇摩（興櫃）" in line
    line2 = format_quote_clock_line("15:01:00", source="tpex_esb", emerging=True)
    assert "收盤" in line2 and "櫃買興櫃" in line2


def test_fetch_emerging_tpex_quote_only_today(monkeypatch):
    monkeypatch.setattr(
        "live_quote._load_tpex_esb_map",
        lambda: {
            "3595": {
                "Date": "1150930",
                "Time": "143015",
                "SecuritiesCompanyCode": "3595",
                "CompanyName": "山太士",
                "PreviousAveragePrice": "1493.35",
                "Highest": "1555",
                "Lowest": "1430",
                "Average": "1459.45",
                "LatestPrice": "1440",
                "TransactionVolume": "450806",
            }
        },
    )
    monkeypatch.setattr("live_quote.taipei_today_str", lambda: "20261001")
    assert fetch_emerging_tpex_quote("3595") is None

    monkeypatch.setattr("live_quote.taipei_today_str", lambda: "20260930")
    rt = fetch_emerging_tpex_quote("3595")
    assert rt is not None
    assert rt["source"] == "tpex_esb"
    assert float(rt["close"]) == 1440.0
    assert rt["update_time"] == "14:30:15"


def test_fetch_lookup_quote_emerging_skips_mis(monkeypatch):
    calls = {"mis": 0}

    def _boom(*a, **k):
        calls["mis"] += 1
        raise AssertionError("興櫃不准打 MIS")

    monkeypatch.setattr("live_quote.fetch_mis_quote", _boom)
    monkeypatch.setattr(
        "live_quote.fetch_emerging_tpex_quote",
        lambda sid: None,
    )
    monkeypatch.setattr(
        "live_quote.fetch_yahoo_tw_quote",
        lambda sid, db=None: {
            "stock_id": sid,
            "close": 1375.0,
            "pct_change": -4.8,
            "change": -70.0,
            "yesterday_close": 1445.0,
            "update_time": "13:28:39",
            "volume": 500,
            "open": 1425.0,
            "high": 1440.0,
            "low": 1345.0,
            "is_realtime": True,
            "source": "yahoo",
        },
    )
    monkeypatch.setattr("live_quote.is_lookup_trading_day", lambda now=None: True)
    rt = fetch_lookup_quote("3595", "EM", db_hit={"market": "EM", "close": 1459.45})
    assert calls["mis"] == 0
    assert rt and float(rt["close"]) == 1375.0
    assert rt["source"] == "yahoo"


def test_fetch_emerging_live_prefers_tpex_today(monkeypatch):
    monkeypatch.setattr(
        "live_quote.fetch_emerging_tpex_quote",
        lambda sid: {
            "stock_id": sid,
            "close": 1400.0,
            "source": "tpex_esb",
            "yesterday_close": 1450.0,
            "pct_change": -3.45,
            "change": -50.0,
            "update_time": "14:10:00",
            "volume": 10,
            "open": 1450.0,
            "high": 1460.0,
            "low": 1390.0,
            "is_realtime": True,
        },
    )
    monkeypatch.setattr(
        "live_quote.fetch_yahoo_tw_quote",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該走 Yahoo")),
    )
    rt = fetch_emerging_live_quote("3595")
    assert rt and rt["source"] == "tpex_esb"
    assert float(rt["close"]) == 1400.0


def test_navigator_merges_emerging_live(monkeypatch, tmp_path):
    """興櫃決策卡盤中可合併現價，13:30～15:00 仍標現價。"""
    import sqlite3

    from emerging_quotes import ensure_emerging_table
    from wayne_db import ensure_core_schema
    from wayne_navigator import NavigatorEngine, session_price_label

    db = str(tmp_path / "em.db")
    ensure_core_schema(db)
    ensure_emerging_table(db)
    conn = sqlite3.connect(db)
    rows = []
    # 足夠長的官方日均價序列
    base = 20260801
    for i in range(30):
        d = str(base + i)
        if len(d) != 8:
            continue
        px = 100.0 + i
        rows.append((d, "3595", "山太士", "EM", px, px + 1, px - 1, px, 10.0, px * 10, 0.0, px, "csv"))
    # 用連續假日字串不夠；改用明確交易日列
    conn.execute("DELETE FROM emerging_quotes")
    days = [
        "20260804",
        "20260805",
        "20260806",
        "20260807",
        "20260808",
        "20260811",
        "20260812",
        "20260813",
        "20260814",
        "20260815",
        "20260818",
        "20260819",
        "20260820",
        "20260821",
        "20260822",
        "20260825",
        "20260826",
        "20260827",
        "20260828",
        "20260829",
        "20260901",
        "20260902",
        "20260903",
        "20260904",
        "20260905",
        "20260908",
        "20260909",
        "20260910",
        "20260911",
        "20260912",
    ]
    for i, d in enumerate(days):
        px = 100.0 + i
        conn.execute(
            """
            INSERT INTO emerging_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (d, "3595", "山太士", "EM", px, px + 1, px - 1, px, 10.0, px * 10, 0.5, px, "csv"),
        )
    conn.commit()
    conn.close()

    live = {
        "stock_id": "3595",
        "open": 130.0,
        "high": 135.0,
        "low": 128.0,
        "close": 132.0,
        "volume": 20,
        "pct_change": 2.0,
        "change": 2.5,
        "yesterday_close": 129.5,
        "update_time": "14:20:00",
        "is_realtime": True,
        "source": "yahoo",
    }
    monkeypatch.setattr("live_quote.is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr("live_quote.taipei_today_str", lambda: "20260915")
    monkeypatch.setattr(
        "decision_card_signals.taipei_now",
        lambda *a, **k: datetime(2026, 9, 15, 14, 20, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    monkeypatch.setattr(
        "config.taipei_now",
        lambda: datetime(2026, 9, 15, 14, 20, tzinfo=ZoneInfo("Asia/Taipei")),
    )

    engine = NavigatorEngine(db)
    card = engine.get_decision_card("3595", merge_live=True, live_quote=live)
    assert not card.get("error"), card
    assert card.get("quote_source") == "emerging_quotes"
    assert card.get("is_live") is True
    assert float(card.get("close") or 0) == 132.0
    assert session_price_label(card) == "現價"
    assert card.get("live_source") == "yahoo"
