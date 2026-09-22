# -*- coding: utf-8 -*-
"""話筒各鈕官方基準日同一套；出圖直出 JPEG 少一趟 PNG。"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile
from pathlib import Path

from PIL import Image
from wayne_db import ensure_core_schema


def test_market_as_of_matches_screen_not_newer_index(tmp_path, monkeypatch):
    from taiwan_market import ensure_index_daily_table, resolve_market_as_of

    db = str(tmp_path / "m.db")
    ensure_core_schema(db)
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
        VALUES ('20260922', 'TWII', 28000, 1e9, 0.1, 27900, 27000, 'bull', 't')
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "trading_calendar.resolve_screen_as_of", lambda *a, **k: "20260919"
    )
    assert resolve_market_as_of(db) == "20260919"
    assert resolve_market_as_of(db, "20260922") == "20260919"


def test_industry_asof_fallback_not_max_quote(tmp_path, monkeypatch):
    from industry_brief import _asof

    db = str(tmp_path / "i.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO daily_quotes("
        "date,stock_id,stock_name,market,open,high,low,close,volume,"
        "turnover_k,pct_change,avg_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("20260921", "2330", "台積電", "TW", 1, 1, 1, 1, 1, 1, 0, 1),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setattr("trading_calendar.fuse_end_trading_date", lambda now=None: "20260918")
    assert _asof(db) == "20260918"


def test_dongzhu_page_uses_zh_date():
    from biaoke_field_scan import dongzhu_page

    html = dongzhu_page(
        "missing.db",
        data={
            "cap": "20260921",
            "chip_cap": "20260918",
            "field": "",
            "line": "還沒對上底部蠢蠢的次族群，不准發明。不是買訊。",
        },
    )
    assert "官方收 2026/09/21（一）" in html
    assert "法人日 2026/09/18（五）" in html


def test_phone_feature_charts_save_jpeg():
    from biaoke_chart import render_biaoke_structure_png
    from chips import render_chips_png
    from index_kline_chart import render_index_kline_png
    from industry_card import render_industry_png as industry_src

    assert "_savefig_lookup_png" in inspect.getsource(render_chips_png)
    assert "_savefig_lookup_png" in inspect.getsource(render_index_kline_png)
    assert "_savefig_lookup_png" in inspect.getsource(render_biaoke_structure_png)
    assert 'save(\n        out, "JPEG"' in inspect.getsource(industry_src) or '"JPEG"' in inspect.getsource(
        industry_src
    )


def test_chips_render_is_jpeg():
    from chips import render_chips_png

    rows = [
        {
            "date": "20260921",
            "stock_name": "南亞",
            "close": 242.5,
            "volume": 169523,
            "foreign_net": 10702,
            "trust_net": 1266,
            "dealer_net": 1041,
            "three_net": 13009,
            "ratio_pct": 7.7,
            "acc_10d": 63634,
        }
    ]
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        out = render_chips_png(rows, path, stock_id="1303")
        assert out and os.path.isfile(out)
        with Image.open(out) as im:
            assert im.format == "JPEG"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_market_page_date_uses_weekday(tmp_path, monkeypatch):
    from taiwan_market import ensure_index_daily_table, format_taiwan_market_page_html

    db = str(tmp_path / "p.db")
    ensure_core_schema(db)
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    for i in range(1, 25):
        d = f"202608{i:02d}"
        close = 22000.0 + i * 50
        conn.execute(
            """
            INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
            VALUES (?, 'TWII', ?, 1e9, 0.1, ?, ?, 'bull', 't')
            """,
            (d, close, close - 100, close - 200),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr("taiwan_market.resolve_market_as_of", lambda *a, **k: "20260821")
    html = format_taiwan_market_page_html(str(db), "20260821")
    assert "2026/08/21（五）" in html
    assert Path("bot_servers.py").read_text(encoding="utf-8").count("_prepare_lookup_album_photo") >= 3
