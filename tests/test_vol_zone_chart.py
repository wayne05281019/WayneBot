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


def test_find_volume_zone_excludes_last_bar():
    """最後一根即使量最大也不當大量區參考日。"""
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260901",
                "open": 100,
                "high": 120,
                "low": 90,
                "close": 110,
                "volume": 5000,
                "is_halt": False,
            },
            {
                "date": "20260902",
                "open": 110,
                "high": 115,
                "low": 105,
                "close": 112,
                "volume": 90000,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260901"
    assert zone["volume"] == 5000


def test_render_volume_zone_png_6274():
    from vol_zone_chart import find_volume_zone, render_volume_zone_png
    from wayne_navigator import _load_ohlc, _nav_work_or_none

    db = get_db_path()
    work = _nav_work_or_none(_load_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    assert zone and zone["date"] == "20260806"
    assert float(zone["high"]) == 1530.0
    assert float(zone["low"]) == 1365.0
    last = work.iloc[-1]
    assert float(last["high"]) == 1530.0
    assert float(last["close"]) == 1495.0
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
    assert src.find("_send_lookup_album") < src.find("await volzone_task")
    # 興櫃與上市櫃同一條；不准另開跳過大量區的路徑
    assert "if is_em:" in src
    assert src.find("if is_em:") < src.find("render_volume_zone_png")
    assert "merge_live=not is_em" in src
    # 導航圖本身不再疊大量區
    nav = open("wayne_navigator.py", encoding="utf-8").read()
    assert "_paint_nav_volume_zone" not in nav
    assert "大量區壓" not in nav


def test_render_volume_zone_png_markets_twse_otc_emerging():
    """上市／上櫃／興櫃都能渲出大量區專圖（查股第三張同一條）。"""
    from emerging_quotes import load_stock_bars
    from vol_zone_chart import render_volume_zone_png
    from wayne_navigator import _load_ohlc

    db = get_db_path()
    cases = [
        ("2330", "台積電", "twse"),
        ("6488", "環球晶", "otc"),
        ("1260", "富味鄉", "emerging"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for sid, name, kind in cases:
            if kind == "emerging":
                df = load_stock_bars(db, sid, 120)
            else:
                df = _load_ohlc(sid, db, 180)
            assert df is not None and not df.empty, (sid, kind)
            out = os.path.join(tmp, f"{sid}_vz.png")
            path = render_volume_zone_png(
                sid, name, db, out, df, already_normalized=False
            )
            assert path and os.path.isfile(path), (sid, kind)
            assert os.path.getsize(path) > 15000, (sid, kind, os.path.getsize(path))


def test_emerging_help_mentions_volzone():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._em_no_listed_html)
    assert "大量區" in src
    mod = open("bot_servers.py", encoding="utf-8").read(800)
    assert "上市／上櫃／興櫃一律" in mod
    assert "大量區專圖" in mod
