# -*- coding: utf-8 -*-
"""破撐／過壓下一層（次大量區壓+撐）＋原文目標；非買訊。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from biaoke_next_support import (
    NONE_LABEL,
    WRITTEN_ABSOLUTE_TARGETS,
    attach_next_support,
    close_broke_vol_support,
    close_over_vol_pressure,
    collect_next_support_candidates,
    find_secondary_vol_zone,
    find_secondary_vol_zone_support,
    pick_layer_label_along_line,
    reason_next_support_line,
    resolve_next_support,
    written_target_label,
    written_targets_for,
)


def _bars_break_support():
    """近窗爆大量日低＝100；末日收 90 破撐。另有次大量低 80 高 95。"""
    day = date(2026, 8, 1)
    rows = []
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 10:
            # 次大量：低 80 高 95
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


def _bars_over_pressure():
    """主大量區高 130；末日收 140 過壓。另有更早次大量高 160 低 140。"""
    day = date(2026, 8, 1)
    rows = []
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 145, 160, 140, 150, 18000
        elif i == 18:
            o, h, l, c, v = 110, 130, 100, 120, 25000
        elif i == 35:
            o, h, l, c, v = 132, 142, 128, 140, 4000
        else:
            px = 115 + i * 0.1
            o, h, l, c, v = px, px + 3, px - 3, px + 0.5, 1500
        rows.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "stock_id": "7777",
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
    assert "飆大原文目標" in written_target_label(2000)
    assert "下一撐" not in written_target_label(2000)
    assert "3081" in WRITTEN_ABSOLUTE_TARGETS
    assert all(t["price"] != 2000 for t in written_targets_for("3017"))


def test_close_broke_uses_close_not_intraday_low():
    assert close_broke_vol_support(close=90, support=100) is True
    assert close_broke_vol_support(close=100, support=100) is False
    assert close_broke_vol_support(close=101, support=100) is False
    assert close_over_vol_pressure(close=140, pressure=130) is True
    assert close_over_vol_pressure(close=130, pressure=130) is False


def test_secondary_vol_zone_pair_below_broken():
    bars = _bars_break_support()
    sec = find_secondary_vol_zone_support(
        bars, broken_lo=100.0, exclude_date="20260819", close=90
    )
    assert sec is not None
    assert float(sec["price"]) == 80.0
    assert float(sec["high"]) == 95.0
    assert sec["source"] == "次大量區撐"
    layer = find_secondary_vol_zone(
        bars, direction="below", ref_lo=100.0, exclude_date="20260819", close=90
    )
    assert layer is not None
    assert float(layer["low"]) == 80.0
    assert float(layer["high"]) == 95.0
    assert "下一層撐" in str(layer.get("label_hold") or "")
    assert "下一層壓" in str(layer.get("label_press") or "")


def test_resolve_next_layer_pair_and_none():
    bars = _bars_break_support()
    pack = resolve_next_support(
        bars,
        sid="9999",
        close=90,
        support=100,
        pressure=130,
        spike_date="20260819",
        under_support=True,
    )
    assert pack["broke"] is True
    assert pack["over"] is False
    assert pack["main_zone_unchanged"] is True
    assert pack["layer"] is not None
    assert float(pack["layer"]["low"]) == 80.0
    assert float(pack["layer"]["high"]) == 95.0
    assert pack["primary"] is not None
    assert float(pack["primary"]["price"]) == 80.0
    assert pack["none_label"] == ""
    assert "下一層" in (pack.get("reason_line") or "")
    assert "非買訊" in (pack.get("reason_line") or "")

    # 無更低結構：全列低都 ≥ 破撐 → 暫無
    flat = []
    day = date(2026, 9, 1)
    for i in range(30):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 110, 120, 105, 115, 9000
        elif i == 29:
            o, h, l, c, v = 104, 106, 100, 102, 2000
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
    if not pack2.get("layer"):
        assert pack2["none_label"] == NONE_LABEL
        assert pack2["primary"] is None


def test_over_pressure_next_layer():
    bars = _bars_over_pressure()
    pack = resolve_next_support(
        bars,
        sid="7777",
        close=140,
        support=100,
        pressure=130,
        spike_date="20260819",
        over_pressure=True,
    )
    assert pack["over"] is True
    assert pack["broke"] is False
    assert pack["layer"] is not None
    assert float(pack["layer"]["high"]) == 160.0
    assert float(pack["layer"]["low"]) == 140.0
    assert "下一層" in (pack.get("reason_line") or "")


def test_channel_not_named_next_support():
    """平行撐可另畫，但不進下一層主候選、不准搶名。"""
    bars = _bars_break_support()
    cands = collect_next_support_candidates(
        bars,
        sid="9999",
        broken_lo=100,
        spike_date="20260819",
        channel={"kind": "desc", "base_now": 85.0, "pos": "破平行撐"},
        close=90,
    )
    assert cands
    assert all(c.get("source") in ("次大量區撐", "次大量區壓") for c in cands)
    assert all("平行" not in str(c.get("source") or "") for c in cands)
    assert all("下一撐：平行" not in str(c.get("label") or "") for c in cands)


def test_written_not_called_next_support():
    bars = _bars_break_support()
    for r in bars:
        r["stock_id"] = "3081"
    bars[-1]["close"] = 2200
    pack = resolve_next_support(
        bars,
        sid="3081",
        close=2200,
        support=2500,
        under_support=True,
    )
    # 原文只在 written，不進下一撐名
    assert any(abs(float(w["price"]) - 2000) < 1e-6 for w in pack.get("written") or [])
    for c in pack.get("candidates") or []:
        assert c.get("source") != "原文目標"
        assert "原文目標" not in str(c.get("label") or "")


def test_reason_line_names_next_layer():
    line = reason_next_support_line(
        broken_lo=2940,
        layer={"low": 2000, "high": 2200},
        distribution=True,
    )
    assert "2940" in line.replace(",", "")
    assert "2000" in line.replace(",", "")
    assert "下一層" in line
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
    if ns.get("layer"):
        assert "下一層" in str(proj.get("label") or "") or "下一層" in str(
            ns.get("reason_line") or ""
        )
    notes = " ".join(info.get("notes") or [])
    assert "收破大量區撐" in notes or NONE_LABEL in notes


def test_chiifeng_written_not_on_other_stock():
    pack = resolve_next_support(
        _bars_break_support(),
        sid="2330",
        close=90,
        support=100,
        under_support=True,
    )
    assert all(
        abs(float(w.get("price") or 0) - px) > 1e-6
        for w in pack.get("written") or []
        for px in (2700, 3000, 2000)
    )
    pack2 = resolve_next_support(
        _bars_break_support(), sid="3017", close=90, support=100, under_support=True
    )
    px = {float(w["price"]) for w in pack2.get("written") or []}
    assert 3000.0 in px and 2700.0 in px


def test_pick_layer_label_avoids_candle_cluster():
    """下一層標沿線掃位：密 K 區代價高，空白段勝出（不准寫死左右）。"""
    n = 80
    highs = [2100.0] * n
    lows = [1900.0] * n
    for i in range(40, n):
        highs[i] = 1950.0
        lows[i] = 1800.0
    cx, ha, box = pick_layer_label_along_line(
        y=2010.0,
        text="下一層壓 2,010",
        xmin=-0.3,
        xmax=float(n) + 0.5,
        highs=highs,
        lows=lows,
        tag_size=9.0,
    )
    # 0–39 穿 2010；應落在空白（左緣外側／右側空窗／右溝），不准停密 K 中段
    assert ha in ("left", "right", "center")
    assert box[0] < box[1]
    mid = 0.5 * (box[0] + box[1])
    assert mid < 5.0 or mid > 35.0 or box[1] < 0.0


def test_layer_tag_size_delta_uniform():
    """下一層壓／撐整組同一字級（結構＝大量區）；不准各走各的。"""
    from biaoke_next_support import LAYER_TAG_PT, LAYER_TAG_SIZE_FLOOR
    import inspect
    from biaoke_next_support import paint_written_and_next_levels

    assert LAYER_TAG_PT >= LAYER_TAG_SIZE_FLOOR
    src = inspect.getsource(paint_written_and_next_levels)
    assert "_layer_tag_size" in src
    assert "LAYER_TAG_PT" in src
    assert 'layer_labels="smart"' in open("biaoke_chart.py", encoding="utf-8").read()


def test_paint_uses_cjk_fontproperties():
    """第 4 張水平標必須帶 fontproperties，避免 DejaVu 方塊亂碼。"""
    import inspect

    from biaoke_next_support import paint_written_and_next_levels

    src = inspect.getsource(paint_written_and_next_levels)
    assert "fontproperties" in src
    assert "_cjk_fp" in src or "_fp" in src
    assert "pick_layer_label_along_line" in src or "layer_labels" in src
    assert 'layer_labels="smart"' in open("vol_zone_chart.py", encoding="utf-8").read()


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
        hi = float(st.get("spike_high") or 0)
        close = float(bars[-1].get("close") or 0)
        pack = resolve_next_support(
            bars[-80:],
            sid=sid,
            close=close,
            support=lo,
            pressure=hi,
            spike_date=str(st.get("spike_date") or ""),
        )
        labels = [w.get("label") for w in pack.get("written") or []]
        assert any(str(int(expect_px)) in (x or "").replace(",", "") for x in labels)
        if pack.get("broke"):
            assert pack.get("main_zone_unchanged") is True
            if pack.get("layer"):
                assert float(pack["layer"]["low"]) > 0
                assert float(pack["layer"]["high"]) > 0
            elif not pack.get("primary"):
                assert pack.get("none_label") == NONE_LABEL
