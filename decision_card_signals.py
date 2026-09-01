"""高低決策卡欄位語意 — 海選／LINE 須跟這套一致，勿另寫平行公式。

對照來源：
- wayne_navigator.get_decision_card（獲利／預警／高低）
- profit_cell_style（獲利格：貼零、剛離零實綠底）
- scan_double_green_breakout（雙綠脫離掃描，已併入起漲概念）

使用者傳過的範本卡（南亞 8234 等）是驗收標準；細節殘差見 形態學/未完成對齊.md
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

# 起漲桶：卡片綠底雖在 >5% 時仍可能成立，但海選不收已噴段（使用者回饋 5%+ 不像剛起步）
LEAVE_ZERO_SCREEN_MAX_PCT = 5.0


def cal60_low_close_at(df, idx: int = -1, *, close_col: str = "close") -> float:
    """該日往前 60 個日曆日收盤最低（決策卡獲利欄、海選同一條）。"""
    dts = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    if len(dts) == 0 or not dts.notna().any():
        return float(df[close_col].iloc[idx] or 0)
    end = dts.iloc[idx]
    mask = (dts >= (end - pd.Timedelta(days=60))) & (dts <= end) & dts.notna()
    if not mask.any():
        return float(df[close_col].iloc[idx] or 0)
    lo = float(df.loc[mask, close_col].astype(float).min())
    return lo if lo > 0 else float(df[close_col].iloc[idx] or 0)


def profit_floor_at(df, idx: int = -1, *, close_col: str = "close") -> float:
    """獲利地板：max(60曆日收盤低, 20日收盤低)。整理期貼月低仍顯示 0.0%（2633 範本）。"""
    cal = cal60_low_close_at(df, idx, close_col=close_col)
    closes = df[close_col].astype(float)
    l20 = float(closes.rolling(20, min_periods=1).min().iloc[idx] or 0)
    if l20 <= 0:
        return cal
    return max(cal, l20)


def profit_pct_series(df, *, close_col: str = "close") -> pd.Series:
    """逐日獲利 %：相對 profit_floor_at（60曆日低與20日收盤低取高）。"""
    closes = df[close_col].astype(float)
    out = []
    for i in range(len(df)):
        c = float(closes.iloc[i])
        floor = profit_floor_at(df, i, close_col=close_col)
        if floor <= 0:
            floor = c or 1.0
        out.append(round((c - floor) / floor * 100.0, 1))
    return pd.Series(out, index=df.index)


def compute_card_temperature(
    close: float,
    high20: float,
    low20: float,
    bias_monthly: float,
    *,
    high60: float = 0.0,
    low60: float = 0.0,
) -> float:
    """溫度計：冷股可到個位數；大波動股仍可上 70°C+（對齊 CaryBot 範本尺度）。"""
    try:
        c, h20, l20 = float(close), float(high20), float(low20)
        bias = float(bias_monthly or 0)
        h60, l60 = float(high60 or h20), float(low60 or l20)
    except (TypeError, ValueError):
        return 0.0
    span = max(h20 - l20, c * 0.002 if c > 0 else 0.01)
    rf = max(0.0, min(1.0, (c - l20) / span))
    space60 = (h60 - l60) / l60 * 100.0 if l60 > 0 else (span / c * 100.0 if c > 0 else 10.0)
    if space60 < 8:
        t_min, t_span = 6.0, 4.5
    elif space60 < 16:
        t_min, t_span = 8.0, 22.0
    else:
        t_min, t_span = 12.0, 68.0
    t = t_min + t_span * rf + 0.35 * bias
    return round(max(0.0, min(99.9, t)), 1)


def card_regime_label(
    close: float,
    ma20: float,
    ma60: float,
    *,
    space_60: float = 0.0,
) -> str:
    """格局徽章：窄波動時多標整理格局，勿一站上月線就喊多頭。"""
    try:
        c, m20, m60 = float(close), float(ma20 or 0), float(ma60 or 0)
        sp = float(space_60 or 0)
    except (TypeError, ValueError):
        return "整理格局"
    if m20 > 0 and m60 > 0 and c >= m20 and m20 >= m60 and sp >= 16:
        return "多頭格局"
    return "整理格局"


def format_profit_pct(profit_pct: float) -> str:
    """與決策卡「獲利」欄相同：一位小數 + %。"""
    try:
        return f"{float(profit_pct):.1f}%"
    except (TypeError, ValueError):
        return "—"


def is_profit_display_zero(profit_pct: float) -> bool:
    """獲利欄顯示 0.0%（貼近 60 曆日低）。"""
    return format_profit_pct(profit_pct) == "0.0%"


def parse_profit_display(cell: str) -> Optional[float]:
    """從卡片「獲利」欄字串反推數值（OCR／人工校準用）。"""
    s = str(cell or "").strip().replace("％", "%")
    if not s or s in ("—", "-", "No"):
        return None
    s = s.rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


def profit_display_stepped_up(prev_profit_pct: float, today_profit_pct: float) -> bool:
    """肉眼讀表：今獲利顯示數字比昨高（一位小數）。"""
    try:
        return format_profit_pct(today_profit_pct) != format_profit_pct(prev_profit_pct) and float(
            today_profit_pct
        ) > float(prev_profit_pct)
    except (TypeError, ValueError):
        return False


def card_row_leave_zero(
    yest_profit_pct: float,
    today_profit_pct: float,
    *,
    yest_alert: str = "",
    today_alert: str = "",
) -> Tuple[bool, str]:
    """依你傳的範本卡「讀兩列」：實綠底 → 雙綠脫離 → 昨 0.0% 今跳升。"""
    if profit_left_zero_highlight(yest_profit_pct, today_profit_pct):
        return True, "獲利格實綠（剛離零）"
    if double_green_breakout(yest_profit_pct, yest_alert, today_profit_pct, today_alert):
        return True, "雙綠脫離"
    if is_profit_display_zero(yest_profit_pct) and profit_display_stepped_up(
        yest_profit_pct, today_profit_pct
    ):
        return True, "昨獲利 0.0%、今數字跳升"
    return False, "卡片兩列未達起漲獲利型態"


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
    low20: float = 0.0,
    bias_monthly: float,
    rsv: float | None = None,
) -> str:
    """預警欄：60低 / K20低 / K20高 / No（K20 用 RSV，不用單獨月乖離≥4%）。"""
    try:
        c = float(close)
        l60 = float(low60 or 0)
        h20 = float(high20 or 0)
        l20 = float(low20 or 0)
        bias = float(bias_monthly or 0)
        k = float(rsv) if rsv is not None else None
    except (TypeError, ValueError):
        return "No"
    if l60 > 0 and c <= l60 * 1.005:
        return "60低"
    if k is not None:
        if k <= 35.0 and (l20 > 0 and c <= l20 * 1.005 or bias < -0.5):
            return "K20低"
        if k >= 70.0 and h20 > 0 and c >= h20 * 0.99:
            return "K20高"
        return "No"
    if l20 > 0 and c <= l20 * 1.005:
        return "K20低"
    if bias < 0.0:
        return "K20低"
    if h20 > 0 and c >= h20 * 0.99:
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
    hit, reason = card_row_leave_zero(py, pt, yest_alert=yest_alert, today_alert=today_alert)
    if hit:
        return True, reason
    return False, "未達起漲獲利條件"


def card_alerts_for_df(df) -> Tuple[str, str]:
    """回傳 (昨預警, 今預警)，對齊決策卡預警欄。"""
    import pandas as pd

    close_s = df["close"].astype(float)
    if len(close_s) < 2:
        return "No", "No"
    low60 = close_s.rolling(60, min_periods=20).min()
    high20 = close_s.rolling(20, min_periods=5).max()
    low20 = close_s.rolling(20, min_periods=5).min()
    ma20 = close_s.rolling(20, min_periods=1).mean()
    bias = pd.Series(0.0, index=close_s.index)
    ok = ma20 > 0
    bias.loc[ok] = ((close_s.loc[ok] - ma20.loc[ok]) / ma20.loc[ok] * 100.0).round(1)
    span = (high20 - low20).clip(lower=close_s * 0.002)
    rsv = ((close_s - low20) / span * 100.0).clip(0, 100).round(1)

    def tag_at(i: int) -> str:
        return alert_tag(
            float(close_s.iloc[i]),
            low60=float(low60.iloc[i] or 0),
            high20=float(high20.iloc[i] or 0),
            low20=float(low20.iloc[i] or 0),
            bias_monthly=float(bias.iloc[i] if pd.notna(bias.iloc[i]) else 0),
            rsv=float(rsv.iloc[i]) if pd.notna(rsv.iloc[i]) else None,
        )

    return tag_at(-2), tag_at(-1)
