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
    assert "_reply_menu" in src
    assert "reply_markup" in src
    assert "_ensure_reply_menu_if_needed" in src
    assert "send_action" in src
    assert "typing" in src
    assert "format_latest_focus" in src
    assert "take_unread_digest" not in src
    assert "reflow=False" in src
    assert "_send_biaoke_structure_chart" in src
    assert "_send_card_to" not in src
    assert "build_biaoke_structure_chart" in inspect.getsource(
        WayneTelegramBot._send_biaoke_structure_chart
    )
    assert not hasattr(WayneTelegramBot, "_biaoke_inline")
    whole = inspect.getsource(WayneTelegramBot)
    assert 'InlineKeyboardButton("怎麼觀察"' not in whole
    assert 'kind == "see"' in whole  # 舊訊息三顆還能答，只是不再畫選單
    from bot_servers import MENU_BTN_BIAOKE_FACE, MENU_LAYOUT_VERSION

    assert MENU_BTN_BIAOKE_FACE == "飆大"
    assert "\u20dd" not in MENU_BTN_BIAOKE_FACE
    assert MENU_LAYOUT_VERSION == "18"


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
