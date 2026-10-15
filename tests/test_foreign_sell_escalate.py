# -*- coding: utf-8 -*-
"""小賣→大賣：單位張、升級 A、起點大賣分軌。"""
from __future__ import annotations

from foreign_sell_escalate import (
    LOTS_PER_SHARE,
    EscalateParams,
    cum_sell_lots,
    evaluate_escalate_A,
    hit_within_k,
    lit_dump_cum10,
    lit_dump_lots,
    lit_dump_share,
    lit_dump_streak,
    sell_lots,
    streak_sell_days,
    units_banner,
)


def test_units_are_lots():
    u = units_banner()
    assert u["lots_per_share"] == 1000 == LOTS_PER_SHARE
    assert u["volume_unit"] == "張"
    assert u["foreign_net_unit"] == "張"


def test_sell_lots_and_cum():
    assert sell_lots(-2500) == 2500.0  # 張
    assert sell_lots(100) == 0.0
    assert cum_sell_lots([-1000, 50, -500]) == 1500.0


def test_streak_and_dump_defs():
    assert streak_sell_days([-1, -2, -3, 1]) == 0  # 末端非賣
    assert streak_sell_days([-1, -2, -3]) == 3
    assert lit_dump_lots(-3000, 1000) is True
    assert lit_dump_share(-200, 1000, 0.15) is True  # 20%
    assert lit_dump_streak([-10, -20, -30], 3) is True
    assert lit_dump_cum10([-1000] * 10, 5000) is True


def test_escalate_A_needs_climb_not_extreme():
    # 連賣爬升、分位未達 90
    fns = [-100.0, -200.0, -300.0]
    vols = [1000.0, 1000.0, 1000.0]
    pctls = [40.0, 55.0, 70.0]
    ev = evaluate_escalate_A(
        foreign_nets=fns, volumes=vols, pctls=pctls, params=EscalateParams(n_days=3)
    )
    assert ev["lit"] is True
    # 已極端
    ev2 = evaluate_escalate_A(
        foreign_nets=fns,
        volumes=vols,
        pctls=[40.0, 55.0, 95.0],
        params=EscalateParams(n_days=3),
    )
    assert ev2["lit"] is False
    assert ev2.get("already_extreme") is True


def test_hit_within_k():
    h = hit_within_k([None, 95.0, 10.0], k=3, theta_pctl=90.0)
    assert h["hit"] is True and h["hit_day_offset"] == 2
    h2 = hit_within_k([10.0, 20.0], k=2, theta_pctl=90.0)
    assert h2["hit"] is False
