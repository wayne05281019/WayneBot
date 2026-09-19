# -*- coding: utf-8 -*-
"""產業卡同業：同一細項才比；跨族（穩懋光通訊／低軌衛星）兩邊都進。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from industry_brief import (
    COPY_PEER_RULE,
    attach_fine_industry,
    format_industry_html,
    industry_card_spec,
    industry_snapshot,
)
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


def test_extra_tags_win_spans_optical_and_satellite():
    optical = {
        "3081",
        "2455",
        "3105",
        "6442",
        "3163",
        "3234",
        "4979",
        "4991",
        "4971",
        "3363",
        "4977",
    }
    for sid in optical:
        assert "光通訊" in extra_tags_for(sid), sid
    assert extra_tags_for("3105") == ["光通訊", "低軌衛星"]
    assert extra_tags_for("3491") == ["低軌衛星"]
    assert extra_tags_for("3062") == []  # 建漢，不是昇達科
    assert extra_tags_for("3450") == []
    assert ("x", "光通訊") in membership_keys("3081", "半導體元件")
    assert ("fine", "半導體元件") not in membership_keys("3081", "半導體元件")
    assert ("fine", "通訊設備") not in membership_keys("3491", "通訊設備")
    assert ("fine", "代工") in membership_keys("3105", "代工")
    assert membership_keys("3081", "半導體元件") & membership_keys("3163", "通訊設備")
    assert membership_keys("3081", "半導體元件") & membership_keys("6442", "通訊設備")
    assert membership_keys("3081", "半導體元件") & membership_keys("4971", "晶圓材料")
    assert membership_keys("3491", "通訊設備") & membership_keys("3105", "代工")
    assert not (membership_keys("3081", "半導體元件") & membership_keys("3491", "通訊設備"))
    assert not (membership_keys("3163", "通訊設備") & membership_keys("3491", "通訊設備"))
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
            ("7887", "宇川精材", "半導體業", "EM", "電子上游-IC-封測", 8.0, 40.0, 0.80),
        ],
    )
    html = format_industry_html("3450", db, allow_fetch=False)
    assert "封測" in html
    assert "同一產業鏈才比" in html
    assert "3374" in html and "精材" in html
    assert "7887" in html and "宇川精材" in html
    assert "興櫃" in html
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
            ("6442", "光聖", "通信網路業", "TW", "電子中游-通訊設備", 30.0, 400.0, 2.00),
            ("3163", "波若威", "通信網路業", "TWO", "電子中游-通訊設備", 12.0, 80.0, 1.10),
            ("4971", "IET-KY", "半導體業", "TWO", "電子上游-晶圓材料", 18.0, 200.0, 1.80),
            ("3105", "穩懋", "半導體業", "TWO", "電子上游-IC-代工", 80.0, 471.0, 3.56),
            ("3491", "昇達科", "通信網路業", "TWO", "電子中游-通訊設備", 10.0, 180.0, 1.50),
            ("2330", "台積電", "半導體業", "TW", "電子上游-IC-代工", 40.0, 2425.0, 14.0),
            ("5434", "崇越", "電子通路業", "TW", "電子上游-半導體元件", 5.0, 530.0, 4.00),
        ],
    )
    html = format_industry_html("3081", db, allow_fetch=False)
    assert "跨族" in html and "光通訊" in html
    for sid, name in (
        ("3105", "穩懋"),
        ("2455", "全新"),
        ("6442", "光聖"),
        ("3163", "波若威"),
        ("4971", "IET-KY"),
    ):
        assert sid in html and name in html
    assert "2330" not in html
    assert "台積電" not in html
    assert "3491" not in html
    assert "昇達科" not in html
    assert "5434" not in html
    assert "崇越" not in html
    win = format_industry_html("3105", db, allow_fetch=False)
    assert "光通訊" in win
    assert "低軌衛星" in win
    assert "3081" in win
    assert "2330" in win
    for tag in ("電子上游", "IC", "代工", "光通訊", "低軌衛星"):
        assert tag in win


def test_satellite_page_includes_win_not_optical_only(tmp_path):
    db = str(tmp_path / "sat.db")
    _seed(
        db,
        [
            ("3491", "昇達科", "通信網路業", "TWO", "電子中游-通訊設備", 10.0, 180.0, 1.50),
            ("2314", "台揚", "通信網路業", "TW", "電子中游-通訊設備", 12.0, 90.0, 1.20),
            ("3105", "穩懋", "半導體業", "TWO", "電子上游-IC-代工", 80.0, 471.0, 3.56),
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 20.0, 2720.0, 7.75),
            ("3163", "波若威", "通信網路業", "TWO", "電子中游-通訊設備", 12.0, 80.0, 1.10),
            ("2455", "全新", "通信網路業", "TW", "電子上游-半導體元件", 15.0, 534.0, 2.20),
        ],
    )
    html = format_industry_html("3491", db, allow_fetch=False)
    assert "低軌衛星" in html
    assert "3105" in html and "穩懋" in html
    assert "2314" not in html
    assert "台揚" not in html
    assert "3081" not in html
    assert "聯亞" not in html
    assert "3163" not in html
    assert "波若威" not in html
    win = format_industry_html("3105", db, allow_fetch=False)
    assert "3491" in win and "昇達科" in win
    assert "3081" in win and "聯亞" in win
    assert "3163" in win and "波若威" in win
    assert "2314" not in win
    opt = format_industry_html("3081", db, allow_fetch=False)
    assert "3105" in opt and "穩懋" in opt
    assert "3163" in opt and "波若威" in opt
    assert "3491" not in opt
    assert "昇達科" not in opt


def test_html_and_png_share_card_spec(tmp_path):
    db = str(tmp_path / "spec.db")
    _seed(
        db,
        [
            ("3105", "穩懋", "半導體業", "TWO", "電子上游-IC-代工", 80.0, 471.0, 3.56),
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 20.0, 2720.0, 7.75),
            ("3062", "建漢", "通信網路業", "TW", "電子中游-網通", 10.0, 21.0, 1.00),
            ("3491", "昇達科", "通信網路業", "TWO", "電子中游-通訊設備", 10.0, 180.0, 1.50),
            ("2330", "台積電", "半導體業", "TW", "電子上游-IC-代工", 40.0, 2425.0, 14.0),
        ],
    )
    snap = attach_fine_industry(industry_snapshot(db, "3105"), db, allow_fetch=False)
    spec = industry_card_spec(snap)
    assert spec["extras"] == ["光通訊", "低軌衛星"]
    assert spec["tags"] == ["電子上游", "IC", "代工", "光通訊", "低軌衛星"]
    assert "代工／光通訊／低軌衛星" in spec["peer_lab"]
    assert spec["copy_rule"] == COPY_PEER_RULE
    html = format_industry_html("3105", db, allow_fetch=False)
    assert COPY_PEER_RULE in html
    assert "3491" in html and "昇達科" in html
    assert "3081" in html
    assert "3062" not in html
    assert "建漢" not in html
    for tag in spec["tags"]:
        assert f"[{tag}]" in html or tag in html
    from industry_card import render_industry_png

    png = str(tmp_path / "3105_industry.png")
    out = render_industry_png("3105", db, png, allow_fetch=False)
    assert out and os.path.isfile(out)
