# -*- coding: utf-8 -*-
"""查股圖下「K線」＝自家這一檔圖。一進日K＋量，可改 15／60 分與五日／十日／月／季。興櫃用官方日均價。"""
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
    kline_page_url,
    listed_kline_ok,
    yahoo_exchange,
    yahoo_urls,
)


def _db(path: str) -> str:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,"
        " open REAL, high REAL, low REAL, close REAL, volume INTEGER)"
    )
    conn.execute(
        "CREATE TABLE emerging_quotes (date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,"
        " open REAL, high REAL, low REAL, close REAL, volume INTEGER)"
    )
    conn.execute(
        "INSERT INTO emerging_quotes(date,stock_id,stock_name,market,open,high,low,close,volume)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260908", "6488X", "測試興櫃", "EM", 11, 13, 10, 12, 80),
    )
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


def test_no_tradingview_product_hooks():
    """產品碼不准再掛外站圖表；AGENTS 密技禁令那一行除外。"""
    for path in (
        "stock_links.py",
        "kline_hop.py",
        "kline_page.html",
        "bot_servers.py",
        "wayne_navigator.py",
        "picture_guide.py",
    ):
        src = open(path, encoding="utf-8").read().lower()
        assert "tradingview.com" not in src, path
        assert "tradingview_chart" not in src, path
        assert "tradingview_widget" not in src, path
        assert "tradingview_exchange" not in src, path
        assert "widgetembed" not in src, path
        assert "tv.js" not in src, path


def test_kline_url_is_own_page(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert yahoo_exchange("2330", db) == "TW"
    assert listed_kline_ok("2330", db) is True
    assert kline_page_url("2330", db) == "https://waynebot-service.onrender.com/k/2330"
    assert kline_page_url("2330", db, span=180) == (
        "https://waynebot-service.onrender.com/k/2330?n=180"
    )
    assert listed_kline_ok("6488", db) is True
    assert kline_page_url("6488", db) == "https://waynebot-service.onrender.com/k/6488"
    web, extra = yahoo_urls("2330", db)
    assert web.endswith("/quote/2330.TW")
    assert extra == web
    assert "technical-analysis" not in web


def test_kline_includes_emerging(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert listed_kline_ok("3595", db) is True
    assert kline_page_url("3595", db) == "https://waynebot-service.onrender.com/k/3595"
    assert kline_page_url("3595", db, span=180).endswith("/k/3595?n=180")
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("3595", em=True)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "K線" in texts
    assert "導航圖" in texts
    assert "產業" in texts
    page = render_kline_html("3595", db_path=db)
    assert "興櫃" in page
    assert '"D":[' in page
    assert "tv.js" not in page
    assert 'id="tv"' not in page
    only_em = render_kline_html("6488X", db_path=db)
    assert "官方日均價" in only_em
    assert '"c":12' in only_em or '"c": 12' in only_em


def test_hub_kline_is_https_url_button(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("2330")
    kline = next(b for r in kb.inline_keyboard for b in r if b.text == "K線")
    assert kline.callback_data is None
    assert kline.url == "https://waynebot-service.onrender.com/k/2330"
    assert kline.url.startswith("https://")
    nav = next(b for r in kb.inline_keyboard for b in r if b.text == "導航圖")
    assert nav.callback_data is None
    assert nav.url == "https://waynebot-service.onrender.com/k/2330?n=180"
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
    assert kline_page_url("00631L", db).endswith("/k/00631L")


def test_kline_page_defaults_daily_and_has_periods(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    page = render_kline_html("2330", db_path=db)
    assert "lang=\"zh-Hant\"" in page
    assert '"start":"D"' in page
    assert "/m?i=" in page
    assert "TWSE" not in page
    assert "widgetembed" not in page
    assert "tradingview.com" not in page
    assert 'id="tv"' not in page
    assert "上市" in page
    assert '"D":[' in page
    for label in ("導航", "日K", "15分", "60分", "五日", "十日", "月線", "季線"):
        assert label in page
    assert "導航圖" in page
    assert '"nav":' in page
    assert '"span":0' in page
    assert "20高" in page
    src = open("kline_page.html", encoding="utf-8").read()
    assert "requestedN" in src
    assert 'data-i="NAV"' in src
    assert "g.lineTo(x,y)" in src
    assert "yx(b.c)" in src
    assert "pointerdown" in src
    assert "PAN_PX=6" in src
    assert "輕點對價" in src
    assert 'mode==="pan"' in src
    assert "對價" in src
    assert "20高" in src
    assert "tradingview.com" not in src.lower()
    page180 = render_kline_html("2330", db_path=db, span=180)
    assert '"span":180' in page180
    assert "導航約 180 根" in page180


def test_merge_minute_bars_remote_wins_same_ts():
    from kline_hop import merge_minute_bars

    stored = [{"t": "202609010900", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]
    remote = [
        {"t": "202609010900", "o": 2, "h": 2, "l": 2, "c": 2, "v": 2},
        {"t": "202609011000", "o": 3, "h": 3, "l": 3, "c": 3, "v": 3},
    ]
    out = merge_minute_bars(stored, remote)
    assert [b["t"] for b in out] == ["202609010900", "202609011000"]
    assert out[0]["c"] == 2


def test_minute_bars_union_without_network(tmp_path, monkeypatch):
    from kline_hop import fetch_yahoo_minutes, save_minute_bars

    db = str(tmp_path / "m.db")
    save_minute_bars(
        "2330",
        "15",
        [{"t": "202609010900", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 10}],
        db,
    )
    remote = [{"t": "202609011000", "o": 2, "h": 3, "l": 2, "c": 2.5, "v": 11}]
    monkeypatch.setattr("kline_hop._download_yahoo_minutes", lambda *a, **k: remote)
    out = fetch_yahoo_minutes("2330", "15", db)
    assert [b["t"] for b in out] == ["202609010900", "202609011000"]
    monkeypatch.setattr("kline_hop._download_yahoo_minutes", lambda *a, **k: [])
    again = fetch_yahoo_minutes("2330", "15", db)
    assert [b["t"] for b in again] == ["202609010900", "202609011000"]
    assert again[1]["c"] == 2.5


def test_yahoo_minute_ranges_try_longer_first():
    from kline_hop import _yahoo_minute_ranges

    assert _yahoo_minute_ranges("15m")[0] == "60d"
    assert _yahoo_minute_ranges("60m")[0] == "2y"


def test_kline_minute_http_uses_store(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import main
    from kline_hop import save_minute_bars

    db = _db(str(tmp_path / "m.db"))
    save_minute_bars(
        "2330",
        "15",
        [{"t": "202609010900", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 10}],
        db,
    )
    monkeypatch.setenv("WAYNE_DB_PATH", db)
    monkeypatch.setattr("kline_hop._download_yahoo_minutes", lambda *a, **k: [])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), main.HealthHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/k/2330/m?i=15", timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
        assert payload["bars"][0]["t"] == "202609010900"
        assert payload["bars"][0]["c"] == 1.5
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_parse_yahoo_chart_bars_to_lots():
    from kline_hop import parse_yahoo_chart_bars

    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1757312100],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [101.0],
                                "low": [99.0],
                                "close": [100.5],
                                "volume": [12000],
                            }
                        ]
                    },
                }
            ]
        }
    }
    bars = parse_yahoo_chart_bars(payload)
    assert len(bars) == 1
    assert bars[0]["o"] == 100.0
    assert bars[0]["v"] == 12.0
    assert len(bars[0]["t"]) >= 12


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
        assert 'id="tv"' not in body
        assert "pointerdown" in body
        assert '"nav":' in body
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/k/2330?i=5D", timeout=8) as resp:
            alt = resp.read().decode("utf-8")
        assert '"start":"5D"' in alt
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/k/2330?n=180", timeout=8) as resp:
            nav = resp.read().decode("utf-8")
        assert '"span":180' in nav
        assert "導航約 180 根" in nav
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_decision_html_has_no_external_chart_links():
    import inspect

    from wayne_navigator import generate_decision_card

    src = inspect.getsource(generate_decision_card)
    assert "網頁走勢" not in src
    assert "技術線" not in src
    assert "yahoo_urls" not in src
    assert "technical-analysis" not in src


def test_nav_overlay_from_uptrend_has_20_high():
    from datetime import date, timedelta

    from wayne_navigator import nav_overlay_from_bars

    start = date(2026, 1, 5)
    bars = []
    i = 0
    px = 40.0
    while len(bars) < 80:
        d = start + timedelta(days=i)
        i += 1
        if d.weekday() >= 5:
            continue
        px += 0.8
        bars.append({"t": d.strftime("%Y%m%d"), "o": px - 0.4, "h": px + 0.6, "l": px - 0.7, "c": px, "v": 1200})
    ov = nav_overlay_from_bars(bars)
    assert ov["labels"]["h20"] == "20高"
    assert ov["labels"]["vol_a"] == "量能異常"
    assert len(ov["ma20"]) == len(bars)
    kinds = {m["kind"] for m in ov["price"]}
    assert "h20" in kinds
