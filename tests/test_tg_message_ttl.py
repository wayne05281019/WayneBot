"""Telegram 顯示 24h：只刪 Bot 自己寄出的 message_id；LOADING／busy 不誤刪。"""

from __future__ import annotations

import inspect
import sqlite3
import time
from pathlib import Path

import tg_message_ttl as ttl


def _db(tmp_path) -> str:
    path = str(tmp_path / "ttl.db")
    Path(path).write_text("", encoding="utf-8")
    ttl.ensure_table(path)
    return path


def test_record_and_purge_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    monkeypatch.setenv("WAYNE_TG_MSG_TTL", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    assert ttl.record_outbound("111", 10, db_path=db, kind="t", sent_at=now - 25 * 3600)
    assert ttl.record_outbound("111", 11, db_path=db, kind="t", sent_at=now - 60)
    assert ttl.record_outbound("222", 20, db_path=db, kind="t", sent_at=now - 30 * 3600)

    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append((str(chat_id), int(message_id)))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db,
        token="tok",
        now=now,
        max_per_run=10,
        sleep_sec=0.01,
        delete_fn=_del,
    )
    assert stats["deleted"] == 2
    assert set(deleted) == {("111", 10), ("222", 20)}
    # 未滿 24h 留著
    conn = sqlite3.connect(db)
    left = conn.execute(
        "SELECT chat_id, message_id FROM tg_bot_outbound ORDER BY message_id"
    ).fetchall()
    conn.close()
    assert left == [("111", 11)]


def test_protect_loading_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("111", 7, db_path=db, protect=True, kind="loading", sent_at=now - 48 * 3600)
    ttl.record_outbound("111", 8, db_path=db, kind="ok", sent_at=now - 48 * 3600)

    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append(int(message_id))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del
    )
    assert stats["deleted"] == 1
    assert deleted == [8]


def test_progress_orphan_blocks_purge(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("9001", 55, db_path=db, sent_at=now - 40 * 3600)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE tg_progress_orphans (
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (actor, kind)
        )
        """
    )
    conn.execute(
        "INSERT INTO tg_progress_orphans VALUES (?,?,?,?,?)",
        ("9001", "lookup", 9001, 55, "2026-10-25 00:00:00"),
    )
    conn.commit()
    conn.close()

    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append(int(message_id))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del
    )
    assert stats["deleted"] == 0
    assert deleted == []
    assert stats["scanned"] >= 0


def test_gone_error_forgets_row(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("111", 99, db_path=db, sent_at=now - 30 * 3600)

    def _del(token, chat_id, message_id):
        return {"ok": False, "error_code": 400, "description": "Bad Request: message to delete not found"}

    stats = ttl.purge_expired(
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del
    )
    assert stats["forgotten"] == 1
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM tg_bot_outbound").fetchone()[0]
    conn.close()
    assert n == 0


def test_throttle_max_per_run(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    for i in range(10):
        ttl.record_outbound("1", i + 1, db_path=db, sent_at=now - 40 * 3600)

    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append(int(message_id))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db,
        token="tok",
        now=now,
        max_per_run=3,
        sleep_sec=0.01,
        delete_fn=_del,
    )
    assert stats["deleted"] == 3
    assert len(deleted) == 3


def test_record_from_api_result_none():
    assert ttl.record_from_api_result(None) == 0


def test_record_from_api_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    n = ttl.record_from_api_result(
        {"ok": True, "result": {"message_id": 42, "chat": {"id": 777}}},
        db_path=db,
        kind="json",
    )
    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT chat_id, message_id FROM tg_bot_outbound"
    ).fetchone()
    conn.close()
    assert row == ("777", 42)


def test_pytest_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_TG_MSG_TTL_TEST", raising=False)
    monkeypatch.setenv("WAYNE_TG_MSG_TTL", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    # 在 pytest 內且未開 TEST 旗 → record 不寫
    assert ttl.record_outbound("1", 1, db_path=db) is False


def test_private_table_listed():
    from wayne_db import PRIVATE_USER_TABLES

    assert "tg_bot_outbound" in PRIVATE_USER_TABLES


def test_main_boots_ttl_guard():
    import main as main_mod

    src = inspect.getsource(main_mod.run_web)
    assert "start_message_ttl_guard" in src
    assert "tg_message_ttl" in src


def test_bot_servers_hooks_install_source():
    import bot_servers as bs

    src = inspect.getsource(bs.WayneTelegramBot.run_polling)
    assert "install_bot_hooks" in src
    assert "tg_message_ttl" in src


def test_disk_guard_untouched_by_ttl():
    """這條只管 Telegram 顯示；不准改 disk_guard 白名單／午夜邏輯。"""
    import disk_guard as dg

    assert dg.DEFAULT_CHART_TTL_SEC == 24 * 60 * 60
    assert "_lookup_memo" in dg.ALLOW_CHART_SUBDIRS
    src = Path(dg.__file__).read_text(encoding="utf-8")
    assert "tg_bot_outbound" not in src
    assert "deleteMessage" not in src
