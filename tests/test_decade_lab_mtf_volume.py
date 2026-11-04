# -*- coding: utf-8 -*-
from scripts.decade_lab_mtf_volume import (
    _period_key,
    aggregate_mtf,
    detect_volume_climaxes,
)


def test_period_and_aggregate():
    assert _period_key("20260615", "Q") == "2026Q2"
    assert _period_key("20260615", "Y") == "2026"
    bars = [
        {"date": "20260102", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1},
        {"date": "20260202", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 2},
        {"date": "20260402", "open": 11, "high": 13, "low": 10.5, "close": 12, "volume": 3},
    ]
    q = aggregate_mtf(bars, {}, "Q")
    assert len(q) == 2
    assert q[0]["key"] == "2026Q1"
    assert q[1]["high"] == 13


def test_climax_detects_spike():
    bars = []
    for i in range(300):
        d = f"2020{i:04d}"[:8]
        # fake yyyymmdd sequence
        y = 2018 + i // 250
        m = (i % 12) + 1
        day = min(28, (i % 28) + 1)
        d = f"{y}{m:02d}{day:02d}"
        bars.append(
            {"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1e6}
        )
    tape = {b["date"]: 1.0 for b in bars}
    # spike last
    tape[bars[-1]["date"]] = 50.0
    hits = detect_volume_climaxes(bars, tape, look=100, pct=95, min_mult=2.0)
    assert any(h["date"] == bars[-1]["date"] for h in hits)
