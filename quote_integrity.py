# -*- coding: utf-8 -*-
"""日 K 寫庫前後的完整性：庫內只留官方收盤、可驗證的 OHLC，拒絕平盤假 K。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from trading_calendar import fuse_end_trading_date, is_trading_weekday, normalize_ymd

_EPS = 1e-6
# 平盤假 K（開高低收同價卻有大漲跌幅）＝2454 9/1 那類殘資料
_STUB_PCT_MIN = 3.0


def ohlc_consistent(open_p: float, high: float, low: float, close: float) -> bool:
    o, h, l, c = float(open_p or 0), float(high or 0), float(low or 0), float(close or 0)
    if min(o, h, l, c) <= 0:
        return False
    return h >= max(o, c) - _EPS and l <= min(o, c) + _EPS and h >= l - _EPS


def is_flat_ohlc(open_p: float, high: float, low: float, close: float) -> bool:
    o, h, l, c = float(open_p or 0), float(high or 0), float(low or 0), float(close or 0)
    return abs(h - l) <= _EPS and abs(o - c) <= _EPS and abs(h - c) <= _EPS


def is_suspect_stub_bar(
    open_p: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    pct_change: float = 0.0,
) -> bool:
    """有量卻開高低收同價，且漲跌幅偏大 → 不可寫庫／應刪除。"""
    if float(volume or 0) <= 0:
        return False
    if not is_flat_ohlc(open_p, high, low, close):
        return False
    return abs(float(pct_change or 0)) >= _STUB_PCT_MIN


def quote_tuple_trusted(
    open_p: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    pct_change: float = 0.0,
) -> bool:
    if not ohlc_consistent(open_p, high, low, close):
        return False
    if is_suspect_stub_bar(open_p, high, low, close, volume, pct_change):
        return False
    return True


def filter_trusted_quote_tuples(records: Sequence[Tuple]) -> Tuple[List[Tuple], int]:
    """data_fetcher executemany 前過濾。tuple 順序同 INSERT 欄位。"""
    kept: List[Tuple] = []
    dropped = 0
    for row in records:
        if len(row) < 12:
            dropped += 1
            continue
        # date, stock_id, ..., open idx7 high8 low9 close10 volume11 pct_change12
        o, h, l, c = row[7], row[8], row[9], row[10]
        vol, pct = row[11], row[12]
        if quote_tuple_trusted(o, h, l, c, vol, pct):
            kept.append(row)
        else:
            dropped += 1
    return kept, dropped


def scrub_untrusted_quotes(db_path: str, now=None) -> Dict[str, int]:
    """
    啟動／融合後清庫：
    - 刪除晚於 fuse 上限的日曆日（盤中不得有「今天收盤」）
    - 刪除週末殘列
    - 刪除上市或上櫃未齊的交易日
    - 刪除平盤假 K 列
    """
    if not db_path:
        return {}
    cap = fuse_end_trading_date(now)
    stats = {"after_cap": 0, "weekend": 0, "incomplete_day": 0, "stub_bar": 0}
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM daily_quotes
        WHERE replace(date,'-','') > ?
        """,
        (cap,),
    )
    stats["after_cap"] = cur.rowcount

    weekend_rows = cur.execute(
        """
        SELECT replace(date,'-','') AS d FROM daily_quotes
        GROUP BY replace(date,'-','')
        """
    ).fetchall()
    for (d,) in weekend_rows:
        if d and not is_trading_weekday(d):
            cur.execute("DELETE FROM daily_quotes WHERE replace(date,'-','')=?", (d,))
            stats["weekend"] += cur.rowcount

    try:
        from import_health import MIN_TW, MIN_TWO, sides_complete

        day_rows = cur.execute(
            """
            SELECT replace(date,'-','') AS d,
                   SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END)
            FROM daily_quotes
            GROUP BY replace(date,'-','')
            """
        ).fetchall()
        for d, tw, two in day_rows:
            if not d or d > cap:
                continue
            if not is_trading_weekday(d):
                continue
            if not sides_complete(int(tw or 0), int(two or 0), MIN_TW, MIN_TWO):
                cur.execute("DELETE FROM daily_quotes WHERE replace(date,'-','')=?", (d,))
                stats["incomplete_day"] += cur.rowcount
    except Exception:
        pass

    cur.execute(
        """
        DELETE FROM daily_quotes
        WHERE volume > 0
          AND abs(high - low) < 0.01
          AND abs(open - close) < 0.01
          AND abs(pct_change) >= ?
        """,
        (_STUB_PCT_MIN,),
    )
    stats["stub_bar"] = cur.rowcount

    conn.commit()
    conn.close()
    try:
        from import_health import clear_complete_date_cache

        clear_complete_date_cache(db_path)
    except Exception:
        pass
    return stats


def db_as_of_trading_date(db_path: str, now=None) -> Optional[str]:
    """決策卡／海選用的庫內基準日（最後一個完整收盤日）。"""
    try:
        from import_health import latest_complete_quote_date

        return latest_complete_quote_date(db_path, now=now)
    except Exception:
        return fuse_end_trading_date(now)
