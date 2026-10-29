# -*- coding: utf-8 -*-
"""2026-10-30：大量區表頭「收／現」旁同列真昨收漲跌點＋％。"""
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


def test_volzone_header_paints_move_beside_close():
    import vol_zone_chart as vz

    src = inspect.getsource(vz)
    # 收旁同列漲跌
    assert "format_move_plain" in src
    assert "_wayne_close_move_plain" in src
    assert "_fp_move" in src or "_fp(11.2" in src
    assert "不准跨行" in src or "同列" in src
    # 真昨收：優先 hdr_quote change／pct，否則 close−prev
    chunk = src[src.index("close_bit = f"): src.index("日標已改掛主K上框內側")]
    assert "hdr_quote" in chunk
    assert "prev_close_hdr" in chunk
    assert "format_move_plain" in chunk
    # 字不必大：move 字級 < close
    assert "15.6" in chunk
    assert "11.2" in chunk


def test_ink_masthead_paints_close_move_no_bg_for_normal():
    import ink_chart_theme as ink

    src = inspect.getsource(ink.vol_masthead)
    assert "_wayne_close_move_plain" in src
    assert "close_move" in src
    # 普通日漲跌字不加底（色底只套收價）
    assert "不加底" in src or "不上色底" in src or "色底只套收價" in src


def test_header_move_matches_real_prev_math():
    """真昨收算點／％；不准假數。"""
    close, prev = 651.61, 824.21
    chg = round(close - prev, 4)
    pct = round(chg / prev * 100.0, 2)
    plain = format_move_plain(chg, pct)
    assert re.search(r"[▲▼]", plain)
    assert "20.94" in plain or f"{abs(pct):.2f}" in plain
    assert f"{abs(chg):.2f}" in plain or "172.60" in plain
