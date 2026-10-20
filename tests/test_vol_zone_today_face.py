# -*- coding: utf-8 -*-
"""查股大量區／結構：今天這根同源（表頭＝臉柱＝黃標＝圖說）。

案例鎖：7853 開當收盤中、3595 昨收當今天盤中、2383／3081 已收仍釘昨收。
不准改買訊。
"""
from __future__ import annotations

import pandas as pd

from vol_zone_chart import (
    _apply_card_face_to_view,
    align_vol_zone_caption_face,
    vol_zone_day_path_label,
    vol_zone_photo_caption,
    vol_zone_position_line,
)


def _zone(hi=3000.0, lo=2400.0):
    return {"date": "20260826", "high": hi, "low": lo, "volume": 6821.0}


def _yest_bars_3081():
    """庫末日仍是 10/16 收 2570；今天 10/20 已收 2490 在決策卡。"""
    return [
        {
            "date": "20261015",
            "open": 2620,
            "high": 2780,
            "low": 2615,
            "close": 2640,
            "volume": 3002,
        },
        {
            "date": "20261016",
            "open": 2685,
            "high": 2695,
            "low": 2500,
            "close": 2570,
            "volume": 4116,
        },
    ]


def _card_3081_closed():
    return {
        "stock_id": "3081",
        "listing": "上市",
        "quote_source": "daily_quotes",
        "is_live": False,
        "latest_date": "20261020",
        "as_of": "20261020",
        "open": 2590.0,
        "high": 2620.0,
        "low": 2490.0,
        "close": 2490.0,
        "prev_close": 2570.0,
        "volume": 5000,
        "query_date": "2026/10/20",
        "query_clock": "13:30收盤",
        "table": [{"date": "20261020", "升降": "降溫", "temp_num": 10.0}],
    }


def _card_2383_closed():
    return {
        "stock_id": "2383",
        "listing": "上市",
        "quote_source": "daily_quotes",
        "is_live": False,
        "latest_date": "20261020",
        "open": 5050.0,
        "high": 5200.0,
        "low": 4930.0,
        "close": 4945.0,
        "prev_close": 5125.0,
        "volume": 8000,
        "query_date": "2026/10/20",
        "query_clock": "13:30收盤",
        "table": [{"date": "20261020", "升降": "降溫"}],
    }


def _card_7853_live(monkeypatch):
    card = {
        "stock_id": "7853",
        "listing": "興櫃",
        "quote_source": "emerging_quotes",
        "is_live": True,
        "latest_date": "20261020",
        "open": 387.0,  # 前日均價
        "high": 395.0,
        "low": 385.0,
        "close": 392.2,  # 興櫃日均價／現
        "prev_close": 387.0,
        "volume": 120,
        "query_date": "2026/10/20",
        "query_clock": "10:30",
        "table": [{"date": "20261020", "升降": "升溫"}],
    }

    def _dq(c):
        if not c:
            return None
        return {
            "close": float(c["close"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "volume": float(c["volume"]),
            "prev": float(c["prev_close"]),
            "is_live": True,
            "label": "盤中",
            "date": "20261020",
            "emerging": True,
            "quote_source": "emerging_quotes",
        }

    monkeypatch.setattr("live_quote.display_quote_from_card", _dq)
    return card


def _card_3595_live(monkeypatch):
    card = {
        "stock_id": "3595",
        "listing": "興櫃",
        "quote_source": "emerging_quotes",
        "is_live": True,
        "latest_date": "20261020",
        "open": 920.0,
        "high": 925.0,
        "low": 900.0,
        "close": 908.3,
        "prev_close": 939.6,
        "volume": 800,
        "query_date": "2026/10/20",
        "query_clock": "11:00",
        "table": [{"date": "20261020", "升降": "降溫"}],
    }

    def _dq(c):
        if not c:
            return None
        return {
            "close": float(c["close"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "volume": float(c["volume"]),
            "prev": float(c["prev_close"]),
            "is_live": True,
            "label": "盤中",
            "date": "20261020",
            "emerging": True,
            "quote_source": "emerging_quotes",
        }

    monkeypatch.setattr("live_quote.display_quote_from_card", _dq)
    return card


def test_3081_closed_caption_and_callout_use_today_not_yest(monkeypatch):
    """表頭收2490；圖說／黃標不准再寫當天收2570（昨收）。"""
    monkeypatch.setattr(
        "live_quote.display_quote_from_card",
        lambda c: {
            "close": 2490.0,
            "open": 2590.0,
            "high": 2620.0,
            "low": 2490.0,
            "volume": 5000.0,
            "prev": 2570.0,
            "is_live": False,
            "label": "收盤",
            "date": "20261020",
            "emerging": False,
        }
        if c
        else None,
    )
    bars = _yest_bars_3081()
    card = _card_3081_closed()
    zone = _zone(3255.0, 2940.0)
    # 破撐：今天收 2490 < 撐 2940
    line = vol_zone_position_line(zone, bars[-1], card, bars=bars)
    assert "當天收2,490" in line
    assert "2570" not in line.replace(",", "")
    assert "當天收2,570" not in line
    cap = vol_zone_photo_caption(zone=zone, last=bars[-1], bars=bars, card=card)
    assert "當天收2,490" in cap
    assert "當天收2,570" not in cap
    path = vol_zone_day_path_label(
        3255.0, 2940.0, bars[-1], bars=bars, zone_date="20260826", card=card
    )
    assert "收2,490" in path
    assert "收2,570" not in path
    assert "10月20日" in path


def test_2383_closed_streak_sentence_stamps_today_close(monkeypatch):
    monkeypatch.setattr(
        "live_quote.display_quote_from_card",
        lambda c: {
            "close": 4945.0,
            "open": 5050.0,
            "high": 5200.0,
            "low": 4930.0,
            "volume": 8000.0,
            "prev": 5125.0,
            "is_live": False,
            "label": "收盤",
            "date": "20261020",
            "emerging": False,
        }
        if c
        else None,
    )
    zone = {"date": "20260917", "high": 5255.0, "low": 4635.0, "volume": 10000}
    bars = [
        {
            "date": "20261019",
            "open": 5100,
            "high": 5150,
            "low": 5080,
            "close": 5125,
            "volume": 6000,
        }
    ]
    card = _card_2383_closed()
    line = vol_zone_position_line(zone, bars[-1], card, bars=bars)
    assert "5125" not in line.replace(",", "") or "比昨天" in line
    # 今天這根必須是 4945
    assert "4,945" in line or "4945" in line.replace(",", "")
    assert "今天收盤" in line or "收盤" in line
    path = vol_zone_day_path_label(
        5255.0, 4635.0, bars[-1], bars=bars, card=card
    )
    assert "收4,945" in path
    assert "收5,125" not in path


def test_7853_emerging_intraday_never_stamps_open_as_close(monkeypatch):
    card = _card_7853_live(monkeypatch)
    zone = {"date": "20260901", "high": 420.0, "low": 400.0, "volume": 200}
    # 庫末日＝前日收／開 387；盤中現＝興櫃日均價 392.2。破撐路徑會戳價。
    bars = [
        {
            "date": "20261019",
            "open": 380,
            "high": 390,
            "low": 375,
            "close": 387,
            "volume": 100,
        }
    ]
    # 壓撐抬高讓 392.2 仍在帶內且比昨低 → 必戳「興櫃日均價 392.2」
    zone_in = {"date": "20260901", "high": 420.0, "low": 360.0, "volume": 200}
    bars_down = [
        {
            "date": "20261018",
            "open": 400,
            "high": 405,
            "low": 395,
            "close": 400,
            "volume": 80,
        },
        {
            "date": "20261019",
            "open": 398,
            "high": 402,
            "low": 390,
            "close": 395,
            "volume": 90,
        },
    ]
    line = vol_zone_position_line(zone_in, bars_down[-1], card, bars=bars_down)
    assert "興櫃日均價 392.2" in line or "興櫃日均價392.2" in line
    assert "當天收" not in line
    assert "今天收盤" not in line
    for banned in ("當天收387", "今天收盤 387", "今天收盤387", "當天收 387"):
        assert banned not in line
    # 破撐：日均價低於撐 → 戳興櫃日均價不是當天收開盤
    zone_brk = {"date": "20260901", "high": 450.0, "low": 400.0, "volume": 200}
    brk = vol_zone_position_line(zone_brk, bars[-1], card, bars=bars)
    assert "興櫃日均價392.2" in brk
    assert "撐400已跌破" in brk
    assert "當天收" not in brk


def test_3595_emerging_intraday_never_stamps_yest_as_today(monkeypatch):
    card = _card_3595_live(monkeypatch)
    zone = {"date": "20260901", "high": 980.0, "low": 850.0, "volume": 500}
    bars = [
        {
            "date": "20261018",
            "open": 950,
            "high": 960,
            "low": 945,
            "close": 955,
            "volume": 300,
        },
        {
            "date": "20261019",
            "open": 940,
            "high": 950,
            "low": 930,
            "close": 939.6,
            "volume": 400,
        },
    ]
    line = vol_zone_position_line(zone, bars[-1], card, bars=bars)
    assert "908.3" in line
    assert "興櫃日均價" in line
    assert "今天收盤 939.6" not in line
    assert "今天收盤939.6" not in line
    assert "當天收939.6" not in line
    assert "當天收" not in line
    assert "今天收盤" not in line


def test_apply_card_face_appends_today_bar_for_candle_geometry(monkeypatch):
    """臉柱幾何：庫停昨收時要附加今天棒，收／高低跟表頭同一組。"""
    monkeypatch.setattr(
        "live_quote.display_quote_from_card",
        lambda c: {
            "close": 2490.0,
            "open": 2590.0,
            "high": 2620.0,
            "low": 2490.0,
            "volume": 5000.0,
            "prev": 2570.0,
            "is_live": False,
            "label": "收盤",
            "date": "20261020",
            "emerging": False,
        }
        if c
        else None,
    )
    view = pd.DataFrame(_yest_bars_3081())
    out = _apply_card_face_to_view(view, _card_3081_closed())
    assert len(out) == len(view) + 1
    last = out.iloc[-1]
    assert str(last["date"]).replace("-", "")[:8] == "20261020"
    assert float(last["close"]) == 2490.0
    assert float(last["open"]) == 2590.0
    assert float(last["high"]) == 2620.0
    assert float(last["low"]) == 2490.0
    # 收 2490 必須低於軸刻度 2500（幾何對得上）
    assert float(last["close"]) < 2500.0
    assert float(last["high"]) < 2500.0 or float(last["close"]) <= float(last["high"])


def test_align_keeps_yest_bar_for_streak_compare(monkeypatch):
    monkeypatch.setattr(
        "live_quote.display_quote_from_card",
        lambda c: {
            "close": 4945.0,
            "open": 5050.0,
            "high": 5200.0,
            "low": 4930.0,
            "volume": 1.0,
            "prev": 5125.0,
            "is_live": False,
            "label": "收盤",
            "date": "20261020",
            "emerging": False,
        }
        if c
        else None,
    )
    bars = [
        {"date": "20261019", "open": 5100, "high": 5150, "low": 5080, "close": 5125, "volume": 1}
    ]
    face, rows, meta = align_vol_zone_caption_face(bars[-1], bars, _card_2383_closed())
    assert meta["aligned"] is True
    assert len(rows) == 2
    assert float(rows[0]["close"]) == 5125.0
    assert float(rows[1]["close"]) == 4945.0
    assert float(face["close"]) == 4945.0


def test_closed_support_break_plain_lines_use_today(monkeypatch):
    monkeypatch.setattr(
        "live_quote.display_quote_from_card",
        lambda c: {
            "close": 2490.0,
            "open": 2590.0,
            "high": 2620.0,
            "low": 2490.0,
            "volume": 5000.0,
            "prev": 2570.0,
            "is_live": False,
            "label": "收盤",
            "date": "20261020",
            "emerging": False,
        }
        if c
        else None,
    )
    zone = _zone(3255.0, 2940.0)
    cap = vol_zone_photo_caption(
        zone=zone,
        last=_yest_bars_3081()[-1],
        bars=_yest_bars_3081(),
        card=_card_3081_closed(),
    )
    assert "撐2,940已跌破" in cap
    assert "當天收2,490" in cap
    assert "這條撐不算還在" in cap
    assert "2570" not in cap.replace(",", "")
