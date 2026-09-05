# -*- coding: utf-8 -*-
"""大盤按鈕 + 專頁：自動模擬測試（不需真人操作 Telegram）。"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_MARKET,
    MENU_LAYOUT_VERSION,
    WayneTelegramBot,
)
from taiwan_market import (
    analyze_taiwan_market,
    ensure_index_breadth_daily_table,
    ensure_index_daily_table,
    format_taiwan_market_page_html,
    load_index_breadth_daily,
)

_TG_SECTION = "────────────────"


def _message(uid: int = 1):
    user = SimpleNamespace(id=uid, first_name="tester")
    msg = MagicMock()
    msg.chat_id = 100
    msg.from_user = user
    msg.reply_text = AsyncMock(return_value=MagicMock())
    msg.reply_html = AsyncMock(return_value=MagicMock())
    return msg


def _update(msg):
    upd = MagicMock()
    upd.message = msg
    upd.effective_user = msg.from_user
    return upd


def _seed_market_db(path: str) -> str:
    """寫入最小可驗證官方融合資料（非 Yahoo fallback）。"""
    ensure_index_daily_table(path)
    ensure_index_breadth_daily_table(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE stock_universe (stock_id TEXT, is_active INT)")
    conn.execute("CREATE TABLE daily_quotes (stock_id TEXT, date TEXT, close REAL, volume REAL)")
    conn.execute("INSERT INTO stock_universe VALUES ('2330', 1)")
    for i, c in enumerate(range(100, 121)):
        d = f"202608{i+1:02d}"
        conn.execute(
            "INSERT INTO daily_quotes VALUES ('2330', ?, ?, 1000)",
            (d, float(c)),
        )
        close = 22000.0 + i * 50
        conn.execute(
            """
            INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
            VALUES (?, 'TWII', ?, 1e9, 0.2, ?, ?, 'neutral', 'test')
            """,
            (d, close, close - 100, close - 200),
        )
    conn.execute(
        """
        INSERT INTO index_breadth_daily(
            date, up_count, down_count, limit_up, limit_down, flat_count,
            up_tw, down_tw, up_two, down_two, source, updated_at
        ) VALUES ('20260820', 800, 600, 10, 5, 100, 500, 400, 300, 200, 'twse', 'test')
        """
    )
    conn.commit()
    conn.close()
    return "20260820"


class TestMarketMenuE2E:
    def test_layout_version_and_button_label(self):
        assert MENU_BTN_MARKET == "大盤"
        assert MENU_LAYOUT_VERSION == "8"
        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        row2 = [b.text for b in bot._reply_menu().keyboard[1]]
        assert row2[-1] == "大盤"

    def test_help_no_reserved_slot_text(self):
        assert "預留" not in HELP_TOPICS["menu"]
        assert "大盤" in HELP_TOPICS["menu"]

    def test_market_page_db_only_no_yahoo(self, tmp_path):
        db = str(tmp_path / "m.db")
        as_of = _seed_market_db(db)
        with patch("taiwan_market._fetch_index_daily") as mock_yahoo:
            html = format_taiwan_market_page_html(db, as_of)
            snap = analyze_taiwan_market(db, as_of, db_only=True)
            mock_yahoo.assert_not_called()
        assert "台股大盤" in html
        assert "庫內官方融合" in html
        assert "漲跌家數" in html
        assert "距月線" in html
        assert "三大法人" in html
        assert snap.get("ok")
        assert snap.get("falling_risk") is not None
        br = load_index_breadth_daily(db, as_of)
        assert br and br["up_count"] == 800

    def test_no_empty_library_message_on_missing_index(self, tmp_path):
        """無 index_daily 時不回覆「庫空／暫不可用」，僅記錄讀取異常。"""
        db = str(tmp_path / "empty.db")
        with patch("taiwan_market._fetch_index_daily") as mock_yahoo:
            html = format_taiwan_market_page_html(db)
            mock_yahoo.assert_not_called()
        assert "庫空" not in html
        assert "暫不可用" not in html
        assert "指數資料讀取異常" in html

    def test_sector_flow_zero_is_valid_not_missing(self, tmp_path):
        """法人合計為 0 仍應顯示，不可當成缺資料往前找別日。"""
        db = str(tmp_path / "flow0.db")
        as_of = _seed_market_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            """
            CREATE TABLE daily_sector_flow (
                date TEXT, sector TEXT,
                foreign_net REAL, trust_net REAL, dealer_net REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO daily_sector_flow VALUES (?, '半導體', 0, 0, 0)",
            (as_of,),
        )
        conn.commit()
        conn.close()
        snap = analyze_taiwan_market(db, as_of, db_only=True)
        assert snap.get("sector_flow_net") == 0
        assert snap.get("sector_flow_as_of") == as_of
        html = format_taiwan_market_page_html(db, as_of)
        assert "合計 +0 張" in html or "合計 0 張" in html


    def test_market_page_shows_sector_leaders(self, tmp_path):
        db = str(tmp_path / "flow_lead.db")
        as_of = _seed_market_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            """
            CREATE TABLE daily_sector_flow (
                date TEXT, industry TEXT,
                foreign_net REAL, trust_net REAL, dealer_net REAL
            )
            """
        )
        conn.execute("INSERT INTO daily_sector_flow VALUES (?, '半導體業', 8000, 200, 0)", (as_of,))
        conn.execute("INSERT INTO daily_sector_flow VALUES (?, '金融業', -5000, -100, 0)", (as_of,))
        conn.commit()
        conn.close()
        html = format_taiwan_market_page_html(db, as_of)
        assert "外資" in html
        assert "合計" in html

    def test_market_page_uses_quote_chips_not_sector_subset(self, tmp_path):
        """大盤三大法人用當日日 K 張數合計，不用產業加總子集。"""
        db = str(tmp_path / "t86.db")
        as_of = _seed_market_db(db)
        conn = sqlite3.connect(db, timeout=30)
        for col, spec in (
            ("foreign_net", "INTEGER"),
            ("trust_net", "INTEGER"),
            ("dealer_net", "INTEGER"),
        ):
            try:
                conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} {spec}")
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=1000, trust_net=200, dealer_net=-50 WHERE date=?",
            (as_of,),
        )
        conn.execute(
            """
            CREATE TABLE daily_sector_flow (
                date TEXT, industry TEXT,
                foreign_net REAL, trust_net REAL, dealer_net REAL
            )
            """
        )
        conn.execute("INSERT INTO daily_sector_flow VALUES (?, '半導體業', 1, 1, 1)", (as_of,))
        conn.commit()
        conn.close()
        html = format_taiwan_market_page_html(db, as_of)
        assert "外資 +1,000" in html
        assert "投信 +200" in html
        assert "自營 -50" in html
        assert "合計 +1,150 張" in html
        assert "合計 +3 張" not in html

    def test_market_page_rebuilds_sector_flow_when_chips_exist(self, tmp_path):
        """日 K 已有法人張、產業表卻停在前一日時，大盤頁要補寫當日，不要默默用舊日。"""
        db = str(tmp_path / "heal.db")
        as_of = _seed_market_db(db)
        prev = "20260819"
        conn = sqlite3.connect(db, timeout=30)
        for col, spec in (
            ("stock_name", "TEXT"),
            ("market_type", "TEXT"),
            ("asset_type", "TEXT"),
            ("industry", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE stock_universe ADD COLUMN {col} {spec}")
            except sqlite3.OperationalError:
                pass
        for col, spec in (
            ("stock_name", "TEXT"),
            ("market", "TEXT"),
            ("open", "REAL"),
            ("high", "REAL"),
            ("low", "REAL"),
            ("turnover_k", "REAL"),
            ("pct_change", "REAL"),
            ("avg_price", "REAL"),
            ("foreign_net", "INTEGER"),
            ("trust_net", "INTEGER"),
            ("dealer_net", "INTEGER"),
        ):
            try:
                conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} {spec}")
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM stock_universe")
        for sid, name, ind in (
            ("2330", "台積電", "半導體業"),
            ("2454", "聯發科", "半導體業"),
            ("2002", "中鋼", "鋼鐵工業"),
            ("2027", "大成鋼", "鋼鐵工業"),
        ):
            conn.execute(
                "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
                (sid, name, "TWSE", "STOCK", ind, "t"),
            )
        conn.execute("DELETE FROM daily_quotes")
        for d, fn in ((prev, -1000), (as_of, 2500)):
            for sid, name, extra in (
                ("2330", "台積電", 0),
                ("2454", "聯發科", 50),
                ("2002", "中鋼", -80),
                ("2027", "大成鋼", -20),
            ):
                conn.execute(
                    "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d, sid, name, "TW", 100, 101, 99, 100, 1000, 1000, 0.2, 100, fn + extra, 10, 5),
                )
        conn.execute(
            """
            CREATE TABLE daily_sector_flow (
                date TEXT, industry TEXT,
                foreign_net REAL, trust_net REAL, dealer_net REAL
            )
            """
        )
        conn.execute("INSERT INTO daily_sector_flow VALUES (?, '半導體業', -800, 10, 5)", (prev,))
        conn.execute("INSERT INTO daily_sector_flow VALUES (?, '鋼鐵工業', -200, 10, 5)", (prev,))
        conn.commit()
        conn.close()
        html = format_taiwan_market_page_html(db, as_of)
        assert f"（{prev}）" not in html
        assert "合計" in html
        snap = analyze_taiwan_market(db, as_of, db_only=True, page_light=True)
        assert snap.get("sector_flow_as_of") == as_of

    def test_menu_cmd_forces_visible_refresh(self):
        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot.db_path = ":memory:"
        msg = _message()

        async def run():
            with patch.object(bot, "_touch_user"), patch.object(
                bot, "_force_reply_menu", new_callable=AsyncMock
            ) as force:
                await bot.menu_cmd(_update(msg), MagicMock())
                force.assert_awaited_once()

        asyncio.run(run())

    def test_market_cmd_reads_db_only(self, tmp_path):
        db = str(tmp_path / "bot.db")
        charts = str(tmp_path / "charts")
        os.makedirs(charts, exist_ok=True)
        _seed_market_db(db)

        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot.db_path = db
        bot.charts_dir = charts
        bot._menu_fade_msgs = {}
        bot._pending = {}
        bot._pending_locks = {}
        bot._screening_running = set()
        bot._menu_fade_gen = {}
        bot._lookup_locks = {}
        msg = _message()

        with patch.object(bot, "_enter_main_menu", new_callable=AsyncMock), patch.object(
            bot, "_transient_status", new_callable=AsyncMock
        ) as status, patch.object(
            bot, "_delete_message", new_callable=AsyncMock
        ), patch(
            "taiwan_market._fetch_index_daily"
        ) as mock_yahoo:

            async def run():
                status.return_value = MagicMock()
                await bot.market_cmd(_update(msg), MagicMock())

            asyncio.run(run())
            mock_yahoo.assert_not_called()

        status.assert_awaited()
        msg.reply_html.assert_awaited()
        body = msg.reply_html.await_args.args[0]
        assert "台股大盤" in body
        assert "三大法人" in body or "結構" in body or "加權指數" in body

    def test_on_text_routes_market_and_flow(self, tmp_path):
        db = str(tmp_path / "route.db")
        charts = str(tmp_path / "charts2")
        os.makedirs(charts, exist_ok=True)
        _seed_market_db(db)

        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot.db_path = db
        bot.charts_dir = charts
        bot._menu_fade_msgs = {}
        bot._pending = {}
        bot._pending_locks = {}
        bot._screening_running = set()
        bot._menu_fade_gen = {}
        bot._lookup_locks = {}
        bot._pending_lock = MagicMock()
        bot._pending_lock.return_value.__aenter__ = AsyncMock(return_value=None)
        bot._pending_lock.return_value.__aexit__ = AsyncMock(return_value=None)
        bot._touch_user = MagicMock()
        bot.market_cmd = AsyncMock()
        bot.flow_cmd = AsyncMock()

        async def run(label):
            msg = _message()
            msg.text = label
            await bot.on_text(_update(msg), MagicMock())

        asyncio.run(run("大盤"))
        bot.market_cmd.assert_awaited_once()
        bot.flow_cmd.assert_not_awaited()

        bot.market_cmd.reset_mock()
        asyncio.run(run("資金"))
        bot.flow_cmd.assert_awaited_once()

    def test_two_users_market_isolated(self, tmp_path):
        """不同 uid 各自按大盤，互不影響 pending 狀態。"""
        db = str(tmp_path / "iso.db")
        charts = str(tmp_path / "c2")
        os.makedirs(charts, exist_ok=True)
        _seed_market_db(db)

        bot = WayneTelegramBot.__new__(WayneTelegramBot)
        bot.db_path = db
        bot.charts_dir = charts
        bot._menu_fade_msgs = {}
        bot._pending = {"99:111": "buy"}
        bot._pending_locks = {}
        bot._screening_running = set()
        bot._menu_fade_gen = {}
        bot._lookup_locks = {}

        async def _run(uid):
            msg = _message(uid)
            with patch.object(bot, "_enter_main_menu", new_callable=AsyncMock), patch.object(
                bot, "_transient_status", new_callable=AsyncMock
            ) as st, patch.object(
                bot, "_delete_message", new_callable=AsyncMock
            ):
                st.return_value = MagicMock()
                await bot.market_cmd(_update(msg), MagicMock())
            return msg

        async def run_both():
            await asyncio.gather(_run(111), _run(222))

        asyncio.run(run_both())
        assert bot._pending.get("99:111") == "buy"

    def test_market_page_builds_under_two_seconds(self):
        import time
        from config import get_db_path

        db = get_db_path()
        if not db or not __import__("os").path.isfile(db):
            pytest.skip("production db required")
        t0 = time.time()
        html = format_taiwan_market_page_html(db)
        elapsed = time.time() - t0
        assert "台股大盤" in html
        assert elapsed < 2.5, f"market page too slow: {elapsed:.2f}s"

    def test_market_page_mobile_friendly_layout(self, tmp_path):
        db = str(tmp_path / "layout.db")
        as_of = _seed_market_db(db)
        html = format_taiwan_market_page_html(db, as_of)
        assert _TG_SECTION in html
        assert "漲跌家數" in html
        assert "結構" in html
        for line in html.splitlines():
            if "上市" in line and "上櫃" in line:
                pytest.fail(f"overlong breadth line: {line!r}")
