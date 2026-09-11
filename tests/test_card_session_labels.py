# -*- coding: utf-8 -*-
"""高低卡最上欄：盤中／昨天標籤不能混讀。"""
from __future__ import annotations

import inspect
import os
import tempfile

import pandas as pd

from wayne_navigator import (
    generate_decision_card,
    ohlc_face_rows,
    ohlc_line_bits,
    render_decision_card_png,
    session_price_label,
    table_row_is_live,
)


def test_session_price_label_live_vs_close():
    assert session_price_label({"is_live": True}) == "現價"
    assert session_price_label({"is_live": False}) == "收盤"
    assert session_price_label({}) == "收盤"
    assert session_price_label(None) == "收盤"


def test_ohlc_face_rows_split_today_and_yesterday():
    rows = ohlc_face_rows(
        {"open": 36, "high": 36.16, "low": 35.66, "prev_close": 37.15},
    )
    assert rows == ["今開 36　今高 36.16", "今低 35.66　昨收 37.15"]


def test_etf_nav_line_bits_live_uses_yesterday_nav():
    from wayne_navigator import etf_nav_line_bits

    bits = etf_nav_line_bits(
        {
            "is_live": True,
            "latest_date": "20260911",
            "etf_nav": 37.10,
            "etf_nav_date": "20260910",
            "etf_premium": -3.18,
        }
    )
    assert bits[0].startswith("昨淨值 37.10")
    assert "09月10日" in bits[0]
    assert bits[1].startswith("今天折價 3.18%")
    assert "對照昨淨值" in bits[1]
    from wayne_navigator import _NAV_STACK, _ohlc_nav_extra_h

    extra = _ohlc_nav_extra_h(
        {
            "is_live": True,
            "latest_date": "20260911",
            "etf_nav": 37.10,
            "etf_nav_date": "20260910",
            "etf_premium": -3.18,
            "open": 36,
            "high": 36.16,
            "low": 35.66,
            "prev_close": 37.15,
        }
    )
    assert extra >= _NAV_STACK * 2 + 2.5


def test_ohlc_line_bits_mark_today_and_yesterday():
    bits = ohlc_line_bits(
        {"open": 72.1, "high": 72.1, "low": 70.2, "prev_close": 73.5},
    )
    assert bits == ["今開 72.1", "今高 72.1", "今低 70.2", "昨收 73.5"]
    from_last = ohlc_line_bits(
        {"open": 1, "high": 1, "low": 1, "prev_close": 9},
        {"open": 72.1, "high": 72.1, "low": 70.2, "yesterday_close": 73.5},
    )
    assert from_last[-1] == "昨收 73.5"
    assert from_last[0] == "今開 72.1"


def test_table_row_is_live_only_today_when_live():
    card = {"is_live": True, "latest_date": "20260911"}
    assert table_row_is_live(card, "20260911") is True
    assert table_row_is_live(card, "20260910") is False
    assert table_row_is_live({"is_live": False, "latest_date": "20260911"}, "20260911") is False


def test_html_card_labels_follow_session():
    """文字卡也要跟圖卡同一套：盤中現價、收盤才叫收盤。"""
    import wayne_navigator as wn

    html_src = inspect.getsource(generate_decision_card)
    assert "今開高低" in html_src
    assert "昨收" in html_src
    assert "session_price_label" in html_src
    png_src = inspect.getsource(wn.render_decision_card_png)
    assert "_paint_price_left" in png_src
    glance_src = inspect.getsource(wn.render_first_glance_png)
    assert "_paint_price_left" in glance_src


def _mini_table():
    return pd.DataFrame(
        [
            {
                "date": "20260911",
                "close": 70.65,
                "獲利": "42.6%",
                "預警": "5低",
                "高低": "低",
                "升降": "降溫",
                "升降註": "",
                "溫度計": "43.3°C",
                "月乖離": "0.3%",
                "120日量": "第116名",
                "bias_monthly": 0.3,
                "vol_rank_120": 116,
                "temp_num": 43.3,
            },
            {
                "date": "20260910",
                "close": 73.5,
                "獲利": "48.3%",
                "預警": "10高",
                "高低": "高",
                "升降": "升溫",
                "升降註": "",
                "溫度計": "49.0°C",
                "月乖離": "3.8%",
                "120日量": "第66名",
                "bias_monthly": 3.8,
                "vol_rank_120": 66,
                "temp_num": 49.0,
            },
        ]
    )


def _card(is_live: bool) -> dict:
    return {
        "stock_id": "6770",
        "stock_name": "力積電",
        "listing": "上市",
        "industry": "半導體業",
        "latest_date": "20260911",
        "query_date": "2026/09/11（五）",
        "query_clock": "盤中 10:04" if is_live else "13:30收盤",
        "is_live": is_live,
        "live_time": "10:03" if is_live else "",
        "close": 70.65,
        "open": 72.1,
        "high": 72.1,
        "low": 70.2,
        "prev_close": 73.5,
        "change_pct": -3.88,
        "h10": 73.5,
        "dist_h10": -4.0,
        "h20": 74.6,
        "dist_h20": -5.6,
        "h60": 85.7,
        "dist_h60": -21.3,
        "l10": 67.8,
        "dist_l10": 4.2,
        "l20": 66.6,
        "dist_l20": 6.1,
        "l60": 49.55,
        "dist_l60": 42.6,
        "space_20": 12,
        "space_60": 73,
        "ma60s": 0.3,
        "qty60": 209078,
        "stance": "漲多了，今天別追",
        "stance_kind": "wait",
        "badges": ["多頭格局", "月K還在往上"],
        "table": _mini_table(),
    }


def test_live_and_closed_png_render():
    live = _card(True)
    closed = _card(False)
    fd1, live_path = tempfile.mkstemp(suffix=".png")
    os.close(fd1)
    fd2, closed_path = tempfile.mkstemp(suffix=".png")
    os.close(fd2)
    try:
        assert render_decision_card_png(live, live_path)
        assert os.path.getsize(live_path) > 8000
        assert render_decision_card_png(closed, closed_path)
        assert os.path.getsize(closed_path) > 8000
    finally:
        for p in (live_path, closed_path):
            try:
                os.remove(p)
            except OSError:
                pass
