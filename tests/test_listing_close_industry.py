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
    assert ">2330 台積電</a>　上市（半導體業）" in tw
    win = html_stock_anchor("3105", "穩懋", db)
    assert "上櫃" in win and "光通訊" in win and "低軌衛星" in win
    assert "（半導體業）" not in win
    assert html_stock_anchor("3644", "凌嘉科", db).endswith("　興櫃（半導體業）")
    assert "一線" not in tw and "二線" not in tw


def test_listing_face_marks_turnover_leader_not_yi_er_xian(tmp_path):
    from universe import listing_industry_face

    db = str(tmp_path / "lead.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    for sid, name, mkt, turn in (
        ("2330", "台積電", "TW", 90000),
        ("2454", "聯發科", "TW", 1000),
        ("3105", "穩懋", "TWO", 500),
    ):
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
            (sid, name, mkt, "STOCK", "半導體業"),
        )
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("20260909", sid, name, mkt, 1, 1, 1, 1, 1, turn, 0, 1),
        )
    conn.commit()
    conn.close()
    tsmc = listing_industry_face("2330", db)
    mtk = listing_industry_face("2454", db)
    otc = listing_industry_face("3105", db)
    assert tsmc == "上市（半導體業）　龍頭"
    assert mtk == "上市（半導體業）"
    assert otc == "上櫃　光通訊／低軌衛星"
    assert "一線" not in tsmc + mtk + otc
    assert "二線" not in tsmc + mtk + otc
    assert html_stock_anchor("2330", "台積電", db).endswith("　上市（半導體業）　<code>龍頭</code>")


def test_listing_face_ok_accepts_industry_leader_rejects_yi_er():
    from tests.card_face_audit import listing_face_ok

    assert listing_face_ok("上市")
    assert listing_face_ok("上市（半導體業）")
    assert listing_face_ok("上市（半導體業）　龍頭")
    assert listing_face_ok("上市　電子上游-IC-代工")
    assert listing_face_ok("上市　電子上游-IC-代工　龍頭")
    assert listing_face_ok("上市　成熟製程")
    assert listing_face_ok("上櫃　代工／光通訊／低軌衛星")
    assert listing_face_ok("上市（ETF）")
    assert listing_face_ok("上櫃（半導體業）")
    assert listing_face_ok("興櫃（半導體業）")
    assert not listing_face_ok("一線")
    assert not listing_face_ok("上市　一線")
    assert not listing_face_ok("上市（半導體業）一線")


def test_split_listing_face_keeps_market_and_tags_apart():
    from universe import split_listing_face
    from wayne_navigator import _title_listing_and_industry

    assert split_listing_face("上櫃　代工／光通訊／低軌衛星") == (
        "上櫃",
        "代工／光通訊／低軌衛星",
    )
    assert split_listing_face("上市　成熟製程") == ("上市", "成熟製程")
    assert split_listing_face("上市　機器人　龍頭") == ("上市　龍頭", "機器人")
    assert split_listing_face("上市　電子上游-IC-代工　龍頭") == (
        "上市　龍頭",
        "電子上游-IC-代工",
    )
    assert split_listing_face("上市（半導體業）　龍頭") == (
        "上市（半導體業）　龍頭",
        "",
    )
    listing, industry, _kind = _title_listing_and_industry(
        {
            "listing": "上櫃　代工／光通訊／低軌衛星",
            "fine_industry": "電子上游-IC-代工",
            "industry": "半導體業",
        }
    )
    assert listing == "上櫃"
    assert industry == "代工／光通訊／低軌衛星"


def test_listing_face_emerging_not_overridden_by_stale_otc_quote(tmp_path):
    """日 K 殘列上櫃、卡片走興櫃表 → 市場標仍是興櫃。"""
    from emerging_quotes import ensure_emerging_table
    from universe import listing_industry_face

    db = str(tmp_path / "em.db")
    ensure_core_schema(db)
    ensure_emerging_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
        ("2938", "昶昕", "TWO", "STOCK", "居家生活"),
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260909", "2938", "昶昕", "TWO", 1, 1, 1, 1, 1, 10, 0, 1),
    )
    for i in range(8):
        conn.execute(
            "INSERT INTO emerging_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"2026090{i+1}" if i < 9 else f"202609{i+1}", "2938", "昶昕", "EM", 10, 11, 9, 10, 100, 1, 0.0, 10),
        )
    conn.commit()
    conn.close()
    face = listing_industry_face("2938", db)
    assert face.startswith("興櫃")
    assert "居家生活" in face
    assert "上櫃" not in face
    assert listing_industry_face("2938", db, quote_source="emerging_quotes").startswith("興櫃")


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


def test_industry_mix_volume_and_lag_month(tmp_path, monkeypatch):
    from emerging_quotes import ensure_emerging_table
    from fundamentals import ensure_fundamentals_tables
    from industry_brief import format_industry_html

    monkeypatch.setattr("industry_brief._asof", lambda _p: "20260909")

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
    assert "還沒產業鏈，不拿證交所粗分類硬比" in html
    assert "量比" not in html
    assert "聯發科" not in html

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
