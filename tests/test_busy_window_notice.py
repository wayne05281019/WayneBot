"""重活窗話筒提示：推兩人＋依 message_id 魔法刪（不改買訊）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import busy_window_notice as bwn


def test_busy_text_is_short_locked_copy():
    assert bwn.BUSY_TEXT == "資料處理中，請稍後再用"
    assert "morning" in bwn.KINDS
    assert "fuse" in bwn.KINDS
    assert "dc_sf" in bwn.KINDS


def test_start_finish_stores_per_chat_and_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "222")
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")

    calls = []

    def _fake_api(token, method, payload):
        calls.append((method, dict(payload)))
        if method == "sendMessage":
            cid = str(payload["chat_id"])
            mid = 1000 + int(cid)
            return {"ok": True, "result": {"message_id": mid}}
        if method == "deleteMessage":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    # 清掉其他測試殘留；鎖在早報窗內，避免現在鐘點觸發 stale 自清
    bwn._active.clear()
    monkeypatch.setattr(bwn, "_taipei_hhmm", lambda: 640)

    sent = bwn.start_busy_notice("morning", db_path=db, token="tok-test")
    assert sent == {"111": 1111, "222": 1222}
    assert bwn.is_busy_window_active(db_path=db) is True
    state = json.loads((tmp_path / "busy_window_notice.json").read_text(encoding="utf-8"))
    assert state["kind"] == "morning"
    assert state["messages"]["111"] == 1111
    assert state["messages"]["222"] == 1222

    stats = bwn.finish_busy_notice("morning", db_path=db, token="tok-test")
    assert stats["deleted"] == 2
    assert stats["failed"] == 0
    assert bwn.is_busy_window_active(db_path=db) is False
    assert not (tmp_path / "busy_window_notice.json").exists()

    deletes = [c for c in calls if c[0] == "deleteMessage"]
    assert {d[1]["chat_id"] for d in deletes} == {"111", "222"}
    assert {d[1]["message_id"] for d in deletes} == {1111, 1222}


def test_delete_failure_edits_then_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()

    seq = {"n": 0}

    def _fake_api(token, method, payload):
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 55}}
        if method == "deleteMessage":
            seq["n"] += 1
            if seq["n"] == 1:
                return {"ok": False, "description": "can't delete"}
            return {"ok": True}
        if method == "editMessageText":
            assert payload["text"] == bwn._EDIT_FALLBACK
            assert payload["message_id"] == 55
            return {"ok": True}
        return {}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    bwn.start_busy_notice("fuse", db_path=db, token="t")
    stats = bwn.finish_busy_notice("fuse", db_path=db, token="t")
    assert stats["deleted"] == 1
    assert seq["n"] == 2


def test_context_manager_finishes_on_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()
    finished = {"n": 0}

    def _fake_api(token, method, payload):
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 9}}
        if method == "deleteMessage":
            finished["n"] += 1
            return {"ok": True}
        return {}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    try:
        with bwn.busy_window("dc_sf", db_path=db, token="t"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert finished["n"] == 1
    assert bwn.is_busy_window_active(db_path=db) is False


def test_gha_notify_off_skips_push(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "0")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()
    spy = MagicMock(return_value={"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(bwn, "_tg_api", spy)
    assert bwn.start_busy_notice("morning", db_path=db, token="t") == {}
    spy.assert_not_called()


def test_wiring_in_heavy_jobs():
    import inspect

    import dc_scenario_silent_verify as dc
    import main_runner as mr
    from bot_servers import WayneTelegramBot

    morning_src = inspect.getsource(mr.MainRunner.run_morning_screen)
    closed_src = inspect.getsource(mr.MainRunner._run_closed_day_morning_digest)
    fuse_src = inspect.getsource(mr.MainRunner.run_increment_job)
    dc_src = inspect.getsource(dc.night_tick)
    phone_src = inspect.getsource(WayneTelegramBot._on_text_bound)

    assert "busy_window" in morning_src and '"morning"' in morning_src
    assert 'busy_window("morning"' in closed_src
    assert 'busy_window("fuse"' in fuse_src
    assert 'start_busy_notice("dc_sf"' in dc_src
    assert 'finish_busy_notice("dc_sf"' in dc_src
    assert "_heavy_job_blocks_phone" in phone_src
    assert "PHONE_HEAVY_JOB" in phone_src


def test_phone_allows_menu_during_heavy():
    from bot_servers import WayneTelegramBot

    assert WayneTelegramBot._phone_allowed_during_heavy_job("開始") is True
    assert WayneTelegramBot._phone_allowed_during_heavy_job("選單") is True
    assert WayneTelegramBot._phone_allowed_during_heavy_job("備份") is True
    assert WayneTelegramBot._phone_allowed_during_heavy_job("海選") is False
    assert WayneTelegramBot._phone_allowed_during_heavy_job("2330") is False


def test_stale_outside_hold_window_reclaims_and_unblocks(tmp_path, monkeypatch):
    """19:xx 補跑留下的 fuse JSON 必須清掉，不准再擋查股。"""
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "222")
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()

    deletes = []

    def _fake_api(token, method, payload):
        if method == "sendMessage":
            cid = str(payload["chat_id"])
            return {"ok": True, "result": {"message_id": 1000 + int(cid)}}
        if method == "deleteMessage":
            deletes.append((payload["chat_id"], payload["message_id"]))
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    # 假裝還在融合窗內推播
    monkeypatch.setattr(bwn, "_taipei_hhmm", lambda: 1630)
    sent = bwn.start_busy_notice("fuse", db_path=db, token="t")
    assert sent
    assert bwn.is_busy_window_active(db_path=db, reclaim_stale=False) is True

    # 盤後 19:13：離窗 → stale → 查股閘放行
    reason = bwn.busy_notice_stale_reason(db_path=db, now_hhmm=1913)
    assert reason.startswith("outside_hold")
    stats = bwn.reclaim_stale_busy_notices(
        db_path=db, token="t", now_hhmm=1913, delete_messages=True
    )
    assert stats["reclaimed"] is True
    assert bwn.is_busy_window_active(db_path=db, reclaim_stale=False) is False
    assert not (tmp_path / "busy_window_notice.json").exists()
    assert len(deletes) >= 2


def test_stale_by_age_even_inside_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()

    def _fake_api(token, method, payload):
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 9}}
        if method == "deleteMessage":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    monkeypatch.setattr(bwn, "_taipei_hhmm", lambda: 1640)
    bwn.start_busy_notice("fuse", db_path=db, token="t")
    path = tmp_path / "busy_window_notice.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    # 開始於 50 分鐘前
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    started = datetime.now(ZoneInfo("Asia/Taipei")) - timedelta(minutes=50)
    state["started_at"] = started.isoformat(timespec="seconds")
    path.write_text(json.dumps(state), encoding="utf-8")

    reason = bwn.busy_notice_stale_reason(db_path=db, now_hhmm=1640)
    assert reason.startswith("age>")
    assert bwn.is_busy_window_active(db_path=db, reclaim_stale=True) is False
    assert not path.exists()


def test_is_busy_active_auto_reclaims_outside_window(tmp_path, monkeypatch):
    """話筒路徑：is_busy_window_active 預設自動清殘閘。"""
    monkeypatch.setenv("WAYNE_BUSY_NOTICE_TEST", "1")
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    db = str(tmp_path / "w.db")
    Path(db).write_text("", encoding="utf-8")
    bwn._active.clear()

    def _fake_api(token, method, payload):
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 42}}
        if method == "deleteMessage":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(bwn, "_tg_api", _fake_api)
    monkeypatch.setattr(bwn, "_taipei_hhmm", lambda: 1910)
    # 直接寫殘檔（模擬 19:07 補跑 push 後卡住）
    path = tmp_path / "busy_window_notice.json"
    path.write_text(
        json.dumps(
            {
                "kind": "fuse",
                "started_at": "2026-10-26T19:07:48+08:00",
                "messages": {"1": 42},
            }
        ),
        encoding="utf-8",
    )
    assert bwn.is_busy_window_active(db_path=db) is False
    assert not path.exists()


def test_boot_wiring_clears_busy_notices():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.run_polling)
    assert "clear_busy_notices" in src
    assert "reclaim_stale_busy_notices" in src


def test_health_wiring_throttled_reclaim():
    import pathlib

    main_src = pathlib.Path("main.py").read_text(encoding="utf-8")
    assert "reclaim_stale_busy_notices_throttled" in main_src
    assert "busy_gate" in main_src
