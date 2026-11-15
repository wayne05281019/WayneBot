# -*- coding: utf-8 -*-
"""低估名單最終結果 PNG：有列／空名單都能出圖。"""
from pathlib import Path

from PIL import Image

from undervalue_card import render_undervalue_png


def test_render_filled_and_empty(tmp_path):
    rows = [
        {
            "mark": "star",
            "stock_id": "2330",
            "name": "台積電",
            "close": 980,
            "pe": 22.4,
            "peer_pe_median": 28.1,
            "dist_to_floor_pct": -18.2,
            "flow_shares": 12345,
            "reason": "同鏈 PE 低於中位近兩成",
        },
        {
            "mark": "watch",
            "stock_id": "2454",
            "name": "聯發科",
            "close": 1285,
            "pe": 19.8,
            "peer_pe_median": 21.0,
            "dist_to_floor_pct": -4.1,
            "flow_shares": 5600,
            "reason": "先列觀察",
        },
    ]
    filled = str(tmp_path / "uv_filled.png")
    empty = str(tmp_path / "uv_empty.png")
    assert Path(render_undervalue_png(rows, filled, as_of="20261114")).is_file()
    assert Path(render_undervalue_png([], empty, as_of="20261114")).is_file()
    im_f = Image.open(filled)
    im_e = Image.open(empty)
    assert im_f.size[0] == 2160
    assert im_f.size[1] >= 2700
    assert im_e.size == (2160, 2700)
    assert Path(filled).stat().st_size > 8000
    assert Path(empty).stat().st_size > 4000
