# -*- coding: utf-8 -*-
"""偉權 + 哥哥同時使用：重疊操作不互相洗版、不搶 pending、不覆蓋出圖。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import MENU_BTN_MARKET, MENU_BTN_STREAK, WayneTelegramBot

WAYNE_UID = 9001
BRO_UID = 9002


def _msg(uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
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
    from config import get_db_path
    from wayne_db import init_database

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    init_database(bot.db_path)
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
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._touch_user = MagicMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    return bot


def test_scratch_chart_paths_differ_for_two_users():
    bot = _bot()
    p1 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(WAYNE_UID))
    p2 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(BRO_UID))
    assert p1 != p2
    assert str(WAYNE_UID) in p1
    assert str(BRO_UID) in p2


@pytest.mark.parametrize("round_i", range(10))
def test_concurrent_buy_streak_wizards_isolated(round_i):
    """十輪：兩人同時走連買區不同路徑，pending 互不干擾。"""
    bot = _bot()
    kinds = ["外資", "投信", "外資+投信"]
    markets = ["上市", "上櫃"]
    w_kind = kinds[round_i % 3]
    b_kind = kinds[(round_i + 1) % 3]
    w_mkt = markets[round_i % 2]
    b_mkt = markets[(round_i + 1) % 2]
    kind_map = {"外資": "foreign", "投信": "trust", "外資+投信": "both"}
    mkt_map = {"上市": "TW", "上櫃": "TWO"}

    async def fake_days(message, uid, actor, kind, market):
        bot._pending[actor] = f"fbuy:days:{kind}:{market}"

    async def run():
        w_actor = f"{WAYNE_UID}:{WAYNE_UID}"
        b_actor = f"{BRO_UID}:{BRO_UID}"
        bot._pending[w_actor] = "fbuy:kind"
        bot._pending[b_actor] = "fbuy:kind"
        with patch.object(bot, "_streak_show_days", side_effect=fake_days):
            await bot._handle_buy_streak(_msg(WAYNE_UID, w_kind), str(WAYNE_UID), "fbuy:kind", w_kind, actor=w_actor)
            await bot._handle_buy_streak(_msg(BRO_UID, b_kind), str(BRO_UID), "fbuy:kind", b_kind, actor=b_actor)
            assert bot._pending[w_actor] == f"fbuy:mkt:{kind_map[w_kind]}"
            assert bot._pending[b_actor] == f"fbuy:mkt:{kind_map[b_kind]}"
            await bot._handle_buy_streak(_msg(WAYNE_UID, w_mkt), str(WAYNE_UID), bot._pending[w_actor], w_mkt, actor=w_actor)
            await bot._handle_buy_streak(_msg(BRO_UID, b_mkt), str(BRO_UID), bot._pending[b_actor], b_mkt, actor=b_actor)
        assert bot._pending[w_actor] == f"fbuy:days:{kind_map[w_kind]}:{mkt_map[w_mkt]}"
        assert bot._pending[b_actor] == f"fbuy:days:{kind_map[b_kind]}:{mkt_map[b_mkt]}"

    asyncio.run(run())


def test_wayne_fbuy_pending_survives_bro_market():
    bot = _bot()
    bot._pending[f"{WAYNE_UID}:{WAYNE_UID}"] = "fbuy:days:foreign:TW"
    bot.market_cmd = AsyncMock()

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, MENU_BTN_MARKET)), MagicMock())

    asyncio.run(run())
    assert bot._pending.get(f"{WAYNE_UID}:{WAYNE_UID}") == "fbuy:days:foreign:TW"
    bot.market_cmd.assert_awaited_once()


def test_both_can_run_screening_flag_independently():
    bot = _bot()
    bot._screening_running.add(f"{WAYNE_UID}:{WAYNE_UID}")
    assert f"{BRO_UID}:{BRO_UID}" not in bot._screening_running
    bot._screening_running.add(f"{BRO_UID}:{BRO_UID}")
    assert len(bot._screening_running) == 2


def test_second_user_screening_blocked_while_global_scan():
    """哥哥在跑全市場海選時，偉權再按不會啟第二趟掃描（避免互相拖慢）。"""
    bot = _bot()
    bot._screening_global_owner = f"{WAYNE_UID}:{WAYNE_UID}"
    bot.screener.run_full_screening = MagicMock()
    msg = _msg(BRO_UID, "海選")

    async def run():
        await bot._run_manual_screening(msg)

    asyncio.run(run())
    bot.screener.run_full_screening.assert_not_called()
    assert f"{BRO_UID}:{BRO_UID}" not in bot._screening_running
    texts = [str(c.args[0]) if c.args else str(c.kwargs.get("text", "")) for c in msg.reply_html.await_args_list + msg.reply_text.await_args_list]
    assert any("海選正在掃描" in t or "海選進行中" in t for t in texts)


def test_parallel_lookup_two_users():
    bot = _bot()
    done = {"w": [], "b": []}

    def fake_lookup(code, *a, **k):
        if str(code).strip() == "3105":
            return [{"stock_id": "3105", "stock_name": "穩懋", "close": 100.0, "market": "TWO"}]
        return [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "market": "TW"}]

    async def fake_locked(message, code, uid, actor, hits):
        if str(uid) == str(WAYNE_UID):
            done["w"].append(code)
        elif str(uid) == str(BRO_UID):
            done["b"].append(code)

    async def run():
        bot._send_card_to = WayneTelegramBot._send_card_to.__get__(bot, WayneTelegramBot)
        bot._send_card_to_locked = fake_locked
        with patch("bot_servers.lookup_stocks", side_effect=fake_lookup):
            await asyncio.gather(
                bot._send_card_to(_msg(WAYNE_UID), "3105", str(WAYNE_UID)),
                bot._send_card_to(_msg(BRO_UID), "2330", str(BRO_UID)),
            )

    asyncio.run(run())
    assert done["w"] == ["3105"]
    assert done["b"] == ["2330"]


@pytest.mark.parametrize("round_i", range(10))
def test_heavy_interleaved_streak_and_market(round_i):
    """十輪：兩人交錯連買 + 大盤，pending 與 global screening owner 不串。"""
    bot = _bot()
    bot.market_cmd = AsyncMock()
    bot._screening_global_owner = ""
    w_actor = f"{WAYNE_UID}:{WAYNE_UID}"
    b_actor = f"{BRO_UID}:{BRO_UID}"

    async def fake_show(message, uid, actor, kind, market, days, offset=0):
        bot._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"

    async def run():
        bot._pending[w_actor] = "fbuy:days:foreign:TW"
        await bot.on_text(_update(_msg(BRO_UID, MENU_BTN_MARKET)), MagicMock())
        assert bot._pending.get(w_actor) == "fbuy:days:foreign:TW"
        await bot._handle_buy_streak(
            _msg(WAYNE_UID, "6"), str(WAYNE_UID), "fbuy:days:foreign:TW", "6", actor=w_actor
        )
        assert bot._pending.get(w_actor, "").startswith("fbuy:pick:")

    with patch.object(bot, "_streak_show_stocks", side_effect=fake_show):
        asyncio.run(run())


def test_last_card_per_uid_not_shared():
    bot = _bot()
    bot._remember_card(str(WAYNE_UID), "3105")
    bot._remember_card(str(BRO_UID), "2330")
    assert bot._last_card[str(WAYNE_UID)] == "3105"
    assert bot._last_card[str(BRO_UID)] == "2330"


def test_menu_layout_cache_per_uid():
    bot = _bot()
    bot._mark_menu_layout_ok(str(WAYNE_UID))
    assert bot._menu_layout_ok(str(WAYNE_UID))
    assert not bot._menu_layout_ok(str(BRO_UID))


@pytest.mark.parametrize("round_i", range(10))
def test_interleaved_main_menu_buttons(round_i):
    """十輪交錯按主選單：各自 handler，pending 不串。"""
    bot = _bot()
    labels = [MENU_BTN_MARKET, MENU_BTN_STREAK, "持股", "觀察", "資金"]
    w_label = labels[round_i % len(labels)]
    b_label = labels[(round_i + 2) % len(labels)]
    for attr in ("market_cmd", "streak_cmd", "portfolio_cmd", "watch_cmd", "flow_cmd"):
        setattr(bot, attr, AsyncMock())
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{getattr(m,'chat_id',0)}:{u}")

    async def run():
        bot._pending[f"{WAYNE_UID}:{WAYNE_UID}"] = f"buy:2330"
        await bot.on_text(_update(_msg(WAYNE_UID, w_label)), MagicMock())
        assert bot._pending.get(f"{WAYNE_UID}:{WAYNE_UID}") in (None, f"buy:2330") or w_label == "持股"
        await bot.on_text(_update(_msg(BRO_UID, b_label)), MagicMock())

    asyncio.run(run())
