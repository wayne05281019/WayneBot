# -*- coding: utf-8 -*-
"""DC→我估：官方 TWII／TX 凍結轉折對質樣例（可重跑；≠他說）。

價來自 index_daily／futures_daily 已收轉折（見 practice_log_20261123.md）。
不准把結果標成飆大原文。
"""
from __future__ import annotations

import pytest

from mine_wave_rules import (
    analyze_motive_from_pivot_prices,
    detect_extension_1618,
    ending_diagonal_flags,
)


# 凍結官方轉折價（MINE 練習；非假數）
TWII_A = [46552.16, 42006.39, 48218.87, 39384.85, 46402.60, 44210.31]
TWII_B = [42006.39, 48218.87, 39384.85, 46402.60, 44210.31, 47578.24]
TWII_C = [48218.87, 39384.85, 46402.60, 44210.31, 47578.24, 45398.43]
TWII_D = [23387.17, 22510.25, 23943.95, 22458.22, 23732.58, 17306.97]
TX_A = [48711.0, 44264.0, 47695.0, 39442.0, 46470.0, 44146.0]
TX_B = [39442.0, 46470.0, 44146.0, 47593.0, 45302.0, 50117.0]


def _assert_mine_pot(pack: dict) -> None:
    assert pack.get("source") == "mine"
    assert pack.get("pot") == "DC→我估"
    # 准寫「≠他說」分鍋；不准寫成肯定「他說：…」
    basis = str(pack.get("basis") or "")
    assert "他說：" not in basis
    assert pack.get("pot") != "他說"


@pytest.mark.parametrize(
    "prices,expect_pass,expect_longest,expect_variant",
    [
        (TWII_A, True, "3", None),
        (TWII_B, False, "3", "rare_ending_motive_variant"),
        (TWII_C, True, "1", None),
        (TWII_D, True, "5", None),
        (TX_A, True, "3", None),
        (TX_B, False, "1", "rare_motive_variant_w1_longest"),
    ],
)
def test_official_pivot_extension_gate(
    prices, expect_pass, expect_longest, expect_variant
):
    pack = analyze_motive_from_pivot_prices(prices)
    _assert_mine_pot(pack)
    assert pack["ok"] is True
    ext = pack["extension"]
    assert ext["pass"] is expect_pass
    assert ext["longest"] == expect_longest
    assert ext.get("variant") == expect_variant
    # 前端：重疊可 candidate；缺位置／結構 → 不准 confirmed
    ld = pack["leading_diagonal"]
    assert ld["confirmed"] is False
    # 末端教材未齊
    ed = pack["ending_diagonal"]
    assert ed["status"] == "curriculum_pending"
    assert ed["confirmed"] is False
    assert ed["implication"] == "termination"


def test_ending_diagonal_never_confirms_without_curriculum():
    flags = ending_diagonal_flags(
        w1_w4_overlap=True,
        position_at_w5_or_C=True,
        wedge_converging=True,
        structure_53535=True,
        curriculum_ready=False,
    )
    assert flags["confirmed"] is False
    assert flags["status"] == "curriculum_pending"
    assert flags["pot"] == "DC→我估"


def test_insufficient_pivots_honest():
    pack = analyze_motive_from_pivot_prices([100.0, 110.0, 105.0])
    assert pack["ok"] is False
    assert pack["extension"]["variant"] == "insufficient_pivots"
    _assert_mine_pot(pack)


def test_twii_a_motive_lengths_match_detect():
    """對質：analyze 與直接 detect_extension_1618 一致。"""
    pack = analyze_motive_from_pivot_prices(TWII_A)
    motive = {k: pack["lengths"][k] for k in ("1", "3", "5")}
    direct = detect_extension_1618(motive)
    assert direct["pass"] == pack["extension"]["pass"]
    assert abs(float(direct["ratio"]) - float(pack["extension"]["ratio"])) < 1e-9
