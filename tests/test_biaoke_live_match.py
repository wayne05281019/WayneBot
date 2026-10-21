# -*- coding: utf-8 -*-
"""近窗說法＋官方柱對質 → 可點／勿追／標配（預設自動化）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _mk_db(tmp_path: Path) -> str:
    """近窗說法＋柱要以台北「今天」為準，不准寫死日（14 日窗一過就紅）。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

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
    # as_of＝台北昨；對齊原 fixture 相對峰日（相對 2026-10-08）
    as_of_dt = datetime.now(ZoneInfo("Asia/Taipei")).date() - timedelta(days=1)
    as_of = as_of_dt.strftime("%Y%m%d")
    post_date = as_of_dt.strftime("%Y-%m-%d")
    # 主文＋自回：week_spoken 要有非 reply 根才串樓中樓
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        (
            "p-root",
            post_date,
            "10:00:00",
            "光通訊 InP 仍是主流，位階各自看。",
            "post",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind,parent) VALUES(?,?,?,?,?,?)",
        ("p-inp", post_date, "13:42:00", body, "reply", "p-root"),
    )
    # 官方柱：環宇／IET 離峰深；全新／穩懋近高；聯亞中離峰（標配不進去找）
    names = {
        "4991": "環宇-KY",
        "4971": "IET-KY",
        "3081": "聯亞",
        "2455": "全新",
        "3105": "穩懋",
    }
    # (days_before_as_of, peak_high, last_close, base_ratio)
    specs = {
        "4991": (136, 900.0, 511.0, 0.45),
        "4971": (169, 955.0, 596.0, 0.50),
        "3081": (37, 3600.0, 2960.0, 0.80),
        "2455": (2, 613.0, 558.0, 0.90),
        "3105": (170, 634.0, 581.0, 0.90),
    }
    start_dt = as_of_dt - timedelta(days=279)
    for sid, (peak_ago, peak_h, last_c, base_ratio) in specs.items():
        peak_day = (as_of_dt - timedelta(days=int(peak_ago))).strftime("%Y%m%d")
        for d in range(0, 280):
            day_dt = start_dt + timedelta(days=d)
            if day_dt > as_of_dt:
                break
            day_s = day_dt.strftime("%Y%m%d")
            if day_s == peak_day:
                h, lo, c = peak_h, peak_h * 0.92, peak_h * 0.96
            elif day_s == as_of:
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


def test_parse_inp_glued_to_chinese_still_finds_pool():
    """InP 緊貼中文時不准因 \\b 失效而空掉去找池（該亮環宇／IET）。"""
    from biaoke_live_match import parse_spoken_stances

    # 無逗號、InP 後直接接中文；也無「光通訊」可備援
    blob = (
        "空手不要再介入全新及穩懋要去找低位階還在底部的 InP當然聯亞是標配一股不賣"
    )
    st = parse_spoken_stances(blob)
    assert "2455" in st["no_chase"] and "3105" in st["no_chase"]
    assert "3081" in st["hold"]
    assert "inp" in st["find_pools"]
    # 常見緊貼：是InP)／的InP為
    assert "inp" in parse_spoken_stances(
        "要去找低位階還在底部的InP，環宇IET先看"
    )["find_pools"]
    assert "inp" in parse_spoken_stances(
        "尤其是InP)為台股雙箭頭，要去找低位階還在底部的個股"
    )["find_pools"]


def test_parse_no_chase_names_before_and_wu_zhui():
    """名前動詞／勿追／位階偏高都要降調拿掉可點追。"""
    from biaoke_live_match import parse_spoken_stances

    st = parse_spoken_stances(
        "全新及穩懋不要再介入，要去找低位階還在底部的 InP。"
    )
    assert "2455" in st["no_chase"] and "3105" in st["no_chase"]
    assert "inp" in st["find_pools"]

    st2 = parse_spoken_stances("全新穩懋空手勿追，要去找低位階還在底部的 InP。")
    assert "2455" in st2["no_chase"] and "3105" in st2["no_chase"]

    st3 = parse_spoken_stances(
        "全新、穩懋位階偏高不要追，低位階 InP 去找。"
    )
    assert "2455" in st3["no_chase"] and "3105" in st3["no_chase"]
    assert "inp" in st3["find_pools"]


def test_parse_high_level_and_named_find_without_inp_token():
    """#562 後仍錯：高位階／先別追要降調；去找點名環宇IET 無 InP 字仍進池。"""
    from biaoke_live_match import parse_spoken_stances

    st = parse_spoken_stances(
        "全新、穩懋高位階，空手不要追，要去找低位階還在底部的 InP。"
    )
    assert "2455" in st["no_chase"] and "3105" in st["no_chase"]
    assert "inp" in st["find_pools"]

    st2 = parse_spoken_stances(
        "全新高位階先別追，要去找低位階還在底部的 InP。"
    )
    assert "2455" in st2["no_chase"]
    assert "inp" in st2["find_pools"]

    # 去找片段直接點名環宇／IET，沒寫 InP／光通訊字 → 仍進 inp 池（該亮）
    st3 = parse_spoken_stances(
        "要去找低位階還在底部的環宇跟IET，空手不要再介入全新及穩懋。"
    )
    assert "2455" in st3["no_chase"] and "3105" in st3["no_chase"]
    assert "inp" in st3["find_pools"]

    # 高位階名後：如全新、穩懋就不要碰 → 仍要降調
    st4 = parse_spoken_stances(
        "高位階如全新、穩懋就不要碰了，要去找低位階還在底部的環宇跟IET。"
    )
    assert "2455" in st4["no_chase"] and "3105" in st4["no_chase"]
    assert "inp" in st4["find_pools"]


def test_no_chase_does_not_steal_hold_across_comma():
    """跨句不准把標配聯亞誤標勿追。"""
    from biaoke_live_match import parse_spoken_stances

    st = parse_spoken_stances(
        "聯亞是標配一股不賣，不要再介入全新及穩懋，要去找低位階還在底部的 InP。"
    )
    assert "3081" in st["hold"]
    assert "3081" not in st["no_chase"]
    assert "2455" in st["no_chase"] and "3105" in st["no_chase"]


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
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from biaoke_digest import format_focus_oral

    called = {"n": 0}

    def _fake_refresh(db_path, spoken=""):
        called["n"] += 1
        return {"ok": True, "matches": []}

    monkeypatch.setattr("biaoke_live_match.refresh_live_match", _fake_refresh)
    db = _mk_db(tmp_path)
    day = (datetime.now(ZoneInfo("Asia/Taipei")).date() - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    html = format_focus_oral(
        [{"date": day, "time": "13:42", "text": "InP 低位階好好去研究"}],
        [],
        db_path=db,
    )
    assert called["n"] >= 1
    assert "飆大現在在講" in html


def test_linkify_spoken_blue_then_plain_no_chase(tmp_path):
    """該記＝藍可點；勿追＝黑字（剔除藍連）。"""
    from biaoke_live_match import linkify_spoken_html, live_match_pack

    db = _mk_db(tmp_path)
    pack = live_match_pack(db)
    html = linkify_spoken_html(
        "聯亞是標配，全新與穩懋不要再介入，環宇去找。",
        db,
        pack=pack,
    )
    assert "quote/3081." in html  # 標配可點
    assert "quote/4991." in html or "環宇" in html  # 去找可點（名在文內）
    assert "quote/2455." not in html  # 勿追不准藍
    assert "全新" in html
    assert "quote/3105." not in html
    assert "穩懋" in html


def test_sync_biaoke_inline_after_update_runs(tmp_path, monkeypatch):
    """融合／更新後同步入口會連線＋走讀＋重算可點。"""
    from biaoke_live_match import sync_biaoke_inline_after_update

    db = _mk_db(tmp_path)
    calls = {"link": 0, "walk": 0, "live": 0}

    def _link(path):
        calls["link"] += 1
        return {"posts": 1, "mentions": 2, "stocks": 2}

    def _walk(path, fetch_missing=False):
        calls["walk"] += 1
        return {"levels": 3, "facts": 4}

    def _live(path, spoken=""):
        calls["live"] += 1
        return {"ok": True, "no_chase": {"2455": "全新"}, "matches": []}

    monkeypatch.setattr("biaoke_link.link_biaoke_db", _link)
    monkeypatch.setattr("biaoke_walk.walk_biaoke_posts", _walk)
    monkeypatch.setattr("biaoke_live_match.refresh_live_match", _live)
    out = sync_biaoke_inline_after_update(db)
    assert out.get("ok")
    assert calls["link"] == 1 and calls["walk"] == 1 and calls["live"] == 1
    assert out.get("live_match", {}).get("levels") == 3


def test_focus_oral_inline_blue_and_plain(tmp_path):
    """圖文重點文內：聯亞藍、全新黑。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from biaoke_digest import format_focus_oral

    db = _mk_db(tmp_path)
    day = (datetime.now(ZoneInfo("Asia/Taipei")).date() - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    html = format_focus_oral(
        [
            {
                "date": day,
                "time": "13:42",
                "text": (
                    "1. 夜盤反彈，大盤還在整理。"
                    "2. 光通訊 InP：聯亞標配一股不賣，全新不要再介入。"
                ),
            }
        ],
        [],
        db_path=db,
    )
    assert "飆大現在在講" in html
    # 族群／他還說裡點到的聯亞應可點；全新勿追＝黑
    assert "quote/3081." in html or "聯亞" in html
    assert "quote/2455." not in html
    assert "全新" in html


def test_refresh_after_fuse_calls_inline_sync(tmp_path, monkeypatch):
    """16:30 融合後走文內藍字／點位同步。"""
    from biaoke_facts import refresh_after_market_fuse

    called = {"n": 0}

    def _sync(path):
        called["n"] += 1
        return {
            "ok": True,
            "link": {"mentions": 1},
            "walk": {"levels": 2},
            "live_match": {"ok": True, "levels": 2},
        }

    monkeypatch.setattr(
        "biaoke_live_match.sync_biaoke_inline_after_update", _sync
    )
    monkeypatch.setattr(
        "biaoke_claims.refresh_wave_minute_hits", lambda path: {"ok": True}
    )
    db = str(tmp_path / "empty.db")
    __import__("sqlite3").connect(db).close()
    ran = refresh_after_market_fuse(db, kind="fuse")
    assert ran.get("ok") is True
    assert called["n"] == 1
    assert ran.get("live_match", {}).get("levels") == 2
