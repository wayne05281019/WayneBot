# -*- coding: utf-8 -*-
"""飆大未讀匣：重疊更新只留最新，按進去看一口重點。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from biaoke_digest import (
    biaoke_button_label,
    format_focus_oral,
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
    assert poll_wait_seconds(stop) == AFTER_EVERY_SEC


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
    assert "飆大現在在講" in html
    assert "散熱還在" in html
    assert "散熱最強" not in html
    assert "不是南亞科" in html
    assert "11:43" in html
    assert "不是買訊" not in html
    assert "今天飆大重點就是" not in html
    assert "官方加權盤中現價" not in html
    assert "程式標籤" not in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
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
    assert [b.text for b in kb.keyboard[0]][-3] == MENU_BTN_BIAOKE
    assert [b.text for b in kb.keyboard[0]][-2] == "大盤"
    assert [b.text for b in kb.keyboard[0]][-1] == "資金"


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
    assert [b.text for b in kb.keyboard[0]][-3] == "飆大 2"
    assert [b.text for b in kb.keyboard[0]][-2] == "大盤"
    assert [b.text for b in kb.keyboard[0]][-1] == "資金"


def test_focus_oral_sep18_not_timestamp_wall():
    mains = [
        {
            "id": "m918",
            "date": "2026-09-18",
            "time": "08:58",
            "text": (
                "1. 從夜盤反彈到47205，這次C波下殺已經沒了。不過這次大盤要漲到目標點位"
                "一定要過前波高點47578，否則大盤頭部型態已經初步出現，未來不是再一次"
                "出現這一次大修正，或者走2024/10~2025/02 做一個大的頭部型態出來。"
                " 2. 目前唯一在多頭格局的族群就是ASIC，再來是散熱，再次之就是光通訊、記憶體，依照強弱排序。"
                " 3. 有一個新族群目前在底部蠢蠢欲動，因為現在追蹤我的人數過多，我已經無法像以前那樣公開點名。"
            ),
        },
        {
            "id": "m917",
            "date": "2026-09-17",
            "time": "10:42",
            "text": "1. 台光電至少要整理三個月 ，和 ABF一樣 。 2. PCB全面走弱 ，建議全面減碼。",
        },
    ]
    replies = [
        {
            "id": "r1",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "22:44",
            "text": "PCB整理時間會比ABF短很多，昨天錯殺成分居多，應該是下波會漲主流族群",
        },
        {
            "id": "r2",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "22:40",
            "text": "我這周末比較忙，星期日晚上我發一篇對台光電、金像電、台燿、富喬、金居 的技術分析看法。",
        },
        {
            "id": "r3",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "19:26",
            "text": "很有心 我很多都是看盤當下寫的，我自己都沒有備份，而且說實話，就算出書 也不可能寫這麼細。",
        },
        {
            "id": "r4",
            "kind": "reply",
            "date": "2026-09-18",
            "time": "16:20",
            "text": "全新 打錯",
        },
        {
            "id": "r5",
            "kind": "reply",
            "date": "2026-09-16",
            "time": "09:21",
            "text": "大盤今天觀察只要收盤不破3日低點45398代表C-5低點確認",
        },
    ]
    html = format_focus_oral(
        mains,
        replies,
        now=datetime(2026, 9, 20, 11, 35, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert html.startswith("<b>飆大現在在講</b>")
    assert "9/18 晚上 22:44" in html
    assert "47578" in html
    assert "如果句" in html
    assert "ASIC" in html
    assert "比 ABF 短" in html or "比ABF短" in html
    assert "整理三個月" in html
    assert "星期日晚上" in html or "星期天晚上" in html
    assert "11:35" in html
    assert "不是買訊" not in html
    assert "還能問" in html
    assert "47578過了沒" in html
    board_html = html.split("<b>族群</b>")[0] if "<b>族群</b>" in html else html
    assert "47205" in board_html
    assert "47578" in board_html
    assert "頭部型態" in board_html
    assert "如果句" in board_html
    assert "一定要過" in board_html
    assert "2024年10月" in board_html or "2024/10" in board_html
    assert "樓下 2026-09-18" not in html
    assert "2026-09-17" not in html
    assert "2026-09-16" not in html
    assert "C-5低點確認" not in html
    assert "出書" not in html
    assert "打錯" not in html
    assert "你可能會問" not in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
    assert "庫 " not in html
    assert html.count("9/17") == 0
    assert html.count("9/16") == 0
    assert len(html) < 1800


def test_latest_focus_is_oral_not_july_bwave():
    html = format_latest_focus("")
    assert "飆大現在在講" in html
    assert "不是買訊" not in html
    assert "直接打字或語音" in html
    assert "這句沒點檔" not in html
    assert "現在位階" not in html
    assert "位階不講死" not in html
    assert "庫 " not in html
    assert "你可能會問" not in html
    assert "今天飆大重點就是" not in html
    assert "樓下 2026-" not in html
    assert "模糊的精確" not in html
    assert "安全邊際" not in html
    assert "和碩" not in html
    assert "仁寶" not in html
    assert "新發：" not in html
    assert "45000" not in html
    assert "46000" not in html
    assert "語料" not in html
    assert "量先價行" not in html
    assert len(html) < 1800


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
    assert "17:49" in html
    assert "樓下 2026-09-11" not in html
    assert "飆大現在在講" in html
