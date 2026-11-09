# -*- coding: utf-8 -*-
from scripts.decade_lab_stock_spirit_soft_leader_pull_fib_ma5_10_hold_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
)


def test_phone_flags_blocked_ma5_10():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "soft_leader_reclaim_ma5_10_hold" in CONFIRM_NAMES
