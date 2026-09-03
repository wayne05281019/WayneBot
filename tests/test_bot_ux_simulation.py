# -*- coding: utf-8 -*-
"""多角色 UX 模擬：深度用戶、初次用戶、不懂股票者 + 亂測輸入。"""
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
    message.reply_photo = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot(db_path: str = None):
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db_path or get_db_path()
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
    bot._enter_main_menu = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot.portfolio_engine.format_holdings_html = MagicMock(return_value="<b>持股</b> 空")
    return bot


# --- 隔離：哥哥 vs 偉權 不同 uid 不互搶 ---


def test_two_users_have_distinct_actor_keys():
    from bot_servers import WayneTelegramBot

    m1 = _msg(100, 111)
    m2 = _msg(100, 222)
    assert WayneTelegramBot._actor_key(m1) != WayneTelegramBot._actor_key(m2)
    assert WayneTelegramBot._actor_key(m1) == "100:111"


def test_lookup_fade_dismiss_only_own_actor():
    bot = _bot()
    m_a = MagicMock()
    m_a.delete = AsyncMock()
    m_b = MagicMock()
    m_b.delete = AsyncMock()
    bot._track_lookup_fade("1:10", m_a, "ack")
    bot._track_lookup_fade("1:20", m_b, "ack")

    async def run():
        await bot._dismiss_lookup_fades("1:10", roles={"ack"})

    asyncio.run(run())
    m_a.delete.assert_awaited_once()
    m_b.delete.assert_not_awaited()
    assert "1:20" in bot._lookup_fade_msgs


def test_last_card_per_user_not_shared():
    bot = _bot()
    bot._remember_card("u1", "3105")
    bot._remember_card("u2", "2330")
    assert bot._last_card["u1"] == "3105"
    assert bot._last_card["u2"] == "2330"


# --- 說明頁：換分類應原地改，不堆新訊息 ---


def test_help_topic_edits_in_place_on_callback():
    bot = _bot()
    message = _msg(1, 9)
    message.edit_text = AsyncMock()

    async def run():
        await bot._reply_help_topic(message, "row1", edit_target=message)

    asyncio.run(run())
    message.edit_text.assert_awaited_once()
    message.reply_html.assert_not_awaited()


# --- 查股報價：交易日不拿過期庫當現價 ---


def test_quote_header_refuses_stale_db_on_trading_day():
    from bot_servers import WayneTelegramBot

    bot = _bot()
    hits = [
        {
            "stock_id": "3105",
            "stock_name": "穩懋",
            "market": "OTC",
            "close": 492.0,
            "pct_change": 9.94,
            "quote_date": "20260901",
        }
    ]
    with patch("live_quote.is_lookup_trading_day", return_value=True), patch(
        "live_quote.fetch_lookup_quote", return_value=None
    ):
        html = bot._quote_header_html("3105", live_quote=None, hits=hits)
    assert "492" not in html
    assert "過期" in html or "無法取得" in html


def test_fetch_lookup_quote_uses_yahoo_on_trading_day():
    from live_quote import fetch_lookup_quote

    yahoo_rt = {
        "stock_id": "3105",
        "close": 469.5,
        "pct_change": -4.57,
        "change": -22.5,
        "yesterday_close": 492.0,
        "update_time": "13:30:00",
        "is_realtime": True,
        "source": "yahoo",
    }
    with patch("live_quote.fetch_mis_quote", return_value=None), patch(
        "live_quote.is_lookup_trading_day", return_value=True
    ), patch("live_quote.fetch_yahoo_tw_quote", return_value=yahoo_rt), patch(
        "live_quote.reconcile_lookup_quote", side_effect=lambda x, *a, **k: x
    ):
        rt = fetch_lookup_quote("3105", "OTC", __import__("config").get_db_path())
    assert rt is not None
    assert rt["close"] == 469.5


# --- 初次用戶：主選單按鈕只觸發對應功能 ---


def test_newbie_menu_buttons_do_not_fall_through_to_stock_lookup():
    bot = _bot()
    bot._send_portfolio = AsyncMock()
    bot._send_watch = AsyncMock()
    bot._ensure_reply_menu_if_needed = AsyncMock()
    bot.screen_cmd = AsyncMock()
    bot.help_cmd = AsyncMock()
    bot.menu_cmd = AsyncMock()

    async def run():
        for label, checker in (
            ("持股", bot._send_portfolio),
            ("觀察", bot._send_watch),
            ("海選", bot.screen_cmd),
            ("說明", bot.help_cmd),
            ("選單", bot.menu_cmd),
        ):
            checker.reset_mock()
            msg = _msg(5, 50, label)
            upd = _update(msg)
            ctx = MagicMock()
            await bot.on_text(upd, ctx)
            checker.assert_awaited_once()
            if label in ("持股", "觀察"):
                texts = [str(c[0][0]) for c in msg.reply_text.await_args_list if c[0]]
                assert texts and any("讀取" in t for t in texts)
            else:
                msg.reply_text.assert_not_awaited()

    asyncio.run(run())


# --- 不懂股票：亂打、空字、預留格不當查股 ---


def test_market_menu_button_shows_page():
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import MENU_BTN_MARKET

    bot = _bot()
    msg = _msg(1, 1, MENU_BTN_MARKET)
    msg.reply_html = AsyncMock()

    async def run():
        with patch.object(bot, "market_cmd", new_callable=AsyncMock) as market:
            await bot.on_text(_update(msg), MagicMock())
            market.assert_awaited_once()

    asyncio.run(run())


def test_help_keyboard_replaces_previous_message():
    bot = _bot()
    old = MagicMock()
    old.delete = AsyncMock()
    bot._help_msgs["1:9"] = [old]
    message = _msg(1, 9)

    async def run():
        await bot._reply_help_topic(message, "guide")

    asyncio.run(run())
    old.delete.assert_awaited_once()
    message.reply_html.assert_awaited()
    assert "1:9" in bot._help_msgs


def test_empty_input_is_silent():
    bot = _bot()
    msg = _msg(2, 2, "")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    msg.reply_text.assert_not_awaited()
    msg.reply_html.assert_not_awaited()


def test_chaos_inputs_get_friendly_not_found():
    bot = _bot()

    async def run():
        with patch("wayne_db.lookup_stocks", return_value=[]):
            for text in ("asdfgh", "股票", "123", "🙂"):
                msg = _msg(2, 2, text)
                await bot.on_text(_update(msg), MagicMock())
        return msg

    msg = asyncio.run(run())
    last = msg.reply_text.await_args_list[-1][0][0]
    assert "找不到" in last or "查詢失敗" in last


# --- 深度用戶：籌碼按鈕只出籌碼，不帶整包查股 ---


def test_chips_callback_only_sends_photo_not_full_card():
    bot = _bot()
    bot._send_card_to = AsyncMock()
    msg = _msg(3, 30)
    q = SimpleNamespace(
        data="h:2330",
        from_user=SimpleNamespace(id=30),
        message=msg,
        answer=AsyncMock(),
        get_bot=MagicMock(),
    )

    async def run():
        with patch("bot_servers.generate_chips_image", return_value="/tmp/x.png"), patch(
            "builtins.open", MagicMock()
        ):
            upd = SimpleNamespace(callback_query=q)
            await bot.on_callback(upd, MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_not_awaited()
    msg.reply_photo.assert_awaited()


# --- 說明完整性：新手詞典與 AI 路徑 ---


def test_help_guide_has_newbie_glossary_and_ai_path():
    from bot_servers import HELP_TOPICS

    guide = HELP_TOPICS["guide"]
    assert "小詞典" in guide
    assert "張" in guide
    assert "AI" in guide
    assert "持股" in HELP_TOPICS["ai"]
    assert "20:00" in HELP_TOPICS["ai"]


def test_compact_holdings_no_wide_padding():
    import re

    from config import get_db_path
    from portfolio_engine import PortfolioEngine

    engine = PortfolioEngine.__new__(PortfolioEngine)
    engine.db_path = get_db_path()
    html = engine.format_holdings_html(
        [{"stock_code": "2330", "stock_name": "台積電", "shares": 1, "cost_price": 500}],
        quotes_map={"2330": {"close": 520, "pct_change": 1.2}},
    )
    assert not re.search(r"<code>\s{3,}", html)
