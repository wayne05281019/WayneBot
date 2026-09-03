# -*- coding: utf-8 -*-
"""主選單十顆按鈕 × 五角色：路由與即時回饋（模擬層，真機見 docs/telegram_ux_audit.md）。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import MENU_BTN_MARKET, WayneTelegramBot

MENU_BUTTONS = [
    ("決策卡", "decision_card_btn"),
    ("當沖", "daytrade_cmd"),
    ("持股", "_send_portfolio"),
    ("觀察", "_send_watch"),
    ("海選", "screen_cmd"),
    ("隔日沖", "overnight_cmd"),
    ("資金", "flow_cmd"),
    ("說明", "help_cmd"),
    ("選單", "menu_cmd"),
    (MENU_BTN_MARKET, "market_cmd"),
]

INSTANT_ACK_BUTTONS = {MENU_BTN_MARKET: "讀取大盤", "資金": "讀取當日資金移動"}


def _msg(uid: int, text: str):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=99)
    message = MagicMock()
    message.chat_id = 99
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot(uid: int = 1001):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._enter_main_menu = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot.portfolio_engine.format_holdings_html = MagicMock(return_value="<b>持股</b>")
    for _label, attr in MENU_BUTTONS:
        setattr(bot, attr, AsyncMock())
    return bot


@pytest.mark.parametrize("label,handler", MENU_BUTTONS)
def test_menu_button_routes_to_handler(label, handler):
    """每顆主選單按鈕只觸發對應 handler。"""
    bot = _bot()
    real = getattr(WayneTelegramBot, handler, None)
    if handler.startswith("_"):
        setattr(bot, handler, AsyncMock())
    else:
        setattr(bot, handler, AsyncMock())

    async def run():
        msg = _msg(1001, label)
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    getattr(bot, handler).assert_awaited_once()


@pytest.mark.parametrize("label,hint", list(INSTANT_ACK_BUTTONS.items()))
def test_instant_ack_before_slow_work(label, hint):
    """大盤／資金須先回「讀取…」再跑重活（PR #134 契約）。"""
    bot = _bot()
    bot._enter_main_menu = AsyncMock(side_effect=lambda *a, **k: asyncio.sleep(0.05) or None)
    calls = []

    async def track_status(message, text, **kw):
        calls.append(text)
        return MagicMock()

    bot._transient_status = AsyncMock(side_effect=track_status)
    bot._send_market_page = AsyncMock()
    # _bot() 會把 handler 換成 mock；此測須綁回真實 market_cmd / flow_cmd
    bot.market_cmd = WayneTelegramBot.market_cmd.__get__(bot, WayneTelegramBot)
    bot.flow_cmd = WayneTelegramBot.flow_cmd.__get__(bot, WayneTelegramBot)
    with patch("money_flow.format_flow_html", return_value="<b>資金</b>"), patch(
        "money_flow.resolve_flow_as_of", return_value=("20260902", "")
    ), patch("money_flow.recompute_sector_flow", return_value=1), patch(
        "trading_calendar.fuse_end_trading_date", return_value="20260902"
    ):
        msg = _msg(1001, label)
        if label == MENU_BTN_MARKET:
            asyncio.run(bot.market_cmd(_update(msg), MagicMock()))
        else:
            asyncio.run(bot.flow_cmd(_update(msg), MagicMock()))

    assert calls and hint in calls[0]
    assert bot._transient_status.await_args_list[0] == bot._transient_status.await_args_list[0]


def test_chaos_user_pending_buy_then_market():
    """亂按：買入 pending 中按大盤，偉權 pending 保留。"""
    bot = _bot(uid=9001)
    bot._pending["99:9001"] = "buy:2330"
    bot.market_cmd = AsyncMock()

    async def run():
        msg = _msg(9002, MENU_BTN_MARKET)
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    assert bot._pending.get("99:9001") == "buy:2330"
    bot.market_cmd.assert_awaited_once()
