# -*- coding: utf-8 -*-
"""官方加權／台指期核對 45839、46506、右肩；第一篇智原 370。"""
from __future__ import annotations

import sqlite3

from biaoke_verify import (
    check_cross,
    format_origin_backtest,
    format_watch,
    origin_first_post,
    right_shoulder,
)


def test_right_shoulder_higher_high_higher_low():
    bars = [
        {"date": "20260901", "high": 46948.72, "low": 46081.11, "close": 46948.72},
        {"date": "20260902", "high": 46946.60, "low": 46164.72, "close": 46164.72},
        {"date": "20260903", "high": 46517.45, "low": 45839.36, "close": 45857.66},
        {"date": "20260904", "high": 46620.96, "low": 45966.86, "close": 46551.13},
        {"date": "20260907", "high": 47429.58, "low": 46724.00, "close": 47326.27},
        {"date": "20260911", "high": 46651.21, "low": 45942.44, "close": 46184.85},
    ]
    sh = right_shoulder(bars, pivot_ymd="20260903", pivot_low=45839.0)
    assert sh["ok"]
    assert sh["held"] is True
    assert sh["passed_prior_high"] is True
    assert sh["hh_date"] == "20260907"
    assert sh["broke_on"] == ""
    assert abs(sh["prior_high"] - 46948.72) < 0.02


def test_right_shoulder_breaks_when_later_low_cuts_pivot():
    bars = [
        {"date": "20260901", "high": 100, "low": 90, "close": 95},
        {"date": "20260903", "high": 92, "low": 80, "close": 81},
        {"date": "20260904", "high": 99, "low": 79, "close": 85},
    ]
    sh = right_shoulder(bars, pivot_ymd="20260903", pivot_low=80)
    assert sh["ok"]
    assert sh["held"] is False
    assert sh["broke_on"] == "20260904"


def test_cross_46506_from_night_bar():
    night = {
        "date": "20260911",
        "high": 46574.0,
        "low": 46041.0,
        "close": 46503.0,
        "open": 46306.0,
        "update_time": "22:25:43",
        "source": "taifex_mis",
        "is_realtime": True,
    }
    hit = check_cross(night, 46506.0)
    assert hit["ok"]
    assert hit["crossed"] is True
    assert hit["above_last"] is False
    html = format_watch("", live_night=night)
    assert "45839" in html
    assert "46506" in html
    assert "高已穿越 46506" in html
    assert "現價回到 46506 之下" in html
    assert "15 分" in html
    assert "不是買訊" in html
    assert "語料" not in html


def test_origin_first_post_without_bar():
    row = origin_first_post("")
    assert row["date"] == "2023-12-04"
    assert row["stock_id"] == "3035"
    assert row["claimed"] == 370.0
    assert row["bar"] is None
    text = format_origin_backtest("")
    assert "2023-12-04" in text
    assert "智原" in text
    assert "370" in text
    assert "庫沒" in text
    assert "語料" not in text


def test_origin_first_post_uses_official_bar(tmp_path):
    db = str(tmp_path / "v.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("20231204", "3035", "智原", "TW", 392, 393.5, 374.5, 380, 23573),
    )
    conn.commit()
    conn.close()
    row = origin_first_post(db)
    assert row["held_that_day"] is True
    assert abs(float(row["bar"]["low"]) - 374.5) < 0.01
    text = format_origin_backtest(db)
    assert "當日低有守" in text
    assert "380" in text
