# -*- coding: utf-8 -*-
from scripts.decade_lab_factor_gap_queue import (
    IDEA_CATALOG,
    diagnose_fruitless,
    pick_ideas,
    _next_slots,
)


def test_idea_catalog_nonempty():
    assert len(IDEA_CATALOG) >= 10
    ids = {x["id"] for x in IDEA_CATALOG}
    assert "margin_balance_long" in ids
    assert "us10y_dxy_yen" in ids


def test_diagnose_flags_weak_hit_rate():
    diag = diagnose_fruitless(
        path_summary={
            "hit_rate_directional": 0.50,
            "directional_n": 100,
            "factor_pack": ["twii_ret"],
        },
        wave_summary={"tracks": {"textbook_8cycle": {"n_decided": 40, "hit_rate": 0.74}}},
    )
    assert diag["reasons"]
    assert any("準度" in r for r in diag["reasons"])


def test_schedule_and_pick():
    slots = _next_slots()
    assert slots
    assert all("at" in s and "kind" in s for s in slots)
    ideas = pick_ideas(
        {
            "fruitless": True,
            "reasons": ["x"],
            "evidence": {"coverage": {"ok": True, "symbols": {}, "market_margin_daily": 10}},
        },
        limit=5,
    )
    assert 1 <= len(ideas) <= 5
