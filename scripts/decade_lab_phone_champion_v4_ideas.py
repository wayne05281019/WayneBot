# -*- coding: utf-8 -*-
"""V4 因子庫：v3 厚樣未抬 B 後再生；材料限既有 feat 欄。phone_sync=blocked。"""
from __future__ import annotations

from typing import Dict

import pandas as pd


def _bool(col, idx) -> pd.Series:
    if col is None:
        return pd.Series(False, index=idx)
    if isinstance(col, pd.Series):
        return col.reindex(idx).fillna(False).astype(bool)
    return pd.Series(False, index=idx)


def build_v4_extras(df: pd.DataFrame, feat: pd.DataFrame) -> Dict[str, pd.Series]:
    idx = df.index
    c = df["close"].astype(float)
    o = df["open"].astype(float)

    prior5 = pd.to_numeric(feat.get("prior_high_5"), errors="coerce")
    var = pd.to_numeric(feat.get("vol_attack_ratio"), errors="coerce")
    prior5_break = (c > prior5) & (var.fillna(0) >= 1.3)

    body = pd.to_numeric(feat.get("candle_body_ratio"), errors="coerce")
    body_thrust = (body.fillna(0) >= 0.55) & (c > o)

    s60 = pd.to_numeric(feat.get("ma60_time_safety"), errors="coerce")
    deduct = feat.get("deduction_accelerating")
    if deduct is None:
        t60_safe = s60.fillna(-9) > 0
    else:
        t60_safe = (s60.fillna(-9) > 0) & (~_bool(deduct, idx))

    week = _bool(feat.get("weekly_trend_bullish"), idx)
    w13 = pd.to_numeric(feat.get("w_ma13_safety"), errors="coerce")
    w_kd_hot = feat.get("w_kd_high_passivation")
    week_stack = week & (w13.fillna(-9) > 0) & (~_bool(w_kd_hot, idx))

    gap_br = _bool(feat.get("gap_breakaway_candidate"), idx)
    gap_fill = _bool(feat.get("gap_filled_within_3d"), idx)
    gap_hold = gap_br & (~gap_fill)

    no_fake = ~_bool(feat.get("fake_breakout_exit"), idx)

    return {
        "V4_prior5_break": prior5_break.fillna(False),
        "V4_body_thrust": body_thrust.fillna(False),
        "V4_t60_safe": t60_safe.fillna(False),
        "V4_week_stack": week_stack.fillna(False),
        "V4_gap_hold": gap_hold.fillna(False),
        "V4_no_fake_break": no_fake.fillna(False),
        "V4_break_body": prior5_break.fillna(False) & body_thrust.fillna(False),
        "V4_week_t60": week_stack.fillna(False) & t60_safe.fillna(False),
    }


__all__ = ["build_v4_extras"]
