# -*- coding: utf-8 -*-
"""平常話路由到官方資料；三條槓不再放「原因」。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import TELEGRAM_BOT_COMMANDS, HELP_TOPICS, WayneTelegramBot


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
    message.reply_photo = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
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
    bot._trade_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._enter_main_menu = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot._send_decision_card_quick = AsyncMock()
    bot._send_chips_to = AsyncMock()
    bot._send_industry = AsyncMock()
    bot._send_fund_to = AsyncMock()
    bot.market_cmd = AsyncMock()
    bot.flow_cmd = AsyncMock()
    bot.screen_cmd = AsyncMock()
    bot.portfolio_cmd = AsyncMock()
    bot.watch_cmd = AsyncMock()
    bot.daytrade_cmd = AsyncMock()
    bot.overnight_cmd = AsyncMock()
    bot.streak_cmd = AsyncMock()
    bot.help_cmd = AsyncMock()
    bot.report_cmd = AsyncMock()
    bot._send_ai_desk_view = AsyncMock()
    bot._keyboard = MagicMock(return_value=None)
    return bot


def test_hamburger_omits_why():
    names = [name for name, _desc in TELEGRAM_BOT_COMMANDS]
    assert "why" not in names
    assert names[0] == "menu"
    assert ("why", "原因：語音或打字對出官方資料") not in TELEGRAM_BOT_COMMANDS
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "_why_hub_keyboard" not in src
    assert "_send_why_hub" not in src
    assert "why" not in HELP_TOPICS
    assert "三條槓「原因」" not in HELP_TOPICS["guide"]
    assert "／why" not in HELP_TOPICS["guide"]
    assert "／why" not in HELP_TOPICS["menu"]


def test_stale_why_command_tells_user_to_type_ticker():
    bot = _bot()
    msg = _msg(9, "/why")
    ctx = SimpleNamespace(args=[])

    async def run():
        await bot.why_cmd(_update(msg), ctx)

    asyncio.run(run())
    text = msg.reply_text.await_args.args[0]
    assert "打代號" in text
    assert bot._pending.get("99:9") != "why"


def test_on_text_why_drop_uses_last_card():
    bot = _bot()
    bot._last_card["9"] = "2330"
    msg = _msg(9, "為什麼跌")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "2330"
    htmls = [str(c.args[0]) for c in msg.reply_html.await_args_list if c.args]
    assert not any("新聞" in h and "沒有" in h for h in htmls)


def test_on_text_sell_with_name_looks_up():
    bot = _bot()
    msg = _msg(9, "台積電怎麼賣")

    async def run():
        with patch(
            "bot_servers.lookup_stocks",
            return_value=[{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
        ):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "2330"
    html = msg.reply_html.await_args.args[0]
    assert "如何賣" in html
    assert "不是買訊" in html


def test_on_text_foreign_maps_to_chips():
    bot = _bot()
    bot._last_card["9"] = "2454"
    msg = _msg(9, "外資")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_chips_to.assert_awaited()
    assert bot._send_chips_to.await_args.args[1] == "2454"


def test_on_text_screen_phrase_routes_to_screen():
    bot = _bot()
    msg = _msg(9, "今日海選名單")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot.screen_cmd.assert_awaited_once()
    bot._send_card_to.assert_not_awaited()


def test_on_text_no_cost_does_not_invent():
    bot = _bot()
    bot._last_card["9"] = "2330"
    msg = _msg(9, "主力成本")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    html = msg.reply_html.await_args.args[0]
    assert "沒有" in html
    assert "三大法人不是主力" in html
    bot._send_chips_to.assert_awaited()


def test_bare_code_still_looks_up_without_why_caption():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(9, "2330")

    async def run():
        with patch(
            "bot_servers.lookup_stocks",
            return_value=[{"stock_id": "2330", "stock_name": "台積電", "close": 100}],
        ):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._reply_card.assert_awaited_once()
    bot._send_card_to.assert_not_awaited()


def test_stale_why_pending_then_code_looks_up():
    bot = _bot()
    bot._reply_card = AsyncMock()
    bot._pending["99:9"] = "why"
    msg = _msg(9, "2454")

    async def run():
        with patch(
            "bot_servers.lookup_stocks",
            return_value=[{"stock_id": "2454", "stock_name": "聯發科", "close": 100}],
        ):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._reply_card.assert_awaited()
    assert bot._reply_card.await_args.args[1] == "2454"


def test_streak_pending_does_not_swallow_why_drop():
    bot = _bot()
    bot._pending["99:9"] = "fbuy:kind"
    bot._last_card["9"] = "2330"
    msg = _msg(9, "為什麼跌")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "2330"
    assert "99:9" not in bot._pending
    blob = " ".join(str(c.args[0]) for c in msg.reply_html.await_args_list if c.args)
    assert "請選" not in blob


def test_buy_pending_does_not_swallow_why_drop():
    bot = _bot()
    bot._pending["99:9"] = "buy:3595"
    bot._last_card["9"] = "3595"
    bot._held_lots_for = MagicMock(return_value=None)
    bot._keyboard = MagicMock(return_value=None)
    msg = _msg(9, "為什麼跌")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "3595"
    assert "99:9" not in bot._pending


def test_chengjiao_text_opens_journal():
    bot = _bot()
    bot._send_trade_journal = AsyncMock()
    msg = _msg(9, "成交")

    async def run():
        await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._send_trade_journal.assert_awaited()
    assert bot._send_trade_journal.await_args.kwargs.get("review") is False


def test_daytrade_lock_blocks_second_press():
    bot = _bot()
    bot._trade_running = {"99:9"}
    bot._reply_menu = MagicMock()
    msg = _msg(9, "當沖")

    async def run():
        await bot._run_trade_bucket(
            msg,
            bucket_key="day_trade",
            live_bucket="daytrade",
            title="x",
            subtitle="",
            topic="daytrade",
            status_text="x",
            menu_label="當沖",
            loader=lambda: [],
        )

    asyncio.run(run())
    text = str(msg.reply_text.await_args.args[0])
    assert "進行中" in text


def test_help_drops_why_topic():
    assert "why" not in HELP_TOPICS
    assert "三條槓" not in HELP_TOPICS["guide"]
    assert "三條槓" not in HELP_TOPICS["menu"]
