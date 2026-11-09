# -*- coding: utf-8 -*-
"""LAB-ONLY lookup mark flags：預設關、phone_sync blocked、stubs no-op。"""
from __future__ import annotations


def test_lookup_lab_marks_default_off():
    from scripts.decade_lab_lookup_mark_flags import (
        LAB_BUY_W3_START,
        LOOKUP_LAB_MARKS_ENABLED,
        PHONE_SYNC,
        REL_HIGH_SELL,
        lab_marks_allowed,
        maybe_paint_lab_lookup_marks,
        paint_lab_buy_indices,
        paint_lab_sell_indices,
    )

    assert LOOKUP_LAB_MARKS_ENABLED is False
    assert PHONE_SYNC == "blocked"
    assert LAB_BUY_W3_START == "LAB_BUY_W3_START"
    assert REL_HIGH_SELL == "REL_HIGH_SELL"
    assert lab_marks_allowed() is False
    assert paint_lab_buy_indices(work=None) == []
    assert paint_lab_sell_indices(work=None) == []
    assert maybe_paint_lab_lookup_marks(None, None, None, chart_kind="nav") is False


def test_enabled_still_blocked_without_promote(monkeypatch):
    import scripts.decade_lab_lookup_mark_flags as flags

    monkeypatch.setattr(flags, "LOOKUP_LAB_MARKS_ENABLED", True)
    monkeypatch.setattr(flags, "_read_gate", lambda: {"promote_to_lookup_display": True})
    # module PHONE_SYNC still blocked → refuse
    assert flags.lab_marks_allowed() is False


def test_wayne_navigator_wrapper_noop():
    from wayne_navigator import _maybe_lab_lookup_marks

    assert _maybe_lab_lookup_marks(None, None, None, chart_kind="card") is False


def test_paint_paths_mention_lab_hook():
    import inspect

    from biaoke_chart import render_biaoke_structure_png
    from intraday_open_close_chart import render_lookup_intraday_result
    from wayne_navigator import (
        _paint_nav_on_axes,
        overlay_nav_marks_on_zone,
        render_decision_card_png,
        render_first_glance_png,
    )

    for fn in (
        render_decision_card_png,
        render_first_glance_png,
        _paint_nav_on_axes,
        overlay_nav_marks_on_zone,
        render_biaoke_structure_png,
        render_lookup_intraday_result,
    ):
        assert "_maybe_lab_lookup_marks" in inspect.getsource(fn)
