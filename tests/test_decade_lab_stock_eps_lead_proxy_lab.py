# -*- coding: utf-8 -*-
"""stock_eps_lead_proxy_lab：純函式煙測（不改買訊）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.decade_lab_stock_eps_lead_proxy_lab import (
    BUY_SIGNAL,
    CONFIRM_NAMES,
    PHONE_SYNC,
    SELL_KEEP,
    _ymd,
    confirm_masks_eps_lead,
    eps_lead_masks_for_dates,
    roc_pub_to_ymd,
    season_available_fallback,
    stocks_with_eps_ge2,
)
from scripts.decade_lab_stock_tech_confirm_lab import tech_features


def test_phone_flags_blocked():
    assert PHONE_SYNC == "blocked"
    assert BUY_SIGNAL is False
    assert SELL_KEEP == "hi20_or_desync"
    assert "eps_qoq_up" in CONFIRM_NAMES
    assert "eps_turn_pos" in CONFIRM_NAMES


def test_roc_and_fallback_available():
    assert _ymd("2026-11-10") == "20261110"
    assert roc_pub_to_ymd("1151106") == "20261106"
    assert roc_pub_to_ymd("1151029") == "20261029"
    assert roc_pub_to_ymd("20261106") == "20261106"
    assert roc_pub_to_ymd("") == ""
    assert season_available_fallback(2026, 1) == "20260515"
    assert season_available_fallback(2026, 2) == "20260814"
    assert season_available_fallback(2026, 3) == "20261114"
    assert season_available_fallback(2025, 4) == "20260331"


def test_eps_mask_respects_publish_date():
    # Q3 出表 11/06；11/05 不准吃到 Q3 轉佳
    rows = [
        {
            "year": 2025,
            "season": 4,
            "season_key": 20254,
            "eps": 1.0,
            "published_roc": "1150331",
            "available_from": "20260331",
        },
        {
            "year": 2026,
            "season": 1,
            "season_key": 20261,
            "eps": 0.8,
            "published_roc": "1150515",
            "available_from": "20260515",
        },
        {
            "year": 2026,
            "season": 2,
            "season_key": 20262,
            "eps": 1.2,
            "published_roc": "1150814",
            "available_from": "20260814",
        },
        {
            "year": 2026,
            "season": 3,
            "season_key": 20263,
            "eps": 2.0,
            "published_roc": "1151106",
            "available_from": "20261106",
        },
    ]
    dates = ["20261105", "20261106", "20261110"]
    m = eps_lead_masks_for_dates(dates, rows)
    # 11/05 只用到 Q1→Q2（0.8→1.2）已轉佳
    assert bool(m["eps_qoq_up"].iloc[0]) is True
    # 11/06 起看到 Q2→Q3（1.2→2.0）
    assert bool(m["eps_qoq_up"].iloc[1]) is True
    assert bool(m["eps_qoq_up_2"].iloc[1]) is True  # 0.8→1.2→2.0 連兩段
    assert bool(m["eps_qoq_up_pos"].iloc[2]) is True


def test_turn_pos_and_confirm_keys():
    rows = [
        {
            "year": 2026,
            "season": 1,
            "season_key": 20261,
            "eps": -0.5,
            "published_roc": "",
            "available_from": "20260515",
        },
        {
            "year": 2026,
            "season": 2,
            "season_key": 20262,
            "eps": 0.3,
            "published_roc": "",
            "available_from": "20260814",
        },
    ]
    m = eps_lead_masks_for_dates(["20260820"], rows)
    assert bool(m["eps_turn_pos"].iloc[0]) is True
    assert bool(m["eps_qoq_up"].iloc[0]) is True

    n = 60
    close = np.linspace(80, 100, n)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=n, freq="B").strftime("%Y%m%d"),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 2000.0),
        }
    )
    tech = tech_features(df)
    masks = confirm_masks_eps_lead(df=df, eps_rows=rows, tech_feat=tech)
    assert set(CONFIRM_NAMES) <= set(masks.keys())
    assert bool(masks["plain"].all())


def test_stocks_with_eps_ge2_reads_db(tmp_path):
    import sqlite3

    db = tmp_path / "qi.db"
    con = sqlite3.connect(str(db))
    con.execute(
        """
        CREATE TABLE quarterly_income(
          stock_id TEXT, year INT, season INT, stock_name TEXT, market TEXT,
          revenue REAL, cogs REAL, gross_profit REAL, gross_margin_pct REAL,
          operating_income REAL, net_income REAL, eps REAL,
          published_roc TEXT, updated_at TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO quarterly_income(stock_id,year,season,eps) VALUES (?,?,?,?)",
        [("2330", 2026, 1, 1.0), ("2330", 2026, 2, 1.2), ("9999", 2026, 2, 0.5)],
    )
    con.commit()
    con.close()
    got = stocks_with_eps_ge2(db)
    assert got == ["2330"]
