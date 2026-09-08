# -*- coding: utf-8 -*-
"""查股不能靜默空白：鍵盤壞掉或出圖失敗仍要留下一則字。"""
from __future__ import annotations

import asyncio
import inspect
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import WayneTelegramBot, _http_url
from config import get_public_base_url


def _message():
    user = SimpleNamespace(id=1, first_name="u")
    message = MagicMock()
    message.chat_id = 99
    message.from_user = user
    message.reply_html = AsyncMock(side_effect=RuntimeError("bad markup"))
    message.reply_photo = AsyncMock(side_effect=RuntimeError("bad markup"))
    message.reply_media_group = AsyncMock(side_effect=RuntimeError("bad markup"))
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock(), edit_text=AsyncMock()))
    return message


def _bot(db_path: str):
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db_path
    bot.charts_dir = tempfile.mkdtemp()
    bot._lookup_ctx = {}
    bot._lookup_fade_msgs = {}
    bot._lookup_locks = {}
    bot._lookup_op_state = {}
    bot._last_card = {}
    bot._pending = {}
    bot._pin_reply_menu = AsyncMock()
    bot._remember_card = MagicMock()
    bot._cache_lookup_ctx = MagicMock()
    bot._hit_is_emerging = lambda code, hits: False
    bot._png_looks_ok = lambda *a, **k: True
    bot._chart_png_looks_ok = lambda *a, **k: True
    bot._hub_keyboard = MagicMock(return_value=None)
    return bot


def test_http_url_rejects_empty_and_javascript():
    assert _http_url("https://example.com/k/2330") == "https://example.com/k/2330"
    assert _http_url("http://example.com") == "http://example.com"
    assert _http_url("javascript:alert(1)") == ""
    assert _http_url("waynebot-service.onrender.com/k/2330") == ""
    assert _http_url("") == ""


def test_public_base_url_adds_https(monkeypatch):
    monkeypatch.delenv("WAYNE_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "waynebot-service.onrender.com")
    assert get_public_base_url() == "https://waynebot-service.onrender.com"


def test_send_card_locked_source_keeps_visible_fallback():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "_reply_visible" in src
    assert "卡片沒送出" in src
    assert "timeout=6.0" in src
    assert src.index("reply_text") < src.index("fetch_stock_news_stats")


def test_send_card_locked_last_resort_plain_text():
    bot = _bot(":memory:")
    msg = _message()

    async def run():
        with patch.object(bot, "_prefetch_mis_quote", return_value=None), patch.object(
            bot, "_quote_header_html", return_value="<b>2330</b>"
        ), patch("stock_news.fetch_stock_news_stats", return_value=None), patch(
            "chip_tape.build_tape", return_value={}
        ), patch(
            "wayne_navigator.NavigatorEngine"
        ) as eng:
            eng.return_value.get_decision_card.return_value = {"error": "沒有日K"}
            await bot._send_card_to_locked(
                msg,
                "2330",
                "1",
                "99:1",
                [{"stock_id": "2330", "close": 100}],
            )

    asyncio.run(run())
    texts = [str(c.args[0]) for c in msg.reply_text.await_args_list if c.args]
    assert texts, "查股失敗後必須留下一則字"
    assert any("2330" in t or "代號" in t or "日K" in t or "查詢" in t for t in texts)
