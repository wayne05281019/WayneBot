# -*- coding: utf-8 -*-
"""台灣加權指數深度研究：持久化、regime、桶權重、勝率回測。"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})
_INDEX_YAHOO = "%5ETWII"
_INDEX_SYMBOL = "TWII"
_INDEX_TWSE_NAME = "發行量加權股價指數"
_INDEX_CLOSE_DIFF_ALERT_PCT = 0.1
_OFFICIAL_LOOKBACK_DAYS = 5

# 大盤 regime → 海選桶加減分（>1 較積極、<1 較保守）
REGIME_BUCKET_MULT: Dict[str, Dict[str, float]] = {
    "bull": {
        "leave_zero": 1.15,
        "golden_buy": 1.1,
        "revenue_cross": 1.1,
        "select_01": 1.12,
        "select_02": 1.05,
        "select_03": 1.0,
        "half_year_high": 1.08,
        "day_trade": 1.1,
        "overnight": 1.05,
    },
    "neutral": {k: 1.0 for k in (
        "leave_zero", "golden_buy", "revenue_cross", "select_01", "select_02",
        "select_03", "half_year_high", "day_trade", "overnight",
    )},
    "bear": {
        "leave_zero": 0.9,
        "golden_buy": 1.05,
        "revenue_cross": 0.85,
        "select_01": 0.72,
        "select_02": 0.75,
        "select_03": 0.8,
        "half_year_high": 0.78,
        "day_trade": 0.55,
        "overnight": 0.55,
    },
}

REGIME_BUCKET_CAP: Dict[str, Dict[str, int]] = {
    "bull": {"leave_zero": 9, "select_01": 9, "half_year_high": 9},
    "neutral": {},
    "bear": {
        "leave_zero": 6,
        "select_01": 5,
        "select_02": 5,
        "select_03": 5,
        "half_year_high": 5,
        "day_trade": 4,
        "overnight": 4,
    },
}

# L3 Regime+（P4）：趨勢／末端／衰竭／修復；海選權重 v2
REGIME_PLUS_LABELS: Dict[str, str] = {
    "trend_up": "多頭延伸",
    "trend_up_late": "多頭末端",
    "range": "箱型震盪",
    "trend_down": "空頭延伸",
    "down_exhaust": "空頭衰竭",
    "repair": "跌後修復",
}

REGIME_PLUS_BUCKET_MULT: Dict[str, Dict[str, float]] = {
    "trend_up": {
        **REGIME_BUCKET_MULT["bull"],
        "day_trade": 1.12,
        "overnight": 1.08,
    },
    "trend_up_late": {
        "leave_zero": 1.05,
        "golden_buy": 1.05,
        "revenue_cross": 0.95,
        "select_01": 0.92,
        "select_02": 0.9,
        "select_03": 0.92,
        "half_year_high": 0.85,
        "day_trade": 0.75,
        "overnight": 0.75,
    },
    "range": dict(REGIME_BUCKET_MULT["neutral"]),
    "trend_down": dict(REGIME_BUCKET_MULT["bear"]),
    "down_exhaust": {
        **REGIME_BUCKET_MULT["bear"],
        "golden_buy": 1.08,
        "leave_zero": 0.95,
        "day_trade": 0.5,
        "overnight": 0.5,
    },
    "repair": {
        "leave_zero": 1.08,
        "golden_buy": 1.12,
        "revenue_cross": 1.0,
        "select_01": 1.05,
        "select_02": 1.0,
        "select_03": 1.0,
        "half_year_high": 1.0,
        "day_trade": 0.85,
        "overnight": 0.85,
    },
}

REGIME_PLUS_BUCKET_CAP: Dict[str, Dict[str, int]] = {
    "trend_up": {"leave_zero": 9, "select_01": 9, "half_year_high": 9},
    "trend_up_late": {"select_01": 6, "half_year_high": 6, "day_trade": 5, "overnight": 5},
    "trend_down": dict(REGIME_BUCKET_CAP["bear"]),
    "down_exhaust": {"day_trade": 3, "overnight": 3, "select_01": 5},
    "repair": {},
    "range": {},
}

_REGIME_PLUS_CONFIRM_DAYS = 2

_BETA_LOOKBACK = 60
_BETA_DOWNWEIGHT_STATES = frozenset({"trend_down", "trend_up_late"})

def ensure_index_daily_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_daily (
                date TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT 'TWII',
                close REAL NOT NULL,
                volume REAL DEFAULT 0,
                pct_change REAL DEFAULT 0,
                ma20 REAL,
                ma60 REAL,
                regime TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (date, symbol)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_index_daily_sym ON index_daily(symbol, date);"
        )
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(index_daily)")}
        for name in ("open", "high", "low"):
            if name not in cols:
                conn.execute(f"ALTER TABLE index_daily ADD COLUMN {name} REAL")
        conn.commit()
    finally:
        conn.close()


def _clean_index_num(val: Any, *, is_float: bool = True) -> float:
    if val is None:
        return 0.0
    s = str(val).replace(",", "").replace("+", "").strip()
    if s in ("--", "-", "", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s) if is_float else float(int(float(s)))
    except (TypeError, ValueError):
        return 0.0


def _fetch_twse_index_close(date: str) -> Optional[Dict[str, Any]]:
    """證交所 MI_INDEX 加權指數收盤（單日 YYYYMMDD）。"""
    d = str(date or "").replace("-", "")[:8]
    if len(d) != 8:
        return None
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?date={d}&type=ALLBUT0999&response=json"
    )
    try:
        resp = _SESSION.get(url, timeout=40)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("TWSE MI_INDEX %s failed: %s", d, exc)
        return None
    stat = str(data.get("stat") or "")
    if stat.upper() != "OK" or "沒有符合" in stat or "很抱歉" in stat:
        return None
    for table in data.get("tables", []):
        title = str(table.get("title") or "")
        if "價格指數" not in title or "臺灣證券交易所" not in title:
            continue
        for row in table.get("data", []):
            if len(row) < 5 or str(row[0]).strip() != _INDEX_TWSE_NAME:
                continue
            close = _clean_index_num(row[1])
            if close <= 0:
                return None
            pct = _clean_index_num(row[4])
            sign_raw = str(row[2] or "") + str(row[3] or "")
            if "-" in sign_raw or "green" in sign_raw or "跌" in sign_raw:
                pct = -abs(pct)
            elif "+" in sign_raw or "red" in sign_raw or "漲" in sign_raw:
                pct = abs(pct)
            return {
                "date": d,
                "close": close,
                "pct_change": round(pct, 2),
                "source": "twse",
            }
    return None


def ensure_index_breadth_daily_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_breadth_daily (
                date TEXT NOT NULL PRIMARY KEY,
                up_count INTEGER NOT NULL DEFAULT 0,
                down_count INTEGER NOT NULL DEFAULT 0,
                limit_up INTEGER NOT NULL DEFAULT 0,
                limit_down INTEGER NOT NULL DEFAULT 0,
                flat_count INTEGER NOT NULL DEFAULT 0,
                up_tw INTEGER NOT NULL DEFAULT 0,
                down_tw INTEGER NOT NULL DEFAULT 0,
                up_two INTEGER NOT NULL DEFAULT 0,
                down_two INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'twse',
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _parse_count_cell(val: Any) -> Tuple[int, int]:
    """MI_INDEX 儲存格：'4,107(47)' → (4107, 47)；'845' → (845, 0)。"""
    s = str(val or "").replace(",", "").replace("+", "").strip()
    if not s or s in ("--", "-", "N/A"):
        return 0, 0
    m = re.match(r"(-?\d+(?:\.\d+)?)(?:\((\d+)\))?$", s)
    if not m:
        n = int(_clean_index_num(val, is_float=False))
        return n, 0
    return int(float(m.group(1))), int(m.group(2) or 0)


def _parse_breadth_row_cells(row: List[Any]) -> Tuple[int, int, int]:
    """解析 MI_INDEX 漲跌列：回傳 (上市, 上櫃, 合計或第三欄)。"""
    if not row or len(row) < 2:
        return 0, 0, 0
    tw, _ = _parse_count_cell(row[1])
    two, _ = _parse_count_cell(row[2]) if len(row) > 2 else (0, 0)
    if len(row) > 3:
        total, _ = _parse_count_cell(row[-1])
    else:
        total = tw + two
    if total <= 0 and (tw > 0 or two > 0):
        total = tw + two
    return tw, two, total


def _fetch_twse_index_breadth(date: str) -> Optional[Dict[str, Any]]:
    """證交所 MI_INDEX 漲跌證券數合計（單日 YYYYMMDD）。"""
    d = str(date or "").replace("-", "")[:8]
    if len(d) != 8:
        return None
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?date={d}&type=ALL&response=json"
    )
    try:
        resp = _SESSION.get(url, timeout=40)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("TWSE MI_INDEX breadth %s failed: %s", d, exc)
        return None
    stat = str(data.get("stat") or "")
    if stat.upper() != "OK" or "沒有符合" in stat or "很抱歉" in stat:
        return None
    for table in data.get("tables", []):
        title = str(table.get("title") or "")
        if "漲跌證券數合計" not in title:
            continue
        out: Dict[str, int] = {
            "up_tw": 0,
            "down_tw": 0,
            "up_two": 0,
            "down_two": 0,
            "limit_up": 0,
            "limit_down": 0,
            "flat_count": 0,
        }
        for row in table.get("data", []):
            label = str(row[0] if row else "").replace(" ", "")
            tw, two, total = _parse_breadth_row_cells(row)
            tw_lim = _parse_count_cell(row[1])[1] if len(row) > 1 else 0
            two_lim = _parse_count_cell(row[2])[1] if len(row) > 2 else 0
            # 新表：「上漲(漲停)」同一列，括號才是漲停家數。先認上漲／下跌。
            if "上漲" in label:
                out["up_tw"], out["up_two"] = tw, two
                if "漲停" in label:
                    out["limit_up"] = tw_lim + two_lim
            elif "下跌" in label:
                out["down_tw"], out["down_two"] = tw, two
                if "跌停" in label:
                    out["limit_down"] = tw_lim + two_lim
            elif "漲停" in label:
                out["limit_up"] = total or tw + two
            elif "跌停" in label:
                out["limit_down"] = total or tw + two
            elif "平盤" in label or "持平" in label:
                out["flat_count"] = total or tw + two
        up = out["up_tw"] + out["up_two"]
        down = out["down_tw"] + out["down_two"]
        if up + down <= 0:
            return None
        return {
            "date": d,
            "up_count": up,
            "down_count": down,
            "limit_up": out["limit_up"],
            "limit_down": out["limit_down"],
            "flat_count": out["flat_count"],
            "up_tw": out["up_tw"],
            "down_tw": out["down_tw"],
            "up_two": out["up_two"],
            "down_two": out["down_two"],
            "source": "twse",
        }
    return None


def load_index_breadth_daily(db_path: str, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """讀 index_breadth_daily；無該日列則 None。"""
    ensure_index_breadth_daily_table(db_path)
    ref = str(as_of or "").replace("-", "")[:8]
    conn = sqlite3.connect(db_path)
    try:
        if ref:
            row = conn.execute(
                """
                SELECT date, up_count, down_count, limit_up, limit_down, flat_count,
                       up_tw, down_tw, up_two, down_two, source
                FROM index_breadth_daily WHERE date = ?
                """,
                (ref,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT date, up_count, down_count, limit_up, limit_down, flat_count,
                       up_tw, down_tw, up_two, down_two, source
                FROM index_breadth_daily ORDER BY date DESC LIMIT 1
                """
            ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    up, down = int(row[1] or 0), int(row[2] or 0)
    if up + down <= 0:
        return None
    return {
        "date": str(row[0]),
        "up_count": up,
        "down_count": down,
        "limit_up": int(row[3] or 0),
        "limit_down": int(row[4] or 0),
        "flat_count": int(row[5] or 0),
        "up_tw": int(row[6] or 0),
        "down_tw": int(row[7] or 0),
        "up_two": int(row[8] or 0),
        "down_two": int(row[9] or 0),
        "up_ratio": round(up / (up + down), 4),
        "source": str(row[10] or "twse"),
    }


def sync_index_breadth_daily(db_path: str, dates: Optional[List[str]] = None) -> Dict[str, Any]:
    """盤後寫入 TWSE 漲跌家數；抓取失敗不寫、不覆蓋舊列。"""
    ensure_index_breadth_daily_table(db_path)
    if not dates:
        from trading_calendar import fuse_end_trading_date

        dates = [fuse_end_trading_date()]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    latest = ""
    conn = sqlite3.connect(db_path)
    try:
        for raw in dates:
            d = str(raw or "").replace("-", "")[:8]
            if len(d) != 8:
                continue
            row = _fetch_twse_index_breadth(d)
            if not row:
                continue
            conn.execute(
                """
                INSERT INTO index_breadth_daily(
                    date, up_count, down_count, limit_up, limit_down, flat_count,
                    up_tw, down_tw, up_two, down_two, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    up_count=excluded.up_count, down_count=excluded.down_count,
                    limit_up=excluded.limit_up, limit_down=excluded.limit_down,
                    flat_count=excluded.flat_count,
                    up_tw=excluded.up_tw, down_tw=excluded.down_tw,
                    up_two=excluded.up_two, down_two=excluded.down_two,
                    source=excluded.source, updated_at=excluded.updated_at
                """,
                (
                    row["date"],
                    row["up_count"],
                    row["down_count"],
                    row["limit_up"],
                    row["limit_down"],
                    row["flat_count"],
                    row["up_tw"],
                    row["down_tw"],
                    row["up_two"],
                    row["down_two"],
                    row["source"],
                    now,
                ),
            )
            written += 1
            latest = row["date"]
        conn.commit()
    finally:
        conn.close()
    return {"ok": written > 0, "rows": written, "latest": latest}


_FUTURES_SYMBOL = "TX"
_TAIFEX_OPENAPI = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
_TAIFEX_HIST_URL = "https://www.taifex.com.tw/cht/3/futDataDown"


def ensure_futures_daily_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_daily (
                date TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT 'TX',
                session TEXT NOT NULL DEFAULT 'regular',
                contract_month TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL NOT NULL,
                settlement REAL,
                volume INTEGER DEFAULT 0,
                open_interest INTEGER DEFAULT 0,
                pct_change REAL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'taifex',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (date, symbol, session)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_futures_daily_sym ON futures_daily(symbol, date);"
        )
        conn.commit()
    finally:
        conn.close()


def _taifex_num(val: Any, *, allow_dash: bool = True) -> Optional[float]:
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if allow_dash and s in ("-", "--", "", "NULL", "null", "None"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _pick_front_month_tx_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """同日多月份：成交量最大之近月（一般交易時段）。"""
    reg = [
        r
        for r in rows
        if str(r.get("Contract") or r.get("contract") or "").upper() == _FUTURES_SYMBOL
        and str(r.get("TradingSession") or r.get("session") or "一般") == "一般"
    ]
    if not reg:
        return None
    best = max(reg, key=lambda r: int(_taifex_num(r.get("Volume") or r.get("volume"), allow_dash=True) or 0))
    close = _taifex_num(best.get("Last") or best.get("close") or best.get("SettlementPrice"))
    if close is None or close <= 0:
        close = _taifex_num(best.get("SettlementPrice") or best.get("settlement"))
    if close is None or close <= 0:
        return None
    settle = _taifex_num(best.get("SettlementPrice") or best.get("settlement"))
    pct_raw = _taifex_num(best.get("%") or best.get("pct_change"))
    if pct_raw is None:
        chg = _taifex_num(best.get("Change") or best.get("pct_change"))
        if chg is not None and close:
            pct_raw = chg / close * 100.0
    return {
        "date": _norm_ymd(best.get("Date") or best.get("date")),
        "contract_month": str(best.get("ContractMonth(Week)") or best.get("contract_month") or "").strip(),
        "open": _taifex_num(best.get("Open") or best.get("open")) or close,
        "high": _taifex_num(best.get("High") or best.get("high")) or close,
        "low": _taifex_num(best.get("Low") or best.get("low")) or close,
        "close": close,
        "settlement": settle or close,
        "volume": int(_taifex_num(best.get("Volume") or best.get("volume"), allow_dash=True) or 0),
        "open_interest": int(_taifex_num(best.get("OpenInterest") or best.get("open_interest"), allow_dash=True) or 0),
        "pct_change": round(float(pct_raw or 0), 2),
        "source": "taifex",
    }


def _parse_taifex_history_csv(content: bytes) -> Dict[str, Dict[str, Any]]:
    import csv
    import io

    text = content.decode("big5", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in reader:
        raw_date = str(row.get("交易日期") or row.get("Date") or "").strip()
        d = _norm_ymd(raw_date.replace("/", "-"))
        if len(d) != 8:
            continue
        sess = str(row.get("交易時段") or row.get("TradingSession") or "一般").strip()
        if sess != "一般":
            continue
        contract = str(row.get("契約") or row.get("Contract") or "").strip().upper()
        if contract != _FUTURES_SYMBOL:
            continue
        by_date.setdefault(d, []).append(
            {
                "Date": d,
                "Contract": contract,
                "ContractMonth(Week)": str(row.get("到期月份(週別)") or "").strip(),
                "Open": row.get("開盤價"),
                "High": row.get("最高價"),
                "Low": row.get("最低價"),
                "Last": row.get("收盤價"),
                "Change": row.get("漲跌價"),
                "%": row.get("漲跌%"),
                "Volume": row.get("成交量"),
                "SettlementPrice": row.get("結算價"),
                "OpenInterest": row.get("未沖銷契約數"),
                "TradingSession": sess,
            }
        )
    out: Dict[str, Dict[str, Any]] = {}
    for d, rows in by_date.items():
        picked = _pick_front_month_tx_rows(rows)
        if picked:
            out[d] = picked
    return out


def _download_taifex_history_chunk(start: str, end: str) -> Dict[str, Dict[str, Any]]:
    """TAIFEX 歷史下載（單次約 31 日）。"""
    payload = {
        "down_type": "1",
        "commodity_id": _FUTURES_SYMBOL,
        "queryStartDate": start,
        "queryEndDate": end,
    }
    try:
        resp = _SESSION.post(_TAIFEX_HIST_URL, data=payload, timeout=60)
        resp.raise_for_status()
        if not resp.content or len(resp.content) < 40:
            return {}
        return _parse_taifex_history_csv(resp.content)
    except Exception as exc:
        logger.debug("TAIFEX history %s-%s failed: %s", start, end, exc)
        return {}


def _fetch_taifex_openapi_by_date(target: str) -> Optional[Dict[str, Any]]:
    target = _norm_ymd(target)
    try:
        resp = _SESSION.get(_TAIFEX_OPENAPI, timeout=40)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.debug("TAIFEX OpenAPI failed: %s", exc)
        return None
    day_rows = [r for r in rows if _norm_ymd(r.get("Date")) == target]
    if not day_rows:
        return None
    return _pick_front_month_tx_rows(day_rows)


def _fetch_taifex_tx_day(date: str) -> Optional[Dict[str, Any]]:
    d = _norm_ymd(date)
    if len(d) != 8:
        return None
    snap = _fetch_taifex_openapi_by_date(d)
    if snap:
        return snap
    from datetime import datetime, timedelta

    dt = datetime.strptime(d, "%Y%m%d")
    start = (dt - timedelta(days=5)).strftime("%Y/%m/%d")
    end = (dt + timedelta(days=5)).strftime("%Y/%m/%d")
    chunk = _download_taifex_history_chunk(start, end)
    return chunk.get(d)


def load_futures_daily(db_path: str, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    ensure_futures_daily_table(db_path)
    ref = _norm_ymd(as_of) if as_of else ""
    conn = sqlite3.connect(db_path)
    try:
        if ref:
            row = conn.execute(
                """
                SELECT date, contract_month, open, high, low, close, settlement,
                       volume, open_interest, pct_change, source
                FROM futures_daily
                WHERE symbol=? AND session='regular' AND date=?
                """,
                (_FUTURES_SYMBOL, ref),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT date, contract_month, open, high, low, close, settlement,
                       volume, open_interest, pct_change, source
                FROM futures_daily
                WHERE symbol=? AND session='regular'
                ORDER BY date DESC LIMIT 1
                """,
                (_FUTURES_SYMBOL,),
            ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "date": str(row[0]),
        "contract_month": str(row[1] or ""),
        "open": float(row[2] or 0),
        "high": float(row[3] or 0),
        "low": float(row[4] or 0),
        "close": float(row[5] or 0),
        "settlement": float(row[6] or row[5] or 0),
        "volume": int(row[7] or 0),
        "open_interest": int(row[8] or 0),
        "pct_change": float(row[9] or 0),
        "source": str(row[10] or "taifex"),
    }


def _nearest_futures_daily(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    ensure_futures_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT date FROM futures_daily
            WHERE symbol=? AND session='regular' AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (_FUTURES_SYMBOL, _norm_ymd(as_of)),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return load_futures_daily(db_path, str(row[0]))


def sync_futures_daily(
    db_path: str,
    dates: Optional[List[str]] = None,
    *,
    backfill_days: int = 0,
) -> Dict[str, Any]:
    """盤後寫入 TAIFEX 台指近月日 K；抓取失敗不覆蓋舊列。"""
    ensure_futures_daily_table(db_path)
    if not dates:
        from trading_calendar import fuse_end_trading_date

        dates = [fuse_end_trading_date()]
    want = {_norm_ymd(d) for d in dates if _norm_ymd(d)}
    if backfill_days <= 0:
        conn = sqlite3.connect(db_path)
        try:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM futures_daily WHERE symbol=?",
                (_FUTURES_SYMBOL,),
            ).fetchone()
        finally:
            conn.close()
        if int(cnt[0] or 0) < 10:
            backfill_days = 35
    if backfill_days > 0:
        from datetime import datetime, timedelta

        end_d = max(want) if want else _norm_ymd(dates[0])
        try:
            end_dt = datetime.strptime(end_d, "%Y%m%d")
        except ValueError:
            end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=backfill_days)
        cur = start_dt
        while cur <= end_dt:
            want.add(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    latest = ""
    conn = sqlite3.connect(db_path)
    try:
        for d in sorted(want):
            if len(d) != 8:
                continue
            row = _fetch_taifex_tx_day(d)
            if not row:
                continue
            conn.execute(
                """
                INSERT INTO futures_daily(
                    date, symbol, session, contract_month, open, high, low, close,
                    settlement, volume, open_interest, pct_change, source, updated_at
                ) VALUES (?, ?, 'regular', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, symbol, session) DO UPDATE SET
                    contract_month=excluded.contract_month,
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, settlement=excluded.settlement,
                    volume=excluded.volume, open_interest=excluded.open_interest,
                    pct_change=excluded.pct_change, source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    row["date"],
                    _FUTURES_SYMBOL,
                    row.get("contract_month") or "",
                    float(row.get("open") or row["close"]),
                    float(row.get("high") or row["close"]),
                    float(row.get("low") or row["close"]),
                    float(row["close"]),
                    float(row.get("settlement") or row["close"]),
                    int(row.get("volume") or 0),
                    int(row.get("open_interest") or 0),
                    float(row.get("pct_change") or 0),
                    row.get("source") or "taifex",
                    now,
                ),
            )
            written += 1
            latest = row["date"]
        conn.commit()
    finally:
        conn.close()
    return {"ok": written > 0, "rows": written, "latest": latest}


def compute_basis_pct(spot_close: float, futures_close: float) -> Optional[float]:
    if spot_close <= 0 or futures_close <= 0:
        return None
    return round((futures_close - spot_close) / spot_close * 100.0, 2)


def compute_futures_lead_stats(db_path: str, as_of: str, lookback: int = 20) -> Dict[str, Any]:
    """近 N 日：期貨／現貨誰先走弱（跌日裡期貨跌幅較大視為期貨領跌）。"""
    d = _norm_ymd(as_of)
    conn = sqlite3.connect(db_path)
    try:
        idx_rows = conn.execute(
            """
            SELECT date, close, pct_change FROM index_daily
            WHERE symbol=? AND date <= ? ORDER BY date DESC LIMIT ?
            """,
            (_INDEX_SYMBOL, d, lookback + 1),
        ).fetchall()
        fut_rows = conn.execute(
            """
            SELECT date, close, pct_change FROM futures_daily
            WHERE symbol=? AND session='regular' AND date <= ?
            ORDER BY date DESC LIMIT ?
            """,
            (_FUTURES_SYMBOL, d, lookback + 1),
        ).fetchall()
    finally:
        conn.close()
    idx = {str(r[0]): (float(r[1]), float(r[2] or 0)) for r in idx_rows}
    fut = {str(r[0]): (float(r[1]), float(r[2] or 0)) for r in fut_rows}
    common = sorted(set(idx) & set(fut), reverse=True)[:lookback]
    fut_lead = spot_lead = sync_days = 0
    for day in common:
        _, ip = idx[day]
        _, fp = fut[day]
        if ip < 0 and fp < 0:
            if fp < ip - 0.05:
                fut_lead += 1
            elif ip < fp - 0.05:
                spot_lead += 1
            else:
                sync_days += 1
    label = "同步"
    if fut_lead >= spot_lead + 2:
        label = "期貨領跌"
    elif spot_lead >= fut_lead + 2:
        label = "現貨領跌"
    return {
        "futures_lead_down": fut_lead,
        "spot_lead_down": spot_lead,
        "sync_down": sync_days,
        "label": label,
        "sample_n": len(common),
    }


def _format_futures_line(snap: Dict[str, Any]) -> Optional[str]:
    fut = snap.get("futures")
    if not fut:
        return None
    basis = snap.get("basis_pct")
    lead = snap.get("futures_lead") or {}
    parts = [f"近月 <b>{fut['close']:,.0f}</b>"]
    if basis is not None:
        parts.append(f"基差 {basis:+.2f}%")
    if int(fut.get("open_interest") or 0) > 0:
        parts.append(f"OI {int(fut['open_interest']):,}")
    line = "　".join(parts)
    f_date = str(snap.get("futures_as_of") or fut.get("date") or "")
    ref = str(snap.get("as_of") or "")
    if f_date and f_date != ref:
        line += f"（{f_date}）"
    if lead.get("sample_n", 0) >= 5:
        line += f"\n20日跌日 {lead.get('label', '同步')}（期{lead.get('futures_lead_down', 0)}/現{lead.get('spot_lead_down', 0)}）"
    return line


def _merge_index_closes(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """近 N 日優先官方收盤；與 Yahoo 差異 >0.1% 時告警。"""
    if df.empty:
        return df, []
    yahoo_by_date = {str(r["date"]): r for _, r in df.iterrows()}
    recent_dates = sorted(yahoo_by_date)[-_OFFICIAL_LOOKBACK_DAYS:]
    official_by_date: Dict[str, Dict[str, Any]] = {}
    alerts: List[str] = []
    for d in recent_dates:
        off = _fetch_twse_index_close(d)
        if not off:
            continue
        official_by_date[d] = off
        y_close = float(yahoo_by_date[d]["close"])
        o_close = float(off["close"])
        if o_close > 0:
            diff_pct = abs(y_close - o_close) / o_close * 100.0
            if diff_pct > _INDEX_CLOSE_DIFF_ALERT_PCT:
                msg = (
                    f"TWII {d}: Yahoo {y_close:.2f} vs TWSE {o_close:.2f} "
                    f"({diff_pct:.3f}%)"
                )
                alerts.append(msg)
                logger.warning("index_daily close mismatch: %s", msg)
    rows: List[Dict[str, Any]] = []
    for d in sorted(yahoo_by_date):
        base = yahoo_by_date[d]
        off = official_by_date.get(d)
        if off:
            rows.append(
                {
                    "date": d,
                    "open": float(base["open"] if "open" in base and pd.notna(base["open"]) else base["close"]),
                    "high": float(base["high"] if "high" in base and pd.notna(base["high"]) else max(float(off["close"]), float(base["close"]))),
                    "low": float(base["low"] if "low" in base and pd.notna(base["low"]) else min(float(off["close"]), float(base["close"]))),
                    "close": float(off["close"]),
                    "volume": float(base["volume"]),
                    "pct_change": float(off.get("pct_change", base["pct_change"])),
                    "source": "twse",
                }
            )
        else:
            rows.append(
                {
                    "date": d,
                    "open": float(base["open"] if "open" in base and pd.notna(base.get("open")) else base["close"]),
                    "high": float(base["high"] if "high" in base and pd.notna(base.get("high")) else base["close"]),
                    "low": float(base["low"] if "low" in base and pd.notna(base.get("low")) else base["close"]),
                    "close": float(base["close"]),
                    "volume": float(base["volume"]),
                    "pct_change": float(base["pct_change"]),
                    "source": "yahoo",
                }
            )
    return pd.DataFrame(rows), alerts


def _fetch_index_daily(range_: str = "2y") -> pd.DataFrame:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{_INDEX_YAHOO}"
        f"?interval=1d&range={range_}"
    )
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        return pd.DataFrame()
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    prev = None
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    vols = q.get("volume") or []
    for i, ts in enumerate(stamps):
        cl = closes[i] if i < len(closes) else None
        if cl is None:
            continue
        c = float(cl)
        pct = 0.0
        if prev and prev > 0:
            pct = (c - prev) / prev * 100.0
        op = opens[i] if i < len(opens) else None
        hi = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        vol = vols[i] if i < len(vols) else 0
        rows.append(
            {
                "date": pd.Timestamp(ts, unit="s", tz="UTC").tz_convert("Asia/Taipei").strftime("%Y%m%d"),
                "open": float(op if op is not None else c),
                "high": float(hi if hi is not None else c),
                "low": float(lo if lo is not None else c),
                "close": c,
                "volume": float(vol or 0),
                "pct_change": round(pct, 2),
            }
        )
        prev = c
    return pd.DataFrame(rows)


def sync_index_daily(db_path: str, range_: str = "2y") -> Dict[str, Any]:
    """盤後融合：官方 MI_INDEX 優先、Yahoo 補洞 → index_daily UPSERT。"""
    ensure_index_daily_table(db_path)
    yahoo_df = _fetch_index_daily(range_)
    if yahoo_df.empty:
        return {"ok": False, "rows": 0}
    df, alerts = _merge_index_closes(yahoo_df)
    if df.empty:
        return {"ok": False, "rows": 0, "alerts": alerts}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        for _, row in df.iterrows():
            closes = df.loc[: row.name, "close"].astype(float)
            ma20 = float(closes.tail(20).mean()) if len(closes) >= 5 else float(row["close"])
            ma60 = float(closes.tail(60).mean()) if len(closes) >= 20 else ma20
            snap = _regime_from_closes(closes)
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, pct_change, ma20, ma60, regime, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    open=COALESCE(NULLIF(excluded.open, 0), index_daily.open),
                    high=COALESCE(NULLIF(excluded.high, 0), index_daily.high),
                    low=COALESCE(NULLIF(excluded.low, 0), index_daily.low),
                    close=excluded.close,
                    volume=CASE WHEN excluded.volume > 0 THEN excluded.volume ELSE index_daily.volume END,
                    pct_change=excluded.pct_change,
                    ma20=excluded.ma20, ma60=excluded.ma60, regime=excluded.regime, updated_at=excluded.updated_at
                """,
                (
                    str(row["date"]),
                    _INDEX_SYMBOL,
                    float(row["open"] if pd.notna(row.get("open")) else row["close"]),
                    float(row["high"] if pd.notna(row.get("high")) else row["close"]),
                    float(row["low"] if pd.notna(row.get("low")) else row["close"]),
                    float(row["close"]),
                    float(row["volume"]),
                    float(row["pct_change"]),
                    ma20,
                    ma60,
                    snap.get("regime", "neutral"),
                    now,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    latest = str(df["date"].iloc[-1])
    out: Dict[str, Any] = {"ok": True, "rows": n, "latest": latest}
    if alerts:
        out["alerts"] = alerts
    last_src = str(df["source"].iloc[-1]) if "source" in df.columns else "yahoo"
    out["latest_source"] = last_src
    return out


def load_index_daily(db_path: str, as_of: Optional[str] = None, *, db_only: bool = False) -> pd.DataFrame:
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(index_daily)")}
        ohlc = ", open, high, low" if {"open", "high", "low"} <= cols else ""
        rows = conn.execute(
            f"""
            SELECT date, close, volume, pct_change, ma20, ma60, regime{ohlc}
            FROM index_daily WHERE symbol=? ORDER BY date
            """,
            (_INDEX_SYMBOL,),
        ).fetchall()
    finally:
        conn.close()
    if rows:
        names = ["date", "close", "volume", "pct_change", "ma20", "ma60", "regime"]
        if ohlc:
            names.extend(["open", "high", "low"])
        df = pd.DataFrame(rows, columns=names)
        if as_of:
            sub = df[df["date"] <= str(as_of)]
            if not sub.empty:
                return sub.reset_index(drop=True)
        return df
    if db_only:
        return pd.DataFrame()
    return _fetch_index_daily("1y")


def _norm_ymd(val: Optional[str]) -> str:
    return str(val or "").replace("-", "").strip()[:8]


def _max_index_daily_date(db_path: str) -> Optional[str]:
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(date) FROM index_daily WHERE symbol=?",
            (_INDEX_SYMBOL,),
        ).fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return _norm_ymd(row[0])
    return None


def resolve_market_as_of(db_path: str, hint: Optional[str] = None) -> str:
    """大盤／海選共用基準日：index_daily 最新完整日優先，再對齊 screen/import 基準日。"""
    hint_d = _norm_ymd(hint)
    max_idx = _max_index_daily_date(db_path)
    if max_idx:
        if hint_d and hint_d <= max_idx:
            return hint_d
        return max_idx
    for resolver in (
        lambda: __import__("trading_calendar", fromlist=["resolve_screen_as_of"]).resolve_screen_as_of(db_path),
        lambda: __import__("import_health", fromlist=["latest_complete_quote_date"]).latest_complete_quote_date(db_path),
    ):
        try:
            d = resolver()
            if d:
                return _norm_ymd(d)
        except Exception:
            pass
    from trading_calendar import fuse_end_trading_date

    return fuse_end_trading_date()


def _prior_quote_dates(db_path: str, as_of: str, limit: int = 12) -> List[str]:
    d = _norm_ymd(as_of)
    conn = sqlite3.connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_quotes'"
        ).fetchone()
        if not has:
            return []
        rows = conn.execute(
            """
            SELECT DISTINCT replace(date, '-', '') AS d
            FROM daily_quotes
            WHERE replace(date, '-', '') <= ?
            ORDER BY d DESC
            LIMIT ?
            """,
            (d, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_norm_ymd(r[0]) for r in rows if r and r[0]]


def _nearest_official_breadth(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    ensure_index_breadth_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT date FROM index_breadth_daily
            WHERE date <= ? ORDER BY date DESC LIMIT 1
            """,
            (_norm_ymd(as_of),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return load_index_breadth_daily(db_path, str(row[0]))


def _nearest_sector_flow(db_path: str, as_of: str) -> Optional[Tuple[str, float]]:
    conn = sqlite3.connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_sector_flow'"
        ).fetchone()
        if not has:
            return None
        row = conn.execute(
            """
            SELECT date, SUM(foreign_net + trust_net + dealer_net)
            FROM daily_sector_flow
            WHERE date <= ?
            GROUP BY date
            HAVING COUNT(*) > 0
            ORDER BY date DESC
            LIMIT 1
            """,
            (_norm_ymd(as_of),),
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    try:
        return _norm_ymd(row[0]), float(row[1] or 0)
    except (TypeError, ValueError):
        return None


def _resolve_breadth_for_date(db_path: str, as_of: str) -> Tuple[Dict[str, float], str]:
    """站上月線廣度：當日無列則往前找最近有官股日 K 的交易日。"""
    for d in _prior_quote_dates(db_path, as_of, 12):
        b = _breadth_from_db(db_path, d)
        if int(b.get("sample_n") or 0) > 0:
            return b, d
    return {"above_ma20_pct": 0.0, "sample_n": 0}, _norm_ymd(as_of)


def _regime_from_closes(
    closes: pd.Series,
    *,
    breadth_pct: float = 50.0,
    sector_flow: float = 0.0,
    official_up_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    if closes is None or len(closes) < 5:
        return {"regime": "unknown", "regime_label": "未知", "score": 0, "confidence": 50.0}
    c = float(closes.iloc[-1])
    ma20 = float(closes.tail(20).mean())
    ma60 = float(closes.tail(60).mean()) if len(closes) >= 60 else ma20
    chg5 = 0.0
    if len(closes) >= 6 and float(closes.iloc[-6]) > 0:
        chg5 = (c - float(closes.iloc[-6])) / float(closes.iloc[-6]) * 100.0
    slope20 = 0.0
    if len(closes) >= 25:
        m0 = float(closes.tail(20).mean())
        m1 = float(closes.iloc[-25:-5].mean())
        if m1 > 0:
            slope20 = (m0 - m1) / m1 * 100.0
    score = 0
    if c >= ma20:
        score += 1
    if c >= ma60:
        score += 1
    if ma20 >= ma60:
        score += 1
    if slope20 > 0:
        score += 1
    if breadth_pct >= 45:
        score += 1
    if official_up_ratio is not None:
        if official_up_ratio >= 0.55:
            score += 1
        elif official_up_ratio <= 0.35:
            score = max(0, score - 1)
    if sector_flow > 0:
        score += 1
    if score >= 5:
        regime, label = "bull", "多頭帶動"
    elif score <= 2:
        regime, label = "bear", "空方壓力"
    else:
        regime, label = "neutral", "區間震盪"
    confidence = round(min(100.0, max(15.0, 35.0 + score * 10.0 + chg5 * 0.8)), 1)
    return {
        "regime": regime,
        "regime_label": label,
        "score": score,
        "confidence": confidence,
        "close": round(c, 1),
        "ma20": round(ma20, 1),
        "ma60": round(ma60, 1),
        "chg5_pct": round(chg5, 2),
        "slope20_pct": round(slope20, 2),
    }


def _breadth_from_db(db_path: str, as_of: str) -> Dict[str, float]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT q.stock_id, q.close
            FROM daily_quotes q
            JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE q.date = ? AND u.is_active = 1 AND LENGTH(q.stock_id) = 4
            """,
            (as_of,),
        ).fetchall()
        hist = conn.execute(
            """
            SELECT stock_id, close FROM daily_quotes
            WHERE date <= ? AND stock_id IN (
                SELECT stock_id FROM stock_universe WHERE is_active = 1 AND LENGTH(stock_id) = 4
            )
            ORDER BY stock_id, date DESC
            """,
            (as_of,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"above_ma20_pct": 0.0, "sample_n": 0}
    by_sid: Dict[str, List[float]] = {}
    for sid, cl in hist:
        lst = by_sid.setdefault(str(sid), [])
        if len(lst) < 25:
            lst.append(float(cl or 0))
    above = total = 0
    for sid, cl in rows:
        seq = by_sid.get(str(sid), [])
        if len(seq) < 20:
            continue
        ma20 = sum(seq[:20]) / 20.0
        if ma20 <= 0:
            continue
        total += 1
        if float(cl) >= ma20:
            above += 1
    return {
        "above_ma20_pct": round((above / total * 100.0) if total else 0.0, 1),
        "sample_n": total,
    }


def _quote_up_down_counts(db_path: str, as_of: str) -> Dict[str, int]:
    """當日個股漲跌家數（STOCK/KY，不含 ETF）。官方「證券數」含權證會灌水。"""
    d = str(as_of or "").replace("-", "")[:8]
    if len(d) != 8:
        return {"up": 0, "down": 0, "flat": 0, "n": 0}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN q.pct_change > 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN q.pct_change < 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN q.pct_change = 0 OR q.pct_change IS NULL THEN 1 ELSE 0 END),
              COUNT(*)
            FROM daily_quotes q
            JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE q.date = ?
              AND LENGTH(q.stock_id) = 4
              AND COALESCE(u.is_active, 1) = 1
              AND UPPER(COALESCE(u.asset_type, 'STOCK')) IN ('STOCK', 'KY')
            """,
            (d,),
        ).fetchone()
    except sqlite3.Error:
        return {"up": 0, "down": 0, "flat": 0, "n": 0}
    finally:
        conn.close()
    if not row:
        return {"up": 0, "down": 0, "flat": 0, "n": 0}
    return {
        "up": int(row[0] or 0),
        "down": int(row[1] or 0),
        "flat": int(row[2] or 0),
        "n": int(row[3] or 0),
    }


def _usable_official_breadth(official: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """證交所新表含權證，上漲+下跌可逾萬；那種漲跌比不當 regime／下跌風險。"""
    if not official:
        return official
    up = int(official.get("up_count") or 0)
    down = int(official.get("down_count") or 0)
    if up + down <= 2500:
        return official
    out = dict(official)
    out["up_ratio"] = None
    return out


def _falling_risk_light(score: int) -> str:
    if score >= 60:
        return "🔴"
    if score >= 35:
        return "🟡"
    return "🟢"


def _risk_zone_label(zone: str) -> str:
    return {
        "elevated": "相對高檔",
        "compressed": "壓縮待變",
        "normal": "中性",
    }.get(str(zone or ""), "中性")


def _support_zone_label(zone: str) -> str:
    return {
        "building": "低檔築底觀察",
        "watch": "低檔留意",
        "none": "無",
    }.get(str(zone or ""), "無")


def compute_falling_risk(
    idx: pd.DataFrame,
    *,
    breadth_pct: float,
    official_breadth: Optional[Dict[str, Any]] = None,
    us_risk_off: bool = False,
) -> Dict[str, Any]:
    """下跌風險 0–100；僅用 index_daily 廣度與庫內美股快取，不抓新資料。"""
    score = 0
    hits: List[str] = []
    if idx is None or idx.empty:
        return {"falling_risk": 0, "falling_risk_hits": hits}
    closes = idx["close"].astype(float)
    vols = idx["volume"].astype(float) if "volume" in idx.columns else pd.Series([0.0] * len(idx))
    pcts = idx["pct_change"].astype(float) if "pct_change" in idx.columns else pd.Series([0.0] * len(idx))
    c = float(closes.iloc[-1])
    ma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else c
    if len(closes) >= 4 and c < ma20:
        recent = closes.tail(4)
        if all(float(x) < ma20 for x in recent):
            score += 25
            hits.append("跌破月線且3日未站回")
    if len(idx) >= 10:
        tail = idx.tail(10)
        up_vol = sum(float(r.get("volume") or 0) for _, r in tail.iterrows() if float(r.get("pct_change") or 0) > 0)
        dn_vol = sum(float(r.get("volume") or 0) for _, r in tail.iterrows() if float(r.get("pct_change") or 0) < 0)
        if dn_vol > up_vol > 0:
            score += 20
            hits.append("10日跌日量>漲日量")
    if breadth_pct > 0 and breadth_pct < 35:
        score += 15
        hits.append("站上月線廣度<35%")
    elif official_breadth:
        up_ratio = official_breadth.get("up_ratio")
        if up_ratio is not None and float(up_ratio) < 0.35:
            score += 15
            hits.append("官方漲跌比偏多跌")
    if len(pcts) >= 5:
        tail5 = pcts.tail(5)
        vol5 = vols.tail(5)
        avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else max(float(vol5.mean()), 1.0)
        for p, v in zip(tail5, vol5):
            if float(p) <= -1.5 and float(v) > avg_vol * 1.1:
                score += 15
                hits.append("近5日長黑放量")
                break
    if us_risk_off:
        score += 10
        hits.append("美股隔夜逆風")
    score = min(100, score)
    return {"falling_risk": score, "falling_risk_hits": hits}


def compute_risk_support_zones(
    idx: pd.DataFrame,
    *,
    breadth_pct: float,
    official_breadth: Optional[Dict[str, Any]] = None,
    prev_official: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """相對高/低檔區（純現貨 index_daily + 廣度）。"""
    if idx is None or idx.empty:
        return {"risk_zone": "normal", "support_zone": "none"}
    closes = idx["close"].astype(float)
    vols = idx["volume"].astype(float)
    c = float(closes.iloc[-1])
    win60 = closes.tail(60) if len(closes) >= 60 else closes
    lo60, hi60 = float(win60.min()), float(win60.max())
    span = hi60 - lo60
    pctile = (c - lo60) / span if span > 0 else 0.5
    high20 = float(closes.tail(20).max()) if len(closes) >= 20 else c
    dist_high20 = (high20 - c) / high20 * 100.0 if high20 > 0 else 99.0
    dist_low60 = (c - lo60) / lo60 * 100.0 if lo60 > 0 else 99.0
    elev_score = 0
    if pctile >= 0.85:
        elev_score += 1
    if dist_high20 < 1.5:
        elev_score += 1
    if len(vols) >= 120:
        if float(vols.tail(5).mean()) > float(vols.tail(120).mean()) * 1.3:
            if len(closes) >= 4:
                chg3 = [
                    float(closes.iloc[-i] - closes.iloc[-i - 1])
                    for i in range(1, min(4, len(closes)))
                ]
                if len(chg3) >= 2 and chg3[0] <= chg3[1]:
                    elev_score += 1
    if pctile >= 0.75 and breadth_pct > 0 and breadth_pct < 40:
        elev_score += 1
    if elev_score >= 3:
        risk_zone = "elevated"
    elif elev_score >= 2:
        risk_zone = "compressed"
    else:
        risk_zone = "normal"
    sup_score = 0
    if pctile <= 0.20:
        sup_score += 1
    if dist_low60 < 2.0:
        sup_score += 1
    if len(vols) >= 6 and float(vols.iloc[-1]) < float(vols.tail(5).mean()):
        sup_score += 1
    if official_breadth and prev_official:
        u0 = official_breadth.get("up_ratio")
        u1 = prev_official.get("up_ratio")
        if u0 is not None and u1 is not None and float(u1) < 0.35 and float(u0) > float(u1):
            sup_score += 1
    if sup_score >= 3:
        support_zone = "building"
    elif sup_score >= 2:
        support_zone = "watch"
    else:
        support_zone = "none"
    return {"risk_zone": risk_zone, "support_zone": support_zone}


def _classify_regime_plus_raw(
    *,
    regime: str,
    falling_risk: int,
    risk_zone: str,
    support_zone: str,
    closes: pd.Series,
    futures_lead_label: str = "同步",
) -> str:
    """單日 Regime+ 原始分類（未滯後）。"""
    reg = str(regime or "neutral")
    fr = int(falling_risk or 0)
    rz = str(risk_zone or "normal")
    sz = str(support_zone or "none")
    fl = str(futures_lead_label or "同步")
    c = float(closes.iloc[-1]) if closes is not None and len(closes) else 0.0
    ma20 = float(closes.tail(20).mean()) if closes is not None and len(closes) >= 20 else c
    was_below = False
    if closes is not None and len(closes) >= 4 and ma20 > 0:
        for i in range(2, min(6, len(closes))):
            if float(closes.iloc[-i]) < ma20:
                was_below = True
                break
    if c >= ma20 and was_below and fr < 60 and reg != "bear":
        return "repair"
    if sz in ("building", "watch") and (reg == "bear" or fr >= 35):
        return "down_exhaust"
    if reg == "bear" or fr >= 60 or (fl == "期貨領跌" and fr >= 35):
        return "trend_down"
    if reg == "bull" and rz == "elevated":
        return "trend_up_late"
    if reg == "bull" and fr < 35:
        return "trend_up"
    if reg == "bull" or (reg == "neutral" and fr >= 35):
        return "trend_up_late"
    if reg == "neutral":
        return "range"
    return "trend_down" if fr >= 35 else "range"


def _confirm_regime_plus(raw_hist: List[str], *, confirm_days: int = _REGIME_PLUS_CONFIRM_DAYS) -> Tuple[str, int, Optional[str]]:
    """滯後確認：連續 confirm_days 日同態才切換；否則維持前一穩定態。"""
    if not raw_hist:
        return "range", 0, None
    cur = raw_hist[-1]
    streak = 1
    for s in reversed(raw_hist[:-1]):
        if s == cur:
            streak += 1
        else:
            break
    if streak >= confirm_days:
        return cur, streak, None
    for i in range(len(raw_hist) - 2, -1, -1):
        state = raw_hist[i]
        sub = 1
        for j in range(i - 1, -1, -1):
            if raw_hist[j] == state:
                sub += 1
            else:
                break
        if sub >= confirm_days:
            return state, streak, cur if cur != state else None
    return cur, streak, None


def _regime_plus_raw_history(db_path: str, as_of: str, *, lookback: int = 8) -> List[str]:
    """近 lookback 個交易日逐日 raw Regime+（供滯後確認）。"""
    d = _norm_ymd(as_of)
    full_idx = load_index_daily(db_path, db_only=True)
    if full_idx.empty:
        return []
    dates = (
        full_idx.loc[full_idx["date"].astype(str) <= d, "date"]
        .astype(str)
        .tolist()[-lookback:]
    )
    raw_hist: List[str] = []
    last_day = dates[-1] if dates else ""
    for day in dates:
        idx = full_idx[full_idx["date"].astype(str) <= day].reset_index(drop=True)
        if idx.empty:
            continue
        official = _usable_official_breadth(
            load_index_breadth_daily(db_path, day) or _nearest_official_breadth(db_path, day)
        )
        if day == last_day:
            breadth, _ = _resolve_breadth_for_date(db_path, day)
        elif official:
            up = int(official.get("up_count") or 0)
            down = int(official.get("down_count") or 0)
            total = up + down
            up_ratio = float(official.get("up_ratio") or (up / total if total else 0.5))
            breadth = {"above_ma20_pct": round(up_ratio * 100.0, 1), "sample_n": 0}
        else:
            breadth = {"above_ma20_pct": 50.0, "sample_n": 0}
        prev_official = _load_prev_official_breadth(db_path, day)
        flow_net = _sector_flow_net(db_path, day)
        if flow_net is None:
            near = _nearest_sector_flow(db_path, day)
            flow_net = near[1] if near else 0.0
        core = _regime_from_closes(
            idx["close"].astype(float),
            breadth_pct=float(breadth.get("above_ma20_pct") or 0),
            sector_flow=float(flow_net or 0),
            official_up_ratio=(official.get("up_ratio") if official else None),
        )
        us_risk_off = False
        try:
            from us_overnight import load_us_overnight

            us = load_us_overnight(db_path, day)
            us_risk_off = str(us.get("regime") or "") == "risk_off"
        except Exception:
            us_risk_off = False
        fr = compute_falling_risk(
            idx,
            breadth_pct=float(breadth.get("above_ma20_pct") or 0),
            official_breadth=official,
            us_risk_off=us_risk_off,
        )
        zones = compute_risk_support_zones(
            idx,
            breadth_pct=float(breadth.get("above_ma20_pct") or 0),
            official_breadth=official,
            prev_official=prev_official,
        )
        lead = compute_futures_lead_stats(db_path, day) if day == last_day else {"label": "同步"}
        raw_hist.append(
            _classify_regime_plus_raw(
                regime=str(core.get("regime") or "neutral"),
                falling_risk=int(fr.get("falling_risk") or 0),
                risk_zone=str(zones.get("risk_zone") or "normal"),
                support_zone=str(zones.get("support_zone") or "none"),
                closes=idx["close"].astype(float),
                futures_lead_label=str(lead.get("label") or "同步"),
            )
        )
    return raw_hist


def compute_regime_plus(db_path: str, as_of: str, *, confirm_days: int = _REGIME_PLUS_CONFIRM_DAYS) -> Dict[str, Any]:
    raw_hist = _regime_plus_raw_history(db_path, as_of)
    confirmed, streak, pending = _confirm_regime_plus(raw_hist, confirm_days=confirm_days)
    return {
        "regime_plus": confirmed,
        "regime_plus_label": REGIME_PLUS_LABELS.get(confirmed, confirmed),
        "regime_plus_raw": raw_hist[-1] if raw_hist else confirmed,
        "regime_plus_streak": streak,
        "regime_plus_pending": pending,
    }


def regime_plus_bucket_mult(regime_plus: str) -> Dict[str, float]:
    return REGIME_PLUS_BUCKET_MULT.get(str(regime_plus or "range"), REGIME_PLUS_BUCKET_MULT["range"])


def regime_plus_screening_note(snap: Dict[str, Any]) -> str:
    if not snap.get("ok"):
        return ""
    rp = str(snap.get("regime_plus") or "range")
    label = snap.get("regime_plus_label") or REGIME_PLUS_LABELS.get(rp, rp)
    pending = snap.get("regime_plus_pending")
    tail = f"（觀察切換→{REGIME_PLUS_LABELS.get(str(pending), pending)}）" if pending else ""
    notes = {
        "trend_up": "多頭延伸：起漲與周帶量桶正常權重。",
        "trend_up_late": "多頭末端：少追、降 cap、多看獲利格。",
        "range": "箱型震盪：偏選股，不賭方向。",
        "trend_down": "空頭延伸：縮短線桶，佈局需極嚴。",
        "down_exhaust": "空頭衰竭：低檔觀察，黃金買點可略放但仍不賭刀。",
        "repair": "跌後修復：觀察 3 日站穩，不急追。",
    }
    return f"Regime+ <b>{label}</b>{tail}　{notes.get(rp, '')}"


def _load_prev_official_breadth(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    ensure_index_breadth_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT date FROM index_breadth_daily
            WHERE date < ? ORDER BY date DESC LIMIT 1
            """,
            (str(as_of),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return load_index_breadth_daily(db_path, str(row[0]))


def _sector_flow_sum(db_path: str, as_of: str) -> float:
    val = _sector_flow_net(db_path, as_of)
    return float(val) if val is not None else 0.0


def _sector_flow_net(db_path: str, as_of: str) -> Optional[float]:
    """當日產業法人合計；無表或無該日列則 None（避免把缺資料當 0）。"""
    conn = sqlite3.connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_sector_flow'"
        ).fetchone()
        if not has:
            return None
        cnt = conn.execute(
            "SELECT COUNT(*) FROM daily_sector_flow WHERE date = ?",
            (as_of,),
        ).fetchone()
        if not cnt or int(cnt[0] or 0) == 0:
            return None
        row = conn.execute(
            "SELECT SUM(foreign_net + trust_net + dealer_net) FROM daily_sector_flow WHERE date = ?",
            (as_of,),
        ).fetchone()
    finally:
        conn.close()
    try:
        return float(row[0] or 0)
    except (TypeError, ValueError):
        return None


def analyze_taiwan_market(
    db_path: str,
    as_of: Optional[str] = None,
    *,
    db_only: bool = False,
    page_light: bool = False,
) -> Dict[str, Any]:
    ref_date = resolve_market_as_of(db_path, as_of)
    idx = load_index_daily(db_path, ref_date or None, db_only=db_only)
    if idx.empty and db_only:
        idx = load_index_daily(db_path, None, db_only=True)
        ref_date = _max_index_daily_date(db_path) or ref_date
    if idx.empty and ref_date:
        for d in _prior_quote_dates(db_path, ref_date, 8):
            trial = load_index_daily(db_path, d, db_only=db_only)
            if not trial.empty:
                idx = trial
                ref_date = d
                break
    if idx.empty:
        return {"ok": False, "regime": "unknown", "brief": "加權指數讀取異常"}
    if not ref_date:
        ref_date = str(idx["date"].iloc[-1])
    breadth, breadth_date = _resolve_breadth_for_date(db_path, ref_date)
    official = _usable_official_breadth(
        load_index_breadth_daily(db_path, ref_date) or _nearest_official_breadth(db_path, ref_date)
    )
    flow_net = _sector_flow_net(db_path, ref_date)
    flow_date = ref_date
    if flow_net is None:
        near = _nearest_sector_flow(db_path, ref_date)
        if near:
            flow_date, flow_net = near
    flow = float(flow_net) if flow_net is not None else 0.0
    core = _regime_from_closes(
        idx["close"].astype(float),
        breadth_pct=breadth.get("above_ma20_pct", 0),
        sector_flow=flow,
        official_up_ratio=(official.get("up_ratio") if official else None),
    )
    us_risk_off = False
    try:
        from us_overnight import load_us_overnight

        us = load_us_overnight(db_path, ref_date)
        us_risk_off = str(us.get("regime") or "") == "risk_off"
    except Exception:
        pass
    prev_official = _load_prev_official_breadth(db_path, ref_date)
    fr = compute_falling_risk(
        idx,
        breadth_pct=float(breadth.get("above_ma20_pct") or 0),
        official_breadth=official,
        us_risk_off=us_risk_off,
    )
    zones = compute_risk_support_zones(
        idx,
        breadth_pct=float(breadth.get("above_ma20_pct") or 0),
        official_breadth=official,
        prev_official=prev_official,
    )
    futures = load_futures_daily(db_path, ref_date) or _nearest_futures_daily(db_path, ref_date)
    futures_date = futures.get("date") if futures else ref_date
    spot_close = float(core.get("close") or 0)
    fut_close = float(futures.get("close") or 0) if futures else 0.0
    basis_pct = compute_basis_pct(spot_close, fut_close) if futures else None
    lead = compute_futures_lead_stats(db_path, ref_date) if futures else {}
    if page_light:
        bt = []
        bt_plus = []
    else:
        bt = backtest_bucket_win_rate_by_regime(db_path, limit_days=60)
        bt_plus = backtest_bucket_win_rate_by_regime_plus(db_path, limit_days=60)
    rp = compute_regime_plus(db_path, ref_date)
    perf = _index_performance(idx)
    flow_parts = _sector_flow_breakdown(db_path, flow_date)
    return {
        "ok": True,
        "as_of": ref_date,
        "close": core.get("close", 0),
        "ma20": core.get("ma20", 0),
        "ma60": core.get("ma60", 0),
        "ma5": perf.get("ma5"),
        "chg5_pct": core.get("chg5_pct", 0),
        "slope20_pct": core.get("slope20_pct", 0),
        **{k: v for k, v in perf.items() if k != "ma5"},
        "sector_inflow": flow_parts.get("inflow") or [],
        "sector_outflow": flow_parts.get("outflow") or [],
        "chips_foreign": flow_parts.get("foreign_net"),
        "chips_trust": flow_parts.get("trust_net"),
        "chips_dealer": flow_parts.get("dealer_net"),
        "breadth_above_ma20": breadth.get("above_ma20_pct", 0),
        "sample_n": breadth.get("sample_n", 0),
        "breadth_as_of": breadth_date,
        "official_breadth": official,
        "sector_flow_net": round(flow_net, 0) if flow_net is not None else None,
        "sector_flow_as_of": flow_date,
        "regime": core.get("regime", "neutral"),
        "regime_label": core.get("regime_label", "區間震盪"),
        "confidence": core.get("confidence", 50),
        "score": core.get("score", 0),
        "falling_risk": fr.get("falling_risk", 0),
        "falling_risk_hits": fr.get("falling_risk_hits", []),
        "risk_zone": zones.get("risk_zone", "normal"),
        "support_zone": zones.get("support_zone", "none"),
        "futures": futures,
        "futures_as_of": futures_date,
        "basis_pct": basis_pct,
        "futures_lead": lead,
        "backtest": bt,
        "backtest_regime_plus": bt_plus,
        **rp,
    }


def backtest_bucket_win_rate_by_regime(db_path: str, limit_days: int = 60) -> List[Dict[str, Any]]:
    """海選隔日勝率 × 當日大盤 regime（需 index_daily + screen_picks）。"""
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        has_picks = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screen_picks'"
        ).fetchone()
        if not has_picks:
            return []
        rows = conn.execute(
            """
            SELECT p.bucket, i.regime, p.next_pct
            FROM screen_picks p
            JOIN index_daily i ON i.date = p.as_of AND i.symbol = ?
            WHERE p.next_pct IS NOT NULL
            ORDER BY p.as_of DESC
            LIMIT ?
            """,
            (_INDEX_SYMBOL, limit_days * 40),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    agg: Dict[Tuple[str, str], List[float]] = {}
    for bucket, regime, pct in rows:
        if not regime or regime == "unknown":
            continue
        agg.setdefault((str(bucket), str(regime)), []).append(float(pct))
    out = []
    for (bucket, regime), pcts in sorted(agg.items()):
        n = len(pcts)
        if n < 3:
            continue
        avg = sum(pcts) / n
        hit = sum(1 for p in pcts if p > 0) / n
        out.append(
            {
                "bucket": bucket,
                "regime": regime,
                "n": n,
                "avg_next_pct": round(avg, 2),
                "hit_rate": round(hit, 2),
            }
        )
    return out


def _variance(vals: List[float]) -> float:
    if not vals:
        return 0.0
    n = len(vals)
    mean = sum(vals) / n
    return sum((v - mean) ** 2 for v in vals) / n


def _covariance(xs: List[float], ys: List[float]) -> float:
    if not xs or len(xs) != len(ys):
        return 0.0
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n


def _index_pct_series(db_path: str, as_of: str, lookback: int = _BETA_LOOKBACK + 1) -> List[Tuple[str, float]]:
    """加權指數日漲跌幅序列（舊→新）。"""
    d = _norm_ymd(as_of)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT date, pct_change FROM index_daily
            WHERE symbol=? AND date <= ? ORDER BY date DESC LIMIT ?
            """,
            (_INDEX_SYMBOL, d, lookback),
        ).fetchall()
    finally:
        conn.close()
    out: List[Tuple[str, float]] = []
    for dt, pct in reversed(rows):
        try:
            out.append((str(dt), float(pct or 0)))
        except (TypeError, ValueError):
            continue
    return out


def compute_stock_betas(
    db_path: str,
    as_of: str,
    stock_ids: List[str],
    *,
    lookback: int = _BETA_LOOKBACK,
) -> Dict[str, float]:
    """個股對加權 60 日 β（cov/ var）；資料不足回傳 1.0 或不列入。"""
    ids = sorted({str(s).strip() for s in stock_ids if s})
    if not ids:
        return {}
    idx_series = _index_pct_series(db_path, as_of, lookback + 1)
    if len(idx_series) < 20:
        return {}
    dates = [d for d, _ in idx_series]
    idx_pcts = [p for _, p in idx_series]
    var_i = _variance(idx_pcts)
    if var_i <= 1e-12:
        return {}
    conn = sqlite3.connect(db_path)
    try:
        sid_ph = ",".join("?" * len(ids))
        date_ph = ",".join("?" * len(dates))
        rows = conn.execute(
            f"""
            SELECT stock_id, date, pct_change FROM daily_quotes
            WHERE stock_id IN ({sid_ph}) AND date IN ({date_ph})
            """,
            ids + dates,
        ).fetchall()
    finally:
        conn.close()
    by_sid: Dict[str, Dict[str, float]] = {}
    for sid, dt, pct in rows:
        try:
            by_sid.setdefault(str(sid), {})[str(dt)] = float(pct or 0)
        except (TypeError, ValueError):
            continue
    out: Dict[str, float] = {}
    for sid in ids:
        mp = by_sid.get(sid, {})
        paired_idx: List[float] = []
        paired_stk: List[float] = []
        for d, ip in idx_series:
            sp = mp.get(d)
            if sp is not None:
                paired_idx.append(ip)
                paired_stk.append(sp)
        if len(paired_idx) < 20:
            continue
        beta = _covariance(paired_stk, paired_idx) / var_i
        out[sid] = round(max(-2.0, min(3.0, beta)), 2)
    return out


def beta_sort_multiplier(beta: float, regime_plus: str) -> float:
    """高 β 股在空頭延伸／多頭末端自動降權（藍圖 §七）。"""
    if str(regime_plus or "") not in _BETA_DOWNWEIGHT_STATES:
        return 1.0
    b = float(beta or 1.0)
    if b <= 1.0:
        return 1.0
    return max(0.55, 1.0 - (b - 1.0) * 0.4)


def backtest_bucket_win_rate_by_regime_plus(
    db_path: str,
    limit_days: int = 60,
    *,
    max_compute_dates: int = 25,
) -> List[Dict[str, Any]]:
    """海選隔日勝率 × 當日 Regime+（需 screen_picks + index_daily）。"""
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        has_picks = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screen_picks'"
        ).fetchone()
        if not has_picks:
            return []
        rows = conn.execute(
            """
            SELECT p.bucket, p.as_of, p.next_pct
            FROM screen_picks p
            WHERE p.next_pct IS NOT NULL
            ORDER BY p.as_of DESC
            LIMIT ?
            """,
            (limit_days * 40,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    unique_dates = sorted({str(r[1]) for r in rows}, reverse=True)[:max_compute_dates]
    rp_cache: Dict[str, str] = {}
    for d in unique_dates:
        try:
            rp_cache[d] = str(compute_regime_plus(db_path, d).get("regime_plus") or "range")
        except Exception:
            rp_cache[d] = "range"
    agg: Dict[Tuple[str, str], List[float]] = {}
    for bucket, as_of, pct in rows:
        rp = rp_cache.get(str(as_of))
        if not rp:
            continue
        agg.setdefault((str(bucket), rp), []).append(float(pct))
    out: List[Dict[str, Any]] = []
    for (bucket, rp), pcts in sorted(agg.items()):
        n = len(pcts)
        if n < 3:
            continue
        avg = sum(pcts) / n
        hit = sum(1 for p in pcts if p > 0) / n
        out.append(
            {
                "bucket": bucket,
                "regime_plus": rp,
                "regime_plus_label": REGIME_PLUS_LABELS.get(rp, rp),
                "n": n,
                "avg_next_pct": round(avg, 2),
                "hit_rate": round(hit, 2),
            }
        )
    return out


def _item_sort_score(key: str, item: Dict[str, Any]) -> float:
    if key == "leave_zero":
        return float(item.get("q60r") or 0) * 2 + (20 - min(int(item.get("vol_rank_120") or 99), 20))
    if key == "golden_buy":
        return -float(item.get("bias_monthly") or 0)
    return float(item.get("q60r") or 0) + float(item.get("pct_change") or item.get("pct") or 0) * 0.1


def latest_regime(db_path: str) -> str:
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT regime FROM index_daily WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (_INDEX_SYMBOL,),
        ).fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return str(row[0])
    return "neutral"


def sync_regime_ai_weights(db_path: str, as_of: Optional[str] = None) -> Dict[str, float]:
    """盤後／海選後：復盤 base 權重 × Regime+（優先）或大盤 regime → bucket_w_*。"""
    from screen_review import adapt_bucket_weights

    snap = analyze_taiwan_market(db_path, as_of)
    regime = snap.get("regime") if snap.get("ok") else latest_regime(db_path)
    regime_plus = snap.get("regime_plus") if snap.get("ok") else None
    return adapt_bucket_weights(db_path, regime=regime, regime_plus=regime_plus)


def apply_market_weights(
    results: Dict[str, Any],
    snap: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """依 Regime+（優先）或大盤 regime 調整桶內排序與上限；falling_risk／期貨領跌／高 β 再疊加。"""
    if not snap.get("ok"):
        return results
    regime_plus = str(snap.get("regime_plus") or "")
    regime = str(snap.get("regime") or "neutral")
    if regime_plus:
        mults = regime_plus_bucket_mult(regime_plus)
        caps = dict(REGIME_PLUS_BUCKET_CAP.get(regime_plus, {}))
    else:
        mults = REGIME_BUCKET_MULT.get(regime, REGIME_BUCKET_MULT["neutral"])
        caps = dict(REGIME_BUCKET_CAP.get(regime, {}))
    out = dict(results)
    out["_mkt_regime"] = regime
    out["_mkt_regime_plus"] = regime_plus or None
    out["_mkt_confidence"] = snap.get("confidence")
    out["_falling_risk"] = snap.get("falling_risk", 0)
    fr = int(snap.get("falling_risk") or 0)
    falling_mult = 0.55 if fr >= 60 else (0.8 if fr >= 35 else 1.0)
    falling_caps = {"day_trade": 3, "overnight": 3} if fr >= 60 else {}
    lead = snap.get("futures_lead") or {}
    if str(lead.get("label") or "") == "期貨領跌" and fr >= 35:
        falling_mult = min(falling_mult, 0.75)
    as_of = str(snap.get("as_of") or "")
    betas: Dict[str, float] = {}
    if db_path and as_of and regime_plus in _BETA_DOWNWEIGHT_STATES:
        stock_ids: List[str] = []
        for key, items in results.items():
            if isinstance(items, list) and not key.startswith("_"):
                stock_ids.extend(str(it.get("stock_id")) for it in items if it.get("stock_id"))
        betas = compute_stock_betas(db_path, as_of, stock_ids)
        if betas:
            out["_stock_betas"] = betas
    for key, items in list(out.items()):
        if not isinstance(items, list) or key.startswith("_"):
            continue
        if not items:
            continue
        m = float(mults.get(key, 1.0))
        if key in ("day_trade", "overnight") and falling_mult < 1.0:
            m *= falling_mult
        scored = sorted(
            (
                (
                    float(_item_sort_score(key, it))
                    * m
                    * beta_sort_multiplier(betas.get(str(it.get("stock_id")), 1.0), regime_plus),
                    it,
                )
                for it in items
            ),
            key=lambda x: x[0],
            reverse=True,
        )
        trimmed = [it for _, it in scored]
        cap = caps.get(key)
        if key in falling_caps:
            cap = min(cap, falling_caps[key]) if cap else falling_caps[key]
        if cap and len(trimmed) > cap:
            trimmed = trimmed[:cap]
        out[key] = trimmed
    return out


def market_screening_note(snap: Dict[str, Any]) -> str:
    if not snap.get("ok"):
        return ""
    rp_note = regime_plus_screening_note(snap)
    if rp_note:
        return rp_note
    reg = snap.get("regime")
    conf = snap.get("confidence")
    if reg == "bull":
        return f"大盤多頭帶動（信心 {conf}%）：佈局桶加權偏多，起漲仍看獲利格。"
    if reg == "bear":
        return f"大盤空方壓力（信心 {conf}%）：突破桶縮水，起漲需量熱＋站上月線。"
    fr = int(snap.get("falling_risk") or 0)
    if fr >= 60:
        return f"下跌風險 {fr}（紅燈）：當沖/隔日沖桶再降權，佈局看獲利格＋站上月線。"
    if fr >= 35:
        return f"下跌風險 {fr}（黃燈）：短線桶保守，選股看結構。"
    return f"大盤區間震盪（信心 {conf}%）：中性權重，選股看個股結構。"


def _regime_traffic_light(regime: str) -> str:
    return {"bull": "🟢", "neutral": "🟡", "bear": "🔴"}.get(str(regime or ""), "⚪")


def _regime_plus_traffic_light(regime_plus: str) -> str:
    return {
        "trend_up": "🟢",
        "repair": "🟢",
        "range": "🟡",
        "trend_up_late": "🟡",
        "down_exhaust": "🟡",
        "trend_down": "🔴",
    }.get(str(regime_plus or ""), "⚪")


_TG_SECTION = "────────────────"


def _index_day_change(db_path: str, as_of: str) -> Optional[float]:
    """讀 index_daily 當日漲跌幅；僅 SELECT，不寫庫。"""
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT pct_change FROM index_daily WHERE symbol=? AND date=?",
            (_INDEX_SYMBOL, str(as_of)),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _ret_n(closes: pd.Series, n: int) -> Optional[float]:
    if closes is None or len(closes) <= n:
        return None
    base = float(closes.iloc[-1 - n])
    last = float(closes.iloc[-1])
    if base <= 0:
        return None
    return round((last / base - 1.0) * 100.0, 2)


def _index_performance(idx: pd.DataFrame) -> Dict[str, Any]:
    """從 index_daily 算多週期漲跌、均線距離、量比、年高低——不打外部。"""
    if idx is None or idx.empty or "close" not in idx.columns:
        return {}
    closes = idx["close"].astype(float)
    c = float(closes.iloc[-1])
    ma5 = float(closes.tail(5).mean()) if len(closes) >= 5 else None
    ma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else None
    ma60 = float(closes.tail(60).mean()) if len(closes) >= 60 else None
    look = closes.tail(min(len(closes), 252))
    hi52 = float(look.max()) if len(look) else None
    lo52 = float(look.min()) if len(look) else None
    vs20 = round((c / ma20 - 1.0) * 100.0, 2) if ma20 and ma20 > 0 else None
    vs60 = round((c / ma60 - 1.0) * 100.0, 2) if ma60 and ma60 > 0 else None
    vs_hi = round((c / hi52 - 1.0) * 100.0, 2) if hi52 and hi52 > 0 else None
    vs_lo = round((c / lo52 - 1.0) * 100.0, 2) if lo52 and lo52 > 0 else None
    vol_ratio = None
    last_vol = None
    prev_vol = None
    if "volume" in idx.columns and len(idx) >= 1:
        vols = idx["volume"].astype(float)
        last_vol = float(vols.iloc[-1] or 0)
        if last_vol <= 0:
            # Yahoo ^TWII 最新一根量常是 0；拿 0 去除以昨量會變成「量縮 100%、量比 0.00」。
            last_vol = None
        else:
            avg20 = float(vols.tail(20).mean()) if len(vols) >= 5 else 0.0
            if avg20 > 0:
                vol_ratio = round(last_vol / avg20, 2)
            if len(vols) >= 2:
                prev_vol = float(vols.iloc[-2] or 0)
    open_px = high_px = low_px = None
    if "open" in idx.columns:
        try:
            open_px = float(idx["open"].iloc[-1] or 0) or None
            high_px = float(idx["high"].iloc[-1] or 0) or None
            low_px = float(idx["low"].iloc[-1] or 0) or None
        except (TypeError, ValueError, KeyError):
            open_px = high_px = low_px = None
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
    amplitude = None
    spread = None
    if high_px and low_px and prev_close and prev_close > 0:
        spread = round(high_px - low_px, 2)
        amplitude = round((high_px - low_px) / prev_close * 100.0, 2)
    vol_chg_pct = None
    if last_vol is not None and prev_vol and prev_vol > 0:
        vol_chg_pct = round((last_vol / prev_vol - 1.0) * 100.0, 1)
    ytd = None
    if "date" in idx.columns:
        year = str(idx["date"].iloc[-1])[:4]
        yrows = idx[idx["date"].astype(str).str.startswith(year)]
        if not yrows.empty and float(yrows["close"].iloc[0] or 0) > 0:
            ytd = round((c / float(yrows["close"].iloc[0]) - 1.0) * 100.0, 2)
    chg1 = None
    if "pct_change" in idx.columns:
        try:
            chg1 = round(float(idx["pct_change"].iloc[-1]), 2)
        except (TypeError, ValueError):
            chg1 = None
    if chg1 is None:
        chg1 = _ret_n(closes, 1)
    return {
        "ma5": round(ma5, 1) if ma5 is not None else None,
        "chg1_pct": chg1,
        "chg10_pct": _ret_n(closes, 10),
        "chg20_pct": _ret_n(closes, 20),
        "chg60_pct": _ret_n(closes, 60),
        "ytd_pct": ytd,
        "vs_ma20_pct": vs20,
        "vs_ma60_pct": vs60,
        "high52": round(hi52, 1) if hi52 is not None else None,
        "low52": round(lo52, 1) if lo52 is not None else None,
        "vs_high52_pct": vs_hi,
        "vs_low52_pct": vs_lo,
        "volume": last_vol,
        "prev_volume": prev_vol,
        "vol_ratio": vol_ratio,
        "vol_chg_pct": vol_chg_pct,
        "open": round(open_px, 2) if open_px else None,
        "high": round(high_px, 2) if high_px else None,
        "low": round(low_px, 2) if low_px else None,
        "prev_close": round(prev_close, 2) if prev_close else None,
        "amplitude_pct": amplitude,
        "hl_spread": spread,
    }


def _sector_flow_breakdown(db_path: str, as_of: str) -> Dict[str, Any]:
    """當日產業買超／賣超前三 + 三大法人合計。表不存在或無列則空。"""
    empty: Dict[str, Any] = {
        "inflow": [],
        "outflow": [],
        "foreign_net": None,
        "trust_net": None,
        "dealer_net": None,
    }
    conn = sqlite3.connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_sector_flow'"
        ).fetchone()
        if not has:
            return empty
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(daily_sector_flow)")}
        name_col = "industry" if "industry" in cols else ("sector" if "sector" in cols else None)
        if not name_col:
            return empty
        three = "COALESCE(foreign_net,0)+COALESCE(trust_net,0)+COALESCE(dealer_net,0)"
        rows = conn.execute(
            f"SELECT {name_col}, {three} FROM daily_sector_flow WHERE date=? ORDER BY 2 DESC",
            (as_of,),
        ).fetchall()
        ftd = conn.execute(
            "SELECT SUM(foreign_net), SUM(trust_net), SUM(dealer_net) FROM daily_sector_flow WHERE date=?",
            (as_of,),
        ).fetchone()
    except sqlite3.Error:
        return empty
    finally:
        conn.close()
    named = []
    for name, val in rows or []:
        try:
            named.append((str(name or "").strip() or "產業", float(val or 0)))
        except (TypeError, ValueError):
            continue
    inflow = [(n, v) for n, v in named if v > 0][:3]
    outflow = sorted([(n, v) for n, v in named if v < 0], key=lambda x: x[1])[:3]

    def _ftd(i: int) -> Optional[float]:
        if not ftd or ftd[i] is None:
            return None
        try:
            return float(ftd[i])
        except (TypeError, ValueError):
            return None

    return {
        "inflow": inflow,
        "outflow": outflow,
        "foreign_net": _ftd(0),
        "trust_net": _ftd(1),
        "dealer_net": _ftd(2),
    }


def _fmt_signed_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{float(val):+.2f}%"


def _fmt_lots(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{float(val):+,.0f} 張"


def _format_chips_line(snap: Dict[str, Any]) -> str:
    bits = []
    for key, name in (("chips_foreign", "外資"), ("chips_trust", "投信"), ("chips_dealer", "自營")):
        val = snap.get(key)
        if val is None:
            continue
        bits.append(f"{name} {_fmt_lots(val).replace(' 張', '')}")
    return "　".join(bits) + " 張" if bits else ""


def _ohlc_from_live_or_snap(snap: Dict[str, Any], live: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    src = live or {}

    def _pick(*keys):
        for k in keys:
            try:
                v = float(src.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
        for k in keys:
            try:
                v = float(snap.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
        return None

    out = {
        "open": _pick("open"),
        "high": _pick("high"),
        "low": _pick("low"),
        "prev_close": _pick("yesterday_close", "prev_close"),
    }
    hi, lo, prev = out["high"], out["low"], out["prev_close"]
    out["hl_spread"] = round(hi - lo, 2) if hi and lo else snap.get("hl_spread")
    out["amplitude_pct"] = (
        round((hi - lo) / prev * 100.0, 2) if hi and lo and prev else snap.get("amplitude_pct")
    )
    return out


def _format_performance_lines(snap: Dict[str, Any], live: Optional[Dict[str, Any]] = None) -> List[str]:
    """只放會改判斷的欄：開高低、振幅、量對昨、距月線／年高。"""
    ohlc = _ohlc_from_live_or_snap(snap, live)
    lines: List[str] = []
    if ohlc.get("open") and ohlc.get("high") and ohlc.get("low"):
        prev = ohlc.get("prev_close")
        prev_s = f"{prev:,.2f}" if prev else "—"
        lines.append(
            f"開 {ohlc['open']:,.2f}　高 {ohlc['high']:,.2f}　"
            f"低 {ohlc['low']:,.2f}　昨收 {prev_s}"
        )
    amp = ohlc.get("amplitude_pct")
    spread = ohlc.get("hl_spread")
    if amp is not None and spread is not None:
        lines.append(f"振幅 {amp:.2f}%　高低差 {spread:,.2f}")
    vol_chg = snap.get("vol_chg_pct")
    vol_r = snap.get("vol_ratio")
    vol_bits = []
    if vol_chg is not None:
        tag = "量增" if vol_chg > 0 else ("量縮" if vol_chg < 0 else "量平")
        vol_bits.append(f"{tag} {abs(vol_chg):.1f}%")
    if vol_r is not None:
        vol_bits.append(f"量比 {float(vol_r):.2f}")
    if vol_bits:
        lines.append("　".join(vol_bits))
    lines.append(
        f"距月線 {_fmt_signed_pct(snap.get('vs_ma20_pct'))}　"
        f"距年高 {_fmt_signed_pct(snap.get('vs_high52_pct'))}"
    )
    return lines or ["—"]


def _sector_short(name: str) -> str:
    try:
        from money_flow import _sector_short_name

        return _sector_short_name(name)
    except Exception:
        s = str(name or "").strip()
        return s[:-1] if s.endswith("業") and len(s) > 2 else (s or "產業")


def _market_read_note(snap: Dict[str, Any]) -> str:
    """用數字寫解讀，避免只剩 Regime 標籤。"""
    bits: List[str] = []
    vs20 = snap.get("vs_ma20_pct")
    vs60 = snap.get("vs_ma60_pct")
    chg5 = snap.get("chg5_pct")
    vs_hi = snap.get("vs_high52_pct")
    vol_r = snap.get("vol_ratio")
    breadth = snap.get("breadth_above_ma20")
    fr = int(snap.get("falling_risk") or 0)
    if vs20 is not None:
        if vs20 >= 1.0:
            bits.append(f"收在月線上 {vs20:.1f}%")
        elif vs20 <= -1.0:
            bits.append(f"收在月線下 {abs(vs20):.1f}%")
        else:
            bits.append("貼著月線")
    if vs60 is not None:
        bits.append("季線上方" if vs60 >= 0 else "季線下方")
    if chg5 is not None:
        if chg5 >= 1.5:
            bits.append(f"5日偏強 {chg5:+.1f}%")
        elif chg5 <= -1.5:
            bits.append(f"5日轉弱 {chg5:+.1f}%")
        else:
            bits.append(f"5日 {chg5:+.1f}%")
    if vs_hi is not None:
        if vs_hi >= -3:
            bits.append(f"距年高僅 {abs(vs_hi):.1f}%")
        elif vs_hi <= -12:
            bits.append(f"距年高已遠 {abs(vs_hi):.1f}%")
        else:
            bits.append(f"距年高 {abs(vs_hi):.1f}%")
    if vol_r is not None:
        if vol_r >= 1.2:
            bits.append(f"量比 {vol_r:.2f} 放大")
        elif vol_r <= 0.8:
            bits.append(f"量比 {vol_r:.2f} 縮量")
        else:
            bits.append(f"量比 {vol_r:.2f}")
    if breadth is not None and float(breadth) > 0:
        bits.append(f"站上月線 {float(breadth):.0f}%")
    if fr >= 60:
        bits.append("下跌風險紅燈，少追")
    elif fr >= 35:
        bits.append("下跌風險黃燈")
    if not bits:
        return ""
    return "；".join(bits) + "。"


def format_taiwan_market_brief_html(db_path: str, as_of: Optional[str] = None) -> str:
    snap = analyze_taiwan_market(db_path, as_of)
    if not snap.get("ok"):
        return ""
    fr_light = _falling_risk_light(int(snap.get("falling_risk") or 0))
    lines = [
        "<b>📊 台灣加權指數研究</b>",
        f"收盤 <b>{snap['close']}</b>",
        f"MA5 {snap.get('ma5') or snap['ma20']}　MA20 {snap['ma20']}　MA60 {snap['ma60']}",
        f"日 {_fmt_signed_pct(snap.get('chg1_pct'))}　5日 {snap['chg5_pct']:+.2f}%　20日 {_fmt_signed_pct(snap.get('chg20_pct'))}",
        f"距月線 {_fmt_signed_pct(snap.get('vs_ma20_pct'))}　距年高 {_fmt_signed_pct(snap.get('vs_high52_pct'))}",
        *(
            [line]
            if (line := _format_futures_line(snap))
            else []
        ),
        f"站上月線 {snap['breadth_above_ma20']:.1f}%（{snap['sample_n']} 檔）",
        *(
            [f"產業法人 {snap['sector_flow_net']:+,.0f} 張"]
            if snap.get("sector_flow_net") is not None
            else []
        ),
        _TG_SECTION,
        f"Regime <b>{snap['regime_label']}</b>（{snap['confidence']}%）",
        f"Regime+ {_regime_plus_traffic_light(snap.get('regime_plus'))} <b>{snap.get('regime_plus_label', '—')}</b>",
        f"下跌風險 {fr_light} <b>{snap.get('falling_risk', 0)}</b>",
        f"高檔區 {_risk_zone_label(snap.get('risk_zone'))}",
        market_screening_note(snap),
    ]
    bt = snap.get("backtest") or []
    cur = snap.get("regime")
    hits = [b for b in bt if b.get("regime") == cur and b.get("n", 0) >= 5]
    if hits:
        bits = [f"{b['bucket']} 隔日{b['avg_next_pct']:+.1f}%（勝{b['hit_rate']:.0%}）" for b in hits[:3]]
        lines.append("同 regime 海選復盤：" + "　".join(bits))
    bt_rp = snap.get("backtest_regime_plus") or []
    cur_rp = snap.get("regime_plus")
    hits_rp = [b for b in bt_rp if b.get("regime_plus") == cur_rp and b.get("n", 0) >= 3]
    if hits_rp:
        bits_rp = [
            f"{b['bucket']} 隔日{b['avg_next_pct']:+.1f}%（勝{b['hit_rate']:.0%}）"
            for b in hits_rp[:3]
        ]
        lines.append("同 Regime+ 海選復盤：" + "　".join(bits_rp))
    return "\n".join(lines)


def format_taiwan_market_page_html(
    db_path: str,
    as_of: Optional[str] = None,
    *,
    live: Optional[Dict[str, Any]] = None,
    snap: Optional[Dict[str, Any]] = None,
) -> str:
    """Telegram「大盤」專頁：只讀庫內；基準日自動對齊 index_daily／官股日 K。"""
    ref_hint = resolve_market_as_of(db_path, as_of)
    if snap is None:
        snap = analyze_taiwan_market(db_path, ref_hint, db_only=True, page_light=True)
    if not snap.get("ok"):
        logger.error("大盤頁：index_daily 無法解析基準日 db=%s hint=%s", db_path, ref_hint)
        return (
            "<b>📊 台股大盤</b>\n"
            "指數資料讀取異常，已記錄；系統會在下一輪盤後融合自動修復。"
        )
    ref = str(snap.get("as_of") or ref_hint)
    day_pct = _index_day_change(db_path, ref)
    light = _regime_traffic_light(snap.get("regime"))
    fr_light = _falling_risk_light(int(snap.get("falling_risk") or 0))
    live_px = float((live or {}).get("close") or 0)
    yest = float((live or {}).get("yesterday_close") or snap.get("prev_close") or 0)
    show_px = live_px if live_px > 0 else float(snap.get("close") or 0)
    show_pct = float((live or {}).get("pct_change") or day_pct or snap.get("chg1_pct") or 0)
    chg_pts = (show_px - yest) if show_px and yest else None
    clock = str((live or {}).get("update_time") or "")[:5]
    if live_px > 0:
        as_of_note = "<i>盤中 MIS 即時；廣度／法人仍依庫內最近完整日</i>"
        px_line = f"<b>{show_px:,.2f}</b>"
        if chg_pts is not None:
            px_line += f"　{chg_pts:+,.2f}（{show_pct:+.2f}%）"
        else:
            px_line += f"（{show_pct:+.2f}%）"
        if clock:
            px_line += f"　{clock}"
    else:
        as_of_note = "<i>庫內官方融合收盤</i>"
        pct_bit = f"（{day_pct:+.2f}%）" if day_pct is not None else ""
        px_line = f"收盤 <b>{float(snap['close']):,.2f}</b>{pct_bit}"
        if chg_pts is not None:
            px_line += f"　{chg_pts:+,.2f}"
    lines = [
        "<b>📊 台股大盤</b>",
        f"截至 <b>{ref}</b>",
        as_of_note,
        "",
        "<b>加權指數</b>",
        px_line,
        *_format_performance_lines(snap, live),
        "",
        _TG_SECTION,
        "<b>漲跌家數</b>",
    ]
    qb = _quote_up_down_counts(db_path, ref)
    if int(qb.get("n") or 0) > 0 and int(qb.get("up") or 0) + int(qb.get("down") or 0) > 0:
        line = f"漲 {qb['up']}　跌 {qb['down']}"
        if int(qb.get("flat") or 0) > 0:
            line += f"　平 {qb['flat']}"
        lines.append(line)
    ob = snap.get("official_breadth")
    ob_same_day = bool(ob) and str(ob.get("date") or "") == ref
    if (not qb or int(qb.get("n") or 0) <= 0) and ob_same_day:
        up_n = int(ob.get("up_count") or 0)
        down_n = int(ob.get("down_count") or 0)
        # 證交所新表含權證，家數會到數千；那種數字不當「漲跌家數」。
        if 0 < up_n + down_n <= 2500:
            lines.append(f"漲 {up_n}　跌 {down_n}")
    if ob_same_day:
        lu, ld = int(ob.get("limit_up") or 0), int(ob.get("limit_down") or 0)
        if lu + ld > 0:
            lines.append(f"漲停 {lu}　跌停 {ld}")
    if int(snap.get("sample_n") or 0) > 0:
        lines.append(f"站上月線 {snap['breadth_above_ma20']:.1f}%")
    flow_date = str(snap.get("sector_flow_as_of") or ref)
    flow_net = snap.get("sector_flow_net")
    lines.extend(["", _TG_SECTION, "<b>三大法人</b>"])
    chips_line = _format_chips_line(snap)
    if chips_line:
        lines.append(chips_line)
    if flow_net is not None and _sector_flow_net(db_path, flow_date) is not None:
        f_note = f"（{flow_date}）" if flow_date != ref else ""
        lines.append(f"合計 {float(flow_net):+,.0f} 張{f_note}")
    fut_line = _format_futures_line(snap)
    if fut_line:
        lines.extend(["", fut_line.split("\n")[0]])
    lines.extend(
        [
            "",
            _TG_SECTION,
            "<b>結構</b>",
            f"{light} {snap['regime_label']}　"
            f"{_regime_plus_traffic_light(snap.get('regime_plus'))} {snap.get('regime_plus_label', '—')}　"
            f"風險 {fr_light}{snap.get('falling_risk', 0)}",
        ]
    )
    read = _market_read_note(snap)
    if read:
        lines.extend(["", read])
    try:
        from us_overnight import REGIME_LABEL, load_us_overnight

        us = load_us_overnight(db_path, ref)
        if us.get("ok") or us.get("vix") is not None:
            us_label = REGIME_LABEL.get(str(us.get("regime") or "unknown"), "美股")
            vix = us.get("vix")
            ixic = us.get("ixic_pct")
            bits = [us_label]
            if ixic is not None:
                bits.append(f"那斯達克 {float(ixic):+.2f}%")
            if vix is not None:
                bits.append(f"VIX {float(vix):.1f}")
            lines.extend(["", "　".join(bits)])
    except Exception:
        pass
    return "\n".join(lines)


# 向後相容
apply_market_filter = apply_market_weights
