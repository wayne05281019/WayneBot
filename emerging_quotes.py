# -*- coding: utf-8 -*-
"""興櫃獨立行情：櫃買官方當日行情表／日表 CSV，不寫進上市櫃 daily_quotes。

興櫃沒有上市櫃那種集合競價開收盤。官方欄位：
日均價＝close、日最高＝high、日最低＝low、前日均價＝open。
獲利／高低卡用這套官方均價序列，不要用上市櫃日K去硬套。
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import requests

logger = logging.getLogger("WayneBot.Emerging")

OPENAPI_LATEST = "https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics"
CSV_URL = "https://www.tpex.org.tw/www/en-us/emerging/dailyDl?name=EMdes010.{ymd}-E.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,*/*;q=0.8",
}

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS emerging_quotes (
    date TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'EM',
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    turnover_k REAL NOT NULL,
    pct_change REAL NOT NULL,
    avg_price REAL NOT NULL,
    foreign_net INTEGER DEFAULT 0,
    trust_net INTEGER DEFAULT 0,
    dealer_net INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    PRIMARY KEY (date, stock_id)
);
"""


def roc_yyyymmdd(raw: str) -> str:
    """1150907 → 20260907。已是西元八碼就原樣。"""
    s = str(raw or "").strip().replace("/", "").replace("-", "")
    if len(s) == 8 and s.startswith("11"):
        y = int(s[:3]) + 1911
        return f"{y:04d}{s[3:]}"
    if len(s) == 7 and s.isdigit():
        y = int(s[:3]) + 1911
        return f"{y:04d}{s[3:]}"
    return s[:8]


def _f(val) -> float:
    s = str(val or "").replace(",", "").replace("%", "").replace("+", "").strip()
    if s in ("", "-", "n/a", "N/A", "--"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _i(val) -> int:
    return int(round(_f(val)))


def parse_emerging_csv(text: str) -> Tuple[str, List[dict]]:
    """解析櫃買英文日表 CSV。回傳 (YYYYMMDD, rows)。"""
    as_of = ""
    rows: List[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("DATADATE"):
            # DATADATE,Date:2026/09/07
            part = line.split("Date:", 1)[-1].strip().replace("/", "")
            as_of = part[:8]
            continue
        if not line.startswith("BODY,"):
            continue
        payload = line[5:]
        try:
            fields = next(csv.reader(io.StringIO(payload)))
        except Exception:
            continue
        if len(fields) < 13:
            continue
        sid = str(fields[0]).strip()
        name = str(fields[1]).strip()
        avg = _f(fields[4])
        prev = _f(fields[5])
        pct = _f(fields[7])
        high = _f(fields[8])
        low = _f(fields[9])
        last = _f(fields[10])
        shares = _i(fields[11])
        turnover = _f(fields[12])
        if not sid or avg <= 0:
            continue
        if high <= 0:
            high = max(avg, last, prev)
        if low <= 0:
            low = min(x for x in (avg, last, prev, high) if x > 0) if high > 0 else avg
        if low > high:
            low, high = high, low
        open_px = prev if prev > 0 else avg
        rows.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "open": open_px,
                "high": high,
                "low": low,
                "close": avg,
                "volume": max(0, int(round(shares / 1000.0))),
                "turnover_k": round(turnover / 1000.0, 2),
                "pct_change": pct,
                "avg_price": avg,
                "source": "tpex_esb_csv",
            }
        )
    return as_of, rows


def parse_emerging_openapi(items: Iterable[dict]) -> Tuple[str, List[dict]]:
    rows: List[dict] = []
    as_of = ""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        as_of = as_of or roc_yyyymmdd(it.get("Date") or "")
        sid = str(it.get("SecuritiesCompanyCode") or "").strip()
        name = str(it.get("CompanyName") or "").strip()
        avg = _f(it.get("Average"))
        prev = _f(it.get("PreviousAveragePrice"))
        high = _f(it.get("Highest"))
        low = _f(it.get("Lowest"))
        last = _f(it.get("LatestPrice"))
        shares = _i(it.get("TransactionVolume"))
        if not sid or avg <= 0:
            continue
        if high <= 0:
            high = max(avg, last, prev)
        if low <= 0:
            low = min(x for x in (avg, last, prev, high) if x > 0) if high > 0 else avg
        if low > high:
            low, high = high, low
        open_px = prev if prev > 0 else avg
        pct = 0.0
        if prev > 0:
            pct = round((avg - prev) / prev * 100.0, 2)
        turnover = avg * shares
        rows.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "open": open_px,
                "high": high,
                "low": low,
                "close": avg,
                "volume": max(0, int(round(shares / 1000.0))),
                "turnover_k": round(turnover / 1000.0, 2),
                "pct_change": pct,
                "avg_price": avg,
                "source": "tpex_esb_openapi",
            }
        )
    return as_of, rows


def ensure_emerging_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_em_stock_date ON emerging_quotes(stock_id, date);"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_em_date ON emerging_quotes(date);")
        conn.commit()
    finally:
        conn.close()


def upsert_emerging_rows(db_path: str, as_of: str, rows: List[dict]) -> int:
    if not as_of or not rows:
        return 0
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        conn.executemany(
            """
            INSERT INTO emerging_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price,
                foreign_net, trust_net, dealer_net, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?)
            ON CONFLICT(date, stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                turnover_k=excluded.turnover_k,
                pct_change=excluded.pct_change,
                avg_price=excluded.avg_price,
                source=excluded.source;
            """,
            [
                (
                    as_of,
                    r["stock_id"],
                    r["stock_name"],
                    "EM",
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                    r["turnover_k"],
                    r["pct_change"],
                    r["avg_price"],
                    r.get("source") or "",
                )
                for r in rows
            ],
        )
        n = conn.total_changes
        conn.commit()
    finally:
        conn.close()
    return n


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_emerging_csv_day(ymd: str, session: Optional[requests.Session] = None) -> Tuple[str, List[dict]]:
    sess = session or _session()
    url = CSV_URL.format(ymd=ymd)
    resp = sess.get(url, timeout=25)
    if resp.status_code != 200 or not (resp.text or "").lstrip().startswith("TITLE"):
        return "", []
    as_of, rows = parse_emerging_csv(resp.text)
    return as_of or ymd, rows


def fetch_emerging_openapi(session: Optional[requests.Session] = None) -> Tuple[str, List[dict]]:
    sess = session or _session()
    resp = sess.get(OPENAPI_LATEST, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return "", []
    return parse_emerging_openapi(data)


def emerging_date_count(db_path: str) -> int:
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(DISTINCT date) FROM emerging_quotes").fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def sync_emerging_quotes(
    db_path: str,
    *,
    lookback_days: int = 90,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.2,
) -> Dict[str, int]:
    """補齊近 lookback 曆日官方興櫃日表。已有 ≥40 個交易日時只抓最新。"""
    ensure_emerging_table(db_path)
    sess = session or _session()
    stats = {"latest": 0, "hist": 0, "days": 0}
    try:
        as_of, rows = fetch_emerging_openapi(sess)
        if as_of and rows:
            stats["latest"] = upsert_emerging_rows(db_path, as_of, rows)
    except Exception:
        logger.exception("興櫃 OpenAPI 當日行情失敗")
    have = emerging_date_count(db_path)
    if have >= 40:
        stats["days"] = have
        return stats
    today = datetime.utcnow() + timedelta(hours=8)
    for i in range(int(lookback_days)):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        ymd = day.strftime("%Y%m%d")
        conn = sqlite3.connect(db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM emerging_quotes WHERE date=?", (ymd,)
            ).fetchone()[0]
        finally:
            conn.close()
        if int(n or 0) >= 50:
            continue
        try:
            as_of, rows = fetch_emerging_csv_day(ymd, sess)
        except Exception:
            logger.info("興櫃 CSV %s 失敗", ymd)
            continue
        if as_of and rows:
            stats["hist"] += upsert_emerging_rows(db_path, as_of, rows)
            stats["days"] += 1
        time.sleep(max(0.0, float(sleep_s)))
    stats["days"] = emerging_date_count(db_path)
    return stats


def load_stock_bars(db_path: str, stock_id: str, limit: int = 520):
    """單檔興櫃官方日均價序列，欄位對齊 daily_quotes 給決策卡／導航圖用。"""
    import pandas as pd

    sid = str(stock_id or "").strip()
    if not sid:
        return pd.DataFrame()
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT date, stock_name, open, high, low, close, volume, turnover_k,
                   pct_change AS change_pct, pct_change
            FROM emerging_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?
            """,
            conn,
            params=(sid, int(limit)),
        )
    finally:
        conn.close()
    return df


def latest_emerging_date(db_path: str) -> str:
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(date) FROM emerging_quotes").fetchone()
        return str(row[0] or "") if row else ""
    finally:
        conn.close()


def load_emerging_frames(db_path: str, as_of: Optional[str] = None) -> Dict[str, "object"]:
    """給 ScreeningEngine 用的興櫃日K框。法人欄官方沒有，填 0。"""
    import pandas as pd

    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        if not as_of:
            row = conn.execute("SELECT MAX(date) FROM emerging_quotes").fetchone()
            as_of = str(row[0] or "") if row else ""
        if not as_of:
            return {}
        ids = [
            r[0]
            for r in conn.execute(
                """
                SELECT stock_id FROM emerging_quotes
                WHERE date=? AND close>0
                """,
                (as_of,),
            )
        ]
        if not ids:
            return {}
        ph = ",".join("?" * len(ids))
        df = pd.read_sql_query(
            f"""
            SELECT date, stock_id, stock_name, market, open, high, low, close,
                   volume, turnover_k, pct_change, avg_price,
                   foreign_net, trust_net, dealer_net
            FROM emerging_quotes
            WHERE stock_id IN ({ph}) AND date<=?
            ORDER BY stock_id, date
            """,
            conn,
            params=list(ids) + [as_of],
        )
    finally:
        conn.close()
    if df is None or df.empty:
        return {}
    out = {}
    for sid, g in df.groupby("stock_id"):
        if len(g) < 5:
            continue
        out[str(sid)] = g.reset_index(drop=True)
    return out
