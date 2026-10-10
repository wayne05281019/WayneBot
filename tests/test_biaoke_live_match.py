# -*- coding: utf-8 -*-
"""近窗說法＋官方柱對質 → 可點／勿追／標配（預設自動化）。"""
from __future__ import annotations

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
        CREATE TABLE biaoke_posts(
            id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT,
            kind TEXT DEFAULT 'post', parent TEXT DEFAULT ''
        );
        CREATE TABLE screen_picks(
            as_of TEXT, bucket TEXT, stock_id TEXT, stock_name TEXT,
            pick_close REAL, PRIMARY KEY(as_of, bucket, stock_id)
        );
        """
    )
    body = (
        "「光通訊 InP 不在前波高點的個股」這句話好好去研究，"
        "就是空手不要再介入全新及穩懋，要去找低位階還在底部的 InP，"
        "當然聯亞是標配一股不賣。"
    )
    # 主文＋自回：week_spoken 要有非 reply 根才串樓中樓
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        (
            "p-root",
            "2026-10-08",
            "10:00:00",
            "光通訊 InP 仍是主流，位階各自看。",
            "post",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind,parent) VALUES(?,?,?,?,?,?)",
        ("p-inp", "2026-10-08", "13:42:00", body, "reply", "p-root"),
    )
    # 官方柱：環宇／IET 離峰深；全新／穩懋近高；聯亞中離峰（標配不進去找）
    from datetime import date, timedelta

    names = {
        "4991": "環宇-KY",
        "4971": "IET-KY",
        "3081": "聯亞",
        "2455": "全新",
        "3105": "穩懋",
    }
    # peak_day, peak_high, last_close；低檔區間讓 pos120 偏低
    specs = {
        "4991": ("20260525", 900.0, 511.0, 0.45),
        "4971": ("20260422", 955.0, 596.0, 0.50),
        "3081": ("20260901", 3600.0, 2960.0, 0.80),
        "2455": ("20261006", 613.0, 558.0, 0.90),
        "3105": ("20260421", 634.0, 581.0, 0.90),
    }
    for sid, (peak_day, peak_h, last_c, base_ratio) in specs.items():
        # 涵蓋 1/2～10/08，確保 as-of／峰日都寫進
        for d in range(0, 280):
            day_s = (date(2026, 1, 2) + timedelta(days=d)).strftime("%Y%m%d")
            if day_s > "20261008":
                break
            if day_s == peak_day:
                h, lo, c = peak_h, peak_h * 0.92, peak_h * 0.96
            elif day_s == "20261008":
                h, lo, c = last_c * 1.01, last_c * 0.99, last_c
            else:
                c = last_c * float(base_ratio)
                h, lo = c * 1.02, c * 0.98
            conn.execute(
                "INSERT OR REPLACE INTO daily_quotes"
                "(date,stock_id,stock_name,market,open,high,low,close,volume) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (day_s, sid, names[sid], "TW", c, h, lo, c, 1000),
            )
    conn.commit()
    conn.close()
    return db


def test_parse_no_chase_hold_find():
    from biaoke_live_match import parse_spoken_stances

    blob = (
        "空手不要再介入全新及穩懋，要去找低位階還在底部的 InP，"
        "聯亞是標配一股不賣。"
    )
    st = parse_spoken_stances(blob)
    assert "2455" in st["no_chase"]
    assert "3105" in st["no_chase"]
    assert "3081" in st["hold"]
    assert "inp" in st["find_pools"]


def test_live_match_ranks_huan_yu_iet(tmp_path):
    from biaoke_live_match import live_match_pack, refresh_live_match

    db = _mk_db(tmp_path)
    pack = live_match_pack(db)
    assert pack["ok"]
    assert "2455" in pack["no_chase"] and "3105" in pack["no_chase"]
    assert "3081" in pack["hold"]
    sids = [r["sid"] for r in pack["matches"]]
    assert "4991" in sids
    assert "4971" in sids
    assert "2455" not in sids
    assert "3105" not in sids
    # 環宇離峰應排在前
    assert sids[0] == "4991"
    refreshed = refresh_live_match(db)
    assert refreshed.get("matches")
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT payload FROM biaoke_live_match WHERE key='latest'"
    ).fetchone()
    conn.close()
    assert row and "4991" in row[0]


def test_advice_html_strips_no_chase_links_keeps_group(tmp_path):
    """勿追拿掉藍字，但 InP 族名仍在；對質符合可點環宇／IET；聯亞標配。"""
    from biaoke_advisor import (
        advice_chart_targets,
        format_action_advice_html,
        sids_mentioned_in_advice_html,
    )

    db = _mk_db(tmp_path)
    # 近窗還要有光通訊／InP 旗標（雙箭頭或 InP）— 已在 reply 正文
    html = format_action_advice_html(db, ask="")
    assert "InP（磷化銦）" in html or "對質符合" in html
    # 全新／穩懋：可出現純文字，但不准奇摩可點
    assert "quote/2455." not in html
    assert "quote/3105." not in html
    assert "全新" in html and "穩懋" in html
    assert "位階偏高" in html or "勿追" in html or "不要介入" in html or "空手勿追" in html
    # 環宇／IET 必須可點
    assert "quote/4991." in html
    assert "quote/4971." in html
    assert "對質符合" in html
    # 聯亞可留連結＋標配
    assert "quote/3081." in html
    assert "標配不賣" in html
    assert "不是買訊" in html or "不准當進場" in html
    # 可點出圖名單：含對質檔、不含勿追
    targets = advice_chart_targets(db, ask="", spoken_html=html)
    t_sids = {str(t.get("sid")) for t in targets}
    assert "4991" in t_sids and "4971" in t_sids
    assert "2455" not in t_sids and "3105" not in t_sids
    linked = set(sids_mentioned_in_advice_html(html))
    assert "2455" not in linked and "3105" not in linked
    assert "4991" in linked and "4971" in linked


def test_digest_refresh_calls_live_match(tmp_path, monkeypatch):
    """按飆大彙整路徑會 refresh（預設自動化）。"""
    from biaoke_digest import format_focus_oral

    called = {"n": 0}

    def _fake_refresh(db_path, spoken=""):
        called["n"] += 1
        return {"ok": True, "matches": []}

    monkeypatch.setattr("biaoke_live_match.refresh_live_match", _fake_refresh)
    db = _mk_db(tmp_path)
    html = format_focus_oral(
        [{"date": "2026-10-08", "time": "13:42", "text": "InP 低位階好好去研究"}],
        [],
        db_path=db,
    )
    assert called["n"] >= 1
    assert "飆大現在在講" in html
