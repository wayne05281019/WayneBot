# -*- coding: utf-8 -*-
"""從第一篇讀到最新：每檔股票記下當天官方日 K，缺的去抓，重複的彙整。

底圖是 Drive 那一千七百多則。不進海選、不是買訊。沒官方列就空，不編。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from biaoke_link import (
    MentionGraph,
    bar_on,
    ensure_biaoke_mentions_table,
    link_biaoke_db,
)

logger = logging.getLogger("WayneBot.BiaokeWalk")

_FACTS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_day_facts (
    post_id TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL,
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    claimed TEXT NOT NULL DEFAULT '',
    club INTEGER NOT NULL DEFAULT 0,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    pct_change REAL,
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, stock_id)
);
"""
_FACTS_SID_IX = (
    "CREATE INDEX IF NOT EXISTS idx_biaoke_facts_sid ON biaoke_day_facts(stock_id, post_date);"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.twse.com.tw/zh/trading/historical/stock-day.html",
}
_SKIP_SIDS = frozenset({"TWII", "TX", "TXN", "^TWII"})
_BACKFILL_LOCK = threading.Lock()
_BACKFILL_DDL = """
CREATE TABLE IF NOT EXISTS quote_month_backfill (
    stock_id TEXT NOT NULL,
    yyyymm TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    tries INTEGER NOT NULL DEFAULT 0,
    rows INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (stock_id, yyyymm)
);
"""
_TWSE_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
_TPEX_DAY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
_LEVEL = re.compile(
    r"(支撐|壓力|不跌破|不破|頸線|目標|買點|停損)\s*[：: ]?\s*(\d{2,5}(?:\.\d+)?)"
)
_CHART_URL = re.compile(
    r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
    re.I,
)
_YEAR_NUM = re.compile(r"^(?:19|20)\d{2}$")
_IDX_CTX = re.compile(
    r"(夜盤|台指期|台指|加權|大盤|細微波|穿刺|穿越|觀盤|右肩|下降軌|下降壓|上升軌)"
)
_STOCK_CTX = re.compile(
    r"(台光電|奇鋐|健策|聯亞|南亞科|華邦電|群聯|勤誠|金像電|富喬|金居|"
    r"旺矽|穎崴|台積電|聯發科|智原)"
)
_IDX_NUM = re.compile(r"(?<![\d.])(\d{4,5}(?:\.\d+)?)(?![\d])")
_LEVELS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_level_facts (
    post_id TEXT NOT NULL,
    claimed REAL NOT NULL,
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    charts TEXT NOT NULL DEFAULT '',
    twii_high REAL,
    twii_low REAL,
    twii_close REAL,
    tx_high REAL,
    tx_low REAL,
    tx_close REAL,
    hit TEXT NOT NULL DEFAULT '',
    club INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, claimed)
);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def ensure_biaoke_facts_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_FACTS_DDL)
        conn.execute(_FACTS_SID_IX)
        conn.execute(_LEVELS_DDL)
        for table, col in (
            ("biaoke_day_facts", "club"),
            ("biaoke_level_facts", "club"),
        ):
            cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0"
                )
        conn.commit()
    finally:
        conn.close()


def extract_index_levels(text: str) -> List[Dict[str, Any]]:
    """文內大盤／台指期點位。個股價、年份不進這張表。"""
    blob = str(text or "")
    hits: List[Dict[str, Any]] = []
    seen = set()
    for m in _IDX_NUM.finditer(blob):
        raw = m.group(1)
        whole = raw.split(".")[0]
        if _YEAR_NUM.fullmatch(whole) and "." not in raw:
            continue
        try:
            n = float(raw)
        except ValueError:
            continue
        ctx = blob[max(0, m.start() - 28) : m.end() + 18]
        if n < 15000 and _STOCK_CTX.search(ctx) and not _IDX_CTX.search(ctx):
            continue
        if n < 15000 and not _IDX_CTX.search(blob):
            continue
        if n < 15000 and not _IDX_CTX.search(ctx) and not _IDX_CTX.search(blob):
            continue
        key = round(n, 2)
        if key in seen:
            continue
        seen.add(key)
        if "夜盤" in ctx:
            role = "夜盤"
        elif "台指" in ctx:
            role = "台指"
        elif "加權" in ctx or "大盤" in ctx:
            role = "加權"
        else:
            role = "點位"
        hits.append(
            {
                "level": n,
                "role": role,
                "ctx": re.sub(r"\s+", " ", ctx).strip()[:90],
            }
        )
    return hits


def post_chart_urls(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for url in _CHART_URL.findall(text or ""):
        if "profile/" in url:
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _hit_note(level: float, bar: Optional[Dict[str, Any]], *, label: str) -> str:
    if not bar:
        return ""
    hi = bar.get("high")
    lo = bar.get("low")
    if hi is None or lo is None:
        return ""
    try:
        h, l = float(hi), float(lo)
    except (TypeError, ValueError):
        return ""
    if l <= level <= h:
        return f"{label}當日K碰到"
    if level > h:
        return f"{label}當日高未到"
    return f"{label}當日低已破"


def _px(raw: Any) -> Optional[float]:
    s = str(raw or "").replace(",", "").replace("＋", "+").strip()
    if not s or s in {"--", "---", "X"}:
        return None
    if s[:1] in "Xx":
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def _roc_to_ymd(raw: str) -> str:
    parts = str(raw or "").replace("-", "/").split("/")
    if len(parts) != 3:
        return ""
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return ""
    if y < 1911:
        y += 1911
    return f"{y:04d}{m:02d}{d:02d}"


def _parse_change(raw: str, close: Optional[float]) -> float:
    s = str(raw or "").replace(",", "").replace("＋", "+").strip()
    m = re.search(r"([+\-]?\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    try:
        chg = float(m.group(1))
    except ValueError:
        return 0.0
    if close and abs(close - chg) > 1e-9:
        prev = close - chg
        if prev:
            return round(chg / prev * 100.0, 2)
    return 0.0


def _rows_from_table(
    data: Sequence[Sequence[Any]], *, sid: str, name: str, market: str
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in data or []:
        if not row or len(row) < 7:
            continue
        ymd = _roc_to_ymd(str(row[0]))
        if len(ymd) != 8:
            continue
        o = _px(row[3])
        h = _px(row[4])
        lo = _px(row[5])
        c = _px(row[6])
        if c is None:
            continue
        vol_raw = str(row[1] or "").replace(",", "")
        try:
            shares = float(vol_raw)
        except ValueError:
            shares = 0.0
        vol = int(shares / 1000) if shares >= 1000 else int(shares)
        chg = _parse_change(row[7] if len(row) > 7 else "", c)
        out.append(
            {
                "date": ymd,
                "stock_id": sid,
                "stock_name": name,
                "market": market,
                "open": o if o is not None else c,
                "high": h if h is not None else c,
                "low": lo if lo is not None else c,
                "close": c,
                "volume": vol,
                "pct_change": chg,
            }
        )
    return out


def _fetch_stock_month_once(
    sess: requests.Session,
    sid: str,
    ym: str,
    which: str,
    name: str,
) -> List[Dict[str, Any]]:
    date_s = ym + "01"
    if which == "TW":
        headers = dict(_UA)
        resp = sess.get(
            _TWSE_DAY,
            params={"response": "json", "date": date_s, "stockNo": sid},
            headers=headers,
            timeout=18,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        if str(payload.get("stat") or "") != "OK":
            return []
        title = str(payload.get("title") or "")
        nm = name or (title.split()[2] if len(title.split()) >= 3 else sid)
        return _rows_from_table(
            payload.get("data") or [], sid=sid, name=nm, market="TW"
        )
    headers = dict(_UA)
    headers["Referer"] = (
        "https://www.tpex.org.tw/web/stock/aftertrading/trading_stock_day/st43.php"
    )
    resp = sess.get(
        _TPEX_DAY,
        params={
            "date": f"{int(ym[:4])}/{int(ym[4:6]):02d}/01",
            "code": sid,
            "response": "json",
        },
        headers=headers,
        timeout=18,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    tables = payload.get("tables") or []
    block = tables[0] if tables else payload
    data = (block or {}).get("data") or []
    subtitle = str((block or {}).get("subtitle") or "")
    nm = name or sid
    bits = subtitle.split()
    if len(bits) >= 2:
        nm = bits[1]
    return _rows_from_table(data, sid=sid, name=nm, market="TWO")


def fetch_stock_month(
    sid: str,
    yyyymm: str,
    *,
    market: str = "TW",
    name: str = "",
    session: Optional[requests.Session] = None,
    tries: int = 2,
) -> List[Dict[str, Any]]:
    """證交所／櫃買一個月官方日 K。沒列就空。網路空包會重試，不編。"""
    sid = str(sid or "").strip()
    ym = str(yyyymm or "").replace("-", "")[:6]
    if not sid or len(ym) != 6 or sid in _SKIP_SIDS:
        return []
    sess = session or requests.Session()
    mk = str(market or "TW").upper()
    order = ["TWO", "TW"] if mk in ("TWO", "OTC", "OT", "TPEX") else ["TW", "TWO"]
    n_try = max(1, int(tries or 1))
    for which in order:
        for attempt in range(n_try):
            try:
                rows = _fetch_stock_month_once(sess, sid, ym, which, name)
            except Exception:
                logger.debug(
                    "飆大補日K失敗 sid=%s ym=%s %s try=%s",
                    sid,
                    ym,
                    which,
                    attempt + 1,
                    exc_info=True,
                )
                rows = []
            if rows:
                return rows
            if attempt + 1 < n_try:
                time.sleep(0.6 * (attempt + 1))
    return []


def _market_of(db_path: str, sid: str) -> str:
    if not db_path or not os.path.isfile(db_path):
        return "TW"
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        row = conn.execute(
            "SELECT market_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    raw = str((row or [""])[0] or "").upper()
    if raw in ("TWO", "OTC", "OT", "TPEX"):
        return "TWO"
    return "TW"


def upsert_fetched_quotes(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not db_path or not rows:
        return 0
    from wayne_db import ensure_core_schema

    ensure_core_schema(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    payload = []
    for q in rows:
        sid = str(q.get("stock_id") or "")
        ymd = _ymd(q.get("date"))
        if not sid or not ymd:
            continue
        close = float(q.get("close") or 0)
        payload.append(
            (
                ymd,
                sid,
                str(q.get("stock_name") or sid),
                str(q.get("market") or "TW"),
                float(q.get("open") or close),
                float(q.get("high") or close),
                float(q.get("low") or close),
                close,
                int(q.get("volume") or 0),
                0.0,
                float(q.get("pct_change") or 0),
                close,
                0,
                0,
                0,
                "biaoke_stock_day",
                now,
            )
        )
    if not payload:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT INTO daily_quotes
            (date, stock_id, stock_name, market, open, high, low, close, volume,
             turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net,
             source, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date, stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                pct_change=excluded.pct_change,
                avg_price=excluded.avg_price,
                source=excluded.source,
                fetched_at=excluded.fetched_at;
            """,
            payload,
        )
        conn.commit()
    finally:
        conn.close()
    return len(payload)


def ensure_quote_month_backfill_table(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_BACKFILL_DDL)
        conn.commit()
    finally:
        conn.close()


def _backfill_status_map(db_path: str) -> Dict[Tuple[str, str], str]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        conn.execute(_BACKFILL_DDL)
        rows = conn.execute(
            "SELECT stock_id, yyyymm, status FROM quote_month_backfill"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return {(str(a), str(b)): str(c) for a, b, c in rows}


def enqueue_missing_quote_months(
    db_path: str, posts: Sequence[Dict[str, Any]] | None = None
) -> int:
    """缺月入列。已補成功或官方確認沒列的不再排。"""
    if not db_path:
        return 0
    ensure_quote_month_backfill_table(db_path)
    if posts is None:
        todo: List[Tuple[str, str, str]] = []
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_day_facts'"
            ).fetchone():
                return 0
            rows = conn.execute(
                """
                SELECT stock_id, MAX(stock_name),
                       substr(replace(replace(post_date,'-',''),'/',''),1,6)
                FROM biaoke_day_facts
                WHERE IFNULL(club,0)=0 AND (close IS NULL OR close=0)
                GROUP BY stock_id, substr(replace(replace(post_date,'-',''),'/',''),1,6)
                """
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        for sid, name, ym in rows:
            sid = str(sid or "").strip()
            ym = str(ym or "").replace("-", "")[:6]
            if sid and sid not in _SKIP_SIDS and len(ym) == 6:
                todo.append((sid, ym, str(name or sid)))
    else:
        todo = missing_stock_months(db_path, posts)
    if not todo:
        return 0
    done = _backfill_status_map(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    payload = []
    for sid, ym, name in todo:
        st = done.get((sid, ym), "")
        if st in ("ok", "none"):
            continue
        if st:
            continue
        payload.append((sid, ym, name, "pending", 0, 0, now))
    if not payload:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO quote_month_backfill
            (stock_id, yyyymm, stock_name, status, tries, rows, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            payload,
        )
        conn.commit()
    finally:
        conn.close()
    return len(payload)


def run_quote_month_backfill(
    db_path: str,
    *,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.55,
    limit: int = 40,
    rewalk: bool = True,
    posts: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, int]:
    """每次只補一批，失敗下次再抓。補完重算 facts，週末沒日 K 的維持標缺。"""
    stats = {"months": 0, "rows": 0, "fail": 0, "none": 0, "queued": 0, "pending": 0}
    if not db_path:
        return stats
    with _BACKFILL_LOCK:
        stats["queued"] = enqueue_missing_quote_months(db_path, posts)
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute(_BACKFILL_DDL)
            todo = conn.execute(
                """
                SELECT stock_id, yyyymm, stock_name, tries FROM quote_month_backfill
                WHERE status IN ('pending','fail') AND tries < 5
                ORDER BY yyyymm, stock_id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        sess = session or requests.Session()
        now = datetime.now().isoformat(timespec="seconds")
        for i, (sid, ym, name, tries) in enumerate(todo):
            rows = fetch_stock_month(
                sid,
                ym,
                market=_market_of(db_path, sid),
                name=name,
                session=sess,
                tries=2,
            )
            n = upsert_fetched_quotes(db_path, rows) if rows else 0
            if n:
                status, field = "ok", "months"
                stats["rows"] += n
            else:
                nxt = int(tries or 0) + 1
                status = "none" if nxt >= 5 else "fail"
                field = "none" if status == "none" else "fail"
            stats[field] = int(stats.get(field) or 0) + 1
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute(
                    """
                    UPDATE quote_month_backfill
                    SET status=?, tries=tries+1, rows=?, updated_at=?
                    WHERE stock_id=? AND yyyymm=?
                    """,
                    (status, n, now, sid, ym),
                )
                conn.commit()
            finally:
                conn.close()
            if i + 1 < len(todo):
                time.sleep(max(0.05, float(sleep_s)))
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            stats["pending"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM quote_month_backfill WHERE status IN ('pending','fail')"
                ).fetchone()[0]
                or 0
            )
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        if rewalk and stats["months"]:
            walk_biaoke_posts(db_path, fetch_missing=False)
    logger.info(
        "官方日K缺月補完 months=%s rows=%s fail=%s none=%s pending=%s queued=%s",
        stats["months"],
        stats["rows"],
        stats["fail"],
        stats["none"],
        stats["pending"],
        stats["queued"],
    )
    return stats


def fetch_missing_quotes(
    db_path: str,
    posts: Sequence[Dict[str, Any]],
    *,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.28,
    limit: int = 0,
) -> Dict[str, int]:
    """缺哪一個月就抓哪一個月。已有的不重抓。分批，給開機／抓文續跑。"""
    cap = int(limit) if limit else 80
    return run_quote_month_backfill(
        db_path,
        session=session,
        sleep_s=sleep_s,
        limit=cap,
        rewalk=False,
        posts=posts,
    )


def start_quote_month_backfill(*, delay_s: float = 20.0) -> Optional[threading.Thread]:
    """開機後背景把飆大點名缺月補完。證交所限速，每次 40 個月。"""
    from config import daily_scheduler_enabled, is_once_mode

    if is_once_mode() or not daily_scheduler_enabled():
        return None

    def _loop() -> None:
        time.sleep(max(0.0, float(delay_s)))
        from config import get_db_path

        dbp = get_db_path()
        idle = 0
        while True:
            try:
                got = run_quote_month_backfill(dbp, limit=40, sleep_s=0.55, rewalk=True)
            except Exception:
                logger.exception("官方日K缺月背景補失敗")
                got = {"pending": 1, "months": 0}
            pending = int(got.get("pending") or 0)
            if pending <= 0:
                idle += 1
                time.sleep(1800 if idle > 2 else 300)
                continue
            idle = 0
            time.sleep(25)

    t = threading.Thread(target=_loop, name="quote-month-backfill", daemon=True)
    t.start()
    return t


def _snippet(text: str, name: str) -> str:
    blob = re.sub(r"\s+", " ", str(text or "")).strip()
    if not blob:
        return ""
    key = name or ""
    i = blob.find(key) if key else 0
    if i < 0:
        i = 0
    a = max(0, i - 12)
    return blob[a : a + 120]


def _claimed(text: str) -> str:
    hits = _LEVEL.findall(text or "")
    if not hits:
        return ""
    kind, px = hits[0]
    return f"{kind}{px}"


def _px_s(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _hold_note(claimed: str, bar: Optional[Dict[str, Any]]) -> str:
    if not claimed or not bar:
        return ""
    m = re.search(r"(支撐|不跌破|不破|頸線|壓力|目標|買點|停損)(\d+(?:\.\d+)?)", claimed)
    if not m:
        return ""
    kind, raw = m.group(1), float(m.group(2))
    lo = bar.get("low")
    hi = bar.get("high")
    if kind in ("支撐", "不跌破", "不破", "頸線", "買點", "停損") and lo is not None:
        return "當日低有守" if float(lo) >= raw else "當日低跌破"
    if kind in ("壓力", "目標") and hi is not None:
        return "當日高過到" if float(hi) >= raw else "當日高還沒到"
    return ""


def missing_stock_months(
    db_path: str, posts: Sequence[Dict[str, Any]]
) -> List[Tuple[str, str, str]]:
    """(sid, yyyymm, name) 庫沒有他講那天的日 K。"""
    if not db_path or not os.path.isfile(db_path):
        return []
    need: Dict[Tuple[str, str], str] = {}
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        has_q = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_quotes'"
        ).fetchone()
        for p in posts:
            ymd = _ymd(p.get("date"))
            if not ymd:
                continue
            names = list(p.get("_snames") or [])
            for i, sid in enumerate(p.get("_sids") or []):
                if not sid or sid in _SKIP_SIDS:
                    continue
                row = None
                if has_q:
                    row = conn.execute(
                        "SELECT 1 FROM daily_quotes WHERE stock_id=? AND date=?",
                        (sid, ymd),
                    ).fetchone()
                if row:
                    continue
                name = names[i] if i < len(names) else sid
                need[(sid, ymd[:6])] = str(name or sid)
    finally:
        conn.close()
    return [(sid, ym, name) for (sid, ym), name in sorted(need.items())]


def walk_biaoke_posts(
    db_path: str,
    *,
    fetch_missing: bool = False,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """從 2023-12 第一篇讀到最新。每檔對當天官方日 K，重複的彙整進 biaoke_day_facts。"""
    stats = {
        "posts": 0,
        "facts": 0,
        "with_bar": 0,
        "missing": 0,
        "fetched_months": 0,
        "stocks": 0,
        "levels": 0,
        "charts": 0,
        "club_posts": 0,
        "claims": 0,
        "targets": 0,
    }
    if not db_path:
        return stats
    from biaoke_desk import ensure_biaoke_posts_table, load_corpus

    ensure_biaoke_posts_table(db_path)
    ensure_biaoke_mentions_table(db_path)
    ensure_biaoke_facts_table(db_path)
    try:
        link_biaoke_db(db_path)
    except Exception:
        logger.exception("飆大連線先寫 mentions 失敗")
    blob = load_corpus(db_path)
    posts = list(blob.get("posts") or [])
    g = MentionGraph(posts, db_path=db_path)
    stats["posts"] = sum(1 for p in posts if (p.get("kind") or "post") != "reply")
    if fetch_missing:
        fetched = fetch_missing_quotes(db_path, g.posts, session=session)
        stats["fetched_months"] = int(fetched.get("months") or 0)
    rows: List[Tuple[Any, ...]] = []
    level_rows: List[Tuple[Any, ...]] = []
    with_bar = 0
    missing = 0
    stocks = set()
    n_charts = 0
    tw_cache: Dict[str, Any] = {}
    tx_cache: Dict[str, Any] = {}
    load_tx = None
    try:
        from taiwan_market import load_futures_daily as load_tx
    except Exception:
        load_tx = None
    batches: List[Tuple[List[Dict[str, Any]], int]] = [(list(g.posts), 0)]
    try:
        from biaoke_archive import load_bundled_club

        club_posts = list((load_bundled_club() or {}).get("posts") or [])
    except Exception:
        club_posts = []
    stats["club_posts"] = sum(
        1 for p in club_posts if (p.get("kind") or "post") != "reply"
    )
    if club_posts:
        batches.append((list(MentionGraph(club_posts, db_path=db_path).posts), 1))
    for src_posts, club_flag in batches:
        for p in sorted(
            src_posts,
            key=lambda p: (
                str(p.get("date") or ""),
                str(p.get("time") or ""),
                0 if p.get("kind") != "reply" else 1,
                str(p.get("id") or ""),
            ),
        ):
            aid = str(p.get("id") or "")
            day = str(p.get("date") or "")
            ymd = _ymd(day)
            if not aid or not ymd:
                continue
            text = str(p.get("text") or "")
            claimed = _claimed(text)
            names = list(p.get("_snames") or [])
            charts = post_chart_urls(text)
            n_charts += len(charts)
            for i, sid in enumerate(p.get("_sids") or []):
                if not sid:
                    continue
                name = names[i] if i < len(names) else sid
                stocks.add(sid)
                bar = bar_on(db_path, sid, day)
                if bar:
                    with_bar += 1
                else:
                    missing += 1
                rows.append(
                    (
                        aid,
                        sid,
                        name,
                        day,
                        str(p.get("time") or ""),
                        _snippet(text, name),
                        claimed,
                        bar.get("open") if bar else None,
                        bar.get("high") if bar else None,
                        bar.get("low") if bar else None,
                        bar.get("close") if bar else None,
                        bar.get("volume") if bar else None,
                        bar.get("pct_change") if bar else None,
                        "daily_quotes" if bar else "",
                        int(club_flag),
                    )
                )
            tw = tw_cache.get(day)
            if day not in tw_cache:
                tw = bar_on(db_path, "TWII", day)
                tw_cache[day] = tw
            if day not in tx_cache:
                tx_cache[day] = load_tx(db_path, ymd) if load_tx else None
            tx = tx_cache[day]
            for hit in extract_index_levels(text):
                note = _hit_note(float(hit["level"]), tw, label="加權")
                tx_note = _hit_note(float(hit["level"]), tx, label="台指") if tx else ""
                verdict = "；".join(x for x in (note, tx_note) if x) or "庫沒這天"
                level_rows.append(
                    (
                        aid,
                        float(hit["level"]),
                        day,
                        str(p.get("time") or ""),
                        str(hit.get("role") or ""),
                        str(hit.get("ctx") or ""),
                        " ".join(charts[:4]),
                        tw.get("high") if tw else None,
                        tw.get("low") if tw else None,
                        tw.get("close") if tw else None,
                        tx.get("high") if tx else None,
                        tx.get("low") if tx else None,
                        tx.get("close") if tx else None,
                        verdict,
                        int(club_flag),
                    )
                )
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("DELETE FROM biaoke_day_facts")
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_day_facts
            (post_id, stock_id, stock_name, post_date, post_time, snippet, claimed,
             open, high, low, close, volume, pct_change, source, club)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.execute("DELETE FROM biaoke_level_facts")
        if level_rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO biaoke_level_facts
                (post_id, claimed, post_date, post_time, role, snippet, charts,
                 twii_high, twii_low, twii_close, tx_high, tx_low, tx_close, hit, club)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                level_rows,
            )
        conn.commit()
    finally:
        conn.close()
    try:
        from biaoke_claims import file_biaoke_claims

        filed = file_biaoke_claims(db_path, batches)
        stats["claims"] = int(filed.get("claims") or 0)
        stats["targets"] = int(filed.get("targets") or 0)
    except Exception:
        logger.exception("飆大目標價建檔失敗")
        stats["claims"] = 0
        stats["targets"] = 0
    stats["facts"] = len(rows)
    stats["with_bar"] = with_bar
    stats["missing"] = missing
    stats["stocks"] = len(stocks)
    stats["levels"] = len(level_rows)
    stats["charts"] = n_charts
    logger.info(
        "飆大連續讀 posts=%s club_posts=%s facts=%s with_bar=%s missing=%s stocks=%s levels=%s charts=%s claims=%s targets=%s fetched_months=%s",
        stats["posts"],
        stats["club_posts"],
        stats["facts"],
        stats["with_bar"],
        stats["missing"],
        stats["stocks"],
        stats["levels"],
        stats["charts"],
        stats.get("claims") or 0,
        stats.get("targets") or 0,
        stats["fetched_months"],
    )
    return stats


def stock_timeline(db_path: str, sid: str, *, limit: int = 8) -> Dict[str, Any]:
    """同一檔所有出現日彙整。有官方日 K 才帶收／低。"""
    sid = str(sid or "").strip()
    out: Dict[str, Any] = {
        "stock_id": sid,
        "stock_name": "",
        "n": 0,
        "from": "",
        "to": "",
        "days": [],
    }
    if not db_path or not os.path.isfile(db_path) or not sid:
        return out
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_day_facts'"
        ).fetchone()
        if not hit:
            return out
        rows = conn.execute(
            """
            SELECT post_date, stock_name, snippet, claimed, high, low, close, post_id
            FROM biaoke_day_facts
            WHERE stock_id=? AND IFNULL(club,0)=0
            ORDER BY post_date, post_time, post_id
            """,
            (sid,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    by_day: Dict[str, Dict[str, Any]] = {}
    for day, name, snip, claimed, hi, lo, close, _pid in rows:
        out["stock_name"] = str(name or out["stock_name"])
        rec = by_day.setdefault(
            str(day),
            {
                "date": str(day),
                "n": 0,
                "snippet": "",
                "claimed": "",
                "high": hi,
                "low": lo,
                "close": close,
                "hold": "",
            },
        )
        rec["n"] += 1
        if snip and not rec["snippet"]:
            rec["snippet"] = snip
        if claimed and not rec["claimed"]:
            rec["claimed"] = claimed
        if close is not None:
            rec["high"], rec["low"], rec["close"] = hi, lo, close
        bar = (
            {"high": rec["high"], "low": rec["low"], "close": rec["close"]}
            if rec["close"] is not None
            else None
        )
        rec["hold"] = _hold_note(str(rec.get("claimed") or ""), bar)
    days = list(by_day.values())
    out["n"] = len(days)
    if days:
        out["from"] = days[0]["date"]
        out["to"] = days[-1]["date"]
    if len(days) <= limit:
        out["days"] = days
    else:
        pick = [days[0], days[len(days) // 2], *days[-(limit - 2) :]]
        seen = set()
        uniq = []
        for d in pick:
            if d["date"] in seen:
                continue
            seen.add(d["date"])
            uniq.append(d)
        out["days"] = uniq[:limit]
    return out


def format_stock_walk(db_path: str, sid: str, *, name: str = "") -> str:
    """給對話腦／手機：同一檔連續出現日＋當日官方收。不是買訊。"""
    from tg_layout import html_escape

    tl = stock_timeline(db_path, sid)
    if not tl.get("n"):
        return ""
    nm = html_escape(tl.get("stock_name") or name or sid)
    sid_h = html_escape(sid)
    lines = [
        f"{sid_h} {nm} 公開文寫過 {int(tl['n'])} 天（{html_escape(tl.get('from'))}～{html_escape(tl.get('to'))}）。"
    ]
    for d in tl.get("days") or []:
        bit = html_escape(d.get("date") or "")
        if d.get("close") is not None:
            bit += f" 收 {_px_s(d.get('close'))} 低 {_px_s(d.get('low'))}"
        if d.get("claimed"):
            bit += " " + html_escape(d["claimed"])
        if d.get("hold"):
            bit += " " + html_escape(d["hold"])
        elif d.get("snippet"):
            bit += " " + html_escape(re.sub(r"\s+", " ", d["snippet"])[:40])
        lines.append(bit)
    try:
        from biaoke_claims import format_stock_claims

        extra = format_stock_claims(db_path, sid, name=tl.get("stock_name") or name)
    except Exception:
        extra = ""
    if extra:
        for ln in extra.split("\n"):
            if ln and ln not in lines and ln != "不是買訊。":
                lines.append(ln)
    lines.append("不是買訊。")
    return "\n".join(lines)
