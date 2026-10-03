# -*- coding: utf-8 -*-
"""智囊團活用：跨庫查閱＋為什麼／可買分層，不准當答錄機。"""
import sqlite3
from pathlib import Path


def _mk_db(tmp_path: Path) -> str:
    db = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY(date, stock_id)
        );
        CREATE TABLE index_daily(
            date TEXT, symbol TEXT DEFAULT 'TWII', close REAL,
            high REAL, low REAL, volume REAL, pct_change REAL,
            PRIMARY KEY(date, symbol)
        );
        CREATE TABLE biaoke_posts(
            id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT,
            kind TEXT DEFAULT 'post', parent TEXT DEFAULT ''
        );
        CREATE TABLE screen_picks(
            as_of TEXT, bucket TEXT, stock_id TEXT, stock_name TEXT,
            pick_close REAL, next_date TEXT, next_close REAL,
            next_pct REAL, entry_stars INTEGER,
            PRIMARY KEY(as_of, bucket, stock_id)
        );
        CREATE TABLE dongzhu_flow_tape(
            date TEXT, group_key TEXT, field TEXT, three_net REAL,
            member_n INTEGER, pos_member INTEGER, market_in REAL,
            market_out REAL, share_pct REAL, share_chg REAL, fine_tag TEXT
        );
        """
    )
    # 近窗雙箭頭＋浪五改口
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        (
            "p1",
            "2026-10-03",
            "10:00:00",
            "修正 波浪位階四完成，開始走五的時候，波浪位階五的位階，"
            "已經可以完全看出來，只是波浪五要走五段，還是走九段！"
            "我記得剛回來就一直強調光通訊，尤其是InP是台股各族群第一最強主流，"
            "現在我稍微改變，由於ASIC創意的創先過歷史高點，"
            "我現在改為ASIC及光通訊（尤其是InP)為台股到農曆年前台股走完這波行情兩大最強雙箭頭。"
            "量價結構，只能看到股票的主力籌碼意圖，長期的大盤規劃，只有波浪理論才可以辨識。",
            "post",
        ),
    )
    conn.execute(
        "INSERT INTO index_daily(date,symbol,close,high,low) VALUES(?,?,?,?,?)",
        ("20261002", "TWII", 27500.0, 27600.0, 27400.0),
    )
    conn.execute(
        "INSERT INTO dongzhu_flow_tape(date,group_key,field,share_pct,share_chg,fine_tag) "
        "VALUES(?,?,?,?,?,?)",
        ("20261002", "asic", "ASIC", 12.5, 1.2, "IP/ASIC"),
    )
    conn.execute(
        "INSERT INTO screen_picks(as_of,bucket,stock_id,stock_name,pick_close) "
        "VALUES(?,?,?,?,?)",
        ("20261002", "leave_zero", "3081", "聯亞", 200.0),
    )
    conn.execute(
        "INSERT INTO screen_picks(as_of,bucket,stock_id,stock_name,pick_close) "
        "VALUES(?,?,?,?,?)",
        ("20261002", "golden_buy", "2455", "全新", 150.0),
    )
    for sid, base in (("3081", 180.0), ("2455", 140.0), ("4971", 90.0), ("3443", 3000.0)):
        for d in range(1, 26):
            day = f"202609{d:02d}"
            c = base * (1 + 0.002 * d)
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, "TW", c, c * 1.01, c * 0.99, c, 1000 + d * 10),
            )
    conn.commit()
    conn.close()
    # evolve live_judge
    evo = str(tmp_path / "wayne_evolve.db")
    econn = sqlite3.connect(evo)
    econn.execute(
        """
        CREATE TABLE live_judge(
            as_of TEXT, kind TEXT, pick TEXT, sid TEXT, name TEXT,
            px REAL, profit REAL, extra TEXT, ran_at TEXT,
            PRIMARY KEY(as_of, kind, pick, sid)
        )
        """
    )
    econn.execute(
        "INSERT INTO live_judge(as_of,kind,pick,sid,name,px,extra,ran_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            "20261002",
            "biaoke_field",
            "expand",
            "3081",
            "聯亞",
            200.0,
            "{}",
            "2026-10-03T12:00:00",
        ),
    )
    econn.commit()
    econn.close()
    return db


def test_advisor_pack_dual_wave_and_cross(tmp_path):
    from biaoke_advisor import advisor_pack, format_advisor_html

    db = _mk_db(tmp_path)
    pack = advisor_pack(db, ask="InP哪些可以買")
    assert pack.get("ok")
    blob = "\n".join(pack.get("lines") or [])
    assert "雙箭頭" in blob or "ASIC" in blob
    assert "五段" in blob or "九段" in blob or "波浪" in blob
    assert "跨庫" in blob or "智囊團活用" in blob
    # 不准只堆日期目錄
    assert "2026-09-01" not in blob or "判斷" in blob
    html = format_advisor_html(db, "InP哪些可以買")
    assert "智囊團活用" in html
    assert "答錄機" not in html or "不是答錄機" in html


def test_cross_db_glance_reads_evolve(tmp_path):
    from biaoke_advisor import cross_db_glance

    db = _mk_db(tmp_path)
    hit = cross_db_glance(db, "聯亞", sids=["3081"])
    assert hit.get("ok")
    lines = "\n".join(hit.get("lines") or [])
    assert "加權" in lines or "佔比" in lines or "evolve" in lines or "剛脫離零" in lines


def test_advisor_live_notes_mentions_cross_db(tmp_path):
    from biaoke_advisor import advisor_live_notes

    db = _mk_db(tmp_path)
    notes = advisor_live_notes(db, "大盤波浪")
    assert "判斷｜" in notes
    assert "主庫" in notes or "evolve" in notes
    assert "答錄機" in notes


def test_focus_oral_includes_advisor(tmp_path):
    from biaoke_digest import format_focus_oral

    db = _mk_db(tmp_path)
    mains = [
        {
            "date": "2026-10-03",
            "time": "10:00:00",
            "text": "ASIC及光通訊尤其是InP為台股到農曆年前兩大最強雙箭頭。波浪位階四完成開始走五。",
            "kind": "post",
        }
    ]
    html = format_focus_oral(mains, [], db_path=db)
    assert "脈絡黃金" in html or "智囊團活用" in html
    assert "雙箭頭" in html or "波浪" in html or "ASIC" in html
    assert "不是買訊" not in html


def test_reweave_gold_from_four_months(tmp_path):
    from biaoke_reweave import reweave_gold, record_reweave

    db = _mk_db(tmp_path)
    pack = reweave_gold(db, force=True)
    assert pack.get("ok")
    blob = "\n".join(pack.get("lines") or [])
    assert "黃金" in blob or "脈絡" in blob
    assert "答錄機" in blob or "活人" in blob or "活化" in blob
    assert "不是買訊" not in blob
    hit = record_reweave(db, [])
    assert hit.get("ok")


def test_advisor_html_no_buy_disclaimer(tmp_path):
    from biaoke_advisor import format_advisor_html

    db = _mk_db(tmp_path)
    html = format_advisor_html(db, "InP哪些可以買")
    assert "不是買訊" not in html
    assert "非買訊" not in html


def test_advice_never_pushes_retired_drone(tmp_path):
    """近窗沒講無人機，不准建議中光電／雷虎。"""
    import sqlite3
    from biaoke_advisor import action_advice_pack, advice_chart_targets, advice_sid_blocked

    db = _mk_db(tmp_path)
    conn = sqlite3.connect(db)
    # 舊文有無人機，近窗（今天）沒有
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        (
            "old-drone",
            "2025-09-05",
            "10:00:00",
            "無人機族群長榮航、中光電、事欣科不要再碰。亞航、雷虎風險大。",
            "post",
        ),
    )
    conn.commit()
    conn.close()
    assert advice_sid_blocked(db, "5371") is True
    assert advice_sid_blocked(db, "8033") is True
    pack = action_advice_pack(db, ask="怎麼做")
    sids = {str(r.get("sid")) for r in (pack.get("do_now") or []) + (pack.get("wait") or []) + (pack.get("skip") or [])}
    assert "5371" not in sids
    assert "8033" not in sids
    targets = advice_chart_targets(db, ask="光通訊")
    assert not any(str(t.get("sid")) in {"5371", "8033", "4916"} for t in targets)
    blob = "\n".join(pack.get("lines") or [])
    assert "中光電" not in blob
    assert "雷虎" not in blob


def test_field_advice_charts_give_all_with_how(tmp_path):
    from biaoke_advisor import (
        action_advice_pack,
        advice_chart_targets,
        is_field_advice_ask,
    )

    db = _mk_db(tmp_path)
    assert is_field_advice_ask("InP哪些可以買")
    assert is_field_advice_ask("")
    assert not is_field_advice_ask("3081")
    assert not is_field_advice_ask("聯亞")
    pack = action_advice_pack(db, ask="光通訊 InP")
    assert pack.get("ok")
    blob = "\n".join(pack.get("lines") or [])
    assert "該怎麼做" in blob or "建議怎麼做" in blob
    assert "憑：" in blob or "官方" in blob
    targets = advice_chart_targets(db, ask="InP")
    # 不截 2～3：名冊該給的都進清單
    n_rows = len(pack.get("do_now") or []) + len(pack.get("wait") or []) + len(
        pack.get("skip") or []
    )
    assert len(targets) == n_rows
    assert all(t.get("do") and t.get("how") for t in targets)


def test_intro_asic_then_optical_yahoo_layout(tmp_path):
    """空白／類股：先 ASIC 三龍頭＋相關鏈，再 InP／FAU／CPO，股名連奇摩。"""
    from biaoke_advisor import action_advice_pack, format_action_advice_html

    db = _mk_db(tmp_path)
    # 補 ASIC 相關鏈柱，讓名冊分層有官方數
    conn = __import__("sqlite3").connect(db)
    for sid, base in (
        ("2454", 1200.0),
        ("3661", 4000.0),
        ("3035", 400.0),
        ("6526", 600.0),
        ("8227", 80.0),
        ("3363", 650.0),
        ("3008", 6000.0),
    ):
        for d in range(1, 26):
            day = f"202609{d:02d}"
            c = base * (1 + 0.001 * d)
            conn.execute(
                "INSERT OR IGNORE INTO daily_quotes"
                "(date,stock_id,stock_name,market,open,high,low,close,volume) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (day, sid, sid, "TW", c, c * 1.01, c * 0.99, c, 1000),
            )
    conn.commit()
    conn.close()

    pack = action_advice_pack(db, ask="")
    assert pack.get("ok")
    live = pack.get("live") or {}
    assert live.get("asic")
    assert live.get("opt")
    leader_sids = {str(r.get("sid")) for r in (pack.get("asic_leaders") or [])}
    related_sids = {str(r.get("sid")) for r in (pack.get("asic_related") or [])}
    assert "3443" in leader_sids  # 創意
    assert "2454" in leader_sids  # 聯發科
    assert "3661" in leader_sids  # 世芯
    assert "3035" in related_sids  # 智原＝相關鏈
    assert "6526" in related_sids  # 達發＝聯發科子公司
    assert "8227" in related_sids  # 巨有科技＝IP/ASIC 同鏈
    assert pack.get("inp_rows")
    assert pack.get("fau_rows")
    assert pack.get("cpo_rows")

    html = format_action_advice_html(db, ask="")
    assert "ASIC｜到年前主軸" in html
    assert "三龍頭" in html
    assert "相關鏈" in html
    assert "光通訊｜InP／FAU／CPO" in html
    assert "InP　" in html
    assert "FAU　" in html
    assert "CPO　" in html
    assert "該怎麼做" in html
    assert "tw.stock.yahoo.com/quote/" in html
    assert "3443" in html and "8227" in html and "6526" in html
    assert "不是買訊" not in html


def test_intro_skips_fields_not_spoken_in_near_window(tmp_path):
    """近窗 14 日沒再講的族群不准建議。"""
    import sqlite3
    from biaoke_advisor import action_advice_pack, format_action_advice_html

    db = _mk_db(tmp_path)
    conn = sqlite3.connect(db)
    # 清掉雙箭頭近窗，只留無關句
    conn.execute("DELETE FROM biaoke_posts")
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        ("p-mem", "2026-10-03", "10:00:00", "南亞科量價變好，記憶體製造先看。", "post"),
    )
    conn.commit()
    conn.close()
    pack = action_advice_pack(db, ask="")
    live = pack.get("live") or {}
    assert not live.get("asic")
    assert not live.get("opt")
    html = format_action_advice_html(db, ask="")
    assert "ASIC｜" not in html
    assert "光通訊｜" not in html
    assert "8227" not in html
