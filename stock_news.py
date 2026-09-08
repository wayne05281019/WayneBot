# -*- coding: utf-8 -*-
"""近幾日公開報導則數：Google 新聞 RSS 實數，沒抓到就不顯示。

這不是買賣訊、不進海選桶。則數變多只代表媒體在寫，點進去自己讀。
"""
from __future__ import annotations

import logging
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger("WayneBot.News")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
}
TAIPEI = timezone(timedelta(hours=8))
CACHE_TTL_S = 6 * 3600
WINDOW_DAYS = 7

_DDL = """
CREATE TABLE IF NOT EXISTS stock_news_stats (
    stock_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    recent_n INTEGER NOT NULL,
    prev_n INTEGER NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (stock_id)
);
"""


def news_search_url(stock_id: str, stock_name: str = "") -> str:
    q = quote(f"{str(stock_id or '').strip()} {str(stock_name or '').strip()}".strip())
    return f"https://news.google.com/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


def rss_url(stock_id: str, stock_name: str = "") -> str:
    q = quote(f"{str(stock_id or '').strip()} {str(stock_name or '').strip()}".strip())
    return f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


def parse_rss_pubdates(xml_text: str) -> list[datetime]:
    out: list[datetime] = []
    raw = (xml_text or "").strip()
    if not raw:
        return out
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for item in root.findall(".//item"):
        pub = (item.findtext("pubDate") or "").strip()
        if not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
        except (TypeError, ValueError, OverflowError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append(dt.astimezone(TAIPEI))
    return out


def count_windows(dates: list[datetime], *, now: Optional[datetime] = None) -> tuple[int, int]:
    now = now or datetime.now(TAIPEI)
    recent_from = now - timedelta(days=WINDOW_DAYS)
    prev_from = now - timedelta(days=WINDOW_DAYS * 2)
    recent = sum(1 for d in dates if recent_from <= d <= now)
    prev = sum(1 for d in dates if prev_from <= d < recent_from)
    return recent, prev


def news_label(recent_n: int, prev_n: int) -> str:
    n = int(recent_n or 0)
    if n <= 0:
        return ""
    arrow = ""
    if prev_n <= 0 and n >= 3:
        arrow = "↑"
    elif prev_n > 0 and n >= prev_n + 3:
        arrow = "↑"
    elif prev_n > 0 and n <= max(0, prev_n - 3):
        arrow = "↓"
    return f"報導{n}{arrow}"


def ensure_news_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def _cache_get(db_path: str, stock_id: str) -> Optional[Dict[str, Any]]:
    ensure_news_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fetched_at, recent_n, prev_n, url FROM stock_news_stats WHERE stock_id=?",
            (stock_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(str(row[0]))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=TAIPEI)
    except ValueError:
        return None
    if datetime.now(TAIPEI) - fetched > timedelta(seconds=CACHE_TTL_S):
        return None
    recent_n, prev_n = int(row[1] or 0), int(row[2] or 0)
    label = news_label(recent_n, prev_n)
    if not label:
        return None
    return {
        "recent_n": recent_n,
        "prev_n": prev_n,
        "url": str(row[3] or ""),
        "label": label,
    }


def _cache_put(db_path: str, stock_id: str, recent_n: int, prev_n: int, url: str) -> None:
    ensure_news_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO stock_news_stats(stock_id, fetched_at, recent_n, prev_n, url)
            VALUES (?,?,?,?,?)
            ON CONFLICT(stock_id) DO UPDATE SET
                fetched_at=excluded.fetched_at,
                recent_n=excluded.recent_n,
                prev_n=excluded.prev_n,
                url=excluded.url;
            """,
            (
                stock_id,
                datetime.now(TAIPEI).isoformat(timespec="seconds"),
                int(recent_n),
                int(prev_n),
                url,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_rss_text(url: str, timeout: float = 4.0) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_stock_news_stats(
    db_path: str,
    stock_id: str,
    stock_name: str = "",
    *,
    allow_fetch: bool = True,
) -> Optional[Dict[str, Any]]:
    """回傳 {recent_n, prev_n, url, label}；沒有真數就 None。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    cached = _cache_get(db_path, sid)
    if cached:
        return cached
    if not allow_fetch:
        return None
    name = str(stock_name or "").strip()
    url = news_search_url(sid, name)
    try:
        xml_text = fetch_rss_text(rss_url(sid, name))
    except Exception:
        logger.info("Google 新聞 RSS 略過 %s", sid)
        return None
    dates = parse_rss_pubdates(xml_text)
    if not dates:
        return None
    recent_n, prev_n = count_windows(dates)
    if recent_n <= 0:
        return None
    _cache_put(db_path, sid, recent_n, prev_n, url)
    label = news_label(recent_n, prev_n)
    if not label:
        return None
    return {"recent_n": recent_n, "prev_n": prev_n, "url": url, "label": label}
