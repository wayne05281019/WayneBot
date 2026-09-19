# -*- coding: utf-8 -*-
"""獲利欄量化鎖：對官方 60 曆日低、Cary 2438 表、不能 0 卻貼 20 高。"""
from __future__ import annotations

import pytest

from profit_quant import (
    CARY_2438_PROFIT,
    cary_2438_mismatches,
    report_lines,
    scan_profit_contradictions,
)
from tests.conftest import require_production_db


def test_scan_flags_zero_bar_poison_on_old_shape():
    """舊公式會把 7/6 收 0 洗成 9/4 獲利 0＋20高；現行公式不得再出這組矛盾。"""
    import pandas as pd

    from profit_quant import _scan_one

    df = pd.DataFrame(
        {
            "date": [
                "20260706",
                "20260730",
                "20260825",
                "20260903",
                "20260904",
                "20260907",
            ],
            "close": [0.0, 16.45, 17.7, 22.05, 21.9, 20.85],
        }
    )
    issues = _scan_one("2438", df, lookback=6)
    kinds = {x["kind"] for x in issues}
    assert "high_zero" not in kinds
    assert "cliff" not in kinds


@pytest.mark.production_db
def test_cary_2438_profit_matches_official_cal60():
    db = require_production_db()
    bad = cary_2438_mismatches(db, as_of="20260917")
    assert not bad, bad
    assert CARY_2438_PROFIT["20260904"] == 33.1


@pytest.mark.production_db
def test_market_profit_has_no_high_zero_or_cliff():
    db = require_production_db()
    scan = scan_profit_contradictions(db, limit_names=250, lookback=40)
    from pathlib import Path

    art = Path("/opt/cursor/artifacts")
    try:
        art.mkdir(parents=True, exist_ok=True)
        (art / "profit_quant_lock.txt").write_text(report_lines(scan), encoding="utf-8")
    except OSError:
        pass
    assert scan["names"] >= 80, scan
    assert not scan["high_zero"], scan["high_zero"][:8]
    assert not scan["cliff"], scan["cliff"][:8]
