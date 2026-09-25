# -*- coding: utf-8 -*-
"""大量區專圖：不改導航，查股第三張。"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_find_volume_zone_prefers_active_overhead():
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260806",
                "open": 1405,
                "high": 1530,
                "low": 1365,
                "close": 1530,
                "volume": 16305,
                "is_halt": False,
            },
            {
                "date": "20260917",
                "open": 1445,
                "high": 1460,
                "low": 1275,
                "close": 1320,
                "volume": 21653,
                "is_halt": False,
            },
            {
                "date": "20260924",
                "open": 1485,
                "high": 1530,
                "low": 1475,
                "close": 1495,
                "volume": 10047,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260806"
    assert zone["high"] == 1530
    assert zone["low"] == 1365
    assert zone["active"] is True


def test_render_volume_zone_png_6274():
    from vol_zone_chart import find_volume_zone, render_volume_zone_png
    from wayne_navigator import _load_ohlc, _nav_work_or_none

    db = get_db_path()
    work = _nav_work_or_none(_load_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    assert zone and zone["date"] == "20260806"
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "6274_vz.png")
        path = render_volume_zone_png("6274", "台燿", db, out)
        assert path and os.path.isfile(path)
        assert os.path.getsize(path) > 20000


def test_lookup_sends_volzone_third_photo():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "render_volume_zone_png" in src
    assert "volzone" in src
    assert "大量區" in src
    # 導航圖本身不再疊大量區
    nav = open("wayne_navigator.py", encoding="utf-8").read()
    assert "_paint_nav_volume_zone" not in nav
    assert "大量區壓" not in nav
