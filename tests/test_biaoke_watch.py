# -*- coding: utf-8 -*-
"""捕獲後同步想：看到什麼、為何這樣回、下一步盯什麼。"""
from biaoke_watch import record_watch_events, think_spoken, latest_watch_line


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
    assert "下一步" in line
