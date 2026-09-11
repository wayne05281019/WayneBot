# -*- coding: utf-8 -*-
"""從第一篇讀到最新：每檔股票記下當天官方日 K，缺的去抓，重複的彙整。

底圖是 Drive 那一千七百多則。不進海選、不是買訊。沒官方列就空，不編。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
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
}
_TWSE_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
_TPEX_DAY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
_LEVEL = re.compile(
    r"(支撐|壓力|不跌破|不破|頸線|目標|買點|停損)\s*[：: ]?\s*(\d{2,5}(?:\.\d+)?)"
)


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
        conn.commit()
    finally:
        conn.close()


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


def fetch_stock_month(
    sid: str,
    yyyymm: str,
    *,
    market: str = "TW",
    name: str = "",
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """證交所／櫃買一個月官方日 K。沒列就空。"""
    sid = str(sid or "").strip()
    ym = str(yyyymm or "").replace("-", "")[:6]
    if not sid or len(ym) != 6:
        return []
    sess = session or requests.Session()
    date_s = ym + "01"
    mk = str(market or "TW").upper()
    order = ["TWO", "TW"] if mk in ("TWO", "OTC", "OT", "TPEX") else ["TW", "TWO"]
    for which in order:
        try:
            if which == "TW":
                resp = sess.get(
                    _TWSE_DAY,
                    params={"response": "json", "date": date_s, "stockNo": sid},
                    headers=_UA,
                    timeout=18,
                )
                resp.raise_for_status()
                payload = resp.json() or {}
                if str(payload.get("stat") or "") != "OK":
                    continue
                title = str(payload.get("title") or "")
                nm = name or (title.split()[2] if len(title.split()) >= 3 else sid)
                rows = _rows_from_table(
                    payload.get("data") or [], sid=sid, name=nm, market="TW"
                )
            else:
                resp = sess.get(
                    _TPEX_DAY,
                    params={
                        "date": f"{int(ym[:4])}/{int(ym[4:6]):02d}/01",
                        "code": sid,
                        "response": "json",
                    },
                    headers=_UA,
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
                rows = _rows_from_table(data, sid=sid, name=nm, market="TWO")
        except Exception:
            logger.debug("飆大補日K失敗 sid=%s ym=%s %s", sid, ym, which, exc_info=True)
            continue
        if rows:
            return rows
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
        for p in posts:
            ymd = _ymd(p.get("date"))
            if not ymd:
                continue
            names = list(p.get("_snames") or [])
            for i, sid in enumerate(p.get("_sids") or []):
                if not sid:
                    continue
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


def fetch_missing_quotes(
    db_path: str,
    posts: Sequence[Dict[str, Any]],
    *,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.28,
    limit: int = 0,
) -> Dict[str, int]:
    """缺哪一個月就抓哪一個月。已有的不重抓。"""
    todo = missing_stock_months(db_path, posts)
    if limit:
        todo = todo[: int(limit)]
    stats = {"months": 0, "rows": 0, "fail": 0}
    sess = session or requests.Session()
    for i, (sid, ym, name) in enumerate(todo):
        rows = fetch_stock_month(
            sid, ym, market=_market_of(db_path, sid), name=name, session=sess
        )
        if rows:
            stats["rows"] += upsert_fetched_quotes(db_path, rows)
            stats["months"] += 1
        else:
            stats["fail"] += 1
        if i + 1 < len(todo):
            time.sleep(max(0.05, float(sleep_s)))
    logger.info(
        "飆大補日K months=%s rows=%s fail=%s",
        stats["months"],
        stats["rows"],
        stats["fail"],
    )
    return stats


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
    with_bar = 0
    missing = 0
    stocks = set()
    for p in sorted(
        g.posts,
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
                    None,
                    bar.get("high") if bar else None,
                    bar.get("low") if bar else None,
                    bar.get("close") if bar else None,
                    None,
                    None,
                    "daily_quotes" if bar else "",
                )
            )
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("DELETE FROM biaoke_day_facts")
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_day_facts
            (post_id, stock_id, stock_name, post_date, post_time, snippet, claimed,
             open, high, low, close, volume, pct_change, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    stats["facts"] = len(rows)
    stats["with_bar"] = with_bar
    stats["missing"] = missing
    stats["stocks"] = len(stocks)
    logger.info(
        "飆大連續讀 posts=%s facts=%s with_bar=%s missing=%s stocks=%s fetched_months=%s",
        stats["posts"],
        stats["facts"],
        stats["with_bar"],
        stats["missing"],
        stats["stocks"],
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
            WHERE stock_id=?
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
    lines.append("不是買訊。")
    return "\n".join(lines)
