# -*- coding: utf-8 -*-
"""深度 UX 審計：callback 路由、排版、邊界輸入。"""
from __future__ import annotations

import asyncio
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _msg(chat_id: int, uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=chat_id)
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    return message


def _cb(data: str, uid: int = 1, chat_id: int = 1):
    msg = _msg(chat_id, uid)
    q = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=uid),
        message=msg,
        answer=AsyncMock(),
        get_bot=MagicMock(),
    )
    return SimpleNamespace(callback_query=q), msg


def _bot():
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = "data/wayne_market.db"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    return bot


@pytest.mark.parametrize(
    "prefix,handler_attr",
    [
        ("w:", "_hub_keyboard"),
        ("b:", "reply_text"),
        ("x:", "reply_text"),
        ("ai_view", "_send_ai_desk_view"),
        ("ai_run", "_run_ai_now"),
        ("portfolio", "_send_portfolio"),
        ("watch", "_send_watch"),
    ],
)
def test_callback_routes_to_expected_handler(prefix, handler_attr):
    bot = _bot()
    if handler_attr.startswith("_"):
        setattr(bot, handler_attr, AsyncMock())
    bot._send_card_to = AsyncMock()
    bot._send_decision_card_quick = AsyncMock()
    bot._send_navigation_chart = AsyncMock()
    bot._send_industry = AsyncMock()
    bot._send_ai_desk_view = AsyncMock()
    bot._run_ai_now = AsyncMock()
    bot._send_portfolio = AsyncMock()
    bot._send_watch = AsyncMock()
    bot._run_manual_screening = AsyncMock()
    bot._run_trade_bucket = AsyncMock()
    bot._reply_help_topic = AsyncMock()
    bot._send_line_rich_bucket = AsyncMock()
    bot._remove_watch_clicked = AsyncMock()
    bot._reply_line_share = AsyncMock()

    data = f"{prefix}2330" if prefix.endswith(":") else prefix
    upd, msg = _cb(data)

    async def run():
        with patch("bot_servers.generate_chips_image", return_value=None), patch(
            "bot_servers.add_to_watchlist"
        ):
            await bot.on_callback(upd, MagicMock())

    asyncio.run(run())

    if prefix == "w:":
        msg.reply_html.assert_awaited()
    elif prefix in ("b:", "x:"):
        msg.reply_text.assert_awaited()
    elif prefix == "ai_view":
        bot._send_ai_desk_view.assert_awaited_once()
    elif prefix == "ai_run":
        bot._run_ai_now.assert_awaited_once()
    elif prefix == "portfolio":
        bot._send_portfolio.assert_awaited_once()
    elif prefix == "watch":
        bot._send_watch.assert_awaited_once()


def test_help_callback_edits_in_place_not_new_message():
    bot = _bot()
    bot._reply_help_topic = AsyncMock()
    upd, msg = _cb("?:stock")

    async def run():
        await bot.on_callback(upd, MagicMock())

    asyncio.run(run())
    bot._reply_help_topic.assert_awaited_once()
    assert bot._reply_help_topic.await_args.kwargs.get("edit_target") is msg


def test_hx_deletes_help_message():
    bot = _bot()
    upd, msg = _cb("hx")

    async def run():
        await bot.on_callback(upd, MagicMock())

    asyncio.run(run())
    msg.delete.assert_awaited_once()


def test_money_flow_html_no_wide_code_padding():
    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    from money_flow import format_flow_html

    html = format_flow_html(db, yyyymmdd="20260828")
    assert html
    assert not re.search(r"<code>\s{3,}", html)


def test_us_overnight_blocks_no_code_columns():
    from us_overnight import format_us_drop_alert

    snap = {
        "regime": "caution",
        "vix": 16.3,
        "vix_pct": 4.5,
        "vix_chg": 0.7,
        "dji_pct": -0.8,
        "dji_chg": -142.15,
        "spx_pct": -0.7,
        "spx_chg": -38.42,
        "ixic_pct": -1.0,
        "ixic_chg": -198.32,
        "sox_pct": -2.1,
        "sox_chg": -125.4,
        "us_phase": "regular",
        "us_session": "20260901",
    }
    html = format_us_drop_alert(snap)
    assert "<code>" not in html


def test_lookup_quote_reconcile_pct_from_db_prior():
    from live_quote import reconcile_lookup_quote

    rt = {
        "stock_id": "3105",
        "close": 469.5,
        "pct_change": 99.0,
        "change": 99.0,
        "yesterday_close": 0,
        "is_realtime": True,
    }
    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    out = reconcile_lookup_quote(rt, db, "3105", db_hit={"close": 492.0, "quote_date": "20260901"})
    assert out is not None
    assert abs(float(out["pct_change"]) - (-4.57)) < 0.2
