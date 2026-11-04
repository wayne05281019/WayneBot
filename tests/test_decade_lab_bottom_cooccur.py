# -*- coding: utf-8 -*-
from scripts.decade_lab_bottom_cooccur import _find_troughs, _lower_wick_ratio, _cooccur_count


def test_lower_wick_and_trough_helpers():
    assert _lower_wick_ratio({"open": 100, "high": 101, "low": 90, "close": 100}) >= 0.45
    bars = []
    px = 100.0
    for i in range(60):
        d = f"202601{i+1:02d}" if i < 28 else f"202602{i-27:02d}"
        # simplify dates as yyyymmdd-like counters
        d = f"2026{1000+i}"
        o = h = l = c = px
        if i == 30:
            l = 80.0
            c = 82.0
            o = 90.0
            h = 91.0
        elif i > 30:
            px = 80 + (i - 30) * 2
            o = h = l = c = px
            h = px + 1
        else:
            px = 100 - i * 0.5
            o = h = l = c = px
            l = px - 0.5
            h = px + 0.5
        bars.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1e6})
    # after trough bounce
    for j in range(31, 41):
        bars[j]["high"] = 80 + (j - 30) * 3
        bars[j]["close"] = 80 + (j - 30) * 2.5
        bars[j]["low"] = 79 + (j - 30)
        bars[j]["open"] = bars[j]["close"]
    hits = _find_troughs(bars)
    assert any(abs(h["low"] - 80) < 1e-6 for h in hits)
    assert _cooccur_count({"a": True, "b": False, "c": True}, ["a", "b", "c"]) == 2
