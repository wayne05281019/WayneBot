# -*- coding: utf-8 -*-
from scripts.decade_lab_linkage_combos import _prior_us_day, _combos, _fwd_ret


def test_prior_us_day_and_combos():
    us = ["20260102", "20260103", "20260106"]
    assert _prior_us_day(us, "20260106") == "20260103"
    assert _prior_us_day(us, "20260102") is None
    flags = {"a": True, "b": False, "c": True}
    combos = _combos(flags, ["a", "b", "c"], max_k=2)
    assert ("a",) in combos
    assert ("c",) in combos
    assert ("a", "c") in combos
    assert ("b",) not in combos


def test_fwd_ret_basic():
    twii = {
        "20260102": {"close": 100.0},
        "20260103": {"close": 101.0},
        "20260106": {"close": 103.0},
    }
    days = ["20260102", "20260103", "20260106"]
    assert abs(_fwd_ret(twii, days, 0, 1) - 1.0) < 1e-9
    assert abs(_fwd_ret(twii, days, 0, 2) - 3.0) < 1e-9
    assert _fwd_ret(twii, days, 2, 1) is None
