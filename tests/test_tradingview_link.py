# -*- coding: utf-8 -*-
"""查股圖下「K線」＝自家這一檔圖。一進日K＋量，可改 15／60 分與五日／十日／月／季。興櫃不掛。"""
from __future__ import annotations

import sqlite3

from bot_servers import WayneTelegramBot
from kline_hop import (
    aggregate_calendar,
    aggregate_n_day,
    normalize_interval,
    packed_series,
    render_kline_html,
)
from stock_links import (
    _EX_CACHE,
    tradingview_chart_url,
    tradingview_exchange,
    tradingview_widget_symbol,
    yahoo_exchange,
)


def _db(path: str) -> str:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,"
        " open REAL, high REAL, low REAL, close REAL, volume INTEGER)"
    )
    conn.execute("CREATE TABLE stock_directory (stock_id TEXT, stock_name TEXT, market TEXT)")
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT, stock_name TEXT, market_type TEXT, asset_type TEXT)"
    )
    conn.executemany(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("20260908", "2330", "台積電", "TW", 1000, 1010, 990, 1005, 50000),
            ("20260908", "6488", "環球晶", "TWO", 200, 205, 195, 202, 8000),
            ("20260908", "3595", "山太士", "EM", 12, 12, 12, 12, 100),
        ],
    )
    conn.commit()
    conn.close()
    _EX_CACHE.clear()
    return path


def test_tradingview_url_is_own_k_page(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert yahoo_exchange("2330", db) == "TW"
    assert tradingview_exchange("2330", db) == "TWSE"
    assert tradingview_widget_symbol("2330", db) == "TWSE:2330"
    assert tradingview_chart_url("2330", db) == "https://waynebot-service.onrender.com/k/2330"
    assert tradingview_exchange("6488", db) == "TPEX"
    assert tradingview_widget_symbol("6488", db) == "TPEX:6488"
    assert tradingview_chart_url("6488", db) == "https://waynebot-service.onrender.com/k/6488"


def test_tradingview_omits_emerging(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert tradingview_exchange("3595", db) == ""
    assert tradingview_chart_url("3595", db) == ""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("3595", em=True)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "K線" not in texts
    page = render_kline_html("3595", db_path=db)
    assert "興櫃" in page
    assert "tv.js" not in page


def test_hub_kline_is_https_url_button(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("2330")
    kline = next(b for r in kb.inline_keyboard for b in r if b.text == "K線")
    assert kline.callback_data is None
    assert kline.url == "https://waynebot-service.onrender.com/k/2330"
    assert kline.url.startswith("https://")
    assert all(len(r) <= 3 for r in kb.inline_keyboard)


def test_etf_letter_suffix_stays_in_k_url(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260908", "00631L", "元上證正2", "TW", 10, 11, 9, 10.5, 1000),
    )
    conn.commit()
    conn.close()
    _EX_CACHE.clear()
    assert tradingview_chart_url("00631L", db).endswith("/k/00631L")
    assert tradingview_widget_symbol("00631L", db) == "TWSE:00631L"


def test_kline_page_defaults_daily_and_has_periods(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    page = render_kline_html("2330", db_path=db)
    assert "lang=\"zh-Hant\"" in page
    assert "locale:\"zh_TW\"" in page
    assert "timezone:\"Asia/Taipei\"" in page
    assert "hide_volume:false" in page
    assert '"start":"D"' in page
    assert "TWSE:2330" in page
    assert "上市" in page and "TWSE" not in page.split("<body>")[1].split("<script")[0]
    for label in ("日K", "15分", "60分", "五日", "十日", "月線", "季線"):
        assert label in page
    assert "高低卡" in page


def test_normalize_interval():
    assert normalize_interval("") == "D"
    assert normalize_interval("15") == "15"
    assert normalize_interval("5D") == "5D"
    assert normalize_interval("3M") == "Q"
    assert normalize_interval("nope") == "D"


def test_aggregate_five_ten_month_quarter():
    bars = []
    for i in range(1, 23):
        day = 10 + i
        bars.append(
            {
                "t": f"202601{day:02d}",
                "o": 10.0 + i,
                "h": 11.0 + i,
                "l": 9.0 + i,
                "c": 10.5 + i,
                "v": 100 * i,
            }
        )
    five = aggregate_n_day(bars, 5)
    assert five[-1]["c"] == bars[-1]["c"]
    assert five[-1]["o"] == bars[-5]["o"]
    assert five[-1]["v"] == sum(b["v"] for b in bars[-5:])
    ten = aggregate_n_day(bars, 10)
    assert ten[-1]["o"] == bars[-10]["o"]
    packed = packed_series(bars)
    assert packed["5D"][-1]["t"] == bars[-1]["t"]
    month = aggregate_calendar(
        [
            {"t": "20260131", "o": 1, "h": 3, "l": 1, "c": 2, "v": 10},
            {"t": "20260201", "o": 2, "h": 9, "l": 2, "c": 8, "v": 7},
            {"t": "20260210", "o": 8, "h": 8, "l": 4, "c": 5, "v": 3},
        ],
        "M",
    )
    assert len(month) == 2
    assert month[1]["o"] == 2 and month[1]["c"] == 5 and month[1]["h"] == 9 and month[1]["v"] == 10
    q = aggregate_calendar(
        [
            {"t": "20260115", "o": 1, "h": 2, "l": 1, "c": 2, "v": 1},
            {"t": "20260320", "o": 2, "h": 4, "l": 2, "c": 3, "v": 1},
            {"t": "20260401", "o": 3, "h": 3, "l": 3, "c": 3, "v": 9},
        ],
        "Q",
    )
    assert len(q) == 2
    assert q[0]["o"] == 1 and q[0]["c"] == 3 and q[1]["v"] == 9


def test_kline_http_route_defaults_daily(tmp_path, monkeypatch):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import main

    db = _db(str(tmp_path / "m.db"))
    monkeypatch.setenv("WAYNE_DB_PATH", db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), main.HealthHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/k/2330", timeout=8) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
        assert "日K" in body and '"start":"D"' in body
        assert "15分" in body and "五日" in body and "季線" in body
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/k/2330?i=5D", timeout=8) as resp:
            alt = resp.read().decode("utf-8")
        assert '"start":"5D"' in alt
    finally:
        httpd.shutdown()
        httpd.server_close()
