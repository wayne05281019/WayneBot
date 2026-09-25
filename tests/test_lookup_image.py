# -*- coding: utf-8 -*-
"""查股出圖：PNG 驗證與產圖順序。"""
import asyncio
import inspect
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import WayneTelegramBot


class LookupImageTests(unittest.TestCase):
    def test_png_looks_ok_rejects_tiny_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"short")
            path = f.name
        try:
            self.assertFalse(WayneTelegramBot._png_looks_ok(path))
        finally:
            os.unlink(path)

    def test_png_looks_ok_accepts_album_jpeg(self):
        from PIL import Image

        from bot_servers import _LOOKUP_ALBUM_CELL

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cell.album.jpg")
            Image.new("RGB", _LOOKUP_ALBUM_CELL, (12, 18, 28)).save(
                path, "JPEG", quality=92
            )
            self.assertGreater(os.path.getsize(path), 24_000)
            self.assertTrue(WayneTelegramBot._png_looks_ok(path))
            self.assertTrue(WayneTelegramBot._png_looks_ok(path, min_h=500))

    def test_png_looks_ok_rejects_tiny_jpeg(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "tiny.jpg")
            Image.new("RGB", (8, 8), (12, 18, 28)).save(path, "JPEG", quality=40)
            self.assertFalse(WayneTelegramBot._png_looks_ok(path))

    @pytest.mark.production_db
    def test_png_looks_ok_accepts_real_card(self):
        from config import get_db_path

        db = get_db_path()
        from wayne_navigator import NavigatorEngine, render_decision_card_png

        card = NavigatorEngine(db).get_decision_card("2454", merge_live=False)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "card.png")
            out = render_decision_card_png(card, path)
            self.assertTrue(WayneTelegramBot._png_looks_ok(out))

    def test_glance_caption_appends_sell_note(self):
        from bot_servers import _glance_photo_caption

        card = {
            "sell_action": "直接減碼",
            "sell_why": "不同步（最高價但非最高溫）",
        }
        out = _glance_photo_caption("", card)
        self.assertIn("Ai建議", out)
        self.assertNotIn("網頁走勢", out)
        self.assertNotIn("紀律　", out)
        self.assertIn("先出一點", out)
        self.assertIn("熱度沒跟上", out)
        self.assertNotIn("買訊", out)

    def test_glance_caption_silent_when_no_sell(self):
        from bot_servers import _glance_photo_caption

        self.assertEqual(_glance_photo_caption("當日K＋籌碼價量", {"sell_action": ""}), "當日K＋籌碼價量")
        self.assertEqual(_glance_photo_caption("", None), "")

    def test_card_caption_appends_sell_note(self):
        from bot_servers import _decision_card_photo_caption, _photo_sell_caption

        card = {
            "stock_id": "2330",
            "stock_name": "台積電",
            "sell_action": "直接減碼",
            "sell_why": "不同步（最高價但非最高溫）",
        }
        out = _decision_card_photo_caption(card, "2330")
        self.assertTrue(out.startswith("台積電"))
        self.assertNotIn("高低決策卡", out)
        self.assertIn("Ai建議", out)
        self.assertNotIn("紀律　", out)
        self.assertIn("先出一點、不要追", out)
        self.assertNotIn("買訊", out)
        self.assertEqual(_photo_sell_caption("高低決策卡", {"sell_action": ""}, fallback="高低決策卡"), "高低決策卡")
        flow_card = {
            "sell_action": "",
            "industry_flow": "本鏈（代工）法人合計買超。佔比在升＝資金流入。",
        }
        flowed = _photo_sell_caption("高低決策卡", flow_card, fallback="高低決策卡")
        self.assertIn("資金流入", flowed)
        self.assertNotIn("半導體業剛輪進", flowed)
        self.assertNotIn("不改溫度", flowed)
        self.assertNotIn("買賣格", flowed)
        self.assertNotIn("Ai建議", flowed)
        self.assertNotIn("紀律　", flowed)

    def test_stock_caption_name_strips_code_prefix(self):
        from bot_servers import _stock_caption_name

        self.assertEqual(_stock_caption_name({"stock_id": "2330", "stock_name": "台積電"}, "2330"), "台積電")
        self.assertEqual(_stock_caption_name({"stock_id": "2330", "stock_name": "2330 台積電"}, "2330"), "台積電")
        self.assertEqual(_stock_caption_name({"stock_id": "2330", "stock_name": "2330"}, "2330"), "2330")

    def test_send_card_uses_lookup_album(self):
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("_send_lookup_album", src)
        self.assertIn("ready_items", src)
        self.assertIn("_stock_caption_name", src)
        self.assertIn("_prepare_album_cell", src)
        self.assertNotIn("industry_task", src)
        self.assertNotIn("card_send_task", src)
        self.assertNotIn("render_industry_png", src)
        self.assertNotIn('"industry"', src)
        self.assertNotIn("generate_chart", src)
        self.assertIn("asyncio.gather", src)
        self.assertNotIn("path = await _render_one(kind, fn, timeout_s)", src)
        self.assertLess(src.find("asyncio.gather"), src.find("_send_lookup_album"))
        self.assertIn("_render_ready", src)
        self.assertIn("_album_pair_box", src)
        self.assertNotIn("_render_then_cell", src)

    def test_glance_and_card_render_start_together(self):
        """介紹圖與高低卡同一拍開始畫，不准等介紹圖畫完才開高低卡。"""
        from PIL import Image

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
        started = {}

        def _png(name: str) -> str:
            path = os.path.join(td, name)
            Image.new("RGB", (800, 900), (12, 18, 28)).save(path, "PNG")
            return path

        def _glance(*_a, **_k):
            started["glance"] = time.monotonic()
            time.sleep(0.25)
            return _png("g.png")

        def _card(*_a, **_k):
            started["card"] = time.monotonic()
            time.sleep(0.25)
            return _png("c.png")

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
        message.reply_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])

        async def _run():
            with patch("wayne_navigator.NavigatorEngine", _Engine), patch(
                "chip_tape.build_tape", return_value={}
            ), patch(
                "stock_news.fetch_stock_news_stats", return_value=None
            ), patch(
                "wayne_navigator.render_first_glance_png", side_effect=_glance
            ), patch(
                "wayne_navigator.render_decision_card_png", side_effect=_card
            ), patch.object(
                bot, "_prefetch_mis_quote", return_value=None
            ), patch.object(
                bot, "_quote_header_html", return_value="<b>2330</b>"
            ), patch.object(
                bot, "_hub_keyboard", return_value=None
            ), patch.object(
                bot, "_track_lookup_fade"
            ), patch.object(
                bot, "_dismiss_lookup_fades", new_callable=AsyncMock
            ), patch.object(
                bot, "_cache_lookup_ctx"
            ), patch.object(
                bot, "_remember_card"
            ), patch.object(
                WayneTelegramBot, "_png_looks_ok", return_value=True
            ), patch.object(
                WayneTelegramBot, "_prepare_lookup_album_photo", side_effect=lambda p: p
            ), patch.object(
                WayneTelegramBot, "_prepare_album_cell", side_effect=lambda p, box=None: p
            ), patch(
                "vol_zone_chart.render_volume_zone_png",
                side_effect=lambda *_a, **_k: _png("vz.png"),
            ):
                await bot._send_card_to_locked(
                    message,
                    "2330",
                    "111",
                    "999:111",
                    [{"stock_id": "2330", "close": 100}],
                )

        asyncio.run(_run())
        self.assertIn("glance", started)
        self.assertIn("card", started)
        self.assertLess(abs(started["glance"] - started["card"]), 0.12)
        self.assertGreaterEqual(message.reply_media_group.await_count, 1)
        self.assertGreaterEqual(message.reply_photo.await_count, 1)
        caps = [
            str(c.kwargs.get("caption") or "")
            for c in message.reply_photo.await_args_list
        ]
        self.assertTrue(any("大量區" in c for c in caps), caps)

    def test_lookup_native_dpi_higher_than_360(self):
        from industry_card import INDUSTRY_PX_SCALE
        from wayne_navigator import CARD_PNG_DPI, GLANCE_PNG_DPI, NAV_CHART_DPI, _savefig_lookup_png

        self.assertGreaterEqual(CARD_PNG_DPI, 200)
        self.assertLessEqual(CARD_PNG_DPI, 220)
        self.assertEqual(GLANCE_PNG_DPI, CARD_PNG_DPI)
        self.assertGreaterEqual(NAV_CHART_DPI, 320)
        self.assertGreaterEqual(INDUSTRY_PX_SCALE, 3)
        src = inspect.getsource(_savefig_lookup_png)
        self.assertIn("format=\"jpeg\"", src)
        self.assertNotIn("compress_level", src)
        card_src = inspect.getsource(__import__("wayne_navigator").render_decision_card_png)
        glance_src = inspect.getsource(__import__("wayne_navigator").render_first_glance_png)
        self.assertIn("_savefig_lookup_png", card_src)
        self.assertIn("_savefig_lookup_png", glance_src)

    def test_lookup_album_sends_hq_jpeg(self):
        src = inspect.getsource(WayneTelegramBot._send_lookup_album)
        self.assertIn("_prepare_album_cell", src)
        self.assertIn("write_timeout", src)
        self.assertIn("open(send_path", src)
        self.assertNotIn("BytesIO", src)
        self.assertIn("改無說明再試", src)

    def test_prepare_album_cell_is_same_4x5_pair(self):
        from PIL import Image

        from bot_servers import _LOOKUP_TG_MAX_WH

        with tempfile.TemporaryDirectory() as td:
            tall = os.path.join(td, "tall.png")
            Image.new("RGB", (800, 2200), (12, 18, 28)).save(tall, "PNG")
            wide = os.path.join(td, "card.png")
            Image.new("RGB", (900, 1600), (20, 24, 36)).save(wide, "PNG")
            box = WayneTelegramBot._album_pair_box([tall, wide])
            self.assertEqual(box[0] * 5, box[1] * 4)
            self.assertLessEqual(sum(box), _LOOKUP_TG_MAX_WH)
            a = WayneTelegramBot._prepare_album_cell(tall, box)
            b = WayneTelegramBot._prepare_album_cell(wide, box)
            with Image.open(a) as im:
                self.assertEqual(im.size, box)
                self.assertEqual(im.format, "JPEG")
            with Image.open(b) as im:
                self.assertEqual(im.size, box)
                self.assertEqual(im.format, "JPEG")
            self.assertLessEqual(os.path.getsize(a), 2_500_000)
            self.assertLessEqual(os.path.getsize(b), 2_500_000)

    def test_album_pair_caps_phone_grid(self):
        """大圖收到 1920×2400，仍比舊 1200 格銳，檔比較小所以傳得快。"""
        from PIL import Image

        from bot_servers import _LOOKUP_ALBUM_CELL, _LOOKUP_ALBUM_MAX

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "card.png")
            Image.new("RGB", (2272, 4238), (12, 18, 28)).save(src, "PNG")
            box = WayneTelegramBot._album_pair_box([src])
            self.assertEqual(box, _LOOKUP_ALBUM_MAX)
            self.assertGreater(box[0], _LOOKUP_ALBUM_CELL[0])
            out = WayneTelegramBot._prepare_album_cell(src, box)
            with Image.open(out) as im:
                self.assertEqual(im.size, box)
                self.assertEqual(im.format, "JPEG")

    def test_lookup_mis_does_not_block_six_seconds(self):
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("_LOOKUP_MIS_TIMEOUT", src)
        self.assertNotIn("timeout=6.0", src)
        import bot_servers

        self.assertLessEqual(bot_servers._LOOKUP_MIS_TIMEOUT, 2.0)

    def test_prepare_lookup_album_photo_keeps_native_pixels(self):
        from PIL import Image

        from bot_servers import _LOOKUP_TG_MAX_BYTES, _LOOKUP_TG_MAX_WH

        with tempfile.TemporaryDirectory() as td:
            native = os.path.join(td, "n.png")
            Image.new("RGB", (1080, 1400), (12, 18, 28)).save(native, "PNG")
            out = WayneTelegramBot._prepare_lookup_album_photo(native)
            with Image.open(out) as im:
                self.assertEqual(im.size, (1080, 1400))
                self.assertEqual(im.format, "JPEG")
            self.assertLessEqual(os.path.getsize(out), _LOOKUP_TG_MAX_BYTES)
            wide = os.path.join(td, "w.png")
            Image.new("RGB", (2272, 2800), (12, 18, 28)).save(wide, "PNG")
            out2 = WayneTelegramBot._prepare_lookup_album_photo(wide)
            with Image.open(out2) as im:
                self.assertEqual(im.size, (2272, 2800))
                self.assertEqual(im.format, "JPEG")
            over = os.path.join(td, "over.png")
            Image.new("RGB", (5000, 6000), (12, 18, 28)).save(over, "PNG")
            out3 = WayneTelegramBot._prepare_lookup_album_photo(over)
            with Image.open(out3) as im:
                self.assertLessEqual(sum(im.size), _LOOKUP_TG_MAX_WH)
                self.assertEqual(im.format, "JPEG")
            nw, nh = WayneTelegramBot._fit_lookup_photo_wh(1080, 1400)
            self.assertEqual((nw, nh), (1080, 1400))
            ow, oh = WayneTelegramBot._fit_lookup_photo_wh(5000, 6000)
            self.assertLessEqual(ow + oh, _LOOKUP_TG_MAX_WH)
            self.assertLess(ow, 5000)

    def test_two_image_album_does_not_upscale(self):
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("tape_task", src)
        self.assertLess(src.find("tape_task"), src.find("to_thread(_build_card)"))
        self.assertNotIn("card_send_task", src)
        self.assertIn("ready_items", src)
        fit = inspect.getsource(WayneTelegramBot._fit_lookup_photo_wh)
        self.assertIn("不准硬拉大", fit)
        self.assertNotIn("拉滿維持高畫質", fit)

    def test_lookup_retries_truncated_png_for_all_kinds(self):
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("attempts = 2", src)
        self.assertNotIn('attempts = 2 if kind == "chart" else 1', src)
        self.assertIn("殘缺圖重試", src)

    def test_lookup_png_timeout_matches_chart(self):
        """介紹圖／決策卡不得比導航圖更短，否則醒機會只送到 1/3 張。"""
        import bot_servers

        self.assertGreaterEqual(bot_servers._LOOKUP_PNG_TIMEOUT, 120.0)
        self.assertGreaterEqual(bot_servers._LOOKUP_PNG_TIMEOUT, bot_servers._CHART_RENDER_TIMEOUT)
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertIn("_LOOKUP_PNG_TIMEOUT", src)
        self.assertNotIn("60.0, cap_links", src)
        self.assertNotIn('60.0, "高低決策卡"', src)

    def test_chart_progress_both_images_at_once(self):
        txt = WayneTelegramBot._chart_progress_text(3, current="both")
        self.assertIn("介紹圖＋高低卡", txt)
        self.assertIn("一次送出", txt)
        self.assertNotIn("導航", txt)
        self.assertNotIn("其餘三張", txt)
        self.assertLess(txt.index("介紹圖＋高低卡"), txt.index("一次送出"))

    def test_chart_progress_records_sent_stage(self):
        txt = WayneTelegramBot._chart_progress_text(8, sent=["glance", "card"], current="album")
        self.assertIn("現在：一次送出", txt)
        self.assertNotIn("接著：導航圖", txt)
        self.assertNotIn("其餘三張", txt)
        self.assertIn("好了這則會消失", txt)

    def test_chart_progress_table_stage(self):
        txt = WayneTelegramBot._chart_progress_text(1, current="table")
        self.assertIn("讀高低卡", txt)

    def test_album_fail_still_sends_jpeg_photos(self):
        """相簿若失敗，.album.jpg 必須能走 send_photo，不准改送文字版。"""
        from PIL import Image

        from bot_servers import _LOOKUP_ALBUM_CELL

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

        def _png(name: str) -> str:
            path = os.path.join(td, name)
            Image.frombytes("RGB", (800, 900), os.urandom(800 * 900 * 3)).save(path, "PNG")
            return path

        def _cell(path: str, box=None) -> str:
            out = path + ".album.jpg"
            Image.new("RGB", _LOOKUP_ALBUM_CELL, (20, 24, 36)).save(
                out, "JPEG", quality=92
            )
            return out

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
        message.reply_media_group = AsyncMock(side_effect=RuntimeError("album down"))

        async def _run():
            with patch("wayne_navigator.NavigatorEngine", _Engine), patch(
                "chip_tape.build_tape", return_value={}
            ), patch(
                "stock_news.fetch_stock_news_stats", return_value=None
            ), patch(
                "wayne_navigator.render_first_glance_png",
                side_effect=lambda *_a, **_k: _png("g.png"),
            ), patch(
                "wayne_navigator.render_decision_card_png",
                side_effect=lambda *_a, **_k: _png("c.png"),
            ), patch(
                "vol_zone_chart.render_volume_zone_png",
                side_effect=lambda *_a, **_k: _png("vz.png"),
            ), patch.object(
                bot, "_prefetch_mis_quote", return_value=None
            ), patch.object(
                bot, "_quote_header_html", return_value="<b>2330</b>"
            ), patch.object(
                bot, "_hub_keyboard", return_value=None
            ), patch.object(
                bot, "_track_lookup_fade"
            ), patch.object(
                bot, "_dismiss_lookup_fades", new_callable=AsyncMock
            ), patch.object(
                bot, "_cache_lookup_ctx"
            ), patch.object(
                bot, "_remember_card"
            ), patch.object(
                WayneTelegramBot, "_prepare_album_cell", side_effect=_cell
            ):
                await bot._send_card_to_locked(
                    message,
                    "2330",
                    "111",
                    "999:111",
                    [{"stock_id": "2330", "close": 100}],
                )

        asyncio.run(_run())
        self.assertGreaterEqual(message.reply_photo.await_count, 3)
        texts = [
            str(c.args[0]) if c.args else str(c.kwargs)
            for c in message.reply_html.await_args_list + message.reply_text.await_args_list
        ]
        self.assertFalse(any("圖片產出失敗" in t for t in texts))

    def test_op_state_map_works_without_init(self):
        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        state = bot._op_state_map()
        self.assertEqual(state, {})
        state["a"] = {"sent": ["glance"], "current": "card"}
        self.assertEqual(bot._lookup_op_state["a"]["current"], "card")
        bot._op_state_map().pop("a", None)
        self.assertEqual(bot._lookup_op_state, {})


if __name__ == "__main__":
    unittest.main()
