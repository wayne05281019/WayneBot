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


def test_ignite_needs_several_buy_days_not_one_spike():
    from biaoke_field_scan import _ignite_from_nets

    slow = _ignite_from_nets([80, 90, 100, 110, 120])
    assert slow["slow_in"] is True
    assert slow["pos_days"] == 5
    spike = _ignite_from_nets([0, 0, 0, 0, 20000])
    assert spike["slow_in"] is False


def test_dongzhu_records_slow_inflow_skips_named_hot(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ][-5:]
    for i, day in enumerate(dates):
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (120 + i * 20, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3443' AND date=?",
            (8000, day),
        )
    conn.commit()
    conn.close()
    save_screen_session(
        db,
        "20260917",
        "morning",
        {"leave_zero": [{"stock_id": "6257", "stock_name": "矽格", "pick_close": 222.5}]},
    )
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import group_ignite, record_dongzhu_flow

    assert record_dongzhu_flow(db, "20260917") > 0
    test_ign = group_ignite(db, "test", "20260917")
    asic_ign = group_ignite(db, "asic", "20260917")
    assert test_ign["slow_in"] is True
    assert asic_ign["cum5"] > test_ign["cum5"]
    html = dongzhu_page(db)
    assert "高階測試／封測" in html
    assert "資金流入" in html or "佔比在升" in html or "流入這細項" in html
    assert "資金進出" in html or "佔當日" in html or "細項" in html
    assert "6257" in html and "矽格" in html
    assert "3443" not in html
    assert "只參考" in html or "主戰場" in html


def test_ignite_share_in_not_lots_size():
    from biaoke_field_scan import _ignite_from_nets

    rising = _ignite_from_nets([80, 90, 100, 110, 120], [0.4, 0.7, 1.1, 1.6, 2.2])
    assert rising["slow_in"] is True
    assert rising["flowing_in"] is True
    falling = _ignite_from_nets([80, 90, 100, 110, 120], [5.0, 4.0, 3.0, 2.0, 1.0])
    assert falling["slow_in"] is False
    assert falling["flowing_in"] is False
    spike = _ignite_from_nets([0, 0, 0, 0, 20000], [0.1, 0.1, 0.1, 0.1, 8.0])
    assert spike["slow_in"] is False


def test_dongzhu_ranks_rising_share_not_named_lots(tmp_path, monkeypatch):
    """封測張遠小於 ASIC／PCB，但佔比在升 → 仍選封測。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
    last_day = datetime(2026, 9, 17)
    n = 60
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        h, c, v = 800.0, 720.0, 1000.0
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2383", "台光電", c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
        )
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT NOT NULL, "
        "cat_id TEXT DEFAULT '', source TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
        ("6257", "電子上游-IC-封測", "[]", "", "test", "2026-09-17"),
    )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ][-5:]
    for i, day in enumerate(dates):
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (80 + i * 200, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2383' AND date=?",
            (5000, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3443' AND date=?",
            (8000, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (20000, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET volume=1000 WHERE stock_id='6257' AND date=?",
        (dates[-1],),
    )
    conn.commit()
    conn.close()
    save_screen_session(
        db,
        "20260917",
        "morning",
        {"leave_zero": [{"stock_id": "6257", "stock_name": "矽格", "pick_close": 222.5}]},
    )
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_picks, group_ignite, record_dongzhu_flow

    assert record_dongzhu_flow(db, "20260917") > 0
    test_ign = group_ignite(db, "test", "20260917")
    pcb_ign = group_ignite(db, "pcb", "20260917")
    asic_ign = group_ignite(db, "asic", "20260917")
    assert test_ign["flowing_in"] is True
    assert asic_ign["cum5"] > test_ign["cum5"]
    assert pcb_ign["cum5"] > test_ign["cum5"]
    assert test_ign["share_up"] > pcb_ign["share_up"]
    data = dongzhu_picks(
        db, spoken="目前主戰場就是封測。根據我的指引去找。"
    )
    assert data.get("field") == "高階測試／封測"
    html = dongzhu_page(db, spoken="目前主戰場就是封測。根據我的指引去找。")
    assert "高階測試／封測" in html
    assert "細項" in html
    assert "%" in html
    assert "pt" in html or "佔" in html
    assert "對五件" in html
    assert "6257" in html
    assert "3443" not in html
    assert "資金流入" in html or "佔比在升" in html
    assert "只參考" in html or "不是唯一" in html
    assert "不准發明切入" not in html


def test_dongzhu_share_beats_his_named_field(tmp_path, monkeypatch):
    """他點名去找封測，但封測佔比在退、PCB 佔比在升 → 主判 PCB。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
    last_day = datetime(2026, 9, 17)
    n = 60
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        h, c, v = 800.0, 720.0, 1000.0
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2383", "台光電", c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
        )
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ][-5:]
    for i, day in enumerate(dates):
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (800 - i * 120, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2383' AND date=?",
            (80 + i * 220, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3443' AND date=?",
            (8000, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (20000, day),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_picks, group_ignite, record_dongzhu_flow

    assert record_dongzhu_flow(db, "20260917") > 0
    assert group_ignite(db, "test", "20260917")["flowing_in"] is False
    assert group_ignite(db, "pcb", "20260917")["flowing_in"] is True
    spoken = "根據我的指引去找，新族群是封測。"
    data = dongzhu_picks(db, spoken=spoken)
    assert data.get("field") == "PCB"
    html = dongzhu_page(db, spoken=spoken)
    assert "PCB" in html
    assert "主判佔比" in html or "只參考" in html
    assert "3443" not in html
