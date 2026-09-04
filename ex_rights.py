"""官方除權息：證交所 TWT49U、櫃買 exDailyQ。寫進同一份 wayne_market.db，決策卡還原用。"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

try:
    from config import get_db_path, taipei_today_str
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

    def taipei_today_str() -> str:
        return datetime.now().strftime("%Y%m%d")

logger = logging.getLogger("WayneBot.ExRights")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


def _num(val) -> float:
    s = str(val if val is not None else "").replace(",", "").strip()
    if s in ("", "-", "--", "－", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def roc_day_to_ymd(raw: str) -> str:
    """115年08月03日 / 115/08/03 → 20260803。"""
    s = str(raw or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 7:
        y, m, d = digits[:3], digits[3:5], digits[5:7]
        return f"{int(y) + 1911}{m}{d}"
    if len(digits) == 8:
        return digits
    return ""


def ymd(val) -> str:
    return str(val or "").replace("-", "").replace("/", "")[:8]


def ensure_ex_rights_table(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ex_rights (
            stock_id TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            kind TEXT DEFAULT '',
            close_before REAL DEFAULT 0,
            ref_price REAL DEFAULT 0,
            right_plus_div REAL DEFAULT 0,
            factor REAL DEFAULT 0,
            source TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (stock_id, ex_date)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_rights_date ON ex_rights(ex_date);")
    conn.commit()
    conn.close()


def _month_windows(start_ymd: str, end_ymd: str) -> List[Tuple[str, str]]:
    y, m = int(start_ymd[:4]), int(start_ymd[4:6])
    ye, me = int(end_ymd[:4]), int(end_ymd[4:6])
    out = []
    while (y, m) <= (ye, me):
        first = f"{y:04d}{m:02d}01"
        if m == 12:
            last = f"{y:04d}1231"
            y, m = y + 1, 1
        else:
            last_d = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
            last = f"{y:04d}{m:02d}{last_d:02d}"
            m += 1
        if last > end_ymd:
            last = end_ymd
        if first < start_ymd:
            first = start_ymd
        out.append((first, last))
    return out


def _kind(raw: str) -> str:
    s = str(raw or "")
    if "權息" in s:
        return "權息"
    if "除權息" in s:
        return "權息"
    if "權" in s:
        return "權"
    if "息" in s:
        return "息"
    return s[:8]


def parse_twse_row(fields: Sequence[str], row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    m = {str(fields[i]): row[i] if i < len(row) else "" for i in range(len(fields))}
    sid = str(m.get("股票代號") or "").strip()
    ex = roc_day_to_ymd(str(m.get("資料日期") or ""))
    if not sid or len(ex) != 8:
        return None
    close_b = _num(m.get("除權息前收盤價"))
    ref = _num(m.get("除權息參考價"))
    factor = (ref / close_b) if close_b > 0 and ref > 0 else 0.0
    return {
        "stock_id": sid,
        "ex_date": ex,
        "stock_name": str(m.get("股票名稱") or "").strip(),
        "market": "TW",
        "kind": _kind(str(m.get("權/息") or "")),
        "close_before": close_b,
        "ref_price": ref,
        "right_plus_div": _num(m.get("權值+息值")),
        "factor": factor,
        "source": "TWT49U",
    }


def parse_tpex_row(fields: Sequence[str], row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    m = {str(fields[i]): row[i] if i < len(row) else "" for i in range(len(fields))}
    sid = str(m.get("代號") or "").strip()
    ex = roc_day_to_ymd(str(m.get("除權息日期") or ""))
    if not sid or len(ex) != 8:
        return None
    close_b = _num(m.get("除權息前收盤價"))
    ref = _num(m.get("除權息參考價"))
    factor = (ref / close_b) if close_b > 0 and ref > 0 else 0.0
    return {
        "stock_id": sid,
        "ex_date": ex,
        "stock_name": str(m.get("名稱") or "").strip(),
        "market": "TWO",
        "kind": _kind(str(m.get("權/息") or "")),
        "close_before": close_b,
        "ref_price": ref,
        "right_plus_div": _num(m.get("權值+息值")),
        "factor": factor,
        "source": "tpex_exDailyQ",
    }


def fetch_twse_month(session: requests.Session, start: str, end: str) -> List[Dict[str, Any]]:
    url = (
        "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
        f"?response=json&startDate={start}&endDate={end}"
    )
    resp = session.get(url, timeout=40)
    resp.raise_for_status()
    payload = resp.json() or {}
    fields = payload.get("fields") or []
    out = []
    for row in payload.get("data") or []:
        item = parse_twse_row(fields, row)
        if item:
            out.append(item)
    return out


def fetch_tpex_month(session: requests.Session, start: str, end: str) -> List[Dict[str, Any]]:
    a = f"{start[:4]}/{start[4:6]}/{start[6:]}"
    b = f"{end[:4]}/{end[4:6]}/{end[6:]}"
    url = (
        "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
        f"?startDate={a}&endDate={b}&response=json"
    )
    resp = session.get(url, timeout=40)
    resp.raise_for_status()
    payload = resp.json() or {}
    tables = payload.get("tables") or []
    if not tables:
        return []
    fields = tables[0].get("fields") or []
    out = []
    for row in tables[0].get("data") or []:
        item = parse_tpex_row(fields, row)
        if item:
            out.append(item)
    return out


def upsert_events(db_path: str, events: List[Dict[str, Any]]) -> int:
    if not events:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    n = 0
    for e in events:
        cur.execute(
            """
            INSERT INTO ex_rights (
                stock_id, ex_date, stock_name, market, kind,
                close_before, ref_price, right_plus_div, factor, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, ex_date) DO UPDATE SET
                stock_name=CASE
                    WHEN excluded.stock_name != '' THEN excluded.stock_name
                    ELSE ex_rights.stock_name END,
                market=CASE
                    WHEN excluded.market != '' THEN excluded.market
                    ELSE ex_rights.market END,
                kind=CASE
                    WHEN excluded.kind != '' THEN excluded.kind
                    ELSE ex_rights.kind END,
                close_before=CASE
                    WHEN excluded.close_before > 0 THEN excluded.close_before
                    ELSE ex_rights.close_before END,
                ref_price=CASE
                    WHEN excluded.ref_price > 0 THEN excluded.ref_price
                    ELSE ex_rights.ref_price END,
                right_plus_div=CASE
                    WHEN excluded.right_plus_div > 0 THEN excluded.right_plus_div
                    ELSE ex_rights.right_plus_div END,
                factor=CASE
                    WHEN excluded.factor > 0 THEN excluded.factor
                    ELSE ex_rights.factor END,
                source=CASE
                    WHEN excluded.factor > 0 THEN excluded.source
                    ELSE COALESCE(NULLIF(ex_rights.source, ''), excluded.source) END,
                updated_at=excluded.updated_at;
            """,
            (
                e["stock_id"], e["ex_date"], e.get("stock_name") or "",
                e.get("market") or "", e.get("kind") or "",
                e.get("close_before") or 0, e.get("ref_price") or 0,
                e.get("right_plus_div") or 0, e.get("factor") or 0,
                e.get("source") or "", now,
            ),
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def sync_ex_rights(db_path: str = None, start: str = None, end: str = None) -> Dict[str, Any]:
    path = db_path or get_db_path()
    ensure_ex_rights_table(path)
    end = ymd(end) or taipei_today_str()
    if not start:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT MIN(replace(date,'-','')) FROM daily_quotes"
        ).fetchone()
        conn.close()
        start = ymd(row[0]) if row and row[0] else "20250101"
    start = ymd(start)
    if len(start) != 8:
        start = "20250101"
    sess = requests.Session()
    sess.headers.update(HEADERS)
    tw_n = two_n = 0
    windows = _month_windows(start, end)
    for i, (a, b) in enumerate(windows):
        try:
            tw = fetch_twse_month(sess, a, b)
            tw_n += upsert_events(path, tw)
        except Exception:
            logger.exception("上市除權息 %s-%s 失敗", a, b)
        try:
            two = fetch_tpex_month(sess, a, b)
            two_n += upsert_events(path, two)
        except Exception:
            logger.exception("上櫃除權息 %s-%s 失敗", a, b)
        if i < len(windows) - 1:
            time.sleep(0.35)
    conn = sqlite3.connect(path)
    total = conn.execute("SELECT COUNT(*) FROM ex_rights").fetchone()[0]
    conn.close()
    logger.info("除權息融合 %s～%s 寫入上市 %s 上櫃 %s，庫內共 %s 筆", start, end, tw_n, two_n, total)
    return {"start": start, "end": end, "tw_upsert": tw_n, "two_upsert": two_n, "total": total}


def upsert_heuristic_event(
    db_path: str,
    stock_id: str,
    ex_date: str,
    factor: float,
    *,
    kind: str = "啟發式",
) -> None:
    """跳空偵測到的減資／分割寫回 ex_rights，下次還原走官方路徑。"""
    if not stock_id or len(str(ex_date)) != 8:
        return
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return
    if not (0.05 <= f <= 20):
        return
    upsert_events(
        db_path,
        [
            {
                "stock_id": str(stock_id),
                "ex_date": str(ex_date),
                "kind": kind,
                "factor": f,
                "source": "heuristic_gap",
            }
        ],
    )


def load_ex_rights(stock_id: str, db_path: str = None) -> List[Dict[str, Any]]:
    path = db_path or get_db_path()
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT stock_id, ex_date, stock_name, kind, close_before, ref_price, factor
               FROM ex_rights WHERE stock_id=? AND factor>0 ORDER BY ex_date ASC""",
            (sid,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _event_verb(kind: str) -> str:
    s = str(kind or "")
    if "法說" in s or "法人說明" in s:
        return "法說"
    if "臨時" in s:
        return "臨時會"
    if "股東" in s or "常會" in s:
        return "股東會"
    mapped = {"息": "除息", "權": "除權", "權息": "除權息"}
    if s in mapped:
        return mapped[s]
    if "權" in s and "息" in s:
        return "除權息"
    if "息" in s:
        return "除息"
    if "權" in s:
        return "除權"
    return "除權息"


def _event_kind_rank(kind: str) -> int:
    """同一天：除權息先於法說，法說先於股東會。"""
    s = str(kind or "")
    if "法說" in s or "法人說明" in s:
        return 1
    if "股東" in s or "常會" in s or "臨時" in s:
        return 2
    return 0


def format_next_event_label(kind: str, ex_date: str, today: str) -> str:
    """每檔只寫一件，例如「3天後除息」。已過的不寫。"""
    d0 = ymd(today)
    d1 = ymd(ex_date)
    if len(d0) != 8 or len(d1) != 8:
        return ""
    try:
        a = datetime.strptime(d0, "%Y%m%d")
        b = datetime.strptime(d1, "%Y%m%d")
    except ValueError:
        return ""
    delta = (b - a).days
    if delta < 0:
        return ""
    verb = _event_verb(kind)
    if delta == 0:
        return f"今日{verb}"
    return f"{delta}天後{verb}"


def parse_twt48u_row(fields: Sequence[str], row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """證交所 TWT48U 除權除息預告。沒有還原因子，只當「最近一件」事件。"""
    m = {str(fields[i]): row[i] if i < len(row) else "" for i in range(len(fields))}
    sid = str(m.get("股票代號") or m.get("代號") or "").strip()
    ex = roc_day_to_ymd(str(m.get("除權除息日期") or m.get("除權息日期") or ""))
    if not sid or len(ex) != 8:
        return None
    kind_raw = str(m.get("除權息") or m.get("權/息") or m.get("權息") or "")
    return {
        "stock_id": sid,
        "ex_date": ex,
        "stock_name": str(m.get("名稱") or m.get("股票名稱") or "").strip(),
        "market": "TW",
        "kind": _kind(kind_raw),
        "close_before": 0.0,
        "ref_price": 0.0,
        "right_plus_div": _num(m.get("權值+息值") or m.get("現金股利")),
        "factor": 0.0,
        "source": "TWT48U",
    }


def fetch_twt48u(session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    url = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json"
    resp = sess.get(url, timeout=40)
    resp.raise_for_status()
    payload = resp.json() or {}
    fields = payload.get("fields") or []
    out = []
    for row in payload.get("data") or []:
        item = parse_twt48u_row(fields, row)
        if item:
            out.append(item)
    return out


def sync_ex_preview(db_path: str = None) -> Dict[str, Any]:
    """盤後寫入即將除權息預告。因子為 0 的列不會覆蓋已有官方還原因子。"""
    path = db_path or get_db_path()
    ensure_ex_rights_table(path)
    try:
        events = fetch_twt48u()
    except Exception:
        logger.exception("TWT48U 除權息預告抓取失敗")
        return {"ok": False, "upsert": 0, "rows": 0}
    n = upsert_events(path, events)
    return {"ok": True, "upsert": n, "rows": len(events)}


def nearest_event_label(stock_id: str, db_path: str = None, today: str = "") -> str:
    """股名旁空白處：每檔只寫最近一件官方事件（除權息／法說／股東會）。沒有官方列就空白。"""
    path = db_path or get_db_path()
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    day = ymd(today) or taipei_today_str()
    cands: List[Tuple[str, str]] = []
    try:
        conn = sqlite3.connect(path)
        try:
            for kind, ex in conn.execute(
                """
                SELECT kind, replace(ex_date,'-','') FROM ex_rights
                WHERE stock_id=? AND replace(ex_date,'-','') >= ?
                """,
                (sid, day),
            ):
                cands.append((str(ex or ""), str(kind or "")))
        except sqlite3.OperationalError:
            pass
        try:
            for ev, kind in conn.execute(
                """
                SELECT event_date, kind FROM company_events
                WHERE stock_id=? AND event_date >= ?
                """,
                (sid, day),
            ):
                cands.append((str(ev or ""), str(kind or "")))
        except sqlite3.OperationalError:
            pass
        conn.close()
    except sqlite3.OperationalError:
        return ""
    cands = [(ymd(d), k) for d, k in cands if len(ymd(d)) == 8]
    if not cands:
        return ""
    cands.sort(key=lambda item: (item[0], _event_kind_rank(item[1])))
    return format_next_event_label(cands[0][1], cands[0][0], day)
