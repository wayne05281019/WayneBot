# -*- coding: utf-8 -*-
from scripts.decade_lab_path_forecast import (
    FACTOR_PACK,
    INVESTOR_OUTPUT,
    _judge,
    _judge_amp,
    _margin_kill_direction_ok,
    _targets,
    decide_path,
    estimate_amplitude,
)


def test_investor_contract_and_factor_pack():
    for k in ("bias", "amp_pct", "amp_class", "horizon", "target", "invalidate", "factors", "missing"):
        assert k in INVESTOR_OUTPUT
    for k in (
        "twii_ret",
        "ixic_prior_ret",
        "tsm_prior_ret",
        "dxy_prior_ret",
        "tx_night_ret",
        "fib_near_0618_support",
        "chips_margin_delta_z",
        "wave_bias",
        "wave_phase",
    ):
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
    # 黃金切割位優先當目標／失效
    tgt2, inv2 = _targets(
        "down",
        20000.0,
        1.0,
        {
            "fib_pull_0.618": 19000.0,
            "fib_bounce_0.786": 20500.0,
            "fib_swing_low": 18500.0,
            "fib_swing_high": 21000.0,
        },
    )
    assert tgt2 == 19000.0
    assert inv2 == 20500.0


def test_margin_kill_direction_gate():
    ok, why = _margin_kill_direction_ok({"chips_margin_kill_2d": True})
    assert ok is False and why == "no_confirm"
    ok2, why2 = _margin_kill_direction_ok(
        {
            "chips_margin_kill_2d": True,
            "mtf_named_support_broken": True,
            "inst_foreign_pos_2d": True,
        }
    )
    assert ok2 is False and why2 == "hard_veto"
    ok3, _ = _margin_kill_direction_ok(
        {"chips_margin_kill_2d": True, "inst_foreign_pos_2d": True}
    )
    assert ok3 is True


def test_chop_abc_soft_range_and_false_up():
    votes = {"us_up_tw_down": 0.5}
    # 震盪＋修正浪＋弱票 → range
    out = decide_path(
        {
            "twii_ret": -0.2,
            "ixic_prior_ret": 0.1,
            "regime": "chop",
            "wave_ok": True,
            "wave_bias": "up",
            "wave_phase": "corrective_abc",
            "chips_margin_kill_2d": True,  # 無確認 → blocked
        },
        [],
        votes,
    )
    assert out["bias"] == "range"
    codes = [x["code"] for x in out["why"]]
    assert any("abc" in c or "soft_range" in c or "margin_kill_blocked" in c for c in codes)

    # 假彈連錯 ≥2 → 修正浪看漲改觀望
    out2 = decide_path(
        {
            "twii_ret": 0.2,
            "ixic_prior_ret": 0.1,
            "regime": "bull",
            "wave_ok": True,
            "wave_bias": "up",
            "wave_phase": "corrective_abc",
            "false_up_streak": 2,
            "inst_foreign_pos_2d": True,
            "chips_margin_kill_2d": True,
        },
        [],
        {"inst_foreign_pos_2d": 0.6, "chips_margin_kill_2d": 1.5},
    )
    assert out2["bias"] == "range"
    assert any(x["code"] == "false_up_streak_soft_range" for x in out2["why"])


def test_macro_only_down_soft_range():
    out2 = decide_path(
        {
            "twii_ret": -1.0,
            "ixic_prior_ret": 0.2,
            "dxy_prior_ret": 0.8,
            "brent_prior_ret": 2.5,
            "usdtwd_prior_ret": 0.5,
            "wave_ok": False,
        },
        [],
        {"dxy_up_tw_down": -0.64, "brent_up_tw_down": -0.4, "fx_up_tw_down": -0.77},
    )
    assert out2["bias"] == "range"
    assert any(x["code"] == "macro_only_down_soft_range" for x in out2["why"])


def test_michael_alone_soft_range():
    # 麥可硬旗孤票不准當唯一看漲主判
    out = decide_path(
        {
            "twii_ret": -0.5,
            "ixic_prior_ret": 0.1,
            "regime": "bull",
            "wave_ok": False,
            "michael_gap_south": True,
            "michael_gap_south_fx_ok": True,
        },
        [],
        {"michael_gap_south_fx_ok": 1.35},
    )
    assert out["bias"] == "range"
    assert any(x["code"] == "michael_alone_soft_range" for x in out["why"])


def test_michael_gap_x_limit_up_soft_range():
    # 缺口南／向南失敗 × 漲停熱 → 觀望（20261005 類）
    out = decide_path(
        {
            "twii_ret": 0.5,
            "ixic_prior_ret": 0.2,
            "regime": "bull",
            "wave_ok": False,
            "twii_vol_spike": True,
            "chips_limit_up_ge_20": True,
            "michael_gap_south": True,
            "michael_gap_south_fx_ok": True,
            "michael_failed_south_after_strong": True,
        },
        [],
        {
            "tw_vol_spike": 0.41,
            "chips_limit_up_ge_20": 0.55,
            "michael_gap_south_fx_ok": 1.35,
            "michael_failed_south_after_strong": 0.41,
        },
    )
    assert out["bias"] == "range"
    assert any(x["code"] == "michael_gap_x_limit_up_soft_range" for x in out["why"])


def test_abc_up_call_streak():
    out = decide_path(
        {
            "twii_ret": 0.2,
            "ixic_prior_ret": 0.1,
            "regime": "bull",
            "wave_ok": True,
            "wave_bias": "up",
            "wave_phase": "corrective_abc",
            "abc_up_call_streak": 2,
            "inst_foreign_pos_2d": True,
            "chips_margin_kill_2d": True,
        },
        [],
        {"inst_foreign_pos_2d": 0.6, "chips_margin_kill_2d": 1.5},
    )
    assert out["bias"] == "range"
    assert any(x["code"] == "abc_up_call_streak_soft_range" for x in out["why"])


def test_amp_regime_scale():
    base = estimate_amplitude("up", 1.0, {}, realized_abs_ret=0.8)
    chop = estimate_amplitude("up", 1.0, {"regime": "chop"}, realized_abs_ret=0.8)
    bear = estimate_amplitude("up", 1.0, {"regime": "bear"}, realized_abs_ret=0.8)
    assert abs(chop["amp_pct"]) < abs(base["amp_pct"])
    assert abs(bear["amp_pct"]) > abs(base["amp_pct"])


def test_amp_michael_method_variants():
    """由麥可做法變化微調三日幅度：破位寬震盪抬、bounce 大估收、after_night 抬底。"""
    rv = 0.8
    plain = estimate_amplitude("up", 1.0, {}, realized_abs_ret=rv)
    break_chop = estimate_amplitude(
        "up",
        1.0,
        {
            "michael_break_lower": True,
            "michael_wide_chop": True,
            "michael_gap_south": False,
        },
        realized_abs_ret=rv,
    )
    assert abs(break_chop["amp_pct"]) > abs(plain["amp_pct"])
    assert abs(break_chop["amp_pct"]) >= 3.8
    assert "m_break_chop" in str(break_chop.get("amp_basis") or "")

    after_night = estimate_amplitude(
        "up",
        1.0,
        {"michael_gap_south_after_night": True, "michael_gap_south": True},
        realized_abs_ret=rv,
    )
    assert abs(after_night["amp_pct"]) >= 3.8
    assert "m_after_night" in str(after_night.get("amp_basis") or "")

    # 高估收縮：大估＋bounce＋寬震盪、且無 after_night
    shrink = estimate_amplitude(
        "up",
        3.5,
        {
            "michael_gap_south_bounce": True,
            "michael_wide_chop": True,
            "michael_gap_south": True,
            "regime": "bear",  # 先把 base 抬過 3.5 再收
        },
        realized_abs_ret=2.2,
    )
    assert abs(shrink["amp_pct"]) <= 2.6
    assert "m_bounce_shrink" in str(shrink.get("amp_basis") or "")


def test_support_beats_margin_kill():
    votes = {"chips_margin_kill_2d": 1.56, "inst_foreign_pos_2d": 0.5}
    out = decide_path(
        {
            "twii_ret": -1.0,
            "ixic_prior_ret": 0.2,
            "chips_margin_kill_2d": True,
            "inst_foreign_pos_2d": True,
            "mtf_named_support_broken": True,
            "wave_ok": False,
        },
        [],
        votes,
    )
    codes = [x["code"] for x in out["why"]]
    assert "conflict_support_over_margin_kill" in codes
    assert "chips_margin_kill_2d" not in codes
    # 衝突中性化：拆掉融資殺反彈票後改觀望，不准單靠衝突硬空
    assert out["bias"] == "range"
