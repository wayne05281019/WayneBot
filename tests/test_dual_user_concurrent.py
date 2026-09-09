# -*- coding: utf-8 -*-
"""偉權 + 哥哥同時使用：重疊操作不互相洗版、不搶 pending、不覆蓋出圖。"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import MENU_BTN_MARKET, MENU_BTN_STREAK, WayneTelegramBot

WAYNE_UID = 9001
BRO_UID = 9002


def _msg(uid: int, text: str = "", *, chat_id: int | None = None):
    cid = int(chat_id) if chat_id is not None else int(uid)
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=cid)
    message = MagicMock()
    message.chat_id = cid
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
    bot._lookup_op_state = {}
    bot._screening_running = set()
    bot._trade_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._menu_pin_msgs = {}
    bot._touch_user = MagicMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._enter_main_menu = AsyncMock()
    bot._reply_menu = MagicMock()
    bot._keyboard = MagicMock()
    bot._held_lots_for = MagicMock(return_value=None)
    bot._send_trade_journal = AsyncMock()
    bot._send_ai_desk_view = AsyncMock()
    bot._send_chips_to = AsyncMock()
    bot._send_industry = AsyncMock()
    bot._send_fund_to = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
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
    assert str(os.getpid()) in p1
    assert str(os.getpid()) in p2


def test_scratch_chart_paths_same_uid_still_unique():
    bot = _bot()
    p1 = bot._scratch_chart_path(bot.charts_dir, "2330", "nav", str(WAYNE_UID))
    p2 = bot._scratch_chart_path(bot.charts_dir, "2330", "nav", str(WAYNE_UID))
    assert p1 != p2


def test_owner_and_family_default_same_twelve_buttons_and_hub(tmp_path):
    """新帳號預設十二顆與查股圖下鈕跟擁有者同一套，不是另一個精簡機器人。"""
    from bot_servers import MENU_ROW1, MENU_ROW2, WayneTelegramBot
    from wayne_db import init_database

    db = str(tmp_path / "samekb.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb_w = bot._reply_menu(str(WAYNE_UID))
    kb_b = bot._reply_menu(str(BRO_UID))
    wayne = [[b.text for b in row] for row in kb_w.keyboard]
    bro = [[b.text for b in row] for row in kb_b.keyboard]
    assert wayne == bro == [list(MENU_ROW1), list(MENU_ROW2)]
    hub_w = [b.text for r in bot._hub_keyboard("2330").inline_keyboard for b in r]
    hub_b = [b.text for r in bot._hub_keyboard("2330").inline_keyboard for b in r]
    assert hub_w == hub_b
    assert "產業" in hub_w and "K線" in hub_w and "籌碼" in hub_w


def test_owner_compact_menu_does_not_shrink_brother(tmp_path):
    """偉權改精簡六顆，哥哥仍是完整十二顆。"""
    from bot_servers import MENU_COMPACT_ROWS, MENU_ROW1, MENU_ROW2, WayneTelegramBot
    from wayne_db import init_database

    db = str(tmp_path / "compactiso.db")
    init_database(db)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot._set_menu_compact(str(WAYNE_UID), True)
    wayne = [b.text for row in bot._reply_menu(str(WAYNE_UID)).keyboard for b in row]
    bro = [[b.text for b in row] for row in bot._reply_menu(str(BRO_UID)).keyboard]
    assert wayne == [t for row in MENU_COMPACT_ROWS for t in row]
    assert bro == [list(MENU_ROW1), list(MENU_ROW2)]


@pytest.mark.parametrize("round_i", range(10))
def test_concurrent_buy_streak_wizards_isolated(round_i):
    """十輪：兩人同時走連買區不同路徑，pending 互不干擾。"""
    bot = _bot()
    kinds = ["外資", "投信", "外資+投信"]
    w_kind = kinds[round_i % 3]
    b_kind = kinds[(round_i + 1) % 3]
    kind_map = {"外資": "foreign", "投信": "trust", "外資+投信": "both"}

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
        assert bot._pending[w_actor] == f"fbuy:days:{kind_map[w_kind]}:ALL"
        assert bot._pending[b_actor] == f"fbuy:days:{kind_map[b_kind]}:ALL"

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


def test_op_state_map_isolated_for_two_users():
    bot = _bot()
    w = f"{WAYNE_UID}:{WAYNE_UID}"
    b = f"{BRO_UID}:{BRO_UID}"
    bot._op_state_map()[w] = {"sent": [], "current": "card"}
    bot._op_state_map()[b] = {"sent": [], "current": "nav"}
    assert bot._lookup_op_state[w]["current"] == "card"
    assert bot._lookup_op_state[b]["current"] == "nav"


def test_ai_desk_button_isolated_for_brother_and_wayne():
    """偉權與哥哥同時按 AI倉：各自開模擬倉，不共用 pending。"""
    bot = _bot()
    bot._send_ai_desk_view = AsyncMock()
    bot._pending[f"{WAYNE_UID}:{WAYNE_UID}"] = "buy:2330"

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, "AI倉")), MagicMock())
        await bot.on_text(_update(_msg(WAYNE_UID, "AI倉")), MagicMock())

    asyncio.run(run())
    assert bot._send_ai_desk_view.await_count == 2
    uids = [c.args[1] for c in bot._send_ai_desk_view.await_args_list]
    assert uids == [str(BRO_UID), str(WAYNE_UID)]
    assert bot._pending.get(f"{WAYNE_UID}:{WAYNE_UID}") is None


SHARED_CHAT = 777


def test_bro_price_does_not_fill_wayne_buy():
    """哥哥打 68.5 不能幫偉權把記買入寫進去。"""
    bot = _bot()
    wayne = f"{WAYNE_UID}:{WAYNE_UID}"
    bot._pending[wayne] = "buy:2330"

    async def run():
        with patch("bot_servers.record_buy") as rb, patch(
            "bot_servers.lookup_stocks", return_value=[]
        ):
            await bot.on_text(_update(_msg(BRO_UID, "68.5")), MagicMock())
        return rb

    rb = asyncio.run(run())
    rb.assert_not_called()
    assert bot._pending.get(wayne) == "buy:2330"


def test_same_chat_bro_why_does_not_swallow_wayne_streak():
    """同一聊天室：偉權停在連買區，哥哥打為什麼跌只用哥哥上一檔。"""
    bot = _bot()
    wayne = f"{SHARED_CHAT}:{WAYNE_UID}"
    bro = f"{SHARED_CHAT}:{BRO_UID}"
    bot._pending[wayne] = "fbuy:kind"
    bot._last_card[str(WAYNE_UID)] = "2330"
    bot._last_card[str(BRO_UID)] = "3105"

    async def run():
        await bot.on_text(
            _update(_msg(BRO_UID, "為什麼跌", chat_id=SHARED_CHAT)), MagicMock()
        )

    asyncio.run(run())
    assert bot._pending.get(wayne) == "fbuy:kind"
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "3105"
    assert bro not in bot._pending


def test_same_chat_trade_lock_is_per_person():
    """偉權當沖進行中，哥哥仍可按當沖；同一人連按才擋。"""
    bot = _bot()
    bot._trade_running.add(f"{SHARED_CHAT}:{WAYNE_UID}")
    wayne_msg = _msg(WAYNE_UID, "當沖", chat_id=SHARED_CHAT)
    bro_msg = _msg(BRO_UID, "當沖", chat_id=SHARED_CHAT)

    async def run():
        await bot._run_trade_bucket(
            wayne_msg,
            bucket_key="day_trade",
            live_bucket="daytrade",
            title="x",
            subtitle="",
            topic="daytrade",
            status_text="查",
            menu_label="當沖",
            loader=lambda: [],
        )
        with patch("trading_calendar.is_tw_equity_session", return_value=False), patch(
            "trading_calendar.tw_session_phase", return_value="closed"
        ), patch("trading_calendar.daytrade_closed_title", return_value="休市"), patch(
            "trading_calendar.daytrade_closed_message", return_value="尚未開盤"
        ):
            await bot._run_trade_bucket(
                bro_msg,
                bucket_key="day_trade",
                live_bucket="daytrade",
                title="x",
                subtitle="",
                topic="daytrade",
                status_text="查",
                menu_label="當沖",
                loader=lambda: [],
            )

    asyncio.run(run())
    w_blob = " ".join(
        str(c.args[0]) for c in wayne_msg.reply_text.await_args_list if c.args
    )
    b_blob = " ".join(
        str(c.args[0]) for c in (bro_msg.reply_text.await_args_list + bro_msg.reply_html.await_args_list) if c.args
    )
    assert "進行中" in w_blob
    assert "進行中" not in b_blob
    assert "休市" in b_blob or "尚未開盤" in b_blob


def test_brother_ai_desk_does_not_clear_wayne_buy():
    bot = _bot()
    bot._send_ai_desk_view = AsyncMock()
    wayne = f"{WAYNE_UID}:{WAYNE_UID}"
    bot._pending[wayne] = "buy:2330"

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, "AI倉")), MagicMock())

    asyncio.run(run())
    bot._send_ai_desk_view.assert_awaited_once()
    assert bot._send_ai_desk_view.await_args.args[1] == str(BRO_UID)
    assert bot._pending.get(wayne) == "buy:2330"


def test_em_last_card_not_shared_for_chips():
    """偉權查興櫃後，哥哥打籌碼仍用哥哥上一檔，不沿用偉權的 3595。"""
    bot = _bot()
    bot._send_chips_to = AsyncMock()
    bot._remember_card(str(WAYNE_UID), "3595")
    bot._remember_card(str(BRO_UID), "1413")

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, "籌碼")), MagicMock())

    asyncio.run(run())
    bot._send_chips_to.assert_awaited()
    assert bot._send_chips_to.await_args.args[1] == "1413"
    assert bot._last_card[str(WAYNE_UID)] == "3595"


@pytest.mark.parametrize("round_i", range(8))
def test_concurrent_screen_universe_isolated(round_i):
    """兩人同時按海選：一人上市櫃、一人興櫃，pending 不得互洗。"""
    bot = _bot()
    listed = []
    emerging = []

    async def fake_listed(message):
        listed.append(int(message.from_user.id))

    async def fake_em(message):
        emerging.append(int(message.from_user.id))

    async def run():
        w_actor = f"{WAYNE_UID}:{WAYNE_UID}"
        b_actor = f"{BRO_UID}:{BRO_UID}"
        bot._pending[w_actor] = "screen:uni"
        bot._pending[b_actor] = "screen:uni"
        with patch.object(bot, "_run_manual_screening", side_effect=fake_listed), patch.object(
            bot, "_run_emerging_screening", side_effect=fake_em
        ):
            if round_i % 2 == 0:
                await bot._handle_screen_pick(
                    _msg(WAYNE_UID, "上市櫃"), str(WAYNE_UID), "上市櫃", actor=w_actor
                )
                await bot._handle_screen_pick(
                    _msg(BRO_UID, "興櫃"), str(BRO_UID), "興櫃", actor=b_actor
                )
                assert listed == [WAYNE_UID]
                assert emerging == [BRO_UID]
            else:
                await bot._handle_screen_pick(
                    _msg(BRO_UID, "上市櫃"), str(BRO_UID), "上市櫃", actor=b_actor
                )
                await bot._handle_screen_pick(
                    _msg(WAYNE_UID, "興櫃"), str(WAYNE_UID), "興櫃", actor=w_actor
                )
                assert listed == [BRO_UID]
                assert emerging == [WAYNE_UID]
        assert w_actor not in bot._pending
        assert b_actor not in bot._pending

    asyncio.run(run())


def test_streak_home_does_not_clear_other_user_pending():
    bot = _bot()
    wayne = f"{WAYNE_UID}:{WAYNE_UID}"
    bro = f"{BRO_UID}:{BRO_UID}"
    bot._pending[wayne] = "fbuy:days:foreign:ALL"
    bot._pending[bro] = "fbuy:kind:ALL"
    bot._reply_menu = MagicMock()

    async def run():
        await bot._restore_main_menu(_msg(WAYNE_UID, "回主選單"), str(WAYNE_UID))

    asyncio.run(run())
    assert wayne not in bot._pending
    assert bot._pending.get(bro) == "fbuy:kind:ALL"


def test_industry_callback_passes_clicker_uid():
    import inspect

    src = inspect.getsource(WayneTelegramBot.on_callback)
    assert "_send_industry(q.message, data[2:].strip(), str(q.from_user.id))" in src
    ind = inspect.getsource(WayneTelegramBot._send_industry)
    assert "uid or self._uid_from_message" in ind
    nav = inspect.getsource(WayneTelegramBot._send_navigation_chart)
    assert "_scratch_chart_path" in nav
    twii = inspect.getsource(WayneTelegramBot._send_market_kline)
    assert "_scratch_chart_path" in twii
    assert "twii_kline_" not in twii
    assert "KD" not in twii


def test_industry_scratch_path_uses_passed_uid_not_message_user():
    bot = _bot()
    captured = []

    def fake_png(code, db, path, **kw):
        captured.append(path)
        return ""

    async def run():
        msg = _msg(555)
        with patch("bot_servers.lookup_stocks", return_value=[{"stock_id": "2330"}]), patch(
            "industry_card.render_industry_png", side_effect=fake_png
        ), patch("industry_brief.format_industry_html", return_value="x"):
            await WayneTelegramBot._send_industry(bot, msg, "2330", str(WAYNE_UID))
            await WayneTelegramBot._send_industry(bot, msg, "2330", str(BRO_UID))

    asyncio.run(run())
    assert len(captured) == 2
    assert str(WAYNE_UID) in captured[0]
    assert str(BRO_UID) in captured[1]
    assert "555" not in captured[0]
    assert captured[0] != captured[1]


def test_wayne_buy_pending_survives_bro_screen_and_lookup():
    bot = _bot()
    wayne = f"{WAYNE_UID}:{WAYNE_UID}"
    bot._pending[wayne] = "buy:2330"
    bot.screen_cmd = AsyncMock()
    bot._reply_card = AsyncMock()

    async def run():
        await bot.on_text(_update(_msg(BRO_UID, "海選")), MagicMock())
        with patch(
            "bot_servers.lookup_stocks",
            return_value=[{"stock_id": "2330", "stock_name": "台積電"}],
        ), patch("bot_servers.hits_need_picker", return_value=False):
            await bot.on_text(_update(_msg(BRO_UID, "2330")), MagicMock())

    asyncio.run(run())
    assert bot._pending.get(wayne) == "buy:2330"
    bot.screen_cmd.assert_awaited_once()


def test_render_stock_pack_paths_include_uid_and_pid():
    import inspect

    from wayne_navigator import render_stock_pack, unique_chart_path

    src = inspect.getsource(render_stock_pack)
    assert "unique_chart_path" in src
    assert "{sid}_glance.png" not in src
    assert "{sid}_card.png" not in src
    p1 = unique_chart_path("data/charts", "2330", "glance", str(WAYNE_UID))
    p2 = unique_chart_path("data/charts", "2330", "glance", str(BRO_UID))
    assert p1 != p2
    assert str(WAYNE_UID) in p1
    assert str(BRO_UID) in p2
    assert str(os.getpid()) in p1

