# -*- coding: utf-8 -*-
"""大量區五日／十日線：大盤與個股查股／壓撐話筒同開；非買訊。"""
from __future__ import annotations

import inspect
import os
import sqlite3

import numpy as np
import pandas as pd
import pytest


def test_market_builder_enables_ma5_ma10():
    from index_kline_chart import build_market_vol_zone_chart

    src = inspect.getsource(build_market_vol_zone_chart)
    assert "with_ma5_ma10=True" in src
    assert "with_parallel_channel=True" in src
    assert "with_nav_signals=False" in src


def test_stock_lookup_vol_enables_ma5_ma10():
    """查股第 4 張必須畫五日／十日（#584 標籤 refinement 前提；話筒不得只剩月／季）。"""
    from vol_zone_chart import render_lookup_vol_result, render_volume_zone_result

    src = inspect.getsource(render_lookup_vol_result)
    assert "with_ma5_ma10=True" in src
    # 全面套用：底層預設也開，漏傳旗也不會冒舊臉
    assert (
        inspect.signature(render_volume_zone_result)
        .parameters["with_ma5_ma10"]
        .default
        is True
    )


def test_attach_official_ma5_ma10_min_periods():
    from vol_zone_chart import attach_official_ma5, attach_official_ma10

    closes = [100.0 + i for i in range(12)]
    df = pd.DataFrame(
        {
            "date": [f"202609{i+1:02d}" for i in range(12)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1e6] * 12,
        }
    )
    out = attach_official_ma10(attach_official_ma5(df))
    assert "ma5" in out.columns and "ma10" in out.columns
    assert np.isnan(out["ma5"].iloc[3])
    assert np.isfinite(out["ma5"].iloc[4])
    assert np.isnan(out["ma10"].iloc[8])
    assert np.isfinite(out["ma10"].iloc[9])
    # SMA5 of closes 5..9 (0-based 0-4) = mean(100..104)
    assert abs(float(out["ma5"].iloc[4]) - 102.0) < 1e-9


def test_paint_ma5_ma10_only_when_flag(tmp_path):
    """旗標關＝不畫五日／十日；開＝圖腳註有橙／青。"""
    from vol_zone_chart import clear_vol_zone_render_cache, render_volume_zone_result

    db = str(tmp_path / "twii.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT, close REAL, volume REAL, pct_change REAL,
            ma20 REAL, ma60 REAL, regime TEXT, updated_at TEXT,
            open REAL, high REAL, low REAL,
            PRIMARY KEY (date, symbol)
        )
        """
    )
    base = 27000.0
    for i in range(50):
        d = f"202608{i+1:02d}" if i < 31 else f"202609{i-30:02d}"
        vol = 2e7 if i == 35 else 5e6
        hi = base + 200 + (50 if i == 35 else 0)
        lo = base - 100
        cl = base + i * 2
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, "TWII", cl, vol, 0.1, None, None, "", "", base, hi, lo),
        )
    conn.commit()
    conn.close()

    clear_vol_zone_render_cache()
    off = str(tmp_path / "off.png")
    path_off, _ = render_volume_zone_result(
        "TWII",
        "加權",
        db,
        off,
        with_nav_signals=False,
        with_ma5_ma10=False,
    )
    assert path_off and os.path.isfile(path_off)

    clear_vol_zone_render_cache()
    on = str(tmp_path / "on.png")
    path_on, _ = render_volume_zone_result(
        "TWII",
        "加權",
        db,
        on,
        with_nav_signals=False,
        with_parallel_channel=True,
        with_ma5_ma10=True,
    )
    assert path_on and os.path.isfile(path_on)
    assert os.path.getsize(path_on) > 5000
    # 開旗後圖檔應與關旗不同（有多畫兩條線）
    assert os.path.getsize(path_on) != os.path.getsize(path_off) or open(
        path_on, "rb"
    ).read() != open(path_off, "rb").read()


@pytest.mark.production_db
def test_market_vol_zone_paints_ma5_ma10(tmp_path, production_db):
    from vol_zone_chart import clear_vol_zone_render_cache
    from index_kline_chart import build_market_vol_zone_chart

    clear_vol_zone_render_cache()
    out = str(tmp_path / "twii-ma5-ma10.jpg")
    path, cap = build_market_vol_zone_chart(out, db_path=production_db)
    assert path and os.path.isfile(path)
    assert os.path.getsize(path) > 20000
    # D4 破撐下一撐刻意標「（非買訊）」；不准當舊禁令掃掉產品免責
    assert "測壓" not in (cap or "")
    assert "（非買訊）" in (cap or "") or "不是買訊" in (cap or "")
