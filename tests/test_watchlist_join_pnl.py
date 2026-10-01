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


def _seed_complete_day(conn: sqlite3.Connection, day: str, *, tw_close: float = 100.0) -> None:
    """上市＋上櫃過門檻，讓 latest_complete_quote_date 認這日。"""
    for i in range(800):
        sid = "2330" if i == 0 else f"T{i:04d}"
        px = tw_close if sid == "2330" else 10.0
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES (?, ?, ?, 'TW', ?, ?, ?, ?, 1000, 1000, 0, ?)""",
            (day, sid, "台積電" if sid == "2330" else "x", px, px, px, px, px),
        )
    for i in range(600):
        px = 10.0
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES (?, ?, 'y', 'TWO', ?, ?, ?, ?, 1, 1, 0, ?)""",
            (day, f"O{i:04d}", px, px, px, px, px),
        )


def _seed(db: str) -> None:
    from wayne_db import ensure_core_schema

    ensure_core_schema(db)
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("DELETE FROM daily_quotes WHERE stock_id='2330' OR stock_id LIKE 'T%' OR stock_id LIKE 'O%'")
    for day, px in (("20260915", 100.0), ("20260922", 105.0), ("20260924", 110.0)):
        _seed_complete_day(conn, day, tw_close=px)
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
        with patch("wayne_db.resolve_watch_view_as_of", return_value=("20260924", None)):
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
        with patch("wayne_db.resolve_watch_view_as_of", return_value=("20260924", None)):
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
        with patch("wayne_db.resolve_watch_view_as_of", return_value=("20260922", None)):
            info = watchlist_join_pnl(self.db, rows, now=now)["2330"]
        self.assertEqual(info["status"], "no_join_close")
        self.assertIsNone(info["pnl_pct"])

    def test_after_close_before_1630_uses_today_if_complete(self):
        """13:30–16:30：fuse 仍卡昨日，觀察清單要用今日完整收（不卡 16:30）。"""
        from wayne_db import resolve_watch_view_as_of, watch_display_cap, watchlist_join_pnl

        conn = sqlite3.connect(self.db)
        _seed_complete_day(conn, "20261001", tw_close=120.0)
        conn.commit()
        conn.close()
        now = datetime(2026, 10, 1, 14, 30, tzinfo=TAIPEI)
        self.assertEqual(watch_display_cap(now), "20261001")
        as_of, lag = resolve_watch_view_as_of(self.db, now=now)
        self.assertEqual(as_of, "20261001")
        self.assertIsNone(lag)
        rows = [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "created_at": "2026-09-15T10:00:00+08:00",
            }
        ]
        info = watchlist_join_pnl(self.db, rows, now=now)["2330"]
        self.assertEqual(info["view_ymd"], "20261001")
        self.assertAlmostEqual(info["view_close"], 120.0)
        self.assertAlmostEqual(info["pnl_pct"], 20.0)

    def test_after_close_sync_lag_honest_message(self):
        """收盤後今日尚未進庫：查看日停在上一完整日，並如實寫 lag。"""
        from wayne_db import resolve_watch_view_as_of, watchlist_join_pnl

        # seed already has complete through 20260924 only
        now = datetime(2026, 10, 1, 14, 30, tzinfo=TAIPEI)
        as_of, lag = resolve_watch_view_as_of(self.db, now=now)
        self.assertEqual(as_of, "20260924")
        self.assertIsNotNone(lag)
        self.assertIn("2026/10/01", lag)
        self.assertIn("2026/09/24", lag)
        self.assertIn("尚未寫入", lag)
        rows = [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "created_at": "2026-09-15T10:00:00+08:00",
            }
        ]
        info = watchlist_join_pnl(self.db, rows, now=now)["2330"]
        self.assertEqual(info["view_ymd"], "20260924")

    def test_midday_incomplete_not_used_as_view(self):
        """盤中 11:00：即使庫裡已有今日列，也不當官方查看日。"""
        from wayne_db import resolve_watch_view_as_of, watch_display_cap

        conn = sqlite3.connect(self.db)
        _seed_complete_day(conn, "20260930", tw_close=115.0)
        _seed_complete_day(conn, "20261001", tw_close=120.0)
        conn.commit()
        conn.close()
        now = datetime(2026, 10, 1, 11, 0, tzinfo=TAIPEI)
        self.assertEqual(watch_display_cap(now), "20260930")
        as_of, lag = resolve_watch_view_as_of(self.db, now=now)
        self.assertEqual(as_of, "20260930")
        self.assertIsNone(lag)

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
            with patch("wayne_db.resolve_watch_view_as_of", return_value=("20260924", None)):
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

    def test_render_watch_shows_lag_when_sync_behind(self):
        from bot_servers import WayneTelegramBot
        from wayne_db import get_user_watchlist

        bot = object.__new__(WayneTelegramBot)
        bot.db_path = self.db
        bot.WATCH_LIST_LIMIT = 30
        lag = "<i>應顯示 2026/10/01（四）收盤，目前僅有 2026/09/24（四）（盤後更新中或尚未寫入）。</i>"
        with patch("money_flow.industry_flows_for_stocks", return_value={}):
            with patch("wayne_db.resolve_watch_view_as_of", return_value=("20260924", lag)):
                with patch("wayne_db.watchlist_join_pnl", return_value={}):
                    html, _kb = bot._render_watch([])
        self.assertIn("尚未寫入", html)
        self.assertIn("2026/10/01", html)


if __name__ == "__main__":
    unittest.main()
