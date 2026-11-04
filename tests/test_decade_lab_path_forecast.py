# -*- coding: utf-8 -*-
from scripts.decade_lab_path_forecast import (
    FACTOR_PACK,
    INVESTOR_OUTPUT,
    _judge,
    _judge_amp,
    _targets,
    decide_path,
    estimate_amplitude,
)


def test_investor_contract_and_factor_pack():
    for k in ("bias", "amp_pct", "amp_class", "horizon", "target", "invalidate", "factors", "missing"):
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
    amp = estimate_amplitude("up", 1.2, {"twii_vol_spike": True, "vix_prior_ret": 10.0})
    assert amp["amp_pct"] > 0
    assert amp["amp_class"] in {"micro", "small", "mid", "large"}
    tgt, inv = _targets("up", 10000.0, amp["amp_pct"])
    assert tgt > 10000 and inv < 10000
    assert "對得上往上" in _judge("up", 10000.0, 10100.0, inv)
    assert "偏了" in _judge("up", 10000.0, 9800.0, inv)
    assert "觀望不計分" in _judge("range", 10000.0, 10050.0, inv)
    assert "幅度對得上" in _judge_amp("up", 1.0, 0.9)
    assert "幅度偏了" in _judge_amp("up", 1.0, 3.5)
    assert "方向偏了" in _judge_amp("up", 1.0, -0.5)
