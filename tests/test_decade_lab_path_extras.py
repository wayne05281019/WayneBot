# -*- coding: utf-8 -*-
from scripts.decade_lab_path_extras import load_extras_votes, snapshot_extras


def test_snapshot_extras_regime_and_streak():
    twii = {}
    px = 10000.0
    days = []
    for i in range(80):
        d = f"{20240101 + i}"
        days.append(d)
        ret = 0.5 if i % 7 else -0.8
        px = px * (1 + ret / 100.0)
        twii[d] = {
            "open": px * 0.999,
            "high": px * 1.01,
            "low": px * 0.99,
            "close": px,
            "ret": ret,
            "ret_ok": True,
        }
    empty: dict = {}
    f, _m = snapshot_extras(
        twii=twii,
        ixic=empty,
        sox=empty,
        vix=empty,
        us10y=empty,
        usdjpy=empty,
        gold=empty,
        copper=empty,
        tsm=empty,
        tw2330=empty,
        tx_night_px={},
        tw_days=days,
        as_of=days[-1],
    )
    assert "regime" in f
    assert "tw_streak" in f


def test_load_extras_votes_optional():
    assert isinstance(load_extras_votes(), dict)
