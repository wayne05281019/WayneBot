# -*- coding: utf-8 -*-
"""對外 PNG：升降雙標上下對切；產業 kv 左標右值。"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.axes
from matplotlib.patches import FancyBboxPatch, Rectangle

from tests.test_sell_discipline import _mini_card_for_png
from wayne_navigator import dual_trend_half_boxes, dual_trend_pill_geom, render_decision_card_png


def test_dual_trend_pill_geom_splits_halves():
    h = 5.05
    g = dual_trend_pill_geom(h)
    assert abs(g["main_h"] - h / 2.0) < 1e-9
    assert abs(g["note_h"] - h / 2.0) < 1e-9
    assert abs(g["main_dy"] - h / 4.0) < 1e-9
    assert abs(g["note_dy"] - h / 4.0) < 1e-9
    assert abs(g["gap"]) < 1e-9
    main_bot = g["main_dy"] - g["main_h"] / 2.0
    note_top = -g["note_dy"] + g["note_h"] / 2.0
    assert abs(main_bot - note_top) < 1e-9
    boxes = dual_trend_half_boxes(40.0, 10.0, 14.8, h)
    mx, my, mw, mh = boxes["main_box"]
    nx, ny, nw, nh = boxes["note_box"]
    assert mx == nx == 40.0
    assert abs(mw - 14.8) < 1e-9 and abs(nw - 14.8) < 1e-9
    assert abs(mh - h / 2.0) < 1e-9 and abs(nh - h / 2.0) < 1e-9
    assert abs(ny - 10.0) < 1e-9
    assert abs(my - (10.0 + h / 2.0)) < 1e-9
    assert abs((my + mh) - (ny + nh + mh)) < 1e-9
    assert abs(boxes["main_xy"][1] - boxes["note_xy"][1] - h / 2.0) < 1e-9


def test_decision_card_dual_pills_do_not_overlap(tmp_path, monkeypatch):
    texts = []
    boxes = []
    orig_text = matplotlib.axes.Axes.text
    orig_patch = matplotlib.axes.Axes.add_patch

    def wrap_text(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        y = float(args[1] if len(args) >= 2 else kwargs.get("y") or 0)
        texts.append((y, s))
        return orig_text(self, *args, **kwargs)

    def wrap_patch(self, patch, *args, **kwargs):
        if isinstance(patch, Rectangle) and not isinstance(patch, FancyBboxPatch):
            boxes.append(
                (
                    float(patch.get_x()),
                    float(patch.get_y()),
                    float(patch.get_width()),
                    float(patch.get_height()),
                )
            )
        return orig_patch(self, patch, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap_text)
    monkeypatch.setattr(matplotlib.axes.Axes, "add_patch", wrap_patch)
    card = _mini_card_for_png()
    card["table"].loc[0, "升降"] = "最低溫"
    card["table"].loc[0, "升降註"] = "價未新低"
    out = tmp_path / "dual.png"
    path = render_decision_card_png(card, str(out))
    assert path and out.is_file()
    main_y = [y for y, t in texts if t == "最低溫"]
    note_y = [y for y, t in texts if t in ("未新低", "價未新低")]
    assert main_y and note_y
    assert abs(main_y[0] - note_y[0]) >= 2.40
    halves = [b for b in boxes if abs(b[3] - 2.525) < 0.12 and b[2] >= 12.0]
    assert len(halves) >= 2
    a, b = halves[-2], halves[-1]
    a0, a1 = a[1], a[1] + a[3]
    b0, b1 = b[1], b[1] + b[3]
    assert a1 <= b0 + 1e-6 or b1 <= a0 + 1e-6
    assert abs(a[2] - b[2]) < 1e-6


def test_decision_card_single_trend_stays_one_pill(tmp_path, monkeypatch):
    texts = []
    orig_text = matplotlib.axes.Axes.text

    def wrap_text(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        texts.append(s)
        return orig_text(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap_text)
    card = _mini_card_for_png()
    card["table"].loc[0, "升降"] = "升溫"
    card["table"].loc[0, "升降註"] = ""
    out = tmp_path / "single.png"
    path = render_decision_card_png(card, str(out))
    assert path and out.is_file()
    assert "升溫" in texts
    assert "未新低" not in texts


def test_industry_kv_uses_right_edge():
    from industry_card import _card_font, _wrap_px

    font = _card_font(32)
    lines = _wrap_px("半導體業含代工、記憶體、設計，不是只跟晶圓代工比。", font, 984)
    assert lines
    assert not any(ln[:1] in "。、；：）" for ln in lines)
    assert max(font.getlength(ln) for ln in lines) <= 984 + 1.0
    # 標左值右：量測函式把 kv 當獨立 kind
    import inspect

    from industry_card import render_industry_png as _fn

    src = inspect.getsource(_fn)
    assert '("kv", "產業"' in src
    assert '("kv", "這檔年增"' in src
    assert "pad_x + max_w - ln_w" in src


def test_stance_short_title_puts_note_on_same_row():
    from wayne_navigator import CARD_FIG_W, _stance_pane_plan, _text_w

    def tw(text, fs, weight=900):
        return _text_w(text, fs, CARD_FIG_W, weight)

    plan = _stance_pane_plan(
        "在低點附近，先看表",
        "表還壓在低附近。先看、先別急著買。",
        tw,
        2.6,
        CARD_FIG_W,
    )
    assert plan["same_row"]
    assert "先看" in plan["same_row"]
    assert plan["h"] < 6.0
