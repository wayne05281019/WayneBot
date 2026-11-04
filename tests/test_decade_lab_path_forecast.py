# -*- coding: utf-8 -*-
from scripts.decade_lab_path_forecast import (
    FACTOR_PACK,
    INVESTOR_OUTPUT,
    _judge,
    _targets,
    decide_path,
)


def test_investor_contract_and_factor_pack():
    for k in ("bias", "horizon", "target", "invalidate", "factors", "missing"):
        assert k in INVESTOR_OUTPUT
    for k in ("twii_ret", "ixic_prior_ret", "tsm_prior_ret", "dxy_prior_ret", "tx_night_ret"):
        assert k in FACTOR_PACK


def test_decide_and_judge():
    votes = {"us_up_tw_down": 0.5, "dxy_up_tw_down": -0.6, "tw_vol_spike": 0.4}
    up = decide_path(
        {
            "twii_ret": -1.0,
            "ixic_prior_ret": 1.5,
            "twii_vol_spike": True,
            "twii_wick": 0.2,
        },
        [],
        votes,
    )
    assert up["bias"] in {"up", "down", "range"}
    assert up["reviewable"] is True
    tgt, inv = _targets("up", 10000.0)
    assert tgt > 10000 and inv < 10000
    assert "對得上往上" in _judge("up", 10000.0, 10100.0, inv)
    assert "偏了" in _judge("up", 10000.0, 9800.0, inv)
    assert "觀望不計分" in _judge("range", 10000.0, 10050.0, inv)
