# -*- coding: utf-8 -*-
"""三百融會 → 一百判斷 → 三百融會＋官方日 K。不進海選。"""
from __future__ import annotations

import sqlite3

from biaoke_archive import load_bundled_archive
from biaoke_brain import DISCLAIMER, answer_biaoke
from biaoke_fuse import (
    ROUND_A,
    ROUND_B,
    ROUND_C,
    format_fuse_html,
    fuse_one,
    is_fuse_query,
    render_snapshot_md,
    run_round_a,
    run_round_b,
    run_round_c,
    stratified_main_posts,
    summarize,
)
from biaoke_mind import corpus_curriculum, method_curriculum, stratified_main_posts as mind_strat


def test_stratified_300_spans_archive_not_only_oldest():
    blob = load_bundled_archive()
    posts = blob.get("posts") or []
    n_main = sum(1 for p in posts if (p.get("kind") or "post") != "reply")
    assert n_main >= 1700
    a = mind_strat(posts, 300, phase=0)
    c = mind_strat(posts, 300, phase=1)
    assert len(a) == 300
    assert len(c) == 300
    ids_a = {p["id"] for p in a}
    ids_c = {p["id"] for p in c}
    assert len(ids_a) == 300
    assert len(ids_c) == 300
    assert len(ids_a & ids_c) < 40
    dates_a = [p["date"] for p in a if p.get("date")]
    assert min(dates_a) < "2025-01-01"
    assert max(dates_a) >= "2026-01-01"


def test_round_b_100_all_answer():
    rows = run_round_b()
    assert len(rows) == ROUND_B
    assert all(r["ok"] for r in rows)
    assert any("細微波" in (r["titles"] or []) or "細微波" in r["ask"] for r in rows)


def test_corpus_curriculum_still_300():
    blob = load_bundled_archive()
    asks = corpus_curriculum(blob.get("posts") or [], limit=300)
    assert len(asks) >= 300
    assert len(method_curriculum()) >= 100


def test_fuse_one_fixture_and_round_c_backtest(tmp_path):
    from datetime import date, timedelta

    db = str(tmp_path / "q.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            pct_change REAL, PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT PRIMARY KEY, stock_name TEXT, is_active INT)"
    )
    conn.execute(
        "INSERT INTO stock_universe(stock_id, stock_name, is_active) VALUES ('3030','智原',1)"
    )
    start = date(2026, 1, 5)
    for i in range(140):
        day = start + timedelta(days=i)
        d = day.strftime("%Y%m%d")
        vol = 90000 if i == 10 else 20000
        close = 100.0 + i
        conn.execute(
            """
            INSERT INTO daily_quotes(date, stock_id, stock_name, open, high, low, close, volume, pct_change)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (d, "3030", "智原", close, close + 2, close - 2, close, vol, 1.0),
        )
    conn.commit()
    conn.close()
    posts = [
        {
            "id": "1",
            "kind": "post",
            "date": "2026-03-20",
            "tags": ["智原"],
            "text": "智原佈局，量先價行站上支撐可以找買點。",
            "_sids": ["3030"],
            "_snames": ["智原"],
        },
        {
            "id": "1:a1",
            "kind": "reply",
            "parent": "1",
            "date": "2026-03-20",
            "text": "破線翻當洗盤",
            "tags": [],
        },
    ]
    # pad so stratified 300 isn't required here
    row = fuse_one(posts[0], posts, db_path=db, backtest=False)
    assert row["fused"]
    assert "volfirst" in (row["families"] or []) or "buy3" in (row["families"] or [])
    assert row["replies"] == 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cache = {}
    bt = fuse_one(posts[0], posts, db_path=db, conn=conn, cache=cache, backtest=True)
    conn.close()
    assert bt.get("bar") is True
    assert bt.get("r20") is not None
    assert bt.get("stance") == "偏多"


def test_summarize_and_html_not_screen():
    a = [{"fused": True, "families": ["volfirst"], "replies": 1, "names": ["智原"]}]
    b = [{"ok": True, "ask": "x", "titles": ["量先價行"]}]
    c = [
        {
            "stance": "偏多",
            "r20": 5.0,
            "r60": 8.0,
            "bar": True,
            "vf_buy": "整理末端候選（難）",
            "vf_above": True,
            "names": ["智原"],
        }
    ]
    snap = summarize(a, b, c, n_posts=1709)
    assert snap["not_screen"] is True
    html = format_fuse_html(snap)
    assert "不是買訊" in html
    assert "不進海選" in html
    assert "1709" in render_snapshot_md(snap) or "主文庫" in render_snapshot_md(snap)
    assert is_fuse_query("融會貫通")
    assert "海選" in html and "不進" in html
    ans = answer_biaoke(":memory:", "融會貫通是什麼")
    assert "這不是買訊" in ans
    assert "海選" in ans


def test_fwd_skips_when_first_bar_years_later():
    from biaoke_fuse import _fwd

    ser = [("20250220", 100.0, 101.0, 99.0, 1.0)]
    ser += [(f"202503{i:02d}", 100.0 + i, 102.0, 98.0, 1.0) for i in range(1, 28)]
    assert _fwd(ser, "2023-12-14", 20) is None
    near = [("20260320", 100.0, 101.0, 99.0, 1.0)]
    near += [(f"202604{i:02d}", 110.0, 111.0, 109.0, 1.0) for i in range(1, 28)]
    # April has 30 days; 20 steps from Mar 20 needs ~20 later bars
    from datetime import date, timedelta

    start = date(2026, 3, 20)
    ser2 = []
    px = 100.0
    for i in range(30):
        d = (start + timedelta(days=i)).strftime("%Y%m%d")
        ser2.append((d, px + i, px + i + 1, px + i - 1, 1.0))
    assert _fwd(ser2, "2026-03-20", 20) == 20.0


def test_round_constants():
    assert ROUND_A == 300
    assert ROUND_B == 100
    assert ROUND_C == 300
    assert stratified_main_posts([], 300) == []
