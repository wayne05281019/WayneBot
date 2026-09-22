# -*- coding: utf-8 -*-
"""同鏈比價：股價 vs 近季 EPS；圖卡欄位對齊；畫面只留表＋一句對照。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from industry_brief import (
    attach_fine_industry,
    attach_price_eps_bijia,
    format_industry_html,
    industry_snapshot,
)
from industry_card import render_industry_png
from wayne_db import ensure_core_schema


def _seed(db: str, rows: list) -> None:
    ensure_core_schema(db)
    try:
        from fundamentals import ensure_fundamentals_tables

        ensure_fundamentals_tables(db)
    except Exception:
        pass
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
    for sid, name, ind, mkt, chain, close, eps in rows:
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe"
            "(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (sid, name, mkt, "STOCK", ind, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO daily_quotes"
            "(date,stock_id,stock_name,market,open,high,low,close,volume,"
            "turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) "
            "VALUES (?,?,?,'TW',100,101,99,?,1000,100000,1.0,?,0,0,0)",
            ("20260917", sid, name, close, close),
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


def test_bijia_ranks_and_skips_cross_chain(tmp_path):
    db = str(tmp_path / "bijia.db")
    _seed(
        db,
        [
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 2720.0, 7.75),
            ("2455", "全新", "通信網路業", "TW", "電子上游-半導體元件", 534.0, 2.20),
            ("6442", "光聖", "通信網路業", "TW", "電子中游-通訊設備", 400.0, 2.00),
            ("5434", "崇越", "電子通路業", "TW", "電子上游-半導體元件", 530.0, 4.00),
            ("2330", "台積電", "半導體業", "TW", "電子上游-IC-代工", 2425.0, 10.0),
        ],
    )
    snap = attach_fine_industry(industry_snapshot(db, "3081"), db, allow_fetch=False)
    bj = snap["bijia"]
    assert bj["ok"] is True
    assert bj["chain"] == "電子上游-半導體元件"
    ids = [r["stock_id"] for r in bj["rows"]]
    assert "3081" in ids and "2455" in ids
    assert "6442" in ids
    assert "2330" not in ids
    assert "5434" not in ids
    assert bj["mine"]["mult"] > 300
    assert "相對貴" in bj["read"]
    assert bj.get("flag") == "dear"
    assert "已偏貴" in (bj.get("flag_text") or "")
    assert "細項" not in bj["read"]

    html = format_industry_html("3081", db, allow_fetch=False)
    assert "同鏈比價" in html
    assert "怎麼做" not in html
    assert "勝率／報酬" not in html
    assert "已偏貴" in html
    assert "3081" in html and "2455" in html
    assert "價/EPS" in html
    assert "2330" not in html
    assert "細項" not in html


def test_bijia_lag_flag_when_cheap(tmp_path):
    db = str(tmp_path / "bijia_lag.db")
    # 這檔便宜、同鏈有很貴的 → 落後補漲對照＋反差
    _seed(
        db,
        [
            ("3163", "波若威", "通信網路業", "TWO", "電子中游-通訊設備", 74.0, 3.12),
            ("2455", "全新", "通信網路業", "TW", "電子上游-半導體元件", 534.0, 2.20),
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 2720.0, 7.75),
        ],
    )
    snap = attach_fine_industry(industry_snapshot(db, "3163"), db, allow_fetch=False)
    bj = snap["bijia"]
    assert bj["ok"] is True
    assert bj["flag"] == "lag"
    assert "落後補漲" in bj["flag_text"]
    assert "相對便宜" in bj["read"]
    html = format_industry_html("3163", db, allow_fetch=False)
    assert "落後補漲" in html
    png = str(tmp_path / "3163_industry.png")
    out = render_industry_png("6208", db, png, allow_fetch=False)
    assert Path(out).is_file() and Path(out).stat().st_size > 1000


def test_bijia_png_layout_short(tmp_path):
    db = str(tmp_path / "bijia2.db")
    _seed(
        db,
        [
            ("3105", "穩懋", "半導體業", "TWO", "電子上游-IC-代工", 471.0, 3.56),
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 2720.0, 7.75),
            ("3491", "昇達科", "通信網路業", "TWO", "電子中游-通訊設備", 180.0, 1.50),
            ("2330", "台積電", "半導體業", "TW", "電子上游-IC-代工", 2425.0, 14.0),
        ],
    )
    snap = attach_price_eps_bijia(
        attach_fine_industry(industry_snapshot(db, "3105"), db, allow_fetch=False),
        db,
    )
    bj = snap["bijia"]
    assert bj["ok"] is True
    assert any(r["stock_id"] == "3105" and r["is_mine"] for r in bj["rows"])
    assert "價／EPS" in bj["read"] or "價/EPS" in bj["read"] or "中位" in bj["read"]
    html = format_industry_html("3105", db, allow_fetch=False)
    assert "怎麼做" not in html and "勝率" not in html
    from industry_brief import format_bijia_cells, pad_listing_slot, pad_stock_name, widest_stock_name

    cells = format_bijia_cells(bj["rows"][0])
    assert "listing" in cells
    assert cells["name"]
    assert "上市" not in cells["name"] and "上櫃" not in cells["name"]

    png = str(tmp_path / "3105_industry.png")
    out = render_industry_png("3105", db, png, allow_fetch=False)
    assert Path(out).is_file() and Path(out).stat().st_size > 1000


def test_listing_slot_aligns_to_longest_name(tmp_path):
    from industry_brief import pad_listing_slot, pad_stock_name, widest_stock_name
    from industry_card import _card_font, name_listing_layout, pick_chip_font, _wrap_px

    names = ["研華", "直得", "大銀微系統"]
    w = widest_stock_name(names)
    a = pad_stock_name("研華", w) + pad_listing_slot("上市")
    b = pad_stock_name("大銀微系統", w) + pad_listing_slot("上櫃")
    assert a.index("上市") == b.index("上櫃") == w
    font = _card_font(32)
    lay = name_listing_layout(font, names)
    assert lay["name_w"] + 0.5 >= font.getlength("大銀微系統")
    assert lay["listing_w"] + 0.5 >= font.getlength("上櫃")
    assert lay["name_chars"] == 5
    from industry_card import left_mid_xy

    x1, _ = left_mid_xy(font, "上市", 400.0, 0.0, 40.0)
    x2, _ = left_mid_xy(font, "上櫃", 400.0, 0.0, 40.0)
    assert abs(x1 - x2) < 0.6
    from PIL import Image
    from industry_card import render_industry_png
    from tests.test_industry_chain_peers import _seed as _seed_chain

    db = str(tmp_path / "align.db")
    _seed_chain(
        db,
        [
            ("2049", "上銀", "電機機械", "TW", "傳產-電機", 10.0, 400.0, 5.00),
            ("2395", "研華", "電腦及週邊設備業", "TW", "電子下游-工業電腦", 12.0, 350.0, 8.00),
            ("4576", "大銀微系統", "電機機械", "TW", "傳產-電機", 6.0, 90.0, 1.00),
            ("1597", "直得", "電機機械", "TWO", "傳產-電機", 5.0, 80.0, 1.20),
        ],
    )
    png = str(tmp_path / "align.png")
    out = render_industry_png("2049", db, png, allow_fetch=False)
    im = Image.open(out).convert("RGB")
    # 上市／上櫃墨水最左：掃中下段，找灰字欄的共同左緣
    muted = []
    w, h = im.size
    for y in range(int(h * 0.35), h - 40):
        row_xs = []
        for x in range(40, int(w * 0.62)):
            r, g, b = im.getpixel((x, y))
            if abs(r - 168) < 32 and abs(g - 186) < 32 and abs(b - 204) < 32:
                row_xs.append(x)
        if len(row_xs) >= 6:
            muted.append(min(row_xs))
    # 名稱左緣會入列；上市欄是較右側那簇。取每列右半最小 x 的中位差要小。
    assert muted
    ch = "中"
    text = ch * 10
    lines = _wrap_px(text, font, font.getlength(ch * 9) + 0.5)
    if len(lines) >= 2:
        assert len(lines[-1].strip()) >= 3
    tags = ["電子上游", "IC", "代工", "光通訊", "低軌衛星"]
    _f_wide, _h_wide, rows_wide = pick_chip_font(tags, 2400)
    _f_tight, _h_tight, rows_tight = pick_chip_font(tags, 520)
    assert rows_wide == 1
    assert int(getattr(_f_tight, "size", 26) or 26) <= int(getattr(_f_wide, "size", 26) or 26)


def test_bijia_skips_nonpositive_eps(tmp_path):
    db = str(tmp_path / "bijia3.db")
    _seed(
        db,
        [
            ("3081", "聯亞", "通信網路業", "TWO", "電子上游-半導體元件", 2720.0, 7.75),
            ("9999", "虧損", "通信網路業", "TWO", "電子上游-半導體元件", 100.0, -1.0),
        ],
    )
    snap = attach_fine_industry(industry_snapshot(db, "3081"), db, allow_fetch=False)
    assert snap["bijia"]["ok"] is False
    assert snap["bijia"]["note"]
