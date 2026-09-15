# -*- coding: utf-8 -*-
"""飆客獨立區：公開文可查、不進海選。"""
from bot_servers import (
    MENU_BTN_BIAOKE,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_SLOT,
    MENU_ROW1,
    MENU_ROW2,
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
    assert MENU_ROW1[-1] == MENU_BTN_BIAOKE_FACE
    assert MENU_ROW2[-1] == MENU_BTN_SLOT
    assert MENU_BTN_SLOT.strip() == ""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    face = [b.text for b in kb.keyboard[0]][-1]
    assert face == "飆大"
    assert "\u20dd" not in face
    assert _normalize_menu_text(face) == "飆大"
    assert [b.text for b in kb.keyboard[1]][-1].strip() == ""


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
    assert "不是買訊" in html


def test_welcome_teaches_chat_not_a_menu():
    from biaoke_brain import WINDOW_OPEN
    from biaoke_desk import format_biaoke_html, format_biaoke_welcome_html

    html = format_biaoke_welcome_html()
    assert html == WINDOW_OPEN
    assert "打字" in html
    assert "語音" in html or "麥克風" in html
    assert "不必打字" in html
    assert "我直接回" in html
    assert "離開飆大" in html
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


def test_biaoke_page_has_no_inside_menu():
    import inspect

    src = inspect.getsource(WayneTelegramBot._send_biaoke_page)
    assert "_biaoke_inline" not in src
    assert "bk:see" not in src
    assert "怎麼觀察" not in src
    assert "問一檔" not in src
    assert "_biaoke_reply_menu" in src
    assert "reply_markup" in src
    assert "_mark_menu_layout_ok" in src
    assert "send_action" in src
    assert "typing" in src
    assert "format_latest_focus" in src
    assert "take_unread_digest" in src
    assert "reflow=False" in src
    assert "_send_biaoke_structure_chart" in src
    assert "_send_biaoke_origin_charts" in src
    assert "create_task" in src
    assert "stock_picker_hits" in src
    assert "_biaoke_hits_keyboard" in src
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
    assert MENU_LAYOUT_VERSION == "20"


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
    assert [b.text for b in kb.keyboard[0]][-1] == MENU_BTN_LEAVE_BIAOKE
    assert [b.text for b in main.keyboard[0]][-1] == "飆大"
    assert [b.text for b in kb.keyboard[0]][:-1] == [b.text for b in main.keyboard[0]][:-1]
    assert [b.text for b in kb.keyboard[1]] == [b.text for b in main.keyboard[1]]
    compact_on = WayneTelegramBot.__new__(WayneTelegramBot)
    compact_on.db_path = ""
    compact_on._menu_compact_on = lambda uid="": True
    compact_kb = compact_on._biaoke_reply_menu()
    assert len(compact_kb.keyboard) == 2
    assert [b.text for b in compact_kb.keyboard[0]][-1] == MENU_BTN_LEAVE_BIAOKE


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
