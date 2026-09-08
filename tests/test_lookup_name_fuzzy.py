# -*- coding: utf-8 -*-
"""查股：撞名列出、讀音／錯字建議、KY 後綴。不硬編只那幾檔。"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from lookup_fuzzy import (
    FUZZY_MIN_SCORE,
    hits_need_picker,
    lookup_picker_lead,
    name_match_score,
    strip_lookup_name,
)
from wayne_db import ensure_core_schema, lookup_stocks


def test_strip_ky_suffix_variants():
    assert strip_lookup_name("譜瑞-KY") == "譜瑞"
    assert strip_lookup_name("譜瑞KY") == "譜瑞"
    assert strip_lookup_name("譜瑞 KY") == "譜瑞"
    assert strip_lookup_name("萊德光電-KY") == "萊德光電"


def test_score_wrong_chars_and_ky_are_generic():
    """例子只是驗收；規則是讀音／近似，不是點名單。"""
    assert name_match_score("影威", "穎崴") >= FUZZY_MIN_SCORE
    assert name_match_score("普瑞", "譜瑞-KY") >= FUZZY_MIN_SCORE
    assert name_match_score("普瑞KY", "譜瑞-KY") >= FUZZY_MIN_SCORE
    assert name_match_score("旺夕", "旺矽") >= FUZZY_MIN_SCORE
    assert name_match_score("台廣", "台光電") >= FUZZY_MIN_SCORE
    assert name_match_score("抬棺", "台光電") >= FUZZY_MIN_SCORE
    assert name_match_score("唐光電", "台光電") >= FUZZY_MIN_SCORE
    assert name_match_score("奈創", "錼創科技-KY") >= FUZZY_MIN_SCORE
    assert name_match_score("台积电", "台積電") >= FUZZY_MIN_SCORE
    assert name_match_score("台廣", "台塑") < FUZZY_MIN_SCORE
    assert name_match_score("南亞", "南亞科") >= 90


def test_picker_rules():
    assert hits_need_picker([]) is False
    assert hits_need_picker([{"stock_id": "2330", "fuzzy": False}]) is False
    assert hits_need_picker(
        [
            {"stock_id": "1303", "stock_name": "南亞", "fuzzy": False},
            {"stock_id": "2408", "stock_name": "南亞科", "fuzzy": False},
        ]
    )
    assert hits_need_picker([{"stock_id": "6515", "stock_name": "穎崴", "fuzzy": True}])
    assert "沒打準" in lookup_picker_lead([{"fuzzy": True, "stock_name": "穎崴"}])
    assert "名稱相近" in lookup_picker_lead(
        [{"fuzzy": False, "stock_name": "南亞"}, {"fuzzy": False, "stock_name": "南亞科"}]
    )


def _seed(db: str, monkeypatch) -> None:
    monkeypatch.setattr("universe.fetch_isin_universe", lambda: [])
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    rows = [
        ("1303", "南亞", 55.0, 8000),
        ("2408", "南亞科", 90.0, 5000),
        ("2383", "台光電", 5295.0, 3000),
        ("1301", "台塑", 40.0, 4000),
        ("2330", "台積電", 2410.0, 20000),
        ("6237", "旺矽", 180.0, 1200),
        ("6515", "穎崴", 220.0, 800),
        ("4966", "譜瑞-KY", 1200.0, 900),
        ("6854", "錼創科技-KY", 80.0, 400),
        ("2421", "建準", 70.0, 2000),
        ("3322", "建舜電", 50.0, 1100),
        ("4561", "健椿", 30.0, 900),
    ]
    for sid, name, close, vol in rows:
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260828', ?, ?, 'TW', ?, ?, ?, ?, ?, 1000, 1.0, ?)""",
            (sid, name, close, close, close, close, vol, close),
        )
    conn.commit()
    conn.close()


def test_lookup_nanya_lists_both(monkeypatch, tmp_path):
    db = str(tmp_path / "nanya.db")
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    hits = lookup_stocks(db, "南亞")
    ids = [h["stock_id"] for h in hits]
    assert "1303" in ids
    assert "2408" in ids
    assert all(not h.get("fuzzy") for h in hits)
    assert hits_need_picker(hits)
    assert hits[0]["stock_id"] == "1303"


def test_lookup_typos_suggest_and_skip_unrelated(monkeypatch, tmp_path):
    db = str(tmp_path / "typo.db")
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    cases = {
        "台廣": "2383",
        "抬棺": "2383",
        "唐光電": "2383",
        "影威": "6515",
        "普瑞": "4966",
        "普瑞KY": "4966",
        "旺夕": "6237",
        "奈創": "6854",
    }
    for q, sid in cases.items():
        hits = lookup_stocks(db, q)
        ids = [h["stock_id"] for h in hits]
        assert sid in ids, (q, ids)
        assert hits_need_picker(hits), q
        hit = next(h for h in hits if h["stock_id"] == sid)
        assert hit.get("fuzzy") is True, q
    plast = lookup_stocks(db, "台廣")
    assert "1301" not in [h["stock_id"] for h in plast]


def test_lookup_exact_name_and_ticker_not_fuzzy(monkeypatch, tmp_path):
    db = str(tmp_path / "exact.db")
    _seed(db, monkeypatch)
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    one = lookup_stocks(db, "台積電")
    assert len(one) == 1
    assert one[0]["stock_id"] == "2330"
    assert not one[0].get("fuzzy")
    assert not hits_need_picker(one)
    tick = lookup_stocks(db, "2383")
    assert len(tick) == 1
    assert tick[0]["stock_id"] == "2383"
    assert not tick[0].get("fuzzy")
    wang = lookup_stocks(db, "旺矽")
    assert len(wang) == 1
    assert wang[0]["stock_id"] == "6237"
    assert not wang[0].get("fuzzy")
    jian = lookup_stocks(db, "建準")
    assert [h["stock_id"] for h in jian] == ["2421"]
    assert not jian[0].get("fuzzy")
    assert not hits_need_picker(jian)


def test_lookup_merges_substring_and_homophone(monkeypatch, tmp_path):
    """字形子字串（普瑞森）不要蓋掉讀音命中的譜瑞-KY。"""
    db = str(tmp_path / "merge.db")
    _seed(db, monkeypatch)
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT OR REPLACE INTO daily_quotes
           (date, stock_id, stock_name, market, open, high, low, close, volume,
            turnover_k, pct_change, avg_price)
           VALUES ('20260828', '6847', '普瑞森', 'TW', 10, 10, 10, 10, 100, 1000, 1.0, 10)"""
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date",
        lambda dp, now=None: "20260828",
    )
    hits = lookup_stocks(db, "普瑞")
    ids = [h["stock_id"] for h in hits]
    assert "4966" in ids
    assert "6847" in ids
    assert hits_need_picker(hits)
    assert any(h["stock_id"] == "4966" and h.get("fuzzy") for h in hits)


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


def test_bot_nanya_picker_does_not_open_card():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(3, 3, "南亞")
    hits = [
        {"stock_id": "1303", "stock_name": "南亞", "fuzzy": False},
        {"stock_id": "2408", "stock_name": "南亞科", "fuzzy": False},
    ]

    async def run():
        with patch("bot_servers.lookup_stocks", return_value=hits):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._reply_card.assert_not_awaited()
    html = msg.reply_html.await_args[0][0]
    assert "南亞" in html
    assert "南亞科" in html
    assert "名稱相近" in html


def test_bot_fuzzy_one_hit_still_asks():
    bot = _bot()
    bot._reply_card = AsyncMock()
    msg = _msg(3, 3, "影威")
    hits = [{"stock_id": "6515", "stock_name": "穎崴", "fuzzy": True}]

    async def run():
        with patch("bot_servers.lookup_stocks", return_value=hits):
            await bot.on_text(_update(msg), MagicMock())

    asyncio.run(run())
    bot._reply_card.assert_not_awaited()
    html = msg.reply_html.await_args[0][0]
    assert "沒打準" in html
    assert "穎崴" in html
