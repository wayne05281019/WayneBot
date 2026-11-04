# -*- coding: utf-8 -*-
from scripts.decade_lab_mtf_volume import named_support_asof
from scripts.decade_lab_path_forecast import (
    FACTOR_PACK,
    INVESTOR_OUTPUT,
    _amp_class,
    _judge,
    _judge_amp,
    _margin_kill_direction_ok,
    _oos_holdout,
    _sample_audit,
    _targets,
    decide_path,
    estimate_amplitude,
)
from scripts.decade_lab_wave8_dual import confirmed_pivots_asof


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


def test_amp_crash_bounce_tail_slice():
    """急跌反彈幅度切片：破位＋寬震盪＋昨大跌 → 抬 amp 底。"""
    amp = estimate_amplitude(
        "up",
        1.0,
        {
            "michael_crash_bounce_tail": True,
            "michael_break_lower": True,
            "michael_wide_chop": True,
            "michael_prior_ret": -4.0,
            "michael_sox_prior_ret": -3.5,
            "michael_bound_span_pct": 18.0,
            "michael_gap_south": False,
        },
        realized_abs_ret=0.8,
    )
    assert abs(amp["amp_pct"]) >= 7.0
    assert "m_crash_bounce" in str(amp.get("amp_basis") or "")


def test_amp_wick_chop_rebound_slice():
    amp = estimate_amplitude(
        "up",
        1.0,
        {
            "michael_wick_chop_rebound": True,
            "michael_wide_chop": True,
            "michael_lower_wick": 0.85,
            "michael_prior_ret": -1.5,
            "michael_gap_south": False,
        },
        realized_abs_ret=0.5,
    )
    assert abs(amp["amp_pct"]) >= 3.0
    assert "m_wick_chop" in str(amp.get("amp_basis") or "")


def test_oos_holdout_split():
    def _mk(n: int):
        rows = []
        for i in range(n):
            day = f"2026{1 + i // 28:02d}{(i % 28) + 1:02d}"
            rows.append(
                {
                    "as_of": day,
                    "bias": "up" if i % 2 == 0 else "down",
                    "verdict": "對得上往上" if i % 3 else "偏了沒往上：x",
                    "amp_verdict": (
                        "幅度對得上：估+1 實+1" if i % 2 == 0 else "幅度偏了：估+1 實+3"
                    ),
                }
            )
        return rows

    small = _oos_holdout(_mk(12), holdout_n=5)
    assert small["ok"] is True
    # n=12 時 holdout = min(5, max(3, n//4)) = 3
    assert small["holdout_n"] == 3
    assert small["in_sample"]["n"] + small["holdout"]["n"] == 12

    big = _oos_holdout(_mk(20), holdout_n=5)
    assert big["ok"] is True
    assert big["holdout_n"] == 5
    assert len(big["holdout_as_of"]) == 5
    assert big["in_sample"]["n"] + big["holdout"]["n"] == 20


def test_amp_class_thresholds():
    assert _amp_class(0.59) == "micro"
    assert _amp_class(0.6) == "small"
    assert _amp_class(1.49) == "small"
    assert _amp_class(1.5) == "mid"
    assert _amp_class(2.99) == "mid"
    assert _amp_class(3.0) == "large"


def test_named_support_no_lookahead():
    bars = [
        {"date": "20260728", "low": 40000.0},
        {"date": "20260729", "low": 39384.85},
        {"date": "20260730", "low": 39500.0},
    ]
    assert named_support_asof(bars, "20260728") is None
    assert named_support_asof(bars, "20260729") == 39384.85
    assert named_support_asof(bars, "20260911") == 39384.85


def test_confirmed_pivots_right_window():
    # look=3：點 i=10 要等到 as_of≥13 才確認
    piv = [{"i": 10, "kind": "L", "px": 100.0}, {"i": 20, "kind": "H", "px": 120.0}]
    assert confirmed_pivots_asof(piv, 12, look=3) == []
    assert [p["i"] for p in confirmed_pivots_asof(piv, 13, look=3)] == [10]
    assert [p["i"] for p in confirmed_pivots_asof(piv, 23, look=3)] == [10, 20]


def test_sample_audit_flags_dilution_and_thin_oos():
    by_amp = {
        "micro": {"n": 0, "hit": 0, "miss": 0, "hit_rate": None},
        "small": {"n": 5, "hit": 2, "miss": 3, "hit_rate": 0.4},
        "mid": {"n": 7, "hit": 7, "miss": 0, "hit_rate": 1.0},
        "large": {"n": 12, "hit": 11, "miss": 1, "hit_rate": 0.92},
    }
    oos = {"holdout_n": 5, "ok": True}
    audit = _sample_audit(
        wrote=5000,
        range_n=4800,
        insuff_n=100,
        soft_range_n=200,
        dir_n=24,
        hit_rate=1.0,
        by_amp_class=by_amp,
        oos=oos,
    )
    assert audit["integrity_ok"] is False
    assert "call_rate_too_low_range_dilution" in audit["integrity_blockers"]
    assert "small_amp_gate_fail" in audit["integrity_blockers"]
    assert "oos_holdout_too_thin" in audit["integrity_blockers"]
    assert "WAVE_NEURONS_MATCH_false" in audit["integrity_blockers"]
    assert "named_support_gated_by_asof" in audit["look_ahead_fixes"]
    assert audit["call_rate"] < 0.02


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
