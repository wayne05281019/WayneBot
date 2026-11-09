# -*- coding: utf-8 -*-
"""波浪重播 tight 裁判：觸及未確認 vs 連2收／假跌破。"""
from scripts.decade_lab_wave_jan_replay import (
    _closes_beyond,
    _fake_breakdown_candidate,
    _verify_paths,
)


def test_closes_beyond_needs_two():
    bars = [
        {"o": 100, "h": 101, "l": 90, "c": 91},
        {"o": 91, "h": 92, "l": 88, "c": 89},
    ]
    assert _closes_beyond(bars, 95.0, side="below", n=2) is True
    assert _closes_beyond(bars[:1], 95.0, side="below", n=2) is False


def test_fake_breakdown_pierce_then_reclaim():
    bars = [
        {"o": 100, "h": 102, "l": 94, "c": 96},  # pierce 95
        {"o": 96, "h": 101, "l": 95.5, "c": 100},  # reclaim
    ]
    assert _fake_breakdown_candidate(bars, 95.0) is True


def test_tight_touch_unconfirmed_not_scoreable():
    paths = [
        {
            "id": "P1_retest_near_floor",
            "levels": {"floor": 100.0},
            "segments_provisional": [{"label": "UNK"}],
        }
    ]
    bar = {"o": 102, "h": 103, "l": 99.5, "c": 101}  # wick touch only
    out = _verify_paths(paths, bar=bar, tx_day=None, prior_bars=[], score_mode="tight")
    assert out["scoreable"] is False
    assert out["verdict"] == "觀望不計分"
    pr = out["path_results"][0]
    assert pr["scoreable"] is False
    assert "touch_unconfirmed_floor" in pr["tags"]


def test_tight_eff_break_scores():
    paths = [
        {
            "id": "P1_retest_near_floor",
            "levels": {"floor": 100.0},
            "segments_provisional": [{"label": "UNK"}],
        }
    ]
    prior = [{"o": 101, "h": 102, "l": 98, "c": 99}]
    bar = {"o": 99, "h": 100, "l": 97, "c": 98}
    out = _verify_paths(
        paths, bar=bar, tx_day=None, prior_bars=prior, score_mode="tight"
    )
    assert out["scoreable"] is True
    assert out["verdict"] == "對"
    assert "eff_break_floor" in out["path_results"][0]["tags"]
