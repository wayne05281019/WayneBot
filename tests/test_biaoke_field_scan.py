# -*- coding: utf-8 -*-
"""還沒點名的族群：用他教過的找法對官方日 K，不准猜。"""
import sqlite3
from datetime import datetime, timedelta

from biaoke_chain import _field
from biaoke_field_scan import dongzhu_page, scan_unnamed_field, want_field_scan
from biaoke_mind import match_methods
from screen_sessions import save_screen_session


def _seed(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.execute(
        "CREATE TABLE biaoke_posts (id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, "
        "kind TEXT, tags TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?)",
        (
            "184802289",
            1,
            "2026-09-18",
            "08:58",
            "post",
            "[]",
            "目前唯一在多頭格局的族群就是ASIC，再來是散熱，再次之就是光通訊、記憶體。"
            "有一個新族群目前在底部蠢蠢欲動，可以根據我的指引去找。",
        ),
    )
    last_day = datetime(2026, 9, 17)

    def add(sid, highs, last_close, last_vol, base_vol=1000.0):
        n = 60
        for i in range(n):
            day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
            if i < 40:
                h, c, v = highs[0], highs[0] * 0.92, base_vol
            elif i < n - 1:
                h, c, v = highs[1], highs[1] * 0.96, base_vol
            else:
                h, c, v = highs[1] * 0.99, last_close, last_vol
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, c, h, c * 0.98, c, int(v), 0.0),
            )

    add("6257", (300.0, 228.0), 222.5, 2500.0)
    add("2449", (150.0, 140.0), 100.0, 900.0)
    add("6515", (10180.0, 8260.0), 6120.0, 900.0)
    add("6223", (7700.0, 6060.0), 5500.0, 800.0)
    add("3443", (6610.0, 6610.0), 6500.0, 1200.0)
    conn.commit()
    conn.close()


def test_want_scan_on_his_find_words():
    assert want_field_scan("根據我的指引去找新族群")
    assert want_field_scan("底部蠢蠢欲動是哪個")
    assert not want_field_scan("台光電怎麼看")


def test_dongzhu_method_hits_find_words():
    hits = match_methods("有一個新族群目前在底部蠢蠢欲動，根據我的指引去找")
    titles = [t for t, _ in hits]
    assert "洞燭先機" in titles
    body = next(b for t, b in hits if t == "洞燭先機")
    assert "從底部找落後" in body
    assert "次族群第一名" in body


def test_scan_picks_test_laggard_not_named_asic(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    line = scan_unnamed_field(db, ask="根據我的指引去找")
    assert "高階測試／封測" in line
    assert "矽格" in line
    assert "6257" in line
    assert "穎崴" in line
    assert "還沒先過前高" in line
    assert "ASIC" in line and "不當新族群" in line
    assert "不是買訊" in line
    assert "不是他當下點名" in line


def test_field_neuron_runs_scan_without_stock_id(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    step = _field("他說新族群底部蠢蠢欲動，怎麼找", {}, db_path=db)
    assert step["ok"] is True
    assert "高階測試／封測" in step["text"]
    assert "洞燭先機" in step["text"] or "還沒熱" in step["text"]


def test_dongzhu_page_recommends_leave_zero_in_field(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    save_screen_session(
        db,
        "20260917",
        "morning",
        {
            "leave_zero": [{"stock_id": "6257", "stock_name": "矽格", "pick_close": 222.5}],
            "golden_buy": [{"stock_id": "2449", "stock_name": "京元電子", "pick_close": 80.0}],
        },
    )
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    assert "洞燭先機" in html
    assert "高階測試／封測" in html
    assert "還沒點名" in html
    assert "6257" in html and "矽格" in html
    assert "買點" in html
    assert "京元電子" in html
    assert "只觀察" in html or "觀察" in html
    assert "不是買訊" in html
    assert "不進海選" in html


def test_dongzhu_page_does_not_invent_buy_or_named_asic(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    save_screen_session(
        db,
        "20260917",
        "morning",
        {"leave_zero": [{"stock_id": "3443", "stock_name": "創意", "pick_close": 6500.0}]},
    )
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    assert "高階測試／封測" in html
    assert "沒有黃金買點" in html
    assert "不准發明切入" in html
    assert "3443" not in html
    assert "矽格" in html
    assert "不是買訊" in html
