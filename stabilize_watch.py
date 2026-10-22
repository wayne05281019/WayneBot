# -*- coding: utf-8 -*-
"""查股「止穩／不再破底」觀察標（永遠不是買訊）。

規則 hold_l60（現況 v1，可重算、只用官方 OHLC）：
1. 近 LOOKBACK 根交易日內，找最近一次 60 根 wick 低「首觸」T0
   （當日低 ≤ 近 60 根最低 × 1.001，且前一根尚未觸；語意對齊導航 l60 首觸）。
2. 自 T0 起至少再走 HOLD_N 根交易日（T ≥ T0+HOLD_N）。
3. T0+1…T 期間最低價未跌破 T0 當日低（× BREAK_TOL，防浮點）。
4. 最新收盤 > T0 當日低（站在底上方）。
5. 停牌柱略過。

命中時在最新柱畫「止穩」。不准進 leave_zero／ma60_lower／paint_buy_entry_indices。
下一版靜默候選 hold_l60_tight＝HOLD_N=5（只落檔，不畫）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

# 現況畫圖規則
RULE_ID = "hold_l60"
LOOKBACK = 45
HOLD_N = 3
L60_TOUCH_MULT = 1.001
BREAK_TOL = 0.999  # low >= tagged_low * BREAK_TOL 視為未破底

# 下一版靜默候選（不畫、只對質）
RULE_NEXT_ID = "hold_l60_tight"
HOLD_N_NEXT = 5

# 視覺（與買訊藍▲紅框、純藍▲60低明顯不同）
STABILIZE_FACE = "#00695C"  # 深绿松石
STABILIZE_EDGE = "#26A69A"
STABILIZE_LABEL = "止穩"


def _halt_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or getattr(df, "empty", True):
        return pd.Series(dtype=bool)
    if "is_halt" in df.columns:
        return df["is_halt"].fillna(False).astype(bool)
    return pd.Series(False, index=df.index)


def _l60_first_touch_indices(df: pd.DataFrame) -> List[int]:
    """60 根 wick 低首觸 index（與導航 collect_nav_mark_events l60 同源語意）。"""
    if df is None or len(df) < 2:
        return []
    halt = _halt_mask(df)
    lo_s = df["low"].where(~halt)
    out: List[int] = []
    was_60l = False
    n = len(df)
    for i in range(n):
        if bool(halt.iloc[i]):
            continue
        try:
            lo = float(df["low"].iloc[i])
        except (TypeError, ValueError):
            was_60l = False
            continue
        if lo != lo:
            was_60l = False
            continue
        window = lo_s.iloc[max(0, i - 59) : i + 1]
        try:
            wick_l60 = float(window.min())
        except (TypeError, ValueError):
            was_60l = False
            continue
        if wick_l60 != wick_l60:
            was_60l = False
            continue
        is_60l = lo <= wick_l60 * L60_TOUCH_MULT
        if is_60l and not was_60l:
            out.append(int(i))
        was_60l = bool(is_60l)
    return out


def _held_after_touch(
    df: pd.DataFrame,
    touch_i: int,
    end_i: int,
    *,
    hold_n: int,
) -> bool:
    """T0 之後 hold_n 根起、到 end_i：未破 T0 低，且最新收 > T0 低。"""
    if df is None or touch_i < 0 or end_i <= touch_i:
        return False
    if end_i - touch_i < int(hold_n):
        return False
    halt = _halt_mask(df)
    try:
        tagged = float(df["low"].iloc[touch_i])
        last_close = float(df["close"].iloc[end_i])
    except (TypeError, ValueError):
        return False
    if tagged != tagged or tagged <= 0 or last_close != last_close:
        return False
    floor = tagged * BREAK_TOL
    for j in range(touch_i + 1, end_i + 1):
        if bool(halt.iloc[j]):
            continue
        try:
            lo = float(df["low"].iloc[j])
        except (TypeError, ValueError):
            return False
        if lo != lo or lo < floor:
            return False
    if last_close <= tagged:
        return False
    return True


def stabilize_detail(
    df: pd.DataFrame,
    *,
    hold_n: int = HOLD_N,
    lookback: int = LOOKBACK,
    at: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """若 end 柱命中止穩，回傳細節；否則 None。"""
    if df is None or getattr(df, "empty", True) or len(df) < 62:
        return None
    end = len(df) - 1 if at is None else int(at)
    if end < 61 or end >= len(df):
        return None
    touches = _l60_first_touch_indices(df.iloc[: end + 1])
    if not touches:
        return None
    start_scan = max(0, end - int(lookback))
    candidates = [i for i in touches if start_scan <= i < end]
    if not candidates:
        return None
    # 最近一次首觸
    t0 = int(candidates[-1])
    if not _held_after_touch(df, t0, end, hold_n=hold_n):
        return None
    try:
        tagged_low = float(df["low"].iloc[t0])
        date_t0 = str(df["date"].iloc[t0])
        date_end = str(df["date"].iloc[end])
    except Exception:
        return None
    return {
        "rule": RULE_ID if hold_n == HOLD_N else RULE_NEXT_ID,
        "touch_i": t0,
        "end_i": end,
        "tagged_low": tagged_low,
        "touch_date": date_t0,
        "as_of_date": date_end,
        "hold_n": int(hold_n),
        "bars_held": int(end - t0),
        "buy_signal": False,
    }


def stabilize_bar_indices(
    df: pd.DataFrame,
    *,
    hold_n: int = HOLD_N,
    lookback: int = LOOKBACK,
) -> List[int]:
    """回傳應畫「止穩」的柱 index（通常 0 或 1 個＝最新柱）。永遠不是買點 index。"""
    detail = stabilize_detail(df, hold_n=hold_n, lookback=lookback)
    if not detail:
        return []
    end_i = int(detail["end_i"])
    # §13 第3輪可換：A5 加 R3a 加權收跌日濾網（不改 hold_l60 公式本體）
    if hold_n == HOLD_N:
        try:
            from config import get_db_path
            from multi_track_env_gates import keep_a5_stabilize

            day = ""
            if df is not None and "date" in df.columns and 0 <= end_i < len(df):
                day = str(df["date"].iloc[end_i] or "").replace("-", "")[:8]
            if day and not keep_a5_stabilize(str(get_db_path()), day):
                return []
        except Exception:
            pass
    return [end_i]


def stabilize_fires_today(df: pd.DataFrame, *, hold_n: int = HOLD_N) -> bool:
    idxs = stabilize_bar_indices(df, hold_n=hold_n)
    return bool(idxs and int(idxs[-1]) == len(df) - 1)


def is_buy_entry_path(fn_name: str) -> bool:
    """測試用：止穩 paint 路徑名不准混進買訊函式名。"""
    buy_names = {
        "paint_buy_entry_indices",
        "paint_leave_zero_indices",
        "paint_ma60_lower_indices",
        "_nav_trade_marks",
        "_paint_nav_buy_arrows",
    }
    return str(fn_name or "") in buy_names


def frame_from_bars(bars: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    """結構圖 bars(list[dict]) → 規則用 DataFrame。"""
    rows = []
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        try:
            rows.append(
                {
                    "date": str(b.get("date") or "")[:8],
                    "open": float(b.get("open") or 0),
                    "high": float(b.get("high") or 0),
                    "low": float(b.get("low") or 0),
                    "close": float(b.get("close") or 0),
                    "volume": float(b.get("volume") or 0),
                    "is_halt": bool(b.get("is_halt") or False),
                }
            )
        except (TypeError, ValueError):
            continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
