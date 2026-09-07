# -*- coding: utf-8 -*-
from unittest.mock import patch


def test_yahoo_volume_shares_to_lots():
    """Yahoo 台股量是股。2330 約 1,409 萬股＝14,090 張，不是 1,409 萬張。"""
    from live_quote import yahoo_volume_to_lots

    assert yahoo_volume_to_lots(14_090_000) == 14_090
    assert yahoo_volume_to_lots(2_000) == 2
    assert yahoo_volume_to_lots(600) == 0
    assert yahoo_volume_to_lots(0) == 0


def test_fetch_yahoo_tw_quote_converts_share_volume(monkeypatch):
    from live_quote import fetch_yahoo_tw_quote

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 2410.0,
                                "chartPreviousClose": 2390.0,
                                "regularMarketChangePercent": 0.84,
                                "regularMarketChange": 20.0,
                            },
                            "indicators": {
                                "quote": [
                                    {
                                        "close": [2410.0],
                                        "volume": [14_090_000],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    monkeypatch.setattr("live_quote._SESSION.get", lambda *a, **k: _Resp())
    monkeypatch.setattr("stock_links.yahoo_exchange", lambda *a, **k: "TW")
    rt = fetch_yahoo_tw_quote("2330")
    assert rt is not None
    assert rt["source"] == "yahoo"
    assert rt["volume"] == 14_090
    # 只有收、沒開高低時才允許落到現價；有日 K 時不要畫假十字。
    assert rt["close"] == 2410.0
    assert rt["yesterday_close"] == 2390.0


def test_fetch_yahoo_tw_quote_uses_session_ohlc_not_last_price(monkeypatch):
    """話筒 2330 盤中卡曾把開高低都畫成現價；Yahoo 日 K／盤中高低是有的。"""
    from live_quote import fetch_yahoo_tw_quote

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 2440.0,
                                "regularMarketDayHigh": 2450.0,
                                "regularMarketDayLow": 2430.0,
                                "chartPreviousClose": 2440.0,
                                "regularMarketTime": 1788746293,
                            },
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [2395.0, 2415.0, 2435.0],
                                        "high": [2440.0, 2420.0, 2450.0],
                                        "low": [2390.0, 2385.0, 2430.0],
                                        "close": [2440.0, 2410.0, 2440.0],
                                        "volume": [17_000_000, 13_000_000, 9_000_000],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    monkeypatch.setattr("live_quote._SESSION.get", lambda *a, **k: _Resp())
    monkeypatch.setattr("stock_links.yahoo_exchange", lambda *a, **k: "TW")
    rt = fetch_yahoo_tw_quote("2330")
    assert rt["open"] == 2435.0
    assert rt["high"] == 2450.0
    assert rt["low"] == 2430.0
    assert rt["close"] == 2440.0
    assert rt["yesterday_close"] == 2410.0
    assert rt["pct_change"] == round((2440.0 - 2410.0) / 2410.0 * 100.0, 2)
    assert {rt["open"], rt["high"], rt["low"]} != {rt["close"]}


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
    assert "AI倉" in HELP_TOPICS["ai"]
    assert "20:00" in HELP_TOPICS["ai"]
    assert "決策卡" in HELP_TOPICS["row1"]
    assert "AI倉" in HELP_TOPICS["row1"]
    assert "隔日沖" in HELP_TOPICS["row2"]
    assert "回報" in HELP_TOPICS["row2"]
    assert "空白預留" not in HELP_TOPICS["row2"]
    assert "按表操課" in HELP_TOPICS["guide"]
    assert "紅箭頭" in HELP_TOPICS["screen"]
    assert "溫度≥80" in HELP_TOPICS["stock"]
    assert "價溫背離" in HELP_TOPICS["stock"]
    assert "60日量" in HELP_TOPICS["stock"]
    assert "露出高低" in HELP_TOPICS["stock"]


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
