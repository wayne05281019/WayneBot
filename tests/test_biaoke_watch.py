# -*- coding: utf-8 -*-
"""捕獲後同步想：看到什麼、為何這樣回、下一步盯什麼。"""
import sqlite3

from biaoke_watch import record_watch_events, think_spoken, latest_watch_line


def _seed_posts(db: str, rows) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE biaoke_posts (
            id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, parent TEXT,
            layer INTEGER, kind TEXT, tags TEXT, text TEXT, updated_at TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO biaoke_posts(id,date,time,kind,text) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_think_night_rebound_next_is_47548():
    got = think_spoken(
        "夜盤已經反彈超過0.75了，超過9成暫時化解C波下殺，"
        "如果要再有 C波除非大盤沒辦法過前高47548，也就是走複式abc才有可能"
    )
    assert "波浪" in got["five"]
    assert "形態" in got["five"]
    assert "47548" in got["nxt"]
    assert "未收" not in got["nxt"] or "如果" in got["seen"] or "夜盤" in got["seen"]
    assert "5／9" not in got["because"]


def test_think_pierce_is_keyk_and_next_effective():
    got = think_spoken(
        "台指期已經穿刺46747，達成第二階段，接下來看看是不是有效穿刺，"
        "並開始漲開細微波5波脈動推升，如果成功推升。就是1，不會有C-2轉C-3"
    )
    assert "關鍵K" in got["five"]
    assert "波浪" in got["five"]
    assert "有效" in got["nxt"]
    assert "發明" not in got["because"]


def test_skip_bystander_and_empty():
    assert think_spoken("") == {}
    n = record_watch_events(
        ":memory:",
        [{"id": "x", "kind": "bystander", "text": "路人問C波", "date": "2026-09-17"}],
    )
    assert n == 0


def test_record_and_latest_line(tmp_path):
    db = str(tmp_path / "w.db")
    n = record_watch_events(
        db,
        [
            {
                "id": "184750441:c1",
                "kind": "reply",
                "layer": 1,
                "date": "2026-09-17",
                "time": "09:47",
                "text": "夜盤已經反彈超過0.75了，如果要再有C波除非沒辦法過前高47548",
            }
        ],
    )
    assert n == 1
    line = latest_watch_line(db)
    assert "09:47" in line
    assert "47548" in line
    assert "不是買訊" in line
    assert "等待" in line or "如果" in line
    assert "下一步" not in line
    assert "不是沒想法" in line


def test_lookback_prefers_2025_plus_over_early_year(tmp_path):
    db = str(tmp_path / "w.db")
    _seed_posts(
        db,
        [
            ("old", "2024-03-01", "10:00", "post", "C波下殺先看45398"),
            ("late", "2026-09-16", "08:38", "post", "過不了前高47548才可能再走C波"),
        ],
    )
    record_watch_events(
        db,
        [
            {
                "id": "now",
                "kind": "reply",
                "layer": 1,
                "date": "2026-09-17",
                "time": "09:47",
                "text": "夜盤已經反彈超過0.75了，如果要再有C波除非沒辦法過前高47548",
            }
        ],
    )
    line = latest_watch_line(db)
    assert "後期" in line
    assert "2026-09-16" in line
    assert "早年方法" not in line
    assert "47548" in line


def test_easing_c_is_revision_wait_not_new_price():
    got = think_spoken(
        "夜盤已經反彈超過0.75了，超過9成暫時化解C波下殺，"
        "如果要再有 C波除非大盤沒辦法過前高47548",
        prior="後期 2026-09-16 08:38 先想到：過不了前高47548才可能再走C波",
    )
    assert "改口" in got["because"]
    assert "47548" in got["nxt"]
    assert "不下判" in got["nxt"]
    assert "46800" not in got["nxt"]
    assert "5／9" not in got["because"]
    assert "發明" not in got["because"]


def test_silence_and_crash_tape_vs_official_close(tmp_path):
    db = str(tmp_path / "w.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE index_daily (date TEXT, symbol TEXT, close REAL)"
    )
    conn.execute(
        "INSERT INTO index_daily VALUES ('20260916','TWII',45848.9)"
    )
    conn.commit()
    conn.close()
    record_watch_events(
        db,
        [
            {
                "id": "c",
                "kind": "reply",
                "layer": 1,
                "date": "2026-09-15",
                "time": "09:02",
                "text": "小心逃命波C-2，不是已確認，43500還是如果",
            }
        ],
    )
    line = latest_watch_line(db)
    assert "不是沒想法" in line
    assert "43500之上" in line or "還沒走到" in line
    assert "不是喊崩" in line
    assert "崩盤" not in line
