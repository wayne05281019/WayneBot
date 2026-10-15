# -*- coding: utf-8 -*-
"""圖三／圖四縮圖末日 K＋量＝決策卡盤中真報價（與圖一二同源）。"""
from __future__ import annotations

import inspect

import pandas as pd


def _live_card(**kw):
    base = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "close": 1010.0,
        "prev_close": 1000.0,
        "change_pct": 1.0,
        "is_live": True,
        "latest_date": "20261015",
        "query_date": "2026/10/15 (四)",
        "query_clock": "盤中 10:05",
        "quote_source": "daily_quotes",
        "listing": "上市",
        "open": 1005.0,
        "high": 1015.0,
        "low": 1002.0,
        "volume": 12345,
    }
    base.update(kw)
    return base


def test_overlay_appends_today_bar_when_missing(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20261015")
    monkeypatch.setattr(
        "trading_calendar.is_tw_open_calendar_day", lambda d: True
    )
    face = [
        {
            "date": "20261013",
            "open": 990.0,
            "high": 1000.0,
            "low": 980.0,
            "close": 995.0,
            "volume": 8000,
        }
    ]
    out = live_quote.overlay_live_face_from_card(face, _live_card(), stock_id="2330")
    assert len(out) == 2
    last = out[-1]
    assert str(last["date"]).replace("-", "")[:8] == "20261015"
    assert float(last["close"]) == 1010.0
    assert float(last["open"]) == 1005.0
    assert float(last["high"]) == 1015.0
    assert float(last["low"]) == 1002.0
    assert float(last["volume"]) == 12345.0
    assert bool(last.get("is_live")) is True


def test_overlay_updates_live_today_row(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20261015")
    df = pd.DataFrame(
        [
            {
                "date": "20261013",
                "open": 990.0,
                "high": 1000.0,
                "low": 980.0,
                "close": 995.0,
                "volume": 8000,
            },
            {
                "date": "20261015",
                "open": 1000.0,
                "high": 1001.0,
                "low": 999.0,
                "close": 1000.5,
                "volume": 100,
                "is_live": True,
            },
        ]
    )
    out = live_quote.overlay_live_face_from_card(df, _live_card(), stock_id="2330")
    assert len(out) == 2
    assert float(out.iloc[-1]["close"]) == 1010.0
    assert float(out.iloc[-1]["volume"]) == 12345.0


def test_overlay_skips_when_not_live(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20261015")
    face = [{"date": "20261013", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10}]
    card = _live_card(is_live=False)
    out = live_quote.overlay_live_face_from_card(face, card, stock_id="2330")
    assert len(out) == 1
    assert str(out[0]["date"]) == "20261013"


def test_overlay_does_not_invent_volume_without_card():
    import live_quote

    face = [{"date": "20261013", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10}]
    out = live_quote.overlay_live_face_from_card(face, None, stock_id="2330")
    assert out is face


def test_structure_paint_calls_overlay():
    from biaoke_chart import render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    assert "overlay_live_face_from_card" in src
    assert "is_live" in src
    assert "live-face" in src or "last_v0" in src


def test_vol_zone_paint_calls_overlay():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "overlay_live_face_from_card" in src
    assert "card.get(\"is_live\")" in src or "card.get('is_live')" in src


def test_lookup_vol_comment_keeps_official_zone_only():
    """選區仍官方；縮圖可疊盤中真報價——不准退回造假量。"""
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "只吃官方原柱" in src
    assert "overlay_live_face_from_card" in open("live_quote.py", encoding="utf-8").read()


def test_emerging_overlay_uses_em_market(monkeypatch):
    import live_quote

    monkeypatch.setattr(live_quote, "is_live_merge_window", lambda now=None: True)
    monkeypatch.setattr(live_quote, "taipei_today_str", lambda: "20261015")
    monkeypatch.setattr(
        "trading_calendar.is_tw_open_calendar_day", lambda d: True
    )
    card = _live_card(
        stock_id="3595",
        listing="興櫃",
        quote_source="emerging_quotes",
        close=1350.0,
        prev_close=1402.0,
        open=1395.0,
        high=1400.0,
        low=1330.0,
        volume=25,
        change_pct=-3.71,
    )
    face = [
        {
            "date": "20261013",
            "open": 1391.0,
            "high": 1450.0,
            "low": 1375.0,
            "close": 1402.0,
            "volume": 10,
        }
    ]
    out = live_quote.overlay_live_face_from_card(face, card, stock_id="3595")
    assert len(out) == 2
    assert float(out[-1]["close"]) == 1350.0
    assert float(out[-1]["volume"]) == 25.0
