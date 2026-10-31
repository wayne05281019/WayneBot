# -*- coding: utf-8 -*-
"""查股五張圖：完整圖下鈕只掛第 4 張大量區；第 2／3／5 張不要重複鍵盤。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from bot_servers import WayneTelegramBot


def _png(td: str, name: str) -> str:
    path = os.path.join(td, name)
    Image.frombytes("RGB", (800, 900), os.urandom(800 * 900 * 3)).save(path, "PNG")
    return path


class LookupHubLastCardOnlyTests(TestCase):
    def test_hub_markup_only_on_intraday_photo(self):
        td = tempfile.mkdtemp()
        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot.db_path = os.path.join(td, "x.db")
        bot.charts_dir = td
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

        hub = MagicMock(name="hub_keyboard")

        class _Engine:
            def __init__(self, *_a, **_k):
                pass

            def get_decision_card(self, *_a, **_k):
                return {"stock_id": "2330", "stock_name": "台積電", "table": []}

        message = MagicMock()
        message.from_user = SimpleNamespace(id=111, first_name="u")
        message.chat_id = 999
        message.reply_html = AsyncMock(return_value=MagicMock())
        message.reply_text = AsyncMock(return_value=MagicMock())
        message.reply_photo = AsyncMock()
        message.reply_media_group = AsyncMock()

        send_markups: list = []

        async def _capture_photo(msg, path, *, caption="", markup=None, kind="", **_k):
            send_markups.append((kind, markup))
            return True

        async def _run():
            with patch("wayne_navigator.NavigatorEngine", _Engine), patch(
                "chip_tape.build_tape", return_value={}
            ), patch(
                "stock_news.fetch_stock_news_stats", return_value=None
            ), patch(
                "wayne_navigator.render_first_glance_png",
                side_effect=lambda *_a, **_k: _png(td, "g.png"),
            ), patch(
                "wayne_navigator.render_decision_card_png",
                side_effect=lambda *_a, **_k: _png(td, "c.png"),
            ), patch(
                "three_in_one_chart.render_lookup_structure_result",
                side_effect=lambda *_a, **_k: (
                    _png(td, "s.png"),
                    "結構圖（非買訊）　買點只認藍▲紅框",
                ),
            ), patch(
                "vol_zone_chart.render_lookup_vol_result",
                side_effect=lambda *_a, **_k: (
                    _png(td, "v.png"),
                    "大量撐壓圖（非買訊）",
                ),
            ), patch(
                "intraday_open_close_chart.render_lookup_intraday_result",
                side_effect=lambda *_a, **_k: (
                    _png(td, "i.png"),
                    "當天走勢（開→收・非買訊）",
                ),
            ), patch.object(
                bot, "_prefetch_mis_quote", return_value=None
            ), patch.object(
                bot, "_quote_header_html", return_value="<b>2330</b>"
            ), patch.object(
                bot, "_hub_keyboard", return_value=hub
            ), patch.object(
                bot, "_track_lookup_fade"
            ), patch.object(
                bot, "_dismiss_lookup_fades", new_callable=AsyncMock
            ), patch.object(
                bot, "_cache_lookup_ctx"
            ), patch.object(
                bot, "_remember_card"
            ), patch.object(
                bot, "_reply_lookup_photo", side_effect=_capture_photo
            ), patch.object(
                WayneTelegramBot, "_png_looks_ok", return_value=True
            ), patch.object(
                WayneTelegramBot, "_chart_png_looks_ok", return_value=True
            ), patch.object(
                WayneTelegramBot,
                "_prepare_lookup_album_photo",
                side_effect=lambda p, kind="": p,
            ):
                await bot._send_card_to_locked(
                    message,
                    "2330",
                    "111",
                    "999:111",
                    [{"stock_id": "2330", "close": 100}],
                )

        asyncio.run(_run())
        kinds = [k for k, _ in send_markups]
        self.assertEqual(kinds, ["card", "glance", "struct", "vol", "intraday"])
        by_kind = {k: mk for k, mk in send_markups}
        self.assertIsNone(by_kind["card"])
        self.assertIsNone(by_kind["glance"])
        self.assertIsNone(by_kind["struct"])
        self.assertIsNone(by_kind["vol"])
        self.assertIs(by_kind["intraday"], hub)

    def test_source_does_not_reattach_hub_on_mid_cards(self):
        import inspect

        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        # 舊 bug：介紹用 markup or hub 會把 None 又變回 hub
        self.assertNotIn("markup or hub", src)
        # 完整鍵盤只掛第 5 張（hub_mk=hub）；前四張走 _send_kind_item 預設 hub_mk=None
        self.assertIn("hub_mk=hub", src)
        self.assertIn("_send_kind_item", src)
        self.assertGreaterEqual(src.count("retry_label=\"第"), 4)

    def test_source_vol_waits_struct_and_reports_mid_miss(self):
        """大量區不准搶介紹／結構 paint；缺圖（含高低卡）要明示。"""
        import inspect

        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("struct_queued", src)
        self.assertIn("struct_queued.wait()", src)
        self.assertIn("缺：", src)
        self.assertIn("miss_core", src)
        self.assertIn("_await_lookup_paint", src)
        self.assertIn("asof_ymd=asof or None", src)
