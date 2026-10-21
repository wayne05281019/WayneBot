# -*- coding: utf-8 -*-
"""夜盤 as_of：現金 fuse_end 之後仍要吃得到今晨結束的官方夜盤。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pytest

TP = ZoneInfo("Asia/Taipei")


def test_futures_night_query_ceiling_weekday_and_weekend():
    from trading_calendar import futures_night_date_cap, futures_night_query_ceiling

    wed = datetime(2026, 10, 21, 8, 0, tzinfo=TP)
    assert futures_night_date_cap(wed) == "20261021"
    # 現金齊到週二 → 可讀週三標籤的週二夜盤
    assert futures_night_query_ceiling("20261020", wed) == "20261021"
    # 現金略落後仍在現況窗 → 一樣讀到牆鐘夜盤日
    assert futures_night_query_ceiling("20261019", wed) == "20261021"

    mon_morn = datetime(2026, 10, 19, 6, 30, tzinfo=TP)
    assert futures_night_date_cap(mon_morn) == "20261019"
    # 現金齊到週五 → 週一標籤的週五夜盤
    assert futures_night_query_ceiling("20261016", mon_morn) == "20261019"

    before_five = datetime(2026, 10, 21, 4, 59, tzinfo=TP)
    assert futures_night_date_cap(before_five) == "20261020"

    # 歷史 as_of 不漂到活檔
    assert futures_night_query_ceiling("20260901", wed) == "20260901"


def test_load_futures_night_allows_next_open_label(tmp_path):
    import sqlite3

    from taiwan_market import ensure_futures_daily_table, load_futures_night

    db = str(tmp_path / "night.db")
    ensure_futures_daily_table(db)
    conn = sqlite3.connect(db)
    for day, close in (("20261020", 46691.0), ("20261021", 46975.0)):
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?, 'TX', 'night', '202610', 1, 2, 1, ?, ?, 10, 0, 0, 'taifex', 't')
            """,
            (day, close, close),
        )
    conn.commit()
    conn.close()
    now = datetime(2026, 10, 21, 8, 0, tzinfo=TP)
    # 舊行為 date<=現金日會停在 10/20；天花板要讓 10/21 進來。
    got = load_futures_night(db, "20261020", now=now)
    assert got and got["date"] == "20261021" and got["close"] == 46975.0


def test_resolve_futures_night_catches_up_from_history(tmp_path):
    from taiwan_market import ensure_futures_daily_table, load_futures_night, resolve_futures_night

    db = str(tmp_path / "catchup.db")
    ensure_futures_daily_table(db)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=TP)
    hist = {
        "regular": {
            "date": "20261021",
            "session": "regular",
            "contract_month": "202610",
            "open": 1.0,
            "high": 2.0,
            "low": 1.0,
            "close": 2.0,
            "settlement": 2.0,
            "volume": 1,
            "open_interest": 0,
            "pct_change": 0.0,
            "source": "taifex",
        },
        "night": {
            "date": "20261021",
            "session": "night",
            "contract_month": "202610",
            "open": 46490.0,
            "high": 47098.0,
            "low": 46136.0,
            "close": 46975.0,
            "settlement": 46975.0,
            "volume": 30400,
            "open_interest": 0,
            "pct_change": 1.0,
            "source": "taifex",
        },
    }

    with patch("taiwan_market._fetch_taifex_tx_sessions", return_value=hist):
        with patch("taiwan_market._cached_taifex_all_sessions", return_value={}):
            got = resolve_futures_night(db, "20261020", now=now)
    assert got and got["date"] == "20261021" and got["close"] == 46975.0
    stored = load_futures_night(db, "20261020", now=now)
    assert stored and stored["close"] == 46975.0


def test_sync_futures_daily_includes_night_cap(tmp_path):
    from taiwan_market import ensure_futures_daily_table, load_futures_night, sync_futures_daily

    db = str(tmp_path / "sync.db")
    ensure_futures_daily_table(db)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=TP)

    def _fetch(d, *, symbol="TX"):
        if d != "20261021":
            return {}
        return {
            "night": {
                "date": "20261021",
                "session": "night",
                "contract_month": "202610",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "settlement": 105.0,
                "volume": 3,
                "open_interest": 0,
                "pct_change": 0.0,
                "source": "taifex",
                "symbol": symbol,
            }
        }

    with patch("trading_calendar.fuse_end_trading_date", return_value="20261020"):
        with patch("trading_calendar.futures_night_date_cap", return_value="20261021"):
            with patch("taiwan_market._fetch_taifex_tx_sessions", side_effect=_fetch):
                with patch("taiwan_market._fetch_taifex_tx_day", return_value=None):
                    r = sync_futures_daily(db, dates=None, backfill_days=0)
    assert r.get("ok")
    got = load_futures_night(db, "20261020", now=now)
    assert got and got["date"] == "20261021" and got["close"] == 105.0


def test_regular_settlement_falls_back_to_history():
    from market_session_cards import _regular_settlement

    with patch("market_session_cards._regular_settlement_from_openapi", return_value=None):
        with patch(
            "taiwan_market._fetch_taifex_tx_sessions",
            return_value={
                "regular": {
                    "date": "20261020",
                    "contract_month": "202610",
                    "settlement": 46341.0,
                    "close": 46384.0,
                }
            },
        ):
            assert _regular_settlement("20261020", "202610") == 46341.0


def test_fetch_tx_after_hours_prefers_newest_session(monkeypatch):
    """較新 zip 結算補得到時，不准被舊 zip（標題停在更早夜盤）捷足先登。"""
    from market_session_cards import fetch_tx_after_hours_card

    ticks_old = [
        ("20261019", "202610", "150100", 46842.0, 10),
        ("20261019", "202610", "210000", 46700.0, 20),
        ("20261020", "202610", "045957", 46691.0, 12),
    ]
    ticks_new = [
        ("20261020", "202610", "150100", 46490.0, 10),
        ("20261020", "202610", "210000", 46800.0, 20),
        ("20261021", "202610", "045953", 46975.0, 12),
    ]

    class _Resp:
        def __init__(self, status=200, content=b"x" * 2000, text=""):
            self.status_code = status
            self.content = content
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http")

    def _get(url, timeout=0):
        if "futPrevious30DaysSalesData" in url:
            return _Resp(text="Daily_2026_10_21.zip")
        if "Daily_2026_10_21.zip" in url:
            return _Resp(content=b"NEWZIP" + b"0" * 2000)
        if "Daily_2026_10_20.zip" in url:
            return _Resp(content=b"OLDZIP" + b"0" * 2000)
        return _Resp(status=404, content=b"")

    def _parse(text):
        if text.startswith("NEW") or "NEWZIP" in text:
            return list(ticks_new)
        return list(ticks_old)

    monkeypatch.setattr("market_session_cards._SESSION.get", _get)
    monkeypatch.setattr("market_session_cards._read_tick_zip", lambda blob: blob.decode("latin1"))
    monkeypatch.setattr("market_session_cards.parse_tx_night_ticks", _parse)
    monkeypatch.setattr("market_session_cards._regular_settlement", lambda session, month: 46341.0)

    now = datetime(2026, 10, 21, 8, 0, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("missing") is False
    assert card.get("session") == "20261020"
    assert card.get("last") == 46975.0
