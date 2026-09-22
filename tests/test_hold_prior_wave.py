# -*- coding: utf-8 -*-
"""創區間新高後回測前波高：高低卡顯示，不進海選／飆大。"""
from __future__ import annotations

from pathlib import Path

from hold_prior_wave import (
    ALMOST_FRAC,
    attach_hold_prior_wave,
    classify_hold_prior_wave,
    hold_note_lines,
)


def _series_auo_like(*, retest_low: float | None = 13.3, extra_new: bool = False):
    """舊高 14.9 仍壓著，1/5 高 13.85 還不是 60 日新高；1/6 起漲。"""
    highs = [10.0] * 50 + [14.9] + [10.0] * 20
    lows = [h - 0.4 for h in highs]
    launch_h = [12.65, 13.85, 15.2, 16.7, 17.5]
    launch_l = [11.9, 12.9, 14.3, 15.8, 15.6]
    highs += launch_h
    lows += launch_l
    if extra_new:
        return highs, lows
    if retest_low is None:
        return highs, lows
    highs += [16.0, 15.0, 14.2, 13.9]
    lows += [15.0, 14.0, 13.6, float(retest_low)]
    return highs, lows


def test_new_high_points_at_prior_wave_high():
    highs, lows = _series_auo_like(retest_low=None)
    got = classify_hold_prior_wave(highs, lows)
    assert got["hold_prior_state"] == "new_high"
    assert got["hold_prior_high"] == 13.85
    assert "前波高 13.85" in got["hold_prior_note"]
    assert "前次底" in got["hold_prior_note"]
    assert "不是買訊" not in got["hold_prior_note"]
    assert "浪" not in got["hold_prior_note"]


def test_retest_almost_holds_like_2409_feb3():
    highs, lows = _series_auo_like(retest_low=13.3)
    got = classify_hold_prior_wave(highs, lows)
    assert got["hold_prior_state"] == "holds"
    assert got["hold_prior_high"] == 13.85
    assert got["hold_prior_retest_low"] == 13.3
    floor = 13.85 * (1.0 - ALMOST_FRAC)
    assert 13.3 + 1e-9 >= floor
    assert "幾乎不破前波高" in got["hold_prior_note"]
    lines = hold_note_lines(got)
    assert len(lines) == 1
    assert "13.85" in lines[0] and "13.3" in lines[0]
    assert "不是買訊" not in lines[0]


def test_retest_past_high_still_above_prior_low():
    """過了前波高 4%，前次底還在：洗盤可以比較深，不判死。"""
    highs, lows = _series_auo_like(retest_low=12.0)
    got = classify_hold_prior_wave(highs, lows)
    assert got["hold_prior_state"] == "wash"
    assert got["hold_prior_retest_low"] == 12.0
    assert got["hold_prior_base"] is not None
    assert 12.0 > float(got["hold_prior_base"])
    assert "前次底還在" in got["hold_prior_note"]
    assert "不是買訊" not in got["hold_prior_note"]


def test_retest_nicks_then_still_not_buy():
    highs, lows = _series_auo_like(retest_low=9.2)
    got = classify_hold_prior_wave(highs, lows)
    assert got["hold_prior_state"] == "nick"
    assert "略破前次底" in got["hold_prior_note"]
    assert "不是買訊" not in got["hold_prior_note"]


def test_retest_broke_prior_low():
    highs, lows = _series_auo_like(retest_low=8.0)
    got = classify_hold_prior_wave(highs, lows)
    assert got["hold_prior_state"] == "broke"
    assert "已破前次底" in got["hold_prior_note"]
    assert "不是買訊" not in got["hold_prior_note"]


def test_short_series_blank():
    got = classify_hold_prior_wave([10.0] * 20, [9.0] * 20)
    assert got["hold_prior_state"] == ""
    lines = hold_note_lines(got)
    assert lines and "高低卡" in lines[0]
    assert "不是買訊" not in lines[0]
    assert all("浪" not in x for x in lines)


def test_attach_writes_card_not_buy_fields():
    highs, lows = _series_auo_like(retest_low=13.3)
    card = {"stock_id": "2409", "gain_pct": 8.0}
    attach_hold_prior_wave(card, [f"202601{i:02d}" for i in range(1, 32)] * 4, highs, lows)
    assert card["hold_prior_state"] == "holds"
    assert "leave_zero" not in card
    assert card.get("sell_action") in (None, "")


def test_module_stays_on_high_low_card_not_biaoke():
    root = Path(__file__).resolve().parents[1]
    src = (root / "hold_prior_wave.py").read_text(encoding="utf-8")
    assert "biaoke" not in src.lower()
    assert "五件" not in src
    assert "波浪" not in src
    nav = (root / "wayne_navigator.py").read_text(encoding="utf-8")
    assert "attach_hold_prior_wave" in nav
    assert "hold_note_lines" in nav
    screen = (root / "screening_engine.py").read_text(encoding="utf-8")
    assert "hold_prior_wave" not in screen
    facts = (root / "biaoke_facts.py").read_text(encoding="utf-8")
    assert "hold_prior_wave.py" in facts


def test_2409_official_as_of_if_db_has_rows():
    import sqlite3

    db = Path("data/wayne_market.db")
    if not db.is_file():
        return
    n = sqlite3.connect(str(db)).execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='2409' AND date='20260203'"
    ).fetchone()[0]
    if not n:
        return
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(str(db))
    jan = eng.get_decision_card("2409", merge_live=False, as_of="20260107")
    assert jan.get("hold_prior_state") == "new_high"
    assert abs(float(jan.get("hold_prior_high") or 0) - 13.85) < 1e-6
    assert jan.get("hold_prior_also_180") is True
    feb = eng.get_decision_card("2409", merge_live=False, as_of="20260203")
    assert feb.get("hold_prior_state") == "holds"
    assert abs(float(feb.get("hold_prior_retest_low") or 0) - 13.3) < 1e-6
    assert abs(float(feb.get("hold_prior_base") or 0) - 11.1) < 1e-6
    assert "幾乎不破" in (feb.get("hold_prior_note") or "")
    apr = eng.get_decision_card("2409", merge_live=False, as_of="20260414")
    assert apr.get("hold_prior_state") == "new_high"
    jul = eng.get_decision_card("2409", merge_live=False, as_of="20260731")
    assert jul.get("hold_prior_state") == "holds"
    assert abs(float(jul.get("hold_prior_retest_low") or 0) - 22.0) < 1e-6
    assert jan.get("buy_verdict") == "no"
    note = jan.get("buy_verdict_note") or ""
    assert "別追" in note
    assert "不是買訊" not in note
    feb_note = feb.get("buy_verdict_note") or ""
    assert feb_note != note
    assert "13.3" in feb_note
    assert "13.85" in feb_note


def _lz_table(yest: float, today: float, hl="No", alert="No"):
    import pandas as pd

    return pd.DataFrame(
        [
            {"date": "20260106", "profit_pct": yest, "預警": "60低" if yest <= 0.05 else "No", "高低": "20低"},
            {"date": "20260107", "profit_pct": today, "預警": alert, "高低": hl},
        ]
    )


def test_buy_verdict_leave_zero_with_base_still_ok():
    from hold_prior_wave import judge_buy_point

    card = {
        "table": _lz_table(0.0, 1.2),
        "hold_prior_state": "holds",
        "gain_pct": 1.2,
    }
    got = judge_buy_point(card)
    assert got["buy_verdict"] == "buy"
    assert "黃金買點" in got["buy_verdict_note"]


def test_buy_verdict_wash_can_still_be_buy_if_table_says_so():
    from hold_prior_wave import judge_buy_point

    got = judge_buy_point(
        {"table": _lz_table(0.0, 0.8), "hold_prior_state": "wash", "gain_pct": 0.8}
    )
    assert got["buy_verdict"] == "buy"
    assert "前次底還在" in got["buy_verdict_note"]


def test_buy_verdict_nick_is_watch_not_buy():
    from hold_prior_wave import judge_buy_point

    got = judge_buy_point(
        {"table": _lz_table(0.0, 1.0), "hold_prior_state": "nick", "gain_pct": 1.0}
    )
    assert got["buy_verdict"] == "watch"
    assert "不要下手" in got["buy_verdict_note"]


def test_buy_verdict_broke_never_buy():
    from hold_prior_wave import judge_buy_point

    got = judge_buy_point(
        {"table": _lz_table(0.0, 1.0), "hold_prior_state": "broke", "gain_pct": 1.0}
    )
    assert got["buy_verdict"] == "no"
    assert "前次底" in got["buy_verdict_note"]


def test_buy_verdict_new_high_not_buy():
    from hold_prior_wave import judge_buy_point

    got = judge_buy_point({"hold_prior_state": "new_high", "gain_pct": 20.0})
    assert got["buy_verdict"] == "no"
    assert "剛創" in got["buy_verdict_note"] and "新高" in got["buy_verdict_note"]
