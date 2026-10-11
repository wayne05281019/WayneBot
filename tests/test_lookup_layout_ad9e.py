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
    # v75＝下一壓帶；v74＝開高低量欄對齊（現況鍵已升 v75）
    assert (
        "hdr-band-v75-next-press" in mod
        or "hdr-band-v74-ohlc-align" in mod
    )
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


def test_monthly_revenue_labels_follow_yyyymm():
    from fundamentals import monthly_revenue_window_rows

    rows = monthly_revenue_window_rows(
        [
            {"yyyymm": "202609", "revenue": 1e8, "mom_pct": 1.0, "yoy_pct": 2.0, "ytd_yoy_pct": 3.0},
            {"yyyymm": "202608", "revenue": 1e8, "mom_pct": 1.0, "yoy_pct": 2.0, "ytd_yoy_pct": 3.0},
            {"yyyymm": "202607", "revenue": 1e8, "mom_pct": 1.0, "yoy_pct": 2.0, "ytd_yoy_pct": 3.0},
        ],
        limit=3,
    )
    assert [lab for lab, _ in rows] == ["9月營收", "8月營收", "7月營收"]
    assert "月營收近窗" not in "".join(lab for lab, _ in rows)
    assert "月營收2" not in "".join(lab for lab, _ in rows)
    # 值不再重複 09月'26；上行金額以億元結尾
    assert all("月'" not in val for _, val in rows)
    assert all("億元" in val for _, val in rows)


def test_structure_top_pad_lifts_header_frame():
    import biaoke_chart as bc

    assert float(bc._STRUCTURE_TOP_PAD) <= 0.35
    assert float(bc._STRUCTURE_TOP_PAD) < 1.35
    src = open(bc.__file__, encoding="utf-8").read()
    assert "name_y = 94.00 if fullbleed" in src
    assert "date_y, ohlc_y1 = 90.40, 86.80" in src


def test_month_revenue_splits_after_yi_for_right_edge():
    """7／8／9 月營收：上行停億元，兩行 ha=right，右緣與毛利同套。"""
    src = inspect.getsource(render_first_glance_png)
    assert 'endswith("月營收")' in src
    assert 'find("億元")' in src
    assert 'value_ha="right"' in src


def test_month_growth_token_colors_pos_red_neg_green():
    from wayne_navigator import _CARD, _month_growth_token_color

    C = _CARD
    assert _month_growth_token_color("月增+19.6%", C) == C["up"]
    assert _month_growth_token_color("年增+100.0%", C) == C["up"]
    assert _month_growth_token_color("累年增+50.3%", C) == C["up"]
    assert _month_growth_token_color("月增-68.1%", C) == C["down"]
    assert _month_growth_token_color("年增-3.2%", C) == C["down"]
    assert _month_growth_token_color("較上月改善；較去年同月大增", C) == C["ink_soft"]
    src = inspect.getsource(render_first_glance_png)
    assert "_paint_month_revenue_row" in src
    assert "month_growth" in src


def test_split_month_growth_and_note_two_lines():
    from wayne_navigator import _split_month_growth_and_note

    g, n = _split_month_growth_and_note(
        "月增+80.3%　年增+45.6%　累年增+45.6%　較上月大增・越來越好；較去年同月大增・越來越好"
    )
    assert g == "月增+80.3%　年增+45.6%　累年增+45.6%"
    assert "較上月大增" in n and "較去年同月" in n
    g2, n2 = _split_month_growth_and_note("月增-55.4%　年增-6.9%　累年增+45.7%")
    assert g2.startswith("月增-55.4%")
    assert n2 == ""
