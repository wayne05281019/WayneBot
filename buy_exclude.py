# -*- coding: utf-8 -*-
"""買點排除層：勝率買點／剛脫離零共用。

壓力圖藍▲多數準、約四成是眼睛看得出的空頭噪音。
此層只做「不推薦」過濾，不准改黃金買點核心公式、不准把紅箭頭當買訊。
只認官方 OHLC／均線可重述的條件；缺真數＝不排除（不准假資料）。
興櫃無漲跌停 → 跌停條不套。時區與柱日對齊呼叫端 as_of。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# 排除 reason 鍵（靜默對質／落檔可記；對話少報）
REASON_LIMIT_DOWN_LOCK = "limit_down_lock"
REASON_LIMIT_DOWN_OPEN = "limit_down_open"
REASON_BEAR_MA = "bear_ma_stack"
REASON_BEAR_BREAK_LOW = "bear_break_lows"
REASON_SAME_BAR_SELL = "same_bar_sell"
REASON_SAME_BAR_WARN = "same_bar_warn"
REASON_THIN_VOL = "thin_vol"  # 量 < 近20日均量

# 靜默對質 kind（與勝率／剛脫離零分開記；不准混勝率）
KIND_EXCLUDE = "buy_exclude_v2"  # v1＋量縮；銅板～超高價＋興櫃對質過
KIND_EXCLUDE_NEXT = "buy_exclude_v3_candidate"  # 再生：收紅／收在振幅中上半等


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _bar_ohlc(df, i: int = -1) -> Optional[Tuple[float, float, float, float]]:
    if df is None or len(df) < 1:
        return None
    try:
        row = df.iloc[i]
        o = _f(row.get("open") if hasattr(row, "get") else row["open"])
        h = _f(row.get("high") if hasattr(row, "get") else row["high"])
        l = _f(row.get("low") if hasattr(row, "get") else row["low"])
        c = _f(row.get("close") if hasattr(row, "get") else row["close"])
    except Exception:
        return None
    if None in (o, h, l, c) or c <= 0:
        return None
    return o, h, l, c


def _prev_close(df, i: int = -1) -> Optional[float]:
    if df is None or len(df) < 2:
        return None
    idx = i if i >= 0 else len(df) + i
    if idx < 1:
        return None
    try:
        return _f(df["close"].iloc[idx - 1])
    except Exception:
        return None


def _is_emerging_frame(df, *, quote_source: str = "") -> bool:
    src = str(quote_source or "").strip()
    if src == "emerging_quotes":
        return True
    if df is None or len(df) < 1:
        return False
    try:
        if "quote_source" in df.columns:
            last = str(df["quote_source"].iloc[-1] or "")
            if last == "emerging_quotes":
                return True
    except Exception:
        pass
    return False


def _near_equal(a: float, b: float, *, tick: float) -> bool:
    return abs(float(a) - float(b)) <= max(float(tick), 1e-9) + 1e-9


def is_locked_limit_down(
    df,
    i: int = -1,
    *,
    emerging: bool = False,
) -> bool:
    """當日鎖跌停：開≈高≈低≈收且收在跌停價（幾乎無法買）。興櫃不套。"""
    if emerging:
        return False
    ohlc = _bar_ohlc(df, i)
    prev = _prev_close(df, i)
    if ohlc is None or prev is None or prev <= 0:
        return False
    o, h, l, c = ohlc
    try:
        from wayne_navigator import _limit_band_px, _tw_tick, quote_limit_side
    except Exception:
        return False
    if quote_limit_side(c, prev) != "down":
        return False
    limit_px = _limit_band_px(prev, -0.10)
    if limit_px is None:
        return False
    # 少數標的 ±20%（處置／重訊）；官方價貼板也認
    limit20 = _limit_band_px(prev, -0.20)
    tick = _tw_tick(limit_px)
    at_limit = _near_equal(c, limit_px, tick=tick) or (
        limit20 is not None and _near_equal(c, limit20, tick=_tw_tick(limit20))
    )
    if not at_limit:
        return False
    # 鎖死：開高低收同一價（允許一檔誤差）
    return (
        _near_equal(o, c, tick=tick)
        and _near_equal(h, c, tick=tick)
        and _near_equal(l, c, tick=tick)
    )


def is_open_locked_limit_down(
    df,
    i: int = -1,
    *,
    emerging: bool = False,
) -> bool:
    """開盤鎖跌停：開盤已在跌停價，且收仍貼跌停（當天幾乎掛不到）。興櫃不套。"""
    if emerging:
        return False
    ohlc = _bar_ohlc(df, i)
    prev = _prev_close(df, i)
    if ohlc is None or prev is None or prev <= 0:
        return False
    o, h, l, c = ohlc
    try:
        from wayne_navigator import _limit_band_px, _tw_tick, quote_limit_side
    except Exception:
        return False
    if quote_limit_side(c, prev) != "down" and quote_limit_side(o, prev) != "down":
        return False
    limit_px = _limit_band_px(prev, -0.10)
    if limit_px is None:
        return False
    tick = _tw_tick(limit_px)
    limit20 = _limit_band_px(prev, -0.20)
    open_at = _near_equal(o, limit_px, tick=tick) or (
        limit20 is not None and _near_equal(o, limit20, tick=_tw_tick(limit20))
    )
    close_at = _near_equal(c, limit_px, tick=tick) or (
        limit20 is not None and _near_equal(c, limit20, tick=_tw_tick(limit20))
    )
    # 開盤鎖＋收仍貼板（或當日從未離開板＝高也貼板）
    if not open_at:
        return False
    if close_at:
        return True
    return _near_equal(h, o, tick=tick) and quote_limit_side(o, prev) == "down"


def _ma_series(close_s, window: int):
    return close_s.rolling(window, min_periods=window).mean()


def is_bear_break_lows(df, i: int = -1, *, bars: int = 3) -> bool:
    """收季線下且近窗連破低，並且今日低跌破「此前約 20 日」低＝結構破底。

    只連降三根在銅板價噪音大；加上破近窗低才眼睛看得出「買點後仍破底」風險。
    柱不足／算不出＝不排除（不准假破底）。
    """
    n = int(bars or 3)
    need = max(60, 20 + n)
    if n < 2 or df is None or len(df) < need:
        return False
    idx = i if i >= 0 else len(df) + i
    if idx < max(59, 20 + n - 1):
        return False
    try:
        import pandas as pd

        close_s = pd.to_numeric(df["close"], errors="coerce")
        low_s = pd.to_numeric(df["low"], errors="coerce")
        c = _f(close_s.iloc[idx])
        ma60 = _f(_ma_series(close_s, 60).iloc[idx])
    except Exception:
        return False
    if c is None or ma60 is None or ma60 <= 0 or c >= ma60:
        return False
    try:
        lows = [_f(low_s.iloc[idx - k]) for k in range(n)]
        closes = [_f(close_s.iloc[idx - k]) for k in range(n)]
    except Exception:
        return False
    if any(x is None for x in lows + closes):
        return False
    # lows[0]=今日低 … 連破＝今日最低
    for a, b in zip(lows, lows[1:]):
        if not (a < b):
            return False
    for a, b in zip(closes, closes[1:]):
        if not (a < b):
            return False
    # 此前約 20 根低（不含近 n 根）
    try:
        prior = pd.to_numeric(low_s.iloc[idx - n - 19 : idx - n + 1], errors="coerce")
        if len(prior) < 10 or prior.isna().all():
            return False
        prior_lo = float(prior.min())
    except Exception:
        return False
    return float(lows[0]) < prior_lo


def is_bear_ma_stack(df, i: int = -1) -> bool:
    """明顯空頭排列：收在季線下且 ma5<ma10<ma20<ma60。柱不足＝不排除。

    現況排除層未採用（銅板／低價噪音大）；保留給下一版靜默對質候選。
    """
    if df is None or len(df) < 60:
        return False
    idx = i if i >= 0 else len(df) + i
    if idx < 59:
        return False
    try:
        import pandas as pd

        close_s = pd.to_numeric(df["close"], errors="coerce")
        c = _f(close_s.iloc[idx])
        ma5 = _f(_ma_series(close_s, 5).iloc[idx])
        ma10 = _f(_ma_series(close_s, 10).iloc[idx])
        ma20 = _f(_ma_series(close_s, 20).iloc[idx])
        ma60 = _f(_ma_series(close_s, 60).iloc[idx])
    except Exception:
        return False
    if None in (c, ma5, ma10, ma20, ma60) or ma60 <= 0:
        return False
    if c >= ma60:
        return False
    return bool(ma5 < ma10 < ma20 < ma60)


def is_same_bar_sell_or_warn(df, i: int = -1) -> Tuple[bool, str]:
    """同根已出賣點／警告 → 不當日買點。

    可安全量化：
    - df 已有「高低」「升降」→ 如何賣「直接減碼／準備減碼」
    OHLC 裸推 20高／K20高／少追帶：與剛離零（貼 60 低）常互斥，平價測試柱易誤殺；
    未過母體對質前不准硬編碼（停在筆記）。
    """
    if df is None or len(df) < 2:
        return False, ""
    idx = i if i >= 0 else len(df) + i
    if idx < 0:
        return False, ""
    try:
        if "高低" in df.columns and "升降" in df.columns:
            from sell_discipline import classify_how_to_sell

            hl = [str(x or "") for x in list(df["高低"].iloc[: idx + 1])]
            temp = [str(x or "") for x in list(df["升降"].iloc[: idx + 1])]
            flags = classify_how_to_sell(hl, temp)
            act = str(flags.get("sell_action") or "")
            if act in ("直接減碼", "準備減碼"):
                return True, REASON_SAME_BAR_SELL
    except Exception:
        pass
    return False, ""


def is_thin_volume(df, i: int = -1, *, mult: float = 0.5) -> bool:
    """量縮：當日量 < 近 20 日均量 × mult。柱不足／無真量＝不排除。

    官方 volume；興櫃／上市櫃同一套。mult 預設 0.5（兩萬以下全母體對質過關；
    1.0 保留率過低不採用）。
    """
    if df is None or "volume" not in getattr(df, "columns", []):
        return False
    idx = i if i >= 0 else len(df) + i
    if idx < 20:
        return False
    try:
        import pandas as pd

        vol = pd.to_numeric(df["volume"], errors="coerce")
        v = _f(vol.iloc[idx])
        base = _f(vol.iloc[idx - 20 : idx].mean())
    except Exception:
        return False
    if v is None or base is None or base <= 0:
        return False
    return bool(v < base * float(mult))


def buy_exclude_reasons(
    df,
    i: int = -1,
    *,
    emerging: bool = False,
    quote_source: str = "",
) -> List[str]:
    """回傳觸發的排除 reason 列表；空＝可推薦（仍須先過 leave_zero）。"""
    em = bool(emerging) or _is_emerging_frame(df, quote_source=quote_source)
    out: List[str] = []
    if is_locked_limit_down(df, i, emerging=em):
        out.append(REASON_LIMIT_DOWN_LOCK)
    elif is_open_locked_limit_down(df, i, emerging=em):
        out.append(REASON_LIMIT_DOWN_OPEN)
    # 結構破底（連破低＋破近20低）；空頭排列仍為下一軌候選
    if is_bear_break_lows(df, i):
        out.append(REASON_BEAR_BREAK_LOW)
    sell, why = is_same_bar_sell_or_warn(df, i)
    if sell and why:
        out.append(why)
    if is_thin_volume(df, i, mult=0.5):
        out.append(REASON_THIN_VOL)
    # 去重保序
    seen = set()
    uniq: List[str] = []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def should_exclude_buy(
    df,
    i: int = -1,
    *,
    emerging: bool = False,
    quote_source: str = "",
) -> bool:
    """True＝兩邊都不推薦（勝率買點／剛脫離零）。"""
    return bool(
        buy_exclude_reasons(
            df, i, emerging=emerging, quote_source=quote_source
        )
    )


def filter_leave_zero_rows(
    rows: Sequence[Dict[str, Any]],
    frames: Dict[str, Any],
    *,
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """對已過 leave_zero 的列套排除；缺框／缺柱＝保留（不准假排除）。"""
    out: List[Dict[str, Any]] = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid:
            continue
        df = (frames or {}).get(sid)
        if df is None or len(df) < 2:
            out.append(it)
            continue
        profit_df = df
        if db_path:
            try:
                from wayne_navigator import frame_for_cal60_profit

                profit_df = frame_for_cal60_profit(df, db_path)
            except Exception:
                profit_df = df
        src = str(it.get("quote_source") or "")
        if should_exclude_buy(profit_df, quote_source=src):
            continue
        out.append(it)
    return out


def sample_exclude_stats(
    frames: Dict[str, Any],
    *,
    leave_zero_sids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """母體／候選抽樣對質數字（對話少報；落檔用）。"""
    from decision_card_signals import leave_zero_from_quote_df

    pool = list(leave_zero_sids) if leave_zero_sids is not None else list(frames or {})
    n_lz = 0
    n_ex = 0
    by_reason: Dict[str, int] = {}
    for sid in pool:
        df = (frames or {}).get(sid)
        if df is None or len(df) < 2:
            continue
        try:
            hit = bool(leave_zero_from_quote_df(df))
        except Exception:
            hit = False
        if leave_zero_sids is None and not hit:
            continue
        if not hit and leave_zero_sids is not None:
            # 呼叫端已認定是 leave_zero 列
            pass
        n_lz += 1
        reasons = buy_exclude_reasons(df)
        if reasons:
            n_ex += 1
            for r in reasons:
                by_reason[r] = int(by_reason.get(r) or 0) + 1
    return {
        "kind": KIND_EXCLUDE,
        "n_leave_zero": n_lz,
        "n_excluded": n_ex,
        "exclude_rate": (round(n_ex / n_lz, 4) if n_lz else None),
        "by_reason": by_reason,
        "next_kind": KIND_EXCLUDE_NEXT,
    }
