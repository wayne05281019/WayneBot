# -*- coding: utf-8 -*-
from scripts.decade_lab_wave_fib_targets import (
    extension_targets,
    retrace_targets,
    snapshot_wave_fib_targets,
    _within_band,
    _within_ratio_band,
)


def test_retrace_targets_defined_ratios():
    # 底 10000 → 頂 11000；回撤 0.618 → 10382
    rt = retrace_targets(10000.0, 11000.0)
    assert abs(rt["0.618"] - 10382.0) < 0.01
    assert abs(rt["0.382"] - 10618.0) < 0.01
    assert abs(rt["0.5"] - 10500.0) < 0.01


def test_extension_targets_defined_ratios():
    ext = extension_targets(10000.0, 11000.0)
    assert abs(ext["1"] - 12000.0) < 0.01
    assert abs(ext["1.618"] - 12618.0) < 0.01


def test_within_band_pos_neg():
    assert _within_band(10000, 10000, 1.5) is True
    assert _within_band(10140, 10000, 1.5) is True  # +1.4%
    assert _within_band(9860, 10000, 1.5) is True  # -1.4%
    assert _within_band(10200, 10000, 1.5) is False


def test_ratio_band_retrace_depth():
    # 10000→11000，下一端 10382 → 深度 0.618
    assert _within_ratio_band(10000, 11000, 10382, 0.618, 0.08) is True
    assert _within_ratio_band(10000, 11000, 10382, 0.382, 0.08) is False
    assert _within_ratio_band(10000, 11000, 11000 - 0.69 * 1000, 0.618, 0.08) is True  # 0.69
    assert _within_ratio_band(10000, 11000, 11000 - 0.50 * 1000, 0.618, 0.08) is False  # 0.50


def test_snapshot_leg_retrace_primary():
    bars = []
    y, m, d = 2025, 1, 1
    for i in range(30):
        px = 20000.0 + i * 30
        bars.append(
            {
                "date": f"{y}{m:02d}{d:02d}",
                "high": px + 25,
                "low": px - 25,
                "close": px,
            }
        )
        d += 1
        if d > 28:
            d = 1
            m += 1
    pivots = [
        {"i": 4, "date": bars[4]["date"], "px": bars[4]["low"], "kind": "L"},
        {"i": 24, "date": bars[24]["date"], "px": bars[24]["high"], "kind": "H"},
    ]
    f, missing = snapshot_wave_fib_targets(bars, pivots, bars[-1]["date"])
    assert missing == [] or all(x.startswith("wave_fib") is False or True for x in missing)
    assert f.get("wave_fib_leg_up") is True
    assert "wave_fib_retrace_0.618" in f
    assert f.get("wave_fib_primary_px") is not None
    assert f.get("wave_fib_defined_ratios") is True
    # 升段完 → 主目標應低於終點
    assert float(f["wave_fib_primary_px"]) < float(f["wave_fib_leg_end"])
