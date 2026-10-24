# -*- coding: utf-8 -*-
"""外資恐懼鏈收斂：非買訊；未過閘不換碼。"""
from __future__ import annotations

import os
import tempfile

from foreign_fear_chain import (
    DENSE_FOREIGN_START,
    OFFLINE_CONVERGE_20261025,
    converge_md,
    converge_verdict,
)
from foreign_sell_gate import OFFLINE_NOTE, any_promote, optimize_status_one_liner


def test_dense_start_and_offline_no_promote():
    assert DENSE_FOREIGN_START == "20260324"
    for track, cell in OFFLINE_CONVERGE_20261025.items():
        assert cell.get("promote_encoding") is False, track


def test_converge_verdict_never_buy_signal():
    td = tempfile.mkdtemp()
    db = os.path.join(td, "wayne_market.db")
    open(db, "wb").close()
    v = converge_verdict(db, artifact_root="/tmp/no-such-fear-chain")
    assert v["buy_signal"] is False
    assert v["promote_leave_zero"] is False
    assert v["promote_golden_buy"] is False
    assert v["any_promote_observe"] is False
    assert any_promote(db) is False
    md = converge_md(v)
    assert "不是買訊" in md
    assert "小賣→大賣" in md
    assert "反向" in md
    line = optimize_status_one_liner(db)
    assert "未過閘" in line


def test_offline_notes_mention_dense_window():
    assert "密窗" in OFFLINE_NOTE["escalate"]
    assert "n5" in OFFLINE_NOTE["escalate"]
    assert "橘六角" in OFFLINE_NOTE["calm"]
