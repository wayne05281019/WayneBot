# -*- coding: utf-8 -*-
"""飆大未讀匣：重疊更新只留最新，按進去看一口重點。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_digest import (
    biaoke_button_label,
    format_latest_focus,
    format_unread_digest,
    mark_biaoke_read,
    normalize_biaoke_button,
    record_ingest_events,
    take_unread_digest,
    unread_count,
)
from biaoke_ingest import AFTER_EVERY_SEC, poll_wait_seconds
from bot_servers import MENU_BTN_BIAOKE, WayneTelegramBot, _normalize_menu_text


def test_poll_wait_until_three():
    tz = ZoneInfo("Asia/Taipei")
    still = datetime(2026, 9, 10, 2, 50, tzinfo=tz)
    assert poll_wait_seconds(still) == AFTER_EVERY_SEC
    stop = datetime(2026, 9, 10, 3, 0, tzinfo=tz)
    assert poll_wait_seconds(stop) == 6 * 60 * 60


def test_unread_dedupes_same_post_and_splits_users(tmp_path):
    db = str(tmp_path / "w.db")
    wayne, bro = "9001", "9002"
    record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"}],
        now=datetime(2026, 9, 11, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "10:20", "text": "散熱還在、記憶體先看量"}],
        now=datetime(2026, 9, 11, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    record_ingest_events(
        db,
        [{"post_id": "1:r1", "kind": "reply", "time": "10:24", "text": "但絕對不是南亞科"}],
        now=datetime(2026, 9, 11, 11, 5, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert unread_count(wayne, db) == 2
    assert unread_count(bro, db) == 2
    html = take_unread_digest(wayne, db, now=datetime(2026, 9, 11, 11, 43, tzinfo=ZoneInfo("Asia/Taipei")))
    assert html.startswith("今天飆大重點就是")
    assert "散熱還在" in html
    assert "散熱最強" not in html
    assert "不是南亞科" in html
    assert "更新至 11:43" in html
    mark_biaoke_read(wayne, db, now=datetime(2026, 9, 11, 11, 44, tzinfo=ZoneInfo("Asia/Taipei")))
    assert unread_count(wayne, db) == 0
    assert unread_count(bro, db) == 2
    assert biaoke_button_label(wayne, db) == "飆大"
    assert biaoke_button_label(bro, db) == "飆大 2"


def test_button_face_and_normalize():
    assert normalize_biaoke_button("飆大") == "飆大"
    assert normalize_biaoke_button("飆大 3") == "飆大"
    assert normalize_biaoke_button("飆大 12") == "飆大"
    assert _normalize_menu_text("飆大 3") == "飆大"
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert [b.text for b in kb.keyboard[0]][-1] == MENU_BTN_BIAOKE


def test_format_digest_empty():
    assert format_unread_digest([]) == ""


def test_unchanged_repost_does_not_revive_unread(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    tz = ZoneInfo("Asia/Taipei")
    row = {"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"}
    record_ingest_events(db, [row], now=datetime(2026, 9, 11, 10, 0, tzinfo=tz))
    mark_biaoke_read(uid, db, now=datetime(2026, 9, 11, 10, 5, tzinfo=tz))
    assert unread_count(uid, db) == 0
    n = record_ingest_events(db, [row], now=datetime(2026, 9, 11, 13, 0, tzinfo=tz))
    assert n == 0
    assert unread_count(uid, db) == 0
    n = record_ingest_events(
        db,
        [{"post_id": "1", "kind": "post", "time": "13:10", "text": "散熱還在、記憶體先看量"}],
        now=datetime(2026, 9, 11, 13, 10, tzinfo=tz),
    )
    assert n == 1
    assert unread_count(uid, db) == 1


def test_reply_menu_badge_uses_unread_count(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    record_ingest_events(
        db,
        [
            {"post_id": "1", "kind": "post", "time": "09:51", "text": "散熱最強"},
            {"post_id": "2", "kind": "post", "time": "10:01", "text": "記憶體看量"},
        ],
        now=datetime(2026, 9, 11, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    kb = bot._reply_menu(uid)
    assert [b.text for b in kb.keyboard[0]][-1] == "飆大 2"


def test_latest_focus_is_sep11_not_july_bwave():
    html = format_latest_focus("")
    assert html.startswith("飆大最新公開文")
    assert "2026-09-11" in html
    assert "17:49" in html
    assert "46506" in html
    assert "45839" in html
    assert "08:43" in html
    assert "45000" not in html
    assert "46000" not in html
    assert "今天飆大重點就是" not in html
    assert "語料" not in html


def test_old_inbox_not_counted_as_unread(tmp_path):
    db = str(tmp_path / "w.db")
    uid = "9001"
    tz = ZoneInfo("Asia/Taipei")
    record_ingest_events(
        db,
        [
            {
                "post_id": "181149602",
                "kind": "post",
                "date": "2026-07-30",
                "time": "09:55",
                "text": "就算大盤今天開始正式開始走大B波反彈，反彈目標45000~46000",
            }
        ],
        now=datetime(2026, 9, 11, 22, 0, tzinfo=tz),
    )
    assert unread_count(uid, db) == 0
    record_ingest_events(
        db,
        [
            {
                "post_id": "184545002",
                "kind": "post",
                "date": "2026-09-11",
                "time": "17:49",
                "text": "今晚夜盤至少要穿越46506",
            }
        ],
        now=datetime(2026, 9, 11, 22, 1, tzinfo=tz),
    )
    html = take_unread_digest(uid, db, now=datetime(2026, 9, 11, 22, 3, tzinfo=tz))
    assert "46506" in html
    assert "45000" not in html
    assert "2026-09-11 17:49" in html
