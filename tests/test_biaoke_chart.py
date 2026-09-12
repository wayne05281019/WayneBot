# -*- coding: utf-8 -*-
from datetime import date, timedelta

from biaoke_chart import (
    analyze_structure,
    chart_caption,
    render_biaoke_structure_png,
)


def _series():
    """爆大量後跌破再站回，後面兩個更低的高。"""
    day = date(2026, 7, 1)
    rows = []
    px = 100.0
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 130, 148, 120, 140, 20000
        elif i == 15:
            o, h, l, c, v = 128, 130, 110, 118, 4000
        elif i == 18:
            o, h, l, c, v = 120, 126, 118, 124, 1800
        elif i == 24:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 30:
            o, h, l, c, v = 128, 132, 124, 126, 1600
        else:
            px = 100 + i * 1.2
            o, h, l, c, v = px, px + 3, px - 3, px + 1, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_structure_flags_wash_and_volume_lines():
    info = analyze_structure(_series())
    assert info.get("struct", {}).get("spike_high") == 148
    assert info.get("struct", {}).get("spike_low") == 120
    assert info.get("wash") is True
    notes = " ".join(info.get("notes") or [])
    assert "爆大量那一天" in notes
    assert "當壓" in notes
    assert "當撐" in notes
    assert "洗盤" in notes
    cap = chart_caption(info, sid="3035", name="智原")
    assert "不是介紹圖" in cap
    assert "決策卡" in cap
    assert "這不是買訊" in cap
    assert "5／9" in cap or "5/9" in cap
    assert "日K" in cap or "日 K" in cap or "官方日K" in cap
    assert "不是15分" in cap
    assert "量先價行" in cap
    assert "爆大量那一天" in cap
    assert "演算" in cap
    assert "不是保證" in cap
    proj = info.get("project") or {}
    assert proj.get("key") == "wash"
    assert abs(float(proj.get("target") or 0) - 148) < 1e-6
    assert "圖上演算" in notes


def _distribution_series():
    """爆大量後先過壓，再掉回撐下＝出貨不是洗盤。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(28):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 100, 120, 96, 118, 18000
        elif i == 14:
            o, h, l, c, v = 118, 128, 116, 126, 4000
        elif i == 20:
            o, h, l, c, v = 110, 114, 92, 94, 3500
        elif i == 27:
            o, h, l, c, v = 95, 98, 90, 92, 1600
        else:
            px = 102 + i * 0.4
            o, h, l, c, v = px, px + 2, px - 2, px + 0.5, 1100
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_structure_flags_distribution_not_wash():
    info = analyze_structure(_distribution_series())
    assert info.get("struct", {}).get("spike_high") == 120
    assert info.get("struct", {}).get("spike_low") == 96
    assert info.get("distribution") is True
    assert info.get("wash") is False
    notes = " ".join(info.get("notes") or [])
    assert "出貨" in notes
    assert "洗盤" not in notes or "不是洗盤" in notes
    proj = info.get("project") or {}
    assert proj.get("key") == "distribution"
    assert abs(float(proj.get("target") or 0) - 96) < 1e-6
    cap = chart_caption(info, sid="3035", name="智原")
    assert "演算" in cap
    assert "不是保證" in cap


def test_render_structure_png(tmp_path):
    from PIL import Image

    out = str(tmp_path / "biaoke.png")
    path = render_biaoke_structure_png(_series(), out, sid="3035", name="智原")
    assert path and path == out
    assert Image.open(path).size[0] >= 1000
    assert (tmp_path / "biaoke.png").stat().st_size > 24_000


def test_real_daily_quotes_numbers_are_exact():
    import os

    from biaoke_brain import load_bars

    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    bars = load_bars(db, "2383", n=120)
    if len(bars) < 40:
        return
    work = bars[-60:]
    info = analyze_structure(work)
    st = info.get("struct") or {}
    lookback = min(40, len(work))
    window = work[-lookback:]
    spike = max(window, key=lambda r: float(r.get("volume") or 0))
    last = work[-1]
    assert float(st.get("spike_high")) == float(spike["high"])
    assert float(st.get("spike_low")) == float(spike["low"])
    assert str(st.get("spike_date") or "").replace("-", "")[:8] == str(spike["date"]).replace("-", "")[:8]
    assert float((info.get("spike_bar") or {}).get("volume")) == float(spike["volume"])
    cap = chart_caption(info, sid="2383", name="台光電")
    assert _px_from_bar(spike["high"]) in cap
    assert _px_from_bar(spike["low"]) in cap
    assert _px_from_bar(last["close"]) in cap
    assert str(int(round(float(spike["volume"])))) in cap.replace(",", "")
    notes = " ".join(info.get("notes") or [])
    assert "3930" in notes or _px_from_bar(spike["low"]) in notes
    proj = info.get("project") or {}
    assert proj.get("key") != "abandon"
    assert float(proj.get("target") or 0) > 0
    assert "圖上演算" in notes
    assert "不是保證" in str(proj.get("label") or "")


def _px_from_bar(val):
    from biaoke_chart import _px

    return _px(val)


def _barely_over_series():
    """剛過壓：最可能先當壓轉撐，不把連點延長當保證續漲。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(28):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 100, 120, 96, 118, 18000
        elif i == 16:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 22:
            o, h, l, c, v = 126, 132, 124, 128, 1800
        elif i == 27:
            o, h, l, c, v = 119, 123, 118, 121, 1400
        else:
            px = 108 + i * 0.3
            o, h, l, c, v = px, px + 2, px - 2, min(px + 0.4, 119), 1100
        rows.append(
            {
                "date": d,
                "stock_id": "2454",
                "stock_name": "聯發科",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def _clearly_over_with_down_rail():
    """明顯過壓但下降連點還壓著：最可能碰到連點延長，不是保證續漲。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 6:
            o, h, l, c, v = 100, 110, 90, 108, 20000
        elif i == 18:
            o, h, l, c, v = 140, 150, 138, 145, 3000
        elif i == 26:
            o, h, l, c, v = 136, 144, 134, 140, 2500
        elif i == 35:
            o, h, l, c, v = 128, 132, 126, 130, 1800
        else:
            px = 100 + i * 0.8
            o, h, l, c, v = px, px + 2, px - 2, px, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "2383",
                "stock_name": "台光電",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_project_barely_over_holds_old_press():
    info = analyze_structure(_barely_over_series())
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "press_hold"
    assert abs(float(proj.get("target") or 0) - 120) < 1e-6
    assert "壓轉撐" in str(proj.get("label") or "")
    assert "不是保證" in str(proj.get("label") or "")


def test_project_clearly_over_uses_down_rail():
    info = analyze_structure(_clearly_over_with_down_rail())
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "rail"
    assert float(proj.get("target") or 0) > 110
    assert "連點" in str(proj.get("label") or "")
    assert "不是保證" in str(proj.get("label") or "")
    path = proj.get("path") or []
    assert len(path) >= 2
    assert path[0][1] == info["closes"][-1]
    assert abs(path[-1][1] - float(proj["target"])) < 1e-6


def test_project_rail_coming_down_caps_price():
    rows = _clearly_over_with_down_rail()
    rows[-1] = dict(rows[-1], open=132, high=135, low=131, close=134)
    info = analyze_structure(rows)
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "rail_cap"
    assert abs(float(proj.get("target") or 0) - 134) < 1e-6
    assert "被軌壓著" in str(proj.get("label") or "")
    assert "不是保證過軌" in str(proj.get("label") or "")
