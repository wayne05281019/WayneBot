# -*- coding: utf-8 -*-
"""話筒步驟落盤：重開後按人接續，互不洗。"""
import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tg_pending import (
    BiaokeHistMap,
    PendingMap,
    TTL_HOURS,
    clear_actor_pending,
    load_actor_pending,
    save_actor_pending,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_pending_survives_new_bot_memory():
    db = _db()
    try:
        a = PendingMap(db)
        h = BiaokeHistMap(db, a)
        a._hist = h
        a["100:1"] = "fbuy:days:foreign:ALL"
        h["100:1"] = [{"ask": "2330", "answer": "材料…"}]
        # 模擬 Render 重開：新記憶體
        a2 = PendingMap(db)
        h2 = BiaokeHistMap(db, a2)
        a2._hist = h2
        assert a2.get("100:1") == "fbuy:days:foreign:ALL"
        assert h2.get("100:1")[0]["ask"] == "2330"
    finally:
        os.unlink(db)


def test_dual_actors_isolated():
    db = _db()
    try:
        p = PendingMap(db)
        p["1:wayne"] = "dongzhu"
        p["1:bro"] = "biaoke:chat"
        assert p.get("1:wayne") == "dongzhu"
        assert p.get("1:bro") == "biaoke:chat"
        p.pop("1:wayne")
        assert p.get("1:wayne") is None
        assert load_actor_pending(db, "1:bro")[0] == "biaoke:chat"
    finally:
        os.unlink(db)


def test_clear_removes_row():
    db = _db()
    try:
        save_actor_pending(db, "9:9", "sell", hist=[])
        clear_actor_pending(db, "9:9")
        assert load_actor_pending(db, "9:9") == ("", [])
    finally:
        os.unlink(db)


def test_expired_pending_ignored(monkeypatch):
    db = _db()
    try:
        save_actor_pending(db, "2:2", "report", hist=[])
        old = (datetime.now(TAIPEI) - timedelta(hours=TTL_HOURS + 2)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE tg_actor_pending SET updated_at=? WHERE actor_key=?",
            (old, "2:2"),
        )
        conn.commit()
        conn.close()
        assert load_actor_pending(db, "2:2") == ("", [])
    finally:
        os.unlink(db)


def test_private_tables_include_pending():
    from wayne_db import PRIVATE_USER_TABLES

    assert "tg_actor_pending" in PRIVATE_USER_TABLES


def test_bot_init_uses_pending_maps():
    from bot_servers import WayneTelegramBot
    from tg_pending import BiaokeHistMap, PendingMap

    db = _db()
    try:
        bot = WayneTelegramBot(token="x", chat_id="1", db_path=db)
        assert isinstance(bot._pending, PendingMap)
        assert isinstance(bot._biaoke_hist, BiaokeHistMap)
        bot._pending["1:1"] = "card"
        bot2 = WayneTelegramBot(token="x", chat_id="1", db_path=db)
        assert bot2._pending.get("1:1") == "card"
    finally:
        os.unlink(db)
