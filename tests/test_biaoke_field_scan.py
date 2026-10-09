# -*- coding: utf-8 -*-
"""還沒點名的族群：用他教過的找法對官方日 K，不准猜。"""
import sqlite3
from datetime import datetime, timedelta

from biaoke_chain import _field
from biaoke_field_scan import (
    dongzhu_page,
    scan_unnamed_field,
    want_field_scan,
    want_share_cross,
)
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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quarterly_income ("
        "stock_id TEXT NOT NULL, year INTEGER NOT NULL, season INTEGER NOT NULL, "
        "stock_name TEXT DEFAULT '', market TEXT DEFAULT '', revenue REAL DEFAULT 0, "
        "cogs REAL DEFAULT 0, gross_profit REAL DEFAULT 0, gross_margin_pct REAL DEFAULT 0, "
        "operating_income REAL DEFAULT 0, net_income REAL DEFAULT 0, eps REAL DEFAULT 0, "
        "published_roc TEXT DEFAULT '', updated_at TEXT DEFAULT '', "
        "PRIMARY KEY (stock_id, year, season))"
    )
    for sid, eps in (
        ("6257", 1.20),
        ("3264", 0.80),
        ("2449", 0.50),
        ("6515", 4.00),
        ("6223", 3.00),
        ("3443", 2.00),
    ):
        conn.execute(
            "INSERT INTO quarterly_income(stock_id,year,season,eps) VALUES (?,?,?,?)",
            (sid, 2026, 2, eps),
        )
    conn.commit()
    conn.close()


def test_want_scan_on_his_find_words():
    assert want_field_scan("根據我的指引去找新族群")
    assert want_field_scan("底部蠢蠢欲動是哪個")
    assert not want_field_scan("台光電怎麼看")


def test_want_share_cross_on_which_field_not_stock_look():
    assert want_share_cross("現在哪族先機")
    assert want_share_cross("資金輪動現在看哪")
    assert want_share_cross("根據我的指引去找")
    assert not want_share_cross("台光電怎麼看")
    assert not want_share_cross("洗盤跟出貨怎麼分")


def test_share_cross_is_not_a_buy_list(tmp_path, monkeypatch):
    from biaoke_field_scan import share_cross_lines

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    blob = "\n".join(share_cross_lines(db))
    assert "官方佔比" in blob
    assert "可買" not in blob
    assert "leave_zero" not in blob


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
    assert "京元電子" in line or "2449" in line
    assert "6257" not in line
    assert "穎崴" in line
    assert "還沒先過前高" in line
    assert "ASIC" in line and "不當新族群" in line
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
    assert "這族黃金買點" not in html
    assert "還在零・嚴重低估" not in html
    assert "捕捉・同鏈比價落後" not in html
    assert "此刻推薦" in html
    assert "主產業" in html and "電子上游" in html
    assert "次產業" in html and "IC" in html
    # 教戰／規則清單／「資金輪動要注意」不准再塞每次正文
    assert "資金輪動要注意" not in html
    assert "不是整層電子" not in html
    assert "他教過怎麼找" not in html
    assert "① " not in html
    assert "佔比如實主判" not in html
    assert "每檔先寫買或不買" not in html
    assert "盤中未收不當官方收" not in html
    assert "誰先過前高" not in html
    assert "官方收" in html
    assert "黃金買點" in html
    assert "點左邊選" not in html
    # 這測例未必有可捕捉次級；有推薦時才會寫「點圖下鈕選檔」（見下方有 recs 的測）
    if "這型最落後次級" in html:
        assert "點圖下鈕選檔" in html
        assert html.count("點圖下鈕選檔") == 1


def test_dongzhu_page_uses_dashed_sections(tmp_path, monkeypatch):
    from pathlib import Path

    from tg_layout import DASH_LINE, reflow_telegram_html

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    assert DASH_LINE in html
    parts = [p.strip() for p in html.split(DASH_LINE) if p.strip()]
    assert len(parts) >= 4
    heads = [p.split("\n", 1)[0] for p in parts]
    blob = "\n".join(heads)
    assert "洞燭先機" in blob
    assert "資金輪動要注意" not in html
    assert "資金進哪條" not in html
    assert "追漲不追跌" not in html
    assert "此刻最像" in html
    assert "此刻推薦" in html
    assert "① " not in html
    assert "② " not in html
    assert "③ " not in html
    assert "每天流入第一名：" not in html
    assert "這族黃金買點" not in html
    assert "還在零・嚴重低估" not in html
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
    assert hold_src[page_i:page_end].count("dongzhu_picks(") == 1
    assert "data=data" in hold_src[page_i:page_end]
    assert "held_sids" in hold_src[page_i:page_end]
    assert "_dongzhu_held_sids" in hold_src[page_i:page_end]
    assert "_dongzhu_hits_keyboard" in hold_src[hold_i:hold_end]
    assert "self._hits_keyboard(" not in hold_src[hold_i:hold_end]


def test_dongzhu_page_phone_reflow_does_not_split_numbers(tmp_path, monkeypatch):
    import re

    from tg_layout import reflow_telegram_html

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    phone = reflow_telegram_html(html)
    for ln in phone.split("\n"):
        s = ln.strip()
        assert not re.search(r"\d,$", s)
        assert s not in ("IC／", "電子上游／IC／")
        assert len(re.sub(r"<[^>]+>", "", s)) <= 18 or s.startswith("┈")
    assert "對五件" not in phone
    assert "他教過怎麼找" not in phone
    assert "誰先過前高" not in phone
    assert "資金輪動要注意" not in phone
    assert "佔比如實主判" not in phone
    assert "第一名還沒過前高" not in phone
    assert "此刻最像" in phone
    assert "官方收" in phone
    assert "此刻推薦" in phone
    assert "落後·次級" not in phone
    assert "電子上游 / IC /" not in phone
    assert "電子上游／IC／" not in phone


def test_dongzhu_stock_card_held_says_keep_or_not(tmp_path, monkeypatch):
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
    html = dongzhu_page(db, held_sids=["6257", "2449"])
    assert "這族黃金買點" not in html
    assert "還在零・嚴重低估" not in html
    assert html.find("6257") < 0
    empty = dongzhu_page(db, held_sids=[])
    assert "可加碼" not in empty
    assert "\n已持有\n" not in empty


def test_dongzhu_hold_page_action_before_numbers(tmp_path, monkeypatch):
    from tg_layout import reflow_telegram_html

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_hold_page

    html = dongzhu_hold_page(db, "6257", held=True)
    phone = reflow_telegram_html(html)
    lines = [ln.strip() for ln in phone.split("\n") if ln.strip()]
    text = "\n".join(lines)
    assert "已持有" in text
    assert "不買" in text
    assert "不加碼" in text
    i_name = next(i for i, ln in enumerate(lines) if "6257" in ln)
    i_act = next(
        i
        for i, ln in enumerate(lines)
        if ln.replace("<b>", "").replace("</b>", "")
        in ("還沒", "可留", "可留觀察", "不留", "偏晚")
    )
    assert i_name < i_act


def test_flow_why_phone_lines_keep_lots_intact():
    from tg_layout import reflow_telegram_html

    from biaoke_field_scan import _flow_why_lines, _sibling_phone_lines

    ign = {
        "fine_tag": "封測",
        "shares": [4.4, 4.8, 0.7, 2.5, 12.2],
        "share_last": 12.2,
        "share_chg": 9.7,
        "share_up": 7.8,
        "nets": [17714, 9461, 4288, 20712, 85409],
        "cum5": 137584,
        "pos_member": 23,
        "member_n": 29,
        "flowing_in": True,
        "slow_in": True,
        "last": 85409,
    }
    html = "\n".join(_flow_why_lines(ign))
    phone = reflow_telegram_html(html)
    plain = "\n".join(
        ln.strip() for ln in phone.split("\n") if ln.strip()
    )
    assert "＋85,409張" in plain
    assert "＋137,584張" in plain
    assert "12.2" in plain
    for ln in phone.split("\n"):
        s = ln.strip()
        assert s not in ("＋85,40", "9")
        assert not s.startswith("%")
        assert len(s) <= 18 or s.startswith("┈")
    sib = _sibling_phone_lines(
        "同主產業 IC／代工 23.0%（升）｜記憶體製造 13.4%（升）｜IC／封測 12.2%（升）"
        "｜被動元件 3.3%（升）｜LED照明及光元件 2.9%（升）"
    )
    sib_phone = reflow_telegram_html("\n".join(sib))
    assert "IC／" not in sib_phone.split("\n")
    assert "IC／代工 23.0%（升）" in sib_phone or "IC／代工" in sib_phone



def test_dongzhu_hold_page_uses_dashed_sections(tmp_path, monkeypatch):
    from tg_layout import DASH_LINE

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    from biaoke_field_scan import dongzhu_hold_page

    html = dongzhu_hold_page(db, "6257")
    assert DASH_LINE in html
    assert "能不能留" in html
    assert "不買" in html or "可買" in html
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
    assert "3443" not in html
    assert "這族黃金買點" not in html
    assert "還在零・嚴重低估" not in html
    assert "沒有可捕捉的次級" in html or "這型最落後次級" in html
    assert "不准發明切入" not in html


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
    assert "資金流入" in html or "佔比" in html or "先機" in html
    assert "資金進出" in html or "佔當日" in html or "產業鏈" in html or "封測" in html
    assert "這族黃金買點" not in html
    assert "3443" not in html
    assert "他教過怎麼找" not in html
    assert "資金輪動要注意" not in html
    assert "官方收" in html
    assert "此刻最像" in html


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
    rec_sids = [x.get("sid") for x in list(data.get("recs") or [])]
    lag_sids = [x.get("sid") for x in list(data.get("laggards") or [])]
    assert rec_sids == lag_sids
    assert rec_sids
    assert "6257" not in rec_sids
    html = dongzhu_page(db, spoken="目前唯一在多頭格局的族群就是ASIC，再來是散熱。PCB全面走弱。")
    assert "高階測試／封測" in html
    assert "封測" in html or "產業鏈" in html or "主產業" in html
    assert "%" in html
    assert "pt" in html or "佔" in html
    assert "這族黃金買點" not in html
    assert "這型最落後次級" in html
    assert "3443" not in html
    assert "資金流入" in html or "佔比" in html or "先機" in html
    assert "主產業" in html
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
    assert "佔當日法人買超" in html or "佔比" in html
    assert "他教過怎麼找" not in html
    assert "資金輪動要注意" not in html
    assert "3443" not in html
    assert "主產業" in html
    assert "次產業" in html


def test_dongzhu_layers_and_parity_roles():
    from biaoke_field_scan import _GROUPS, _inflow_board, _layer_line, _parity_txt, _stock_role

    test_g = next(g for g in _GROUPS if g["key"] == "test")
    assert _stock_role(test_g, "6515") == "龍頭"
    assert _stock_role(test_g, "6257") == "次級"
    mature = next(g for g in _GROUPS if g["key"] == "mature")
    assert _stock_role(mature, "2303") == "龍頭"
    sat = next(g for g in _GROUPS if g["key"] == "sat")
    assert _stock_role(sat, "3491") == "龍頭"
    from biaoke_field_scan import _is_flow_group

    assert _is_flow_group(test_g)
    assert not _is_flow_group(mature)
    assert not _is_flow_group(sat)
    robot = next(g for g in _GROUPS if g["key"] == "robot")
    assert not _is_flow_group(robot)
    mem = next(g for g in _GROUPS if g["key"] == "mem")
    assert _is_flow_group(mem)
    solar = next(g for g in _GROUPS if g["key"] == "solar")
    assert _is_flow_group(solar)
    memmod = next(g for g in _GROUPS if g["key"] == "memmod")
    assert _is_flow_group(memmod)
    for key in ("hitest", "mempack", "lab", "air", "power", "chem", "fab"):
        assert not _is_flow_group(next(g for g in _GROUPS if g["key"] == key)), key
    from biaoke_field_scan import _stock_line

    lead_line = _stock_line(
        {"sid": "2303", "name": "聯電", "role": "龍頭", "vs20": -10.0, "vs60": -20.0},
        1,
        "買點",
    )
    assert lead_line.startswith("1. <code>龍頭</code> ")
    assert "2303" in lead_line and "聯電" in lead_line
    assert "href=" in lead_line
    line = _layer_line(("電子上游", "IC", "封測"))
    assert "主產業 電子上游" in line
    assert "次產業 IC" in line
    assert "產業鏈 封測" in line
    assert "細項" not in line
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


def test_dongzhu_rotation_layer_and_leader_ref_clarity():
    """輪動進哪一層要寫清；龍頭只對照；單日／近窗佔比分開標。"""
    from biaoke_field_scan import (
        _dongzhu_query_stamp_line,
        _leader_ref_lines,
        _rotation_layer_lines,
        _share_path_lines,
    )

    rot = _rotation_layer_lines(
        ("電子上游", "IC", "封測"),
        {"share_up": 1.6, "share_chg": 0.8},
        {"field": "金控", "share_up": -2.0},
    )
    assert rot[0] == "輪動進產業鏈 封測"
    assert any("佔比最高退→這鏈升" in x for x in rot)
    assert "金控" not in "\n".join(rot)
    assert "細項" not in "\n".join(rot)
    assert not any("近窗佔比" in x for x in rot)  # 數字留給 share_path

    lead = _leader_ref_lines(
        {
            "leader": {"sid": "6515", "name": "穎崴", "vs20": -12.0, "broke": False},
            "buys": [],
        }
    )
    assert "6515 穎崴" in lead
    assert "龍頭・只對照" in lead
    assert any("距20高" in x for x in lead)
    assert "還沒過前高" in lead

    path = _share_path_lines(
        {"shares": [0.0, 0.4, 1.6], "share_chg": 1.2, "share_up": 1.6}
    )
    blob = "\n".join(path)
    assert "近3日佔比" in blob or "0.0%→1.6%" in blob
    assert "近窗升" in blob
    assert "單日升" in blob
    assert "佔當日" in blob
    # 退／平也要一字標，不准只寫裸 pt
    down = "\n".join(
        _share_path_lines({"shares": [2.0, 1.0], "share_chg": -1.0, "share_up": -1.0})
    )
    assert "近窗退" in down
    assert "單日退" in down

    stamp = _dongzhu_query_stamp_line("20260917")
    assert stamp.startswith("查詢 ")


def test_dongzhu_page_evolve_share_buy_bridge(tmp_path, monkeypatch):
    """進化：佔比升降標清、先機／買點銜接、切入只認黃金買點；不改編碼。"""
    from tg_layout import reflow_telegram_html

    from biaoke_field_scan import (
        _share_chg_line,
        _stock_action_lines,
        dongzhu_hold_page,
        dongzhu_page,
    )

    assert _share_chg_line("單日", 0.8) == "單日升 ＋0.8pt"
    assert _share_chg_line("近窗", -1.2) == "近窗退 −1.2pt"
    assert _stock_action_lines({}, "先機") == ["先機・只觀察"]
    assert _stock_action_lines({}, "買點")[0] == "買點・可切入"
    assert "可買" in _stock_action_lines({}, "買點")

    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db)
    phone = reflow_telegram_html(html)
    assert "切入只認黃金買點" in html
    assert "先機・只觀察不是買訊" in html
    assert "買點＝剛離零才可切入" in html
    assert "剛好剛離零才標黃金買點" not in html
    assert "可看" not in html
    # 層級仍寫主／次／產業鏈（＝細項那層）；不准發明「細項」字樣上話筒
    assert "主產業" in html and "次產業" in html and "產業鏈" in html
    assert "細項" not in html
    assert "佔比如實主判" not in html
    assert "資金輪動要注意" not in html
    for ln in phone.split("\n"):
        s = ln.strip()
        plain = __import__("re").sub(r"<[^>]+>", "", s)
        assert len(plain) <= 18 or s.startswith("┈")

    hold = dongzhu_hold_page(db, "6257")
    assert "輪動進" in hold or "主產業" in hold
    assert "不買" in hold or "可買" in hold
    if "可買" in hold:
        assert "買點・可切入" in hold
        assert "切入只認黃金買點" in hold


def test_dongzhu_page_shows_rotation_leader_and_stamp(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    html = dongzhu_page(db, spoken="")
    assert "輪動進產業鏈" in html or "輪動進" in html
    assert "主產業" in html and "次產業" in html and "產業鏈" in html
    assert "細項" not in html
    assert "龍頭對照" in html or "此刻推薦" in html
    # 有股價／距高時寫查詢戳（種子頁有官方收日期）
    assert "查詢" in html
    assert "資金輪動要注意" not in html
    assert "佔比如實主判" not in html
    # 單日／近窗標籤：有佔比列才出；單元測已鎖格式
    assert "佔比如實" not in html


def test_dongzhu_button_failsoft_silent_snapshot_hook():
    """洞燭鈕送完後靜默落檔；失敗不擋話筒、對話不准講％。"""
    from pathlib import Path

    src = Path("bot_servers.py").read_text(encoding="utf-8")
    page_i = src.find("async def _send_dongzhu_page")
    page_end = src.find("\n    async def ", page_i + 10)
    body = src[page_i:page_end]
    assert "snapshot_dongzhu_picks" in body
    assert "asyncio.create_task" in body
    assert "讀佔比升降" in body
    assert "分層排次級" in body


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
    assert "_refresh_dongzhu_after_close" in runner
    assert "snapshot_and_score_dongzhu" in runner
    assert runner.find('if judged.get("skipped")') < runner.find(
        "snapshot_and_score_dongzhu"
    )
    assert "from dongzhu_tape import" not in money
    assert "匯入可能延遲" in runner
    assert "recompute_sector_flow" in runner
    assert runner.find("sync_all_fine_industry") < runner.find("recompute_sector_flow")
    assert runner.find("sync_all_fine_industry") < runner.find("record_dongzhu_flow")
    assert "from biaoke_" not in screen
    assert "from dongzhu_screen import rotation_screen_block" in screen


def test_dongzhu_judgment_waits_for_late_import(tmp_path, monkeypatch):
    db = str(tmp_path / "j.db")
    sqlite3.connect(db).close()
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20260916"
    )
    from dongzhu_judge import refresh_dongzhu_judgment

    out = refresh_dongzhu_judgment(db, "20260917")
    assert out.get("skipped") == "quotes_incomplete"
    assert out.get("want") == "20260917"
    assert out.get("complete") == "20260916"

    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20260917"
    )
    monkeypatch.setattr("biaoke_field_scan._chip_cap", lambda *_a, **_k: "")
    out2 = refresh_dongzhu_judgment(db, "20260917")
    assert out2.get("skipped") == "chips_incomplete"


def test_dongzhu_catches_test_laggards_without_stir_words(tmp_path, monkeypatch):
    """他只講 ASIC 是主戰場、沒說蠢蠢欲動；封測佔比已經最高 → 主推封測，捕捉距20高最深次級。"""
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
    lags = list(data.get("laggards") or [])
    sids = [x.get("sid") for x in lags]
    assert sids == ["2449", "3264"]
    assert "6257" not in sids
    assert "6515" not in sids and "6223" not in sids
    assert all(str(x.get("role") or "") == "次級" for x in lags)
    vs = [float(x["vs20"]) for x in lags]
    assert vs == sorted(vs)
    assert all(v <= -8.0 for v in vs)
    assert len(lags) <= 3
    rec_sids = [x.get("sid") for x in list(data.get("recs") or [])]
    assert rec_sids == sids
    html = dongzhu_page(db, spoken=spoken)
    assert "高階測試／封測" in html
    assert "此刻推薦" in html
    assert "這型最落後次級" in html
    assert "捕捉・同鏈比價落後" not in html
    assert "2449" in html and "京元電子" in html
    assert "3264" in html and "欣銓" in html
    assert "蠢蠢欲動" not in spoken
    empty = dongzhu_picks(db, spoken="")
    assert empty.get("field") == "高階測試／封測"


def test_chain_laggards_skip_loss_makers(tmp_path):
    """落後補漲要能做價／EPS：近季虧損不上捕捉。"""
    db = str(tmp_path / "loss.db")
    _seed(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE quarterly_income SET eps=? WHERE stock_id=?",
        (-0.45, "2449"),
    )
    conn.commit()
    conn.close()
    from biaoke_field_scan import _GROUPS, _PAGE_RULES, _chain_laggards
    from industry_brief import has_positive_eps

    assert has_positive_eps(db, "3264") is True
    assert has_positive_eps(db, "2449") is False
    assert has_positive_eps(db, "2429") is False
    g = next(x for x in _GROUPS if x["key"] == "test")
    sids = [x.get("sid") for x in _chain_laggards(db, g, "20260917", n=3)]
    assert "2449" not in sids
    assert "3264" in sids
    assert any("捕捉只收近季有賺" in x for x in _PAGE_RULES)


def test_dongzhu_window_is_100_chip_days():
    import biaoke_field_scan as m
    from biaoke_field_scan import FLOW_LOOKBACK, LAG_CAPTURE_N, PRE_VS20, SHARE_DAYS

    assert FLOW_LOOKBACK == 100
    assert SHARE_DAYS == 5
    assert PRE_VS20 == -8.0
    assert LAG_CAPTURE_N == 3
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
    assert "官方收" in html
    rec_sids = [x.get("sid") for x in list(data.get("recs") or [])]
    assert rec_sids
    assert "3228" not in rec_sids
    assert "3443" not in html
    assert "3228" not in html
    assert "不准發明切入" not in html
    assert "這型最落後次級" in html
    assert "次熱" in html
    assert "點圖下鈕選檔" in html
    assert "點左邊選" not in html
    assert html.count("點圖下鈕選檔") == 1


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
    assert "官方收" in html
    assert "流入第一名" in html


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
    assert "封測" in html
    assert "細項" not in html
    assert "判斷單位" not in html
    assert "沒打準" not in html
    assert "再打下一檔" not in html
    assert "整層電子" not in html
    assert data.get("verdict") in ("可留觀察", "可留", "還在")
    # 種子 OHLC 昨貼零今約 1.7%＝與查股同一條剛離零；可留才買
    assert data.get("leave_zero") is True
    assert data.get("buy") is (data.get("verdict") == "可留")
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


def test_dongzhu_hold_leave_zero_from_ohlc_not_bucket(tmp_path, monkeypatch):
    """洞燭 leave_zero 跟查股同一套官方柱；海選桶有無不准左右結論。"""
    db = str(tmp_path / "lz.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes ("
        "date TEXT, stock_id TEXT, stock_name TEXT, open REAL, high REAL, "
        "low REAL, close REAL, volume INTEGER, change_pct REAL, "
        "foreign_net INTEGER DEFAULT 0, trust_net INTEGER DEFAULT 0, "
        "dealer_net INTEGER DEFAULT 0)"
    )
    last = datetime(2026, 9, 17)
    for i in range(90):
        day = (last - timedelta(days=89 - i)).strftime("%Y%m%d")
        px = 101.0 if i == 89 else 100.0
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (day, "6257", "矽格", px, px, px, px, 5000, 0.0, 0, 0, 0),
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
    # 海選桶故意空／塞別檔，不准影響 leave_zero
    conn.execute(
        "CREATE TABLE screen_sessions ("
        "slot TEXT, as_of TEXT, stock_id TEXT, bucket TEXT, stock_name TEXT, "
        "close REAL, payload TEXT, PRIMARY KEY (slot, as_of, stock_id, bucket))"
    )
    conn.execute(
        "INSERT INTO screen_sessions VALUES (?,?,?,?,?,?,?)",
        ("morning", "20260917", "2330", "leave_zero", "台積電", 1000.0, "{}"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    monkeypatch.setattr("biaoke_field_scan._chip_cap", lambda *_a, **_k: "20260917")

    def _boom(*_a, **_k):
        raise AssertionError("dongzhu_hold 不准用海選桶判 leave_zero")

    monkeypatch.setattr("biaoke_field_scan._bucket_by_id", _boom)
    from biaoke_field_scan import _sid_leave_zero_official, dongzhu_hold

    assert _sid_leave_zero_official(db, "6257", "20260917") is True
    data = dongzhu_hold(db, "6257")
    assert data.get("leave_zero") is True


def test_rotation_notice_and_screen_block(tmp_path, monkeypatch):
    from biaoke_field_scan import ROTATION_NOTES, rotation_notice_lines, rotation_screen_block

    notes = rotation_notice_lines()
    blob = "".join(notes)
    assert notes == list(ROTATION_NOTES)
    assert "不是整層電子" in blob
    assert "人去樓空" in blob
    assert "停車格" in blob
    assert "黃金買點" in blob
    db = str(tmp_path / "f.db")
    _seed(db)
    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    monkeypatch.setattr(
        "biaoke_field_scan.dongzhu_picks",
        lambda *_a, **_k: {
            "field": "LCD / TFT面板",
            "pre_sign": "chase",
            "pre_ok": True,
            "pre_vs20": -18.5,
            "recs": [],
            "buys": [],
        },
    )
    html = rotation_screen_block(db)
    from tg_layout import DASH_LINE, _html_plain

    assert "LCD / TFT面板" in html
    assert "當天第一" in html
    assert "追了勝率較差" in html
    assert "進場只認剛離零" in html
    assert "此刻" not in html
    assert "不是整層電子" not in html
    assert "台股資金輪動" not in html
    assert "門檻" not in html
    assert "近100日" not in html
    assert "次級距20高" not in html
    assert "這型此刻沒有" not in html
    assert DASH_LINE not in html
    for ln in html.split("\n"):
        plain = _html_plain(ln)
        assert len(plain) <= 20, plain

    monkeypatch.setattr(
        "biaoke_field_scan.dongzhu_picks",
        lambda *_a, **_k: {
            "field": "封測",
            "pre_sign": "pre",
            "pre_ok": True,
            "pre_vs20": -12.0,
            "recs": [{"sid": "6257", "name": "矽格"}],
            "buys": [{"sid": "6257", "name": "矽格"}],
        },
    )
    pre_html = rotation_screen_block(db)
    assert "封測" in pre_html
    assert "先機" in pre_html
    assert "次級距20高 -12.0%" in pre_html
    assert "6257" in pre_html
    assert "門檻" not in pre_html
    assert "此刻" not in pre_html
    assert "不是整層電子" not in pre_html


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


def test_dongzhu_elec_pick_skips_shipping_plastic_build():
    from biaoke_field_scan import _is_elec_pick

    assert _is_elec_pick({"_layers": ("電子上游", "IC", "封測")})
    assert _is_elec_pick({"_layers": ("電子下游", "電信服務")})
    assert _is_elec_pick({"_layers": ("電子上游", "IP/ASIC")})
    assert not _is_elec_pick({"_layers": ("傳產", "塑膠")})
    assert not _is_elec_pick({"_layers": ("傳產", "航運")})
    assert not _is_elec_pick({"_layers": ("傳產", "營建")})
    assert not _is_elec_pick({"_layers": ("金融", "金控")})


def test_dongzhu_taught_elec_excludes_shipping_plastic_telecom():
    from biaoke_field_scan import _is_taught_elec

    assert _is_taught_elec({"_layers": ("電子上游", "IP/ASIC")})
    assert _is_taught_elec({"_layers": ("電子上游", "PCB", "製造")})
    assert _is_taught_elec({"_layers": ("電子上游", "IC", "封測")})
    assert not _is_taught_elec({"_layers": ("傳產", "航運")})
    assert not _is_taught_elec({"_layers": ("傳產", "塑膠")})
    assert not _is_taught_elec({"_layers": ("電子下游", "電信服務")})
    assert not _is_taught_elec({"_layers": ("電子下游", "筆記型電腦")})


def test_dongzhu_chain_bucket_maps_asic_ship_chem_not_defense():
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
    from dongzhu_precursor import MISSING_BUCKETS, chain_bucket, is_elec_chain

    assert chain_bucket("電子上游-IP/ASIC") == "asic"
    assert chain_bucket("傳產-航運") == "ship"
    assert chain_bucket("傳產-塑膠") == "chem"
    assert chain_bucket("傳產-化學工業") == "chem"
    assert chain_bucket("電子下游-電信服務") == "tel"
    assert chain_bucket("傳產-營建") == "build"
    assert chain_bucket("電子中游-散熱零組件") == "cool"
    assert chain_bucket("電子上游-記憶體製造") == "mem"
    assert chain_bucket("傳產-電機") == ""
    assert chain_bucket("電子下游-消費電子") == ""
    assert is_elec_chain("電子下游-電信服務")
    assert not is_elec_chain("傳產-航運")
    assert any("軍工" in x and "不發明" in x for x in MISSING_BUCKETS)


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
    assert "停車格" in html or "金控／銀行當停車格" in str(data.get("why") or "")
    assert "他教過怎麼找" not in html
    assert "資金輪動要注意" not in html
    assert "金控／銀行當停車格" in html or "略過" in html or "不拿來當先機" in str(
        data.get("why") or ""
    )


def test_optical_tier_insight_inp_vs_connect():
    """觸類旁通：點到光通訊／InP → 展開整組教過成員，不是只記點名。"""
    from biaoke_field_scan import optical_tier_insight
    from industry_fine import TAUGHT_GROUPS

    spoken = (
        "目前主流是InP，不是CPO。"
        "InP：聯亞、全新、IET、穩懋。"
        "上詮更弱，建議專注聯亞、全新。"
    )
    hit = optical_tier_insight(spoken, db_path="")
    assert hit.get("ok") is True
    lines = " ".join(hit.get("lines") or [])
    assert "InP" in lines
    assert "黃金買點" in lines or "整組展開" in lines
    assert "整組展開" in lines
    roster = hit.get("roster") or []
    taught = set(TAUGHT_GROUPS.get("光通訊") or ())
    assert taught
    assert {str(r.get("sid")) for r in roster} >= taught
    assert any(x.get("name") == "聯亞" for x in (hit.get("inp") or []))
    assert any(x.get("name") == "上詮" for x in (hit.get("connect") or []))
    # 只講「光通訊」沒點名個股 → 仍展開整組
    bare = optical_tier_insight("光通訊這兩天要注意", db_path="")
    assert bare.get("ok") is True
    assert len(bare.get("roster") or []) >= len(taught)


def test_optical_tier_insight_judges_bars(tmp_path):
    """整組展開後用官方柱判 InP 層是否強過連接側。"""
    from biaoke_field_scan import optical_tier_insight

    db = str(tmp_path / "opt.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    # 6 根：近5日％＝(last/first-1)*100；InP 強、連接弱
    series = {
        "3081": [100, 102, 105, 108, 110, 120],  # 聯亞 +20%
        "2455": [100, 101, 103, 106, 108, 115],  # 全新 +15%
        "4971": [100, 100, 101, 102, 104, 110],  # IET +10%
        "3105": [100, 100, 101, 102, 103, 108],  # 穩懋 +8%
        "4991": [100, 100, 100, 101, 102, 105],  # 環宇 +5%
        "3363": [100, 99, 98, 97, 96, 90],  # 上詮 -10%
        "3163": [100, 99, 98, 97, 96, 92],  # 波若威 -8%
        "6442": [100, 99, 98, 97, 95, 93],  # 光聖 -7%
        "3234": [100, 100, 100, 100, 100, 101],
        "4979": [100, 100, 100, 100, 100, 100],
        "4977": [100, 100, 100, 100, 100, 99],
        "3450": [100, 100, 100, 100, 100, 100],
    }
    base = datetime(2026, 9, 20)
    for sid, closes in series.items():
        name = {
            "3081": "聯亞",
            "2455": "全新",
            "3363": "上詮",
        }.get(sid, sid)
        for i, c in enumerate(closes):
            day = (base + timedelta(days=i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
                (day, sid, name, c, c, c, c, 1000, 0.0),
            )
    conn.commit()
    conn.close()
    hit = optical_tier_insight(
        "光通訊主流是InP不是CPO，聯亞、全新先看。上詮更弱。",
        db_path=db,
    )
    assert hit.get("ok") is True
    assert hit.get("inp_avg_5d") is not None
    assert hit.get("connect_avg_5d") is not None
    assert float(hit["inp_avg_5d"]) > float(hit["connect_avg_5d"]) + 1.0
    blob = " ".join(hit.get("lines") or [])
    assert "印證主流InP" in blob or "InP 均" in blob
    assert "整組展開" in blob


def test_spoken_field_roster_judge_cooling(tmp_path):
    """點到散熱 → 展開教過成員股＋近5日柱強弱。"""
    from biaoke_field_scan import spoken_field_roster_judge

    db = str(tmp_path / "cool.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    series = {
        "3653": [100, 102, 104, 106, 108, 120],  # 健策強
        "3017": [100, 100, 101, 102, 103, 105],  # 奇鋐
        "3324": [100, 99, 98, 97, 96, 90],  # 雙鴻弱
        "6933": [100, 100, 100, 100, 100, 100],
    }
    base = datetime(2026, 9, 20)
    for sid, closes in series.items():
        for i, c in enumerate(closes):
            day = (base + timedelta(days=i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, c, c, c, c, 1000, 0.0),
            )
    conn.commit()
    conn.close()
    hit = spoken_field_roster_judge("真正主流為ASIC、散熱、光通訊", db_path=db)
    assert hit.get("ok") is True
    cool = (hit.get("fields") or {}).get("散熱") or {}
    assert cool.get("ok") is True
    assert len(cool.get("members") or []) >= 3
    blob = " ".join(hit.get("lines") or [])
    assert "散熱整組" in blob
    assert "類股展開對質" in blob


def test_asic_ic_peer_insight_from_week_speech(tmp_path):
    """炒ASIC不是其他IC設計 → 錨定台積／創意／聯發，展開相關IC設計對位階連動。"""
    from biaoke_field_scan import asic_ic_peer_insight

    db = str(tmp_path / "asic.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.execute(
        "CREATE TABLE stock_fine_industry (stock_id TEXT PRIMARY KEY, chain TEXT)"
    )
    for sid, chain in (
        ("2330", "電子上游-IC-代工"),
        ("3443", "電子上游-IP/ASIC"),
        ("2454", "電子上游-IC-設計"),
        ("3035", "電子上游-IP/ASIC"),
        ("3661", "電子上游-IP/ASIC"),
        ("4966", "電子上游-IC-設計"),
        ("6531", "電子上游-記憶體IC設計"),
    ):
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?)", (sid, chain)
        )
    # 21+ 根：錨定偏強；智原落後有空間；譜瑞跟漲
    base = datetime(2026, 8, 20)
    series = {
        "2330": [100 + i * 0.3 for i in range(25)],
        "3443": [100 + i * 0.8 for i in range(25)],
        "2454": [100 + i * 0.5 for i in range(25)],
        "3035": [100 + (0.1 if i < 20 else 0.05) * i for i in range(25)],  # 弱
        "3661": [100 + i * 0.7 for i in range(25)],
        "4966": [100 + i * 0.55 for i in range(25)],
        "6531": [100 + i * 0.2 for i in range(25)],
    }
    # 製造距20高：智原最後收在低位
    series["3035"] = [120] * 20 + [100, 101, 102, 103, 104]
    for sid, closes in series.items():
        for i, c in enumerate(closes):
            day = (base + timedelta(days=i)).strftime("%Y%m%d")
            h = max(c, closes[max(0, i - 1)]) * 1.01
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, c, h, c * 0.99, c, 2000, 0.0),
            )
    conn.commit()
    conn.close()
    spoken = (
        "目前市場主力是在炒ASIC而不是其他IC設計股或IP股要搞清楚。"
        "二軍IC設計要找ASIC、台積電、創意、聯發科相關的IC設計。"
        "愛普應該和記憶體相關不是主流。"
    )
    hit = asic_ic_peer_insight(spoken, db_path=db)
    assert hit.get("ok") is True
    blob = " ".join(hit.get("lines") or [])
    assert "台積電" in blob and "創意" in blob and "聯發科" in blob
    assert "記憶體" in blob or "愛普" in blob
    peers = hit.get("peers") or []
    assert any(p.get("sid") == "3035" for p in peers)
    assert not any(p.get("sid") == "6531" for p in peers)  # 記憶體排除主流池
    assert any("黃金買點" in x for x in (hit.get("lines") or []))


def test_recent_spoken_range_falls_back(tmp_path):
    """本自然週沒文 → 用庫內最新主文往回一週，才能推論。"""
    from biaoke_field_scan import recent_spoken_range, week_spoken, biaoke_week_link
    from zoneinfo import ZoneInfo

    db = str(tmp_path / "fb.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE biaoke_posts (id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, "
        "kind TEXT, tags TEXT, text TEXT, parent TEXT DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?)",
        (
            "p1",
            1,
            "2026-09-23",
            "08:39",
            "post",
            "[]",
            "目前台股最強主流是ASIC，創意、聯發科都有效突破。炒ASIC而不是其他IC設計。",
            "",
        ),
    )
    conn.commit()
    conn.close()
    now = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    a, b = recent_spoken_range(db, now=now)
    assert b == "2026-09-23"
    assert a <= b
    spoken = week_spoken(db, now=now)
    assert "ASIC" in spoken
    ref = biaoke_week_link(db, now=now)
    assert ref.get("ok") is True
    assert any("ASIC" in x or "引領" in x for x in (ref.get("lines") or []))


def test_record_spoken_field_expand_from_reply_thread(tmp_path):
    """樓中樓只講『上詮更弱』→ 拼父文光通訊 → 整組展開並凍 live_judge。"""
    from biaoke_field_scan import record_spoken_field_expand, spoken_blob_from_events
    from industry_fine import TAUGHT_GROUPS

    db = str(tmp_path / "thread.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.execute(
        "CREATE TABLE biaoke_posts (id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, "
        "kind TEXT, tags TEXT, text TEXT, parent TEXT DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?)",
        (
            "p1",
            1,
            "2026-10-02",
            "10:00",
            "post",
            "[]",
            "光通訊主流是InP不是CPO，聯亞、全新先看。",
            "",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?)",
        (
            "p1:c1",
            2,
            "2026-10-02",
            "11:00",
            "reply",
            "[]",
            "上詮更弱，專注聯亞、全新。",
            "p1",
        ),
    )
    # 最少柱：聯亞／上詮各 6 根
    base = datetime(2026, 9, 20)
    for sid, closes in (
        ("3081", [100, 102, 105, 108, 110, 120]),
        ("3363", [100, 99, 98, 97, 96, 90]),
        ("2455", [100, 101, 102, 103, 104, 110]),
    ):
        for i, c in enumerate(closes):
            day = (base + timedelta(days=i)).strftime("%Y%m%d")
            conn.execute(
                "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, c, c, c, c, 1000, 0.0),
            )
    conn.commit()
    conn.close()

    events = [
        {
            "id": "p1:c1",
            "kind": "reply",
            "parent": "p1",
            "text": "上詮更弱，專注聯亞、全新。",
            "reply_to_text": "",
        }
    ]
    blob = spoken_blob_from_events(events, db)
    assert "光通訊" in blob or "InP" in blob
    assert "上詮更弱" in blob
    hit = record_spoken_field_expand(db, events, as_of="20260925")
    assert hit.get("ok") is True
    assert len((hit.get("optical") or {}).get("roster") or []) >= len(
        TAUGHT_GROUPS.get("光通訊") or ()
    )
    assert any("整組展開" in x for x in (hit.get("lines") or []))
    # live_judge 有凍（同庫或旁路 store）
    assert int(hit.get("n") or 0) >= 1 or any(
        (r.get("chg5") is not None)
        for r in ((hit.get("optical") or {}).get("roster") or [])
    )


def test_biaoke_week_link_on_dongzhu_page(tmp_path, monkeypatch):
    """本週飆大聯動上洞燭頁：只參考，不改佔比主判／不准當買訊。"""
    from biaoke_field_scan import (
        biaoke_week_link,
        clear_dongzhu_picks_cache,
        dongzhu_page,
        dongzhu_picks,
        week_range_taipei,
        week_spoken,
    )

    db = str(tmp_path / "week.db")
    _seed(db)
    conn = sqlite3.connect(db)
    # 本週（相對固定假日 2026-10-03 週六→週一 09-28）
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?)",
        (
            "185072783",
            2,
            "2026-10-02",
            "10:28",
            "post",
            '["創意","健策","聯亞","台光電"]',
            "大盤在過9/22 48601的最後整理，而且已經有完成6/23 48218回測的跡象。"
            "真正主流為ASIC、散熱、光通訊、CCL。觀察創意、健策。IET 二軍漲停。"
            "光通訊主流是InP不是CPO，聯亞、全新先看。",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?)",
        (
            "185072783:c1",
            3,
            "2026-10-03",
            "09:42",
            "reply",
            "[]",
            "南亞科站穩531就是整理完成。奇鋐還在關前。上詮更弱，專注聯亞、全新。",
        ),
    )
    # parent 欄：_seed 表沒 parent；補欄以免 week_spoken 查 reply parent 失敗
    cols = [r[1] for r in conn.execute("PRAGMA table_info(biaoke_posts)").fetchall()]
    if "parent" not in cols:
        conn.execute("ALTER TABLE biaoke_posts ADD COLUMN parent TEXT DEFAULT ''")
    conn.execute(
        "UPDATE biaoke_posts SET parent='185072783' WHERE id='185072783:c1'"
    )
    conn.commit()
    conn.close()

    clear_dongzhu_picks_cache()
    start, end = week_range_taipei(datetime(2026, 10, 3, 12, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Taipei")))
    assert start == "2026-09-28"
    assert end == "2026-10-03"
    spoken = week_spoken(db, start=start, end=end)
    assert "48601" in spoken
    assert "南亞科" in spoken
    ref = biaoke_week_link(db, start=start, end=end)
    assert ref.get("ok") is True
    assert ref.get("mains") >= 1
    assert ref.get("replies") >= 1
    assert "ASIC" in (ref.get("fields") or []) or "散熱" in (ref.get("fields") or [])
    assert any("切入只認黃金買點" in x for x in (ref.get("lines") or []))
    assert any("InP" in x for x in (ref.get("lines") or []))
    assert any("整組展開" in x for x in (ref.get("lines") or []))
    assert isinstance(ref.get("optical"), dict)
    assert isinstance(ref.get("field_expand"), dict)
    assert len((ref.get("optical") or {}).get("roster") or []) >= 8

    monkeypatch.setattr("biaoke_field_scan._cap", lambda *_a, **_k: "20260917")
    monkeypatch.setattr(
        "biaoke_field_scan.week_range_taipei",
        lambda now=None: ("2026-09-28", "2026-10-03"),
    )
    clear_dongzhu_picks_cache()
    data = dongzhu_picks(db, spoken="")
    # spoken="" 時主判不吃本週正文；聯動層仍附加
    assert isinstance(data.get("biaoke_week"), dict)
    assert data["biaoke_week"].get("ok") is True
    html = dongzhu_page(db, spoken="", data=data)
    assert "近窗飆大聯想（引領找股）" in html or "本週飆大聯動" in html
    assert "不是買訊" in html or "切入只認黃金買點" in html
    # 推薦買點邏輯未被本週聯動改成亂標
    assert "不准發明切入" not in html
