#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年／大盤活資料｜精簡補抓落庫（靜默）。

補：
1. market_tape_daily：證交所 FMTQIK 全日成交金額（元）— 給「≥1.3兆」口徑
2. market_margin_daily：MI_MARGN 大盤融資金額（仟元）長史
3. decade_lab.db lab_daily：2330 Yahoo 十年（raw＋adj）— 市值龍頭對照；標明非官方
4. index_daily OTC：櫃買指數（TPEX 日成交量值指數／tradingIndex；台北日）

原則：只存日彙總／必要 OHLC，不准堆 PNG；缺就標缺；不是買訊；不准寫回話筒。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
UA = "Mozilla/5.0 (compatible; WayneBot-decade-lab/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

TAPE_DDL = """
CREATE TABLE IF NOT EXISTS market_tape_daily (
    date TEXT PRIMARY KEY,
    amount_ntd INTEGER NOT NULL,
    shares INTEGER,
    trades INTEGER,
    twii_close REAL,
    amount_trillion REAL,
    source TEXT NOT NULL DEFAULT 'twse_fmtqik',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_market_tape_date ON market_tape_daily(date);
"""

LAB_DDL = """
CREATE TABLE IF NOT EXISTS lab_daily (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL DEFAULT 0,
    adj_close REAL,
    adj_kind TEXT NOT NULL DEFAULT 'raw_quote',
    source TEXT NOT NULL DEFAULT '',
    pack TEXT NOT NULL DEFAULT '',
    tz_rule TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (symbol, date, adj_kind)
);
CREATE INDEX IF NOT EXISTS idx_lab_daily_sym_date ON lab_daily(symbol, date);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _int_commas(raw: Any) -> Optional[int]:
    s = str(raw or "").replace(",", "").strip()
    if not s or s in {"--", "-"}:
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _float_commas(raw: Any) -> Optional[float]:
    s = str(raw or "").replace(",", "").strip()
    if not s or s in {"--", "-"}:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _roc_to_ymd(raw: str) -> str:
    """115/11/02 → 20261102"""
    s = str(raw or "").strip()
    parts = s.replace("-", "/").split("/")
    if len(parts) != 3:
        return ""
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return ""
    if y < 1911:
        y += 1911
    return f"{y:04d}{m:02d}{d:02d}"


def ensure_tape(conn: sqlite3.Connection) -> None:
    conn.executescript(TAPE_DDL)
    conn.commit()


def ensure_lab(conn: sqlite3.Connection) -> None:
    conn.executescript(LAB_DDL)
    conn.commit()


def fetch_fmtqik_month(yyyymm: str) -> List[Dict[str, Any]]:
    """月份字串 YYYYMM → 該月 FMTQIK 列。"""
    ym = str(yyyymm or "")[:6]
    if len(ym) != 6 or not ym.isdigit():
        return []
    date = ym + "01"
    url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={date}"
    try:
        r = SESSION.get(url, timeout=40)
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return []
    if str(payload.get("stat") or "") != "OK":
        return []
    out: List[Dict[str, Any]] = []
    for row in payload.get("data") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        day = _roc_to_ymd(str(row[0]))
        if len(day) != 8:
            continue
        shares = _int_commas(row[1])
        amount = _int_commas(row[2])
        trades = _int_commas(row[3])
        twii = _float_commas(row[4])
        if amount is None:
            continue
        out.append(
            {
                "date": day,
                "shares": shares,
                "amount_ntd": amount,
                "trades": trades,
                "twii_close": twii,
                "amount_trillion": round(amount / 1e12, 4),
            }
        )
    return out


def backfill_market_tape(
    db_path: Path, *, from_ym: str = "201701", sleep_s: float = 0.35
) -> Dict[str, Any]:
    if not db_path.is_file():
        return {"ok": False, "error": "missing_db"}
    start = datetime.strptime(from_ym + "01", "%Y%m%d")
    end = datetime.now(TAIPEI).replace(day=1)
    months: List[str] = []
    cur = start
    while cur <= end.replace(tzinfo=None):
        months.append(cur.strftime("%Y%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    wrote = 0
    failed: List[str] = []
    try:
        ensure_tape(conn)
        stamp = _now()
        for i, ym in enumerate(months):
            rows = fetch_fmtqik_month(ym)
            if not rows:
                failed.append(ym)
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO market_tape_daily(
                        date, amount_ntd, shares, trades, twii_close,
                        amount_trillion, source, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(date) DO UPDATE SET
                        amount_ntd=excluded.amount_ntd,
                        shares=excluded.shares,
                        trades=excluded.trades,
                        twii_close=excluded.twii_close,
                        amount_trillion=excluded.amount_trillion,
                        source=excluded.source,
                        updated_at=excluded.updated_at
                    """,
                    (
                        r["date"],
                        int(r["amount_ntd"]),
                        r.get("shares"),
                        r.get("trades"),
                        r.get("twii_close"),
                        r.get("amount_trillion"),
                        "twse_fmtqik",
                        stamp,
                    ),
                )
                wrote += 1
            conn.commit()
            if i < len(months) - 1:
                time.sleep(max(0.0, sleep_s))
        n = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_tape_daily").fetchone()
    finally:
        conn.close()
    return {
        "ok": True,
        "wrote_rows": wrote,
        "months": len(months),
        "failed_months": failed[:12],
        "failed_n": len(failed),
        "table_n": int(n[0] or 0) if n else 0,
        "from": n[1] if n else "",
        "to": n[2] if n else "",
    }


def backfill_market_margin(
    db_path: Path, *, from_ymd: str = "20200101", sleep_s: float = 0.25, max_days: int = 0
) -> Dict[str, Any]:
    from official_snapshots import fetch_twse_market_margin, ensure_schema, _upsert_market_margin
    from trading_calendar import is_tw_open_calendar_day

    path = ensure_schema(str(db_path))
    start = datetime.strptime(_ymd(from_ymd), "%Y%m%d")
    end = datetime.now(TAIPEI).date()
    days: List[str] = []
    d = start.date()
    while d <= end:
        ymd = d.strftime("%Y%m%d")
        if is_tw_open_calendar_day(ymd):
            days.append(ymd)
        d += timedelta(days=1)
    if max_days > 0:
        days = days[-int(max_days) :]
    # skip already present
    conn = sqlite3.connect(path, timeout=60.0)
    try:
        have = {
            str(r[0])
            for r in conn.execute("SELECT date FROM market_margin_daily").fetchall()
        }
    finally:
        conn.close()
    todo = [x for x in days if x not in have]
    wrote = 0
    errors = 0
    now = datetime.now(__import__('datetime').timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, ymd in enumerate(todo):
        try:
            row = fetch_twse_market_margin(ymd)
        except Exception:
            errors += 1
            row = None
        if row:
            conn = sqlite3.connect(path, timeout=30.0)
            try:
                wrote += int(_upsert_market_margin(conn, row, now) or 0)
                conn.commit()
            finally:
                conn.close()
        if i < len(todo) - 1:
            time.sleep(max(0.0, sleep_s))
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        n, mn, mx = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM market_margin_daily"
        ).fetchone()
    finally:
        conn.close()
    return {
        "ok": True,
        "todo": len(todo),
        "wrote": wrote,
        "errors": errors,
        "table_n": int(n or 0),
        "from": mn,
        "to": mx,
    }


def fetch_yahoo_2330(range_: str = "10y") -> List[Dict[str, Any]]:
    from scripts.decade_lab_freeze import fetch_yahoo_daily_full

    return fetch_yahoo_daily_full("2330.TW", range_=range_, tz_name="Asia/Taipei")


def backfill_tsmc_lab(lab_db: Path, *, range_: str = "10y") -> Dict[str, Any]:
    bars = fetch_yahoo_2330(range_=range_)
    if not bars:
        return {"ok": False, "error": "yahoo_empty"}
    lab_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(lab_db), timeout=60.0)
    wrote_raw = wrote_adj = 0
    stamp = _now()
    try:
        ensure_lab(conn)
        for b in bars:
            day = _ymd(b.get("date"))
            if not day:
                continue
            conn.execute(
                """
                INSERT INTO lab_daily(
                    symbol, date, open, high, low, close, volume,
                    adj_close, adj_kind, source, pack, tz_rule, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol, date, adj_kind) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    adj_close=excluded.adj_close, source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                (
                    "2330",
                    day,
                    b.get("open"),
                    b.get("high"),
                    b.get("low"),
                    b.get("close"),
                    b.get("volume"),
                    b.get("adj_close"),
                    "raw_quote",
                    "yahoo",
                    "C_2330",
                    "Asia/Taipei",
                    stamp,
                ),
            )
            wrote_raw += 1
            if b.get("adj_close"):
                # 還原列：OHLC 等比縮到 adj（精簡：只存 close=adj, o/h/l 等比）
                c = float(b["close"] or 0)
                adj = float(b["adj_close"] or 0)
                if c > 0 and adj > 0:
                    ratio = adj / c
                    conn.execute(
                        """
                        INSERT INTO lab_daily(
                            symbol, date, open, high, low, close, volume,
                            adj_close, adj_kind, source, pack, tz_rule, fetched_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(symbol, date, adj_kind) DO UPDATE SET
                            open=excluded.open, high=excluded.high, low=excluded.low,
                            close=excluded.close, volume=excluded.volume,
                            adj_close=excluded.adj_close, source=excluded.source,
                            fetched_at=excluded.fetched_at
                        """,
                        (
                            "2330",
                            day,
                            (b.get("open") or c) * ratio,
                            (b.get("high") or c) * ratio,
                            (b.get("low") or c) * ratio,
                            adj,
                            b.get("volume"),
                            adj,
                            "yahoo_adjclose",
                            "yahoo",
                            "C_2330",
                            "Asia/Taipei",
                            stamp,
                        ),
                    )
                    wrote_adj += 1
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM lab_daily WHERE symbol='2330' AND adj_kind='raw_quote'"
        ).fetchone()
    finally:
        conn.close()
    return {
        "ok": True,
        "wrote_raw": wrote_raw,
        "wrote_adj": wrote_adj,
        "n": int(n[0] or 0) if n else 0,
        "from": n[1] if n else "",
        "to": n[2] if n else "",
        "note": "lab only；話筒查股仍認官方 daily_quotes",
    }


def _roc_date_to_ymd(s: str) -> str:
    """113/11/01 → 20241101。"""
    parts = str(s or "").strip().replace("-", "/").split("/")
    if len(parts) != 3:
        return ""
    try:
        y = int(parts[0]) + 1911
        m = int(parts[1])
        d = int(parts[2])
        return f"{y:04d}{m:02d}{d:02d}"
    except (TypeError, ValueError):
        return ""


def _f_num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.replace(",", "")
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def fetch_tpex_otc_month(yyyy: int, mm: int) -> List[Dict[str, Any]]:
    """櫃買指數月窗（TPEX tradingIndex；欄位 close＝指數收）。"""
    # 新站
    url = (
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingIndex"
        f"?date={yyyy:04d}/{mm:02d}/01&response=json"
    )
    data: List[Any] = []
    try:
        resp = SESSION.get(url, timeout=45)
        resp.raise_for_status()
        payload = resp.json()
        tables = payload.get("tables") or []
        if tables:
            data = tables[0].get("data") or []
    except Exception:
        data = []
    if not data:
        # 舊站 ROC 日
        roc_y = yyyy - 1911
        url2 = (
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_index/"
            f"st41_result.php?l=zh-tw&d={roc_y}/{mm:02d}/01"
        )
        try:
            resp = SESSION.get(url2, timeout=45)
            resp.raise_for_status()
            payload = resp.json()
            tables = payload.get("tables") or []
            data = (tables[0].get("data") if tables else None) or payload.get("aaData") or []
        except Exception:
            return []
    out: List[Dict[str, Any]] = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        ymd = _roc_date_to_ymd(row[0])
        close = _f_num(row[4])
        chg = _f_num(row[5])
        if not ymd or close is None or close <= 0:
            continue
        out.append(
            {
                "date": ymd,
                "close": close,
                "pct_change": chg,
                "volume": _f_num(str(row[1]).replace(",", "")) if row[1] is not None else None,
            }
        )
    return out


def backfill_otc_index(
    db_path: Path, *, from_ym: str = "201001", sleep_s: float = 0.2, max_months: int = 0
) -> Dict[str, Any]:
    """補 index_daily symbol=OTC（櫃買指數）。缺就不硬填假數。"""
    from scripts.decade_lab_outer_backfill import ensure_index

    raw = str(from_ym or "201001").replace("/", "").replace("-", "")
    if len(raw) == 6:
        y0, m0 = int(raw[:4]), int(raw[4:6])
    elif len(raw) == 8:
        y0, m0 = int(raw[:4]), int(raw[4:6])
    else:
        y0, m0 = 2010, 1
    end = datetime.now(TAIPEI).date()
    months: List[Tuple[int, int]] = []
    y, m = y0, m0
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    if max_months > 0:
        months = months[-int(max_months) :]

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60.0)
    wrote = 0
    errors = 0
    stamp = _now()
    try:
        ensure_index(conn)
        for i, (yy, mm) in enumerate(months):
            try:
                bars = fetch_tpex_otc_month(yy, mm)
            except Exception:
                errors += 1
                bars = []
            for b in bars:
                day = b["date"]
                c = float(b["close"])
                conn.execute(
                    """
                    INSERT INTO index_daily(
                        date, symbol, open, high, low, close, volume, pct_change, regime, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, symbol) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume,
                        pct_change=excluded.pct_change, regime=excluded.regime,
                        updated_at=excluded.updated_at
                    """,
                    (
                        day,
                        "OTC",
                        c,
                        c,
                        c,
                        c,
                        b.get("volume"),
                        b.get("pct_change"),
                        "tpex_trading_index",
                        stamp,
                    ),
                )
                wrote += 1
            conn.commit()
            if i < len(months) - 1:
                time.sleep(max(0.0, sleep_s))
        n, mn, mx = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM index_daily WHERE symbol='OTC'"
        ).fetchone()
    finally:
        conn.close()
    return {
        "ok": True,
        "months": len(months),
        "wrote": wrote,
        "errors": errors,
        "table_n": int(n or 0),
        "from": mn,
        "to": mx,
        "source": "tpex_trading_index",
        "note_zh": "櫃買指數；Yahoo 無長史改官方月窗",
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--tape-from", default="201701")
    ap.add_argument("--margin-from", default="20230101")
    ap.add_argument("--margin-max-days", type=int, default=400)
    ap.add_argument("--otc-from", default="201001")
    ap.add_argument("--otc-max-months", type=int, default=0)
    ap.add_argument("--skip-tape", action="store_true")
    ap.add_argument("--skip-margin", action="store_true")
    ap.add_argument("--skip-tsmc", action="store_true")
    ap.add_argument("--skip-otc", action="store_true")
    ap.add_argument("--tape-sleep", type=float, default=0.35)
    ap.add_argument("--margin-sleep", type=float, default=0.22)
    ap.add_argument("--otc-sleep", type=float, default=0.18)
    args = ap.parse_args()

    out: Dict[str, Any] = {"written_at": _now(), "tz": "Asia/Taipei"}
    if not args.skip_tape:
        print("… FMTQIK market_tape_daily", flush=True)
        out["tape"] = backfill_market_tape(MARKET_DB, from_ym=args.tape_from, sleep_s=args.tape_sleep)
    if not args.skip_margin:
        print("… MI_MARGN market_margin_daily", flush=True)
        out["margin"] = backfill_market_margin(
            MARKET_DB,
            from_ymd=args.margin_from,
            sleep_s=args.margin_sleep,
            max_days=args.margin_max_days,
        )
    if not args.skip_otc:
        print("… TPEX OTC 櫃買指數 → index_daily", flush=True)
        out["otc"] = backfill_otc_index(
            MARKET_DB,
            from_ym=args.otc_from,
            sleep_s=args.otc_sleep,
            max_months=args.otc_max_months,
        )
    if not args.skip_tsmc:
        print("… Yahoo 2330 → decade_lab.lab_daily", flush=True)
        out["tsmc"] = backfill_tsmc_lab(LAB_DB, range_="10y")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "pulse_backfill_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
