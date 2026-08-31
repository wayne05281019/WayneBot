# ==============================================================================
# 官方 ISIN 標的母體：保留現股／KY／ETF，剔除權證、牛熊、特別股、債券
# ==============================================================================
from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

logger = logging.getLogger("WayneBot.Universe")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

EXCLUDE_NAME_TOKENS = (
    "權證", "認購", "認售", "牛證", "熊證", "展權",
    "特別股", "甲特", "乙特",
    "債券", "公司債", "可轉債", "轉換公司債", "次順位",
    "附認股權",
)

WARRANT_CODE = re.compile(r"^(0[3-8]\d{4}|7\d{5}|\d{4,6}[PQCFX])$", re.I)
DIRTY_NAME = re.compile(r"^\[|<p\s|style=", re.I)


def clean_stock_name(name: str) -> str:
    s = str(name or "").replace("\u3000", " ").strip()
    if DIRTY_NAME.search(s) or s.startswith("['"):
        return ""
    return s


def classify_target(stock_id: str, stock_name: str = "") -> Tuple[str, bool]:
    sid = str(stock_id or "").strip().upper()
    name = clean_stock_name(stock_name)

    if not sid or len(sid) < 4:
        return "INVALID", False
    if sid in ("TWA00", "TWO00", "TWII"):
        return "INDEX", True
    if any(tok in name for tok in EXCLUDE_NAME_TOKENS):
        return "JUNK", False
    if "牛" in name and "證" in name:
        return "JUNK", False
    if "熊" in name and "證" in name:
        return "JUNK", False
    if WARRANT_CODE.match(sid):
        return "WARRANT", False
    if sid[-1] == "B" and sid[0].isdigit():
        return "BOND", False
    if sid[-1] in ("C", "D", "E") and len(sid) == 5 and not sid.startswith("00"):
        return "PREFERRED", False
    if "KY" in name or sid.endswith("KY"):
        if len(sid) == 4 and sid.isdigit():
            return "KY", True
        if sid.endswith("KY") and sid[:4].isdigit():
            return "KY", True
    if sid.startswith("00") or sid.startswith("01"):
        if sid.endswith("L"):
            return "ETF_LEVERAGED", True
        if sid.endswith("R"):
            return "ETF_INVERSE", True
        if sid[-1].isalpha():
            return "ETF_ACTIVE", True
        return "ETF_PASSIVE", True
    if len(sid) == 4 and sid.isdigit():
        return "STOCK", True
    return "OTHER", False


def default_industry(asset_type: str, industry: str = "") -> str:
    """ISIN 對 ETF 常沒產業欄；空白就標 ETF，避免輪動／產業頁變成未分類。"""
    ind = str(industry or "").strip()
    if ind and ind.lower() not in ("nan", "none"):
        return ind
    if str(asset_type or "").upper().startswith("ETF"):
        return "ETF"
    return ""


def is_tradable(stock_id: str, stock_name: str = "") -> bool:
    _atype, keep = classify_target(stock_id, stock_name)
    return keep


def name_or_sid(name: str, sid: str) -> str:
    n = clean_stock_name(name)
    return n if n else sid


def _parse_isin_html(html: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    try:
        import pandas as pd
        dfs = pd.read_html(io.StringIO(html))
        if dfs:
            df = dfs[0]
            for i in range(len(df)):
                raw0 = str(df.iloc[i, 0]).strip()
                industry = ""
                if df.shape[1] > 4:
                    industry = str(df.iloc[i, 4]).strip()
                    if industry in ("nan", "None"):
                        industry = ""
                m = re.match(r"^([0-9A-Za-z]{4,8})[\s\u3000\xa0\t]+(.+)$", raw0)
                if not m:
                    continue
                rows.append((m.group(1).strip(), m.group(2).strip(), industry))
            if rows:
                return rows
    except Exception as e:
        logger.info("pandas.read_html 失敗，改用 regex：%s", e)

    pattern = re.compile(r">([0-9A-Za-z]{4,8})[\s\u3000]+([^<]{1,40})<", re.U)
    for m in pattern.finditer(html):
        rows.append((m.group(1).strip(), m.group(2).strip(), ""))
    return rows


def fetch_isin_universe() -> List[Dict]:
    universe: List[Dict] = []
    urls = [
        ("TW", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"),
        ("TWO", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"),
        ("EM", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=5"),
    ]
    session = requests.Session()
    session.headers.update(HEADERS)
    for market, url in urls:
        try:
            resp = session.get(url, timeout=25)
            resp.encoding = "cp950"
            rows = _parse_isin_html(resp.text)
            for sid, sname, industry in rows:
                atype, keep = classify_target(sid, sname)
                if not keep:
                    continue
                universe.append({
                    "stock_id": sid,
                    "stock_name": name_or_sid(sname, sid),
                    "market_type": market,
                    "asset_type": atype,
                    "industry": industry or "",
                    "is_active": 1,
                })
            logger.info("ISIN %s 解析保留 %s 檔", market, sum(1 for u in universe if u["market_type"] == market))
        except Exception as e:
            logger.warning("ISIN %s 擷取失敗: %s", market, e)
    seen = {}
    for u in universe:
        seen[u["stock_id"]] = u
    return list(seen.values())


def ensure_universe_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_universe (
        stock_id TEXT PRIMARY KEY,
        stock_name TEXT NOT NULL,
        market_type TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        industry TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def sync_universe(db_path: str = None, items: Optional[List[Dict]] = None) -> Dict[str, int]:
    path = db_path or get_db_path()
    ensure_universe_table(path)
    items = items if items is not None else fetch_isin_universe()
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("UPDATE stock_universe SET is_active = 0;")
    rows = [
        (
            u["stock_id"],
            u["stock_name"],
            u["market_type"],
            u["asset_type"],
            default_industry(u.get("asset_type") or "", u.get("industry") or ""),
            now,
        )
        for u in items
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO stock_universe (stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                market_type=excluded.market_type,
                asset_type=excluded.asset_type,
                industry=excluded.industry,
                is_active=1,
                updated_at=excluded.updated_at;
            """,
            rows,
        )
    conn.commit()
    active_n = cur.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active=1").fetchone()[0]
    cur.execute("""
    UPDATE daily_quotes
    SET stock_name = (
        SELECT u.stock_name FROM stock_universe u
        WHERE u.stock_id = daily_quotes.stock_id AND u.is_active = 1
    )
    WHERE EXISTS (
        SELECT 1 FROM stock_universe u
        WHERE u.stock_id = daily_quotes.stock_id AND u.is_active = 1
    );
    """)
    all_ids = [r[0] for r in cur.execute("SELECT DISTINCT stock_id FROM daily_quotes")]
    deleted = 0
    active = {r[0] for r in cur.execute("SELECT stock_id FROM stock_universe WHERE is_active=1")}
    for sid in all_ids:
        if sid in active:
            continue
        row = cur.execute("SELECT stock_name FROM daily_quotes WHERE stock_id=? LIMIT 1", (sid,)).fetchone()
        name = row[0] if row else ""
        _atype, keep = classify_target(sid, name)
        if keep:
            continue
        cur.execute("DELETE FROM daily_quotes WHERE stock_id = ?", (sid,))
        deleted += cur.rowcount
        try:
            cur.execute("DELETE FROM technical_indicators WHERE stock_id = ?", (sid,))
        except sqlite3.OperationalError:
            pass
    filled = 0
    try:
        cur.execute(
            """
            UPDATE stock_universe
            SET industry = (
                SELECT m.industry FROM monthly_revenue m
                WHERE m.stock_id = stock_universe.stock_id
                  AND TRIM(COALESCE(m.industry,'')) != ''
                LIMIT 1
            )
            WHERE TRIM(COALESCE(industry,'')) = ''
              AND EXISTS (
                SELECT 1 FROM monthly_revenue m
                WHERE m.stock_id = stock_universe.stock_id
                  AND TRIM(COALESCE(m.industry,'')) != ''
              );
            """
        )
        filled = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    except sqlite3.OperationalError:
        filled = 0
    conn.commit()
    stats = {
        "universe": len(items),
        "active": active_n,
        "quotes_ids": len(all_ids),
        "deleted_junk_rows": deleted,
        "industry_from_monthly": filled,
    }
    conn.close()
    logger.info("母體同步完成 %s", stats)
    return stats


def get_active_ids(db_path: str = None) -> set:
    path = db_path or get_db_path()
    ensure_universe_table(path)
    conn = sqlite3.connect(path)
    ids = {r[0] for r in conn.execute("SELECT stock_id FROM stock_universe WHERE is_active=1")}
    conn.close()
    return ids


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print("同步母體 →", path)
    print(sync_universe(path))
