# -*- coding: utf-8 -*-
"""高低決策卡欄位語意 — 海選／LINE 須跟這套一致，勿另寫平行公式。

對照來源：
- wayne_navigator.get_decision_card（獲利／預警／高低）
- profit_cell_style（獲利格：貼零、剛離零實綠底）
- scan_double_green_breakout（雙綠脫離掃描，已併入黃金買點／leave_zero）

使用者傳過的範本卡（南亞 8234 等）是驗收標準；細節殘差見 形態學/未完成對齊.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_TAIPEI = ZoneInfo("Asia/Taipei")

# 黃金買點桶（leave_zero）：卡片綠底雖在 >5% 時仍可能成立，但海選不收已噴段（使用者回饋 5%+ 不像剛起步）
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


def _ymd8(date_val) -> str:
    d = str(date_val or "").strip().replace("-", "").replace("/", "")
    return d[:8] if len(d) >= 8 and d[:8].isdigit() else ""


def format_ymd_slash(date_val) -> str:
    d = str(date_val or "").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}/{d[4:6]}/{d[6:8]}"
    if len(d) >= 10 and d[4] in "-/" and d[7] in "-/":
        return f"{d[0:4]}/{d[5:7]}/{d[8:10]}"
    return d


def format_ymd_slash_weekday(date_val) -> str:
    """20260910 → 2026/09/10（四）。圖戳日期一律帶星期。"""
    ymd = _ymd8(date_val)
    if ymd:
        try:
            from trading_calendar import format_trading_date_zh

            return format_trading_date_zh(ymd)
        except Exception:
            pass
    return format_ymd_slash(date_val)


def _parse_stamp_dt(generated_at: datetime | str | None) -> datetime:
    if isinstance(generated_at, datetime):
        return taipei_now(generated_at)
    raw = str(generated_at or "").strip()
    if raw:
        blob = raw.replace("T", " ").replace("／", "/").replace("－", "-")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                return taipei_now(datetime.strptime(blob[:19], fmt))
            except ValueError:
                continue
        parts = blob.split()
        if parts and ":" in parts[-1]:
            clock = parts[-1][:8]
            try:
                today = taipei_now().strftime("%Y-%m-%d")
                return taipei_now(datetime.strptime(f"{today} {clock}", "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                try:
                    today = taipei_now().strftime("%Y-%m-%d")
                    return taipei_now(datetime.strptime(f"{today} {clock[:5]}", "%Y-%m-%d %H:%M"))
                except ValueError:
                    pass
    return taipei_now()


def _in_cash_session(dt: datetime) -> bool:
    """上市櫃現股 09:00～13:30；13:30 當下已收盤。"""
    dt = taipei_now(dt)
    ymd = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_trading_weekday

        if not is_trading_weekday(ymd):
            return False
    except Exception:
        if dt.weekday() >= 5:
            return False
    hm = dt.hour * 60 + dt.minute
    return 9 * 60 <= hm < 13 * 60 + 30


def format_card_query_stamp(
    *,
    is_live: bool,
    latest_date="",
    generated_at: datetime | str | None = None,
) -> Tuple[str, str]:
    """高低卡／介紹圖右上角：日期帶星期，永遠配產出時刻。

    盤中查詢（有即時列、台北 09:00～未滿 13:30）寫當下 HH:MM。
    已過收盤、週末、或卡上是官方收盤列：一律「13:30收盤」，不要寫晚上查詢的時鐘。
    """
    dt = _parse_stamp_dt(generated_at)
    date_s = format_ymd_slash_weekday(latest_date)
    if not date_s:
        date_s = format_ymd_slash_weekday(dt.strftime("%Y%m%d"))
    if is_live and _in_cash_session(dt):
        return date_s, f"盤中 {dt.strftime('%H:%M')}"
    return date_s, "13:30收盤"


def format_produced_clock(*, generated_at: datetime | str | None = None) -> str:
    """這張圖產出時刻：盤中 HH:MM，否則 13:30收盤。"""
    _, clock = format_card_query_stamp(is_live=True, generated_at=generated_at)
    return clock


def _quote_datetimes(df) -> pd.Series:
    return pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")


def _cal60_lows_array(df, *, close_col: str = "close") -> np.ndarray:
    """逐日 60 曆日收盤低。只 parse 一次日期，結果須與逐列 cal60_low_close_at 相同。"""
    dts = _quote_datetimes(df)
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)
    n = len(closes)
    if n == 0:
        return np.zeros(0, dtype=float)
    d = dts.to_numpy(dtype="datetime64[ns]")
    window_lo = d - np.timedelta64(60, "D")
    dj = d[None, :]
    mask = (dj >= window_lo[:, None]) & (dj <= d[:, None])
    cj = np.where(np.isfinite(closes), closes, np.nan)[None, :]
    with np.errstate(all="ignore"):
        floors = np.nanmin(np.where(mask, cj, np.nan), axis=1)
    row_close = np.where(np.isfinite(closes), closes, 0.0)
    bad = ~np.isfinite(floors) | (floors <= 0)
    floors = np.where(bad, row_close, floors)
    return floors.astype(float)


def cal60_profit_bundle(df, *, close_col: str = "close"):
    """一次算出逐日 60 曆日低與獲利％，決策卡／海選共用，避免重算 n×n。"""
    floors = _cal60_lows_array(df, close_col=close_col)
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)
    c = np.where(np.isfinite(closes), closes, 0.0)
    floor = np.where(floors > 0, floors, np.where(c > 0, c, 1.0))
    floor = np.where(floor > 0, floor, 1.0)
    pct = np.round((c - floor) / floor * 100.0, 1)
    return floors, pd.Series(pct, index=df.index)


def cal60_low_close_at(df, idx: int = -1, *, close_col: str = "close") -> float:
    """該日往前 60 個日曆日收盤最低（決策卡獲利欄、海選同一條）。"""
    floors = _cal60_lows_array(df, close_col=close_col)
    if len(floors) == 0:
        return 0.0
    return float(floors[idx])


def profit_floor_at(
    df,
    idx: int = -1,
    *,
    close_col: str = "close",
    cal60_lows: np.ndarray | None = None,
) -> float:
    """獲利地板：max(60曆日收盤低, 20日收盤低)。整理期貼月低仍顯示 0.0%（2633 範本）。"""
    if cal60_lows is None:
        cal = cal60_low_close_at(df, idx, close_col=close_col)
    else:
        if len(cal60_lows) == 0:
            cal = 0.0
        else:
            cal = float(cal60_lows[idx])
    closes = df[close_col].astype(float)
    l20 = float(closes.rolling(20, min_periods=1).min().iloc[idx] or 0)
    if l20 <= 0:
        return cal
    return max(cal, l20)


def profit_pct_series(df, *, close_col: str = "close") -> pd.Series:
    """逐日獲利 %：相對 profit_floor_at（60曆日低與20日收盤低取高）。

    僅供需要「貼月低顯示 0%」的內部分析；決策卡／海選顯示與黃金買點（leave_zero）條件用
    ``profit_pct_cal60_series``（對齊 CaryBot）。
    """
    closes = pd.to_numeric(df[close_col], errors="coerce").to_numpy(dtype=float)
    cal = _cal60_lows_array(df, close_col=close_col)
    l20 = (
        pd.to_numeric(df[close_col], errors="coerce")
        .rolling(20, min_periods=1)
        .min()
        .to_numpy(dtype=float)
    )
    c = np.where(np.isfinite(closes), closes, 0.0)
    floor = np.where(l20 > 0, np.maximum(cal, l20), cal)
    floor = np.where(floor > 0, floor, np.where(c > 0, c, 1.0))
    floor = np.where(floor > 0, floor, 1.0)
    pct = np.round((c - floor) / floor * 100.0, 1)
    return pd.Series(pct, index=df.index)


def profit_pct_cal60_series(df, *, close_col: str = "close") -> pd.Series:
    """決策卡／海選獲利欄：只用 60 曆日收盤低（對齊 CaryBot；貼 20 日低不歸零）。"""
    _floors, pct = cal60_profit_bundle(df, close_col=close_col)
    return pct


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
    ma60: float = 0.0,
) -> float:
    """溫度計：冷股可到個位數；大波動股仍可上 70°C+（對齊 CaryBot 範本尺度）。

    決策卡 °C 對的是作者技術表 VAM 欄的數字，公式沒公開，這裡只用公開日 K
    做尺度近似，不抄 PWave／VAM／ATRB。

    跌破季線後在 60 日區間下半盤整、又不是 20 高／20 低／60 低：改走窄尺，
    避免舊高把溫度撐到 40°C+（中石化 8 月 VAM 0.5、長榮 7 月底 VAM 3.5）。
    貼 20 高且 60 日空間仍 ≥12% 時，窄尺至少拉到 40°C 一段（萬海 8/13 VAM 56.8）。
    20 高熱尺（8234 76.9、致伸 9/4 69.3）不變。貼 20 高但 VAM 只有 50～55
    （6547／台塑）對 8234／大成鋼 100 同一把尺對不上，不整表改熱尺、不抄 VAM。
    """
    try:
        c, h20, l20 = float(close), float(high20), float(low20)
        bias = float(bias_monthly or 0)
        h60, l60 = float(high60 or h20), float(low60 or l20)
        m60 = float(ma60 or 0)
    except (TypeError, ValueError):
        return 0.0
    span = max(h20 - l20, c * 0.002 if c > 0 else 0.01)
    p20 = max(0.0, min(1.0, (c - l20) / span))
    rf = p20 ** 0.94
    space60 = (h60 - l60) / l60 * 100.0 if l60 > 0 else (span / c * 100.0 if c > 0 else 10.0)
    p60 = (c - l60) / (h60 - l60) if (h60 - l60) > 1e-12 else p20
    space20 = (h20 - l20) / l20 * 100.0 if l20 > 0 else space60
    at_60_low = l60 > 0 and c <= l60 * 1.005
    at_20_high = h20 > 0 and c >= h20 * 0.998
    at_20_low = l20 > 0 and c <= l20 * 1.002
    below_ma60 = m60 > 0 and c < m60
    # 20 日還算寬、60 日舊高還掛著：才是「跌完在盤」不是 60 低附近的窄幅彈（致伸／華建）。
    dumped_chop = (
        below_ma60
        and (not at_60_low)
        and (not at_20_high)
        and (not at_20_low)
        and p60 < 0.42
        and space20 >= 11.0
        and (space60 - space20) >= 18.0
    )
    if dumped_chop:
        t_min, t_span, bias_k = 1.0, 14.0, 0.18
    elif space60 < 8:
        t_min, t_span, bias_k = 6.0, 4.5, 0.22
    elif space60 < 16:
        t_min, t_span, bias_k = 8.0, 22.0, 0.27
    elif space60 >= 24:
        t_min, t_span, bias_k = 10.0, 63.0, 0.26
    else:
        t_min, t_span, bias_k = 10.0, 68.0, 0.28
    # 貼 20 高但 60 日區間不算大：作者 VAM 仍可到 50～60（萬海 8/13），不要卡在 30°C。
    if at_20_high and space60 >= 12.0 and t_span < 40.0:
        t_span = 40.0
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


def profit_display_leave_zero_band(profit_pct: float) -> bool:
    """作者獲利格淺綠：顯示 0.1%～0.9%（零點幾也算脫離零，不看昨天是不是剛好 0.0%）。"""
    shown = format_profit_pct(profit_pct)
    return shown.startswith("0.") and shown != "0.0%"


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
    return False, "卡片兩列未達黃金買點獲利型態"


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
        return "今天別追高", "avoid"
    if at_high and p >= 15:
        return "漲多了，今天別追", "avoid"
    if p >= 40:
        return "漲多了，今天別追", "avoid"
    if at_60_low and -1.5 <= p <= 2.5 and b < -10:
        return "靠近低點，先看表", "watch"
    if at_60_low:
        return "在低點附近，先看表", "watch"
    if p > 20:
        return "離低點有一段了，先等", "wait"
    return "今天先看表，先等", "wait"


MONTHLY_STAGE_UP = "月K還在往上"
MONTHLY_STAGE_DOWN = "月K已走空"
MONTHLY_STAGE_SIDE = "月K在整理"
_MONTHLY_STAGE_SHORT = {
    "up": "還在往上",
    "down": "已走空",
    "side": "在整理",
}
# 本月收比上月低超過這比例，即使 12 月均線還在爬也不喊往上（均線會慢一拍）。
_MONTHLY_PULLBACK = 0.08


def monthly_last_closes(dates, closes) -> list[float]:
    """每個日曆月最後一根有效收盤。無量／停牌 0 元略過。"""
    last: dict[str, tuple[str, float]] = {}
    for raw_d, raw_c in zip(dates or [], closes or []):
        ds = str(raw_d or "").replace("-", "").replace("/", "")[:8]
        if len(ds) < 6:
            continue
        try:
            cv = float(raw_c)
        except (TypeError, ValueError):
            continue
        if cv != cv or cv <= 0:
            continue
        ym = ds[:6]
        prev = last.get(ym)
        if prev is None or ds >= prev[0]:
            last[ym] = (ds, cv)
    return [last[k][1] for k in sorted(last)]


def monthly_stage_from_ohlc(dates, closes) -> tuple[str, str, str]:
    """每月收盤相對近 12 個月均線：往上／走空／整理。不是買訊，不改海選。

    回傳 (kind, 全句, 短句)。資料不足三個月就空白，不上卡。
    """
    series = monthly_last_closes(dates, closes)
    if len(series) < 3:
        return "", "", ""
    cur = float(series[-1])
    prev = float(series[-2])
    kind = "side"
    if len(series) >= 13:
        arr = np.asarray(series, dtype=float)
        sma = pd.Series(arr).rolling(12, min_periods=12).mean().to_numpy()
        sma_now = float(sma[-1])
        sma_prev = float(sma[-2])
        if sma_now == sma_now and sma_prev == sma_prev and sma_now > 0:
            above = cur > sma_now
            rising = sma_now + 1e-12 >= sma_prev
            drop = (cur - prev) / prev if prev > 0 else 0.0
            if above and rising and drop >= -_MONTHLY_PULLBACK:
                kind = "up"
            elif (not above) and (not rising) and drop <= _MONTHLY_PULLBACK:
                kind = "down"
            else:
                kind = "side"
    else:
        older = float(series[-3])
        if cur > prev > older:
            kind = "up"
        elif cur < prev < older:
            kind = "down"
    label = {
        "up": MONTHLY_STAGE_UP,
        "down": MONTHLY_STAGE_DOWN,
        "side": MONTHLY_STAGE_SIDE,
    }[kind]
    return kind, label, _MONTHLY_STAGE_SHORT[kind]


def ma_matches_price(close, ma, *, max_ratio: float = 3.0) -> bool:
    """均線跟現價差超過這倍，多半是缺列／減資沒還原，不上卡、不進重點觀察。"""
    try:
        c = float(close)
        m = float(ma)
    except (TypeError, ValueError):
        return False
    if c <= 0 or m <= 0:
        return False
    return max(c, m) / min(c, m) <= float(max_ratio)


def close_gap_broken(prev, cur, *, max_move: float = 0.45) -> bool:
    """跟上根收盤差超過這成數，當缺列／分割，月乖離不能信。"""
    try:
        p = float(prev)
        c = float(cur)
    except (TypeError, ValueError):
        return False
    if p <= 0 or c <= 0:
        return False
    return abs(c / p - 1.0) > float(max_move)


def last_table_facts(card: Dict[str, Any] | None) -> Dict[str, Any]:
    """最新一列＋卡面數字，給態度第二行對表。沒有表就用卡上現成欄。"""
    card = card or {}
    row: Dict[str, Any] = {}
    try:
        from sell_discipline import latest_table_row

        row = latest_table_row(card)
    except Exception:
        row = {}
    if not row:
        tbl = card.get("table")
        if tbl is not None and hasattr(tbl, "iloc") and len(tbl):
            try:
                row = tbl.iloc[0].to_dict()
            except Exception:
                row = {}
        elif isinstance(tbl, (list, tuple)) and tbl and isinstance(tbl[0], dict):
            row = dict(tbl[0])

    def _num(*keys) -> float | None:
        for k in keys:
            for src in (card, row):
                if k not in src or src.get(k) in (None, ""):
                    continue
                try:
                    return float(src.get(k))
                except (TypeError, ValueError):
                    continue
        return None

    def _txt(*keys) -> str:
        for k in keys:
            for src in (card, row):
                v = src.get(k)
                if v not in (None, ""):
                    return str(v)
        return ""

    return {
        "gain": _num("gain_pct", "profit_pct", "profit"),
        "space": _num("space_20"),
        "bias": _num("bias_monthly", "bias"),
        "temp": _num("temp_num", "temp", "temperature"),
        "hl": _txt("高低", "hl"),
        "alert": _txt("預警", "alert"),
        "lift": _txt("升降"),
        "badges": [str(x) for x in (card.get("badges") or [])],
    }


def table_reads_as_low(card: Dict[str, Any] | None) -> bool:
    """表在畫長線低／近低時，減碼句會跟格子打架，不上那句。"""
    facts = last_table_facts(card)
    badges = facts["badges"]
    hl = facts["hl"]
    alert = facts["alert"]
    gain = facts["gain"]
    space = facts["space"]
    at_high = hl in {"20高", "10高"} or alert == "K20高"
    g = 99.0 if gain is None else gain
    if any(
        str(b).startswith(
            ("近480日低", "近240日低", "近120日低", "創480日新低", "創240日新低", "創120日新低")
        )
        for b in badges
    ):
        return (not at_high) and g < 15
    if space is not None and space < 8 and g < 8 and not at_high:
        return True
    if (alert in {"60低", "K20低"} or hl in {"60低", "20低", "10低"}) and g < 8:
        return True
    return False


def _look_table(on_list: bool) -> str:
    return "先看高低卡再決定。" if on_list else "看下面這張表再決定。"


def _fact_gain(g: float) -> str:
    return f"獲利 {format_profit_pct(g)}"


def _fact_bias(bias: float) -> str:
    return f"月乖離 {float(bias):+.1f}%"


def _fact_space(space: float) -> str:
    try:
        return f"空間 {int(round(float(space)))}%"
    except (TypeError, ValueError):
        return ""


def _fact_temp(temp) -> str:
    if temp is None:
        return ""
    try:
        return f"溫度 {float(temp):.0f}°C"
    except (TypeError, ValueError):
        return ""


def _paren(*bits: str) -> str:
    parts = [str(b).strip() for b in bits if b]
    return f"（{'、'.join(parts)}）" if parts else ""


def _stance_from_table(kind: str, card: Dict[str, Any] | None, *, on_list: bool = False) -> str:
    """依這張卡最新列數字組一句，對齊底色，不講月K。"""
    facts = last_table_facts(card)
    gain = facts["gain"]
    space = facts["space"]
    bias = facts["bias"]
    temp = facts["temp"]
    hl = facts["hl"]
    alert = facts["alert"]
    lift = facts["lift"]
    badges = facts["badges"]
    k = str(kind or "wait")
    g = 0.0 if gain is None else gain
    has_bias = bias is not None
    has_space = space is not None
    at_high = hl in {"20高", "10高"} or alert == "K20高"
    at_near_low = alert in {"60低", "K20低"} or hl in {"60低", "20低", "10低"}
    long_low = any(
        str(b).startswith(("近480日低", "近240日低", "近120日低", "創480日新低", "創240日新低", "創120日新低"))
        for b in badges
    )
    bear = any(any(x in b for x in ("空頭排列", "空頭整理", "弱勢破底")) for b in badges)
    weak_daily = bear or (has_bias and bias < -1) or at_near_low
    mark = hl if hl in {"20高", "10高", "20低", "10低", "60低"} else (alert if alert not in {"", "No", "—"} else "")
    heat = lift if lift and lift not in {"No", "—"} else ""
    tbit = _fact_temp(temp)
    gbit = _fact_gain(g)
    sbit = _fact_space(space) if has_space else ""
    bbit = _fact_bias(bias) if has_bias else ""

    if at_high:
        if has_space and space < 8:
            return f"表貼在這段小區間的高{_paren(mark, sbit, gbit)}。空間很小，先別追。"
        if k == "avoid" or g >= 40:
            return f"表貼在高檔{_paren(mark, gbit, tbit, heat)}。今天別追。"
        return f"表貼在高檔{_paren(mark, gbit, tbit)}。先別追，" + _look_table(on_list)

    if long_low and g < 15:
        if has_space and space < 8:
            return f"表還壓在長線低附近{_paren(gbit, sbit)}，這段空間很小。低點訊號不是買訊。先看、先別急著買。"
        return f"表還壓在長線低附近{_paren(gbit, mark)}。低點訊號不是買訊。先看、先別急著買。"

    if at_near_low and g < 8:
        if g < 1.0:
            return f"表壓在低附近{_paren(mark)}、獲利還沒離開0{_paren(gbit)}。低點訊號不是買訊。先看、先別急著買。"
        if has_bias and bias < -8:
            return f"表壓在低檔{_paren(mark, gbit)}、{bbit}偏負。低點訊號不是買訊。先看、先別急著買。"
        if bear or (has_bias and bias < -3):
            return f"日線偏空、表壓在低附近{_paren(mark, gbit, bbit)}。低點訊號不是買訊。先看、先別急著買。"
        return f"表還壓在低附近{_paren(mark, gbit)}。低點訊號不是買訊。先看、先別急著買。"

    if k == "avoid" or g >= 40:
        if has_bias and bias >= 8:
            return f"獲利已經拉很開{_paren(gbit)}，也高出月線一截{_paren(bbit, tbit)}。今天別追。"
        return f"獲利已經拉很開{_paren(gbit, tbit)}。今天別追。"

    if g > 20 and weak_daily:
        if has_bias and bias < -0.5:
            return f"離低點有一段了{_paren(gbit)}，但表還偏空、收在月線下{_paren(bbit)}。先等。"
        return f"離低點有一段了{_paren(gbit)}，但表還偏空。先等。"

    if k == "watch":
        if has_bias and bias < -8:
            return f"靠近低點{_paren(gbit)}、{bbit}偏負。可以放進觀察，先別急著買。"
        return f"靠近低點{_paren(gbit)}可以放進觀察，先別急著買。"

    if has_space and space < 8:
        if has_bias and abs(bias) < 1:
            return f"這段空間很小{_paren(sbit, gbit)}，貼著月線。先看表再決定。"
        return f"這段空間很小{_paren(sbit, gbit)}。先看表再決定。"

    if has_bias and abs(bias) < 0.5 and 8 <= g <= 25:
        return f"離低點有一段了{_paren(gbit)}，表貼著月線{_paren(bbit)}。先看再決定。"

    if bear or (has_bias and bias < -3):
        extra = _paren(gbit, bbit)
        return f"日線還偏空{extra}。今天先看表，先等。"

    if g > 20:
        return f"離低點有一段了{_paren(gbit, tbit)}。今天沒有急著買或賣，" + _look_table(on_list)

    extra = _paren(gbit, tbit, heat)
    if extra:
        if on_list:
            return f"今天沒有急著買或賣{extra}。紅箭頭不是買進訊號。"
        return f"今天沒有急著買或賣{extra}。看下面這張20日表再決定。紅箭頭不是買進訊號。"
    return _stance_kind_fallback(k, on_list=on_list)


def _stance_kind_fallback(kind: str, *, on_list: bool = False) -> str:
    k = str(kind or "wait")
    if k == "avoid":
        return "現在偏高或過熱，追進去容易挨打。不是叫你賣光，也不是下單指令。"
    if k == "watch":
        return "靠近低點可以放進觀察。低點訊號不是買訊，先別急著買。"
    if on_list:
        return "今天沒有急著買或賣。紅箭頭不是買進訊號。"
    return "今天沒有急著買或賣。看下面這張20日表再決定。紅箭頭不是買進訊號。"


def kotei_to_window_extreme(
    dates: Sequence[Any],
    values: Sequence[Any],
    period: int,
    *,
    kind: str = "low",
) -> Dict[str, Any]:
    """均線扣抵：n 日前那根是今天的扣抵值；窗內極值還要幾根交易日才被扣到。

    月線 n=20、季線 n=60。對齊 CaryBot：
    - 3630 2026-09-04「季線扣抵再過五天通過最高點」→ 季線距窗內高 = 5
    - 4739 2026-09-10「月線一個月／季線兩個月」→ 月線 19 日、季線 30 日（約 1／2 個月）
    不是買訊、不進海選。
    """
    empty: Dict[str, Any] = {"ok": False, "remain": None, "period": int(period or 0)}
    n = int(period or 0)
    if n < 5:
        return empty
    ds: List[str] = []
    vs: List[float] = []
    for raw_d, raw_v in zip(list(dates or []), list(values or [])):
        d = _ymd8(raw_d)
        try:
            v = float(raw_v)
        except (TypeError, ValueError):
            continue
        if len(d) != 8 or v != v or v <= 0:
            continue
        ds.append(d)
        vs.append(v)
    if len(ds) <= n:
        return empty
    t = len(ds) - 1
    kote_i = t - n
    if kote_i < 0:
        return empty
    win = range(kote_i + 1, t + 1)
    if kind == "high":
        ext_i = max(win, key=lambda i: vs[i])
    else:
        ext_i = min(win, key=lambda i: vs[i])
    remain = int(ext_i - kote_i)
    return {
        "ok": True,
        "period": n,
        "kind": "high" if kind == "high" else "low",
        "kotei_date": ds[kote_i],
        "kotei_value": vs[kote_i],
        "extreme_date": ds[ext_i],
        "extreme": vs[ext_i],
        "remain": remain,
    }


def kotei_wait_label(td: Any) -> str:
    """交易日 → 等多久。13 日以上用約 N 個月（20 日≈1 個月），對齊康普 19／30。"""
    try:
        n = int(td)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return "已通過"
    if n <= 5:
        return f"再{n}個交易日"
    months = int(round(n / 20.0))
    if n >= 13 and months >= 1:
        return f"{n}個交易日（約{months}個月）"
    weeks = max(1, int(round(n / 5.0)))
    return f"{n}個交易日（約{weeks}週）"


def format_kotei_note(
    *,
    close: float = 0.0,
    ma60: float = 0.0,
    hl: str = "",
    m20_low: Optional[int] = None,
    m60_low: Optional[int] = None,
    m60_high: Optional[int] = None,
) -> str:
    """高低卡說明用。過高點只在站上季線且即將扣到高點時寫；否則寫距低點要等多久。"""
    try:
        c = float(close or 0)
        q = float(ma60 or 0)
    except (TypeError, ValueError):
        c, q = 0.0, 0.0
    hi = str(hl or "")
    above_q = q > 0 and c >= q * 0.998
    near_high = hi in ("20高", "10高")
    try:
        rh = int(m60_high) if m60_high is not None else None
    except (TypeError, ValueError):
        rh = None
    if above_q and near_high and rh is not None and 0 < rh <= 15:
        return f"季線扣抵{kotei_wait_label(rh)}過高點。只是說明，進場仍看表。"
    bits: List[str] = []
    try:
        rq = int(m60_low) if m60_low is not None else None
    except (TypeError, ValueError):
        rq = None
    try:
        rm = int(m20_low) if m20_low is not None else None
    except (TypeError, ValueError):
        rm = None
    if rq is not None and rq > 0:
        bits.append("季線扣抵距低點還有" + kotei_wait_label(rq))
    if rm is not None and rm > 0:
        bits.append("月線還有" + kotei_wait_label(rm))
    if not bits:
        return ""
    return "；".join(bits) + "。這是等多久打底，不是買訊。"


def attach_kotei_note(
    card: Dict[str, Any],
    dates: Sequence[Any],
    closes: Sequence[Any],
    highs: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """寫進決策卡。不改黃金買點、不進海選。"""
    if not card or card.get("error"):
        return card
    m20 = kotei_to_window_extreme(dates, closes, 20, kind="low")
    m60l = kotei_to_window_extreme(dates, closes, 60, kind="low")
    m60h = kotei_to_window_extreme(dates, highs if highs is not None else closes, 60, kind="high")
    card["kotei_m20_low_days"] = m20.get("remain") if m20.get("ok") else None
    card["kotei_m60_low_days"] = m60l.get("remain") if m60l.get("ok") else None
    card["kotei_m60_high_days"] = m60h.get("remain") if m60h.get("ok") else None
    card["kotei_m20_low_date"] = m20.get("extreme_date") or ""
    card["kotei_m60_low_date"] = m60l.get("extreme_date") or ""
    card["kotei_m60_high_date"] = m60h.get("extreme_date") or ""
    last_hl = ""
    tbl = card.get("table")
    try:
        if tbl is not None and hasattr(tbl, "iloc") and len(tbl) and "高低" in tbl.columns:
            last_hl = str(tbl.iloc[0].get("高低") or "")
    except Exception:
        last_hl = str(card.get("hl") or "")
    card["kotei_note"] = format_kotei_note(
        close=float(card.get("close") or 0),
        ma60=float(card.get("ma60") or 0),
        hl=last_hl,
        m20_low=card.get("kotei_m20_low_days"),
        m60_low=card.get("kotei_m60_low_days"),
        m60_high=card.get("kotei_m60_high_days"),
    )
    return card


def stance_explain(
    kind: str,
    *,
    sell_note: str = "",
    card: Dict[str, Any] | None = None,
    monthly_stage: str = "",
    surface: str = "card",
) -> str:
    """今日態度後面那句：對這張20日表的數字和底色，不把月K階段寫進來。"""
    del monthly_stage  # 月K只掛徽章，避免跟表上「月乖離」撞名。
    on_list = str(surface or "card") == "list"
    note = str(sell_note or "").strip()
    if note and not table_reads_as_low(card):
        if "不是叫你買" not in note:
            note = note.rstrip("。") + "。不是叫你買。"
        body = note
    elif card:
        body = _stance_from_table(kind, card, on_list=on_list)
    else:
        body = _stance_kind_fallback(kind, on_list=on_list)
    kotei = str((card or {}).get("kotei_note") or "").strip()
    if kotei and not on_list and kotei not in body:
        body = (body.rstrip("。") + "。" if body else "") + kotei
    return body


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
        # 6770 9/4：RSV 低、月乖離負，但離 20 低還有一段；Cary 預警 No，不能只因乖離標 K20低。
        if k <= 35.0 and l20 > 0 and c <= l20 * 1.005:
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


def hi_lo_tag(close, h20, h10, h5, l20, l10, l5) -> str:
    """高低格：20 高／20 低允許 0.2% 貼齊；10／5 要收盤碰到當日極值。

    6526 9/9 收 643、5 日高 644：Cary 預警 No，不能因 0.998 誤標 5高。
    6770 9/7 收 72.9、10 日高 73.0：Cary 寫 5高，0.998 會誤標 10高。
    """
    try:
        c = float(close)
    except (TypeError, ValueError):
        return "No"

    def _px(v) -> float:
        try:
            x = float(v or 0)
            return x if x == x else 0.0
        except (TypeError, ValueError):
            return 0.0

    h20, h10, h5 = _px(h20), _px(h10), _px(h5)
    l20, l10, l5 = _px(l20), _px(l10), _px(l5)
    if h20 > 0 and c >= h20 * 0.998:
        return "20高"
    if h10 > 0 and c >= h10:
        return "10高"
    if h5 > 0 and c >= h5:
        return "5高"
    if l20 > 0 and c <= l20 * 1.002:
        return "20低"
    if l10 > 0 and c <= l10 * 1.002:
        return "10低"
    if l5 > 0 and c <= l5:
        return "5低"
    return "No"


def display_alert_cell(alert: str, hi_lo: str) -> str:
    """預警欄呈現：No 時仍露出高低；K20 與 20高／10低重疊時優先顯示高低（CaryBot 同欄）。

    5高／5低不蓋過反向 K20（6526 8/17 Cary 是 K20高，不是 5低）。
    """
    a = str(alert or "").strip()
    h = str(hi_lo or "").strip()
    if a == "60低":
        return a
    if h in ("20高", "10高", "20低", "10低"):
        if a in ("", "No", "—") or a.startswith("K20"):
            return h
    if h in ("5高", "5低"):
        if a in ("", "No", "—"):
            return h
        if a.startswith("K20"):
            a_high = "高" in a and "低" not in a
            h_high = "高" in h
            if a_high != h_high:
                return a
            return h
    if a and a not in ("No", "—"):
        return a
    return "No"


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
    """黃金買點海選（leave_zero）：以獲利格實綠為主，雙綠脫離為輔；今日獲利 ≤5%。"""
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
    return False, "未達黃金買點獲利條件"


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
