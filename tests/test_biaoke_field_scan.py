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
    add("3264", (300.0, 268.0), 244.5, 1200.0)
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
    assert "主產業" in html and "電子上游" in html
    assert "次產業" in html and "IC" in html
    assert "細項" in html and "封測" in html
    assert "次級" in html
    assert "比價" in html
    assert "此刻推薦" in html
    assert "資金輪動要注意" in html
    assert "不是整層電子" in html
    assert "人去樓空" in html
    assert "黃金買點" in html


def test_dongzhu_page_uses_dashed_sections(tmp_path, monkeypatch):
    from pathlib import Path

    from tg_layout import DASH_LINE, reflow_telegram_html

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    assert DASH_LINE in html
    parts = [p.strip() for p in html.split(DASH_LINE) if p.strip()]
    assert len(parts) >= 6
    heads = [p.split("\n", 1)[0] for p in parts]
    blob = "\n".join(heads)
    assert "洞燭先機" in blob
    assert "資金輪動要注意" in html
    assert "此刻最像" in html
    assert "此刻推薦" in html
    assert "① " in html
    assert "② " in html
    assert "③ " in html
    assert "每天流入第一名：" not in html
    name_lines = [
        ln for ln in html.split("\n") if "6257" in ln and "矽格" in ln
    ]
    assert name_lines
    assert all("近5日法人" not in ln for ln in name_lines)
    phone = reflow_telegram_html(html)
    assert DASH_LINE in phone
    hold_src = Path("bot_servers.py").read_text(encoding="utf-8")
    page_i = hold_src.find("async def _send_dongzhu_page")
    hold_i = hold_src.find("async def _send_dongzhu_hold")
    page_end = hold_src.find("\n    async def ", page_i + 10)
    hold_end = hold_src.find("\n    async def ", hold_i + 10)
    assert "reflow=True" in hold_src[page_i:page_end]
    assert "reflow=True" in hold_src[hold_i:hold_end]
    assert "_start_plain_wait" in hold_src[page_i:page_end]
    assert "_start_plain_wait" in hold_src[hold_i:hold_end]
    assert "_wait_bubble" in hold_src[page_i:page_end]
    assert "洞燭先機進行中" in hold_src[page_i:page_end]
    assert "洞燭先機進行中" in hold_src[hold_i:hold_end]
    assert "_leave_zero_section_keyboard" not in hold_src[page_i:page_end]
    assert "_dongzhu_picks_keyboard" in hold_src[page_i:page_end]


def test_dongzhu_hold_page_uses_dashed_sections(tmp_path, monkeypatch):
    from tg_layout import DASH_LINE

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_hold_page

    html = dongzhu_hold_page(db, "6257")
    assert DASH_LINE in html
    assert "能不能留" in html
    assert "判斷單位" not in html
    assert "沒打準" not in html
    assert "再打下一檔" not in html


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
        db, spoken="目前唯一在多頭格局的族群就是ASIC，再來是散熱。PCB全面走弱。"
    )
    assert data.get("field") == "高階測試／封測"
    html = dongzhu_page(db, spoken="目前唯一在多頭格局的族群就是ASIC，再來是散熱。PCB全面走弱。")
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
    assert "主產業" in html
    assert "同主產業" in html
    assert "次級" in html or "龍頭" in html
    assert "比價" in html or "龍頭" in html


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
    spoken = "目前唯一在多頭格局的族群就是ASIC。根據我的指引去找，新族群是封測。"
    data = dongzhu_picks(db, spoken=spoken)
    assert data.get("field") == "PCB"
    html = dongzhu_page(db, spoken=spoken)
    assert "PCB" in html
    assert "主判佔比" in html or "只參考" in html
    assert "3443" not in html
    assert "主產業" in html
    assert "次產業" in html


def test_dongzhu_layers_and_parity_roles():
    from biaoke_field_scan import _GROUPS, _inflow_board, _layer_line, _parity_txt, _stock_role

    test_g = next(g for g in _GROUPS if g["key"] == "test")
    assert _stock_role(test_g, "6515") == "龍頭"
    assert _stock_role(test_g, "6257") == "次級"
    line = _layer_line(("電子上游", "IC", "封測"))
    assert "主產業 電子上游" in line
    assert "次產業 IC" in line
    assert "細項 封測" in line
    missed = _parity_txt(
        test_g,
        [{"sid": "6257", "role": "次級"}],
        {"broke": True},
    )
    assert "來不及買" in missed
    assert "比價" in missed
    both = _parity_txt(
        test_g,
        [{"sid": "6515", "role": "龍頭"}, {"sid": "6257", "role": "次級"}],
        {"broke": False},
    )
    assert "不是替代買訊" in both
    board = _inflow_board(
        [
            {"in_lead_n": 35, "_field": "金控"},
            {"in_lead_n": 13, "_field": "LCD／TFT面板"},
            {"in_lead_n": 4, "_field": "高階測試／封測"},
            {"in_lead_n": 2, "_field": "電信服務"},
        ]
    )
    assert "金控 35天" in board
    assert "LCD／TFT面板 13天" in board
    assert "電信服務" in board
    assert "高階測試／封測" in board


def test_dongzhu_flow_hooks_fuse_not_money_flow():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    money = (root / "money_flow.py").read_text(encoding="utf-8")
    runner = (root / "main_runner.py").read_text(encoding="utf-8")
    screen = (root / "screening_engine.py").read_text(encoding="utf-8")
    assert "from biaoke_field_scan import record_dongzhu_flow" not in money
    assert "record_dongzhu_flow" in runner
    assert "refresh_dongzhu_judgment" in runner
    assert "dongzhu_judge" in runner
    assert "recompute_sector_flow" in runner
    assert "from biaoke_" not in screen
    assert "from dongzhu_screen import rotation_screen_block" in screen


def test_dongzhu_catches_test_laggards_without_stir_words(tmp_path, monkeypatch):
    """他只講 ASIC 是主戰場、沒說蠢蠢欲動；封測佔比已經最高 → 仍抓矽格／欣銓。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        try:
            conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    last_day = datetime(2026, 9, 17)
    n = 60
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, 0, 0, 0),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ]
    chip_days = dates[-6:-1]
    zero_day = dates[-1]
    for i, day in enumerate(chip_days):
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (400 + i * 80, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3264' AND date=?",
            (200 + i * 40, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3443' AND date=?",
            (40, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (800, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=0, trust_net=0, dealer_net=0 WHERE date=?",
        (zero_day,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import _chip_cap, dongzhu_picks, record_dongzhu_flow

    assert record_dongzhu_flow(db, "20260917") > 0
    assert _chip_cap(db, "20260917") == chip_days[-1]
    spoken = "目前唯一在多頭格局的族群就是ASIC，再來是散熱。"
    assert "蠢蠢欲動" not in spoken
    data = dongzhu_picks(db, spoken=spoken)
    assert data.get("field") == "高階測試／封測"
    sids = {x.get("sid") for x in (data.get("laggards") or [])}
    assert "6257" in sids
    assert "3264" in sids
    html = dongzhu_page(db, spoken=spoken)
    assert "高階測試／封測" in html
    assert "6257" in html and "矽格" in html
    assert "3264" in html and "欣銓" in html
    assert "蠢蠢欲動" not in spoken
    assert "不准發明切入" in html or "不是買訊" in html
    empty = dongzhu_picks(db, spoken="")
    assert empty.get("field") == "高階測試／封測"


def test_dongzhu_window_is_100_chip_days():
    import biaoke_field_scan as m
    from biaoke_field_scan import FLOW_LOOKBACK, PRE_VS20, SHARE_DAYS

    assert FLOW_LOOKBACK == 100
    assert SHARE_DAYS == 5
    assert PRE_VS20 == -8.0
    from biaoke_field_scan import PREFER_NOT_LEAD, SKIP_LEAVING_HOT, SKIP_PARKING

    assert PREFER_NOT_LEAD is True
    assert SKIP_LEAVING_HOT is True
    assert SKIP_PARKING is True
    src = open(m.__file__, encoding="utf-8").read()
    assert "START_SHARE" not in src
    assert "START_PCT" not in src
    assert "FLOW_LOOKBACK = 100" in src


def test_dongzhu_chip_dates_skip_all_zero(tmp_path):
    from biaoke_field_scan import FLOW_LOOKBACK, _chip_dates

    db = str(tmp_path / "c.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER, "
        "PRIMARY KEY (date, stock_id))"
    )
    last = datetime(2026, 9, 17)
    for i in range(25):
        day = (last - timedelta(days=24 - i)).strftime("%Y%m%d")
        net = 100 if i < 24 and i % 2 == 0 else 0
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, net, 0, 0),
        )
    conn.commit()
    dates = _chip_dates(conn, "20260917", FLOW_LOOKBACK)
    conn.close()
    assert dates
    assert "20260917" not in dates
    assert all(d <= "20260916" for d in dates)
    assert len(dates) <= FLOW_LOOKBACK
    assert len(dates) > 5


def test_dongzhu_ranks_untaught_ic_design_chain(tmp_path, monkeypatch):
    """沒教過的三層鏈（IC／設計）佔比最高 → 仍抓次級，不靠蠢蠢欲動。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        try:
            conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    last_day = datetime(2026, 9, 17)

    def add(sid, name, highs, last_close, last_vol, base_vol=1000.0):
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
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, sid, name, c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
            )

    add("2454", "聯發科", (1600.0, 1500.0), 1480.0, 8000.0, 5000.0)
    add("3228", "金麗科", (80.0, 70.0), 62.0, 2500.0)
    add("3259", "鑫創", (90.0, 80.0), 71.0, 1800.0)
    n = 60
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, 0, 0, 0),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT NOT NULL, "
        "cat_id TEXT DEFAULT '', source TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    for sid, chain in (
        ("2454", "電子上游-IC-設計"),
        ("3228", "電子上游-IC-設計"),
        ("3259", "電子上游-IC-設計"),
        ("6257", "電子上游-IC-封測"),
        ("3443", "電子上游-IP/ASIC"),
    ):
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
            (sid, chain, "[]", "", "test", "2026-09-17"),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ]
    chip_days = dates[-6:-1]
    zero_day = dates[-1]
    for i, day in enumerate(chip_days):
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3228' AND date=?",
            (500 + i * 120, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3259' AND date=?",
            (300 + i * 80, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2454' AND date=?",
            (200 + i * 40, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='3443' AND date=?",
            (40, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (10, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (800, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=0, trust_net=0, dealer_net=0 WHERE date=?",
        (zero_day,),
    )
    conn.commit()
    conn.close()
    save_screen_session(
        db,
        "20260917",
        "morning",
        {"leave_zero": [{"stock_id": "3228", "stock_name": "金麗科", "pick_close": 62.0}]},
    )
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import FLOW_LOOKBACK, dongzhu_picks

    spoken = "目前唯一在多頭格局的族群就是ASIC，再來是散熱。"
    assert "蠢蠢欲動" not in spoken
    data = dongzhu_picks(db, spoken=spoken)
    assert data.get("field") == "高階測試／封測"
    assert data.get("flow_window") == FLOW_LOOKBACK
    assert data.get("chip_cap") == chip_days[-1]
    assert data.get("pre_sign") == "pre"
    buy_sids = {x.get("sid") for x in (data.get("buys") or [])}
    assert "3228" not in buy_sids
    html = dongzhu_page(db, spoken=spoken)
    assert "高階測試／封測" in html
    assert "設計" in html
    assert "資金窗近100個有法人日" in html
    assert "3443" not in html
    assert "不准發明切入" in html
    assert "次熱" in html
    assert "沒打準" in html or "打股名" in html


def test_dongzhu_100d_skips_telecom_at_20high_for_test_laggards(tmp_path, monkeypatch):
    """100日：電信佔比最高但次級已貼20高＝偏晚；封測次級距20高≤−8% 才是先機。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        try:
            conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    last_day = datetime(2026, 9, 17)
    n = 60

    def add_flat(sid, name, px, vol):
        for i in range(n):
            day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, sid, name, px, px, px, px, int(vol), 0.0, 0, 0, 0),
            )

    add_flat("2412", "中華電", 128.0, 8000)
    add_flat("3045", "台灣大", 124.5, 3000)
    add_flat("4904", "遠傳", 105.0, 2500)
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, 0, 0, 0),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT NOT NULL, "
        "cat_id TEXT DEFAULT '', source TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    for sid, chain in (
        ("2412", "電子下游-電信服務"),
        ("3045", "電子下游-電信服務"),
        ("4904", "電子下游-電信服務"),
        ("6257", "電子上游-IC-封測"),
        ("3264", "電子上游-IC-封測"),
        ("2449", "電子上游-IC-封測"),
    ):
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
            (sid, chain, "[]", "", "test", "2026-09-17"),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ]
    chip_days = dates[-6:-1]
    zero_day = dates[-1]
    for i, day in enumerate(chip_days):
        for sid, net in (("2412", 900), ("3045", 700), ("4904", 500)):
            conn.execute(
                "UPDATE daily_quotes SET foreign_net=? WHERE stock_id=? AND date=?",
                (net + i * 40, sid, day),
            )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (200 + i * 50, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2449' AND date=?",
            (80 + i * 20, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (400, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=0, trust_net=0, dealer_net=0 WHERE date=?",
        (zero_day,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_picks

    data = dongzhu_picks(db, spoken="")
    assert data.get("field") == "高階測試／封測"
    assert data.get("pre_ok") is True
    assert data.get("pre_late") is False
    html = dongzhu_page(db, spoken="")
    assert "高階測試／封測" in html
    assert "電信服務" not in html.split("此刻最像")[-1][:80]
    assert "6257" in html or "2449" in html
    assert "資金窗近100個有法人日" in html
    assert "流入第一名" in html
    assert "每天流入第一名" in html


def test_dongzhu_hold_uses_stock_own_fine_not_electronics(tmp_path, monkeypatch):
    """打矽格：判斷單位是電子上游／IC／封測，不是整層電子。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        try:
            conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    last_day = datetime(2026, 9, 17)
    n = 60

    def add_flat(sid, name, px, vol):
        for i in range(n):
            day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, sid, name, px, px, px, px, int(vol), 0.0, 0, 0, 0),
            )

    add_flat("2412", "中華電", 128.0, 8000)
    add_flat("3045", "台灣大", 124.5, 3000)
    add_flat("4904", "遠傳", 105.0, 2500)
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, 0, 0, 0),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT NOT NULL, "
        "cat_id TEXT DEFAULT '', source TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    for sid, chain in (
        ("2412", "電子下游-電信服務"),
        ("3045", "電子下游-電信服務"),
        ("4904", "電子下游-電信服務"),
        ("6257", "電子上游-IC-封測"),
        ("3264", "電子上游-IC-封測"),
        ("2449", "電子上游-IC-封測"),
    ):
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
            (sid, chain, "[]", "", "test", "2026-09-17"),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ]
    chip_days = dates[-6:-1]
    zero_day = dates[-1]
    for i, day in enumerate(chip_days):
        tel = 900 if i < len(chip_days) - 1 else 500
        test_net = 80 + i * 90
        for sid, net in (("2412", tel), ("3045", tel - 100), ("4904", tel - 200)):
            conn.execute(
                "UPDATE daily_quotes SET foreign_net=? WHERE stock_id=? AND date=?",
                (net, sid, day),
            )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (test_net, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2449' AND date=?",
            (40 + i * 20, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (400, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=0, trust_net=0, dealer_net=0 WHERE date=?",
        (zero_day,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_hold, dongzhu_hold_page

    data = dongzhu_hold(db, "6257")
    assert data.get("layers") == ["電子上游", "IC", "封測"]
    assert "電子上游" in str(data.get("layer_txt") or "")
    assert "封測" in str(data.get("layer_txt") or "")
    assert data.get("layers")[0] != "電子"
    html = dongzhu_hold_page(db, "6257")
    assert "能不能留" in html
    assert "主產業 電子上游" in html
    assert "次產業 IC" in html
    assert "細項 封測" in html
    assert "判斷單位" not in html
    assert "沒打準" not in html
    assert "再打下一檔" not in html
    assert "整層電子" not in html
    assert data.get("verdict") in ("可留觀察", "可留", "還在")
    assert data.get("buy") is False
    tel = dongzhu_hold(db, "2412")
    assert tel.get("layers")[-1] == "電信服務"
    assert tel.get("verdict") in ("不留", "小心", "偏晚")
    assert tel.get("hold") is False
    assert tel.get("buy") is False


def test_dongzhu_hold_missing_chain_does_not_invent(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_hold_page

    html = dongzhu_hold_page(db, "6257")
    assert "還沒" in html or "不准猜" in html
    assert "判斷單位" not in html
    assert "再打下一檔" not in html


def test_rotation_notice_and_screen_block(tmp_path, monkeypatch):
    from biaoke_field_scan import ROTATION_NOTES, rotation_notice_lines, rotation_screen_block

    notes = rotation_notice_lines()
    blob = "".join(notes)
    assert notes == list(ROTATION_NOTES)
    assert "不是整層電子" in blob
    assert "人去樓空" in blob
    assert "停車格" in blob
    assert "黃金買點" in blob
    assert "紅箭頭不是買訊" in blob
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = rotation_screen_block(db)
    assert "台股資金輪動" in html
    assert "不是整層電子" in html
    assert "人去樓空" in html


def test_dongzhu_precursor_store_feeds_notes_and_flags(tmp_path):
    db = str(tmp_path / "p.db")
    sqlite3.connect(db).close()
    from biaoke_field_scan import (
        live_dongzhu_flags,
        rotation_notice_lines,
        store_dongzhu_precursor,
    )

    store_dongzhu_precursor(
        db,
        "20260917",
        {
            "skip_parking": True,
            "prefer_rising_not_lead": True,
            "skip_leaving_hot": True,
            "rates": {
                "no_park": {"n": 80, "gain": 80.0, "stuck": 1.2},
                "pre": {"n": 75, "gain": 70.7, "stuck": 4.0},
                "chase": {"n": 68, "gain": 55.9, "stuck": 4.4},
            },
        },
    )
    flags = live_dongzhu_flags(db)
    assert flags["skip_parking"] is True
    assert flags["prefer_rising_not_lead"] is True
    blob = "".join(rotation_notice_lines(db))
    assert "約80%" in blob
    assert "停車格" in blob
    assert "細項" in blob


def test_parking_chain_flags_holding_and_bank():
    from biaoke_field_scan import _is_parking_chain

    assert _is_parking_chain(
        {"fine_tag": "金控", "_field": "金控", "_layers": ("金融", "金控")}
    )
    assert _is_parking_chain(
        {"fine_tag": "銀行", "_field": "銀行", "_layers": ("金融", "銀行")}
    )
    assert not _is_parking_chain(
        {
            "fine_tag": "封測",
            "_field": "高階測試／封測",
            "_layers": ("電子上游", "IC", "封測"),
        }
    )


def test_dongzhu_skips_holding_company_parking(tmp_path, monkeypatch):
    """金控佔比次高但當停車格；封測才是先機。"""
    db = str(tmp_path / "f.db")
    _seed(db)
    conn = sqlite3.connect(db)
    for col in ("foreign_net", "trust_net", "dealer_net"):
        try:
            conn.execute(f"ALTER TABLE daily_quotes ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    last_day = datetime(2026, 9, 17)
    n = 60

    def add(sid, name, highs, last_close, last_vol, base_vol=1000.0):
        for i in range(n):
            day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
            if i < 40:
                h, c, v = highs[0], highs[0] * 0.92, base_vol
            elif i < n - 1:
                h, c, v = highs[1], highs[1] * 0.96, base_vol
            else:
                h, c, v = highs[1] * 0.99, last_close, last_vol
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, sid, name, c, h, c * 0.98, c, int(v), 0.0, 0, 0, 0),
            )

    def add_flat(sid, name, px, vol):
        for i in range(n):
            day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (day, sid, name, px, px, px, px, int(vol), 0.0, 0, 0, 0),
            )

    add_flat("2412", "中華電", 128.0, 8000)
    add_flat("3045", "台灣大", 124.5, 3000)
    add_flat("4904", "遠傳", 105.0, 2500)
    add("2881", "富邦金", (100.0, 95.0), 93.0, 8000.0, 4000.0)
    add("2880", "華南金", (40.0, 38.0), 32.0, 2000.0)
    add("2890", "永豐金", (50.0, 48.0), 42.0, 1500.0)
    for i in range(n):
        day = (last_day - timedelta(days=n - 1 - i)).strftime("%Y%m%d")
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "2330", "台積電", 1, 1, 1, 1, 1, 0.0, 0, 0, 0),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT NOT NULL, "
        "cat_id TEXT DEFAULT '', source TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    for sid, chain in (
        ("2412", "電子下游-電信服務"),
        ("3045", "電子下游-電信服務"),
        ("4904", "電子下游-電信服務"),
        ("2881", "金融-金控"),
        ("2880", "金融-金控"),
        ("2890", "金融-金控"),
        ("6257", "電子上游-IC-封測"),
        ("3264", "電子上游-IC-封測"),
        ("2449", "電子上游-IC-封測"),
    ):
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
            (sid, chain, "[]", "", "test", "2026-09-17"),
        )
    dates = [
        str(r[0])
        for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date").fetchall()
    ]
    chip_days = dates[-6:-1]
    zero_day = dates[-1]
    for i, day in enumerate(chip_days):
        for sid, net in (("2412", 900), ("3045", 700), ("4904", 500)):
            conn.execute(
                "UPDATE daily_quotes SET foreign_net=? WHERE stock_id=? AND date=?",
                (net + i * 40, sid, day),
            )
        for sid, net in (("2881", 400), ("2880", 250), ("2890", 180)):
            conn.execute(
                "UPDATE daily_quotes SET foreign_net=? WHERE stock_id=? AND date=?",
                (net + i * 30, sid, day),
            )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='6257' AND date=?",
            (200 + i * 50, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2449' AND date=?",
            (80 + i * 20, day),
        )
        conn.execute(
            "UPDATE daily_quotes SET foreign_net=? WHERE stock_id='2330' AND date=?",
            (400, day),
        )
    conn.execute(
        "UPDATE daily_quotes SET foreign_net=0, trust_net=0, dealer_net=0 WHERE date=?",
        (zero_day,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_picks

    data = dongzhu_picks(db, spoken="")
    assert data.get("field") == "高階測試／封測"
    assert "金控" not in str(data.get("field") or "")
    assert data.get("pre_ok") is True
    html = dongzhu_page(db, spoken="")
    assert "高階測試／封測" in html
    assert "停車格" in html
    assert "金控／銀行當停車格" in html or "不拿來當先機" in html
