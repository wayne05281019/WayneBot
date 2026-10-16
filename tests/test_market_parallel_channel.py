# -*- coding: utf-8 -*-
"""大盤大量區平行軌：可重算上升軌／下降壓兩條線；不數浪、非買訊。"""
from __future__ import annotations

import inspect
import os
import sqlite3

import pytest


def _seed_twii_channel(db: str, n: int = 80) -> None:
    """種子：前高後高更低＋低點抬高，讓近窗推得出通道。"""
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            close REAL NOT NULL,
            volume REAL DEFAULT 0,
            pct_change REAL DEFAULT 0,
            ma20 REAL,
            ma60 REAL,
            regime TEXT,
            updated_at TEXT NOT NULL DEFAULT '',
            open REAL,
            high REAL,
            low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    # 用可重算的假柱：一段上坡後回檔再抬低，形成上升軌
    base = 44000.0
    for i in range(n):
        d = f"2026{6 + i // 28:02d}{(i % 28) + 1:02d}"
        # 低點緩升、高點緩升
        lo = base + i * 35.0 + (80 if i in (20, 45) else 0)
        hi = lo + 900 + (400 if i in (30, 55, 70) else 0)
        op = lo + 200
        cl = lo + 400 if i % 3 else lo + 150
        vol = 8e6 + i * 1e4
        if i == 70:
            vol = 3e7
            hi = lo + 1600
        conn.execute(
            "INSERT OR REPLACE INTO index_daily("
            "date,symbol,open,high,low,close,volume,pct_change,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "TWII", op, hi, lo, cl, vol, 0.1, "t"),
        )
    conn.commit()
    conn.close()


def test_market_builder_enables_parallel_channel():
    from index_kline_chart import build_market_vol_zone_chart

    src = inspect.getsource(build_market_vol_zone_chart)
    assert "with_parallel_channel=True" in src
    assert "with_ma5_ma10=True" in src
    assert "with_nav_signals=False" in src
    assert "leave_zero" not in src
    assert "ma60_lower" not in src


@pytest.mark.production_db
def test_infer_vol_zone_parallel_channel_twii_production(production_db):
    from vol_zone_chart import (
        clear_vol_zone_render_cache,
        infer_vol_zone_parallel_channel,
        prepare_volume_zone,
    )

    clear_vol_zone_render_cache()
    pack = prepare_volume_zone("TWII", "加權", production_db, "/tmp/twii-ch-prep.png")
    assert pack is not None
    ch = infer_vol_zone_parallel_channel(pack["view"], bars_face=pack.get("bars"))
    assert ch
    assert ch.get("kind") in ("asc", "desc")
    assert float(ch.get("rail_now") or 0) > float(ch.get("base_now") or 0) > 0
    assert ch.get("name_u") and ch.get("name_l")
    # 不准發明浪號用語
    blob = f"{ch.get('label')} {ch.get('tip')}"
    assert "第5" not in blob and "5浪" not in blob and "九浪" not in blob


@pytest.mark.production_db
def test_market_vol_zone_paints_parallel_channel(tmp_path, production_db):
    from vol_zone_chart import clear_vol_zone_render_cache
    from index_kline_chart import build_market_vol_zone_chart

    clear_vol_zone_render_cache()
    out = str(tmp_path / "twii-parallel.jpg")
    path, cap = build_market_vol_zone_chart(out, db_path=production_db)
    assert path and os.path.isfile(path)
    assert os.path.getsize(path) > 20000
    assert "大量區" in (cap or "")
    assert "非買訊" in (cap or "")
    # 圖說應帶平行軌 tip（上升軌／下降壓）
    assert ("上升軌" in (cap or "")) or ("下降壓" in (cap or ""))


def test_market_vol_zone_canvas_matches_daily_k(tmp_path):
    """大盤大量區畫布＝日K 12.8×7.55、主圖右緣 0.96；個股 figsize 不動。"""
    from PIL import Image

    from index_kline_chart import build_market_vol_zone_chart
    from vol_zone_chart import (
        MARKET_VOL_ZONE_FIG,
        MARKET_VOL_ZONE_GS_RIGHT,
        VOL_ZONE_FIG_H_NAV,
        VOL_ZONE_FIG_W,
        clear_vol_zone_render_cache,
    )
    from wayne_navigator import NAV_CHART_DPI

    assert MARKET_VOL_ZONE_FIG == (12.8, 7.55)
    assert MARKET_VOL_ZONE_GS_RIGHT == 0.96
    assert VOL_ZONE_FIG_W == 12.4
    assert VOL_ZONE_FIG_H_NAV == 9.35
    db = str(tmp_path / "twii.db")
    _seed_twii_channel(db)
    clear_vol_zone_render_cache()
    out = str(tmp_path / "vz.jpg")
    path, cap = build_market_vol_zone_chart(out, db_path=db)
    assert path and os.path.isfile(path)
    assert "大量區" in (cap or "")
    with Image.open(path) as im:
        assert im.size == (
            int(round(MARKET_VOL_ZONE_FIG[0] * NAV_CHART_DPI)),
            int(round(MARKET_VOL_ZONE_FIG[1] * NAV_CHART_DPI)),
        )


def test_stock_lookup_vol_default_no_parallel_flag():
    """查股第 4 張預設不准自動開平行軌（大盤專用旗標）。"""
    import inspect

    from vol_zone_chart import render_lookup_vol_result

    src = inspect.getsource(render_lookup_vol_result)
    assert "with_parallel_channel" not in src
