# -*- coding: utf-8 -*-
"""資金／籌碼／營收／產業標題：有籌碼K產業鏈就標鏈。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from industry_fine import peek_cached_fine_chain
from money_flow import _flow_stock_title, _sector_entry
from universe import listing_industry_face
from wayne_db import ensure_core_schema


def _db_with_fine(tmp_path, *, sid="2303", name="聯電", ind="半導體業", chain="電子上游-IC-代工"):
    db = str(tmp_path / "fine.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
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
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        (sid, name, "TWSE", "STOCK", ind, now),
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
        "VALUES (?,?,?,'TW',100,101,99,100,5000,900000,1.0,100,100,0,0)",
        ("20260917", sid, name),
    )
    tags = chain.split("-")
    conn.execute(
        "INSERT INTO stock_fine_industry(stock_id,chain,tags_json,cat_id,source,fetched_at) "
        "VALUES (?,?,?,?,?,?)",
        (sid, chain, json.dumps(tags, ensure_ascii=False), "", "cmoney_forum", now),
    )
    conn.commit()
    conn.close()
    return db


def test_listing_industry_face_prefers_fine_chain(tmp_path):
    db = _db_with_fine(
        tmp_path, sid="2412", name="中華電", ind="通信網路業", chain="電子下游-電信"
    )
    face = listing_industry_face("2412", db)
    assert "電子下游-電信" in face
    assert face.startswith("上市")
    assert "（通信網路業）" not in face
    assert "細項" not in face


def test_listing_industry_face_uses_taught_membership(tmp_path):
    db = _db_with_fine(tmp_path)
    face = listing_industry_face("2303", db)
    assert "成熟製程" in face
    assert face.startswith("上市")
    assert "電子上游-IC-代工" not in face
    assert "（半導體業）" not in face
    conn = sqlite3.connect(db)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("3105", "穩懋", "TWO", "STOCK", "半導體業", now),
    )
    conn.execute(
        "INSERT INTO stock_fine_industry(stock_id,chain,tags_json,cat_id,source,fetched_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "3105",
            "電子上游-IC-代工",
            json.dumps(["電子上游", "IC", "代工"], ensure_ascii=False),
            "",
            "cmoney_forum",
            now,
        ),
    )
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("2049", "上銀", "TW", "STOCK", "電機機械", now),
    )
    conn.commit()
    conn.close()
    win = listing_industry_face("3105", db)
    assert win.startswith("上櫃")
    assert "光通訊" in win and "低軌衛星" in win
    assert "代工／光通訊" not in win
    robot = listing_industry_face("2049", db)
    assert robot.startswith("上市")
    assert "機器人" in robot


def test_listing_industry_face_falls_back_without_fine(tmp_path):
    db = _db_with_fine(
        tmp_path, sid="2412", name="中華電", ind="通信網路業", chain="電子下游-電信"
    )
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM stock_fine_industry")
    conn.commit()
    conn.close()
    face = listing_industry_face("2412", db)
    assert face == "上市（通信網路業）" or face.startswith("上市（通信網路業）")


def test_flow_stock_title_and_sector_entry_show_fine(tmp_path):
    db = _db_with_fine(tmp_path)
    title = _flow_stock_title("2303", "聯電", db)
    assert "2303" in title and "聯電" in title
    assert "成熟製程" in title
    assert "電子上游-IC-代工" not in title
    row = {
        "industry": "半導體業",
        "three_net": 40000,
        "avg_pct": 0.7,
        "three_delta": 1000,
        "top_buys": [
            {"stock_id": "2303", "stock_name": "聯電", "three_net": 40000},
            {"stock_id": "2330", "stock_name": "台積電", "three_net": 10000},
        ],
    }
    # 2330 沒產業鏈表 → 退回證交所臉，不崩
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("2330", "台積電", "TWSE", "STOCK", "半導體業", datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    html = _sector_entry(row, db)
    assert "前幾名買超" in html
    assert "成熟製程" in html
    assert "細項" not in html
    assert "1. " in html and "2. " in html


def test_fundamentals_and_industry_title_carry_fine(tmp_path):
    from fundamentals import ensure_fundamentals_tables, format_fundamentals_html
    from industry_brief import format_industry_html

    db = _db_with_fine(tmp_path)
    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,"
        "revenue_prev_month,revenue_prev_year,mom_pct,yoy_pct,ytd_revenue,ytd_prev_year,ytd_yoy_pct) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2303", "202608", "聯電", "TW", "半導體業", 100000, 90000, 80000, 11.0, 25.0, 500000, 400000, 25.0),
    )
    conn.commit()
    conn.close()
    fund = format_fundamentals_html("2303", db)
    assert "基本面" in fund
    assert "成熟製程" in fund
    assert "細項" not in fund
    ind = format_industry_html("2303", db, allow_fetch=False)
    assert "產業說明" in ind
    assert "成熟製程" in ind
    assert "細項" not in ind


def test_chips_html_title_carries_fine(tmp_path):
    from chips import format_major_player_html

    db = _db_with_fine(tmp_path)
    # html_stock_anchor 讀 get_db_path；這裡直接測 face 已夠，再測 format 字串組裝
    from unittest.mock import patch

    rows = [
        {
            "stock_id": "2303",
            "stock_name": "聯電",
            "date": "20260917",
            "foreign_net": 100,
            "trust_net": 0,
            "dealer_net": 0,
            "three_net": 100,
            "volume": 1000,
            "ratio_pct": 10.0,
        }
    ]
    with patch("stock_links.html_stock_anchor", side_effect=lambda s, n, p=None: f"{s} {n}　上市　電子上游-IC-代工"):
        html = format_major_player_html(rows, "2303")
    assert "電子上游-IC-代工" in html
    assert "細項" not in html
