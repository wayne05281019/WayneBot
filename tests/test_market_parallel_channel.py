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
    # D4 破撐下一撐刻意標「（非買訊）」；不准當舊禁令掃掉產品免責
    assert "測壓" not in (cap or "")
    assert "（非買訊）" in (cap or "") or "不是買訊" in (cap or "")
    # 圖說應帶平行軌 tip（上升軌／下降壓）
    assert ("上升軌" in (cap or "")) or ("下降壓" in (cap or ""))


def test_market_channel_caption_uses_anchor_dates_not_extended_price():
    """軌標寫兩天低／貼高的那天，不寫右緣延伸價。"""
    from vol_zone_chart import _market_channel_anchor_caption

    ch = {
        "kind": "asc",
        "name_u": "平行壓",
        "name_l": "上升軌",
        "source": "biaoke_named",
        "base": ((1, 44210.3, "20260825"), (2, 45398.4, "20260914")),
        "lower": ((1, 44210.3, "20260825"), (2, 45398.4, "20260914")),
        "touch": (10, 49970.0, "20261006"),
        "rail_now": 50846.0,
        "base_now": 49181.0,
    }
    low = _market_channel_anchor_caption(ch, upper=False)
    up = _market_channel_anchor_caption(ch, upper=True)
    assert "上升軌" in low and "8/25" in low and "44,210" in low
    assert "9/14" in low and "45,398" in low
    assert "平行壓" in up and "10/6" in up and "49,970" in up
    assert "50,846" not in up and "49,181" not in low


def test_market_rail_dash_denser_same_weight_and_color():
    """大盤虛線段更密、空隙更短；線寬與顏色維持。結構圖細虛線常數不動。"""
    from biaoke_chart import _CHANNEL_RAIL_DASH, _CHANNEL_RAIL_LW
    from vol_zone_chart import paint_vol_zone_parallel_channel

    src = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "rail_lw=3.2" in src
    assert "rail_halo=2.3" in src
    assert 'rail_color="#0d47a1"' in src
    assert "rail_dash=_CHANNEL_RAIL_DASH" in src
    assert "(8.2, 3.5)" not in src
    assert "(3.6, 1.2)" not in src
    assert _CHANNEL_RAIL_LW <= 1.2
    assert _CHANNEL_RAIL_DASH == (0, (1.2, 1.2))


def test_rising_rail_label_stays_beside_last_bars():
    """上升軌文字右緣貼最後幾根，不准落到圖中段。"""
    import numpy as np

    from vol_zone_chart import _blank_for_channel_label, _channel_box_blocked

    n = 80
    highs = np.full(n, 100.0)
    lows = np.full(n, 90.0)
    highs[-8:] = 130.0
    lows[-8:] = 118.0
    mas = [np.full(n, 96.0)]
    mas[0][-8:] = 124.0
    cx, cy = _blank_for_channel_label(
        text="上升軌\n8/25低44,210\n9/29低47,573",
        seg=((10.0, 80.0, "a"), (70.0, 100.0, "b")),
        y_now=112.0,
        outside=-1,
        n=n,
        ymin=60.0,
        ymax=160.0,
        dx=7.0,
        dy=6.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
        near_last=True,
    )
    assert cx + 3.5 >= n - 2.0
    box = (cx - 3.5, cx + 3.5, cy - 3.0, cy + 3.0)
    assert not _channel_box_blocked(
        *box,
        n=n,
        ymin=60.0,
        ymax=160.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
    )


def test_channel_label_blank_avoids_candles_and_ma():
    """軌標找空白：盒子不准壓 K、不准壓均線。"""
    import numpy as np

    from vol_zone_chart import _blank_for_channel_label, _channel_box_blocked

    n = 80
    highs = np.full(n, 100.0)
    lows = np.full(n, 92.0)
    mas = [np.full(n, 96.0)]
    seg = ((10.0, 104.0, "a"), (70.0, 112.0, "b"))
    cx, cy = _blank_for_channel_label(
        text="上升軌 49,181",
        seg=seg,
        y_now=112.0,
        outside=-1,
        n=n,
        ymin=70.0,
        ymax=140.0,
        dx=8.0,
        dy=3.5,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
    )
    box = (cx - 4.0, cx + 4.0, cy - 1.75, cy + 1.75)
    assert not _channel_box_blocked(
        *box,
        n=n,
        ymin=70.0,
        ymax=140.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
    )


def test_channel_label_mark_pad_avoids_nav_arrow_band():
    """有 mark_pad：軌標盒不准落進 K 上下箭頭／殘影帶；下軌錨點也不准死貼最右。"""
    import numpy as np

    from vol_zone_chart import _blank_for_channel_label, _channel_box_blocked

    n = 80
    span = 70.0
    mark_pad = span * 0.10
    highs = np.full(n, 100.0)
    lows = np.full(n, 92.0)
    # 近端堆箭：右側高低拉開一點，仍要被 mark_pad 擋住貼箭位
    highs[-12:] = 108.0
    lows[-12:] = 88.0
    mas = [np.full(n, 96.0)]
    seg = ((5.0, 90.0, "a"), (75.0, 90.0, "b"))  # 近似水平下軌
    cx, cy = _blank_for_channel_label(
        text="平行撐 90",
        seg=seg,
        y_now=90.0,
        outside=-1,
        n=n,
        ymin=70.0,
        ymax=140.0,
        dx=8.0,
        dy=3.5,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
        mark_pad=mark_pad,
    )
    box = (cx - 4.0, cx + 4.0, cy - 1.75, cy + 1.75)
    assert not _channel_box_blocked(
        *box,
        n=n,
        ymin=70.0,
        ymax=140.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
        mark_pad=mark_pad,
    )
    # 下軌＋mark_pad：錨點改中右往左掃，不准貼在最右幾根箭堆上
    assert cx < n * 0.85


def test_paint_channel_splits_rails_and_nav_aware_labels():
    """軌線／標可拆畫；avoid_nav_marks 走 mark_pad（跟柱幅）。"""
    from vol_zone_chart import paint_vol_zone_parallel_channel

    src = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "paint_rails" in src and "paint_labels" in src
    assert "avoid_nav_marks" in src
    assert "mark_pad" in src
    assert "candle_span" in src
    assert "0.10" in src


def test_lower_rail_label_prefers_pocket_above_rail():
    """下軌：K 拉離軌上方時，標優先落在軌上空窗（聯亞紅標那種），不准沉到軌下壓▲。"""
    import numpy as np

    from vol_zone_chart import _blank_for_channel_label, _channel_box_blocked

    n = 80
    # 下軌約 90；中右段 K 在 110–125（拉離），左右有更低／更高雜訊
    highs = np.full(n, 118.0)
    lows = np.full(n, 110.0)
    highs[:20] = 105.0
    lows[:20] = 95.0
    highs[-8:] = 130.0
    lows[-8:] = 112.0
    mas = [np.full(n, 108.0)]
    seg = ((5.0, 92.0, "a"), (75.0, 88.0, "b"))  # 緩降下軌 ~90
    y_now = 90.0
    span = 70.0
    mark_pad = span * 0.10
    cx, cy = _blank_for_channel_label(
        text="平行撐 90",
        seg=seg,
        y_now=y_now,
        outside=-1,
        n=n,
        ymin=60.0,
        ymax=160.0,
        dx=8.0,
        dy=4.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
        mark_pad=mark_pad,
    )
    # 應在軌上方空窗（> y_now），且低於窗內低－箭帶
    assert cy > y_now - 1.0
    assert cy < 110.0
    box = (cx - 4.0, cx + 4.0, cy - 2.0, cy + 2.0)
    assert not _channel_box_blocked(
        *box,
        n=n,
        ymin=60.0,
        ymax=160.0,
        highs=highs,
        lows=lows,
        mas=mas,
        placed=[],
        mark_pad=mark_pad,
    )
    assert 0.35 * n < cx < 0.90 * n


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
    assert cap
    assert "爆大量" in cap
    assert "非買訊" not in cap
    assert "庫" not in cap
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


def test_parallel_channel_keeps_fullwidth_gs_right():
    """開平行軌仍維持導航滿版 right＝0.935；不准 0.72 黑邊。"""
    import inspect

    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "0.72 if with_parallel_channel" not in src
    assert "0.935 if with_nav_signals" in src
    assert "MARKET_VOL_ZONE_GS_RIGHT" in src
