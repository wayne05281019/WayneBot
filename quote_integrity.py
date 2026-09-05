# -*- coding: utf-8 -*-
"""日 K 寫庫前後的完整性：庫內只留官方收盤、可驗證的 OHLC。

開高低收同價＋大漲跌不是假 K：冷門／KY 漲停鎖死（安瑞-KY 9/2）官方就是這樣。
聯發科殘列應被官方 MI_INDEX 覆寫，不能用「平盤大漲跌」把真漲停刪掉。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from trading_calendar import fuse_end_trading_date, is_trading_weekday, normalize_ymd

_EPS = 1e-6

# data_fetcher INSERT tuple 欄位順序（與 daily_quotes 一致，勿手算 magic number）
_QI_DATE = 0
_QI_STOCK_ID = 1
_QI_STOCK_NAME = 2
_QI_MARKET = 3
_QI_OPEN = 4
_QI_HIGH = 5
_QI_LOW = 6
_QI_CLOSE = 7
_QI_VOLUME = 8
_QI_TURNOVER_K = 9
_QI_PCT_CHANGE = 10
_QI_AVG_PRICE = 11
_QI_MIN_FIELDS = 13  # 含法人三欄前的最少欄位數


def _fields_from_quote_tuple(row: Tuple) -> Tuple[float, float, float, float, float, float]:
    """從 executemany tuple 取出 OHLCV＋漲跌幅；索引錯誤會在測試階段被攔下。"""
    return (
        float(row[_QI_OPEN] or 0),
        float(row[_QI_HIGH] or 0),
        float(row[_QI_LOW] or 0),
        float(row[_QI_CLOSE] or 0),
        float(row[_QI_VOLUME] or 0),
        float(row[_QI_PCT_CHANGE] or 0),
    )


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
    """舊名保留。漲停／跌停鎖死與薄量單價成交都是官方列，不再當假 K。"""
    return False


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
    return True


def filter_trusted_quote_tuples(records: Sequence[Tuple]) -> Tuple[List[Tuple], int]:
    """data_fetcher executemany 前過濾。tuple 順序同 INSERT 欄位。"""
    kept: List[Tuple] = []
    dropped = 0
    for row in records:
        if len(row) < _QI_MIN_FIELDS:
            dropped += 1
            continue
        o, h, l, c, vol, pct = _fields_from_quote_tuple(row)
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
    stats = {"after_cap": 0, "weekend": 0, "incomplete_day": 0, "stub_bar": 0}  # stub_bar 固定 0，相容舊日誌
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

    stats["stub_bar"] = 0

    conn.commit()
    conn.close()
    try:
        from import_health import clear_complete_date_cache

        clear_complete_date_cache(db_path)
    except Exception:
        pass
    return stats


def audit_untrusted_quotes(db_path: str, now=None) -> Dict[str, Any]:
    """唯讀掃描：回報庫內可疑列數（不修改資料）。"""
    if not db_path:
        return {}
    cap = fuse_end_trading_date(now)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    after_cap = cur.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','') > ?",
        (cap,),
    ).fetchone()[0]
    weekend = 0
    for (d,) in cur.execute(
        "SELECT DISTINCT replace(date,'-','') FROM daily_quotes"
    ).fetchall():
        if d and not is_trading_weekday(d):
            weekend += cur.execute(
                "SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','')=?",
                (d,),
            ).fetchone()[0]
    stub_bar = 0
    bad_ohlc = cur.execute(
        """
        SELECT COUNT(*) FROM daily_quotes
        WHERE open > 0
          AND (high < max(open, close) - 0.01
               OR low > min(open, close) + 0.01
               OR high < low)
        """
    ).fetchone()[0]
    incomplete_day = 0
    try:
        from import_health import MIN_TW, MIN_TWO, sides_complete

        for d, tw, two in cur.execute(
            """
            SELECT replace(date,'-',''),
                   SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END)
            FROM daily_quotes
            GROUP BY replace(date,'-','')
            """
        ).fetchall():
            if not d or d > cap or not is_trading_weekday(d):
                continue
            if not sides_complete(int(tw or 0), int(two or 0), MIN_TW, MIN_TWO):
                incomplete_day += cur.execute(
                    "SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','')=?",
                    (d,),
                ).fetchone()[0]
    except Exception:
        pass
    conn.close()
    return {
        "fuse_cap": cap,
        "after_cap": int(after_cap or 0),
        "weekend": int(weekend or 0),
        "incomplete_day": int(incomplete_day or 0),
        "stub_bar": int(stub_bar or 0),
        "bad_ohlc": int(bad_ohlc or 0),
    }


def repair_pct_change_from_prior(db_path: str, tolerance: float = 0.2) -> int:
    """漲跌幅必須與前一根官方收盤價一致；偏差過大就依收盤重算。"""
    if not db_path:
        return 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    fixed = 0
    for (sid,) in cur.execute("SELECT DISTINCT stock_id FROM daily_quotes"):
        rows = cur.execute(
            """
            SELECT rowid, replace(date,'-','') AS d, close, pct_change
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY d
            """,
            (str(sid),),
        ).fetchall()
        prev_close: Optional[float] = None
        for rowid, _d, close, pct in rows:
            try:
                c = float(close or 0)
            except (TypeError, ValueError):
                c = 0.0
            if prev_close and prev_close > 0 and c > 0:
                expected = round((c - prev_close) / prev_close * 100.0, 2)
                try:
                    cur_pct = float(pct) if pct is not None else None
                except (TypeError, ValueError):
                    cur_pct = None
                if cur_pct is None or abs(cur_pct - expected) > tolerance:
                    cur.execute(
                        "UPDATE daily_quotes SET pct_change=? WHERE rowid=?",
                        (expected, rowid),
                    )
                    fixed += 1
            if c > 0:
                prev_close = c
    conn.commit()
    conn.close()
    if fixed:
        try:
            from import_health import clear_complete_date_cache

            clear_complete_date_cache(db_path)
        except Exception:
            pass
    return fixed


def ensure_quote_integrity(db_path: str, now=None) -> Dict[str, int]:
    """啟動／融合後強制清庫；有刪除才回傳非零統計。"""
    stats = scrub_untrusted_quotes(db_path, now=now)
    repaired = repair_pct_change_from_prior(db_path)
    if repaired:
        stats["pct_repaired"] = repaired
    return stats


def db_as_of_trading_date(db_path: str, now=None) -> Optional[str]:
    """決策卡／海選用的庫內基準日（最後一個完整收盤日）。"""
    try:
        from import_health import latest_complete_quote_date

        return latest_complete_quote_date(db_path, now=now)
    except Exception:
        return fuse_end_trading_date(now)
