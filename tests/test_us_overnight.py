# -*- coding: utf-8 -*-
"""美股現金收盤用日 K，不拿 Yahoo 盤後％；領漲類股只認官方收。"""
from us_overnight import (
    _cash_move,
    _fmt_move,
    format_quote_move,
    format_us_lead_line,
    last_post_from_block,
    last_pre_from_block,
    pick_us_lead_group,
)


def test_cash_move_uses_daily_bars_not_yahoo_meta_pct():
    """20260916 台積：meta 1.23% 是錯的；日 K 417.72 vs 413.75 = +0.96%。"""
    closes = [413.75, 417.72]
    px, chg, pct = _cash_move(closes, 417.72, session_open=False)
    assert px == 417.72
    assert abs(chg - 3.97) < 1e-9
    assert abs(pct - 0.9595166163141994) < 1e-9


def test_cash_move_ignores_post_tainted_last_price():
    px, chg, pct = _cash_move([413.75, 417.72], 430.0, session_open=False)
    assert px == 417.72
    assert abs(chg - 3.97) < 1e-9


def test_fmt_tsm_shows_price_pct_and_usd():
    text = _fmt_move(0.96, 3.97, px=417.72, unit="美元")
    assert text == "417.72　+0.96%（+3.97美元）"
    snap = {"tsm_pct": 0.96, "tsm_chg": 3.97, "tsm_px": 417.72}
    assert format_quote_move(snap, "tsm_pct", "tsm_chg") == text
    assert _fmt_move(-0.8, -142.15) == "-0.80%（-142.15點）"


def test_pick_lead_group_requires_positive_max():
    assert pick_us_lead_group([("半導體", 0.64), ("光通訊", 2.19), ("能源", -2.8)]) == (
        "光通訊",
        2.19,
    )
    assert pick_us_lead_group([("半導體", -0.1), ("能源", -2.8)]) is None
    assert format_us_lead_line({"us_lead_name": "光通訊", "us_lead_pct": 2.19}) == (
        "美股昨漲較多　光通訊"
    )
    assert format_us_lead_line({"us_lead_name": "光通訊", "us_lead_pct": -0.2}) == ""


def test_last_post_pct_vs_cash_close_not_previous_close():
    block = {
        "meta": {
            "previousClose": 100.0,
            "currentTradingPeriod": {
                "regular": {"start": 1000, "end": 2000},
                "post": {"start": 2000, "end": 3000},
            },
        },
        "timestamp": [1500, 1999, 2000, 2500, 3100],
        "indicators": {"quote": [{"close": [101.0, 102.0, 99.0, 97.5, 50.0]}]},
    }
    got = last_post_from_block(block)
    assert got["price"] == 97.5
    assert got["previous_close"] == 102.0
    assert abs(got["pct"] - (97.5 - 102.0) / 102.0 * 100.0) < 1e-9


def test_last_pre_from_block_uses_pre_window():
    block = {
        "meta": {
            "previousClose": 100.0,
            "currentTradingPeriod": {
                "pre": {"start": 500, "end": 1000},
                "regular": {"start": 1000, "end": 2000},
                "post": {"start": 2000, "end": 3000},
            },
        },
        "timestamp": [400, 600, 900, 1100],
        "indicators": {"quote": [{"close": [99.0, 101.5, 102.0, 103.0]}]},
    }
    got = last_pre_from_block(block)
    assert got["price"] == 102.0
    assert got["previous_close"] == 100.0
    assert abs(got["pct"] - 2.0) < 1e-9


def test_weekend_sox_live_bar_is_official_close_not_extended(monkeypatch):
    """週末 force 抓費半：live_session=0，收＝日K官方收，不准盤後／meta 殘價。"""
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    import us_overnight as uo

    cash_close = 9390.25
    extended_px = 9474.0
    friday_ts = int(datetime(2026, 11, 6, 16, 0, tzinfo=uo.NY).timestamp())

    def _fake_get(url, timeout=20):
        if "SOXX" in url:
            body = {
                "chart": {
                    "result": [
                        {
                            "meta": {"regularMarketVolume": 1_000_000},
                            "indicators": {"quote": [{"volume": [1_000_000]}]},
                        }
                    ]
                }
            }
        else:
            # 日K官方收 vs meta／盤後殘價：休市只准吃 closes[-1]
            body = {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": extended_px,
                                "regularMarketOpen": 9300.0,
                                "regularMarketDayHigh": extended_px,
                                "regularMarketDayLow": 9200.0,
                                "regularMarketTime": friday_ts,
                                "preMarketPrice": extended_px,
                            },
                            "timestamp": [friday_ts],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [9300.0],
                                        "high": [9420.0],
                                        "low": [9200.0],
                                        "close": [cash_close],
                                        "volume": [0],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: body,
        )

    monkeypatch.setattr(uo._SESSION, "get", _fake_get)
    monkeypatch.setattr(uo, "_fetch_post_last", lambda _sym: {"price": extended_px, "ts": friday_ts})
    monkeypatch.setattr(uo, "_fetch_pre_last", lambda _sym: {"price": extended_px, "ts": friday_ts})

    taipei = ZoneInfo("Asia/Taipei")
    sunday = datetime(2026, 11, 8, 8, 53, tzinfo=taipei)
    assert uo._us_cash_calendar_closed(sunday) is True
    live = uo.fetch_live_sox_display_bar(sunday, force=True)
    assert live is not None
    assert int(live.get("live_session") or 0) == 0
    # as_of=11/8 週末 → 上一美股開市日 11/06；不准拿到之後的 11/09 柱／盤後殘
    assert str(live.get("date") or "") == "20261106"
    assert abs(float(live["close"]) - cash_close) < 1e-9
    assert abs(float(live["close"]) - extended_px) > 1.0


def test_outer_rows_brent_dx_twd():
    from us_overnight import outer_rows

    rows = dict(
        outer_rows(
            {
                "brent_px": 78.5,
                "brent_pct": 1.2,
                "dx_f_px": 104.2,
                "dx_f_pct": -0.31,
                "usdtwd_px": 31.45,
                "usdtwd_pct": 0.22,
            }
        )
    )
    assert rows["布蘭特原油"].startswith("78.50美元/桶")
    assert "+1.20%" in rows["布蘭特原油"]
    assert "104.20" in rows["美元指數"]
    assert "台幣貶" in rows["美元兌台幣"]
    assert outer_rows({}) == []
    weak = dict(outer_rows({"usdtwd_px": 32.1, "usdtwd_pct": -0.18}))
    assert "台幣升" in weak["美元兌台幣"]
