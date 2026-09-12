# -*- coding: utf-8 -*-
"""飆大視窗單向讀主庫；一般查股仍出兩張圖卡。"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

from biaoke_brain import answer_biaoke, resolve_stock, stock_query
from biaoke_facts import (
    DAILY_FUSE_SLOTS,
    MAIN_FEATURE_MODULES,
    format_market_facts,
    names_in_ask,
    refresh_after_market_fuse,
    talk_core,
)
from tests.test_why_menu import _bot, _msg, _update


def _seed(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT,
            asset_type TEXT, industry TEXT, is_active INT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT DEFAULT 'TWII', close REAL,
            volume REAL, pct_change REAL, high REAL, low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE user_holdings (
            user_id TEXT NOT NULL, stock_code TEXT NOT NULL,
            stock_name TEXT DEFAULT '', shares REAL NOT NULL,
            cost_price REAL NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, stock_code)
        )
        """
    )
    conn.execute(
        "INSERT INTO stock_universe VALUES ('3035','智原','TW','STOCK','IC設計',1)"
    )
    conn.execute(
        "INSERT INTO stock_universe VALUES ('2454','聯發科','TW','STOCK','IC設計',1)"
    )
    for d, o, h, l, c, v, pct, fr, tr, de in (
        ("20260908", 140, 148, 138, 145, 8000, 2.1, 1200, 80, 10),
        ("20260909", 145, 146, 132, 134, 4000, -7.5, -300, 20, -5),
        ("20260910", 134, 138, 130, 136, 2500, 1.49, 50, 0, 0),
    ):
        conn.execute(
            """
            INSERT INTO daily_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price,
                foreign_net, trust_net, dealer_net
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (d, "3035", "智原", "TW", o, h, l, c, v, 0, pct, c, fr, tr, de),
        )
    for d, o, h, l, c, v, pct in (
        ("20260908", 1200, 1280, 1180, 1260, 20000, 4.0),
        ("20260909", 1260, 1290, 1240, 1280, 9000, 1.6),
        ("20260910", 1280, 1310, 1270, 1300, 8000, 1.56),
    ):
        conn.execute(
            """
            INSERT INTO daily_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (d, "2454", "聯發科", "TW", o, h, l, c, v, 0, pct, c),
        )
    conn.execute(
        """
        INSERT INTO index_daily(date, symbol, close, pct_change, high, low)
        VALUES ('20260910','TWII',26500,-1.12,26580,26440)
        """
    )
    conn.execute(
        """
        INSERT INTO user_holdings
        VALUES ('9','3035','智原',2000,120,'2026-09-10T10:00:00')
        """
    )
    conn.commit()
    conn.close()


def test_talk_core_keeps_zhiyuan():
    assert talk_core("你怎麼看智原") == "智原"
    assert talk_core("智原") == "智原"
    assert talk_core("3035") == "3035"
    assert names_in_ask("你怎麼看智原")[0][0] == "3035"
    assert stock_query("你怎麼看智原") == "智原"


def test_zhiyuan_in_biaoke_uses_main_db_not_lookup_miss(tmp_path):
    db = str(tmp_path / "wayne.db")
    _seed(db)
    hits = resolve_stock(db, "你怎麼看智原")
    assert hits
    assert hits[0]["stock_id"] == "3035"
    html = answer_biaoke(db, "你怎麼看智原", uid="9")
    assert "智原" in html
    assert "找不到這檔" not in html
    assert "3035" in html
    pack = format_market_facts(db, "智原", uid="9")
    assert "3035" in pack
    assert "智原" in pack
    assert "外資" in pack
    assert "這個人持股" in pack
    assert "成本" in pack
    assert "官方加權" in pack
    assert "聯發科" in html or "聯發科" in pack
    assert "爆大量" in html or "量價" in pack
    assert "補漲" in html or "補漲" in pack
    assert "波浪" not in html or "不" in html
    assert "融會貫通審核" in pack
    assert "自問" in pack


def test_refresh_after_fuse_only_on_fuse(tmp_path):
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()
    skipped = refresh_after_market_fuse(db, kind="morning")
    assert skipped.get("skipped") == "morning"
    ran = refresh_after_market_fuse(db, kind="fuse")
    assert ran.get("ok") is True
    assert any(slot[0] == "16:30" for slot in DAILY_FUSE_SLOTS)


def test_main_features_do_not_import_biaoke_overlay():
    root = Path(__file__).resolve().parents[1]
    for name in MAIN_FEATURE_MODULES:
        src = (root / name).read_text(encoding="utf-8")
        assert "from biaoke_" not in src
        assert "import biaoke_" not in src
        assert "import biaoke\n" not in src


def test_normal_name_lookup_sends_two_cards_not_biaoke():
    bot = _bot()
    bot._send_biaoke_page = AsyncMock()
    msg = _msg(9, "智原")
    with patch(
        "bot_servers.lookup_stocks",
        return_value=[{"stock_id": "3035", "stock_name": "智原", "close": 136}],
    ):
        with patch("bot_servers.hits_need_picker", return_value=False):
            asyncio.run(bot.on_text(_update(msg), MagicMock()))
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "3035"
    bot._send_biaoke_page.assert_not_awaited()


def test_biaoke_window_zhiyuan_goes_to_biaoke_not_cards():
    bot = _bot()
    bot._send_biaoke_page = AsyncMock()
    msg = _msg(9, "你怎麼看智原")
    bot._pending[bot._actor_key(msg, uid="9")] = "biaoke:chat"
    asyncio.run(bot.on_text(_update(msg), MagicMock()))
    bot._send_biaoke_page.assert_awaited()
    ask = bot._send_biaoke_page.await_args.kwargs.get("ask") or ""
    assert "智原" in ask
    bot._send_card_to.assert_not_awaited()
    assert bot._pending[bot._actor_key(msg, uid="9")] == "biaoke:chat"


def test_biaoke_window_plain_name_stays_in_biaoke():
    bot = _bot()
    bot._send_biaoke_page = AsyncMock()
    msg = _msg(9, "智原")
    bot._pending[bot._actor_key(msg, uid="9")] = "biaoke:chat"
    asyncio.run(bot.on_text(_update(msg), MagicMock()))
    bot._send_biaoke_page.assert_awaited()
    assert (bot._send_biaoke_page.await_args.kwargs.get("ask") or "") == "智原"
    bot._send_card_to.assert_not_awaited()


def test_ingest_hook_still_on_clocks_and_fuse_relinks():
    import inspect
    import main

    src = inspect.getsource(main.run_scheduled_job)
    assert "run_biaoke_ingest_quiet" in src
    assert "refresh_after_market_fuse" in src
    assert 'kind == "fuse"' in src
