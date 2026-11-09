# -*- coding: utf-8 -*-
"""stock_spirit_soft_leader_ma60_hold_sell_ma60_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

from scripts.decade_lab_stock_spirit_soft_leader_ma60_hold_sell_ma60_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
)


def test_phone_flags_blocked_sell_ma60():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync_ma60"
    assert "soft_leader_reclaim_ma60_hold" in CONFIRM_NAMES
    assert "ma60_hold" in CONFIRM_NAMES
