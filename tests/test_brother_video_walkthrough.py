# -*- coding: utf-8 -*-
"""哥哥教學片閘門：說明三步、12 鈕、圖下方、亂按後能導回。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_CARD,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    WayneTelegramBot,
)
from persona_grid import PERSONAS_10
from tg_layout import chunk_telegram_html


MENU_BUTTONS = [
    (MENU_BTN_CARD, "decision_card_btn"),
    ("當沖", "daytrade_cmd"),
    ("持股", "_send_portfolio"),
    ("觀察", "_send_watch"),
    ("海選", "screen_cmd"),
    (MENU_BTN_AI, "_send_ai_desk_view"),
    ("隔日沖", "overnight_cmd"),
    ("資金", "flow_cmd"),
    ("說明", "help_cmd"),
    (MENU_BTN_STREAK, "streak_cmd"),
    (MENU_BTN_MARKET, "market_cmd"),
    (MENU_BTN_REPORT, "report_cmd"),
]


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
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._enter_main_menu = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._ensure_reply_menu_if_needed = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot.portfolio_engine.format_holdings_html = MagicMock(return_value="<b>持股</b>")
    for _label, attr in MENU_BUTTONS:
        setattr(bot, attr, AsyncMock())
    return bot


def test_twelve_menu_buttons_exist_in_order():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    row1 = [b.text for b in kb.keyboard[0]]
    row2 = [b.text for b in kb.keyboard[1]]
    assert row1 == ["說明", "海選", "持股", "觀察", MENU_BTN_CARD, MENU_BTN_REPORT]
    assert row2 == [MENU_BTN_MARKET, "資金", "當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK]


def test_help_script_ready_for_brother_video():
    first = chunk_telegram_html(HELP_TOPICS["guide"])[0]
    assert "第一次用" in first
    assert "直接打代號" in first
    assert "00981A" in first
    assert "先別追" in HELP_TOPICS["stock"]
    assert "開 LINE・傳這檔" in HELP_TOPICS["screen"]
    assert "一鍵傳 LINE" in HELP_TOPICS["screen"]
    assert "按錯" in HELP_TOPICS["oops"]
    hub = WayneTelegramBot.__new__(WayneTelegramBot)._hub_keyboard("2330")
    texts = [b.text for r in hub.inline_keyboard for b in r]
    assert texts[:5] == ["籌碼", "營收", "產業", "觀察", "記買入"]


def test_ten_personas_help_and_menu_clear_wrong_pending():
    """十種熟悉度亂按回報／連買後，按說明或 /menu 能導回。"""
    bot = _bot()
    bot.menu_cmd = AsyncMock()

    async def run():
        for name, uid, _codes in PERSONAS_10:
            actor = f"99:{uid}"
            bot._pending[actor] = "report"
            msg = _msg(99, uid, "說明")
            await bot.on_text(_update(msg), MagicMock())
            assert actor not in bot._pending, name
            bot.help_cmd.assert_awaited()
            bot.help_cmd.reset_mock()

            bot._pending[actor] = "fbuy:kind"
            menu_msg = _msg(99, uid, "/menu")
            await bot.on_text(_update(menu_msg), MagicMock())
            assert actor not in bot._pending, name
            bot.menu_cmd.assert_awaited()
            bot.menu_cmd.reset_mock()

    asyncio.run(run())


def test_ten_personas_each_menu_button_routes():
    bot = _bot()

    async def run():
        for _name, uid, _codes in PERSONAS_10:
            for label, handler in MENU_BUTTONS:
                msg = _msg(99, uid, label)
                await bot.on_text(_update(msg), MagicMock())
                getattr(bot, handler).assert_awaited()
                getattr(bot, handler).reset_mock()

    asyncio.run(run())


def test_empty_account_decision_card_asks_for_code():
    bot = _bot()
    bot._send_decision_card_quick = AsyncMock()
    msg = _msg(2, 9002)

    async def run():
        with patch("wayne_db.get_user_watchlist", return_value=[]):
            await WayneTelegramBot.decision_card_btn(bot, _update(msg), MagicMock())

    asyncio.run(run())
    bot._send_decision_card_quick.assert_not_awaited()
    html = "".join(str(c[0][0]) for c in msg.reply_html.await_args_list if c[0])
    assert "沒有上一檔" in html
    assert "四碼" in html or "代號" in html
