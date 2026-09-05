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


def test_parse_qty_accepts_share_and_lot_units():
    from trade_journal import (
        held_is_odd_lot_only,
        normalize_trade_tokens,
        parse_qty_to_lots,
    )

    assert parse_qty_to_lots("2") == 2.0
    assert parse_qty_to_lots("2張") == 2.0
    assert parse_qty_to_lots("439股") == pytest.approx(0.439)
    assert parse_qty_to_lots("200", default_unit="股") == pytest.approx(0.2)
    assert normalize_trade_tokens("200 股 72") == ["200股", "72"]
    assert held_is_odd_lot_only(0.439)
    assert not held_is_odd_lot_only(4)
    assert not held_is_odd_lot_only(1.0)
    from trade_journal import held_has_odd_shares

    assert held_has_odd_shares(0.439)
    assert held_has_odd_shares(1.439)
    assert not held_has_odd_shares(4)
    assert not held_has_odd_shares(1.0)


def test_parse_lots_price_share_units():
    lots, price = parse_lots_price("439股 631.6")
    assert lots == pytest.approx(0.439)
    assert price == 631.6
    lots, price = parse_lots_price("200股 72", price_only_sell_all=True)
    assert lots == pytest.approx(0.2)
    assert price == 72.0
    lots, price = parse_lots_price("1張 72", price_only_sell_all=True)
    assert lots == 1.0
    assert price == 72.0


def test_parse_odd_lot_bare_qty_is_shares_not_lots():
    lots, price = parse_lots_price("200 72", price_only_sell_all=True)
    assert lots == 200.0
    lots, price = parse_lots_price(
        "200 72", price_only_sell_all=True, bare_qty_is_shares=True
    )
    assert lots == pytest.approx(0.2)
    assert price == 72.0
    lots, price = parse_lots_price(
        "1張 72", price_only_sell_all=True, bare_qty_is_shares=True
    )
    assert lots == 1.0


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


def test_sell_from_holdings_message_uses_shares(tmp_db):
    from wayne_db import add_to_portfolio, sell_from_holdings

    add_to_portfolio(tmp_db, "u4", "6526", "達發", 0.439, 631.6)
    result = sell_from_holdings(tmp_db, "u4", "6526", 0.2, 635.0)
    assert result.ok
    assert "200股" in result.message
    assert "0.2張" not in result.message
    assert "0.200" not in result.message


def test_parse_sell_text_odd_lot_bare_qty(tmp_db):
    from bot_servers import WayneTelegramBot
    from wayne_db import add_to_portfolio

    add_to_portfolio(tmp_db, "u5", "6526", "達發", 0.439, 631.6)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = tmp_db
    code, lots, price = bot._parse_sell_text("200 72", "6526", held_lots=0.439)
    assert code == "6526"
    assert lots == pytest.approx(0.2)
    assert price == 72.0
    code, lots, price = bot._parse_sell_text("72", "6526", held_lots=0.439)
    assert lots == 0.0
    assert price == 72.0
    code, lots, price = bot._parse_sell_text("1 72", "3035", held_lots=4.0)
    assert lots == 1.0
    code, lots, price = bot._parse_buy_text("439股 631.6", "6526")
    assert lots == pytest.approx(0.439)
    assert price == 631.6


def test_parse_sell_bare_large_qty_is_shares_when_held_whole_lots(tmp_db):
    from bot_servers import WayneTelegramBot
    from trade_journal import coerce_bare_qty_if_share_count

    assert coerce_bare_qty_if_share_count(200, 4.0) == pytest.approx(0.2)
    assert coerce_bare_qty_if_share_count(1, 4.0) == 1
    assert coerce_bare_qty_if_share_count(200, 0.15) == 200  # 0.2 張已超過持有，不硬轉
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = tmp_db
    code, lots, price = bot._parse_sell_text("200 72", "3035", held_lots=4.0)
    assert lots == pytest.approx(0.2)
    code, lots, price = bot._parse_sell_text("200張 72", "3035", held_lots=4.0)
    assert lots == 200.0
    code, lots, price = bot._parse_sell_text("1 72", "3035", held_lots=4.0)
    assert lots == 1.0


def test_parse_sell_three_token_looks_up_held_lots(tmp_db):
    """pending 只有 sell、或一次打「代號 數量 價格」時，也要用持股把 200 當股。"""
    from bot_servers import WayneTelegramBot
    from wayne_db import add_to_portfolio

    add_to_portfolio(tmp_db, "u6", "3035", "智原", 4.0, 196.8)
    add_to_portfolio(tmp_db, "u6", "6526", "達發", 0.439, 631.6)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = tmp_db
    code, lots, price = bot._parse_sell_text("3035 200 72", uid="u6")
    assert code == "3035"
    assert lots == pytest.approx(0.2)
    assert price == 72.0
    code, lots, price = bot._parse_sell_text("3035 200張 72", uid="u6")
    assert lots == 200.0
    code, lots, price = bot._parse_sell_text("6526 200 72", uid="u6")
    assert code == "6526"
    assert lots == pytest.approx(0.2)
    code, lots, price = bot._parse_sell_text("3035 1 72", uid="u6")
    assert lots == 1.0


def test_parse_buy_bare_qty_looks_like_shares(tmp_db):
    """記買入打 439 631.6 當 439股；2 68.5 仍是 2張；已寫 439張 維持張。"""
    from bot_servers import WayneTelegramBot
    from trade_journal import coerce_bare_qty_if_share_count
    from wayne_db import add_to_portfolio

    assert coerce_bare_qty_if_share_count(439, 0, allow_unheld=True) == pytest.approx(0.439)
    assert coerce_bare_qty_if_share_count(2, 0, allow_unheld=True) == 2
    assert coerce_bare_qty_if_share_count(439, 0) == 439  # 賣出無持股不硬轉
    add_to_portfolio(tmp_db, "u7", "6526", "達發", 0.439, 631.6)
    add_to_portfolio(tmp_db, "u7", "3035", "智原", 4.0, 196.8)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = tmp_db
    code, lots, price = bot._parse_buy_text("439 631.6", "6526", uid="u7")
    assert code == "6526"
    assert lots == pytest.approx(0.439)
    assert price == 631.6
    code, lots, price = bot._parse_buy_text("6526 439 631.6", uid="u7")
    assert lots == pytest.approx(0.439)
    code, lots, price = bot._parse_buy_text("439張 631.6", "6526", uid="u7")
    assert lots == 439.0
    code, lots, price = bot._parse_buy_text("2 68.5", "2330", uid="u7")
    assert lots == 2.0
    code, lots, price = bot._parse_buy_text("68.5", "2330", uid="u7")
    assert lots == 1.0
    assert price == 68.5
    code, lots, price = bot._parse_buy_text("200 196.8", "3035", uid="u7")
    assert lots == pytest.approx(0.2)
    code, lots, price = bot._parse_buy_text("2330 439 500", uid="u8")
    assert code == "2330"
    assert lots == pytest.approx(0.439)


def test_parse_buy_mixed_lots_bare_qty_under_100(tmp_db):
    """混合張 1.439：50 未標單位當 50股；2 仍是 2張。"""
    from bot_servers import WayneTelegramBot
    from trade_journal import coerce_bare_qty_if_share_count
    from wayne_db import add_to_portfolio

    assert coerce_bare_qty_if_share_count(50, 1.439) == pytest.approx(0.05)
    assert coerce_bare_qty_if_share_count(2, 1.439) == 2
    add_to_portfolio(tmp_db, "u9", "6526", "達發", 1.439, 631.6)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = tmp_db
    code, lots, price = bot._parse_buy_text("50 631.6", "6526", uid="u9")
    assert lots == pytest.approx(0.05)
    code, lots, price = bot._parse_buy_text("2 631.6", "6526", uid="u9")
    assert lots == 2.0
    code, lots, price = bot._parse_sell_text("50 635", "6526", uid="u9")
    assert lots == pytest.approx(0.05)
