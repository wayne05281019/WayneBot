# -*- coding: utf-8 -*-
"""台股產業族群共振（實驗室；不是買訊；phone_sync=blocked）。"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True


def compute_sector_bull_ratio(panel: pd.DataFrame) -> pd.DataFrame:
    """panel 需含 date/symbol/sector/Close/MA20/MA60/angle_10。

    回傳每日每產業 sector_bull_ratio，並標 top30% sector_priority=1。
    """
    need = {"date", "symbol", "sector", "Close", "MA20", "MA60", "angle_10"}
    # 容許 index 是 date
    df = panel.copy()
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date"})
    missing = [c for c in ("symbol", "sector", "Close", "MA20", "MA60", "angle_10") if c not in df.columns]
    if missing:
        raise ValueError(f"缺少欄位: {missing}")
    df["bull"] = (df["Close"] > df["MA20"]) & (df["MA20"] > df["MA60"]) & (df["angle_10"] > 20)
    g = df.groupby(["date", "sector"], sort=False)["bull"].mean().rename("sector_bull_ratio")
    out = g.reset_index()
    # 每日產業排名前 30%
    out["sector_rank"] = out.groupby("date")["sector_bull_ratio"].rank(method="average", pct=True)
    out["sector_priority"] = (out["sector_rank"] >= 0.70).astype(float)
    out.attrs["phone_sync"] = PHONE_SYNC
    out.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
    return out


def merge_sector_priority(stock_row: pd.Series, sector_table: pd.DataFrame, date, sector: str) -> float:
    if sector_table is None or len(sector_table) == 0:
        return 0.0
    m = sector_table[(sector_table["date"] == date) & (sector_table["sector"] == sector)]
    if len(m) == 0:
        return 0.0
    return float(m.iloc[0]["sector_priority"])


__all__ = ["compute_sector_bull_ratio", "merge_sector_priority", "PHONE_SYNC", "NOT_BUY_SIGNAL"]
