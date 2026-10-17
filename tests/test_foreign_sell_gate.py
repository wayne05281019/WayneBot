# -*- coding: utf-8 -*-
"""外資／恐懼預警分軌閘門：未過閘不准正式；非買訊。"""
from __future__ import annotations

import os
import tempfile

from foreign_sell_gate import (
    all_track_gates,
    any_promote,
    gate_table_md,
    optimize_status_one_liner,
)


def test_gate_all_test_no_promote_empty_db():
    td = tempfile.mkdtemp()
    db = os.path.join(td, "wayne_market.db")
    open(db, "wb").close()
    gates = all_track_gates(db)
    assert len(gates) == 4
    assert any_promote(db) is False
    for g in gates:
        assert g["buy_signal"] is False
        assert g["promote_observe_copy"] is False
        assert g["display_mode"] == "test"
        assert g["wins_current"] is False
    line = optimize_status_one_liner(db)
    assert line.startswith("明確優化狀態：")
    assert "未過閘" in line
    assert "還在測試" in line
    assert "非買訊" in line
    md = gate_table_md(db)
    assert "開盤前恐懼" in md
    assert "還在測試" in md
