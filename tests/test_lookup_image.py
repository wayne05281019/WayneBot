# -*- coding: utf-8 -*-
"""查股出圖：PNG 驗證與產圖順序。"""
import inspect
import os
import tempfile
import unittest

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
        self.assertIn("rest_items", src)
        self.assertIn("industry_task", src)
        self.assertIn("card_send_task", src)
        self.assertIn("高低溫度卡", src)
        self.assertLess(src.index("card_path"), src.index("rest_items"))
        self.assertIn("_glance_photo_caption", src)
        self.assertIn("_decision_card_photo_caption", src)
        self.assertIn("render_industry_png", src)
        self.assertIn('"industry"', src)
        self.assertIn("generate_chart", src)
        self.assertIn('"chart"', src)

    def test_lookup_native_dpi_higher_than_360(self):
        from industry_card import INDUSTRY_PX_SCALE
        from wayne_navigator import CARD_PNG_DPI, GLANCE_PNG_DPI, NAV_CHART_DPI

        self.assertGreaterEqual(CARD_PNG_DPI, 420)
        self.assertEqual(GLANCE_PNG_DPI, CARD_PNG_DPI)
        self.assertGreaterEqual(NAV_CHART_DPI, 420)
        self.assertGreaterEqual(INDUSTRY_PX_SCALE, 3)

    def test_lookup_album_sends_hq_jpeg(self):
        src = inspect.getsource(WayneTelegramBot._send_lookup_album)
        self.assertIn("_prepare_lookup_album_photo", src)
        self.assertIn("write_timeout", src)
        self.assertIn("BytesIO", src)

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

    def test_card_first_does_not_wait_tape_or_upscale(self):
        src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
        self.assertNotIn("card+tape", src)
        self.assertIn("tape_task", src)
        self.assertLess(src.find("tape_task"), src.find("to_thread(_build_card)"))
        send_i = src.find("card_send_task")
        tape_await = src.find("await tape_task")
        self.assertGreater(send_i, 0)
        self.assertGreater(tape_await, send_i)
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

    def test_chart_progress_card_first_then_rest(self):
        waiting = WayneTelegramBot._chart_progress_text(3, current="card")
        self.assertIn("高低溫度卡", waiting)
        self.assertIn("其餘三張", waiting)
        after = WayneTelegramBot._chart_progress_text(
            8, sent=["card"], current="glance"
        )
        self.assertIn("其餘三張", after)
        self.assertIn("一次送出", after)

    def test_chart_progress_table_stage(self):
        txt = WayneTelegramBot._chart_progress_text(1, current="table")
        self.assertIn("讀高低卡", txt)

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
