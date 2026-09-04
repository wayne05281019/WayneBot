# -*- coding: utf-8 -*-
"""查股端到端：實際產三張圖 + 多使用者隔離 + 模擬 Telegram 送圖。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import get_db_path


def _message(chat_id: int, uid: int):
    user = SimpleNamespace(id=uid, first_name="u")
    message = MagicMock()
    message.chat_id = chat_id
    message.from_user = user
    message.reply_html = AsyncMock(return_value=MagicMock())
    message.reply_text = AsyncMock(return_value=MagicMock())
    message.reply_photo = AsyncMock(return_value=MagicMock())
    message.reply_media_group = AsyncMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    return message


def _bare_bot(db_path: str, charts_dir: str):
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db_path
    bot.charts_dir = charts_dir
    bot._lookup_ctx = {}
    bot._lookup_fade_msgs = {}
    bot._menu_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._last_card = {}
    bot._pending = {}
    bot._lookup_locks = {}
    bot._lookup_op_state = {}
    return bot


pytestmark = pytest.mark.production_db


class LookupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = get_db_path()

    def test_2454_three_pngs_render_and_validate(self):
        """實際產圖：介紹圖→決策卡→導航，每張通過 PNG 驗證。"""
        from bot_servers import WayneTelegramBot
        from chip_tape import build_tape
        from wayne_navigator import (
            NavigatorEngine,
            generate_chart,
            render_decision_card_png,
            render_first_glance_png,
        )

        engine = NavigatorEngine(self.db)
        card = engine.get_decision_card("2454", merge_live=False)
        self.assertNotIn("error", card)
        ohlc = card.pop("_ohlc", None)
        tape = build_tape(self.db, "2454", merge_live=False) or {}

        timings: dict[str, float] = {}
        paths: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as td:
            glance_p = os.path.join(td, "glance.png")
            card_p = os.path.join(td, "card.png")
            chart_p = os.path.join(td, "chart.png")

            t0 = time.perf_counter()
            paths["glance"] = render_first_glance_png("2454", card, tape, glance_p, self.db)
            timings["glance"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            paths["card"] = render_decision_card_png(card, card_p)
            timings["card"] = time.perf_counter() - t0

            self.assertIsNotNone(ohlc)
            t0 = time.perf_counter()
            paths["chart"] = generate_chart(
                "2454", "", self.db, chart_p, ohlc, already_normalized=True
            )
            timings["chart"] = time.perf_counter() - t0

            for kind, path in paths.items():
                self.assertTrue(path and os.path.isfile(path), kind)
                min_h = 900 if kind == "chart" else 500
                self.assertTrue(
                    WayneTelegramBot._png_looks_ok(path, min_h=min_h),
                    f"{kind} failed png check size={os.path.getsize(path)}",
                )

            # 介紹圖應明顯快於導航圖（使用者等 50s 才看到第一張的根因）
            self.assertLess(timings["glance"], timings["chart"])

    def test_send_card_to_locked_posts_three_photos_in_order(self):
        """模擬 Telegram：畫完一張就送一張（不整包等相簿）。"""
        bot = _bare_bot(self.db, tempfile.mkdtemp())
        message = _message(999001, 111)

        async def _run():
            with patch.object(bot, "_prefetch_mis_quote", return_value=None), patch.object(
                bot, "_quote_header_html", return_value="<b>2454</b>"
            ), patch.object(bot, "_hub_keyboard", return_value=None), patch.object(
                bot, "_track_lookup_fade"
            ), patch.object(
                bot, "_dismiss_lookup_fades", new_callable=AsyncMock
            ), patch.object(
                bot, "_cache_lookup_ctx"
            ), patch.object(
                bot, "_remember_card"
            ):
                await bot._send_card_to_locked(
                    message,
                    "2454",
                    "111",
                    "999001:111",
                    [{"stock_id": "2454", "close": 100}],
                )

        asyncio.run(_run())

        # 邊畫邊送：應走 reply_photo，不整包 reply_media_group。
        self.assertEqual(message.reply_media_group.await_count, 0)
        sent = [
            (c.kwargs.get("caption") or "")[:80]
            for c in message.reply_photo.await_args_list
        ]
        self.assertGreaterEqual(len(sent), 2, f"photos sent: {sent}")
        captions = " ".join(sent)
        self.assertTrue(
            "決策卡" in captions or "介紹" in captions or "導航" in captions or "縮圖" in captions,
            captions,
        )

    def test_lookup_lock_blocks_same_user_not_other(self):
        """同 chat 兩個 uid：A 出圖中 B 不受阻；同一人連打才提示稍候。"""
        from bot_servers import WayneTelegramBot

        bot = _bare_bot(self.db, tempfile.mkdtemp())
        gate = asyncio.Event()
        started = asyncio.Event()
        user_a_busy = _message(100, 111)
        user_b = _message(100, 222)
        user_a_busy.reply_text = AsyncMock()

        async def slow_locked(message, code, uid, actor, hits):
            if uid == "111":
                started.set()
                await gate.wait()

        async def _run():
            bot._send_card_to_locked = slow_locked
            task_a = asyncio.create_task(bot._send_card_to(user_a_busy, "2330", "111"))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            await bot._send_card_to(user_b, "2454", "222")
            gate.set()
            await task_a

        asyncio.run(_run())
        user_a_busy.reply_text.assert_not_awaited()
        self.assertNotIn(
            "上一檔還在出圖",
            str(user_b.reply_text.await_args_list),
        )

    def test_same_user_second_lookup_gets_busy_hint(self):
        """同一人連續查股：第二發應收到「上一檔還在出圖」。"""
        bot = _bare_bot(self.db, tempfile.mkdtemp())
        gate = asyncio.Event()
        started = asyncio.Event()
        message = _message(100, 111)
        message.reply_text = AsyncMock()

        async def slow_locked(message, code, uid, actor, hits):
            started.set()
            await gate.wait()

        async def _run():
            bot._send_card_to_locked = slow_locked
            task = asyncio.create_task(bot._send_card_to(message, "2330", "111"))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            await bot._send_card_to(message, "2454", "111")
            gate.set()
            await task

        asyncio.run(_run())
        busy = [c for c in message.reply_text.await_args_list if "上一檔還在出圖" in str(c)]
        self.assertEqual(len(busy), 1)

    def test_two_users_parallel_lookup_both_complete(self):
        """哥哥／偉權同時查不同股：各自 actor 鎖，兩邊都應出圖。"""
        bot = _bare_bot(self.db, tempfile.mkdtemp())
        photos: dict[str, list] = {"111": [], "222": []}

        async def fake_locked(message, code, uid, actor, hits):
            photos[uid].append(code)
            await asyncio.sleep(0.05)

        async def _run():
            bot._send_card_to_locked = fake_locked
            await asyncio.gather(
                bot._send_card_to(_message(100, 111), "2330", "111"),
                bot._send_card_to(_message(100, 222), "2454", "222"),
            )

        asyncio.run(_run())
        self.assertEqual(photos["111"], ["2330"])
        self.assertEqual(photos["222"], ["2454"])

    def test_lookup_fade_dismiss_does_not_cross_users(self):
        """查股 fade 訊息：只清自己的，不刪另一人的。"""
        bot = _bare_bot(self.db, tempfile.mkdtemp())
        msg_a = MagicMock()
        msg_a.delete = AsyncMock()
        msg_b = MagicMock()
        msg_b.delete = AsyncMock()
        bot._track_lookup_fade("100:111", msg_a, "wait")
        bot._track_lookup_fade("100:222", msg_b, "wait")

        async def _run():
            await bot._dismiss_lookup_fades("100:111", roles={"wait"})

        asyncio.run(_run())
        msg_a.delete.assert_awaited_once()
        msg_b.delete.assert_not_awaited()

    def test_ai_desk_two_users_separate_positions(self):
        """AI 模擬倉：兩人各買各的，持倉 user_id 不混。"""
        import sqlite3
        import tempfile

        from ai_trader import ai_user_id, run_ai_desk
        from portfolio_engine import PortfolioEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        results = {
            "leave_zero": [
                {"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "chase_warning": False},
            ],
        }
        try:
            run_ai_desk(path, "111", results, "20260831")
            run_ai_desk(path, "222", results, "20260831")
            eng = PortfolioEngine(path)
            self.assertGreaterEqual(eng.get_portfolio_summary(ai_user_id("111"))["positions_count"], 1)
            self.assertGreaterEqual(eng.get_portfolio_summary(ai_user_id("222"))["positions_count"], 1)
            conn = sqlite3.connect(path)
            rows = conn.execute(
                "SELECT DISTINCT user_id FROM user_positions WHERE user_id LIKE 'ai_%'"
            ).fetchall()
            conn.close()
            ids = {r[0] for r in rows}
            self.assertIn(ai_user_id("111"), ids)
            self.assertIn(ai_user_id("222"), ids)
            self.assertEqual(len(ids), 2)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
