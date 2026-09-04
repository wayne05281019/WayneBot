# -*- coding: utf-8 -*-
"""十人格 × 十子人格（100 人）同時查股：pending／出圖／查股結果互不干擾。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import WayneTelegramBot
from persona_grid import PERSONAS_10, SUBS_PER_PERSONA, iter_grid, sub_uid

GRID = iter_grid()
ALL_UIDS = [row[3] for row in GRID]
UID_TO_CODE = {row[3]: row[4] for row in GRID}


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


def test_sub_uid_grid_covers_100():
    assert len(GRID) == 100
    assert len(set(ALL_UIDS)) == 100
    assert sub_uid(9001, 1) == 9101
    assert sub_uid(9001, 10) == 9110
    assert sub_uid(9010, 10) == 10010


def test_100_scratch_chart_paths_all_unique():
    bot = _bot()
    paths = [bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(uid)) for uid in ALL_UIDS]
    assert len(set(paths)) == 100


def test_100_parallel_lookups_each_get_own_code():
    bot = _bot()
    results: dict[int, str] = {}

    def fake_lookup(code, *a, **k):
        c = str(code).strip()
        return [{"stock_id": c, "stock_name": f"N{c}", "close": 100.0, "market": "TW"}]

    async def fake_locked(message, code, uid, actor, hits):
        results[int(uid)] = str(code).strip()

    async def run():
        bot._send_card_to = WayneTelegramBot._send_card_to.__get__(bot, WayneTelegramBot)
        bot._send_card_to_locked = fake_locked
        with patch("bot_servers.lookup_stocks", side_effect=fake_lookup):
            await asyncio.gather(
                *[
                    bot._send_card_to(_msg(uid), UID_TO_CODE[uid], str(uid))
                    for uid in ALL_UIDS
                ]
            )

    asyncio.run(run())
    assert len(results) == 100
    for uid, expected in UID_TO_CODE.items():
        assert results[uid] == expected


@pytest.mark.parametrize("round_i", range(10))
def test_100_pending_states_no_cross_bleed(round_i):
    bot = _bot()
    for name, parent_uid, sub_i, uid, code in GRID:
        actor = f"{uid}:{uid}"
        bot._pending[actor] = f"buy:{code}:{round_i}"

    for name, parent_uid, sub_i, uid, code in GRID:
        actor = f"{uid}:{uid}"
        assert bot._pending[actor] == f"buy:{code}:{round_i}"

    # 任一人改自己的 pending，不影響其他人
    victim = GRID[round_i * 10][3]
    actor_v = f"{victim}:{victim}"
    bot._pending[actor_v] = "sell:9999"
    assert bot._pending[actor_v] == "sell:9999"
    others = [row[3] for row in GRID if row[3] != victim]
    for uid in others[:20]:
        actor = f"{uid}:{uid}"
        assert not bot._pending[actor].startswith("sell:9999")


@pytest.mark.parametrize("round_i", range(10))
def test_persona_groups_parallel_streak_wizards(round_i):
    """十輪：十人格各派一子人格同時走連買區，pending 依父系路徑隔離。"""
    bot = _bot()
    kinds = ["外資", "投信", "外資+投信"]
    markets = ["上市", "上櫃"]
    kind_map = {"外資": "foreign", "投信": "trust", "外資+投信": "both"}
    mkt_map = {"上市": "TW", "上櫃": "TWO"}

    async def fake_days(message, uid, actor, kind, market):
        bot._pending[actor] = f"fbuy:days:{kind}:{market}"

    async def one_persona(name, parent_uid, sub_i):
        uid = sub_uid(parent_uid, (sub_i + round_i) % SUBS_PER_PERSONA + 1)
        actor = f"{uid}:{uid}"
        kind = kinds[(parent_uid + round_i) % 3]
        market = markets[(parent_uid + round_i) % 2]
        bot._pending[actor] = "fbuy:kind"
        with patch.object(bot, "_streak_show_days", side_effect=fake_days):
            await bot._handle_buy_streak(_msg(uid, kind), str(uid), "fbuy:kind", kind, actor=actor)
            await bot._handle_buy_streak(
                _msg(uid, market), str(uid), bot._pending[actor], market, actor=actor
            )
        return actor, kind_map[kind], mkt_map[market]

    async def run():
        reps = [(name, parent_uid) for name, parent_uid, _ in PERSONAS_10]
        tasks = [one_persona(name, parent_uid, round_i % SUBS_PER_PERSONA) for name, parent_uid in reps]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run())
    for actor, kind, market in results:
        assert bot._pending[actor] == f"fbuy:days:{kind}:{market}"


def test_last_card_100_users_isolated():
    bot = _bot()
    for uid, code in UID_TO_CODE.items():
        bot._remember_card(str(uid), code)
    for uid, code in UID_TO_CODE.items():
        assert bot._last_card[str(uid)] == code


def test_lookup_ctx_keys_per_user():
    bot = _bot()
    for uid, code in list(UID_TO_CODE.items())[:50]:
        bot._cache_lookup_ctx(str(uid), code, [{"x": 1}])
    for uid, code in list(UID_TO_CODE.items())[:50]:
        hit = bot._get_lookup_ohlc(str(uid), code)
        assert hit is not None
