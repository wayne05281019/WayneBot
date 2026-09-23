# -*- coding: utf-8 -*-
"""飆客獨立區：公開文可查、不進海選。"""
from bot_servers import (
    MENU_BTN_BIAOKE,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_FLOW,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_MARKET,
    MENU_BTN_SLOT,
    MENU_BTN_DONGZHU,
    MENU_ROW1,
    MENU_ROW2,
    TELEGRAM_BOT_COMMANDS,
    _normalize_menu_text,
    WayneTelegramBot,
)
from intent_router import parse_intent
from biaoke_desk import format_biaoke_desk_html, search_biaoke


def test_biaoke_button_is_plain_biaoda_top_right():
    assert MENU_BTN_BIAOKE == "飆大"
    assert MENU_BTN_BIAOKE_FACE == "飆大"
    assert "\u20dd" not in MENU_BTN_BIAOKE_FACE
    from bot_servers import MENU_BTN_BIAOKE_ALIASES, _circled_menu_label

    assert _circled_menu_label("飆大") in MENU_BTN_BIAOKE_ALIASES
    assert _normalize_menu_text(MENU_BTN_BIAOKE_FACE) == "飆大"
    assert MENU_ROW1[-1] == MENU_BTN_FLOW
    assert MENU_ROW1[-2] == MENU_BTN_MARKET
    assert MENU_ROW1[-3] == MENU_BTN_BIAOKE_FACE
    assert MENU_ROW2[-1] == MENU_BTN_DONGZHU
    assert MENU_ROW2[-2] == MENU_BTN_LEAVE_ZERO
    assert MENU_BTN_LEAVE_ZERO == "獲利為零"
    assert MENU_BTN_DONGZHU == "洞燭先機"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    face = [b.text for b in kb.keyboard[0]][-3]
    assert face == "飆大"
    assert "\u20dd" not in face
    assert _normalize_menu_text(face) == "飆大"
    assert [b.text for b in kb.keyboard[0]][-1] == MENU_BTN_FLOW
    assert [b.text for b in kb.keyboard[0]][-2] == MENU_BTN_MARKET
    assert [b.text for b in kb.keyboard[1]][-1] == MENU_BTN_DONGZHU
    assert [b.text for b in kb.keyboard[1]][-2] == MENU_BTN_LEAVE_ZERO


def test_year_end_2025_was_memory_not_pcb():
    html = search_biaoke("去年年底")
    assert "記憶體" in html
    assert "南亞科" in html or "群聯" in html
    assert "專心做記憶體" in html or "記憶體" in html
    assert "2025-12-17" in html or "2025-12-18" in html


def test_progress_page_is_independent():
    html = format_biaoke_desk_html()
    assert "海選" in html and "無關" in html
    assert "細微波" in html
    assert "費半" in html or "1-4" in html
    assert "量先價行" in html
    assert "量價背離" in html
    assert "不是買訊" not in html


def test_welcome_teaches_chat_not_a_menu():
    from biaoke_brain import WINDOW_OPEN
    from biaoke_desk import format_biaoke_html, format_biaoke_welcome_html

    html = format_biaoke_welcome_html()
    assert html == WINDOW_OPEN
    assert "打字" in html
    assert "語音" in html or "麥克風" in html
    assert "查個股" not in html
    assert "離開飆大" in html
    assert "點下面「大盤」" not in html
    assert "勤誠" not in html
    assert format_biaoke_html("") == html
    assert format_biaoke_html() == html
    see = format_biaoke_desk_html()
    assert "量先價行" in see
    assert "細微波" in see
    assert "問一檔" not in see


def test_intent_biaoke_keeps_query():
    hit = parse_intent("飆客 勤誠")
    assert hit.kind == "biaoke"
    assert "勤誠" in hit.query
    hit2 = parse_intent("飆大 去年年底")
    assert hit2.kind == "biaoke"
    assert "去年年底" in hit2.query
    hit3 = parse_intent(MENU_BTN_BIAOKE_FACE)
    assert hit3.kind == "biaoke"


def test_qincheng_hits_corpus_not_invented():
    html = search_biaoke("勤誠")
    assert "勤誠" in html
    assert "海選" not in html or "無關" in html or "公開" in html


def test_knowhow_shixinke_ticker_is_4916():
    from pathlib import Path

    text = Path("docs/expert_notes/飆客/knowhow.md").read_text(encoding="utf-8")
    assert "事欣科 **4916**" in text or "事欣科 4916" in text
    assert "3679 新至陞" in text
    src = Path("scripts/biaoke_verify_knowhow.py").read_text(encoding="utf-8")
    assert '("無人機 事欣科", "4916"' in src
    assert '("無人機 事欣科", "3679"' not in src


def test_circled_face_routes_like_biaoda():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {}
    bot._actor_key = MagicMock(return_value="1:1")
    bot._send_biaoke_page = AsyncMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.text = MENU_BTN_BIAOKE_FACE
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    bot._send_biaoke_page.assert_awaited()
    assert bot._pending["1:1"] == "biaoke:chat"


def test_biaoke_chat_keeps_pending_when_asking_unknown_name():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {"1:1": "biaoke:chat"}
    bot._pending_locks = {}
    bot._actor_key = MagicMock(return_value="1:1")
    bot._send_biaoke_page = AsyncMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.chat_id = 1
    msg.text = "藝舍-KY"
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    bot._send_biaoke_page.assert_awaited()
    assert "藝舍" in str(bot._send_biaoke_page.await_args.kwargs.get("ask") or "")
    assert bot._pending["1:1"] == "biaoke:chat"


def test_circled_face_routes_like_biaoda():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.text = MENU_BTN_SLOT
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    msg.reply_text.assert_not_awaited()
    msg.reply_html.assert_not_awaited()


def test_dongzhu_button_opens_page():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {}
    bot._actor_key = MagicMock(return_value="1:1")
    bot.dongzhu_cmd = AsyncMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.text = MENU_BTN_DONGZHU
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    bot.dongzhu_cmd.assert_awaited()


def test_dongzhu_keyboard_toggles_same_slot():
    from bot_servers import MENU_BTN_LEAVE_DONGZHU

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    bot._menu_compact_on = lambda uid="": False
    kb = bot._dongzhu_reply_menu()
    main = bot._reply_menu()
    assert len(kb.keyboard) == 2
    assert len(main.keyboard) == 2
    assert [b.text for b in kb.keyboard[1]][-1] == MENU_BTN_LEAVE_DONGZHU
    assert [b.text for b in main.keyboard[1]][-1] == MENU_BTN_DONGZHU
    assert [b.text for b in kb.keyboard[1]][:-1] == [b.text for b in main.keyboard[1]][:-1]
    assert [b.text for b in kb.keyboard[0]] == [b.text for b in main.keyboard[0]]
    assert MENU_BTN_LEAVE_DONGZHU == "離開洞燭先機"


def test_leave_dongzhu_clears_only_that_uid():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import MENU_BTN_LEAVE_DONGZHU

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {"11:11": "dongzhu", "22:22": "dongzhu"}
    bot._pending_locks = {}
    bot._menu_compact_on = MagicMock(return_value=False)
    bot._reply_menu = MagicMock(return_value=None)
    bot._mark_menu_layout_ok = MagicMock()

    def _actor(message, uid=""):
        return f"{message.chat_id}:{uid or message.from_user.id}"

    bot._actor_key = _actor

    user = SimpleNamespace(id=11, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.chat_id = 11
    msg.text = MENU_BTN_LEAVE_DONGZHU
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    assert "11:11" not in bot._pending
    assert bot._pending["22:22"] == "dongzhu"
    html = msg.reply_html.await_args.args[0]
    assert "已離開" in html
    assert "洞燭先機" in html


def test_biaoke_page_has_no_inside_menu():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_biaoke_inline" not in src
    assert "bk:see" not in src
    assert "怎麼觀察" not in src
    assert "問一檔" not in src
    assert "_biaoke_reply_menu" in src
    assert "_show_biaoke_leave_key" in src
    assert "還在飆大" in inspect.getsource(WayneTelegramBot._show_biaoke_leave_key)
    assert "reply_markup" in src
    assert "_mark_menu_layout_ok" in src
    assert "_start_plain_wait" in src
    assert "_stop_plain_wait" in src
    assert "_biaoke_progress_text" in src
    assert "format_latest_focus" in src
    assert "take_unread_digest" in src
    assert "reflow=False" in src
    assert "_send_biaoke_structure_chart" in src
    assert "_send_biaoke_origin_charts" not in src
    assert "create_task" in src
    assert "stock_picker_hits" in src
    assert "_biaoke_hits_keyboard" in src
    assert "_biaoke_hub_markup" in src
    assert "split_lead_detail" in src
    assert "bkdk:" in inspect.getsource(WayneTelegramBot._on_callback_bound)
    assert "_send_card_to" not in src
    struct_src = inspect.getsource(WayneTelegramBot._send_biaoke_structure_chart)
    assert "build_biaoke_structure_chart" in struct_src
    assert "ask=q" in struct_src
    assert "uid=uid" in struct_src
    assert "is_wave_question" in struct_src
    assert "_send_biaoke_twii_degree_chart" in struct_src
    origin = inspect.getsource(WayneTelegramBot._send_biaoke_origin_charts)
    assert "pick_charts" in origin
    assert "public_only" in origin
    card = inspect.getsource(WayneTelegramBot._send_card_to)
    assert "pick_charts" not in card
    assert "_send_biaoke_origin_charts" not in card
    assert not hasattr(WayneTelegramBot, "_biaoke_inline")
    whole = inspect.getsource(WayneTelegramBot)
    assert 'InlineKeyboardButton("怎麼觀察"' not in whole
    assert 'kind == "see"' in whole  # 舊訊息三顆還能答，只是不再畫選單
    assert 'kind == "leave"' in whole
    assert "MENU_BTN_LEAVE_BIAOKE" in whole
    from bot_servers import MENU_BTN_BIAOKE_FACE, MENU_BTN_LEAVE_BIAOKE, MENU_LAYOUT_VERSION

    assert MENU_BTN_BIAOKE_FACE == "飆大"
    assert MENU_BTN_LEAVE_BIAOKE == "離開飆大"
    assert "\u20dd" not in MENU_BTN_BIAOKE_FACE
    assert MENU_LAYOUT_VERSION == "28"


def test_two_uids_both_enter_biaoke_chat_without_submenu():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {}
    bot._pending_locks = {}
    bot._send_biaoke_page = AsyncMock()

    def _actor(message, uid=""):
        return f"{message.chat_id}:{uid or message.from_user.id}"

    bot._actor_key = _actor

    async def _run(uid: int):
        user = SimpleNamespace(id=uid, first_name="u")
        msg = MagicMock()
        msg.from_user = user
        msg.chat_id = uid
        msg.text = MENU_BTN_BIAOKE_FACE
        msg.reply_text = AsyncMock()
        msg.reply_html = AsyncMock()
        upd = SimpleNamespace(message=msg, effective_user=user)
        await bot.on_text(upd, MagicMock())

    asyncio.run(_run(11))
    asyncio.run(_run(22))
    assert bot._pending["11:11"] == "biaoke:chat"
    assert bot._pending["22:22"] == "biaoke:chat"
    assert bot._send_biaoke_page.await_count == 2


def test_biaoke_keyboard_toggles_same_slot():
    from bot_servers import MENU_BTN_LEAVE_BIAOKE

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    bot._menu_compact_on = lambda uid="": False
    kb = bot._biaoke_reply_menu()
    main = bot._reply_menu()
    assert len(kb.keyboard) == 2
    assert len(main.keyboard) == 2
    assert [b.text for b in kb.keyboard[0]][-3] == MENU_BTN_LEAVE_BIAOKE
    assert [b.text for b in kb.keyboard[0]][-2] == MENU_BTN_MARKET
    assert [b.text for b in kb.keyboard[0]][-1] == MENU_BTN_FLOW
    assert [b.text for b in main.keyboard[0]][-3] == "飆大"
    assert [b.text for b in main.keyboard[0]][-2] == MENU_BTN_MARKET
    assert [b.text for b in main.keyboard[0]][-1] == MENU_BTN_FLOW
    assert [b.text for b in kb.keyboard[0]][:-3] == [b.text for b in main.keyboard[0]][:-3]
    assert [b.text for b in kb.keyboard[1]] == [b.text for b in main.keyboard[1]]
    compact_on = WayneTelegramBot.__new__(WayneTelegramBot)
    compact_on.db_path = ""
    compact_on._menu_compact_on = lambda uid="": True
    compact_kb = compact_on._biaoke_reply_menu()
    assert len(compact_kb.keyboard) == 2
    assert [b.text for b in compact_kb.keyboard[0]][-3] == MENU_BTN_LEAVE_BIAOKE
    assert [b.text for b in compact_kb.keyboard[0]][-1] == MENU_BTN_FLOW


def test_send_biaoke_page_pushes_leave_key():
    """按飆大進去：最後一則必須掛「離開飆大」，不能只丟 Inline。"""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bot_servers import MENU_BTN_LEAVE_BIAOKE

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    bot._pending = {}
    bot._biaoke_hist = {}
    bot._enter_biaoke_chat = MagicMock()
    bot._mark_menu_layout_ok = MagicMock()
    bot._uid_from_message = MagicMock(return_value="11")
    bot._actor_key = MagicMock(return_value="11:11")
    bot._start_plain_wait = AsyncMock(return_value=(None, None, None))
    bot._stop_plain_wait = AsyncMock()
    bot._menu_compact_on = lambda uid="": False
    msg = MagicMock()
    msg.reply_html = AsyncMock()
    msg.reply_text = AsyncMock()
    html = "<b>飆大現在在講</b> 測試重點。不是買訊。"
    with patch("biaoke_digest.take_unread_digest", return_value=""), patch(
        "biaoke_digest.format_latest_focus", return_value=html
    ):
        asyncio.run(bot._send_biaoke_page(msg, uid="11"))
    assert msg.reply_html.await_count >= 1
    last_html_kb = msg.reply_html.await_args.kwargs.get("reply_markup")
    assert last_html_kb is None
    assert msg.reply_text.await_count >= 1
    leave = msg.reply_text.await_args
    assert "離開飆大" in str(leave.args[0])
    kb = leave.kwargs.get("reply_markup")
    assert kb is not None
    assert [b.text for b in kb.keyboard[0]][-3] == MENU_BTN_LEAVE_BIAOKE


def test_leave_biaoke_clears_only_that_uid():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import MENU_BTN_LEAVE_BIAOKE

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {"11:11": "biaoke:chat", "22:22": "biaoke:chat"}
    bot._pending_locks = {}
    bot._menu_compact_on = MagicMock(return_value=False)
    bot._reply_menu = MagicMock(return_value=None)
    bot._mark_menu_layout_ok = MagicMock()

    def _actor(message, uid=""):
        return f"{message.chat_id}:{uid or message.from_user.id}"

    bot._actor_key = _actor

    user = SimpleNamespace(id=11, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.chat_id = 11
    msg.text = MENU_BTN_LEAVE_BIAOKE
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    assert "11:11" not in bot._pending
    assert bot._pending["22:22"] == "biaoke:chat"
    msg.reply_html.assert_awaited()
    html = str(msg.reply_html.await_args.args[0])
    assert "已離開" in html
    assert "主選單" in html


def test_screen_from_biaoke_clears_pending():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {"1:1": "biaoke:chat"}
    bot._pending_locks = {}
    bot._actor_key = MagicMock(return_value="1:1")
    bot.screen_cmd = AsyncMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.chat_id = 1
    msg.text = "海選"
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    bot.screen_cmd.assert_awaited()
    assert "1:1" not in bot._pending


def test_biaoke_hits_keyboard_stays_in_biaoke():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._biaoke_hits_keyboard(
        [
            {"stock_id": "1303", "stock_name": "南亞"},
            {"stock_id": "2408", "stock_name": "南亞科"},
            {"stock_id": "2330", "stock_name": "台積電"},
        ]
    )
    datas = [b.callback_data for r in kb.inline_keyboard for b in r]
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert datas == ["bkq:1303", "bkq:2408", "bkq:2330"]
    assert all(d.startswith("bkq:") for d in datas)
    assert not any(d.startswith("k:") for d in datas)
    assert "1303 南亞" in texts
    assert all(len(r) <= 2 for r in kb.inline_keyboard)


def test_biaoke_picker_callback_asks_biaoke_not_card():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._enter_biaoke_chat = MagicMock()
    bot._send_biaoke_page = AsyncMock()
    bot._send_card_to = AsyncMock()
    q = SimpleNamespace(
        data="bkq:1303",
        from_user=SimpleNamespace(id=11),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    asyncio.run(bot._on_callback_bound(None, None, q, "11"))
    q.answer.assert_awaited()
    bot._enter_biaoke_chat.assert_called()
    bot._send_biaoke_page.assert_awaited()
    assert bot._send_biaoke_page.await_args.kwargs.get("ask") == "1303"
    assert bot._send_biaoke_page.await_args.kwargs.get("uid") == "11"
    bot._send_card_to.assert_not_awaited()


def test_biaoke_dayk_markup_named_stock_not_card(monkeypatch):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    monkeypatch.setattr("biaoke_chain._resolve_sid", lambda *_a, **_k: ("3037", "威盛"))
    kb = bot._biaoke_dayk_markup("威盛怎麼看")
    datas = [b.callback_data for r in kb.inline_keyboard for b in r]
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert datas == ["bkdk:3037"]
    assert texts == ["官方日K 威盛"]
    monkeypatch.setattr("biaoke_chain._resolve_sid", lambda *_a, **_k: ("", ""))
    assert bot._biaoke_dayk_markup("現在波浪位階") is None
    assert bot._biaoke_dayk_markup("") is None
    assert bot._biaoke_dayk_markup("大盤現在") is None
    assert bot._biaoke_dayk_markup("你好") is None
    monkeypatch.setattr("biaoke_chain._resolve_sid", lambda *_a, **_k: ("TWII", "加權"))
    assert bot._biaoke_dayk_markup("加權") is None


def test_biaoke_hub_has_stock_not_market_buttons(monkeypatch):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ""
    monkeypatch.setattr("biaoke_chain._resolve_sid", lambda *_a, **_k: ("", ""))
    assert bot._biaoke_hub_markup("大盤現在") is None
    assert bot._biaoke_hub_markup("") is None
    monkeypatch.setattr("biaoke_chain._resolve_sid", lambda *_a, **_k: ("3037", "威盛"))
    assert bot._biaoke_hub_markup("威盛怎麼看") is None


def test_biaoke_dayk_callback_sends_structure_not_card():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._enter_biaoke_chat = MagicMock()
    bot._send_biaoke_page = AsyncMock()
    bot._send_biaoke_structure_chart = AsyncMock()
    bot._send_card_to = AsyncMock()
    q = SimpleNamespace(
        data="bkdk:2330",
        from_user=SimpleNamespace(id=11),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    asyncio.run(bot._on_callback_bound(None, None, q, "11"))
    q.answer.assert_awaited()
    bot._enter_biaoke_chat.assert_called()
    bot._send_biaoke_structure_chart.assert_awaited()
    assert bot._send_biaoke_structure_chart.await_args.args[1] == "2330"
    bot._send_biaoke_page.assert_not_awaited()
    bot._send_card_to.assert_not_awaited()
    q2 = SimpleNamespace(
        data="bkdk:TWII",
        from_user=SimpleNamespace(id=11),
        message=MagicMock(),
        answer=AsyncMock(),
    )
    asyncio.run(bot._on_callback_bound(None, None, q2, "11"))
    assert bot._send_biaoke_structure_chart.await_args.args[1] == "現在波浪位階"


def test_stock_wave_ask_sends_stock_chart_not_twii(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 30_000)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = str(tmp_path / "x.db")
    bot.charts_dir = str(tmp_path)
    bot._scratch_chart_path = MagicMock(return_value=str(png))
    bot._png_looks_ok = MagicMock(return_value=True)
    bot._biaoke_reply_menu = MagicMock(return_value=None)
    bot._send_biaoke_twii_degree_chart = AsyncMock()
    msg = MagicMock()
    msg.chat = None
    msg.reply_photo = AsyncMock()

    def fake_resolve(_db, q):
        if "2330" in str(q):
            return [{"stock_id": "2330", "stock_name": "台積電"}]
        return []

    def fake_build(*_a, **_k):
        return {"path": str(png), "caption": "結構圖"}

    with patch("biaoke_brain.resolve_stock", fake_resolve), patch(
        "biaoke_chart.build_biaoke_structure_chart", fake_build
    ):
        asyncio.run(bot._send_biaoke_structure_chart(msg, "2330細微波", "1"))
    bot._send_biaoke_twii_degree_chart.assert_not_awaited()
    msg.reply_photo.assert_awaited()
    bot._send_biaoke_twii_degree_chart.reset_mock()
    msg.reply_photo.reset_mock()
    with patch("biaoke_brain.resolve_stock", fake_resolve), patch(
        "biaoke_chart.build_biaoke_structure_chart", fake_build
    ):
        asyncio.run(bot._send_biaoke_structure_chart(msg, "現在波浪位階", "1"))
    bot._send_biaoke_twii_degree_chart.assert_awaited()
    msg.reply_photo.assert_not_awaited()


def test_phone_update_notice_persists_beside_db(tmp_path, monkeypatch):
    from bot_servers import (
        is_phone_code_query,
        notified_sha_is,
        phone_code_reply,
        phone_git_sha,
        phone_update_notice,
        remember_notified_sha,
        should_notify_phone_update,
    )
    from phone_update import UPDATE_DONE, phone_health_fields, phone_update_note, phone_update_title

    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    note = phone_update_note()
    title = phone_update_title()
    assert note
    assert title == note
    assert any("\u4e00" <= ch <= "\u9fff" for ch in note)
    sha = "abc123def4567890"
    spoken = phone_update_notice(sha)
    assert spoken in (title, f"{title}\n{UPDATE_DONE}")
    assert phone_update_notice("") == spoken
    assert "git_sha" not in spoken
    assert sha not in spoken
    assert not notified_sha_is(sha)
    remember_notified_sha(sha)
    assert (tmp_path / ".wayne_notified_sha").read_text(encoding="utf-8").strip() == sha
    assert notified_sha_is(sha)
    assert not notified_sha_is("other")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert phone_git_sha() == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    expected = phone_update_notice(phone_git_sha())
    assert "git_sha" not in expected
    assert phone_code_reply() == expected
    assert phone_update_notice(phone_git_sha()) == expected
    health = phone_health_fields()
    assert health["update"] == UPDATE_DONE
    assert health["update_note"] == title
    assert health["git_sha"] == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    import main as main_mod

    assert phone_git_sha() == main_mod._code_revision()
    src = __import__("inspect").getsource(WayneTelegramBot.run_polling)
    assert "_notify_phones_updated" in src
    assert should_notify_phone_update(sha) is False  # pytest 當下不准真送
    assert is_phone_code_query("代碼")
    assert is_phone_code_query("/code")
    assert is_phone_code_query("git_sha")
    assert is_phone_code_query("更新代碼")
    assert not is_phone_code_query("2330")
    assert not is_phone_code_query("代碼2330")
    assert not is_phone_code_query("版本")
    names = [name for name, _desc in TELEGRAM_BOT_COMMANDS]
    assert names == ["menu", "industry", "code", "start"]
    assert "screen" not in names
    assert "market" not in names
    assert "portfolio" not in names
    assert "watch" not in names
    assert "flow" not in names


def test_notify_phones_updated_sends_both_uids(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot_servers import WayneTelegramBot, notified_sha_is, phone_update_notice, remember_notified_sha
    from phone_update import UPDATE_DONE

    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "cafebabedeadbeef1234567890")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr("bot_servers.should_notify_phone_update", lambda *_a, **_k: True)
    monkeypatch.setattr("bot_servers.allowed_telegram_uids", lambda: ["9001", "9003"])
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    asyncio.run(bot._notify_phones_updated(app))
    calls = app.bot.send_message.await_args_list
    assert [c.kwargs["chat_id"] for c in calls] == [9001, 9003]
    assert all(c.kwargs["text"] == phone_update_notice("cafebabedeadbeef1234567890") for c in calls)
    assert notified_sha_is("cafebabedeadbeef1234567890")
    app.bot.send_message.reset_mock()
    remember_notified_sha("cafebabedeadbeef1234567890")
    monkeypatch.setattr("bot_servers.should_notify_phone_update", lambda *_a, **_k: False)
    asyncio.run(bot._notify_phones_updated(app))
    app.bot.send_message.assert_not_awaited()
    notice = phone_update_notice("cafebabedeadbeef1234567890")
    assert "cafebabedeadbeef1234567890" not in notice
    assert "git_sha" not in notice
    assert "完成" in notice
    assert any("\u4e00" <= ch <= "\u9fff" for ch in notice)


def test_code_cmd_replies_same_sha_as_health(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot, is_phone_code_query, phone_code_reply
    from phone_update import UPDATE_DONE, phone_update_title

    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    import main as main_mod

    expected = phone_code_reply()
    assert expected == phone_update_title() or expected.endswith(UPDATE_DONE)
    assert main_mod._code_revision() == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"
    assert "git_sha" not in expected
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in expected
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._pending = {}
    bot._touch_user = MagicMock()
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.chat_id = 99
    msg.chat = SimpleNamespace(id=99)
    msg.from_user = SimpleNamespace(id=9001, first_name="w")
    update = SimpleNamespace(message=msg, effective_user=msg.from_user)
    asyncio.run(bot.code_cmd(update, MagicMock()))
    assert msg.reply_text.await_args.args[0] == expected
    bot.code_cmd = AsyncMock()
    asyncio.run(bot._on_text_bound(update, MagicMock(), raw="代碼", text="代碼", uid="9001"))
    bot.code_cmd.assert_awaited()
    bot.code_cmd.reset_mock()
    asyncio.run(bot._on_text_bound(update, MagicMock(), raw="/code", text="/code", uid="9003"))
    bot.code_cmd.assert_awaited()
    assert is_phone_code_query("現在代碼")
    assert not is_phone_code_query("2330")


def test_biaoke_wait_box_matches_lookup_blocks_without_emoji():
    txt0 = WayneTelegramBot._biaoke_progress_text(0)
    txt20 = WayneTelegramBot._biaoke_progress_text(20)
    assert "飆大進行中" in txt0
    assert "□" * 10 in txt0
    assert "■" in txt20
    assert "□" in txt20
    assert "結構圖" in txt0
    assert "回覆" in txt0
    assert "＋" not in txt0
    assert "｜" not in txt0
    assert "<pre>" not in txt0
    assert "好了這則會消失" in txt0
    assert txt0.count("■") + txt0.count("□") == 10
    assert txt20.count("■") + txt20.count("□") == 10
    assert "＝" not in txt0 and "＝" not in txt20
    for ch in ("⏳", "🔄", "📊", "🔍"):
        assert ch not in txt0
        assert ch not in txt20
    wait_src = __import__("inspect").getsource(WayneTelegramBot._start_plain_wait)
    assert "reply_markup" not in wait_src
    assert "edit_text" in wait_src
    page = __import__("inspect").getsource(WayneTelegramBot._send_biaoke_page)
    assert page.index("_start_plain_wait") < page.index("stock_picker_hits")
    card = __import__("inspect").getsource(WayneTelegramBot._send_card_to)
    assert card.index("_chart_progress_text") < card.index("lookup_stocks(")


def test_shared_button_surfaces_use_same_formatters():
    """同一資訊只走一顆最新函式：大盤頁／海選末段輪動／資金頁不各寫一套。"""
    from pathlib import Path

    import inspect

    mkt = inspect.getsource(WayneTelegramBot._send_market_page)
    assert "format_taiwan_market_page_html" in mkt
    assert "format_screen_market_outlook_html" not in mkt
    flow = inspect.getsource(WayneTelegramBot.flow_cmd)
    assert "format_flow_html" in flow
    hub = inspect.getsource(WayneTelegramBot._biaoke_hub_markup)
    assert "bk:mkt" not in hub
    assert 'InlineKeyboardButton("查個股"' not in hub
    dayk = inspect.getsource(WayneTelegramBot._biaoke_dayk_markup)
    assert 'sid, name = "TWII", "加權"' not in dayk
    screen = Path("screening_engine.py").read_text(encoding="utf-8")
    assert "format_screen_market_outlook_html" in screen
    assert "from dongzhu_screen import rotation_screen_block" in screen
    dz = Path("dongzhu_screen.py").read_text(encoding="utf-8")
    assert "from biaoke_field_scan import rotation_screen_block" in dz
    tm = Path("taiwan_market.py").read_text(encoding="utf-8")
    assert tm.index("def _outlook_action_plain") < tm.index(
        "def format_screen_market_outlook_html"
    )
    assert "format_us_lead_line" in tm
