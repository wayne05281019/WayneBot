# -*- coding: utf-8 -*-
"""語音聽寫後走同一條平常話／查股路由。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import WayneTelegramBot
from tests.test_why_menu import _bot, _msg, _update


def _voice_msg(uid: int, *, duration: int = 3, file_id: str = "fid"):
    msg = _msg(uid, "")
    msg.text = None
    msg.voice = SimpleNamespace(
        file_id=file_id,
        duration=duration,
        mime_type="audio/ogg",
        file_name=None,
    )
    msg.audio = None
    return msg


def test_voice_handler_is_registered():
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "filters.VOICE" in src
    assert "filters.AUDIO" in src
    assert "self.on_voice" in src


def test_on_voice_without_key_does_not_pretend(monkeypatch):
    monkeypatch.delenv("WAYNE_STT_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    bot = _bot()
    msg = _voice_msg(9)
    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock()

    asyncio.run(bot.on_voice(_update(msg), ctx))
    html = msg.reply_html.await_args.args[0]
    assert "還沒接金鑰" in html
    ctx.bot.get_file.assert_not_called()
    bot._send_card_to.assert_not_awaited()


def test_on_voice_rejects_long_clip(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bot = _bot()
    msg = _voice_msg(9, duration=90)
    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock()

    asyncio.run(bot.on_voice(_update(msg), ctx))
    html = msg.reply_html.await_args.args[0]
    assert "45 秒" in html
    ctx.bot.get_file.assert_not_called()


def test_on_voice_empty_transcript(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bot = _bot()
    msg = _voice_msg(9)
    tg_file = SimpleNamespace(download_to_drive=AsyncMock())
    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock(return_value=tg_file)

    async def run():
        with patch("voice_stt.transcribe_audio", return_value=""):
            await bot.on_voice(_update(msg), ctx)

    asyncio.run(run())
    htmls = [c.args[0] for c in msg.reply_html.await_args_list]
    assert any("沒聽清楚" in h for h in htmls)
    bot._send_card_to.assert_not_awaited()


def test_on_voice_routes_like_typed_why(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bot = _bot()
    bot._last_card["9"] = "2330"
    msg = _voice_msg(9)
    tg_file = SimpleNamespace(download_to_drive=AsyncMock())
    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock(return_value=tg_file)

    async def run():
        with patch("voice_stt.transcribe_audio", return_value="為什麼跌"):
            await bot.on_voice(_update(msg), ctx)

    asyncio.run(run())
    heard = msg.reply_html.await_args_list[0].args[0]
    assert "聽到" in heard
    assert "為什麼跌" in heard
    bot._send_card_to.assert_awaited()
    assert bot._send_card_to.await_args.args[1] == "2330"


def test_on_voice_in_biaoke_goes_to_biaoke_not_card(monkeypatch):
    """按了飆大之後，語音聽寫走飆大回文，不必打字，也不改走查股卡。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bot = _bot()
    bot._send_biaoke_page = AsyncMock()
    bot._last_card["9"] = "2330"
    msg = _voice_msg(9)
    bot._pending[bot._actor_key(msg, uid="9")] = "biaoke:chat"
    tg_file = SimpleNamespace(download_to_drive=AsyncMock())
    ctx = MagicMock()
    ctx.bot.get_file = AsyncMock(return_value=tg_file)

    async def run():
        with patch("voice_stt.transcribe_audio", return_value="勤誠怎麼看"):
            await bot.on_voice(_update(msg), ctx)

    asyncio.run(run())
    heard = msg.reply_html.await_args_list[0].args[0]
    assert "聽到" in heard
    assert "勤誠" in heard
    bot._send_biaoke_page.assert_awaited()
    ask = bot._send_biaoke_page.await_args.kwargs.get("ask") or ""
    assert "勤誠" in ask
    bot._send_card_to.assert_not_awaited()


def test_on_text_spoken_kwarg_same_as_typing():
    bot = _bot()
    bot._last_card["9"] = "2454"
    msg = _msg(9, "ignore-this")

    async def run():
        await bot.on_text(_update(msg), MagicMock(), spoken="外資")

    asyncio.run(run())
    bot._send_chips_to.assert_awaited()
    assert bot._send_chips_to.await_args.args[1] == "2454"
