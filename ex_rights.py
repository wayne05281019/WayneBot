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
    """TWT49U／櫃買／TWT48U 的 權/息 只有 權、息、權息。其餘空白，不准發明分割。"""
    s = str(raw or "")
    if "權息" in s or "除權息" in s:
        return "權息"
    if "權" in s:
        return "權"
    if "息" in s:
        return "息"
    return ""


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


def fetch_twse_month(
    session: requests.Session, start: str, end: str, timeout: float = 40
) -> List[Dict[str, Any]]:
    url = (
        "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
        f"?response=json&startDate={start}&endDate={end}"
    )
    resp = session.get(url, timeout=float(timeout or 40))
    resp.raise_for_status()
    payload = resp.json() or {}
    fields = payload.get("fields") or []
    out = []
    for row in payload.get("data") or []:
        item = parse_twse_row(fields, row)
        if item:
            out.append(item)
    return out


def fetch_tpex_month(
    session: requests.Session, start: str, end: str, timeout: float = 40
) -> List[Dict[str, Any]]:
    a = f"{start[:4]}/{start[4:6]}/{start[6:]}"
    b = f"{end[:4]}/{end[4:6]}/{end[6:]}"
    url = (
        "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
        f"?startDate={a}&endDate={b}&response=json"
    )
    resp = session.get(url, timeout=float(timeout or 40))
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


_OFFICIAL_EX_SRC = frozenset({"TWT49U", "tpex_exDailyQ"})


def _is_official_ex_src(src: Any) -> bool:
    return str(src or "") in _OFFICIAL_EX_SRC


def upsert_events(db_path: str, events: List[Dict[str, Any]]) -> int:
    if not events:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    n = 0
    for e in events:
        sid = str(e.get("stock_id") or "")
        ex = str(e.get("ex_date") or "")
        incoming = str(e.get("source") or "")
        if sid and ex:
            old = cur.execute(
                "SELECT source FROM ex_rights WHERE stock_id=? AND ex_date=?",
                (sid, ex),
            ).fetchone()
            if old and _is_official_ex_src(old[0]) and not _is_official_ex_src(incoming):
                continue
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
    """跳空偵測只寫還原因子。kind 參數保留相容，實際固定啟發式。"""
    if not stock_id or len(str(ex_date)) != 8:
        return
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return
    if not (0.05 <= f <= 20):
        return
    try:
        conn = sqlite3.connect(db_path)
        old = conn.execute(
            "SELECT source FROM ex_rights WHERE stock_id=? AND ex_date=?",
            (str(stock_id), str(ex_date)),
        ).fetchone()
        conn.close()
        if old and _is_official_ex_src(old[0]):
            return
    except sqlite3.OperationalError:
        pass
    upsert_events(
        db_path,
        [
            {
                "stock_id": str(stock_id),
                "ex_date": str(ex_date),
                "kind": "啟發式",
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
            """SELECT stock_id, ex_date, stock_name, kind, close_before, ref_price, factor,
                      ifnull(source,'') AS source
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
    if "息" in s and "分割" not in s and "減資" not in s:
        return "除息"
    if "權" in s and "分割" not in s:
        return "除權"
    return ""


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
    if any(x in str(kind or "") for x in ("分割", "減資", "啟發式")):
        return ""
    verb = _event_verb(kind)
    if not verb:
        return ""
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


def event_as_of_day(today: str = "") -> str:
    """週末用上一個工作日當「最近一件」基準，否則週六查 2383 法說會空白。"""
    day = ymd(today) or taipei_today_str()
    try:
        from trading_calendar import is_trading_weekday, last_weekday_on_or_before

        if len(day) == 8 and not is_trading_weekday(day):
            return last_weekday_on_or_before(day)
    except Exception:
        pass
    return day


def nearest_event_label(stock_id: str, db_path: str = None, today: str = "") -> str:
    """股名旁空白處：每檔只寫最近一件官方事件（除權息／法說／股東會）。沒有官方列就空白。"""
    path = db_path or get_db_path()
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    day = event_as_of_day(today)
    try:
        from company_events import ensure_events_loaded

        ensure_events_loaded(path)
    except Exception:
        pass
    cands: List[Tuple[str, str]] = []
    try:
        conn = sqlite3.connect(path)
        try:
            for kind, ex, src in conn.execute(
                """
                SELECT kind, replace(ex_date,'-','') , ifnull(source,'')
                FROM ex_rights
                WHERE stock_id=? AND replace(ex_date,'-','') >= ?
                """,
                (sid, day),
            ):
                if str(src) not in {"TWT49U", "tpex_exDailyQ", "TWT48U"}:
                    continue
                if any(x in str(kind or "") for x in ("分割", "減資", "啟發式")):
                    continue
                if not _event_verb(str(kind or "")):
                    continue
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


OFFICIAL_EX_SRC = frozenset({"TWT49U", "tpex_exDailyQ"})
_GAP_PCT = 0.05
_HYDRATE_HTTP_TIMEOUT = 5.0
_hydrate_month_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}


def bar_ymd(val: Any) -> str:
    return ymd(val)


def scale_ex_verb(kind: Any) -> str:
    s = str(kind or "")
    if "減資" in s:
        return "減資"
    if "分割" in s:
        return "分割"
    if "法說" in s or "股東" in s or "常會" in s or "臨時" in s:
        return ""
    return _event_verb(s)


PHONE_EX_VERBS = frozenset({"除息", "除權", "除權息"})


def phone_ex_verb(kind: Any) -> str:
    """上市櫃／興櫃話筒只寫官方 權／息／權息。沒有分割、沒有減資、沒有啟發式。"""
    s = str(kind or "")
    if any(x in s for x in ("分割", "減資", "啟發式")):
        return ""
    v = scale_ex_verb(s)
    return v if v in PHONE_EX_VERBS else ""


def is_scale_ex(ev: Dict[str, Any]) -> bool:
    return scale_ex_verb((ev or {}).get("kind")) in ("除息", "除權", "除權息", "減資", "分割")


def is_official_ex(ev: Optional[Dict[str, Any]]) -> bool:
    """已發生的除權息只認證交所 TWT49U、櫃買 exDailyQ。"""
    return str((ev or {}).get("source") or "") in OFFICIAL_EX_SRC


def official_scale_events(events: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in events or []:
        if not is_official_ex(e):
            continue
        if not phone_ex_verb((e or {}).get("kind")):
            continue
        out.append(e)
    return out


def _fmt_px(p: Any) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return ""
    av = abs(v)
    if av >= 1000:
        return f"{v:,.0f}"
    if av >= 100:
        s = f"{v:,.1f}"
        return s[:-2] if s.endswith(".0") else s
    s = f"{v:,.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _md_ex(raw: Any) -> str:
    t = bar_ymd(raw)
    if len(t) == 8:
        return f"{int(t[4:6]):02d}/{int(t[6:8]):02d}"
    return str(raw or "").strip()


def _as_bar_rows(work: Any) -> List[Dict[str, Any]]:
    if work is None:
        return []
    if hasattr(work, "empty") and getattr(work, "empty", False):
        return []
    if hasattr(work, "to_dict"):
        return [dict(x) for x in work.to_dict("records")]
    if isinstance(work, (list, tuple)):
        return [dict(x) for x in work if isinstance(x, dict)]
    return []


def load_scale_ex_events(
    stock_id: str,
    db_path: str,
    start: str = "",
    end: str = "",
) -> List[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return []
    try:
        conn = sqlite3.connect(path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT stock_id, ex_date, kind, close_before, ref_price, right_plus_div, source
               FROM ex_rights WHERE stock_id=? AND ex_date>=? AND ex_date<=? AND kind!=''
               ORDER BY ex_date ASC""",
            (sid, start or "19000101", end or "99991231"),
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows if is_scale_ex(dict(r))]


def unexplained_gap_dates(
    work: Any, thresh: float = _GAP_PCT, *, way: str = "any"
) -> List[str]:
    """開盤相對昨收跳超過 thresh。way=any 給補抓官方列；down／up 給圖說文案。"""
    rows = _as_bar_rows(work)
    want = str(way or "any").strip().lower()
    if want not in ("any", "down", "up"):
        want = "any"
    out: List[str] = []
    prev_c = 0.0
    for row in rows:
        op = 0.0
        cl = 0.0
        try:
            op = float(row.get("open") or 0)
            cl = float(row.get("close") or 0)
        except (TypeError, ValueError):
            pass
        if prev_c > 0 and op > 0:
            move = (op - prev_c) / prev_c
            hit = abs(move) >= float(thresh)
            if hit and want == "down":
                hit = move < 0
            elif hit and want == "up":
                hit = move > 0
            if hit:
                d = bar_ymd(row.get("date"))
                if d:
                    out.append(d)
        if cl > 0:
            prev_c = cl
    return out


def close_inside_ex_bar(raw_bars: Any, ex_date: str, close: float) -> bool:
    """收盤還在官方除息／除權當日高低裡（息差帶，不是破底）。"""
    d0 = bar_ymd(ex_date)
    try:
        c = float(close or 0)
    except (TypeError, ValueError):
        c = 0.0
    if not d0 or c <= 0 or raw_bars is None:
        return False
    lo = 0.0
    hi = 0.0
    try:
        if hasattr(raw_bars, "empty"):
            if getattr(raw_bars, "empty", True) or "date" not in getattr(raw_bars, "columns", []):
                return False
            days = raw_bars["date"].astype(str).str.replace("-", "", regex=False)
            hit = raw_bars.loc[days == d0]
            if hit.empty:
                return False
            lo = float(hit["low"].iloc[-1] or 0)
            hi = float(hit["high"].iloc[-1] or 0)
        else:
            for row in _as_bar_rows(raw_bars):
                if bar_ymd(row.get("date")) != d0:
                    continue
                lo = float(row.get("low") or 0)
                hi = float(row.get("high") or 0)
    except (TypeError, ValueError, KeyError):
        return False
    return lo > 0 and hi >= lo and lo * 0.998 <= c <= hi * 1.002


def latest_scale_ex(
    events: Optional[List[Dict[str, Any]]], last_date: str
) -> Optional[Dict[str, Any]]:
    last = bar_ymd(last_date)
    best = None
    best_d = ""
    for ev in events or []:
        if not is_scale_ex(ev):
            continue
        d = bar_ymd(ev.get("ex_date") or ev.get("date"))
        if not (d and last and d <= last):
            continue
        if d > best_d:
            best, best_d = ev, d
            continue
        if d == best_d and str((ev or {}).get("source") or "") in OFFICIAL_EX_SRC:
            best = ev
    return best


def hydrate_official_ex_for_gaps(
    stock_id: str,
    db_path: str,
    work: Any,
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """跳空日還沒官方除權息列（或只剩啟發式）才補抓 TWT49U／櫃買。"""
    if os.getenv("WAYNE_SKIP_EX_FETCH") == "1":
        return events
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    if not sid or not path:
        return events
    official_dates = {
        bar_ymd(e.get("ex_date"))
        for e in events
        if str(e.get("source") or "") in OFFICIAL_EX_SRC
    }
    need = [d for d in unexplained_gap_dates(work) if d not in official_dates]
    if not need:
        return events
    months = sorted({d[:6] for d in need if len(d) == 8})
    try:
        import calendar

        sess = requests.Session()
        sess.headers.update(HEADERS)
        packed: List[Dict[str, Any]] = []
        tout = _HYDRATE_HTTP_TIMEOUT

        def _month(src: str, ym: str, fn) -> List[Dict[str, Any]]:
            key = (src, ym)
            hit = _hydrate_month_cache.get(key)
            if hit is not None:
                return hit
            y, m = int(ym[:4]), int(ym[4:6])
            last = calendar.monthrange(y, m)[1]
            a, b = f"{ym}01", f"{ym}{last:02d}"
            try:
                rows = fn(sess, a, b, timeout=tout)
            except Exception:
                logger.warning("補抓%s除權息 %s 失敗", src, ym)
                return []
            _hydrate_month_cache[key] = rows
            return rows

        for ym in months:
            tw = _month("twse", ym, fetch_twse_month)
            packed.extend(tw)
            if any(str(x.get("stock_id") or "") == sid for x in tw):
                continue
            packed.extend(_month("tpex", ym, fetch_tpex_month))
        mine = [x for x in packed if str(x.get("stock_id") or "") == sid]
        if mine:
            upsert_events(path, mine)
            rows = _as_bar_rows(work)
            start = bar_ymd(rows[0].get("date")) if rows else ""
            end = bar_ymd(rows[-1].get("date")) if rows else ""
            return load_scale_ex_events(sid, path, start, end)
    except Exception:
        logger.warning("補抓除權息略過", exc_info=True)
    return events


def ex_gap_note(
    events: Optional[List[Dict[str, Any]]],
    gaps: Optional[List[str]],
    last_date: str,
    zone_date: str = "",
    *,
    voice: str = "card",
) -> str:
    """官方除權息先講；沒列的大跳空也要講，不准當崩 silently。

    voice=zone：大量區原柱圖。voice=card：介紹圖／高低卡（可能已還原），不准寫原柱／測壓。
    """
    ev = latest_scale_ex(official_scale_events(events), last_date)
    last = bar_ymd(last_date)
    zd = bar_ymd(zone_date)
    zone = str(voice or "card") == "zone"
    if ev:
        d = bar_ymd(ev.get("ex_date"))
        verb = phone_ex_verb(ev.get("kind"))
        if verb and d and (d == zd or d == last or (gaps and d in gaps)):
            md = _md_ex(d)
            amt = 0.0
            before = 0.0
            ref = 0.0
            try:
                amt = float(ev.get("right_plus_div") or 0)
                before = float(ev.get("close_before") or 0)
                ref = float(ev.get("ref_price") or 0)
            except (TypeError, ValueError):
                pass
            bit = f"{md}{verb}"
            if amt > 0:
                bit += f"{_fmt_px(amt)}元"
            if before > 0 and ref > 0:
                bit += f"（前收{_fmt_px(before)}、參考價{_fmt_px(ref)}）"
            if zone:
                return f"{bit}。圖是官方原柱，缺口是息差不是崩。"
            return f"{bit}。缺口是息差不是崩。"
    for d in gaps or []:
        if d:
            extra = "、也不拿來當測壓理由。" if zone else "。"
            return (
                f"{_md_ex(d)}跳空超過五％，庫沒這日官方除權息列，"
                f"缺口先不當崩{extra}"
            )
    return ""


def recent_ex_face(
    stock_id: str,
    db_path: str,
    as_of: str = "",
    bars: Any = None,
    *,
    voice: str = "card",
) -> Dict[str, str]:
    """介紹圖／高低卡：先官方除息除權。回傳 note（圖說）與 label（標題）。"""
    sid = str(stock_id or "").strip()
    path = str(db_path or "").strip()
    last = bar_ymd(as_of) or taipei_today_str()
    rows = _as_bar_rows(bars)
    if rows:
        last = bar_ymd(rows[-1].get("date")) or last
    start = bar_ymd(rows[0].get("date")) if rows else (last[:6] + "01" if len(last) == 8 else "19000101")
    events = load_scale_ex_events(sid, path, start, last) if sid and path else []
    if rows and sid and path:
        events = hydrate_official_ex_for_gaps(sid, path, rows[-5:], events)
    events = official_scale_events(events)
    recent = rows[-5:] if rows else []
    win0 = bar_ymd(recent[0].get("date")) if recent else last
    events_r = [e for e in events if bar_ymd(e.get("ex_date")) >= win0] if win0 else events
    gaps = unexplained_gap_dates(recent, way="down")
    note = ex_gap_note(events_r, gaps, last, last, voice=voice)
    ev = latest_scale_ex(events_r, last)
    label = ""
    if ev and note and _md_ex(ev.get("ex_date")) in note:
        d = bar_ymd(ev.get("ex_date"))
        verb = phone_ex_verb(ev.get("kind"))
        if not verb:
            return {"note": note, "label": "", "ex_date": ""}
        amt = 0.0
        try:
            amt = float(ev.get("right_plus_div") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        label = f"{_md_ex(d)}{verb}"
        if amt > 0:
            label += f"{_fmt_px(amt)}元"
    return {"note": note, "label": label, "ex_date": bar_ymd((ev or {}).get("ex_date")) if label else ""}
