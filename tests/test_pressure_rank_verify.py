# -*- coding: utf-8 -*-
"""壓撐排序靜默對質：第一次優化鍵 vs 現況；飆大只靜默。"""
from __future__ import annotations

from pressure_rank_verify import (
    VARIANT_BIAOKE_SILENT,
    VARIANT_CURRENT,
    VARIANT_FIRST,
    biaoke_hard_cut,
    gate_status,
    optimize_status_one_liner,
    outcome_win,
    rank_key_first,
    rank_pool,
)
from pressure_support_watch import (
    TAG_SIDEWAYS,
    TAG_STAND_SUPPORT,
    TAG_TEST_PRESS,
    rank_key_current,
)


def _row(**kw):
    base = {
        "stock_id": "2330",
        "close": 100.0,
        "pressure": 105.0,
        "support": 90.0,
        "vol_ratio": 0.5,
        "dist_to_press_pct": 1.0,
    }
    base.update(kw)
    return base


def test_first_rank_sideways_thin_before_dist():
    a = _row(stock_id="A", vol_ratio=0.2, dist_to_press_pct=0.4)  # thin
    b = _row(stock_id="B", vol_ratio=0.8, dist_to_press_pct=0.1)  # not thin, closer
    ranked = rank_pool([b, a], TAG_SIDEWAYS, VARIANT_FIRST)
    assert [r["stock_id"] for r in ranked[:2]] == ["A", "B"]


def test_first_rank_test_press_dist_before_thin():
    a = _row(stock_id="A", vol_ratio=0.8, dist_to_press_pct=0.1)
    b = _row(stock_id="B", vol_ratio=0.2, dist_to_press_pct=0.4)
    ranked = rank_pool([b, a], TAG_TEST_PRESS, VARIANT_FIRST)
    assert [r["stock_id"] for r in ranked[:2]] == ["A", "B"]


def test_first_rank_stand_in_band_then_moderate_dist():
    # in band + dist≈2 應優於出帶或太貼壓
    good = _row(
        stock_id="G",
        close=103.0,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=1.9,
        vol_ratio=0.4,
    )
    too_close = _row(
        stock_id="C",
        close=104.8,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=0.2,
        vol_ratio=0.4,
    )
    out_band = _row(
        stock_id="O",
        close=106.0,
        pressure=105.0,
        support=90.0,
        dist_to_press_pct=-0.95,
        vol_ratio=0.3,
    )
    ranked = rank_pool([out_band, too_close, good], TAG_STAND_SUPPORT, VARIANT_FIRST)
    assert ranked[0]["stock_id"] == "G"
    assert ranked[-1]["stock_id"] == "O"


def test_current_unchanged_key_order():
    # 現況：離壓近優先（與第一次橫盤「量縮優先」不同）
    a = _row(stock_id="A", vol_thin_bonus=True, dist_to_press_pct=0.4)
    b = _row(stock_id="B", vol_thin_bonus=False, dist_to_press_pct=0.1)
    assert rank_key_current(b) < rank_key_current(a)
    assert rank_key_first(TAG_SIDEWAYS, a) < rank_key_first(TAG_SIDEWAYS, b)


def test_biaoke_silent_cuts_and_caps():
    dump = _row(stock_id="D", dump_pause=True, vol_ratio=0.2, dist_to_press_pct=0.1)
    ok = [
        _row(stock_id=str(i), vol_ratio=0.2, dist_to_press_pct=0.1 + i * 0.01)
        for i in range(10)
    ]
    ranked = rank_pool([dump] + ok, TAG_TEST_PRESS, VARIANT_BIAOKE_SILENT)
    assert all(r["stock_id"] != "D" for r in ranked)
    assert len(ranked) <= 8
    assert biaoke_hard_cut(dump, TAG_TEST_PRESS) is True


def test_outcome_win_defs():
    bars = [
        {"close": 106, "high": 107, "low": 105},
        {"close": 107, "high": 108, "low": 106},
        {"close": 108, "high": 109, "low": 107},
        {"close": 109, "high": 110, "low": 108},
        {"close": 110, "high": 111, "low": 109},
    ]
    side = outcome_win(
        TAG_SIDEWAYS, pressure=105, support=90, entry=100, bars=bars
    )
    assert side["stand_press"] == 1 and side["win"] == 1
    hold = outcome_win(
        TAG_TEST_PRESS, pressure=105, support=90, entry=100, bars=bars
    )
    assert hold["hold_support"] == 1 and hold["win"] == 1
    broke_bars = list(bars)
    broke_bars[2] = {"close": 80, "high": 90, "low": 79}
    bad = outcome_win(
        TAG_STAND_SUPPORT, pressure=105, support=90, entry=100, bars=broke_bars
    )
    assert bad["broke_support"] == 1 and bad["win"] == 0


def test_gate_biaoke_never_promote_without_first(tmp_path):
    db = str(tmp_path / "m.db")
    # empty evolve → n=0
    g = gate_status(db)
    assert g["n_ok"] is False
    assert g["biaoke_silent_only"] is True
    assert g["squeeze_candidate"] is False
    assert g["promote_ready"] is False
    line = optimize_status_one_liner(db)
    assert "尚未改碼" in line or "繼續收集" in line
    assert VARIANT_CURRENT and VARIANT_FIRST
