# -*- coding: utf-8 -*-
"""收盤紅漲綠跌、上市／上櫃／興櫃標、產業期別與量比（含興櫃）。"""
from __future__ import annotations

import os
import sqlite3

from fundamentals import mops_monthly_urls
from industry_brief import (
    format_month_zh,
    format_season_zh,
    industry_snapshot,
    month_display,
    peer_mix_label,
)
from midday_review import format_midday_stock_line
from stock_links import html_stock_anchor
from tg_layout import format_move_plain, html_move
from wayne_db import ensure_core_schema, listing_zh


def test_listing_zh_maps_official_markets():
    assert listing_zh("TW") == "上市"
    assert listing_zh("TWSE") == "上市"
    assert listing_zh("TWO") == "上櫃"
    assert listing_zh("TPEX") == "上櫃"
    assert listing_zh("EM") == "興櫃"
    assert listing_zh({"market_type": "EM"}) == "興櫃"
    assert listing_zh({"universe": "TW"}) == "上市"
    assert listing_zh("") == ""
    assert listing_zh(None) == ""


def test_format_move_plain_red_green_flat():
    assert format_move_plain(20.0, 0.82) == "▲ 20.00（+0.82%）"
    assert format_move_plain(-5.5, -3.05) == "▼ 5.50（-3.05%）"
    assert format_move_plain(0, 0) == "0.00（0.00%）"
    assert "▲" not in format_move_plain(0, 0)
    down = html_move(-5.50, -3.05)
    assert "▼" in down and "5.50" in down
    up = html_move(5.50, 3.05)
    assert "▲" in up and "+3.05%" in up


def test_html_stock_anchor_appends_listing(tmp_path):
    db = str(tmp_path / "a.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
        ("2330", "台積電", "TW", "STOCK", "半導體業"),
    )
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
        ("3105", "穩懋", "TWO", "STOCK", "半導體業"),
    )
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
        ("3644", "凌嘉科", "EM", "STOCK", "半導體業"),
    )
    conn.commit()
    conn.close()
    tw = html_stock_anchor("2330", "台積電", db)
    assert ">2330 台積電</a>　上市" in tw
    assert html_stock_anchor("3105", "穩懋", db).endswith("　上櫃")
    assert html_stock_anchor("3644", "凌嘉科", db).endswith("　興櫃")


def test_midday_line_tags_listing_when_row_has_market():
    row = {
        "stock_id": "4915",
        "stock_name": "致伸",
        "pick_close": 60.8,
        "market": "TW",
    }
    line = format_midday_stock_line(row, {"close": 62.1})
    assert line.startswith("4915 致伸　上市　現在 62.1")
    plain = format_midday_stock_line(
        {"stock_id": "4915", "stock_name": "致伸", "pick_close": 60.8},
        {"close": 62.1},
    )
    assert plain.startswith("4915 致伸　現在 62.1")


def test_month_season_labels_are_human():
    assert format_month_zh("202608") == "2026年8月"
    assert format_season_zh(2026, 2) == "2026年第2季"
    assert month_display("202607", "202608") == "2026年7月（8月尚未公告）"
    assert month_display("202608", "202608") == "2026年8月"


def test_industry_mix_volume_and_lag_month(tmp_path):
    from emerging_quotes import ensure_emerging_table
    from fundamentals import ensure_fundamentals_tables
    from industry_brief import format_industry_html

    db = str(tmp_path / "ind.db")
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    ensure_emerging_table(db)
    conn = sqlite3.connect(db)
    now = "2026-09-09T00:00:00"
    univ = [
        ("2330", "台積電", "TW", "STOCK", "半導體業"),
        ("3105", "穩懋", "TWO", "STOCK", "半導體業"),
        ("3644", "凌嘉科", "EM", "STOCK", "半導體業"),
        ("2454", "聯發科", "TW", "STOCK", "半導體業"),
    ]
    for sid, name, mkt, atype, ind in univ:
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
            (sid, name, mkt, atype, ind, now),
        )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        ("2330", "202608", "台積電", "TW", "半導體業", 1000, 2.0, 40.0, 30.0),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        ("2454", "202607", "聯發科", "TW", "半導體業", 800, 1.0, 8.0, 8.0),
    )
    qsql = "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    conn.execute(qsql, ("20260909", "2330", "台積電", "TW", 100, 101, 99, 100, 10000, 1, 1.0, 100, 0, 0, 0))
    conn.execute(qsql, ("20260909", "3105", "穩懋", "TWO", 100, 101, 99, 100, 2000, 1, 1.0, 100, 0, 0, 0))
    conn.execute(qsql, ("20260909", "2454", "聯發科", "TW", 100, 101, 99, 100, 4000, 1, 1.0, 100, 0, 0, 0))
    conn.execute(
        "INSERT INTO emerging_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260909", "3644", "凌嘉科", "EM", 10, 11, 9, 10, 400, 1, 0.0, 10),
    )
    conn.commit()
    conn.close()

    snap = industry_snapshot(db, "2330")
    assert snap["listing"] == "上市"
    assert snap["peer_n"] == 4
    assert snap["peer_tw"] == 2 and snap["peer_two"] == 1 and snap["peer_em"] == 1
    assert "興櫃1" in peer_mix_label(snap)
    assert snap["month_label"] == "2026年8月"
    assert snap["vol"] == 10000
    assert snap["vol_em_n"] == 1
    assert snap["vol_n"] == 4
    html = format_industry_html("2330", db)
    assert "上市" in html
    assert "2026年8月" in html
    assert "量比" in html
    assert "興櫃" in html

    late = industry_snapshot(db, "2454")
    assert late["month"] == "202607"
    assert "8月尚未公告" in late["month_label"]

    em = industry_snapshot(db, "3644")
    assert em["listing"] == "興櫃"
    html_em = format_industry_html("3644", db)
    assert "興櫃沒有免登入的全市場月營收彙總" in html_em


def test_mops_urls_stay_listed_otc_no_rot_guess():
    blob = " ".join(u for u, _m in mops_monthly_urls("202608"))
    assert "/sii/" in blob and "/otc/" in blob
    assert "/rot/" not in blob


def test_close_paint_uses_triangle_and_color(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from tests.test_sell_discipline import _mini_card_for_png
    from wayne_navigator import _CARD, render_decision_card_png, render_first_glance_png

    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        text = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        seen.append((text, kwargs.get("color")))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    card = _mini_card_for_png(prev_close=130.0, close=143.0, change_pct=10.0, listing="上櫃")
    out = tmp_path / "up.png"
    render_decision_card_png(card, str(out))
    texts = [t for t, _c in seen]
    assert any("▲ 13.00（+10.00%）" in t for t in texts)
    assert any("上櫃" in t for t in texts)
    assert any(c == _CARD["up"] for t, c in seen if "▲" in t)

    seen.clear()
    down = _mini_card_for_png(prev_close=150.0, close=143.0, change_pct=-4.67, listing="上市")
    render_first_glance_png("3441", down, {}, str(tmp_path / "down.png"))
    assert any("▼" in t and "-4.67%" in t for t, _c in seen)
    assert any(c == _CARD["down"] for t, c in seen if "▼" in t)

    seen.clear()
    render_decision_card_png(
        card | {"prev_close": 143.0, "change_pct": 0.0}, str(tmp_path / "flat.png")
    )
    assert any("0.00（0.00%）" in t for t, _c in seen)
    assert not any("▲" in t or "▼" in t for t, _c in seen if "0.00（0.00%）" in t)
    assert os.path.getsize(out) > 1000
