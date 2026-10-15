# -*- coding: utf-8 -*-
"""Calm／小買→大買：非買訊、單位張。"""
from __future__ import annotations

from foreign_sell_calm import (
    BuyEscalateParams,
    buy_lots,
    buy_share,
    evaluate_buy_escalate_A,
    evaluate_calm_fear_fade,
    hit_buy_within_k,
    units_banner,
)


def test_units_and_buy_share():
    assert units_banner()["lots_per_share"] == 1000
    assert buy_lots(2500) == 2500.0
    assert buy_lots(-100) == 0.0
    assert abs((buy_share(200, 1000) or 0) - 0.2) < 1e-12


def test_buy_escalate_needs_climb():
    fns = [100.0, 200.0, 300.0]
    vols = [1000.0, 1000.0, 1000.0]
    pctls = [40.0, 55.0, 70.0]
    ev = evaluate_buy_escalate_A(
        foreign_nets=fns, volumes=vols, pctls=pctls, params=BuyEscalateParams(n_days=3)
    )
    assert ev["lit"] is True
    ev2 = evaluate_buy_escalate_A(
        foreign_nets=fns,
        volumes=vols,
        pctls=[40.0, 55.0, 95.0],
        params=BuyEscalateParams(n_days=3),
    )
    assert ev2["lit"] is False and ev2.get("already_extreme") is True


def test_calm_fade_and_hit():
    assert evaluate_calm_fear_fade(
        fear_edges_today=1, fear_edges_yest=3, lit_today=False, lit_yest=True
    )["lit"] is True
    assert evaluate_calm_fear_fade(
        fear_edges_today=3, fear_edges_yest=3, lit_today=True, lit_yest=True
    )["lit"] is False
    h = hit_buy_within_k([None, 95.0], k=3, theta_pctl=90.0)
    assert h["hit"] is True
