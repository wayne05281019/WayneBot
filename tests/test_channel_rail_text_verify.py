# -*- coding: utf-8 -*-
"""平行軌圖／文字準度：幾何一致＋空通道腳註誠實；非買訊。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from channel_rail_text_verify import (
    FACE_DEFAULT,
    KIND,
    PRODUCT_ENTRY,
    TAG_NEAR_LO,
    TAG_NONE,
    classify_channel_day,
    empty_channel_foot_honest,
    gate_status,
    recompute_pos,
    run_skeleton,
    scan_stock_history,
)
from vol_zone_chart import (
    channel_has_drawable_rails,
    vol_zone_parallel_rail_foot_bits,
)


def test_product_entry_always_false():
    assert PRODUCT_ENTRY is False
    assert FACE_DEFAULT is False
    assert KIND == "channel_rail_text"


def test_recompute_pos_desc_buckets():
    pos, alive = recompute_pos(
        kind="desc", last=100.0, rail_now=110.0, base_now=90.0, width=20.0, span=40.0
    )
    assert pos == "下降通道中段" and alive is True
    pos, alive = recompute_pos(
        kind="desc", last=92.0, rail_now=110.0, base_now=90.0, width=20.0, span=40.0
    )
    assert pos == "靠近平行撐" and alive is True
    pos, alive = recompute_pos(
        kind="desc", last=80.0, rail_now=110.0, base_now=90.0, width=20.0, span=40.0
    )
    assert pos == "破平行撐" and alive is True


def test_classify_empty_and_geom_ok():
    empty = classify_channel_day({}, last=100.0, span=20.0)
    assert empty["tag"] == TAG_NONE
    assert empty["geom_ok"] is True
    ch = {
        "kind": "asc",
        "pos": "靠近上升軌",
        "alive": True,
        "rail_now": 120.0,
        "base_now": 100.0,
        "width": 20.0,
    }
    # last near base
    pack = classify_channel_day(ch, last=102.0, span=30.0)
    assert pack["geom_ok"] is True
    assert pack["tag"] == TAG_NEAR_LO


def test_foot_bits_honest_when_no_rails():
    assert channel_has_drawable_rails({}) is False
    bits = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=True, with_nav_signals=False, channel={}
    )
    assert bits["has_rails"] is False
    assert "推不出合格平行軌" in bits["foot2"]
    assert "雙線＝可重算" not in bits["foot2"]
    bits_nav = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=True, with_nav_signals=True, channel={}
    )
    assert "推不出合格平行軌" in bits_nav["quiet_bit"]
    assert "淡灰藍虛線＝平行趨勢" not in bits_nav["quiet_bit"]
    assert empty_channel_foot_honest(
        with_parallel_channel=True, with_nav_signals=False, channel={}
    )
    assert empty_channel_foot_honest(
        with_parallel_channel=True, with_nav_signals=True, channel={}
    )


def test_foot_bits_with_rails_keeps_legend():
    ch = {
        "kind": "desc",
        "pos": "下降通道中段",
        "alive": True,
        "label": "下降壓通道　下降通道中段",
        "rail_now": 110.0,
        "base_now": 90.0,
        "width": 20.0,
    }
    bits = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=True, with_nav_signals=False, channel=ch
    )
    assert bits["has_rails"] is True
    assert "雙線＝可重算" in bits["foot2"]
    assert "下降壓通道" in bits["foot1_suffix"]
    bits_nav = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=True, with_nav_signals=True, channel=ch
    )
    assert bits_nav["quiet_bit"] == "淡灰藍虛線＝平行趨勢（標名＋最新價・不數浪）"


def test_asc_dead_no_desc_copy():
    ch = {
        "kind": "asc",
        "pos": "破上升軌",
        "alive": False,
        "label": "上升軌通道　已失效　未畫下降壓",
        "rail_now": 120.0,
        "base_now": 100.0,
        "width": 20.0,
    }
    bits = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=True, with_nav_signals=False, channel=ch
    )
    assert "未畫下降壓" in bits["foot2"]
    assert "改畫下降壓" not in bits["foot2"]


def _mk_db(tmp_path):
    db = tmp_path / "crt.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE daily_quotes (
            stock_id TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            stock_name TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE stock_universe (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT,
            market_type TEXT,
            asset_type TEXT,
            is_active INTEGER
        )
        """
    )
    day0 = date(2025, 1, 2)
    # 緩升低點＋高點抬高 → 易推升通道
    rows = []
    for i in range(90):
        d = (day0 + timedelta(days=i)).strftime("%Y-%m-%d")
        lo = 100.0 + i * 0.4
        hi = lo + 8.0 + (2.0 if i % 11 == 0 else 0.0)
        cl = lo + 3.0
        rows.append(("2330", d, lo + 1, hi, lo, cl, 1000.0 + i, "測軌"))
    con.executemany(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?)", rows
    )
    con.execute(
        "INSERT INTO stock_universe VALUES ('2330','測軌','TW','STOCK',1)"
    )
    con.commit()
    con.close()
    return str(db)


def test_scan_and_gate_never_buy(tmp_path):
    db = _mk_db(tmp_path)
    pack = scan_stock_history(db, "2330", max_events=12, persist=True)
    assert pack["n"] >= 1
    st = run_skeleton(db, stock_ids=["2330"], limit_stocks=1, max_events=12)
    assert st["ok"] is True
    assert st["product_entry"] is False
    g = st["gate"]
    assert g["promote_ready"] is False
    assert g["product_entry"] is False
    g2 = gate_status(db)
    assert g2["promote_ready"] is False


def test_paint_uses_foot_bits_helper():
    import inspect

    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "vol_zone_parallel_rail_foot_bits" in src
    assert "本圖推不出合格平行軌" in inspect.getsource(
        vol_zone_parallel_rail_foot_bits
    )
