# -*- coding: utf-8 -*-
"""產業卡同業：同一細項才比；跨族（穩懋光通訊）兩邊都進。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from industry_brief import format_industry_html
from industry_fine import extra_tags_for, membership_keys
from wayne_db import ensure_core_schema


def _seed(db: str, rows: list) -> None:
    ensure_core_schema(db)
    from fundamentals import ensure_fundamentals_tables

    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fine_industry (
            stock_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            cat_id TEXT DEFAULT '',
            source TEXT DEFAULT '',
            fetched_at TEXT NOT NULL
        )
        """
    )
    for sid, name, ind, mkt, chain, yoy, close, eps in rows:
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe"
            "(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, mkt, "STOCK", ind, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO monthly_revenue"
            "(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, "202608", name, "TW", ind, 1000, 1.0, yoy, yoy),
        )
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes"
            "(date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
            "VALUES (?,?,?,'TW',100,101,99,?,1000,100000,1.0,?,0,0,0)",
            ("20260918", sid, name, close, close),
        )
        conn.execute(
            "INSERT OR REPLACE INTO quarterly_income"
            "(stock_id,year,season,stock_name,market,revenue,gross_profit,"
            "gross_margin_pct,operating_income,net_income,eps) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, 2026, 2, name, "TW", 1e6, 3e5, 30.0, 2e5, 1e5, eps),
        )
        tags = chain.split("-")
        conn.execute(
            "INSERT OR REPLACE INTO stock_fine_industry"
            "(stock_id,chain,tags_json,cat_id,source,fetched_at) VALUES (?,?,?,?,?,?)",
            (sid, chain, json.dumps(tags, ensure_ascii=False), "", "test", now),
        )
    conn.commit()
    conn.close()


def test_extra_tags_win_semiconductor_optical_not_invented_satellite():
    assert "光通訊" in extra_tags_for("3105")
    assert "光通訊" in extra_tags_for("3081")
    assert extra_tags_for("3450") == []
    assert extra_tags_for("3062") == []
    assert ("x", "光通訊") in membership_keys("3105", "代工")
    assert not (membership_keys("3450", "封測") & membership_keys("3006", "記憶體IC設計"))


def test_packaging_card_excludes_memory_names(tmp_path):
    db = str(tmp_path / "pack.db")
    _seed(
        db,
        [
            ("3450", "聯鈞", "半導體業", "TW", "電子上游-IC-封測", 109.8, 530.0, 2.78),
            ("3374", "精材", "半導體業", "TWO", "電子上游-IC-封測", 40.0, 444.0, 2.88),
            ("3006", "晶豪科", "半導體業", "TW", "電子上游-記憶體IC設計", 605.2, 100.0, 1.0),
            ("2408", "南亞科", "半導體業", "TW", "電子上游-記憶體製造", 560.9, 80.0, 1.0),
            ("6854", "錼創科技-KY", "半導體業", "TW", "電子上游-LED照明及光元件", -47.6, 50.0, 1.0),
        ],
    )
    html = format_industry_html("3450", db, allow_fetch=False)
    assert "封測" in html
    assert "同一產業鏈才比" in html
    assert "證交所半導體業全組" in html or "同一產業鏈" in html
    assert "3374" in html and "精材" in html
    assert "晶豪科" not in html
    assert "3006" not in html
    assert "南亞科" not in html
    assert "2408" not in html
    assert "錼創" not in html
    assert "半導體業含代工、記憶體、設計" not in html


def test_optical_page_includes_win_semiconductor_not_tsmc(tmp_path):
    db = str(tmp_path / "opt.db")
    _seed(
        db,
        [
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 20.0, 2720.0, 7.75),
            ("2455", "全新", "通信網路業", "TW", "電子上游-半導體元件", 15.0, 534.0, 2.20),
            ("3105", "穩懋", "半導體業", "TWO", "電子上游-IC-代工", 80.0, 471.0, 3.56),
            ("2330", "台積電", "半導體業", "TW", "電子上游-IC-代工", 40.0, 2425.0, 14.0),
        ],
    )
    html = format_industry_html("3081", db, allow_fetch=False)
    assert "跨族" in html and "光通訊" in html
    assert "3105" in html and "穩懋" in html
    assert "2455" in html and "全新" in html
    assert "2330" not in html
    assert "台積電" not in html
    win = format_industry_html("3105", db, allow_fetch=False)
    assert "光通訊" in win
    assert "3081" in win
    assert "2330" in win
