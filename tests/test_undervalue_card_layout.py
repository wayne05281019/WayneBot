# -*- coding: utf-8 -*-
"""低估名單 PNG 排版防呆：數字欄不互壓、NaN 不印、收盤不改檔位、理由不切數字。"""
import os
import re

from PIL import Image

import undervalue_card as uc


def _real_stress_rows():
    # 收盤／證交所本益取自 daily_valuation 20261109：聯亞 1925／122.77、合一 46.5／357.69、信驊 11700
    return [
        {"mark": "watch", "stock_id": "3081", "name": "聯亞", "close": 1925.0, "pe": 122.77,
         "peer_pe_median": 122.77, "dist_to_floor_pct": -123.4, "flow_shares": 123456},
        {"mark": "watch", "stock_id": "4743", "name": "合一", "close": 46.5, "pe": 357.69,
         "pe_est": True, "dist_to_floor_pct": 3.2},
        {"mark": "star", "stock_id": "5274", "name": "信驊", "close": 11700.0, "pe": 78.05,
         "flow_shares": 820},
    ]


def test_number_columns_leave_gap_for_widest_cell():
    col_f = uc._font(22, bold=True)
    cell_f = uc._font(30, bold=True)
    cells = [uc._cells(r) for r in _real_stress_rows()]
    heads = {"close": "收盤", "pe": "PE", "med": "中位", "dist": "距下緣％", "flow": "流動張"}
    cols = uc._column_widths(cells, heads, col_f, cell_f)
    for key in uc.COL_MIN:
        widest = max(cell_f.getlength(c[key]) for c in cells)
        assert cols[key] >= widest + uc._px(uc.COL_GAP), key


def test_nan_inf_missing_render_dash():
    nan, inf = float("nan"), float("inf")
    assert uc._fmt_pct(nan) == "—"
    assert uc._fmt_flow(nan) == "—"
    assert uc._fmt_num(inf) == "—"
    assert uc._fmt_close(None) == "—"


def test_close_keeps_official_tick_and_flow_uniform():
    assert uc._fmt_close(21.35) == "21.35"
    assert uc._fmt_close(168.5) == "168.5"
    assert uc._fmt_close(980) == "980"
    assert uc._fmt_close(11700.0) == "11700"
    assert uc._fmt_flow(12345) == "12,345"
    assert uc._fmt_flow(820) == "820"


def test_reason_wrap_never_cuts_numbers():
    f = uc._font(24)
    text = "長股名、NaN；理由很長很長要看會不會把數字切斷：投信 5 日買超 12,345 張、綜合空間 31.2%、脫離零第 2 天"
    max_w = f.getlength(text) * 0.55
    lines = uc._wrap_reason(f, text, max_w)
    assert 2 <= len(lines) <= uc.REASON_MAX_LINES
    assert all(f.getlength(x) <= max_w + 1 for x in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
    for num in ("12,345", "31.2%"):
        assert sum(num in x for x in lines) == 1
    assert not any(x[:1] in uc._NO_LINE_START for x in lines)


def test_reason_overflow_truncates_on_token_boundary():
    f = uc._font(24)
    text = "，".join(f"投信 {i} 日買超 {i * 1111:,} 張" for i in range(1, 30))
    lines = uc._wrap_reason(f, text, 600)
    assert len(lines) == uc.REASON_MAX_LINES
    assert lines[-1].endswith("…")
    nums = set(re.findall(r"\d[\d,]*", text))
    for x in lines:
        for n in re.findall(r"\d[\d,]*", x.rstrip("…")):
            assert n in nums


def test_no_invented_date_and_module_relative_font():
    assert uc._as_of_label(None) == ""
    assert uc._as_of_label("20261114") == "2026-11-14（台北）"
    bundled = os.path.join(os.path.dirname(os.path.abspath(uc.__file__)), "fonts")
    if os.path.isdir(bundled):
        assert os.path.dirname(uc._font(10).path) == bundled


def test_star_rows_first_and_estimate_footnote(tmp_path):
    rows = _real_stress_rows()
    assert [r["stock_id"] for r in uc._order_rows(rows)] == ["5274", "3081", "4743"]
    p = uc.render_undervalue_png(rows, str(tmp_path / "uv.png"), as_of="20261109")
    im = Image.open(p)
    assert im.size[0] == uc._px(uc.BASE_W) and im.size[1] >= uc._px(uc.BASE_H)
    long_rows = [dict(rows[0], reason="理由") for _ in range(14)]
    im2 = Image.open(uc.render_undervalue_png(long_rows, str(tmp_path / "long.png")))
    assert im2.size[1] > uc._px(uc.BASE_H)
