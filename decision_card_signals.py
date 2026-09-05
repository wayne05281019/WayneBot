"""高低決策卡欄位語意 — 海選／LINE 須跟這套一致，勿另寫平行公式。

對照來源：
- wayne_navigator.get_decision_card（獲利／預警／高低）
- profit_cell_style（獲利格：貼零、剛離零實綠底）
- scan_double_green_breakout（雙綠脫離掃描，已併入起漲概念）

使用者傳過的範本卡（南亞 8234 等）是驗收標準；細節殘差見 形態學/未完成對齊.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

_TAIPEI = ZoneInfo("Asia/Taipei")

# 起漲桶：卡片綠底雖在 >5% 時仍可能成立，但海選不收已噴段（使用者回饋 5%+ 不像剛起步）
LEAVE_ZERO_SCREEN_MAX_PCT = 5.0
# 創中長線新高時，溫度計 ≥80 要少追（CaryBot：溫度是領先指標）。
TEMP_ATH_WATCH = 80.0
# K20高：收盤須貼近 20 日收盤高（CaryBot 9/2 穩懋 469.5 / 492 ≈ 95.4%）。
K20_HIGH_NEAR = 0.95


def taipei_now(now: datetime | None = None) -> datetime:
    """決策卡產出時鐘：台北時間。"""
    if now is None:
        now = datetime.now(_TAIPEI)
    if now.tzinfo is None:
        return now.replace(tzinfo=_TAIPEI)
    return now.astimezone(_TAIPEI)


def format_ymd_slash(date_val) -> str:
    d = str(date_val or "").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}/{d[4:6]}/{d[6:8]}"
    if len(d) >= 10 and d[4] in "-/" and d[7] in "-/":
        return f"{d[0:4]}/{d[5:7]}/{d[8:10]}"
    return d


def format_card_query_stamp(
    *,
    is_live: bool,
    latest_date="",
    generated_at: datetime | str | None = None,
) -> Tuple[str, str]:
    """高低卡右上角：庫已是官方收盤只寫資料日；當天即時列（盤中或 16:30 融合前）寫日期＋產出時分秒。

    作者公開貼文常是盤中截圖，價格會跟收盤不同。對圖時必須對產出時間，
    不能拿舊文或盤中價當收盤對答案。
    """
    date_s = format_ymd_slash(latest_date)
    if not is_live:
        return date_s, ""
    clock = ""
    if isinstance(generated_at, datetime):
        dt = taipei_now(generated_at)
        clock = dt.strftime("%H:%M:%S")
        if not date_s:
            date_s = dt.strftime("%Y/%m/%d")
    else:
        raw = str(generated_at or "").strip()
        if len(raw) >= 8 and ":" in raw:
            clock = raw[-8:] if raw[-8] != " " else raw[-8:].strip()
            if len(clock) == 8 and clock[2] == ":" and clock[5] == ":":
                pass
            else:
                parts = raw.replace("T", " ").split()
                clock = parts[-1][:8] if parts else ""
        if not date_s and len(raw) >= 10:
            date_s = format_ymd_slash(raw[:10].replace("-", ""))
    if clock and len(clock) == 5 and clock[2] == ":":
        clock = clock + ":00"
    if not clock:
        clock = taipei_now().strftime("%H:%M:%S")
        if not date_s:
            date_s = taipei_now().strftime("%Y/%m/%d")
    return date_s, f"產出 {clock}"


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
    """逐日獲利 %：相對 profit_floor_at（60曆日低與20日收盤低取高）。

    僅供需要「貼月低顯示 0%」的內部分析；決策卡／海選顯示與起漲條件用
    ``profit_pct_cal60_series``（對齊 CaryBot）。
    """
    closes = df[close_col].astype(float)
    out = []
    for i in range(len(df)):
        c = float(closes.iloc[i])
        floor = profit_floor_at(df, i, close_col=close_col)
        if floor <= 0:
            floor = c or 1.0
        out.append(round((c - floor) / floor * 100.0, 1))
    return pd.Series(out, index=df.index)


def profit_pct_cal60_series(df, *, close_col: str = "close") -> pd.Series:
    """決策卡／海選獲利欄：只用 60 曆日收盤低（對齊 CaryBot；貼 20 日低不歸零）。"""
    closes = df[close_col].astype(float)
    out = []
    for i in range(len(df)):
        c = float(closes.iloc[i])
        floor = cal60_low_close_at(df, i, close_col=close_col)
        if floor <= 0:
            floor = c or 1.0
        out.append(round((c - floor) / floor * 100.0, 1))
    return pd.Series(out, index=df.index)


def profit_pct_card_series(df, *, close_col: str = "close") -> pd.Series:
    """決策卡顯示別名：一律 60 曆日低（舊版貼 20 日低歸零已廢止，避免 2383 型誤顯 0%）。"""
    return profit_pct_cal60_series(df, close_col=close_col)


def finite_pct(value) -> Optional[float]:
    """官方漲跌幅：0 是平盤，不能當成缺值。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def prev_close_from_change_pct(close: float, change_pct: Optional[float]) -> float:
    """用官方漲跌幅反推參考價（昨收）。缺日／還原列不能拿上一根庫內收盤替代。"""
    c = float(close or 0)
    pct = finite_pct(change_pct)
    if c <= 0 or pct is None:
        return 0.0
    denom = 1.0 + pct / 100.0
    if denom <= 1e-12:
        return 0.0
    return round(c / denom, 4)


def resolve_daily_change_pct(
    close: float,
    *,
    stored_pct: Optional[float] = None,
    yesterday_close: float = 0.0,
    prev_close: float = 0.0,
    prefer_stored: bool = False,
) -> float:
    """日漲跌幅：盤中優先昨收→現價；收盤列優先官方 pct_change（含平盤 0）。

    冷門／KY／分割股日 K 常缺無量日或被還原，用上一根庫內收盤會跟證交所／櫃買對不上。
    """
    c = float(close or 0)
    y = float(yesterday_close or 0)
    if y > 0 and c > 0:
        return round((c - y) / y * 100.0, 2)
    stored = finite_pct(stored_pct)
    if prefer_stored and stored is not None:
        return round(stored, 2)
    p = float(prev_close or 0)
    if p > 0 and c > 0:
        return round((c - p) / p * 100.0, 2)
    return round(stored or 0.0, 2)


def calc_volume_rank(
    volumes,
    window: int = 120,
    *,
    closes=None,
    turnovers=None,
) -> int:
    """近 window 根量排名：1＝區間內最大。優先 turnover_k，其次收盤×量。"""
    if volumes is None:
        return 99
    if turnovers is not None and len(turnovers) == len(volumes):
        vals = [float(t or 0) for t in turnovers]
    else:
        vals = [float(v or 0) for v in volumes]
        if closes is not None and len(closes) == len(vals):
            vals = [float(c or 0) * float(v or 0) for c, v in zip(closes, vals)]
    if not vals:
        return 99
    last = vals[-1]
    start = max(0, len(vals) - window)
    sub = vals[start:]
    return int(sum(1 for x in sub if x > last) + 1)


def compute_ma60s(ma0: float, ma7: float, close: float) -> float:
    """MA60S：7 個交易日前後均線差。高價股用 %，中價股用元（達發型），超高價用 %。"""
    try:
        m0, m7, c = float(ma0 or 0), float(ma7 or 0), float(close or ma0 or 0)
    except (TypeError, ValueError):
        return 0.0
    if m7 <= 0:
        return 0.0
    delta = m0 - m7
    pct = delta / m7 * 100.0
    if c >= 500 or m0 >= 200:
        return round(pct, 1)
    if c >= 80:
        if abs(pct) >= 6.0:
            return round(pct, 1)
        return round(delta, 1)
    if abs(pct) >= 5.0:
        return round(pct, 1)
    return round(delta, 1)


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
    rf = rf ** 0.94
    space60 = (h60 - l60) / l60 * 100.0 if l60 > 0 else (span / c * 100.0 if c > 0 else 10.0)
    if space60 < 8:
        t_min, t_span, bias_k = 6.0, 4.5, 0.22
    elif space60 < 16:
        t_min, t_span, bias_k = 8.0, 22.0, 0.27
    elif space60 >= 24:
        t_min, t_span, bias_k = 10.0, 63.0, 0.26
    else:
        t_min, t_span, bias_k = 10.0, 68.0, 0.28
    t = t_min + t_span * rf + bias_k * bias
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


def card_daily_stance(
    *,
    profit_pct: float,
    alert: str = "",
    hl: str = "",
    temp: float = 0.0,
    trend_note: str = "",
    bias: float = 0.0,
    badges: list | None = None,
) -> Tuple[str, str]:
    """今日態度：只認高低卡表，不複製 Cary 紅箭頭當買訊、也不是下單指令。

    回傳 (文案, kind)，kind ∈ avoid / watch / wait。
    """
    badges = [str(x) for x in (badges or [])]
    alert = str(alert or "")
    hl = str(hl or "")
    note = str(trend_note or "")
    try:
        p = float(profit_pct or 0)
    except (TypeError, ValueError):
        p = 0.0
    try:
        t = float(temp or 0)
    except (TypeError, ValueError):
        t = 0.0
    try:
        b = float(bias or 0)
    except (TypeError, ValueError):
        b = 0.0
    at_high = hl in ("20高", "10高") or alert == "K20高"
    at_60_low = alert == "60低" or hl == "60低"
    if (
        any("溫度≥80" in x or "價溫背離" in x for x in badges)
        or (t >= TEMP_ATH_WATCH and at_high)
        or note == "價溫背離"
    ):
        return "今天不要追", "avoid"
    if at_high and p >= 15:
        return "高檔不宜追", "avoid"
    if p >= 40:
        return "高檔不宜追", "avoid"
    if at_60_low and -1.5 <= p <= 2.5 and b < -10:
        return "黃金買點觀察・按表", "watch"
    if at_60_low:
        return "低點觀察・按表", "watch"
    if p > 20:
        return "等待・獲利已離低點", "wait"
    return "等待・按表操課", "wait"


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
        if k >= 70.0 and h20 > 0 and c >= h20 * K20_HIGH_NEAR:
            return "K20高"
        return "No"
    if l20 > 0 and c <= l20 * 1.005:
        return "K20低"
    if bias < 0.0:
        return "K20低"
    if h20 > 0 and c >= h20 * K20_HIGH_NEAR:
        return "K20高"
    return "No"


def display_alert_cell(alert: str, hi_lo: str) -> str:
    """預警欄呈現：No 時仍露出高低；K20 與 20高／10低重疊時優先顯示高低（CaryBot 同欄）。"""
    a = str(alert or "").strip()
    h = str(hi_lo or "").strip()
    if a == "60低":
        return a
    if h in ("20高", "10高", "5高", "20低", "10低", "5低"):
        if a in ("", "No", "—") or a.startswith("K20"):
            return h
    if a and a not in ("No", "—"):
        return a
    return a or "—"


def candle_up_taiwan(close, prev_close=None, open_=None) -> bool:
    """台股紅漲綠跌：相對昨收。無昨收時退回收盤≥開盤。平盤視為紅。"""
    try:
        c = float(close)
    except (TypeError, ValueError):
        return True
    try:
        p = float(prev_close) if prev_close is not None else 0.0
    except (TypeError, ValueError):
        p = 0.0
    if p == p and p > 0:
        return c >= p
    try:
        o = float(open_) if open_ is not None else c
    except (TypeError, ValueError):
        o = c
    return c >= o


def volume_headline_rank(vol_rank_480=99, vol_rank_120=99, vol_rank_60=99) -> tuple[str, int]:
    """表頭量能：480 → 120 → 60，前 10 名才亮；否則退回 120 日量。"""
    try:
        r480, r120, r60 = int(vol_rank_480 or 99), int(vol_rank_120 or 99), int(vol_rank_60 or 99)
    except (TypeError, ValueError):
        return "120日量", 99
    if r480 <= 10:
        return "480日量", r480
    if r120 <= 10:
        return "120日量", r120
    if r60 <= 10:
        return "60日量", r60
    return "120日量", r120


def volume_rank_pair_text(vol_rank_480=99, vol_rank_120=99, vol_rank_60=99) -> str:
    """表頭短窗與 120 日並列，避免一張第 7、一張第 25 以為算錯。"""
    lab, n = volume_headline_rank(vol_rank_480, vol_rank_120, vol_rank_60)
    try:
        r120 = int(vol_rank_120 or 99)
    except (TypeError, ValueError):
        r120 = 99
    if lab == "120日量":
        return f"120日第 {n} 名"
    short = str(lab).replace("量", "")
    return f"{short}第{n} · 120日第{r120}"


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
