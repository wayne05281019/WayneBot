# ==============================================================================
# 官方 ISIN 標的母體：保留現股／KY／ETF，剔除權證、牛熊、特別股、債券
# ==============================================================================
from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
import unicodedata
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


# 查股代號：2330／0050／00878／00631L／00990A。海選仍不收 ETF。
# 至少四碼：不要把「100 天」這種三位數當代號。
_LOOKUP_TICKER_RE = re.compile(r"^(?:\d{4,6}|[0-9]{4,6}[A-Za-z])$", re.I)


def is_lookup_ticker(query: str) -> bool:
    q = unicodedata.normalize("NFKC", (query or "").strip())
    return bool(_LOOKUP_TICKER_RE.fullmatch(q))


_ETF_KIND_ALIASES = {
    "兩倍槓桿": ("ETF_LEVERAGED",),
    "二倍槓桿": ("ETF_LEVERAGED",),
    "2倍槓桿": ("ETF_LEVERAGED",),
    "兩倍": ("ETF_LEVERAGED",),
    "二倍": ("ETF_LEVERAGED",),
    "2倍": ("ETF_LEVERAGED",),
    "槓桿": ("ETF_LEVERAGED",),
    "槓桿etf": ("ETF_LEVERAGED",),
    "正2etf": ("ETF_LEVERAGED",),
    "反向": ("ETF_INVERSE",),
    "反向etf": ("ETF_INVERSE",),
    "反1": ("ETF_INVERSE",),
    "反1etf": ("ETF_INVERSE",),
    "主動etf": ("ETF_ACTIVE",),
    "主動": ("ETF_ACTIVE",),
    "被動etf": ("ETF_PASSIVE",),
    "被動": ("ETF_PASSIVE",),
    "主被動etf": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主被動": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主動被動etf": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主動被動": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "etf": ("ETF_PASSIVE", "ETF_ACTIVE", "ETF_LEVERAGED", "ETF_INVERSE"),
}


def parse_etf_lookup_kinds(query: str) -> Optional[Tuple[str, ...]]:
    """對話框打「兩倍槓桿／主被動ETF」對到官方分類。代號查詢不走這裡。"""
    q = unicodedata.normalize("NFKC", (query or "").strip())
    q = re.sub(r"[\s\u3000]+", "", q)
    if not q or is_lookup_ticker(q):
        return None
    key = q.replace("槓杆", "槓桿").replace("ＥＴＦ", "ETF").replace("Etf", "ETF")
    key = key.lower()
    return _ETF_KIND_ALIASES.get(key)


def etf_kind_label(kinds) -> str:
    s = {str(k) for k in (kinds or ())}
    if s == {"ETF_LEVERAGED"}:
        return "兩倍槓桿 ETF"
    if s == {"ETF_INVERSE"}:
        return "反向 ETF"
    if s == {"ETF_ACTIVE"}:
        return "主動 ETF"
    if s == {"ETF_PASSIVE"}:
        return "被動 ETF"
    if s == {"ETF_ACTIVE", "ETF_PASSIVE"}:
        return "主動／被動 ETF"
    return "ETF"


ETF_CARD_KIND = {
    "ETF_PASSIVE": "被動",
    "ETF_ACTIVE": "主動",
    "ETF_LEVERAGED": "正2",
    "ETF_INVERSE": "反1",
}


def is_etf_asset(asset_type: str = "", stock_id: str = "", stock_name: str = "") -> bool:
    """查股／圖下鈕用：有 universe.asset_type 就認官方；沒有就用代號規則。"""
    at = str(asset_type or "").strip().upper()
    if at:
        return at.startswith("ETF")
    if stock_id:
        kind, _ok = classify_target(stock_id, stock_name)
        return str(kind).startswith("ETF")
    return False


def etf_card_kind_label(asset_type: str = "", stock_id: str = "", stock_name: str = "") -> str:
    """查股標題旁：被動／主動／正2／反1。不是清單用的長名。"""
    at = str(asset_type or "").strip().upper()
    if not at.startswith("ETF") and stock_id:
        kind, _ok = classify_target(stock_id, stock_name)
        at = str(kind or "").strip().upper()
    return ETF_CARD_KIND.get(at, "")


def card_asset_type(stock_id: str, db_path: str = None) -> str:
    """查股讀母體分類；庫沒列再退回代號規則。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT asset_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
        conn.close()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip().upper()
    except Exception:
        pass
    kind, _ok = classify_target(sid)
    return str(kind or "").strip().upper()


def canonical_lookup_ticker(query: str) -> str:
    """查股用代號：全形轉半形、槓桿／主動後綴大寫。"""
    q = unicodedata.normalize("NFKC", (query or "").strip())
    if not _LOOKUP_TICKER_RE.fullmatch(q):
        return ""
    return q.upper() if q[-1:].isalpha() else q


def default_industry(asset_type: str, industry: str = "") -> str:
    """ISIN 對 ETF 常沒產業欄；空白就標 ETF，避免輪動／產業頁變成未分類。"""
    ind = str(industry or "").strip()
    if ind and ind.lower() not in ("nan", "none"):
        return ind
    if str(asset_type or "").upper().startswith("ETF"):
        return "ETF"
    return ""


def card_industry_label(stock_id: str, db_path: str = None) -> str:
    """查股圖卡用的官方細部產業（公開資訊觀測站產業別）。沒有真值就空字串。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT industry, asset_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    if not row:
        return ""
    return default_industry(row[1] or "", row[0] or "")


def is_tradable(stock_id: str, stock_name: str = "") -> bool:
    _atype, keep = classify_target(stock_id, stock_name)
    return keep


SCREEN_EQUITY_TYPES = frozenset({"STOCK", "KY"})


def is_screen_equity(stock_id: str, stock_name: str = "", asset_type: Optional[str] = None) -> bool:
    """海選／當沖快取只收現股與 KY。ETF（含槓桿、反向、主動）一律排除。

    有 universe.asset_type 就認官方分類；沒有就用代號規則（00／01 開頭＝ETF）。
    """
    at = str(asset_type or "").strip().upper()
    if at:
        return at in SCREEN_EQUITY_TYPES
    kind, ok = classify_target(stock_id, stock_name)
    return bool(ok and kind in SCREEN_EQUITY_TYPES)


def name_or_sid(name: str, sid: str) -> str:
    n = clean_stock_name(name)
    return n if n else sid


def decode_isin_bytes(raw: bytes) -> str:
    """ISIN 頁：utf-8 優先。硬解 cp950 會把 utf-8 的「台積電」解成亂碼。"""
    if not raw:
        return ""
    last = ""
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        last = text
        if "有價證券" in text or "台積電" in text or "國際證券辨識" in text:
            return text
    return last or raw.decode("utf-8", errors="replace")


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
            text = decode_isin_bytes(resp.content or b"")
            rows = _parse_isin_html(text)
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
