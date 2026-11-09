# -*- coding: utf-8 -*-
from scripts.decade_lab_stock_spirit_soft_leader_pull_fib_reclaim_sell_vol_fade_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
)


def test_phone_flags_blocked_sell_vol_fade():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_vol_fade_or_desync"
    assert "soft_leader_and_reclaim" in CONFIRM_NAMES
    assert "soft_leader_reclaim_bias_lt5" in CONFIRM_NAMES
