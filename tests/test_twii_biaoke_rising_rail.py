# -*- coding: utf-8 -*-
"""加權上升軌：他自己點的兩天低點優先；大量區軌標不准右緣切斷。"""
from __future__ import annotations

import os
import sqlite3

import pytest


def test_parse_biaoke_rising_rail_low_dates_916_1013():
    from biaoke_chart import parse_biaoke_rising_rail_low_dates

    text = (
        "這幾天的修正大盤推升上升軌道已經改變，"
        "(9/16 10/13兩天低點來畫)代表大盤未來推升脈動變成緩步攻堅"
    )
    pair = parse_biaoke_rising_rail_low_dates(text, as_of="2026-10-14")
    assert pair == ("20260916", "20261013")
    # 沒上升軌語境＝不收
    assert parse_biaoke_rising_rail_low_dates("9/16 10/13兩天低點來畫", as_of="20261014") is None
    # 不准發明浪號進解析
    assert "5" not in (pair[0] + pair[1])


def test_build_asc_channel_from_low_dates_uses_official_lows():
    from biaoke_chart import build_asc_channel_from_low_dates

    rows = []
    # 夠長假柱：9/16、10/13 低點抬高；10/6 當平行壓觸點
    dates = [
        "20260901",
        "20260908",
        "20260916",
        "20260922",
        "20260929",
        "20261006",
        "20261013",
        "20261014",
        "20261015",
    ]
    for i, d in enumerate(dates):
        lo = 45000.0 + i * 350
        if d == "20260916":
            lo = 45546.0
        if d == "20261013":
            lo = 48066.0
        hi = lo + 900 + (800 if d == "20261006" else 0)
        rows.append(
            {
                "date": d,
                "open": lo + 100,
                "high": hi,
                "low": lo,
                "close": lo + 300,
            }
        )
    ch = build_asc_channel_from_low_dates(rows, "20260916", "20261013")
    assert ch
    assert ch.get("source") == "biaoke_named"
    assert ch.get("kind") == "asc"
    (a, b) = ch["base"]
    assert a[2] == "20260916" and abs(float(a[1]) - 45546.0) < 0.1
    assert b[2] == "20261013" and abs(float(b[1]) - 48066.0) < 0.1
    tip = str(ch.get("tip") or "")
    assert "9/16" in tip and "10/13" in tip
    assert "他自己點的兩天低點" in tip
    assert "第5" not in tip and "5浪" not in tip
    assert "不是買訊" in tip


def test_latest_biaoke_named_rising_lows_from_db(tmp_path):
    from biaoke_chart import latest_biaoke_named_rising_lows
    from biaoke_desk import ensure_biaoke_posts_table

    db = str(tmp_path / "t.db")
    ensure_biaoke_posts_table(db)
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO biaoke_posts(id,n,date,time,parent,layer,kind,tags,text,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "p1",
            1,
            "2026-10-14",
            "09:38",
            "",
            0,
            "reply",
            "[]",
            "大盤推升上升軌道已經改變，(9/16 10/13兩天低點來畫)緩步攻堅",
            "t",
        ),
    )
    con.commit()
    con.close()
    got = latest_biaoke_named_rising_lows(db)
    assert got == ("20260916", "20261013", "p1")


def test_paint_vol_zone_channel_labels_outside_axis_gutter():
    """軌標走軸外右溝（blended transform）＋呼叫端收窄 GridSpec right。"""
    import inspect

    from vol_zone_chart import _paint_volume_zone, paint_vol_zone_parallel_channel

    src = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "blended_transform_factory" in src
    assert "clip_on=False" in src
    assert "1.085" in src
    paint_src = inspect.getsource(_paint_volume_zone)
    assert "_gs_right" in paint_src
    assert "with_parallel_channel" in paint_src


@pytest.mark.production_db
def test_twii_prefers_biaoke_916_1013(production_db):
    from vol_zone_chart import (
        clear_vol_zone_render_cache,
        infer_vol_zone_parallel_channel,
        prepare_volume_zone,
    )
    from biaoke_chart import (
        latest_biaoke_named_rising_lows,
        parse_biaoke_rising_rail_low_dates,
    )

    named = latest_biaoke_named_rising_lows(production_db)
    if not named:
        pytest.skip("庫內尚無「兩天低點來畫」原文")
    assert named[0] == "20260916" and named[1] == "20261013"

    clear_vol_zone_render_cache()
    pack = prepare_volume_zone("TWII", "加權", production_db, "/tmp/twii-named-ch.png")
    assert pack is not None
    ch = infer_vol_zone_parallel_channel(
        pack["view"],
        bars_face=pack.get("bars"),
        db_path=production_db,
        stock_id="TWII",
    )
    assert ch
    assert ch.get("source") == "biaoke_named"
    base = ch.get("base") or ()
    assert len(base) == 2
    assert str(base[0][2]).replace("-", "")[:8] == "20260916"
    assert str(base[1][2]).replace("-", "")[:8] == "20261013"
    tip = str(ch.get("tip") or "")
    assert "他自己點的兩天低點" in tip
    assert "8/25" not in tip  # 不准再默默用自動 8/25～*
