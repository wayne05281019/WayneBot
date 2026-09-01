"""高低決策卡欄位語意 — 海選／LINE 須跟這套一致，勿另寫平行公式。

對照來源：
- wayne_navigator.get_decision_card（獲利／預警／高低）
- profit_cell_style（獲利格：貼零、剛離零實綠底）
- scan_double_green_breakout（雙綠脫離掃描，已併入起漲概念）

使用者傳過的範本卡（南亞 8234 等）是驗收標準；細節殘差見 形態學/未完成對齊.md
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# 起漲桶：卡片綠底雖在 >5% 時仍可能成立，但海選不收已噴段（使用者回饋 5%+ 不像剛起步）
LEAVE_ZERO_SCREEN_MAX_PCT = 5.0


def format_profit_pct(profit_pct: float) -> str:
    """與決策卡「獲利」欄相同：一位小數 + %。"""
    try:
        return f"{float(profit_pct):.1f}%"
    except (TypeError, ValueError):
        return "—"


def is_profit_display_zero(profit_pct: float) -> bool:
    """獲利欄顯示 0.0%（貼近 60 曆日低）。"""
    return format_profit_pct(profit_pct) == "0.0%"


def profit_left_zero_highlight(prev_profit_pct: float, today_profit_pct: float) -> bool:
    """獲利格「剛離零」實綠底 — 與 profit_cell_style 同一條。

    昨 ≤0.05%（貼零）、今 >0.05%。上限不在此函式；海選另用 LEAVE_ZERO_SCREEN_MAX_PCT。
    """
    try:
        prev = float(prev_profit_pct)
        today = float(today_profit_pct)
    except (TypeError, ValueError):
        return False
    return prev <= 0.05 and today > 0.05


def alert_tag(
    close: float,
    *,
    low60: float,
    high20: float,
    bias_monthly: float,
) -> str:
    """預警欄：對齊 get_decision_card（60低 / K20低 / K20高 / No）。"""
    try:
        c = float(close)
        l60 = float(low60 or 0)
        h20 = float(high20 or 0)
        bias = float(bias_monthly or 0)
    except (TypeError, ValueError):
        return "No"
    if l60 > 0 and c <= l60 * 1.005:
        return "60低"
    if bias < 0.0:
        return "K20低"
    if h20 > 0 and (c >= h20 * 0.99 or bias >= 4.0):
        return "K20高"
    return "No"


def double_green_breakout(
    yest_profit_pct: float,
    yest_alert: str,
    today_profit_pct: float,
    today_alert: str,
) -> bool:
    """scan_double_green_breakout 同一套（雙綠脫離）。"""
    was_green = is_profit_display_zero(yest_profit_pct) or str(yest_alert or "") in ("60低", "K20低")
    breakout = (not is_profit_display_zero(today_profit_pct)) and str(today_alert or "") != "60低"
    return bool(was_green and breakout)


def leave_zero_screen_ok(
    yest_profit_pct: float,
    today_profit_pct: float,
    *,
    yest_alert: str = "",
    today_alert: str = "",
) -> Tuple[bool, str]:
    """起漲海選：以獲利格實綠為主，雙綠脫離為輔；今日獲利 ≤5%。"""
    try:
        pt = float(today_profit_pct)
        py = float(yest_profit_pct)
    except (TypeError, ValueError):
        return False, "獲利無法計算"
    if pt > LEAVE_ZERO_SCREEN_MAX_PCT:
        return False, f"今日獲利 {format_profit_pct(pt)} 已超過海選上限 {LEAVE_ZERO_SCREEN_MAX_PCT:.0f}%"
    if profit_left_zero_highlight(py, pt):
        return True, "獲利格剛離零（實綠底）"
    if double_green_breakout(py, yest_alert, pt, today_alert):
        return True, "雙綠脫離（昨貼零/低預警、今脫離）"
    return False, "未達起漲獲利條件"


def card_alerts_for_df(df) -> Tuple[str, str]:
    """回傳 (昨預警, 今預警)，對齊決策卡預警欄。"""
    import pandas as pd

    close_s = df["close"].astype(float)
    if len(close_s) < 2:
        return "No", "No"
    low60 = close_s.rolling(60, min_periods=20).min()
    high20 = close_s.rolling(20, min_periods=5).max()
    ma20 = close_s.rolling(20, min_periods=1).mean()
    bias = ((close_s - ma20) / ma20.replace(0, pd.NA) * 100.0).round(1)

    def tag_at(i: int) -> str:
        return alert_tag(
            float(close_s.iloc[i]),
            low60=float(low60.iloc[i] or 0),
            high20=float(high20.iloc[i] or 0),
            bias_monthly=float(bias.iloc[i] if pd.notna(bias.iloc[i]) else 0),
        )

    return tag_at(-2), tag_at(-1)
