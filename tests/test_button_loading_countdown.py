"""全鍵 LOADING／倒數＋魔法消逝（UX，不改買訊／出圖公式）。"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

from bot_servers import WayneTelegramBot


def test_wait_bubble_has_loading_and_elapsed():
    txt0 = WayneTelegramBot._wait_bubble("大盤進行中", 0, now="讀指數", fill_sec=20.0)
    txt12 = WayneTelegramBot._wait_bubble("大盤進行中", 12, now="讀指數", fill_sec=20.0)
    assert "LOADING" in txt0
    assert "大盤進行中" in txt0
    assert "□" * 10 in txt0
    assert "已 0 秒" in txt0 or "已 0" in txt0
    assert "■" in txt12
    assert "已 12 秒" in txt12
    assert "好了這則會消失" in txt0
    for ch in ("⏳", "🔄", "📊", "🔍"):
        assert ch not in txt0


def test_magic_dismiss_frames_no_emoji():
    frames = WayneTelegramBot._magic_dismiss_frames()
    assert len(frames) >= 2
    blob = "\n".join(frames)
    assert "魔法收起" in blob or "完成" in blob
    for ch in ("⏳", "🔄", "✨", "🪄"):
        assert ch not in blob


def test_stop_plain_wait_uses_magic_dismiss():
    src = inspect.getsource(WayneTelegramBot._stop_plain_wait)
    assert "_magic_dismiss" in src


def test_menu_slow_paths_start_plain_wait():
    paths = {
        "market_cmd": "大盤進行中",
        "flow_cmd": "資金輪動進行中",
        "portfolio_cmd": "持股進行中",
        "watch_cmd": "觀察進行中",
        "_run_trade_bucket": "進行中",
        "_run_emerging_screening": "興櫃海選進行中",
        "_run_winrate_buypoint": "勝率買點進行中",
        "_run_leave_zero_now": "剛脫離零進行中",
        "_send_dongzhu_page": "洞燭先機進行中",
        "_run_manual_screening": "_screening_progress_text",
        "_send_ai_desk_view": "AI倉進行中",
        "_run_ai_now": "AI倉進行中",
        "_streak_show_days": "連買區進行中",
        "_send_trade_journal": "成交進行中",
    }
    for name, needle in paths.items():
        src = inspect.getsource(getattr(WayneTelegramBot, name))
        if name == "_run_manual_screening":
            assert needle in src
            continue
        assert "_start_plain_wait" in src or "_wait_bubble" in src, name
        assert needle in src, name


def test_magic_dismiss_edits_then_deletes():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.delete = AsyncMock()

    async def run():
        await bot._magic_dismiss(msg)

    asyncio.run(run())
    assert msg.edit_text.await_count >= 2
    msg.delete.assert_awaited()


def test_magic_dismiss_delete_fail_not_blank():
    """delete 失敗時不准留下空白「·」。"""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.delete = AsyncMock(side_effect=RuntimeError("gone"))

    async def run():
        await bot._magic_dismiss(msg)

    asyncio.run(run())
    last = msg.edit_text.await_args_list[-1].args[0]
    assert "·" != last.strip()
    assert "等待框已結束" in last


def test_stop_plain_wait_clears_on_success_and_fail():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._magic_dismiss = AsyncMock()

    async def run_ok():
        stop = asyncio.Event()

        async def _tick():
            stop.set()

        task = asyncio.create_task(_tick())
        await bot._stop_plain_wait(MagicMock(), stop, task)
        bot._magic_dismiss.assert_awaited()

    async def run_none():
        bot._magic_dismiss.reset_mock()
        await bot._stop_plain_wait(None, None, None)
        bot._magic_dismiss.assert_awaited_once_with(None)

    asyncio.run(run_ok())
    asyncio.run(run_none())


def test_manual_screening_fail_sends_error_not_blank():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._actor_op_gen = {}
    bot._actor_op_kind = {}
    bot._actor_waits = {}
    bot._actor_bg_tasks = {}
    bot._dismiss_menu_transients = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot._dismiss_progress_now = AsyncMock()
    bot._magic_dismiss = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = MagicMock(return_value="u1")
    bot._menu_uid_from_message = MagicMock(return_value="u1")
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(side_effect=RuntimeError("boom"))
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    status.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        await bot._run_manual_screening(msg, "u1")

    asyncio.run(run())
    texts = [c.args[0] for c in msg.reply_text.await_args_list if c.args]
    assert any("暫時沒跑完" in str(t) or "LOADING" in str(t) for t in texts)
    assert any("暫時沒跑完" in str(t) for t in texts)
    bot._dismiss_progress_now.assert_awaited()
    assert "u1" not in bot._screening_running
    assert bot._screening_global_owner == ""


def test_manual_screening_success_dismisses_loading():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._actor_op_gen = {}
    bot._actor_op_kind = {}
    bot._actor_waits = {}
    bot._actor_bg_tasks = {}
    bot._dismiss_menu_transients = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot._dismiss_progress_now = AsyncMock()
    bot._magic_dismiss = AsyncMock()
    bot._reply_screening_payload = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = MagicMock(return_value="u1")
    bot._menu_uid_from_message = MagicMock(return_value="u1")
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(return_value={"as_of": "20261004"})
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        await bot._run_manual_screening(msg, "u1")

    asyncio.run(run())
    bot._reply_screening_payload.assert_awaited()
    bot._dismiss_progress_now.assert_awaited()
    assert "u1" not in bot._screening_running


def test_biaoke_entry_has_loading_and_fail_text():
    """空白進飆大必須有 LOADING；失敗要有錯誤句。"""
    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_start_plain_wait" in src
    assert "PHONE_BUSY" in src
    assert "_begin_actor_op" in src
    assert "current=\"chart\" if q else \"reply\"" in src or 'current="chart" if q else "reply"' in src

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._biaoke_hist = {}
    bot._actor_op_gen = {}
    bot._actor_op_kind = {}
    bot._actor_waits = {}
    bot._screening_running = set()
    bot._magic_dismiss = AsyncMock()
    bot._enter_biaoke_chat = MagicMock()
    bot._mark_menu_layout_ok = MagicMock()
    bot._actor_key = MagicMock(return_value="u1")
    bot._uid_from_message = MagicMock(return_value="u1")
    bot._biaoke_reply_menu = MagicMock(return_value=None)
    bot._biaoke_hub_markup = MagicMock(return_value=None)
    bot._show_biaoke_leave_key = AsyncMock()
    bot._stop_plain_wait = AsyncMock()
    bot._start_plain_wait = AsyncMock(return_value=(MagicMock(), asyncio.Event(), None))
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock(side_effect=RuntimeError("tg down"))

    async def run():
        await bot._send_biaoke_page(msg, ask="", uid="u1")

    asyncio.run(run())
    bot._start_plain_wait.assert_awaited()
    assert msg.reply_text.await_count >= 1
    assert any(
        "暫時沒跑完" in str(c.args[0]) for c in msg.reply_text.await_args_list if c.args
    )


def test_start_and_back_clear_only_that_actor_pending():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {"a": "biaoke:chat", "b": "dongzhu"}
    bot._biaoke_hist = {"a": [{"ask": "x"}], "b": [{"ask": "y"}]}
    bot._clear_actor_menu_state("a")
    assert "a" not in bot._pending
    assert "b" in bot._pending
    assert "a" not in bot._biaoke_hist
    assert "b" in bot._biaoke_hist


def test_preboot_replay_detected():
    from datetime import datetime, timezone

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._boot_wall = 1_700_000_100.0
    msg = MagicMock()
    msg.date = datetime.fromtimestamp(1_700_000_000.0, tz=timezone.utc)
    assert bot._message_is_preboot_replay(msg) is True
    msg.date = datetime.fromtimestamp(1_700_000_200.0, tz=timezone.utc)
    assert bot._message_is_preboot_replay(msg) is False


def test_generation_cancels_stale_screen_delivery():
    """換鍵 bump generation 後，海選過期結果不准送。"""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._actor_op_gen = {}
    bot._actor_op_kind = {}
    bot._actor_waits = {}
    bot._actor_bg_tasks = {}
    bot._dismiss_menu_transients = AsyncMock()
    bot._pin_reply_menu = AsyncMock()
    bot._dismiss_progress_now = AsyncMock()
    bot._magic_dismiss = AsyncMock()
    bot._reply_screening_payload = AsyncMock()
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = MagicMock(return_value="u1")
    bot._menu_uid_from_message = MagicMock(return_value="u1")

    started = asyncio.Event()
    release = asyncio.Event()

    def _slow_screen():
        started.set()
        # block until test cancels via begin biaoke op
        import time as _t

        for _ in range(200):
            if release.is_set():
                break
            _t.sleep(0.01)
        return {"as_of": "20261004"}

    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(side_effect=_slow_screen)
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    status.delete = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        task = asyncio.create_task(bot._run_manual_screening(msg, "u1"))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        # 模擬使用者改按飆大／開始：作廢海選 generation
        await bot._begin_actor_op("u1", "biaoke")
        release.set()
        await task
        bot._reply_screening_payload.assert_not_awaited()
        bot._dismiss_progress_now.assert_awaited()

    asyncio.run(run())


def test_screen_and_biaoke_waits_are_separate_slots():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._actor_op_gen = {"u1": 1}
    bot._actor_op_kind = {"u1": "screen"}
    bot._actor_waits = {}
    bot._register_actor_wait(
        "u1", "screen", gen=1, wait_msg="S", stop=None, task=None
    )
    bot._actor_op_gen["u1"] = 2
    bot._actor_op_kind["u1"] = "biaoke"
    bot._register_actor_wait(
        "u1", "biaoke", gen=2, wait_msg="B", stop=None, task=None
    )
    assert bot._actor_waits["u1"]["screen"]["wait_msg"] == "S"
    assert bot._actor_waits["u1"]["biaoke"]["wait_msg"] == "B"
    assert bot._actor_op_alive("u1", "biaoke", 2)
    assert not bot._actor_op_alive("u1", "screen", 1)


def test_drop_pending_updates_true_on_boot():
    src = inspect.getsource(WayneTelegramBot.run_polling)
    assert "drop_pending_updates=True" in src


def test_menu_and_start_cancel_ops():
    """ /menu／/start／回主選單 必須 cancel 並立刻清 LOADING。"""
    for name in ("menu_cmd", "start_cmd", "_restore_main_menu"):
        src = inspect.getsource(getattr(WayneTelegramBot, name))
        assert "_cancel_actor_ops" in src, name


def test_cancel_dismisses_frozen_progress_and_blocks_bg_send():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._actor_op_gen = {"u1": 3}
    bot._actor_op_kind = {"u1": "biaoke"}
    bot._actor_waits = {}
    bot._actor_bg_tasks = {}
    bot._screening_running = set()
    status = MagicMock()
    status.delete = AsyncMock()
    status.edit_text = AsyncMock()
    stop = asyncio.Event()
    tick_ran = {"n": 0}

    async def _tick():
        tick_ran["n"] += 1
        await asyncio.Event().wait()

    task = None
    sent = {"photo": 0}

    async def run():
        nonlocal task
        task = asyncio.create_task(_tick())
        bot._register_actor_wait(
            "u1", "biaoke", gen=3, wait_msg=status, stop=stop, task=task
        )
        bot._track_actor_bg("u1", task)
        await bot._cancel_actor_ops("u1", dismiss=True)
        # 殘框必須被清掉
        status.delete.assert_awaited()
        assert bot._actor_op_kind.get("u1") == ""
        assert "u1" not in bot._actor_waits
        assert "u1" not in bot._actor_bg_tasks
        # 過期 generation 不准再送圖
        assert not bot._actor_op_alive("u1", "biaoke", 3)

        async def _fake_send():
            if bot._actor_op_alive("u1", "biaoke", 3):
                sent["photo"] += 1

        await _fake_send()
        assert sent["photo"] == 0

    asyncio.run(run())


def test_error_handler_skips_cancelled_no_start_prompt():
    src = inspect.getsource(WayneTelegramBot.run_polling)
    assert "CancelledError" in src
    assert "telegram_uid_allowed" in src
    assert "PHONE_BUSY" in src
    assert "請先按 /start" in src
