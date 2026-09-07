# -*- coding: utf-8 -*-
"""籌碼K細項解析／快取；產業圖卡小框。"""
from __future__ import annotations

import os

from PIL import Image

from industry_fine import parse_cmoney_forum_industry, save_fine_industry


FIXTURE_2330 = """
<html><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList","itemListElement":[
    {"@type":"ListItem","position":1,"name":"首頁","item":"https://www.cmoney.tw/forum"},
    {"@type":"ListItem","position":2,"name":"台股大盤行情","item":"https://www.cmoney.tw/forum/stock"},
    {"@type":"ListItem","position":3,"name":"電子上游-IC-代工","item":"https://www.cmoney.tw/forum/category/C23020"},
    {"@type":"ListItem","position":4,"name":"台積電","item":"https://www.cmoney.tw/forum/stock/2330"}
  ]}
]}
</script></html>
"""

FIXTURE_2408 = """
<html><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList","itemListElement":[
    {"@type":"ListItem","position":3,"name":"電子上游-記憶體製造","item":"https://www.cmoney.tw/forum/category/C23030"},
    {"@type":"ListItem","position":4,"name":"南亞科","item":"https://www.cmoney.tw/forum/stock/2408"}
  ]}
]}
</script></html>
"""


def test_parse_cmoney_foundry_and_memory():
    a = parse_cmoney_forum_industry(FIXTURE_2330)
    assert a["chain"] == "電子上游-IC-代工"
    assert a["tags"] == ["電子上游", "IC", "代工"]
    assert a["tags"][-1] == "代工"
    assert a["cat_id"] == "C23020"
    b = parse_cmoney_forum_industry(FIXTURE_2408)
    assert b["tags"][-1] == "記憶體製造"
    assert parse_cmoney_forum_industry("") is None
    assert parse_cmoney_forum_industry("<html>no json</html>") is None


def test_industry_html_and_png_show_fine_chips(tmp_path):
    import sqlite3

    from fundamentals import ensure_fundamentals_tables
    from industry_brief import format_industry_html
    from industry_card import render_industry_png
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "ind.db")
    ensure_core_schema(path)
    ensure_fundamentals_tables(path)
    conn = sqlite3.connect(path)
    now = "2026-08-31T00:00:00"
    for sid, name, yoy in (
        ("2330", "台積電", 44.7),
        ("2408", "南亞科", 719.6),
        ("5351", "鈺創", 590.8),
        ("2303", "聯電", 5.0),
    ):
        conn.execute(
            "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
            (sid, name, "TWSE", "STOCK", "半導體業", now),
        )
        conn.execute(
            "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, "202607", name, "TW", "半導體業", 1000, 1.0, yoy, yoy),
        )
        conn.execute(
            "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, 2026, 2, name, "TW", 10000, 1000, 40.0, 400, 300, 1.0),
        )
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("20260904", sid, name, "TW", 100, 101, 99, 100, 10000, 50000, 1.0, 100, 100, 0, 0),
        )
    conn.commit()
    conn.close()
    save_fine_industry(
        path,
        {"stock_id": "2330", "chain": "電子上游-IC-代工", "tags": ["電子上游", "IC", "代工"], "cat_id": "C23020"},
    )
    save_fine_industry(
        path,
        {"stock_id": "2408", "chain": "電子上游-記憶體製造", "tags": ["電子上游", "記憶體製造"], "cat_id": "C23030"},
    )
    save_fine_industry(
        path,
        {"stock_id": "5351", "chain": "電子上游-記憶體IC設計", "tags": ["電子上游", "記憶體IC設計"], "cat_id": "C30018"},
    )
    html = format_industry_html("2330", path, allow_fetch=False)
    assert "[代工]" in html or "[IC]" in html
    assert "籌碼K" in html
    assert "[記憶體製造]" in html
    assert "這族" not in html
    html_title = html.split("\n", 1)[0]
    assert "台積電" in html_title
    assert "[代工]" in html_title
    from industry_fine import chip_color

    assert chip_color("代工") != chip_color("記憶體製造")
    assert chip_color("LED照明及光元件") != chip_color("代工")

    png = str(tmp_path / "2330_industry.png")
    out = render_industry_png("2330", path, png, allow_fetch=False)
    assert out and os.path.isfile(out)
    with Image.open(out) as im:
        assert im.size[0] == 1080
        assert im.size[1] >= 900
        assert im.size[0] + im.size[1] < 10000
        xs = []
        for y in range(44, 90):
            for x in range(30, im.width - 30, 2):
                r, g, b = im.getpixel((x, y))[:3]
                if b >= 180 and g >= 150 and r <= 210:
                    xs.append(x)
        assert xs, "產業說明 kicker missing"
        cx = sum(xs) / len(xs)
        assert abs(cx - im.width / 2) < 48, cx
    assert os.path.getsize(out) > 20_000


def test_chip_text_origin_centers_ink_box():
    from industry_card import _card_font, centered_text_xy

    font = _card_font(26, bold=True)
    box = (40.0, 20.0, 220.0, 66.0)
    x, y = centered_text_xy(font, "代工", box)
    bbox = font.getbbox("代工")
    ink_cx = x + (bbox[0] + bbox[2]) / 2.0
    ink_cy = y + (bbox[1] + bbox[3]) / 2.0
    assert abs(ink_cx - (box[0] + box[2]) / 2.0) < 0.51
    assert abs(ink_cy - (box[1] + box[3]) / 2.0) < 0.51


def test_draw_fine_chip_ink_near_center():
    import numpy as np

    from industry_card import _card_font, draw_fine_chip

    font = _card_font(26, bold=True)
    im = Image.new("RGB", (360, 140), (22, 34, 48))
    box = (50, 40, 250, 86)
    draw_fine_chip(im, box, "代工", (8, 72, 78), (8, 72, 78), (255, 255, 255), font)
    arr = np.array(im)
    x0, y0, x1, y1 = box
    crop = arr[y0 + 8 : y1 - 8, x0 + 10 : x1 - 10]
    lum = crop.mean(axis=2)
    ys, xs = np.where(lum > 200)
    assert xs.size > 20
    cx = xs.mean() + 10
    cy = ys.mean() + 8
    assert abs(cx - (x1 - x0) / 2.0) < 5
    assert abs(cy - (y1 - y0) / 2.0) < 5


def test_parse_category_index_and_bulk_sync(tmp_path, monkeypatch):
    from industry_fine import parse_cmoney_category_index, sync_all_fine_industry
    from wayne_db import ensure_core_schema

    html = 'href="/forum/category/C23020">\n              IC-代工\n            '
    assert parse_cmoney_category_index(html)["C23020"] == "IC-代工"
    path = str(tmp_path / "bulk.db")
    ensure_core_schema(path)
    monkeypatch.setattr("industry_fine.SEED_PATH", str(tmp_path / "no-seed.json"))
    calls = []

    def fake(sid, timeout=8.0):
        calls.append(sid)
        if sid == "2330":
            return {
                "stock_id": sid,
                "chain": "電子上游-IC-代工",
                "tags": ["電子上游", "IC", "代工"],
                "cat_id": "C23020",
                "source": "cmoney_forum",
            }
        if sid == "2408":
            return {
                "stock_id": sid,
                "chain": "電子上游-記憶體製造",
                "tags": ["電子上游", "記憶體製造"],
                "cat_id": "C23030",
                "source": "cmoney_forum",
            }
        return None

    monkeypatch.setattr("industry_fine.fetch_cmoney_fine_industry", fake)
    stats = sync_all_fine_industry(path, ids=["2330", "2408", "9999"], workers=2)
    assert stats["ok"] == 2
    assert stats["fail"] == 1
    assert stats["skip"] == 0
    cached = sync_all_fine_industry(path, ids=["2330", "2408"], workers=2)
    assert cached["skip"] == 2
    assert cached["ok"] == 0
    assert set(calls) == {"2330", "2408", "9999"}

