# -*- coding: utf-8 -*-
import unittest

from tg_layout import aligned_block, aligned_rows, headline_lines, html_quote_move, kv_html


class TgLayoutAlignTests(unittest.TestCase):
    def test_html_quote_move_monospace(self):
        s = html_quote_move(-0.79, -419.11)
        self.assertIn("<code>", s)
        self.assertIn("-0.79%", s)
        self.assertIn("-419.11點", s)

    def test_aligned_rows_one_per_line(self):
        body = aligned_rows(
            [
                ("道瓊", html_quote_move(-0.79, -419.11)),
                ("那斯達克", html_quote_move(-1.03, -271.09)),
            ],
            label_width=8,
        )
        self.assertEqual(body.count("\n"), 1)
        self.assertIn("道瓊", body)
        self.assertIn("那斯達克", body)

    def test_headline_lines_not_crammed(self):
        h = headline_lines("<b>標題</b>", "第二行", "第三行")
        self.assertEqual(h.count("\n"), 2)


if __name__ == "__main__":
    unittest.main()
