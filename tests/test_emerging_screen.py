# -*- coding: utf-8 -*-
"""興櫃獨立海選：官方日均價、不混進上市櫃海選。"""
import os
import sqlite3
import tempfile
import unittest

from emerging_quotes import (
    parse_emerging_csv,
    parse_emerging_openapi,
    roc_yyyymmdd,
    upsert_emerging_rows,
    load_emerging_frames,
    sync_emerging_quotes,
    latest_emerging_date,
    emerging_rows_on,
)
from wayne_db import ensure_core_schema


CSV = """TITLE,Daily Trading Table
DATADATE,Date:2026/09/07
HEADER,Security Code,Security Name,Last Best Bid Quote,Last Best Ask Quote,Avg.,Prev. Average,Change,Change (%),Highest,Lowest,Last,Trading Volume(Shares),Trading Value (NTD)
BODY,"3595  ","SAMPLE              ","10.00  ","11.00  ","10.50  ","10.00  ","+0.50    ","+5.00    ","11.00  ","10.00  ","10.80  ","12,000        ","126,000       "
"""


class EmergingQuotesParseTests(unittest.TestCase):
    def test_roc_and_csv_map_official_avg_to_close(self):
        self.assertEqual(roc_yyyymmdd("1150907"), "20260907")
        self.assertEqual(roc_yyyymmdd("20260907"), "20260907")
        as_of, rows = parse_emerging_csv(CSV)
        self.assertEqual(as_of, "20260907")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["stock_id"], "3595")
        self.assertEqual(r["close"], 10.5)
        self.assertEqual(r["open"], 10.0)
        self.assertEqual(r["high"], 11.0)
        self.assertEqual(r["low"], 10.0)
        self.assertEqual(r["volume"], 12)
        self.assertEqual(r["source"], "tpex_esb_csv")

    def test_openapi_maps_chinese_name_and_average(self):
        as_of, rows = parse_emerging_openapi(
            [
                {
                    "Date": "1150907",
                    "SecuritiesCompanyCode": "3595",
                    "CompanyName": "山太士",
                    "PreviousAveragePrice": "10",
                    "Highest": "11",
                    "Lowest": "9.5",
                    "Average": "10.2",
                    "LatestPrice": "10.5",
                    "TransactionVolume": "5000",
                }
            ]
        )
        self.assertEqual(as_of, "20260907")
        self.assertEqual(rows[0]["stock_name"], "山太士")
        self.assertEqual(rows[0]["close"], 10.2)
        self.assertEqual(rows[0]["source"], "tpex_esb_openapi")

    def test_sync_fills_recent_gap_when_history_already_long(self):
        from datetime import datetime, timedelta
        from unittest.mock import patch

        from emerging_quotes import ensure_emerging_table

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            ensure_emerging_table(path)
            conn = sqlite3.connect(path)
            d = datetime(2026, 9, 21)
            n = 0
            while n < 40:
                if d.weekday() < 5:
                    ymd = d.strftime("%Y%m%d")
                    conn.execute(
                        "INSERT INTO emerging_quotes("
                        "date,stock_id,stock_name,market,open,high,low,close,"
                        "volume,turnover_k,pct_change,avg_price,source) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ymd, "3595", "山太士", "EM", 10, 11, 9, 10, 1, 1, 0, 10, "seed"),
                    )
                    n += 1
                d -= timedelta(days=1)
            conn.execute(
                "INSERT INTO daily_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,volume,"
                "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260923", "2330", "台積電", "TW", 1, 1, 1, 1, 1, 1, 0, 1),
            )
            conn.commit()
            conn.close()
            self.assertEqual(latest_emerging_date(path), "20260921")
            fetched = []

            def fake_open(*_a, **_k):
                return "", []

            def fake_csv(ymd, session=None):
                fetched.append(ymd)
                return ymd, [
                    {
                        "stock_id": "3595",
                        "stock_name": "山太士",
                        "open": 12.0,
                        "high": 13.0,
                        "low": 11.0,
                        "close": 12.5,
                        "volume": 10,
                        "turnover_k": 12.5,
                        "pct_change": 1.0,
                        "avg_price": 12.5,
                        "source": "tpex_esb_csv",
                    }
                ]

            with patch("emerging_quotes.fetch_emerging_openapi", fake_open), patch(
                "emerging_quotes.fetch_emerging_csv_day", fake_csv
            ):
                stats = sync_emerging_quotes(path, cap="20260923", sleep_s=0)
            self.assertIn("20260922", fetched)
            self.assertIn("20260923", fetched)
            self.assertGreaterEqual(stats.get("gaps") or 0, 1)
            self.assertEqual(latest_emerging_date(path), "20260923")
            self.assertGreaterEqual(emerging_rows_on(path, "20260923"), 1)
        finally:
            os.remove(path)


    def test_sync_fills_middle_gap_even_if_newer_day_exists(self):
        from unittest.mock import patch

        from emerging_quotes import ensure_emerging_table, missing_emerging_days

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            ensure_emerging_table(path)
            conn = sqlite3.connect(path)
            q = (
                "INSERT INTO emerging_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,"
                "volume,turnover_k,pct_change,avg_price,source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )
            for ymd in ("20260918", "20260921", "20260924"):
                conn.execute(
                    q,
                    (ymd, "3595", "山太士", "EM", 10, 11, 9, 10, 1, 1, 0, 10, "seed"),
                )
            conn.execute(
                "INSERT INTO daily_quotes("
                "date,stock_id,stock_name,market,open,high,low,close,volume,"
                "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260923", "2330", "台積電", "TW", 1, 1, 1, 1, 1, 1, 0, 1),
            )
            conn.commit()
            conn.close()
            self.assertEqual(latest_emerging_date(path), "20260924")
            holes = missing_emerging_days(path, "20260923", lookback=8)
            self.assertIn("20260922", holes)
            self.assertIn("20260923", holes)
            fetched = []

            def fake_open(*_a, **_k):
                return "20260924", [
                    {
                        "stock_id": "3595",
                        "stock_name": "山太士",
                        "open": 15,
                        "high": 16,
                        "low": 14,
                        "close": 15,
                        "volume": 1,
                        "turnover_k": 15,
                        "pct_change": 0,
                        "avg_price": 15,
                        "source": "tpex_esb_openapi",
                    }
                ]

            def fake_csv(ymd, session=None):
                fetched.append(ymd)
                return ymd, [
                    {
                        "stock_id": "3595",
                        "stock_name": "山太士",
                        "open": 12.0,
                        "high": 13.0,
                        "low": 11.0,
                        "close": 12.5,
                        "volume": 10,
                        "turnover_k": 12.5,
                        "pct_change": 1.0,
                        "avg_price": 12.5,
                        "source": "tpex_esb_csv",
                    }
                ]

            with patch("emerging_quotes.fetch_emerging_openapi", fake_open), patch(
                "emerging_quotes.fetch_emerging_csv_day", fake_csv
            ):
                stats = sync_emerging_quotes(path, cap="20260923", sleep_s=0)
            self.assertIn("20260922", fetched)
            self.assertIn("20260923", fetched)
            self.assertGreaterEqual(stats.get("gaps") or 0, 1)
            self.assertGreaterEqual(emerging_rows_on(path, "20260922"), 1)
            self.assertGreaterEqual(emerging_rows_on(path, "20260923"), 1)
        finally:
            os.remove(path)


class EmergingScreenIsolationTests(unittest.TestCase):
    def test_listed_screen_drops_emerging_universe(self):
        from screening_engine import ScreeningEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.executemany(
                "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?, '', 1, 't')",
                [
                    ("4915", "致伸", "TW", "STOCK"),
                    ("3595", "山太士", "EM", "STOCK"),
                ],
            )
            q = "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            for sid, name, mkt in (("4915", "致伸", "TW"), ("3595", "山太士", "EM")):
                conn.execute(
                    q,
                    ("20260907", sid, name, mkt, 10, 11, 9, 10, 5000, 80000, 1.0, 10, 0, 0, 0),
                )
            conn.commit()
            conn.close()
            dfs = ScreeningEngine(path).load_market_data(
                "20260907", min_volume=1000, min_turnover_k=30000
            )
            self.assertIn("4915", dfs)
            self.assertNotIn("3595", dfs)
        finally:
            os.remove(path)

    def test_emerging_frames_not_from_listed_quotes(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            rows = []
            for i in range(6):
                d = f"2026082{i+1}"
                rows.append(
                    (
                        d,
                        {
                            "stock_id": "3595",
                            "stock_name": "山太士",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10 + i * 0.1,
                            "volume": 12,
                            "turnover_k": 126,
                            "pct_change": 1,
                            "avg_price": 10 + i * 0.1,
                            "source": "tpex_esb_csv",
                        },
                    )
                )
            for d, rec in rows:
                upsert_emerging_rows(path, d, [rec])
            frames = load_emerging_frames(path, "20260826")
            self.assertIn("3595", frames)
            self.assertGreaterEqual(len(frames["3595"]), 5)
            from screening_engine import ScreeningEngine

            out = ScreeningEngine(path).run_emerging_screening("20260826", sync=False)
            self.assertEqual(out["universe"], "EM")
            self.assertIn("leave_zero", out)
            self.assertIn("golden_buy", out)
        finally:
            os.remove(path)

    def test_payload_title_is_emerging(self):
        from screening_engine import EMERGING_PUSH_SPECS, format_screening_payload

        parts = format_screening_payload(
            {"leave_zero": [], "golden_buy": []},
            "20260907",
            title="WayneBot 興櫃海選",
            specs=EMERGING_PUSH_SPECS,
        )
        blob = "\n".join(p.get("html") or "" for p in parts)
        self.assertIn("興櫃海選", blob)
        self.assertNotIn("周帶量", blob)

    def test_decision_card_reads_emerging_bars_not_listed(self):
        from wayne_navigator import NavigatorEngine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            ensure_core_schema(path)
            conn = sqlite3.connect(path)
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260810", "2330", "台積電", "TW", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
            )
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260810", "3595", "山太士", "TWO", 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
            )
            conn.commit()
            conn.close()
            rows = []
            for i in range(20):
                d = f"202608{i+1:02d}" if i < 31 else f"202609{i-30:02d}"
                rows.append(
                    (
                        d,
                        {
                            "stock_id": "3595",
                            "stock_name": "山太士",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10 + i * 0.05,
                            "volume": 12,
                            "turnover_k": 126,
                            "pct_change": 1,
                            "avg_price": 10 + i * 0.05,
                            "source": "tpex_esb_csv",
                        },
                    )
                )
            for d, rec in rows:
                upsert_emerging_rows(path, d, [rec])
            card = NavigatorEngine(path).get_decision_card("3595", merge_live=False)
            self.assertNotIn("error", card)
            self.assertEqual(card.get("quote_source"), "emerging_quotes")
            self.assertEqual(card.get("listing"), "興櫃")
            self.assertIn("興櫃官方日均價", card.get("badges") or [])
            last_em = max(d for d, _ in rows)
            self.assertEqual(str(card.get("latest_date")).replace("-", "")[:8], last_em)
        finally:
            os.remove(path)
        from intent_router import parse_intent

        self.assertEqual(parse_intent("興櫃海選").kind, "emerging_screen")
        self.assertEqual(parse_intent("興櫃名單").kind, "emerging_screen")
        self.assertEqual(parse_intent("興櫃").kind, "emerging_screen")
        self.assertEqual(parse_intent("海選").kind, "screen")

    def test_increment_job_syncs_emerging_not_into_daily_quotes(self):
        src = open("main_runner.py", encoding="utf-8").read()
        self.assertIn("sync_emerging_quotes", src)
        self.assertIn("cap=fuse_to", src)
        self.assertIn("興櫃補齊寫入", src)
        self.assertIn("興櫃收盤再寫", src)
        emsrc = open("emerging_quotes.py", encoding="utf-8").read()
        self.assertNotIn("if have >= 40:", emsrc)
        self.assertIn("_weekdays_after", emsrc)
        nav = open("wayne_navigator.py", encoding="utf-8").read()
        self.assertIn("load_stock_bars", nav)
        self.assertIn("興櫃官方日均價", nav)
        load_fn = open("screening_engine.py", encoding="utf-8").read()
        start = load_fn.index("def load_market_data")
        chunk = load_fn[start : start + 1800]
        self.assertIn("NOT IN ('EM', 'EMERGING')", chunk)
        self.assertNotIn("emerging_quotes", chunk)


if __name__ == "__main__":
    unittest.main()
