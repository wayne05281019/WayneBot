# -*- coding: utf-8 -*-
from unittest.mock import patch


def test_fetch_lookup_quote_yahoo_when_mis_empty():
    from live_quote import fetch_lookup_quote

    yahoo_rt = {
        "stock_id": "3105",
        "close": 469.5,
        "pct_change": -4.57,
        "change": -22.5,
        "yesterday_close": 492.0,
        "update_time": "13:30:00",
        "is_realtime": True,
        "source": "yahoo",
    }
    with patch("live_quote.fetch_mis_quote", return_value=None), patch(
        "live_quote.is_lookup_trading_day", return_value=True
    ), patch("live_quote.fetch_yahoo_tw_quote", return_value=yahoo_rt):
        rt = fetch_lookup_quote("3105", "OTC", "data/wayne_market.db")
    assert rt is not None
    assert rt["close"] == 469.5
    assert rt["source"] == "yahoo"


def test_help_has_row1_row2_and_ai():
    from bot_servers import HELP_TOPICS

    for key in ("row1", "row2", "ai"):
        assert key in HELP_TOPICS
    assert "AI模擬倉" in HELP_TOPICS["ai"]
    assert "20:00" in HELP_TOPICS["ai"]
    assert "決策卡" in HELP_TOPICS["row1"]
    assert "隔日沖" in HELP_TOPICS["row2"]


def test_us_alert_no_wide_rjust_padding():
    from us_overnight import format_us_drop_alert

    snap = {
        "regime": "caution",
        "vix": 16.34,
        "vix_pct": 9.52,
        "dji_pct": -0.79,
        "dji_chg": -419.11,
        "spx_pct": -0.71,
        "spx_chg": -54.65,
        "ixic_pct": -1.03,
        "ixic_chg": -271.09,
        "sox_pct": -2.14,
        "sox_chg": -246.39,
        "nq_f_pct": -0.12,
        "nq_f_chg": -34.37,
        "us_phase": "post",
        "us_session": "20260901",
    }
    html = format_us_drop_alert(snap)
    assert "    -0.79%" not in html
    assert "<code>" not in html
    assert max(len(line) for line in html.splitlines()) <= 36
