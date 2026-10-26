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
        force=True,
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
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del, force=True
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
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del, force=True
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
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del, force=True
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
        force=True,
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


def test_purge_defers_during_busy_window(tmp_path, monkeypatch):
    """重活進行中整輪略過：不准跟早報／融合／DC 搶 API 弄崩話筒。"""
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("111", 1, db_path=db, sent_at=now - 40 * 3600)
    monkeypatch.setattr(ttl, "_heavy_window_active", lambda db_path="": True)
    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append(int(message_id))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db, token="tok", now=now, sleep_sec=0.01, delete_fn=_del
    )
    assert stats["deferred"] == 1
    assert stats["deleted"] == 0
    assert deleted == []
    # force 單測仍可刪
    stats2 = ttl.purge_expired(
        db_path=db,
        token="tok",
        now=now,
        sleep_sec=0.01,
        delete_fn=_del,
        force=True,
    )
    assert stats2["deleted"] == 1


def test_purge_source_does_not_touch_schedulers():
    src = Path(ttl.__file__).read_text(encoding="utf-8")
    assert "run_scheduled_job" not in src
    assert "start_daily_scheduler" not in src
    assert "wayne_market.db" not in src or "get_db_path" in src
    assert "DELETE FROM daily_quotes" not in src
    assert "strip_private_user_data" not in src
    # 雙人 pending／持股本不准碰
    assert "tg_actor_pending" not in src
    assert "user_holdings" not in src
    assert "user_watchlist" not in src
    assert "save_actor_pending" not in src


def test_clock_windows_cover_morning_midday_fuse_dc_midnight():
    """早報／12:45 海選／融合／DC／午夜 disk_guard 鐘點都要略過。"""
    assert ttl._mins_in_heavy_window(6 * 60 + 30) is True
    assert ttl._mins_in_heavy_window(12 * 60 + 45) is True
    assert ttl._mins_in_heavy_window(16 * 60 + 30) is True
    assert ttl._mins_in_heavy_window(3 * 60 + 30) is True
    assert ttl._mins_in_heavy_window(0) is True
    assert ttl._mins_in_heavy_window(23 * 60 + 58) is True
    # 平常時段可清
    assert ttl._mins_in_heavy_window(10 * 60) is False
    assert ttl._mins_in_heavy_window(14 * 60) is False
    assert ttl._heavy_window_active(now_mins=6 * 60 + 30) is True
    assert ttl._heavy_window_active(now_mins=10 * 60) is False


def test_busy_message_pair_skipped_even_with_force(tmp_path, monkeypatch):
    """busy_window 進行中的那則，force 也不准誤刪。"""
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("111", 1, db_path=db, sent_at=now - 40 * 3600)
    ttl.record_outbound("111", 2, db_path=db, sent_at=now - 40 * 3600)
    monkeypatch.setattr(
        ttl, "_protected_pairs", lambda db_path="": {("111", 1)}
    )
    deleted = []

    def _del(token, chat_id, message_id):
        deleted.append(int(message_id))
        return {"ok": True}

    stats = ttl.purge_expired(
        db_path=db,
        token="tok",
        now=now,
        sleep_sec=0.01,
        delete_fn=_del,
        force=True,
    )
    assert 1 not in deleted
    assert 2 in deleted
    assert stats["deleted"] == 1


def test_record_fail_soft_never_raises(tmp_path, monkeypatch):
    """落檔失敗不准噴到查股／推播主路徑。"""
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()

    def _boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(ttl, "ensure_table", lambda db_path="": str(tmp_path / "x.db"))
    monkeypatch.setattr(sqlite3, "connect", _boom)
    assert ttl.record_outbound("1", 9, db_path=str(tmp_path / "x.db")) is False


def test_purge_exception_in_delete_fn_counts_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_TG_MSG_TTL_TEST", "1")
    ttl.reset_for_tests()
    db = _db(tmp_path)
    now = time.time()
    ttl.record_outbound("1", 3, db_path=db, sent_at=now - 40 * 3600)

    def _boom(token, chat_id, message_id):
        raise RuntimeError("network down")

    stats = ttl.purge_expired(
        db_path=db,
        token="tok",
        now=now,
        sleep_sec=0.01,
        delete_fn=_boom,
        force=True,
    )
    assert stats["failed"] == 1
    assert stats["deleted"] == 0


def test_wiring_does_not_rewrite_core_feature_modules():
    """TTL 只附加 hook／落檔；不准改寫排程／海選／查股／disk_guard 本體邏輯。"""
    # disk_guard 本體無 deleteMessage（已測）；排程／pending 模組無 TTL 反向依賴
    for mod_name in ("main_runner", "disk_guard", "tg_pending", "screening_engine"):
        src = Path(__import__(mod_name).__file__).read_text(encoding="utf-8")
        if mod_name == "main_runner":
            # runner 只准附加 record，不准 purge 擋主路徑
            assert "purge_expired" not in src
            assert "record_from_api_result" in src
        else:
            assert "tg_message_ttl" not in src
            assert "purge_expired" not in src
