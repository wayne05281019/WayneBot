"""2026-11-17：模擬倉整包拿掉；話筒／排程不准再操盤、不准崩潰。"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock


class AiDeskRetiredTests(unittest.TestCase):
    def test_run_ai_desk_runner_noop(self):
        from main_runner import MainRunner

        runner = MainRunner.__new__(MainRunner)
        runner.db_path = ":memory:"
        out = MainRunner._run_ai_desk(runner, "20261117", results={}, notify=True)
        self.assertTrue(out.get("retired"))
        self.assertEqual(out.get("bought"), [])

    def test_phone_reply_retired_no_crash(self):
        from bot_servers import AI_DESK_RETIRED_ZH, WayneTelegramBot

        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot._keyboard = MagicMock(return_value=None)
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        asyncio.run(WayneTelegramBot._reply_ai_desk_retired(bot, msg))
        msg.reply_text.assert_awaited()
        args, kwargs = msg.reply_text.await_args
        self.assertEqual(args[0], AI_DESK_RETIRED_ZH)

    def test_portfolio_keyboard_has_no_ai_button(self):
        from bot_servers import WayneTelegramBot

        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        kb = WayneTelegramBot._portfolio_keyboard(
            bot, [{"stock_code": "2330", "stock_name": "台積電"}]
        )
        blobs = []
        for row in kb.inline_keyboard:
            for btn in row:
                blobs.append(str(btn.text))
                blobs.append(str(btn.callback_data))
        joined = " ".join(blobs)
        self.assertNotIn("AI倉", joined)
        self.assertNotIn("ai_view", joined)


if __name__ == "__main__":
    unittest.main()
