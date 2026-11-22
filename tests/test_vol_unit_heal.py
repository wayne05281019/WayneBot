# -*- coding: utf-8 -*-
"""daily_quotes 股／張混用：爆大量日選核與量標必須用張。"""
from __future__ import annotations

import sqlite3

import pandas as pd


def test_volume_lots_healed_from_turnover():
    from vol_zone_chart import volume_lots_healed

    # 2330 20261015：股數級 volume + 真成交金額 → 約 5.8 萬張
    lots = volume_lots_healed(48190233, close=2440.0, turnover_k=142629538.81)
    assert 50000 <= lots <= 70000
    # 已是張：不變
    assert volume_lots_healed(110714, close=2195.0, turnover_k=110714 * 2195) == 110714


def test_volume_lots_healed_abs_fallback():
    from vol_zone_chart import volume_lots_healed

    assert volume_lots_healed(48_190_233) == 48190
    assert volume_lots_healed(110714) == 110714


def test_find_volume_zone_ignores_share_spike():
    """近窗若混入股數級假爆量，選核必須改認真張最大日。"""
    from vol_zone_chart import find_volume_zone

    # 42 根：前段普通張、中段假股數爆量、真張爆量、末日
    rows = []
    for i in range(40):
        rows.append(
            {
                "date": f"{20260901 + i}",
                "open": 2100.0,
                "high": 2200.0,
                "low": 2000.0,
                "close": 2150.0,
                "volume": 30000 + i,
                "turnover_k": float((30000 + i) * 2150),
                "is_halt": False,
            }
        )
    # 覆蓋第 10 根＝假股數爆量（高仍在頭上）
    rows[10] = {
        "date": "20260911",
        "open": 2440.0,
        "high": 2450.0,
        "low": 2420.0,
        "close": 2440.0,
        "volume": 48_190_233,
        "turnover_k": float(58_455 * 2440),
        "is_halt": False,
    }
    # 覆蓋第 35 根＝真張爆量
    rows[35] = {
        "date": "20261006",
        "open": 2100.0,
        "high": 2195.0,
        "low": 2020.0,
        "close": 2180.0,
        "volume": 110_714,
        "turnover_k": float(110_714 * 2180),
        "is_halt": False,
    }
    # 末日
    rows.append(
        {
            "date": "20261011",
            "open": 2170.0,
            "high": 2180.0,
            "low": 2150.0,
            "close": 2170.0,
            "volume": 61610,
            "turnover_k": float(61610 * 2170),
            "is_halt": False,
        }
    )
    work = pd.DataFrame(rows)
    zone = find_volume_zone(work, lookback=40)
    assert zone is not None
    assert zone["date"] == "20261006"
    assert zone["volume"] == 110_714
    assert zone["high"] == 2195.0
    assert zone["low"] == 2020.0


def test_scrub_daily_quotes_share_volumes(tmp_path):
    from vol_zone_chart import scrub_daily_quotes_share_volumes

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes(
          date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
          open REAL, high REAL, low REAL, close REAL, volume INTEGER,
          turnover_k REAL, pct_change REAL, avg_price REAL,
          PRIMARY KEY(date, stock_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO daily_quotes
        VALUES ('20261015','2330','台積電','TW',2440,2450,2420,2440,48190233,142629538.81,0,2440)
        """
    )
    conn.execute(
        """
        INSERT INTO daily_quotes
        VALUES ('20261106','2330','台積電','TW',2100,2195,2020,2180,110714,241356520,0,2180)
        """
    )
    conn.commit()
    conn.close()
    out = scrub_daily_quotes_share_volumes(str(db), since_ymd="20260101")
    assert out["n"] == 1
    assert out["stocks"] == ["2330"]
    conn = sqlite3.connect(db)
    v15 = conn.execute(
        "SELECT volume FROM daily_quotes WHERE date='20261015'"
    ).fetchone()[0]
    v06 = conn.execute(
        "SELECT volume FROM daily_quotes WHERE date='20261106'"
    ).fetchone()[0]
    conn.close()
    assert 50000 <= int(v15) <= 70000
    assert int(v06) == 110714


def test_legend_cat_not_buy_sell_wording():
    from ink_chart_theme import _key_cats
    import inspect

    src = inspect.getsource(_key_cats)
    assert "訊號・標記" in src
    assert "訊號・買賣" not in src


def test_biaoke_vol_label_never_writes_share_as_lot():
    from biaoke_chart import _vol

    assert _vol(48_190_233) == "48,190張"
    assert _vol(110_714) == "110,714張"
