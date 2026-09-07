"""籌碼K公開個股頁的細項產業（JSON-LD 麵包屑），不是證交所產業別。

只讀 https://www.cmoney.tw/forum/stock/{代號}，不登入、不解驗證碼。
沒抓到就不畫細項，不准自造。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

logger = logging.getLogger("WayneBot.IndustryFine")

SOURCE = "cmoney_forum"
CACHE_DAYS = 7
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cmoney_fine_industry.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def split_chain(chain: str) -> List[str]:
    return [p.strip() for p in str(chain or "").split("-") if p.strip()]


def parse_cmoney_forum_industry(html: str) -> Optional[Dict[str, Any]]:
    """從籌碼K個股頁 JSON-LD 取出產業分類鏈，例如 電子上游-IC-代工。"""
    raw = str(html or "")
    if not raw:
        return None
    for block in _LD_RE.findall(raw):
        try:
            data = json.loads(block)
        except Exception:
            continue
        nodes: List[Any] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@graph"):
                    nodes.extend(item.get("@graph") or [])
                elif isinstance(item, dict):
                    nodes.append(item)
        elif isinstance(data, dict):
            if data.get("@graph"):
                nodes.extend(data.get("@graph") or [])
            else:
                nodes.append(data)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "BreadcrumbList":
                continue
            chain = ""
            cat_id = ""
            for el in node.get("itemListElement") or []:
                if not isinstance(el, dict):
                    continue
                item = str(el.get("item") or "")
                name = str(el.get("name") or "").strip()
                if "/forum/category/" in item and name:
                    chain = name
                    cat_id = item.rstrip("/").split("/")[-1]
            if chain:
                tags = split_chain(chain)
                if tags:
                    return {
                        "chain": chain,
                        "tags": tags,
                        "cat_id": cat_id,
                        "source": SOURCE,
                    }
    return None


def _create_fine_industry_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fine_industry (
            stock_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            cat_id TEXT DEFAULT '',
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_fine_industry_table(db_path: str) -> None:
    _create_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM stock_fine_industry").fetchone()[0]
    conn.close()
    if int(n or 0) == 0:
        seed_fine_industry_table(db_path)


def seed_fine_industry_table(db_path: str) -> int:
    """空表時灌進已抓好的籌碼K細項，查股不必等全市場現抓。"""
    if not os.path.isfile(SEED_PATH):
        return 0
    try:
        with open(SEED_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return 0
    recs = []
    for sid, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        recs.append(
            {
                "stock_id": str(sid),
                "chain": rec.get("chain") or "",
                "tags": rec.get("tags") or split_chain(rec.get("chain") or ""),
                "cat_id": rec.get("cat_id") or "",
                "source": rec.get("source") or SOURCE,
            }
        )
    return save_fine_industry_many(db_path, recs)


def _row_to_rec(stock_id: str, chain: str, tags: List[str], cat_id: str, source: str) -> Dict[str, Any]:
    return {
        "stock_id": stock_id,
        "chain": chain,
        "tags": list(tags),
        "finest": tags[-1] if tags else "",
        "cat_id": cat_id or "",
        "source": source or SOURCE,
    }


def load_cached_fine_industry(
    db_path: str, stock_ids: Iterable[str], *, max_age_days: int = CACHE_DAYS
) -> Dict[str, Dict[str, Any]]:
    ids = [str(s).strip() for s in stock_ids if str(s).strip()]
    if not ids:
        return {}
    ensure_fine_industry_table(db_path)
    qmarks = ",".join("?" * len(ids))
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        f"SELECT stock_id, chain, tags_json, cat_id, source, fetched_at FROM stock_fine_industry WHERE stock_id IN ({qmarks})",
        ids,
    ).fetchall()
    conn.close()
    cutoff = datetime.now() - timedelta(days=max(1, int(max_age_days)))
    out: Dict[str, Dict[str, Any]] = {}
    for sid, chain, tags_json, cat_id, source, fetched_at in rows:
        try:
            ts = datetime.fromisoformat(str(fetched_at))
        except Exception:
            continue
        if ts < cutoff:
            continue
        try:
            tags = json.loads(tags_json) if tags_json else split_chain(chain)
        except Exception:
            tags = split_chain(chain)
        if not tags:
            continue
        out[str(sid)] = _row_to_rec(str(sid), str(chain), [str(t) for t in tags], str(cat_id or ""), str(source or SOURCE))
    return out


def save_fine_industry(db_path: str, rec: Dict[str, Any]) -> None:
    sid = str(rec.get("stock_id") or "").strip()
    chain = str(rec.get("chain") or "").strip()
    tags = rec.get("tags") or split_chain(chain)
    if not sid or not chain or not tags:
        return
    ensure_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO stock_fine_industry(stock_id, chain, tags_json, cat_id, source, fetched_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(stock_id) DO UPDATE SET
            chain=excluded.chain,
            tags_json=excluded.tags_json,
            cat_id=excluded.cat_id,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        (
            sid,
            chain,
            json.dumps(list(tags), ensure_ascii=False),
            str(rec.get("cat_id") or ""),
            str(rec.get("source") or SOURCE),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def fetch_cmoney_fine_industry(stock_id: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid or len(sid) > 8:
        return None
    try:
        import requests

        url = f"https://www.cmoney.tw/forum/stock/{sid}"
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        parsed = parse_cmoney_forum_industry(resp.text)
        if not parsed:
            return None
        parsed["stock_id"] = sid
        return parsed
    except Exception as exc:
        logger.info("籌碼K細項抓不到 %s：%s", sid, exc)
        return None


def load_or_fetch_fine_industry(
    db_path: str,
    stock_ids: Iterable[str],
    *,
    allow_fetch: bool = False,
    max_fetch: int = 5,
) -> Dict[str, Dict[str, Any]]:
    path = db_path or get_db_path()
    ids = []
    seen = set()
    for s in stock_ids:
        sid = str(s or "").strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    out = load_cached_fine_industry(path, ids)
    if not allow_fetch:
        return out
    fetched = 0
    missing = [sid for sid in ids if sid not in out][: max(0, int(max_fetch))]
    if not missing:
        return out
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workers = min(4, len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_cmoney_fine_industry, sid): sid for sid in missing}
        for fut in as_completed(futs):
            sid = futs[fut]
            fetched += 1
            try:
                rec = fut.result()
            except Exception:
                rec = None
            if not rec:
                continue
            rec["stock_id"] = sid
            save_fine_industry(path, rec)
            out[sid] = _row_to_rec(
                sid, rec["chain"], rec["tags"], rec.get("cat_id") or "", rec.get("source") or SOURCE
            )
    return out


def chip_color(tag: str) -> tuple:
    """不同細項用不同框色。同類（記憶體／代工／LED）同一色系。"""
    t = str(tag or "").strip()
    palettes = {
        "memory": ((92, 52, 8), (242, 176, 64), (255, 236, 200)),
        "foundry": ((8, 72, 78), (64, 214, 196), (220, 255, 248)),
        "design": ((58, 28, 96), (186, 148, 255), (238, 228, 255)),
        "ic": ((16, 48, 112), (96, 168, 255), (220, 236, 255)),
        "upstream": ((42, 54, 72), (148, 168, 188), (226, 232, 240)),
        "led": ((12, 78, 40), (86, 210, 128), (220, 255, 230)),
        "pack": ((86, 32, 60), (230, 138, 186), (255, 230, 244)),
        "pcb": ((72, 48, 16), (214, 164, 82), (255, 232, 200)),
        "other": ((48, 56, 70), (160, 176, 196), (230, 236, 242)),
    }
    if any(k in t for k in ("記憶體", "DRAM", "NAND", "Flash")):
        return palettes["memory"]
    if "代工" in t or "晶圓製造" in t:
        return palettes["foundry"]
    if "LED" in t or "光元件" in t or t.startswith("照明"):
        return palettes["led"]
    if "封測" in t or "封裝" in t or "測試" in t:
        return palettes["pack"]
    if "PCB" in t:
        return palettes["pcb"]
    if "設計" in t or "IP" in t or "ASIC" in t:
        return palettes["design"]
    if t == "IC" or t.startswith("IC-") or t.startswith("IC／"):
        return palettes["ic"]
    if "電子上游" in t or "電子中游" in t or "電子下游" in t:
        return palettes["upstream"]
    h = sum(ord(c) for c in t) % 5
    return list(palettes.values())[h]


def parse_cmoney_category_index(html: str) -> Dict[str, str]:
    """產業總覽頁：C23020 → IC-代工。只作對照，個股細項仍以個股頁麵包屑為準。"""
    out: Dict[str, str] = {}
    for cid, name in re.findall(r'href="/forum/category/(C\d+)"[^>]*>([^<]+)', str(html or "")):
        n = re.sub(r"\s+", "", name)
        if cid and n:
            out[cid] = n
    return out


def active_equity_ids(db_path: str) -> List[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT stock_id FROM stock_universe
        WHERE is_active=1 AND length(stock_id)=4
          AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
        ORDER BY stock_id
        """
    ).fetchall()
    conn.close()
    return [str(r[0]) for r in rows if r and r[0]]


def save_fine_industry_many(db_path: str, recs: List[Dict[str, Any]]) -> int:
    rows = []
    now = datetime.now().isoformat(timespec="seconds")
    for rec in recs:
        sid = str(rec.get("stock_id") or "").strip()
        chain = str(rec.get("chain") or "").strip()
        tags = rec.get("tags") or split_chain(chain)
        if not sid or not chain or not tags:
            continue
        rows.append(
            (
                sid,
                chain,
                json.dumps(list(tags), ensure_ascii=False),
                str(rec.get("cat_id") or ""),
                str(rec.get("source") or SOURCE),
                now,
            )
        )
    if not rows:
        return 0
    _create_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO stock_fine_industry(stock_id, chain, tags_json, cat_id, source, fetched_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(stock_id) DO UPDATE SET
            chain=excluded.chain,
            tags_json=excluded.tags_json,
            cat_id=excluded.cat_id,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def sync_all_fine_industry(
    db_path: str = None,
    *,
    workers: int = 8,
    force: bool = False,
    limit: int = 0,
    ids: Optional[List[str]] = None,
) -> Dict[str, int]:
    """盤後一次抓全市場現股的籌碼K細項。查股只讀庫，不再一檔一檔等。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    path = db_path or get_db_path()
    ensure_fine_industry_table(path)
    want = list(ids) if ids is not None else active_equity_ids(path)
    if limit:
        want = want[: int(limit)]
    cached = {} if force else load_cached_fine_industry(path, want)
    missing = [sid for sid in want if sid not in cached]
    stats = {
        "total": len(want),
        "skip": len(want) - len(missing),
        "ok": 0,
        "fail": 0,
    }
    if not missing:
        return stats
    n_workers = max(1, min(int(workers or 8), 12))
    buf: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {pool.submit(fetch_cmoney_fine_industry, sid): sid for sid in missing}
        for fut in as_completed(futs):
            sid = futs[fut]
            rec = None
            try:
                rec = fut.result()
            except Exception:
                rec = None
            if not rec:
                stats["fail"] += 1
                continue
            rec["stock_id"] = sid
            buf.append(rec)
            stats["ok"] += 1
            if len(buf) >= 40:
                save_fine_industry_many(path, buf)
                buf = []
    if buf:
        save_fine_industry_many(path, buf)
    logger.info("籌碼K細項全市場同步：%s", stats)
    return stats

