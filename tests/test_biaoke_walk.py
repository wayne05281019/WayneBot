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
    conn.close()
    assert nanya >= 5
    assert zhi >= 5
    assert bulk == 0
    assert first[0].startswith("2023-12")
    assert "智原" in (first[1] or "")
    tl = stock_timeline(db, "3035")
    assert tl["n"] >= 5
    assert str(tl.get("from") or "").startswith("2023-12")
    html = format_stock_walk(db, "3035")
    assert "3035" in html
    assert "不是買訊" in html
    assert "語料" not in html


def test_upsert_does_not_invent_when_empty():
    assert upsert_fetched_quotes("", []) == 0
    assert upsert_fetched_quotes("missing.db", []) == 0
