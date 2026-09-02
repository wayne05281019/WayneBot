# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from config import get_db_path


class LookupRenderTests(unittest.TestCase):
    def test_parallel_card_glance_produces_files(self):
        db = get_db_path()
        if not os.path.isfile(db):
            self.skipTest("no db")
        from wayne_navigator import NavigatorEngine
        from lookup_render import render_card_and_glance_parallel

        card = NavigatorEngine(db).get_decision_card("2330", merge_live=False)
        self.assertNotIn("error", card)
        ohlc = card.pop("_ohlc", None)
        with tempfile.TemporaryDirectory() as tmp:
            card_p = os.path.join(tmp, "c.png")
            glance_p = os.path.join(tmp, "g.png")
            cp, gp = render_card_and_glance_parallel(
                card, card_p, "2330", {}, glance_p, db
            )
            self.assertTrue(cp and os.path.isfile(cp))
            self.assertTrue(gp and os.path.isfile(gp))
            self.assertGreater(os.path.getsize(cp), 5000)
            self.assertGreater(os.path.getsize(gp), 5000)


if __name__ == "__main__":
    unittest.main()
