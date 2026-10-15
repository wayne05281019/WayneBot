# -*- coding: utf-8 -*-
"""FearComposite₀：票邏輯／Lead-Sync／缺欄不硬編／非買訊。"""
from __future__ import annotations

from fear_composite import (
    DEFAULT_NIGHT_THR,
    FearParams,
    VOTE_NIGHT,
    VOTE_OUTER,
    VOTE_US,
    classify_lead_sync,
    evaluate_fear_composite,
    iter_fear_param_grid,
    night_vs_prior_settle_pct,
    sell_share,
    us_keys_present,
    vote_outer,
    vote_tx_te_night,
    vote_us_risk,
)


def test_us_keys_present_requires_any_of_ixic_sox_vix():
    assert not us_keys_present({})
    assert not us_keys_present({"regime": "ok"})
    assert us_keys_present({"ixic_pct": -1.0})
    assert us_keys_present({"vix": 22.0})
    assert us_keys_present({"sox_pct": -2.0})


def test_vote_us_alert_or_chain_risk():
    # should_alert：risk_off
    d = vote_us_risk({"regime": "risk_off", "ixic_pct": -3.0, "vix": 28.0, "sox_pct": -2.0})
    assert d.available and d.lit and d.name == VOTE_US
    # caution + 電子鏈跌
    snap = {
        "regime": "caution",
        "ixic_pct": -0.5,
        "vix": 19.0,
        "sox_pct": -1.5,
        "tsm_pct": -1.2,
        "nvda_pct": -1.1,
    }
    d2 = vote_us_risk(snap)
    assert d2.available and d2.lit
    # 中性且無大跌
    d3 = vote_us_risk(
        {
            "regime": "ok",
            "ixic_pct": 0.2,
            "vix": 14.0,
            "sox_pct": 0.1,
            "tsm_pct": 0.3,
            "nvda_pct": 0.2,
        }
    )
    assert d3.available and not d3.lit


def test_vote_us_unavailable_when_empty():
    d = vote_us_risk({})
    assert not d.available and not d.lit


def test_night_vote_tx_or_te():
    d = vote_tx_te_night(tx_night_pct=-1.0, te_night_pct=None, night_thr=DEFAULT_NIGHT_THR)
    assert d.available and d.lit and d.name == VOTE_NIGHT
    d2 = vote_tx_te_night(tx_night_pct=-0.3, te_night_pct=-0.2, night_thr=-0.8)
    assert d2.available and not d2.lit
    d3 = vote_tx_te_night(tx_night_pct=None, te_night_pct=None)
    assert not d3.available


def test_night_vs_prior_settle():
    assert abs(night_vs_prior_settle_pct(99.0, 100.0) - (-1.0)) < 1e-9
    assert night_vs_prior_settle_pct(None, 100.0) is None


def test_outer_vote_pool():
    d = vote_outer({"usdtwd_pct": 0.5})
    assert d.available and d.lit and d.name == VOTE_OUTER
    d2 = vote_outer({"dx_f_pct": 0.5})
    assert d2.lit
    d3 = vote_outer({"brent_pct": -3.5})
    assert d3.lit  # |Δ|≥3
    d4 = vote_outer({"usdtwd_pct": 0.1, "dx_f_pct": 0.1, "brent_pct": 1.0})
    assert d4.available and not d4.lit
    d5 = vote_outer({})
    assert not d5.available


def test_composite_needs_two_votes_and_us_keys():
    # 缺美股 → 整包不評估
    r = evaluate_fear_composite(as_of="20261013", us_snap={}, tx_night_pct=-2.0)
    assert not r.evaluable and not r.lit
    assert "美股" in r.skip_reason
    # 一票不夠
    us = {"regime": "ok", "ixic_pct": 0.1, "vix": 14.0, "sox_pct": 0.0}
    r2 = evaluate_fear_composite(
        as_of="20261013", us_snap=us, tx_night_pct=-2.0, te_night_pct=None
    )
    assert r2.evaluable and not r2.lit and r2.votes == 1
    # 美股大跌 + 夜盤
    us_bad = {
        "regime": "risk_off",
        "ixic_pct": -3.0,
        "vix": 30.0,
        "sox_pct": -2.5,
        "tsm_pct": -2.0,
    }
    r3 = evaluate_fear_composite(
        as_of="20261013",
        us_snap=us_bad,
        tx_night_pct=-1.0,
        gap_open_pct=-0.2,
    )
    assert r3.evaluable and r3.lit and r3.votes >= 2
    assert r3.lead_sync == "lead"
    # 跳空大跌＝sync
    r4 = evaluate_fear_composite(
        as_of="20261013",
        us_snap=us_bad,
        tx_night_pct=-1.0,
        gap_open_pct=-1.5,
    )
    assert r4.lead_sync == "sync"


def test_tw_closed_not_evaluable():
    us = {"ixic_pct": -3.0, "vix": 30.0, "sox_pct": -2.0, "regime": "risk_off"}
    r = evaluate_fear_composite(as_of="20261011", us_snap=us, tw_closed=True)
    assert not r.evaluable and not r.lit


def test_param_grid_is_full_not_sampled():
    grid = iter_fear_param_grid()
    # 2×3×1×1×1＝6
    assert len(grid) == 6
    keys = {p.key() for p in grid}
    assert len(keys) == 6


def test_sell_share_and_lead_sync_helpers():
    # 張／張：賣超 100 張、量 1000 張 → 10%
    assert sell_share(-100, 1000) == 0.1
    assert sell_share(50, 1000) == 0.0
    assert classify_lead_sync(False, -2.0) == ""
    assert classify_lead_sync(True, -0.2) == "lead"
    assert classify_lead_sync(True, -1.2) == "sync"


def test_sell_share_units_are_lots_not_shares():
    from fear_composite import (
        FOREIGN_NET_UNIT,
        LOTS_PER_SHARE,
        SELL_SHARE_UNIT,
        VOLUME_UNIT,
        unit_consistency_report,
    )

    assert LOTS_PER_SHARE == 1000
    assert VOLUME_UNIT == "張"
    assert FOREIGN_NET_UNIT == "張"
    assert "張" in SELL_SHARE_UNIT
    # 同單位張：佔量 ≤1 為常態
    ok_rows = [{"foreign_net": -200, "volume": 5000} for _ in range(20)]
    rep = unit_consistency_report(ok_rows)
    assert rep["units_ok"] is True
    # 若誤把法人當股、量當張：−200000 股配 5000 張 → 佔量 40 → 應觸發
    bad_rows = [{"foreign_net": -200_000, "volume": 5000} for _ in range(20)]
    bad = unit_consistency_report(bad_rows)
    assert bad["units_ok"] is False
    assert bad["n_sell_share_gt10"] == 20


def test_fear_params_key_stable():
    p = FearParams()
    assert p.key() == FearParams(**p.as_dict()).key()
