# -*- coding: utf-8 -*-
"""台股價格還原 V7（實驗室；不是買訊；phone_sync=blocked）。

- Ratio-Adjusted OHLC（有 Adj Close）
- V7 corporate_action_sanitizer：法定漲跌幅越界＝減資／面額變更換股，無縫接合
- Continuous_OHLC（基準 100）供特徵／波浪計算
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
LIMIT_CUT = pd.Timestamp("2015-06-01")


def _colmap(df: pd.DataFrame) -> dict:
    return {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}


def _find_adj(df: pd.DataFrame, cm: dict, adj_close_col: Optional[str]) -> Optional[str]:
    if adj_close_col is not None:
        if adj_close_col in df.columns:
            return adj_close_col
        raise ValueError(f"找不到 Adj Close 欄: {adj_close_col}")
    for cand in ("adj_close", "adjclose", "adjusted_close", "adj_close_price"):
        if cand in cm:
            return cm[cand]
    return None


def _limit_bound(ts) -> float:
    try:
        t = pd.Timestamp(ts)
    except Exception:
        return 0.105
    return 0.073 if t < LIMIT_CUT else 0.105


def corporate_action_sanitizer(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, List[dict]]:
    """偵測減資／面額變更裂口，向前回溯調整使序列無縫。

    對每個異常日 t：split_ratio = Close[t-1] / Open[t]，
    將 t 日「以前」的 OHLC 全部除以 split_ratio（把歷史接到新價位尺度），
    或等價地把 t 起點以後乘上（此實作採：調整 t 以前，保留近期報價尺度）。
    """
    o = open_.astype(float).copy()
    h = high.astype(float).copy()
    low_s = low.astype(float).copy()
    c = close.astype(float).copy()
    n = len(c)
    events: List[dict] = []
    split_cum = pd.Series(1.0, index=c.index, dtype=float)

    # 由舊到新掃描；每偵測到裂口就調整「該日以前」
    for i in range(1, n):
        prev_c = float(c.iloc[i - 1])
        cur_o = float(o.iloc[i])
        cur_c = float(c.iloc[i])
        if not (np.isfinite(prev_c) and prev_c > 0 and np.isfinite(cur_o) and cur_o > 0):
            continue
        ret_co = cur_c / prev_c - 1.0
        ret_oo = cur_o / prev_c - 1.0
        bound = _limit_bound(c.index[i])
        # 停牌後重掛：日曆間隔 > 4 個交易日（用索引位置差近似；若 DatetimeIndex 用營業日差）
        gap_days = 1
        if isinstance(c.index, pd.DatetimeIndex):
            gap_days = int((c.index[i] - c.index[i - 1]).days)
        reopening_jump = gap_days > 4 and abs(ret_oo) > 0.11
        illegal = abs(ret_co) > bound or abs(ret_oo) > bound or reopening_jump
        if not illegal:
            continue
        # 排除真漲跌停（開高低接近鎖死且幅度貼近法定）：仍可能是真實漲停，不修
        # 減資特徵：Open 相對昨收遠超界，且 High/Low 跨度相對 Open 正常
        if abs(ret_oo) <= bound and not reopening_jump:
            continue
        split_ratio = prev_c / cur_o
        if not np.isfinite(split_ratio) or split_ratio <= 0:
            continue
        # 調整 i 以前（不含 i）的價格到新尺度：old *= (1/split) wait
        # Close[t-1]/Open[t] = split；要讓調整後 Open'[t] ≈ Close'[t-1]
        # 若保留 t 以後不變：Close'[t-1] = Close[t-1] / split_ratio = Open[t]
        o.iloc[:i] = o.iloc[:i] / split_ratio
        h.iloc[:i] = h.iloc[:i] / split_ratio
        low_s.iloc[:i] = low_s.iloc[:i] / split_ratio
        c.iloc[:i] = c.iloc[:i] / split_ratio
        split_cum.iloc[:i] = split_cum.iloc[:i] / split_ratio
        events.append(
            {
                "i": i,
                "date": str(c.index[i]),
                "split_ratio": float(split_ratio),
                "ret_oo": float(ret_oo),
                "bound": float(bound),
                "reopening": bool(reopening_jump),
            }
        )
    return o, h, low_s, c, split_cum, events


def ratio_adjust_ohlc(df: pd.DataFrame, *, adj_close_col: Optional[str] = None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    # 重複交易日：留最後一筆，避免權益曲線被 dict 壓半
    if getattr(df.index, "has_duplicates", False) and bool(df.index.duplicated().any()):
        df = df[~df.index.duplicated(keep="last")].sort_index()
    cm = _colmap(df)
    need = ("open", "high", "low", "close", "volume")
    missing = [k for k in need if k not in cm]
    if missing:
        raise ValueError(f"缺少欄位: {missing}")

    out = pd.DataFrame(index=df.index.copy())
    o_raw = df[cm["open"]].astype(float).copy()
    h_raw = df[cm["high"]].astype(float).copy()
    l_raw = df[cm["low"]].astype(float).copy()
    c_raw = df[cm["close"]].astype(float).copy()
    v = df[cm["volume"]].astype(float).copy()
    out["Open_raw"], out["High_raw"], out["Low_raw"], out["Close_raw"] = o_raw, h_raw, l_raw, c_raw
    out["Volume"] = v

    # V7：先對 raw 做減資／面額裂口消毒
    o_s, h_s, l_s, c_s, split_cum, ca_events = corporate_action_sanitizer(o_raw, h_raw, l_raw, c_raw)
    out["corp_action_n"] = len(ca_events)
    out.attrs["corp_action_events"] = ca_events
    out["split_cum_factor"] = split_cum

    adj_key = _find_adj(df, cm, adj_close_col)

    if adj_key is not None:
        adj = df[adj_key].astype(float)
        # 對 adj 也跑 sanitizer（防 API 漏還原）
        _ao, _ah, _al, adj_s, _, adj_events = corporate_action_sanitizer(adj, adj, adj, adj)
        out.attrs["corp_action_events_adj"] = adj_events
        factor = np.where(
            (c_s > 0) & np.isfinite(c_s) & np.isfinite(adj_s),
            adj_s / c_s,
            1.0,
        )
        factor = pd.Series(factor, index=df.index, dtype=float).replace([np.inf, -np.inf], 1.0).fillna(1.0)
        out["Adj Close"] = adj_s
        out["adj_factor"] = factor
        out["ratio_adjusted"] = True
        adj_ret = adj_s.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        # 消毒後若仍有越界報酬，夾到法定界（最後防線）
        clipped = []
        for i, (ts, r) in enumerate(adj_ret.items()):
            b = _limit_bound(ts)
            if i == 0:
                clipped.append(0.0)
            elif abs(r) > b + 0.02:
                # 殘留異常：用 0 報酬接合（已在 sanitizer 處理；此為保底）
                clipped.append(0.0)
            else:
                clipped.append(float(r))
        adj_ret = pd.Series(clipped, index=adj_ret.index)
        cont_c = 100.0 * (1.0 + adj_ret).cumprod()
        scale = cont_c / c_s.replace(0, np.nan)
        scale = scale.replace([np.inf, -np.inf], np.nan).fillna(factor)
        cont_o = o_s * scale
        cont_h = h_s * scale
        cont_l = l_s * scale
    else:
        out["adj_factor"] = 1.0
        out["ratio_adjusted"] = False
        raw_ret = c_s.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        clipped = []
        for i, (ts, r) in enumerate(raw_ret.items()):
            b = _limit_bound(ts)
            if i == 0:
                clipped.append(0.0)
            elif abs(r) > b + 0.02:
                clipped.append(0.0)
            else:
                clipped.append(float(r))
        raw_ret = pd.Series(clipped, index=raw_ret.index)
        cont_c = 100.0 * (1.0 + raw_ret).cumprod()
        scale = cont_c / c_s.replace(0, np.nan)
        scale = scale.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        cont_o = o_s * scale
        cont_h = h_s * scale
        cont_l = l_s * scale

    out["Continuous_Open"] = cont_o
    out["Continuous_High"] = cont_h
    out["Continuous_Low"] = cont_l
    out["Continuous_Close"] = cont_c
    out["Open"], out["High"], out["Low"], out["Close"] = cont_o, cont_h, cont_l, cont_c

    # 透傳可選籌碼／產業／股數
    for opt in (
        "shares_outstanding",
        "shares",
        "issued_shares",
        "sector",
        "foreign_buy",
        "trust_buy",
        "margin_balance",
        "short_balance",
    ):
        if opt in cm:
            out[opt] = df[cm[opt]]
    # 常見欄名別名
    aliases = {
        "Foreign_Buy": "foreign_buy",
        "Trust_Buy": "trust_buy",
        "Margin_Balance": "margin_balance",
        "Short_Balance": "short_balance",
    }
    for src, dst in aliases.items():
        if src in df.columns and dst not in out.columns:
            out[dst] = df[src]

    out.attrs["phone_sync"] = PHONE_SYNC
    out.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
    out.attrs["preprocessor_version"] = "hsiao_v7"
    return out


def prepare_ohlcv(df: pd.DataFrame, *, adj_close_col: Optional[str] = None) -> pd.DataFrame:
    return ratio_adjust_ohlc(df, adj_close_col=adj_close_col)


__all__ = [
    "ratio_adjust_ohlc",
    "prepare_ohlcv",
    "corporate_action_sanitizer",
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
]
