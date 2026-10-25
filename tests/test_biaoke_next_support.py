# -*- coding: utf-8 -*-
"""破撐下一撐＋原文目標（D4／D5-T1）；非買訊。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from biaoke_next_support import (
    NONE_LABEL,
    WRITTEN_ABSOLUTE_TARGETS,
    attach_next_support,
    close_broke_vol_support,
    collect_next_support_candidates,
    find_secondary_vol_zone_support,
    reason_next_support_line,
    resolve_next_support,
    written_target_label,
    written_targets_for,
)


def _bars_break_support():
    """近窗爆大量日低＝100；末日收 90 破撐。另有次大量低 80、樞紐低。"""
    day = date(2026, 8, 1)
    rows = []
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 10:
            # 次大量：低 80
            o, h, l, c, v = 85, 95, 80, 88, 12000
        elif i == 18:
            # 主大量區：高 130 低 100
            o, h, l, c, v = 110, 130, 100, 120, 25000
        elif i == 35:
            # 收破撐
            o, h, l, c, v = 98, 99, 88, 90, 3000
        else:
            px = 115 - i * 0.2
            o, h, l, c, v = px, px + 3, px - 3, px + 0.5, 1500
        rows.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "stock_id": "9999",
            }
        )
    return rows


def test_written_targets_isolated():
    assert [r["price"] for r in written_targets_for("3081")] == [2000.0]
    assert [r["price"] for r in written_targets_for("3017")] == [3000.0, 2700.0]
    assert written_targets_for("2330") == []
    assert written_targets_for("3008") == []  # 大立光無絕對價不准補
    assert "非買訊" in written_target_label(2000)
    assert "2000" in written_target_label(2000).replace(",", "")
    # 不准串檔
    assert "3081" in WRITTEN_ABSOLUTE_TARGETS
    assert all(t["price"] != 2000 for t in written_targets_for("3017"))


def test_close_broke_uses_close_not_intraday_low():
    assert close_broke_vol_support(close=90, support=100) is True
    assert close_broke_vol_support(close=100, support=100) is False
    assert close_broke_vol_support(close=101, support=100) is False
    # 低刺穿但收守住 → 不算破（呼叫端餵 close）
    assert close_broke_vol_support(close=101, support=100) is False


def test_secondary_vol_zone_below_broken():
    bars = _bars_break_support()
    sec = find_secondary_vol_zone_support(
        bars, broken_lo=100.0, exclude_date="20260819"
    )
    assert sec is not None
    assert float(sec["price"]) == 80.0
    assert sec["source"] == "次大量區撐"


def test_resolve_next_support_primary_and_none():
    bars = _bars_break_support()
    pack = resolve_next_support(
        bars,
        sid="9999",
        close=90,
        support=100,
        spike_date="20260819",
        under_support=True,
    )
    assert pack["broke"] is True
    assert pack["primary"] is not None
    assert float(pack["primary"]["price"]) > 0
    assert float(pack["primary"]["price"]) < 100
    assert pack["none_label"] == ""

    # 無更低結構：全列低都 ≥ 破撐 → 暫無
    flat = []
    day = date(2026, 9, 1)
    for i in range(30):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 110, 120, 105, 115, 9000
        elif i == 29:
            o, h, l, c, v = 104, 106, 100, 102, 2000  # 收破 105
        else:
            o, h, l, c, v = 110, 112, 108, 111, 1000
        flat.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "stock_id": "8888",
            }
        )
    pack2 = resolve_next_support(
        flat, sid="8888", close=102, support=105, spike_date="20260913", under_support=True
    )
    # 可能仍有樞紐低；若完全沒有才暫無
    if not pack2.get("candidates"):
        assert pack2["none_label"] == NONE_LABEL
        assert pack2["primary"] is None


def test_written_as_next_for_lianya():
    bars = _bars_break_support()
    # 把破撐抬到 2500，讓 2000 成為下一原文目標
    for r in bars:
        r["stock_id"] = "3081"
    bars[-1]["close"] = 2200
    # 人工 spike：用 resolve 的 broken_lo
    pack = resolve_next_support(
        bars,
        sid="3081",
        close=2200,
        support=2500,
        under_support=True,
    )
    srcs = [c.get("source") for c in pack.get("candidates") or []]
    assert "原文目標" in srcs
    written_px = [
        float(c["price"])
        for c in pack["candidates"]
        if c.get("source") == "原文目標"
    ]
    assert 2000.0 in written_px


def test_reason_line_names_next():
    line = reason_next_support_line(
        broken_lo=2940,
        primary={"source": "原文目標", "price": 2000},
        distribution=True,
    )
    assert "2940" in line.replace(",", "")
    assert "2000" in line.replace(",", "")
    assert "非買訊" in line
    none_line = reason_next_support_line(broken_lo=100, primary=None, none_label=NONE_LABEL)
    assert NONE_LABEL in none_line


def test_attach_rewrites_abandon_label():
    from biaoke_chart import analyze_structure

    bars = _bars_break_support()
    info = analyze_structure(bars)
    assert info.get("under_support") is True
    attach_next_support(info, sid="9999", bars=bars)
    ns = info.get("next_support") or {}
    assert ns.get("broke") is True
    proj = info.get("project") or {}
    if ns.get("primary"):
        assert "下一撐" in str(proj.get("label") or "") or "朝" in str(
            (ns.get("reason_line") or "")
        )
    notes = " ".join(info.get("notes") or [])
    assert "收破大量區撐" in notes or NONE_LABEL in notes


def test_chiifeng_written_not_on_other_stock():
    cands = collect_next_support_candidates(
        _bars_break_support(),
        sid="2330",
        broken_lo=500,
    )
    assert all(c.get("source") != "原文目標" or float(c.get("price") or 0) not in (2700, 3000, 2000) for c in cands)
    # 奇鋐才有 3000／2700
    c2 = collect_next_support_candidates(
        _bars_break_support(), sid="3017", broken_lo=3500
    )
    px = {float(c["price"]) for c in c2 if c.get("source") == "原文目標"}
    assert 3000.0 in px and 2700.0 in px


@pytest.mark.production_db
def test_sample_3081_3017_resolve_smoke():
    from biaoke_brain import load_bars
    from tests.conftest import require_production_db

    db = require_production_db()
    for sid, expect_px in (("3081", 2000.0), ("3017", 3000.0)):
        bars = load_bars(db, sid, n=120)
        if len(bars) < 40:
            continue
        from biaoke_brain import volume_first_price

        st = volume_first_price(bars[-60:], lookback=40)
        lo = float(st.get("spike_low") or 0)
        close = float(bars[-1].get("close") or 0)
        pack = resolve_next_support(
            bars[-60:],
            sid=sid,
            close=close,
            support=lo,
            spike_date=str(st.get("spike_date") or ""),
        )
        labels = [w.get("label") for w in pack.get("written") or []]
        assert any(str(int(expect_px)) in (x or "").replace(",", "") for x in labels)
        if pack.get("broke") and not pack.get("primary"):
            assert pack.get("none_label") == NONE_LABEL
