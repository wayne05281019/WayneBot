# -*- coding: utf-8 -*-
"""查股圖下「K線」＝開 TradingView，網址已帶交易所＋代號。興櫃不掛。"""
from __future__ import annotations

import sqlite3

from bot_servers import WayneTelegramBot
from stock_links import (
    _EX_CACHE,
    tradingview_chart_url,
    tradingview_exchange,
    yahoo_exchange,
)


def _db(path: str) -> str:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, market TEXT)"
    )
    conn.execute("CREATE TABLE stock_directory (stock_id TEXT, stock_name TEXT, market TEXT)")
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT, stock_name TEXT, market_type TEXT, asset_type TEXT)"
    )
    conn.executemany(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market) VALUES (?,?,?,?)",
        [
            ("20260908", "2330", "台積電", "TW"),
            ("20260908", "6488", "環球晶", "TWO"),
            ("20260908", "3595", "山太士", "EM"),
        ],
    )
    conn.commit()
    conn.close()
    _EX_CACHE.clear()
    return path


def test_tradingview_url_twse_and_tpex(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert yahoo_exchange("2330", db) == "TW"
    assert tradingview_exchange("2330", db) == "TWSE"
    assert tradingview_chart_url("2330", db) == "https://www.tradingview.com/chart/?symbol=TWSE:2330"
    assert tradingview_exchange("6488", db) == "TPEX"
    assert tradingview_chart_url("6488", db) == "https://www.tradingview.com/chart/?symbol=TPEX:6488"


def test_tradingview_omits_emerging(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    assert tradingview_exchange("3595", db) == ""
    assert tradingview_chart_url("3595", db) == ""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("3595", em=True)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "K線" not in texts


def test_hub_kline_is_https_url_button(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._hub_keyboard("2330")
    kline = next(b for r in kb.inline_keyboard for b in r if b.text == "K線")
    assert kline.callback_data is None
    assert kline.url == "https://www.tradingview.com/chart/?symbol=TWSE:2330"
    assert all(len(r) <= 3 for r in kb.inline_keyboard)


def test_etf_letter_suffix_stays_in_tv_url(tmp_path):
    db = _db(str(tmp_path / "m.db"))
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market) VALUES (?,?,?,?)",
        ("20260908", "00631L", "元上證正2", "TW"),
    )
    conn.commit()
    conn.close()
    _EX_CACHE.clear()
    assert "TWSE:00631L" in tradingview_chart_url("00631L", db)
