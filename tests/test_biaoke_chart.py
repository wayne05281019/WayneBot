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


def _px_from_bar(val):
    from biaoke_chart import _px

    return _px(val)
