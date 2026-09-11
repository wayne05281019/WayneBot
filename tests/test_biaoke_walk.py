# -*- coding: utf-8 -*-
"""從第一篇讀到最新：每檔對當天官方日 K，重複的彙整。"""
from __future__ import annotations

import sqlite3

from biaoke_archive import seed_biaoke_archive
from biaoke_walk import (
    _hold_note,
    fetch_stock_month,
    format_stock_walk,
    stock_timeline,
    upsert_fetched_quotes,
    walk_biaoke_posts,
)


def test_fetch_stock_month_parses_twse():
    class _Sess:
        def get(self, url, params=None, headers=None, timeout=18):
            class R:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "stat": "OK",
                        "title": "112年12月 3035 智原 各日成交資訊",
                        "data": [
                            [
                                "112/12/04",
                                "23,573,533",
                                "9,052,947,592",
                                "392.00",
                                "393.50",
                                "374.50",
                                "380.00",
                                "-11.00",
                                "21,742",
                                "",
                            ]
                        ],
                    }

            return R()

    rows = fetch_stock_month("3035", "202312", session=_Sess())
    assert len(rows) == 1
    assert rows[0]["date"] == "20231204"
    assert rows[0]["low"] == 374.5
    assert rows[0]["close"] == 380.0


def test_hold_note_zhiyuan_370():
    note = _hold_note("支撐370", {"high": 393.5, "low": 374.5, "close": 380})
    assert note == "當日低有守"
    note2 = _hold_note("支撐370", {"high": 360, "low": 360, "close": 360})
    assert note2 == "當日低跌破"


def test_walk_from_first_post_without_fetch(tmp_path):
    db = str(tmp_path / "w.db")
    seed_biaoke_archive(db)
    stats = walk_biaoke_posts(db, fetch_missing=False)
    assert stats["posts"] >= 1709
    assert stats.get("club_posts", 0) >= 92
    assert stats["facts"] >= 1000
    assert stats["stocks"] >= 40
    conn = sqlite3.connect(db)
    nanya = conn.execute(
        "SELECT COUNT(*) FROM biaoke_day_facts WHERE stock_id='2408'"
    ).fetchone()[0]
    zhi = conn.execute(
        "SELECT COUNT(*) FROM biaoke_day_facts WHERE stock_id='3035'"
    ).fetchone()[0]
    bulk = conn.execute(
        "SELECT COUNT(*) FROM biaoke_day_facts WHERE stock_id='3167'"
    ).fetchone()[0]
    first = conn.execute(
        "SELECT post_date, snippet FROM biaoke_day_facts WHERE stock_id='3035' ORDER BY post_date LIMIT 1"
    ).fetchone()
    n_club = conn.execute(
        "SELECT COUNT(*) FROM biaoke_day_facts WHERE IFNULL(club,0)=1"
    ).fetchone()[0]
    n_lv = conn.execute("SELECT COUNT(*) FROM biaoke_level_facts").fetchone()[0]
    lv465 = conn.execute(
        "SELECT 1 FROM biaoke_level_facts WHERE claimed BETWEEN 46500 AND 46520"
    ).fetchone()
    n370 = conn.execute(
        "SELECT COUNT(*) FROM biaoke_claims WHERE stock_id='3035' AND role='support' "
        "AND lo BETWEEN 369 AND 371 AND IFNULL(club,0)=0"
    ).fetchone()[0]
    n397 = conn.execute(
        "SELECT COUNT(*) FROM biaoke_claims WHERE stock_id='3035' AND role='target' "
        "AND lo BETWEEN 396 AND 398 AND IFNULL(club,0)=0"
    ).fetchone()[0]
    n_claim_club = conn.execute(
        "SELECT COUNT(*) FROM biaoke_claims WHERE IFNULL(club,0)=1"
    ).fetchone()[0]
    n465c = conn.execute(
        "SELECT 1 FROM biaoke_claims WHERE stock_id='TWII' AND lo BETWEEN 46500 AND 46520"
    ).fetchone()
    conn.close()
    assert nanya >= 5
    assert zhi >= 5
    assert bulk == 0
    assert first[0].startswith("2023-12")
    assert "智原" in (first[1] or "")
    assert stats["levels"] >= 8
    assert stats["charts"] >= 1
    assert n_lv >= 8
    assert n_club >= 1
    assert lv465
    assert stats.get("claims", 0) >= 80
    assert stats.get("targets", 0) >= 20
    assert n370 >= 1
    assert n397 >= 1
    assert n_claim_club >= 1
    assert n465c
    tl = stock_timeline(db, "3035")
    assert tl["n"] >= 5
    assert str(tl.get("from") or "").startswith("2023-12")
    html = format_stock_walk(db, "3035")
    assert "3035" in html
    assert "不是買訊" in html
    assert "語料" not in html
    assert "397" in html or "370" in html


def test_extract_index_levels_skips_stock_keeps_night():
    from biaoke_walk import extract_index_levels

    zhi = extract_index_levels("智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！")
    assert zhi == []
    night = extract_index_levels(
        "今晚夜盤至少要穿越46506為今晚觀盤重點。加權指數細微波修正已經走5段。"
    )
    assert any(abs(float(h["level"]) - 46506) < 0.1 for h in night)


def test_upsert_does_not_invent_when_empty():
    assert upsert_fetched_quotes("", []) == 0
    assert upsert_fetched_quotes("missing.db", []) == 0
