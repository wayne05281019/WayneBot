# -*- coding: utf-8 -*-
from scripts.decade_lab_fib_module import load_fib_votes, snapshot_fib_factors


def test_snapshot_fib_levels_present():
    bars = []
    for i in range(60):
        # 20240101 … 簡化用連續序號日字串（模組只要求 8 碼數字）
        ymd = f"{20240101 + i}"
        px = 100.0 + i * 0.8
        bars.append({"date": ymd, "high": px + 1, "low": px - 1, "close": px})
    hi = max(b["high"] for b in bars)
    lo = min(b["low"] for b in bars)
    span = hi - lo
    lvl = hi - 0.618 * span
    bars[-1]["close"] = lvl
    bars[-1]["high"] = lvl + 0.2
    bars[-1]["low"] = lvl - 0.2
    f, m = snapshot_fib_factors(bars, bars[-1]["date"])
    assert "fib_swing" not in m
    assert f.get("fib_swing_span")
    assert "fib_amp_0618_pct" in f
    assert f.get("fib_pull_0.618") is not None
    assert f.get("fib_near_0618_support") is True


def test_load_fib_votes_optional():
    votes = load_fib_votes()
    assert isinstance(votes, dict)
