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
            # 主路徑：LOADING reply 必須早於 cancel／鍵盤 DB／掃描
            load_i = src.index("self._screening_progress_text(0)")
            assert load_i < src.index("await self._begin_actor_op")
            assert load_i < src.index("await self._dismiss_menu_transients")
            assert load_i < src.index("hub = self._reply_menu")
            assert load_i < src.index("build_and_cache_full_screening")
            assert "load_cached_full_screening" in src
            assert "build_and_cache_full_screening" in src
            assert "screen_timeout_s = 180.0" in src
            assert "超過 3 分鐘" in src
            assert "會自動推" in src
            continue
        assert "_start_plain_wait" in src or "_wait_bubble" in src, name
        assert needle in src, name
        if name == "flow_cmd":
            # LOADING 必須先於 enter_main_menu／DB；結束不准沉默。
            assert src.index("_start_plain_wait") < src.index("_enter_main_menu")
            assert "to_thread(_build_flow_html)" in src or "_build_flow_html" in src
            assert "目前沒有可顯示的資金輪動" in src
            assert "這次沒送出內容" in src
        if name == "_run_emerging_screening":
            wait_i = src.index("await self._start_plain_wait")
            assert wait_i < src.index("hub = self._reply_menu")


def test_manual_screening_loading_before_screen_work(monkeypatch):
    """按海選：第一則 Telegram 回覆必須是 LOADING，且早於 begin／DB 鍵盤／掃描。"""
    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: None
    )
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
    order: list[str] = []

    async def _slow_begin(actor, kind):
        order.append("begin")
        await asyncio.sleep(0.05)
        bot._actor_op_gen[str(actor)] = 1
        bot._actor_op_kind[str(actor)] = str(kind)
        return 1

    def _slow_menu(uid=""):
        order.append("reply_menu")
        return None

    bot._begin_actor_op = _slow_begin
    bot._reply_menu = _slow_menu
    bot._actor_key = MagicMock(return_value="u1")
    bot._menu_uid_from_message = MagicMock(return_value="u1")
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(
        side_effect=AssertionError("no bare full")
    )
    bot.db_path = "data/wayne_market.db"

    def _build(_db=None):
        order.append("screen")
        return {"as_of": "20261004", "results": {}, "payload": []}

    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "screening_engine.build_and_cache_full_screening", _build
    )
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()

    async def _reply_text(*args, **kwargs):
        order.append("loading")
        return status

    msg.reply_text = AsyncMock(side_effect=_reply_text)

    async def run():
        await bot._run_manual_screening(msg, "u1")

    asyncio.run(run())
    assert order[0] == "loading"
    assert "LOADING" in str(msg.reply_text.await_args_list[0].args[0])
    assert order.index("loading") < order.index("begin")
    assert order.index("loading") < order.index("reply_menu")
    assert order.index("loading") < order.index("screen")
    bot._reply_screening_payload.assert_awaited()


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


def test_manual_screening_fail_sends_error_not_blank(monkeypatch):
    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "screening_engine.build_and_cache_full_screening",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
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
    bot.screener.run_full_screening = MagicMock(side_effect=AssertionError("no bare full"))
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


def test_manual_screening_prefers_cache(monkeypatch):
    """有當日快照時不准打 run_full_screening。"""
    cached = {
        "status": "success",
        "as_of": "20261002",
        "date": "20261002",
        "results": {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100}]},
        "from_cache": True,
        "message": "cache",
    }
    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: cached
    )
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
    bot.screener.run_full_screening = MagicMock(side_effect=AssertionError("no full scan"))
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        await bot._run_manual_screening(msg, "u1")

    asyncio.run(run())
    bot.screener.run_full_screening.assert_not_called()
    bot._reply_screening_payload.assert_awaited()
    sent = bot._reply_screening_payload.await_args.args[1]
    assert sent.get("from_cache") is True
    assert sent.get("as_of") == "20261002"


def test_flow_cmd_loading_first_and_never_silent():
    """資金輪動：LOADING 先於重活；空／逾時／送失敗都有中文句。"""
    from unittest.mock import patch

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot._pending = {}
    bot._keyboard = MagicMock(return_value=None)
    order: list[str] = []

    async def track_wait(message, *, text_fn):
        order.append("wait")
        assert "LOADING" in text_fn(0)
        assert "資金輪動進行中" in text_fn(0)
        return MagicMock(), asyncio.Event(), asyncio.create_task(asyncio.sleep(0))

    async def track_enter(*_a, **_k):
        order.append("enter")
        return "u1"

    bot._start_plain_wait = AsyncMock(side_effect=track_wait)
    bot._stop_plain_wait = AsyncMock()
    bot._enter_main_menu = AsyncMock(side_effect=track_enter)
    msg = MagicMock()
    msg.reply_html = AsyncMock()
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.message = msg
    update.effective_user = MagicMock(id=1001)

    with patch("money_flow.format_flow_html", return_value="<b>資金</b>"), patch(
        "money_flow.resolve_flow_as_of", return_value=("20261002", "")
    ), patch("money_flow.sector_flow_ready", return_value=True):
        asyncio.run(WayneTelegramBot.flow_cmd(bot, update, MagicMock()))
    assert order[:2] == ["wait", "enter"]
    msg.reply_html.assert_awaited()
    bot._stop_plain_wait.assert_awaited()

    # 空字串 → 清楚無資料說明（不准沉默）
    msg.reply_html.reset_mock()
    msg.reply_text.reset_mock()
    order.clear()
    with patch("money_flow.format_flow_html", return_value=""), patch(
        "money_flow.resolve_flow_as_of", return_value=("", None)
    ), patch("money_flow.sector_flow_ready", return_value=False):
        asyncio.run(WayneTelegramBot.flow_cmd(bot, update, MagicMock()))
    html_blob = " ".join(str(c.args[0]) for c in msg.reply_html.await_args_list if c.args)
    text_blob = " ".join(str(c.args[0]) for c in msg.reply_text.await_args_list if c.args)
    assert "沒有可顯示的資金輪動" in html_blob or "沒有可顯示的資金輪動" in text_blob

    # 逾時 → 中文提示
    msg.reply_html.reset_mock()
    msg.reply_text.reset_mock()

    def _slow(*_a, **_k):
        import time as _t

        _t.sleep(0.2)
        return "<b>慢</b>"

    with patch("bot_servers._FLOW_HTML_TIMEOUT", 0.05), patch(
        "money_flow.format_flow_html", side_effect=_slow
    ), patch("money_flow.resolve_flow_as_of", return_value=("20261002", "")), patch(
        "money_flow.sector_flow_ready", return_value=True
    ), patch("trading_calendar.is_tw_equity_session", return_value=False):
        asyncio.run(WayneTelegramBot.flow_cmd(bot, update, MagicMock()))
    assert any(
        "載入逾時" in str(c.args[0]) for c in msg.reply_text.await_args_list if c.args
    )


def test_flow_menu_route_does_not_cancel_before_cmd():
    """主選單按資金輪動：不准在 flow_cmd 前 cancel（會拖掉立刻 LOADING）。"""
    src = inspect.getsource(WayneTelegramBot._on_text_bound)
    idx = src.find("MENU_BTN_FLOW_ALIASES")
    assert idx > 0
    chunk = src[idx : idx + 280]
    assert "flow_cmd" in chunk
    assert "_cancel_actor_ops" not in chunk
    # 第一則 LOADING：資金輪動必須早於 touch DB。
    assert src.find("MENU_BTN_FLOW_ALIASES") < src.find("self._touch_user")


def test_flow_first_telegram_reply_is_loading_not_busy():
    """按資金輪動：第一則氣泡必須是 LOADING，不准先出鎖／忙線句。"""
    from unittest.mock import patch

    from bot_servers import PHONE_BUSY, WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot._pending = {}
    bot._keyboard = MagicMock(return_value=None)
    bot._actor_op_gen = {}
    bot._actor_op_kind = {}
    bot._actor_waits = {}
    bot._magic_dismiss = AsyncMock()
    order: list[str] = []

    msg = MagicMock()

    async def reply_text(text, **_k):
        order.append(str(text))
        out = MagicMock()
        out.edit_text = AsyncMock()
        out.delete = AsyncMock()
        return out

    async def reply_html(text, **_k):
        order.append(str(text))
        return MagicMock()

    msg.reply_text = AsyncMock(side_effect=reply_text)
    msg.reply_html = AsyncMock(side_effect=reply_html)
    update = MagicMock()
    update.message = msg
    update.effective_user = MagicMock(id=1001, first_name="u")

    async def slow_touch(*_a, **_k):
        order.append("touch")

    async def slow_enter(*_a, **_k):
        order.append("enter")
        await asyncio.sleep(0.02)
        return "u1"

    bot._touch_user = MagicMock(side_effect=lambda *_a, **_k: order.append("touch"))
    bot._enter_main_menu = AsyncMock(side_effect=slow_enter)
    bot._start_plain_wait = WayneTelegramBot._start_plain_wait.__get__(bot, WayneTelegramBot)
    bot._stop_plain_wait = WayneTelegramBot._stop_plain_wait.__get__(bot, WayneTelegramBot)

    with patch("money_flow.format_flow_html", return_value="<b>資金</b>"), patch(
        "money_flow.resolve_flow_as_of", return_value=("20261002", "")
    ), patch("money_flow.sector_flow_ready", return_value=True):
        asyncio.run(WayneTelegramBot.flow_cmd(bot, update, MagicMock()))

    assert order, "沒有任何回覆"
    assert "LOADING" in order[0]
    assert "資金輪動進行中" in order[0]
    assert "已 0 秒" in order[0] or "已 0" in order[0]
    busy_at = next((i for i, t in enumerate(order) if "暫時沒跑完" in t), None)
    load_at = next(i for i, t in enumerate(order) if "LOADING" in t)
    assert busy_at is None or load_at < busy_at
    assert order.index("touch") > load_at
    assert order.index("enter") > load_at
    _ = PHONE_BUSY


def test_skip_handler_busy_ack_for_menu_and_flow():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    menu = MagicMock()
    menu.text = "/menu"
    flow = MagicMock()
    flow.text = "資金輪動"
    timed = type("TimedOut", (Exception,), {})()
    assert bot._skip_handler_busy_ack(
        MagicMock(effective_message=menu), timed
    )
    assert bot._skip_handler_busy_ack(
        MagicMock(effective_message=flow), RuntimeError("boom")
    )
    other = MagicMock()
    other.text = "2330"
    assert not bot._skip_handler_busy_ack(
        MagicMock(effective_message=other), RuntimeError("boom")
    )


def test_plain_wait_elapsed_starts_after_send():
    src = inspect.getsource(WayneTelegramBot._start_plain_wait)
    send_i = src.index("await message.reply_text")
    t0_i = src.rfind("t0 = time.monotonic()")
    assert send_i < t0_i


def test_biaoke_entry_has_loading_and_fail_text():
    """空白進飆大必須有 LOADING；失敗要有錯誤句。"""
    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_start_plain_wait" in src
    assert "PHONE_BUSY" in src
    assert "_begin_actor_op" in src
    assert "current=\"chart\" if q else \"reply\"" in src or 'current="chart" if q else "reply"' in src
    wait_i = src.index("wait_h = await self._start_plain_wait")
    assert wait_i < src.index("self._mark_menu_layout_ok")
    assert src.index("await self._begin_actor_op") < wait_i

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


def test_biaoke_advice_charts_progress_and_skip_reason(monkeypatch, tmp_path):
    """出圖階段 LOADING 帶 出圖中 done/total；失敗不准靜默，要講略過原因。"""
    from pathlib import Path

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "x.db")
    bot.charts_dir = str(tmp_path / "charts")
    Path(bot.charts_dir).mkdir(parents=True, exist_ok=True)
    bot._actor_op_gen = {"u1": 1}
    bot._actor_op_kind = {"u1": "biaoke"}
    bot._actor_waits = {}
    bot._actor_bg_tasks = {}
    bot._actor_key = MagicMock(return_value="u1")
    bot._biaoke_reply_menu = MagicMock(return_value=None)
    bot._scratch_chart_path = MagicMock(
        side_effect=lambda d, sid, kind, uid: str(Path(d) / f"{sid}-{kind}.png")
    )
    bot._png_looks_ok = MagicMock(return_value=False)
    bot._magic_dismiss = AsyncMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    first_bubble = {"txt": ""}

    async def _start_wait(message, *, text_fn, actor="", kind="", gen=0):
        first_bubble["txt"] = text_fn(0)
        return (status, asyncio.Event(), None)

    bot._start_plain_wait = AsyncMock(side_effect=_start_wait)
    bot._stop_plain_wait = AsyncMock()

    targets = [
        {
            "sid": "3081",
            "name": "聯亞",
            "do": "可接",
            "how": "剛脫離零",
            "evidence": "近5日+1%",
            "basis": "雙箭頭",
        },
        {
            "sid": "2330",
            "name": "台積電",
            "do": "等回測再接",
            "how": "等回測",
            "evidence": "官方柱",
            "basis": "雙箭頭",
        },
    ]

    def _targets(*_a, **_k):
        return list(targets)

    monkeypatch.setattr("biaoke_advisor.advice_chart_targets", _targets)
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.reply_photo = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.send_action = AsyncMock()

    async def run():
        await bot._send_biaoke_advice_charts(
            msg,
            "u1",
            ask="",
            actor="u1",
            kind="biaoke",
            gen=1,
            spoken_html='quote/3081.TWO quote/2330.TW',
        )

    asyncio.run(run())
    bot._start_plain_wait.assert_awaited()
    assert "出圖中 0/2" in first_bubble["txt"]
    assert "LOADING" in first_bubble["txt"]
    # 兩檔都圖檔不合格 → 各一則略過原因；不准靜默
    skip_texts = [
        str(c.args[0]) for c in msg.reply_text.await_args_list if c.args
    ]
    assert len(skip_texts) == 2
    assert all("結構圖略過" in t for t in skip_texts)
    assert any("3081" in t for t in skip_texts)
    assert any("2330" in t for t in skip_texts)
    bot._stop_plain_wait.assert_awaited()
    msg.reply_photo.assert_not_awaited()


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


def test_generation_cancels_stale_screen_delivery(monkeypatch):
    """換鍵 bump generation 後，海選過期結果不准送。"""
    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: None
    )
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

    monkeypatch.setattr(
        "screening_engine.build_and_cache_full_screening", lambda *_a, **_k: _slow_screen()
    )
    bot.screener = MagicMock()
    bot.screener.run_full_screening = MagicMock(side_effect=AssertionError("no bare full"))
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


def test_manual_screening_cache_miss_builds_and_saves(monkeypatch):
    """無快取時必須走 build_and_cache（會 save_screen_session），不准裸 run_full_screening。"""
    built = {"n": 0}

    def _build(_db=None):
        built["n"] += 1
        return {
            "status": "success",
            "as_of": "20261002",
            "date": "20261002",
            "from_cache": False,
            "results": {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 1}]},
            "payload": [{"html": "ok", "mark_key": "leave_zero", "picks": [("2330", "台積電")]}],
        }

    monkeypatch.setattr(
        "screening_engine.load_cached_full_screening", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "screening_engine.build_and_cache_full_screening", _build
    )
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
    bot.screener.run_full_screening = MagicMock(side_effect=AssertionError("no bare full"))
    bot.db_path = "data/wayne_market.db"
    msg = MagicMock()
    status = MagicMock()
    status.edit_text = AsyncMock()
    msg.reply_text = AsyncMock(return_value=status)

    async def run():
        await bot._run_manual_screening(msg, "u1")

    asyncio.run(run())
    assert built["n"] == 1
    bot.screener.run_full_screening.assert_not_called()
    bot._reply_screening_payload.assert_awaited()


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
    assert "_skip_handler_busy_ack" in src
    assert "PHONE_BUSY" in src
    assert "請先按 /start" in src
    skip = inspect.getsource(WayneTelegramBot._skip_handler_busy_ack)
    assert "CancelledError" in skip
    assert "ConcurrentUpdateError" in skip
    assert "MENU_BTN_FLOW_ALIASES" in skip
