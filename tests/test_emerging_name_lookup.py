# -*- coding: utf-8 -*-
"""興櫃查股：代號精確、名稱／簡稱、錯字模糊＋確認。與上市櫃同一套入口。"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from lookup_fuzzy import hits_need_picker, lookup_picker_lead, name_match_score
from wayne_db import ensure_core_schema, ensure_stock_directory, lookup_stocks


def _seed_emerging(db: str, monkeypatch) -> None:
    monkeypatch.setattr("universe.fetch_isin_universe", lambda: [])
    ensure_core_schema(db)
    from emerging_quotes import ensure_emerging_table

    ensure_emerging_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT NOT NULL,
            market_type TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            industry TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        );"""
    )
    # 上市櫃干擾項：讀音近似時不准蓋掉興櫃正選
    listed = [
        ("5438", "東友", "TWO", 17.0),
        ("4702", "中美實", "TWO", 9.0),
        ("4960", "誠美材", "TW", 22.0),
        ("2330", "台積電", "TW", 2400.0),
    ]
    for sid, name, mkt, close in listed:
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260828', ?, ?, ?, ?, ?, ?, ?, 1000, 1000, 1.0, ?)""",
            (sid, name, mkt, close, close, close, close, close),
        )
        conn.execute(
            """INSERT OR REPLACE INTO stock_universe
               (stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at)
               VALUES (?, ?, ?, 'STOCK', '', 1, 't')""",
            (sid, name, mkt),
        )
    emerging = [
        ("7942", "東佑達", 600.0),
        ("7853", "政美應用", 360.0),
        ("3595", "山太士", 1500.0),
    ]
    for sid, name, close in emerging:
        # 模擬英文 CSV 殘渣日＋漢字日
        conn.execute(
            """INSERT OR REPLACE INTO emerging_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260820', ?, ?, 'EM', ?, ?, ?, ?, 100, 100, 0, ?)""",
            (sid, sid, close, close, close, close, close),
        )
        conn.execute(
            """INSERT OR REPLACE INTO emerging_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260828', ?, ?, 'EM', ?, ?, ?, ?, 200, 200, 1.0, ?)""",
            (sid, name, close, close, close, close, close),
        )
        conn.execute(
            """INSERT OR REPLACE INTO stock_universe
               (stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at)
               VALUES (?, ?, 'EM', 'STOCK', '', 1, 't')""",
            (sid, name),
        )
    conn.commit()
    conn.close()
    ensure_stock_directory(db)


def test_emerging_ticker_and_full_name(monkeypatch, tmp_path):
    db = str(tmp_path / "em_tick.db")
    _seed_emerging(db, monkeypatch)
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    for q, sid, name in (
        ("7942", "7942", "東佑達"),
        ("東佑達", "7942", "東佑達"),
        ("7853", "7853", "政美應用"),
        ("政美應用", "7853", "政美應用"),
    ):
        hits = lookup_stocks(db, q)
        assert len(hits) == 1, q
        assert hits[0]["stock_id"] == sid
        assert hits[0]["stock_name"] == name
        assert hits[0].get("close") is not None
        assert not hits[0].get("fuzzy")
        assert not hits_need_picker(hits)


def test_emerging_partial_and_typo_need_confirm(monkeypatch, tmp_path):
    db = str(tmp_path / "em_fuzzy.db")
    _seed_emerging(db, monkeypatch)
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    assert name_match_score("正美", "政美應用") >= 90
    for q in ("政美", "政美應", "正美"):
        hits = lookup_stocks(db, q)
        ids = [h["stock_id"] for h in hits]
        assert "7853" in ids, (q, ids)
        assert hits_need_picker(hits), q
        hit = next(h for h in hits if h["stock_id"] == "7853")
        assert hit.get("fuzzy") or hit.get("partial"), q
        assert hit.get("close") is not None
    # 東佑達全名不准被上市櫃「東友」讀音搶走
    dong = lookup_stocks(db, "東佑達")
    assert [h["stock_id"] for h in dong] == ["7942"]
    assert not hits_need_picker(dong)


def test_directory_prefers_cjk_over_english_csv(monkeypatch, tmp_path):
    db = str(tmp_path / "em_cjk.db")
    _seed_emerging(db, monkeypatch)
    conn = sqlite3.connect(db)
    # 故意把目錄寫成英文殘渣
    conn.execute(
        "UPDATE stock_directory SET stock_name='TOYO' WHERE stock_id='7942'"
    )
    conn.commit()
    conn.close()
    ensure_stock_directory(db)
    conn = sqlite3.connect(db)
    name = conn.execute(
        "SELECT stock_name FROM stock_directory WHERE stock_id='7942'"
    ).fetchone()[0]
    conn.close()
    assert name == "東佑達"


def test_partial_picker_copy():
    assert hits_need_picker([{"stock_id": "7853", "partial": True}])
    assert "還不完整" in lookup_picker_lead(
        [{"stock_id": "7853", "stock_name": "政美應用", "partial": True}]
    )


def _msg(chat_id: int, uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=chat_id)
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._enter_main_menu = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    bot._keyboard = MagicMock(return_value=None)
    bot._dispatch_intent = AsyncMock(return_value=False)
    return bot


def test_bot_zhengmei_partial_asks_before_card():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(3, 3, "政美")
    hits = [
        {
            "stock_id": "7853",
            "stock_name": "政美應用",
            "fuzzy": False,
            "partial": True,
            "close": 360.0,
            "market": "EM",
        }
    ]

    async def run():
        with patch("bot_servers.lookup_stocks", return_value=hits):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._reply_card.assert_not_awaited()
    html = msg.reply_html.await_args[0][0]
    assert "政美應用" in html
    assert "還不完整" in html or "確認" in html
