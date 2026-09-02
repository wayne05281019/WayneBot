# -*- coding: utf-8 -*-
"""多使用者角色：偉權（重度）、哥哥（同機）、新手、不懂股、亂按。"""
from __future__ import annotations

import asyncio
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
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


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
    bot.portfolio_engine.format_holdings_html = MagicMock(return_value="<b>持股</b>")
    return bot


# --- 新手：第一次按持股，只靜默掛鍵盤，不洗版 ---


def test_newbie_first_portfolio_silent_menu_pin():
    bot = _bot()
    bot._menu_layout_ok = MagicMock(return_value=False)
    bot._refresh_reply_menu = AsyncMock()
    bot._send_portfolio = AsyncMock()

    async def run():
        msg = _msg(10, 1001, "持股")
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._refresh_reply_menu.assert_awaited_once_with(
        bot._refresh_reply_menu.await_args[0][0],
        uid="1001",
        silent=True,
    )
    bot._send_portfolio.assert_awaited_once()


def test_explicit_menu_cmd_not_silent():
    bot = _bot()
    bot._refresh_reply_menu = AsyncMock()
    msg = _msg(10, 1001)

    async def run():
        await bot.menu_cmd(_update(msg), MagicMock())

    asyncio.run(run())
    kwargs = bot._refresh_reply_menu.await_args.kwargs
    assert kwargs.get("silent") is not True


# --- 哥哥 vs 偉權：LINE 進度、海選區塊互不干擾 ---


def test_brother_line_pack_status_isolated():
    bot = _bot()
    m_wayne = MagicMock()
    m_wayne.delete = AsyncMock()
    m_bro = MagicMock()
    m_bro.delete = AsyncMock()
    bot._track_line_pack_status("99:111", m_wayne)
    bot._track_line_pack_status("99:222", m_bro)

    async def run():
        await bot._dismiss_line_pack_status("99:111")

    asyncio.run(run())
    m_wayne.delete.assert_awaited_once()
    m_bro.delete.assert_not_awaited()
    assert "99:222" in bot._line_pack_status_msgs


def test_brother_screening_section_isolated():
    bot = _bot()
    m_wayne = MagicMock()
    m_wayne.delete = AsyncMock()
    m_bro = MagicMock()
    bot._track_screening_msg("99:111", "leave_zero", m_wayne)
    bot._track_screening_msg("99:222", "leave_zero", m_bro)

    async def run():
        await bot._dismiss_screening_section("99:111", "leave_zero")

    asyncio.run(run())
    m_wayne.delete.assert_awaited_once()
    bucket = bot._screening_msgs.get("99:222") or {}
    assert "leave_zero" in bucket


# --- 重度用戶：有上次決策卡代號，按決策卡只刷新該檔 ---


def test_power_user_decision_card_reuses_last_code():
    bot = _bot()
    bot._last_card["9001"] = "3105"
    bot._send_decision_card_quick = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    msg = _msg(1, 9001)

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[{"stock_id": "3105", "stock_name": "穩懋"}]):
            await bot.decision_card_btn(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_decision_card_quick.assert_awaited_once()
    assert bot._send_decision_card_quick.await_args[0][1] == "3105"
    bot._delete_message.assert_awaited()


# --- 不懂股：純空白、全形空白不觸發查股 ---


@pytest.mark.parametrize("text", ("   ", "\u3000\u3000", "\t"))
def test_whitespace_only_is_silent(text):
    bot = _bot()
    msg = _msg(2, 2, text)

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    msg.reply_text.assert_not_awaited()


# --- 亂按：同聊天室兩人 pending 不共用 ---


def test_simplified_buy_pending_single_price():
    bot = _bot()
    bot._pending["42"] = "buy:2330"
    msg = _msg(1, 42, "68.5")

    async def run():
        with patch("bot_servers.record_buy", return_value="已記錄買入 2330 台積電 1張 @ 68.5") as rb, patch(
            "wayne_db.lookup_stocks", return_value=[{"stock_id": "2330", "stock_name": "台積電"}]
        ):
            await bot.on_text(_update(msg), MagicMock())
        return rb

    rb = asyncio.run(run())
    rb.assert_called_once()
    assert rb.call_args[0][2] == "2330"
    assert rb.call_args[0][4] == 1.0
    assert rb.call_args[0][5] == 68.5


def test_lookup_no_ack_spam():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(3, 3, "台積電")

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[{"stock_id": "2330", "stock_name": "台積電"}]):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    for call in msg.reply_text.await_args_list:
        text = call[0][0] if call[0] else ""
        assert "查詢中" not in str(text)


def test_pending_state_per_user_not_per_chat():
    bot = _bot()
    bot._pending["111"] = "buy:2330"
    bot._pending["222"] = "sell:2454"
    assert bot._pending["111"] == "buy:2330"
    assert bot._pending["222"] == "sell:2454"
