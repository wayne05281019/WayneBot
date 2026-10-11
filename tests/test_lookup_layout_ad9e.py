# -*- coding: utf-8 -*-
"""查股／高低卡排版再對：結構頭欄爆大量左緣；介紹卡基本面數值靠右。"""
from __future__ import annotations

import inspect

import matplotlib

matplotlib.use("Agg")
import matplotlib.axes

from wayne_navigator import (
    _paint_lr_box,
    _wrap_fit,
    clear_lookup_render_cache,
    render_first_glance_png,
)


def test_structure_header_uses_aligned_ohlc_helper():
    import biaoke_chart as bc

    assert hasattr(bc, "_paint_aligned_kv_row")
    mod = open(bc.__file__, encoding="utf-8").read()
    assert "_paint_aligned_kv_row" in mod
    assert "hdr-band-v74-ohlc-align" in mod
    # 爆大量壓撐列不准再 shared[1:] 對「高」欄縮進
    assert "spike_cols = shared[1:" not in mod
    assert "_col_starts(header_x, [spike_cells])" in mod


def test_aligned_kv_row_spike_shares_left_edge(tmp_path):
    """爆大量高／低／量與當日開高低量同一 x0 左緣。"""
    from biaoke_chart import _ow, _paint_aligned_kv_row

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)
    x0 = 5.2
    today = [("開", "5910"), ("高", "6065"), ("低", "5745"), ("量", "1,859張")]
    spike = [("高", "6115＝壓"), ("低", "5820＝撐"), ("量", "5,086張")]
    cols1 = _paint_aligned_kv_row(ax, x0, 7, today, color="#111", size=16)
    cols2 = _paint_aligned_kv_row(ax, x0, 4, spike, color="#ad1457", size=16)
    plt.close(fig)
    assert abs(cols1[0] - x0) < 1e-6
    assert abs(cols2[0] - x0) < 1e-6
    # 本列欄距仍依字寬，不准互壓
    assert cols2[1] > cols2[0] + _ow("高 6115＝壓", 16) - 0.01


def test_margin_fund_right_aligns_both_lines(tmp_path, monkeypatch):
    """資券兩行：數值 ha=right，與季營收／毛利同一右緣。"""
    clear_lookup_render_cache()
    texts = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        s = str(args[2] if len(args) >= 3 else kwargs.get("s") or "")
        x = float(args[0] if len(args) >= 1 else kwargs.get("x") or 0)
        y = float(args[1] if len(args) >= 2 else kwargs.get("y") or 0)
        ha = kwargs.get("ha") or "left"
        texts.append((x, y, s, ha))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)

    import matplotlib.pyplot as plt
    from wayne_navigator import _CARD

    fig, ax = plt.subplots(figsize=(7.1, 2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 20)
    C = _CARD
    _paint_lr_box(
        ax, 5, 5, 90, 7.4, "資券餘額",
        "融資 2,414張（2.7%）",
        "融券 9張（0.0%）",
        lab_c=C["ink_soft"], prim_c=C["ink"], sec_c=C["ink_soft"],
        fc=C["white"], ec=C["line"], lab_fs=11.5, prim_fs=13.0, sec_fs=11.5,
        value_ha="right",
    )
    plt.close(fig)
    prim = [t for t in texts if t[2].startswith("融資")]
    sec = [t for t in texts if t[2].startswith("融券")]
    assert prim and sec
    assert prim[0][3] == "right" and sec[0][3] == "right"
    assert abs(prim[0][0] - sec[0][0]) < 1e-6


def test_margin_one_line_when_fits():
    from wayne_navigator import GLANCE_FIG_W, _text_w

    s = "融資 9張（0.0%）　融券 1張（0.0%）"
    # 寬欄應一行
    lines = _wrap_fit(s, 13.0, 80.0, GLANCE_FIG_W)
    assert len(lines) == 1
    assert "融資" in lines[0] and "融券" in lines[0]


def test_glance_source_keeps_fund_right_align():
    src = inspect.getsource(render_first_glance_png)
    assert 'value_ha="right"' in src
    assert "資券餘額" in src
    # 不准再依行數切 left／right
    assert 'value_ha="left" if len(vlines)' not in src
