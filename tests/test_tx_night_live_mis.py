# -*- coding: utf-8 -*-
"""台指電子盤：夜盤窗優先 MIS 即時，不准再用上週 zip 冒充現況。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TP = ZoneInfo("Asia/Taipei")


def test_wall_in_tx_night_hours():
    from market_session_cards import _evening_start_ymd, _wall_in_tx_night

    assert _wall_in_tx_night(datetime(2026, 11, 2, 15, 0, tzinfo=TP))
    assert _wall_in_tx_night(datetime(2026, 11, 3, 0, 15, tzinfo=TP))
    assert _wall_in_tx_night(datetime(2026, 11, 3, 4, 59, tzinfo=TP))
    assert not _wall_in_tx_night(datetime(2026, 11, 3, 5, 0, tzinfo=TP))
    assert not _wall_in_tx_night(datetime(2026, 11, 2, 14, 59, tzinfo=TP))
    assert _evening_start_ymd(datetime(2026, 11, 3, 0, 15, tzinfo=TP)) == "20261102"
    assert _evening_start_ymd(datetime(2026, 11, 2, 16, 0, tzinfo=TP)) == "20261102"


def test_build_tx_night_card_from_mis_1m_uses_evening_session():
    from market_session_cards import build_tx_night_card_from_mis_1m

    pack = {
        "symbol": "TXFK6-M",
        "date": "20261102",
        "update_time": "00:18:43",
        "close": 45060.0,
        "volume": 27113,
        "ref": 45227.0,
        "ticks": [
            ["150100", "45227", "45246", "45171", "45175", "237"],
            ["150200", "45180", "45200", "45150", "45190", "100"],
            ["001800", "45050", "45070", "45040", "45055", "40"],
            ["001900", "45062", "45072", "45056", "45060", "21"],
        ],
    }
    card = build_tx_night_card_from_mis_1m(pack, 45300.0, evening_ymd="20261102")
    assert card is not None
    assert card["session"] == "20261102"
    assert card["last"] == 45060.0
    assert card["prev"] == 45300.0
    assert card["source"] == "taifex_mis"
    assert card.get("is_realtime") is True
    assert len(card["series"]) >= 3
    assert card["asof_time"] == "00:18:43"


def test_fetch_tx_after_hours_prefers_mis_during_night(monkeypatch):
    """00:15 夜盤窗：MIS 即時勝 zip（zip 常仍是上週五夜）。"""
    from market_session_cards import fetch_tx_after_hours_card

    pack = {
        "symbol": "TXFK6-M",
        "date": "20261102",
        "update_time": "00:15:00",
        "close": 45060.0,
        "volume": 27000,
        "ref": 45227.0,
        "ticks": [
            ["150100", "45227", "45246", "45171", "45175", "237"],
            ["220000", "45100", "45120", "45080", "45090", "50"],
            ["001500", "45050", "45070", "45040", "45060", "30"],
        ],
        "source": "taifex_mis",
        "is_realtime": True,
    }

    def _boom(*_a, **_k):
        raise AssertionError("夜盤窗不准先打 zip")

    monkeypatch.setattr(
        "market_ticker.fetch_tx_night_chart_1m", lambda timeout=6.0: pack
    )
    monkeypatch.setattr(
        "market_session_cards._regular_settlement", lambda session, month: 45300.0
    )
    monkeypatch.setattr("market_session_cards._SESSION.get", _boom)

    now = datetime(2026, 11, 3, 0, 15, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("missing") is False
    assert out.get("source") == "taifex_mis"
    assert card.get("session") == "20261102"
    assert card.get("last") == 45060.0
    assert card.get("session") != "20261030"


def test_fetch_tx_after_hours_daytime_still_uses_zip(monkeypatch):
    """日盤時段仍走 zip；MIS 夜盤路徑不准搶白天。"""
    from market_session_cards import fetch_tx_after_hours_card

    ticks = [
        ("20261102", "202611", "150100", 45200.0, 10),
        ("20261102", "202611", "210000", 45100.0, 20),
        ("20261103", "202611", "045953", 45050.0, 12),
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
            return _Resp(text="Daily_2026_11_03.zip")
        if "Daily_2026_11_03.zip" in url:
            return _Resp(content=b"ZIP" + b"0" * 2000)
        return _Resp(status=404, content=b"")

    def _mis_should_not_run(**_k):
        raise AssertionError("白天不准打夜盤 MIS")

    monkeypatch.setattr("market_session_cards._SESSION.get", _get)
    monkeypatch.setattr(
        "market_session_cards._read_tick_zip", lambda blob: "ZIP"
    )
    monkeypatch.setattr(
        "market_session_cards.parse_tx_night_ticks", lambda text: list(ticks)
    )
    monkeypatch.setattr(
        "market_session_cards._regular_settlement", lambda session, month: 45300.0
    )
    monkeypatch.setattr(
        "market_ticker.fetch_tx_night_chart_1m", _mis_should_not_run
    )

    now = datetime(2026, 11, 3, 10, 0, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("source") == "taifex_zip"
    assert card.get("session") == "20261102"


def test_pick_tx_quote_row_night_suffix():
    from market_ticker import pick_tx_quote_row

    rows = [
        {"SymbolID": "TXF-S", "CLastPrice": "44920", "CTotalVolume": ""},
        {"SymbolID": "TXFK6-F", "CLastPrice": "45256", "CTotalVolume": "90000"},
        {"SymbolID": "TXFK6-M", "CLastPrice": "45060", "CTotalVolume": "27113"},
        {"SymbolID": "TXFL6-M", "CLastPrice": "45156", "CTotalVolume": "141"},
    ]
    night = pick_tx_quote_row(rows, night=True)
    assert night and night["SymbolID"] == "TXFK6-M"
    day = pick_tx_quote_row(rows, night=False)
    assert day and day["SymbolID"] == "TXFK6-F"
