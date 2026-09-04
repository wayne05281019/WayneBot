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

    def test_chart_progress_mentions_glance_first(self):
        txt = WayneTelegramBot._chart_progress_text(3, current="glance")
        self.assertIn("介紹圖", txt)
        self.assertLess(txt.index("介紹圖"), txt.index("決策卡"))
        self.assertLess(txt.index("決策卡"), txt.index("導航"))

    def test_chart_progress_records_sent_stage(self):
        txt = WayneTelegramBot._chart_progress_text(
            8, sent=["glance"], current="card"
        )
        self.assertIn("已送：介紹圖", txt)
        self.assertIn("現在：決策卡", txt)
        self.assertIn("接著：導航圖", txt)

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
