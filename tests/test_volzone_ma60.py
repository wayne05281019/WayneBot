# -*- coding: utf-8 -*-
"""大量區圖：季線 MA60＋右上查詢時間。"""
from __future__ import annotations

import inspect
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_attach_official_ma60_needs_60_bars():
    from vol_zone_chart import attach_official_ma60, ma60_is_rising

    closes = list(range(100, 175))  # 75 bars rising → MA60 有足夠近窗
    df = pd.DataFrame(
        {
            "date": [f"20260{i:03d}" for i in range(len(closes))],
            "close": closes,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "volume": [1000] * len(closes),
        }
    )
    out = attach_official_ma60(df)
    assert "ma60" in out.columns
    assert pd.isna(out["ma60"].iloc[58])
    assert float(out["ma60"].iloc[-1]) == pytest.approx(sum(closes[-60:]) / 60.0)
    assert ma60_is_rising(out["ma60"], slope_bars=5) is True

    flat = attach_official_ma60(
        pd.DataFrame({"close": [10.0] * 80})
    )
    assert ma60_is_rising(flat["ma60"], slope_bars=5) is False


def test_paint_draws_ma60_and_query_stamp():
    from vol_zone_chart import _paint_volume_zone, _label_ma_left

    src = inspect.getsource(_paint_volume_zone)
    assert "_MA60" in src and "_MA20" in src
    assert "format_card_query_stamp" in src
    assert "fig.text" in src and "0.985" in src  # 整圖右上時間戳
    assert "大量區壓" in src and "大量區撐" in src
    assert "linewidth=1.35" in src
    assert "_label_ma_left" in src
    assert 'lab="月線"' in src and 'lab="季線"' in src
    assert "left=0.050" in src  # 左縮右鬆放大 K 區
    assert "draw_ma20=False" in src
    lab_src = inspect.getsource(_label_ma_left)
    assert "_local_hl" in lab_src  # 附近 K 包絡避讓
    assert "half_h" in lab_src


def test_label_ma_left_stays_clear_of_candle_envelope():
    """月線／季線標盒不准落在附近 K 高低包絡內。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from vol_zone_chart import _label_ma_left

    n = 40
    xs = np.arange(n, dtype=float)
    # 左段均線穿進 K；中左才離開高點上方
    highs = np.full(n, 110.0)
    lows = np.full(n, 90.0)
    vals = np.full(n, 100.0)
    highs[8:14] = 105.0
    lows[8:14] = 95.0
    vals[8:14] = 112.0  # 明確在高點上方
    fig, ax = plt.subplots()
    ax.set_ylim(80, 130)
    ax.set_xlim(-1, n)
    _label_ma_left(ax, xs, highs, lows, lab="月線", vals=vals, color="#f9a825", face="#fffde7")
    texts = [t for t in ax.texts if t.get_text() == "月線"]
    assert texts
    y = float(texts[0].get_position()[1])
    x = float(texts[0].get_position()[0])
    j = int(round(x))
    i0, i1 = max(0, j - 2), min(n - 1, j + 2)
    loc_hi = float(np.nanmax(highs[i0 : i1 + 1]))
    loc_lo = float(np.nanmin(lows[i0 : i1 + 1]))
    half_h = (130 - 80) * 0.028
    assert y - half_h >= loc_hi - 1e-6 or y + half_h <= loc_lo + 1e-6
    plt.close(fig)


def test_prepare_loads_ma60_warm_bars():
    from vol_zone_chart import prepare_volume_zone

    src = inspect.getsource(prepare_volume_zone)
    assert "VOL_ZONE_MA60_WARM" in src or "attach_official_ma60" in src
    assert "attach_official_ma60" in src
    assert "attach_official_ma20" in src


def test_render_volume_zone_includes_ma60_column(tmp_path):
    from vol_zone_chart import (
        clear_vol_zone_render_cache,
        prepare_volume_zone,
        render_volume_zone_png,
    )

    clear_vol_zone_render_cache()
    db = get_db_path()
    pack = prepare_volume_zone("2330", "台積電", db, str(tmp_path / "x.jpg"))
    assert pack is not None
    assert "ma60" in pack["view"].columns
    assert "ma20" in pack["view"].columns
    ma60 = pd.to_numeric(pack["view"]["ma60"], errors="coerce")
    ma20 = pd.to_numeric(pack["view"]["ma20"], errors="coerce")
    assert ma60.notna().sum() >= 10
    assert ma20.notna().sum() >= 10
    # 近窗第一根就要有線（暖機）
    assert pd.notna(ma20.iloc[0])
    assert pd.notna(ma60.iloc[0])
    out = render_volume_zone_png("2330", "台積電", db, str(tmp_path / "2330_vz.jpg"))
    assert out and os.path.isfile(out)
    assert os.path.getsize(out) > 20000


def test_volzone_ma60_verify_gate_never_promotes_buy(tmp_path):
    from volzone_ma60_verify import (
        TRACK_VARIANTS,
        VARIANT_CURRENT,
        VARIANT_MA60_RISING,
        ensure_tables,
        gate_status,
        rank_pool,
    )
    import sqlite3

    assert VARIANT_CURRENT in TRACK_VARIANTS
    assert VARIANT_MA60_RISING in TRACK_VARIANTS
    ranked = rank_pool(
        [
            {
                "stock_id": "B",
                "dist_to_press_pct": 2.0,
                "vol_ratio": 0.5,
                "close": 100,
                "pressure": 105,
                "support": 90,
            },
            {
                "stock_id": "A",
                "dist_to_press_pct": 0.3,
                "vol_ratio": 0.2,
                "close": 104,
                "pressure": 105,
                "support": 90,
            },
        ],
        "sideways",
    )
    assert ranked[0]["stock_id"] == "A"
    db = str(tmp_path / "g.db")
    sqlite3.connect(db).close()
    ensure_tables(db)
    g = gate_status(db)
    assert g.get("promote_buy_signals") is False
    assert g.get("promote_ready") is False


def test_volzone_ma60_verify_persist_and_gate(tmp_path):
    from volzone_ma60_verify import (
        VARIANT_CURRENT,
        VARIANT_MA60_RISING,
        ensure_tables,
        gate_status,
        persist_ranked,
        optimize_status_one_liner,
    )

    db = str(tmp_path / "m.db")
    # minimal empty market db file so tape_store_path works beside it
    import sqlite3

    sqlite3.connect(db).close()
    ensure_tables(db)
    rows = [
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pressure": 105.0,
            "support": 90.0,
            "vol_ratio": 0.4,
            "dist_to_press_pct": 1.0,
            "ma60_rising": 1,
        }
    ]
    assert persist_ranked(db, "20260901", "sideways", VARIANT_CURRENT, rows) == 1
    assert persist_ranked(db, "20260901", "sideways", VARIANT_MA60_RISING, rows) == 1
    g = gate_status(db)
    assert g["promote_buy_signals"] is False
    assert g["promote_ready"] is False
    assert "季線" in optimize_status_one_liner(db) or "大量區" in optimize_status_one_liner(db)


def test_judge_tape_hooks_volzone_ma60():
    import judge_tape

    src = inspect.getsource(judge_tape._snapshot_pressure_support)
    assert "volzone_ma60_verify" in src
    assert "volzone_ma60_night_tick" in src


def test_button_catalog_lists_volzone_ma60():
    from button_silent_verify import catalog

    rows = catalog()
    hit = [r for r in rows if "volzone_ma60" in (r.get("kinds") or ())]
    assert hit
    assert hit[0]["status"] == "external"
