# -*- coding: utf-8 -*-
"""查股出圖：PNG 驗證與產圖順序。"""
import os
import tempfile
import unittest

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

    def test_png_looks_ok_accepts_real_card(self):
        from config import get_db_path

        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        from wayne_navigator import NavigatorEngine, render_decision_card_png

        card = NavigatorEngine(db).get_decision_card("2454", merge_live=False)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "card.png")
            out = render_decision_card_png(card, path)
            self.assertTrue(WayneTelegramBot._png_looks_ok(out))

    def test_chart_progress_mentions_glance_first(self):
        txt = WayneTelegramBot._chart_progress_text(3)
        self.assertIn("介紹圖", txt)
        self.assertLess(txt.index("介紹圖"), txt.index("決策卡"))
        self.assertLess(txt.index("決策卡"), txt.index("導航"))


if __name__ == "__main__":
    unittest.main()
