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
    # 清掉其他測試殘留
    bwn._active.clear()

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
