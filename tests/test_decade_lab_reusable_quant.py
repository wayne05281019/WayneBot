# -*- coding: utf-8 -*-
from scripts.decade_lab_reusable_quant import (
    MIN_EDGE_ABS,
    MIN_N,
    TARGET_KEEP,
    _mean,
    _pctile,
    _wick,
)


def test_gates_and_helpers():
    assert MIN_N >= 20
    assert MIN_EDGE_ABS > 0
    assert TARGET_KEEP >= 10
    assert _mean([1.0, 3.0]) == 2.0
    assert _mean([]) is None
    assert _wick({"open": 100, "high": 101, "low": 90, "close": 100}) >= 0.45
    assert _pctile([1, 2, 3, 4, 5], 50) == 3
