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

    def test_wrap_cjk_does_not_leave_orphan_char(self):
        from tg_layout import wrap_cjk_lines

        lines = wrap_cjk_lines("準備減碼不是買訊", 14)
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(all(len(ln.strip()) >= 2 for ln in lines), lines)
        self.assertNotEqual(lines[-1], "訊")
        joined = "".join(lines)
        self.assertEqual(joined, "準備減碼不是買訊")

    def test_wrap_cjk_glues_hanging_period(self):
        from tg_layout import wrap_cjk_lines

        lines = wrap_cjk_lines("先看表，先等。", 8)
        self.assertTrue(lines)
        self.assertNotEqual(lines[-1].strip(), "。")
        self.assertEqual("".join(lines), "先看表，先等。")

    def test_reflow_telegram_html_breaks_sentences_not_orphan(self):
        from tg_layout import reflow_telegram_html

        html = (
            "早報／海選優先認<b>黃金買點</b>：獲利格剛離開 0。"
            "認表、按表操課，不認圖上紅箭頭。低買高賣。"
        )
        out = reflow_telegram_html(html, width=18)
        self.assertIn("黃金買點", out)
        self.assertIn("<b>", out)
        self.assertIn("</b>", out)
        self.assertGreaterEqual(out.count("\n"), 1)
        for ln in out.split("\n"):
            plain = ln.replace("<b>", "").replace("</b>", "").strip()
            if not plain:
                continue
            self.assertNotEqual(plain, "。")
            self.assertGreaterEqual(len(plain), 2)

    def test_reflow_keeps_compact_kv_line(self):
        from tg_layout import reflow_telegram_html

        line = "收盤　60.80　漲跌　+2.01%"
        self.assertEqual(reflow_telegram_html(line, width=18), line)

    def test_reflow_splits_menu_row_at_bar(self):
        from tg_layout import reflow_telegram_html

        html = "第一排：<b>說明</b>｜<b>海選</b>｜<b>持股</b>｜<b>觀察</b>｜<b>刷新</b>｜<b>回報</b>"
        out = reflow_telegram_html(html, width=18)
        self.assertGreaterEqual(out.count("\n"), 1)
        self.assertIn("說明", out)
        self.assertIn("回報", out)
        blob = out.replace("\n", "")
        self.assertIn("<b>說明</b>", blob)
        self.assertEqual(blob.count("<b>"), blob.count("</b>"))

    def test_reflow_does_not_split_inside_bold_slash(self):
        from tg_layout import reflow_telegram_html

        html = "3　兩張圖出來後，<b>籌碼／營收／產業／K線／導航圖</b>在圖下面，不在右側四格鍵盤"
        out = reflow_telegram_html(html, width=18)
        self.assertIn("<b>籌碼／營收／產業／K線／導航圖</b>", out.replace("\n", ""))
        self.assertEqual(out.count("<b>"), out.count("</b>"))
        self.assertGreaterEqual(out.count("\n"), 1)

    def test_wrap_cjk_keeps_short_text(self):
        from tg_layout import wrap_cjk_lines

        self.assertEqual(wrap_cjk_lines("439股", 20), ["439股"])
        self.assertEqual(wrap_cjk_lines("", 20), [])


if __name__ == "__main__":
    unittest.main()
