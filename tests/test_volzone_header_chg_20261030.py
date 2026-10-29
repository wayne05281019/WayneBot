# -*- coding: utf-8 -*-
"""2026-10-30：大量區表頭收旁真昨收漲跌（上下並排、可讀字級）。"""
from __future__ import annotations

import inspect
import re

from tg_layout import format_move_plain


def test_format_move_plain_is_single_line():
    s = format_move_plain(-172.6, -20.94)
    assert "\n" not in s
    assert "▼" in s
    assert "20.94" in s or "−" in s or "-" in s
    assert "%" in s


def test_volzone_header_passes_stacked_move_bits():
    import vol_zone_chart as vz

    src = inspect.getsource(vz)
    assert "_wayne_close_move_pts" in src
    assert "_wayne_close_move_pct" in src
    chunk = src[src.index("close_bit = f"): src.index("日標已改掛主K上框內側")]
    assert "hdr_quote" in chunk
    assert "prev_close_hdr" in chunk
    assert "15.6" in chunk  # 收字級鎖原本
    assert "move_pts" in chunk and "move_pct_s" in chunk
    assert "不准在此再畫一層" in chunk or "masthead" in chunk


def test_ink_masthead_stacks_move_larger_keeps_close():
    import ink_chart_theme as ink

    src = inspect.getsource(ink.vol_masthead)
    assert "_wayne_close_move_pts" in src
    assert "_wayne_close_move_pct" in src
    assert "close_move" in src
    assert "上下並排" in src
    assert "15.5" in src  # 昨比加大起點
    assert "CLOSE_FS" in src
    assert "不准為塞昨比縮小" in src or "不准動收" in src or "鎖死原本" in src
    assert "close_fs -=" not in src
    assert "不上色底" in src or "色底只套收價" in src or "普通日不上色底" in src


def test_header_move_matches_real_prev_math():
    """真昨收算點／％；不准假數。"""
    close, prev = 651.61, 824.21
    chg = round(close - prev, 4)
    pct = round(chg / prev * 100.0, 2)
    plain = format_move_plain(chg, pct)
    assert re.search(r"[▲▼]", plain)
    assert "20.94" in plain or f"{abs(pct):.2f}" in plain
    assert f"{abs(chg):.2f}" in plain or "172.60" in plain
