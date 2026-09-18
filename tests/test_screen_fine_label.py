# -*- coding: utf-8 -*-
"""海選產業列：CMoney 細項＋佔比＋龍頭／次級。不改海選桶。"""
from __future__ import annotations

import sqlite3

from industry_fine import display_chain, screen_industry_card_lines, screen_share_text
from money_flow import annotate_screen_results, annotate_items_with_sector_flow
from screening_engine import _stock_card_html
from wayne_db import ensure_core_schema


def test_display_chain_splits_main_sub_fine():
    assert display_chain("電子上游-IC-封測") == "電子上游／IC／封測"
    assert display_chain("") == ""


def test_stock_card_shows_fine_industry_role_and_share():
    html = _stock_card_html(
        {
            "stock_id": "6257",
            "stock_name": "矽格",
            "close": 80.0,
            "industry_face": "電子上游／IC／封測",
            "industry_role": "次級",
            "fine_share_pct": 2.4,
            "fine_share_chg": 0.6,
            "sector_inflow": True,
            "sector_flow_label": "剛輪到·封測",
            "ma20": 78.0,
            "ma60": 77.0,
        },
        1,
        bucket_label="黃金買點",
    )
    assert "產業　電子上游／IC／封測　次級" in html
    assert "佔比　2.4%　升" in html
    assert "剛輪到·封測" in html
    assert "半導體業" not in html


def test_screen_share_text_blank_without_number():
    assert screen_share_text({}) == ""
    assert screen_share_text({"fine_share_pct": 1.0, "fine_share_chg": -0.2}) == "1.0%　降"
    assert screen_industry_card_lines({}) == []


def test_fine_chain_beats_coarse_industry_on_screen(tmp_path):
    db = str(tmp_path / "fine.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    now = "2026-09-17T00:00:00"
    univ = [
        ("6515", "穎崴", "電子零組件業"),
        ("6257", "矽格", "電子零組件業"),
        ("2449", "京元電子", "電子零組件業"),
        ("3443", "創意", "半導體業"),
        ("3661", "世芯-KY", "半導體業"),
        ("2002", "中鋼", "鋼鐵工業"),
        ("2027", "大成鋼", "鋼鐵工業"),
    ]
    for sid, name, ind in univ:
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, "TWSE", "STOCK", ind, now),
        )
    conn.execute(
        "CREATE TABLE stock_fine_industry ("
        "stock_id TEXT PRIMARY KEY, chain TEXT NOT NULL, tags_json TEXT, cat_id TEXT, source TEXT, fetched_at TEXT)"
    )
    fines = [
        ("6515", "電子上游-IC-封測"),
        ("6257", "電子上游-IC-封測"),
        ("2449", "電子上游-IC-封測"),
        ("3443", "電子上游-IP/ASIC"),
        ("3661", "電子上游-IP/ASIC"),
    ]
    for sid, chain in fines:
        conn.execute(
            "INSERT INTO stock_fine_industry VALUES (?,?,?,?,?,?)",
            (sid, chain, "[]", "", "test", now),
        )

    def q(date, sid, name, fn, tn, dn):
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,"
            "pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (date, sid, name, "TW", 100, 101, 99, 100, 8000, 40000, 1.0, 100, fn, tn, dn),
        )

    for date, packs in (
        (
            "20260916",
            (
                ("6515", "穎崴", -400, -40, 0),
                ("6257", "矽格", -80, -10, 0),
                ("2449", "京元電子", -50, -5, 0),
                ("3443", "創意", 900, 80, 10),
                ("3661", "世芯-KY", 700, 50, 5),
                ("2002", "中鋼", 200, 20, 0),
                ("2027", "大成鋼", 80, 10, 0),
            ),
        ),
        (
            "20260917",
            (
                ("6515", "穎崴", 5000, 400, 50),
                ("6257", "矽格", 300, 20, 5),
                ("2449", "京元電子", 200, 10, 0),
                ("3443", "創意", -800, -90, 0),
                ("3661", "世芯-KY", -600, -70, 0),
                ("2002", "中鋼", -300, -40, 0),
                ("2027", "大成鋼", -100, -10, 0),
            ),
        ),
    ):
        for sid, name, fn, tn, dn in packs:
            q(date, sid, name, fn, tn, dn)
    conn.commit()
    conn.close()

    results = {
        "leave_zero": [
            {"stock_id": "6257", "stock_name": "矽格", "close": 80},
            {"stock_id": "6515", "stock_name": "穎崴", "close": 1200},
        ],
        "select_01": [
            {"stock_id": "3443", "stock_name": "創意", "close": 2500},
        ],
    }
    annotate_screen_results(db, "20260917", results)
    sil = results["leave_zero"][0]
    ying = results["leave_zero"][1]
    asic = results["select_01"][0]
    assert sil["industry_face"] == "電子上游／IC／封測"
    assert sil["industry_role"] == "次級"
    assert ying["industry_role"] == "龍頭"
    assert "封測" in (sil.get("sector_flow_label") or "")
    assert "電子零組件業" not in (sil.get("sector_flow_label") or "")
    assert sil.get("fine_share_pct") not in (None, 0, 0.0)
    assert float(sil["fine_share_chg"]) > 0
    assert asic["industry_face"] == "電子上游／IP/ASIC"
    assert asic.get("industry_role") in ("", None)
    assert "ASIC" in (asic.get("sector_flow_label") or "")
    html = _stock_card_html({**sil, "ma20": 78, "ma60": 77}, 1, bucket_label="黃金買點")
    assert "產業　電子上游／IC／封測　次級" in html
    assert "佔比　" in html and "升" in html


def test_no_fine_table_still_uses_exchange_industry(tmp_path):
    db = str(tmp_path / "coarse.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    now = "2026-08-31T00:00:00"
    for sid, name, ind in (
        ("2330", "台積電", "半導體業"),
        ("2454", "聯發科", "半導體業"),
        ("2002", "中鋼", "鋼鐵工業"),
        ("2027", "大成鋼", "鋼鐵工業"),
    ):
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, "TWSE", "STOCK", ind, now),
        )

    def q(date, sid, name, fn, tn, dn):
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,"
            "pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (date, sid, name, "TW", 100, 101, 99, 100, 10000, 50000, 1.0, 100, fn, tn, dn),
        )

    q("20260827", "2330", "台積電", 500, 100, 0)
    q("20260827", "2454", "聯發科", 80, 20, 0)
    q("20260827", "2002", "中鋼", -200, -50, 0)
    q("20260827", "2027", "大成鋼", -40, -10, 0)
    q("20260828", "2330", "台積電", 8000, 400, 50)
    q("20260828", "2454", "聯發科", 1200, 300, 20)
    q("20260828", "2002", "中鋼", -3000, -400, -50)
    q("20260828", "2027", "大成鋼", -500, -80, -10)
    conn.commit()
    conn.close()
    items = [{"stock_id": "2330", "stock_name": "台積電", "close": 100}]
    annotate_items_with_sector_flow(db, "20260828", items)
    assert items[0].get("sector_inflow")
    assert "半導體" in (items[0].get("sector_flow_label") or "")
    assert items[0].get("industry_face") == "半導體業"
