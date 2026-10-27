# -*- coding: utf-8 -*-
"""墨線套皮：可關閉、失敗不炸、字型走 repo fonts。"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest


def test_ink_fonts_resolve_under_repo():
    import ink_chart_theme as ink

    assert os.path.isfile(ink.FONT_H), ink.FONT_H
    assert os.path.isfile(ink.FONT_M), ink.FONT_M


def test_ink_kill_switch(monkeypatch):
    import ink_chart_theme as ink

    monkeypatch.setenv("WAYNE_INK_CHART", "0")
    fig = plt.figure(figsize=(4, 3), dpi=72)
    try:
        assert ink.ink_chart_enabled() is False
        assert ink.maybe_apply_ink(fig, "struct") is False
        assert ink.maybe_apply_ink(fig, "vol") is False
    finally:
        plt.close(fig)


def test_maybe_apply_ink_tolerates_empty_figure(monkeypatch):
    import ink_chart_theme as ink

    monkeypatch.setenv("WAYNE_INK_CHART", "1")
    fig = plt.figure(figsize=(4, 3), dpi=72)
    fig.add_subplot(111)
    try:
        # 空圖也可能套皮失敗；不准噴出例外
        ink.maybe_apply_ink(fig, "struct")
        ink.maybe_apply_ink(fig, "vol")
    finally:
        plt.close(fig)


def test_structure_and_vol_zone_call_maybe_apply_ink():
    import inspect

    import biaoke_chart
    import vol_zone_chart

    st = inspect.getsource(biaoke_chart.render_biaoke_structure_png)
    assert "maybe_apply_ink" in st
    vz = inspect.getsource(vol_zone_chart._paint_volume_zone)
    assert "maybe_apply_ink" in vz
