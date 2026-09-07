# -*- coding: utf-8 -*-
"""正式庫：基準日齊、過濾器過、2383 獲利公式仍對。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.production_db

from automation_health import run_automation_audit
from config import fuse_end_date, get_db_path
from wayne_navigator import NavigatorEngine


def test_live_db_automation_audit_has_complete_as_of():
    path = get_db_path()
    cap = fuse_end_date()
    report = run_automation_audit(path, cap=cap, strict_release=False, max_gap_days=999)
    filt = (report.get("checks") or {}).get("quote_filter") or {}
    assert filt.get("ok") is True, filt
    complete = report.get("latest_complete") or ""
    assert complete and len(str(complete).replace("-", "")) == 8, report.get("reasons")
    if cap:
        assert str(complete).replace("-", "") <= str(cap).replace("-", "")


def test_live_2383_profit_formula_still_matches_card():
    """獲利＝近 60 曆日收盤低；2383 永久驗收鎖在公式，不鎖死某一天收盤。"""
    eng = NavigatorEngine(get_db_path())
    card = eng.get_decision_card("2383", merge_live=False)
    assert not card.get("error"), card.get("error")
    close = float(card.get("close") or 0)
    low = float(card.get("cal60_low") or 0)
    assert close > 0 and low > 0
    pct = (close / low - 1.0) * 100.0
    assert abs(float(card.get("gain_pct") or 0) - pct) < 0.08
    pinned = eng.get_decision_card("2383", merge_live=False, as_of="20260904")
    if str(pinned.get("latest_date") or "") == "20260904":
        p_close = float(pinned.get("close") or 0)
        p_low = float(pinned.get("cal60_low") or 0)
        assert p_close > 0 and p_low > 0
        p_pct = (p_close / p_low - 1.0) * 100.0
        assert abs(float(pinned.get("gain_pct") or 0) - p_pct) < 0.08
