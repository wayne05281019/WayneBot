# -*- coding: utf-8 -*-
"""成交紀錄與簡化買賣輸入。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from trade_journal import parse_lots_price, record_buy, record_sell, recent_user_trades
from wayne_db import ensure_core_schema, get_user_portfolio


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    ensure_core_schema(path)
    yield path
    os.unlink(path)


def test_parse_buy_single_price_defaults_one_lot():
    lots, price = parse_lots_price("68.5", default_lots=1.0)
    assert lots == 1.0
    assert price == 68.5


def test_parse_buy_two_tokens():
    lots, price = parse_lots_price("2 68.5")
    assert lots == 2.0
    assert price == 68.5


def test_parse_sell_price_only_means_all():
    lots, price = parse_lots_price("72", price_only_sell_all=True)
    assert lots == 0.0
    assert price == 72.0


def test_parse_sell_all_keywords():
    lots, price = parse_lots_price("全賣", price_only_sell_all=True)
    assert lots == 0.0
    assert price is None


def test_record_buy_and_sell_writes_journal(tmp_db):
    uid = "u1"
    msg = record_buy(tmp_db, uid, "2330", "台積電", 1, 500.0)
    assert "已記錄買入" in msg
    assert get_user_portfolio(tmp_db, uid)[0]["stock_code"] == "2330"

    msg2 = record_sell(tmp_db, uid, "2330", 0, 520.0)
    assert "已賣出" in msg2
    assert not get_user_portfolio(tmp_db, uid)

    rows = recent_user_trades(tmp_db, uid)
    assert len(rows) == 2
    assert rows[0]["action"] == "SELL"
    assert rows[1]["action"] == "BUY"
    assert rows[0]["realized_pnl"] is not None


def test_sell_partial_keeps_remainder(tmp_db):
    record_buy(tmp_db, "u2", "2454", "聯發科", 2, 4000.0)
    record_sell(tmp_db, "u2", "2454", 1, 4100.0)
    held = get_user_portfolio(tmp_db, "u2")
    assert len(held) == 1
    assert float(held[0]["shares"]) == 1.0


def test_odd_lot_messages_use_shares_not_zhang(tmp_db):
    from trade_journal import format_user_trades_html

    uid = "u3"
    buy = record_buy(tmp_db, uid, "6526", "達發", 0.439, 631.6)
    assert "439股" in buy
    assert "0.439張" not in buy
    html = format_user_trades_html(tmp_db, uid)
    assert "439股" in html
    assert "0.439張" not in html
    sell = record_sell(tmp_db, uid, "6526", 0, 635.0)
    assert "439股" in sell
    assert "0.439張" not in sell
    html2 = format_user_trades_html(tmp_db, uid)
    assert "439股" in html2
