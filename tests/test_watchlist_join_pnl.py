# -*- coding: utf-8 -*-
"""觀察清單：加入日＋官方收損益％。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def _seed(db: str) -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("DELETE FROM daily_quotes WHERE stock_id='2330'")
    for day, px in (("20260915", 100.0), ("20260922", 105.0), ("20260924", 110.0)):
        conn.execute(
            """INSERT INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES (?, '2330', '台積電', 'TW', ?, ?, ?, ?, 1000, 1000, 0, ?)""",
            (day, px, px, px, px, px),
        )
    try:
        conn.execute("DELETE FROM emerging_quotes WHERE stock_id='3595'")
    except sqlite3.OperationalError:
        pass
    for day, px in (("20260915", 20.0), ("20260924", 22.0)):
        conn.execute(
            """INSERT OR REPLACE INTO emerging_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES (?, '3595', '山太士', 'EM', ?, ?, ?, ?, 1000, 1000, 0, ?)""",
            (day, px, px, px, px, px),
        )
    conn.commit()
    conn.close()


class WatchlistJoinPnlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "w.db")
        _seed(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_stores_taipei_created_at_and_get_returns_it(self):
        from wayne_db import add_to_watchlist, get_user_watchlist, parse_watch_join_ymd

        add_to_watchlist(self.db, "9001", "2330", "台積電")
        rows = get_user_watchlist(self.db, "9001")
        self.assertEqual(len(rows), 1)
        self.assertIn("created_at", rows[0])
        self.assertTrue(str(rows[0]["created_at"]))
        ymd = parse_watch_join_ymd(rows[0]["created_at"])
        self.assertEqual(len(ymd or ""), 8)
        # 新寫入應帶台北偏移
        self.assertIn("+08:00", str(rows[0]["created_at"]))

    def test_readd_keeps_original_join_day(self):
        from wayne_db import add_to_watchlist, get_user_watchlist

        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO user_watchlist (user_id, stock_code, stock_name, created_at) "
            "VALUES ('9001','2330','台積電','2026-09-15T09:00:00+08:00')"
        )
        conn.commit()
        conn.close()
        add_to_watchlist(self.db, "9001", "2330", "台積電")
        row = get_user_watchlist(self.db, "9001")[0]
        self.assertTrue(str(row["created_at"]).startswith("2026-09-15"))

    def test_pnl_listed_official_closes(self):
        from wayne_db import watchlist_join_pnl

        now = datetime(2026, 9, 25, 10, 0, tzinfo=TAIPEI)
        rows = [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "created_at": "2026-09-15T10:00:00+08:00",
            }
        ]
        with patch("quote_integrity.db_as_of_trading_date", return_value="20260924"):
            info = watchlist_join_pnl(self.db, rows, now=now)["2330"]
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["join_ymd"], "20260915")
        self.assertEqual(info["view_ymd"], "20260924")
        self.assertAlmostEqual(info["join_close"], 100.0)
        self.assertAlmostEqual(info["view_close"], 110.0)
        self.assertAlmostEqual(info["pnl_pct"], 10.0)

    def test_pnl_emerging(self):
        from wayne_db import watchlist_join_pnl

        now = datetime(2026, 9, 25, 10, 0, tzinfo=TAIPEI)
        rows = [
            {
                "stock_code": "3595",
                "stock_name": "山太士",
                "created_at": "2026-09-15T10:00:00+08:00",
            }
        ]
        with patch("quote_integrity.db_as_of_trading_date", return_value="20260924"):
            info = watchlist_join_pnl(self.db, rows, now=now)["3595"]
        self.assertEqual(info["status"], "ok")
        self.assertAlmostEqual(info["pnl_pct"], 10.0)

    def test_no_join_date_no_fake_pct(self):
        from wayne_db import format_watch_join_pnl_line, watchlist_join_pnl

        rows = [{"stock_code": "2330", "stock_name": "台積電", "created_at": ""}]
        info = watchlist_join_pnl(self.db, rows)["2330"]
        self.assertEqual(info["status"], "no_join")
        self.assertIsNone(info["pnl_pct"])
        self.assertIn("無加入日", format_watch_join_pnl_line(info))

    def test_intraday_join_day_not_official_yet(self):
        from wayne_db import watchlist_join_pnl

        now = datetime(2026, 9, 24, 11, 0, tzinfo=TAIPEI)
        rows = [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "created_at": "2026-09-24T10:00:00+08:00",
            }
        ]
        with patch("quote_integrity.db_as_of_trading_date", return_value="20260922"):
            info = watchlist_join_pnl(self.db, rows, now=now)["2330"]
        self.assertEqual(info["status"], "no_join_close")
        self.assertIsNone(info["pnl_pct"])

    def test_users_isolated(self):
        from wayne_db import add_to_watchlist, get_user_watchlist

        add_to_watchlist(self.db, "9001", "2330", "台積電")
        add_to_watchlist(self.db, "9002", "3595", "山太士")
        w = {r["stock_code"] for r in get_user_watchlist(self.db, "9001")}
        b = {r["stock_code"] for r in get_user_watchlist(self.db, "9002")}
        self.assertEqual(w, {"2330"})
        self.assertEqual(b, {"3595"})

    def test_render_watch_shows_join_pnl_one_line(self):
        from bot_servers import WayneTelegramBot
        from wayne_db import get_user_watchlist

        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO user_watchlist (user_id, stock_code, stock_name, created_at) "
            "VALUES ('9001','2330','台積電','2026-09-15T09:00:00+08:00')"
        )
        conn.commit()
        conn.close()
        bot = object.__new__(WayneTelegramBot)
        bot.db_path = self.db
        bot.WATCH_LIST_LIMIT = 30
        with patch("money_flow.industry_flows_for_stocks", return_value={}):
            with patch("wayne_db.watchlist_join_pnl") as mock_pnl:
                mock_pnl.return_value = {
                    "2330": {
                        "join_ymd": "20260915",
                        "view_ymd": "20260924",
                        "join_close": 100.0,
                        "view_close": 110.0,
                        "pnl_pct": 10.0,
                        "status": "ok",
                    }
                }
                html, kb = bot._render_watch(get_user_watchlist(self.db, "9001"))
        self.assertIn("9/15→9/24", html)
        self.assertIn("+10.0%", html)
        stock_lines = [ln for ln in html.splitlines() if ln.startswith("•")]
        self.assertEqual(len(stock_lines), 1)
        self.assertIn("2330", stock_lines[0])
        self.assertIn("9/15→9/24", stock_lines[0])
        self.assertIn("損益％", html)
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("k:2330", datas)
        self.assertIn("rw:2330", datas)


if __name__ == "__main__":
    unittest.main()
