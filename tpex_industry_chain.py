"""櫃買產業價值鏈（ic.tpex.org.tw）細項。

只收非「其他」節點。籌碼K 最細標若是其他／其他業，才用這份蓋過去。
不准把 X400「其他」174 家當同業。盤中不現抓；seed 檔進庫。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("WayneBot.TpexIndustry")

SOURCE = "tpex_ic"
SEED_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "tpex_industry_chain.json"
)
CATCHALL_LABELS = frozenset({"其他", "其他業"})
_OVERLAID: set = set()


def is_catchall_label(name: str) -> bool:
    s = str(name or "").strip()
    if not s:
        return True
    if s in CATCHALL_LABELS:
        return True
    return s.startswith("其他")


def load_tpex_seed() -> Dict[str, Dict[str, Any]]:
    if not os.path.isfile(SEED_PATH):
        return {}
    try:
        with open(SEED_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for sid, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        chain = str(rec.get("chain") or "").strip()
        tags = [str(t).strip() for t in list(rec.get("tags") or []) if str(t).strip()]
        if not tags:
            tags = [p for p in chain.split("-") if p]
        finest = tags[-1] if tags else ""
        if not chain or is_catchall_label(finest):
            continue
        out[str(sid).strip()] = {
            "stock_id": str(sid).strip(),
            "chain": chain,
            "tags": tags,
            "finest": finest,
            "cat_id": str(rec.get("ic") or ""),
            "source": SOURCE,
        }
    return out


def apply_tpex_overlay(
    db_path: str, ids: Optional[Iterable[str]] = None, *, force: bool = False
) -> Dict[str, int]:
    """只蓋籌碼K「其他」或還沒產業鏈的檔。已有水泥／代工／散熱零組件這種真分類不改。

    開機／ensure 會跑；同一行程同一顆庫只寫一次，查股不會每次重灌。
    庫裡已有列優先；沒列才補 universe 現股（興櫃測庫沒灌 overlay 時仍走證交所備援）。
    """
    from industry_fine import save_fine_industry_many, split_chain

    path = str(db_path or "")
    stats = {"seed": 0, "write": 0, "keep": 0}
    seed = load_tpex_seed()
    stats["seed"] = len(seed)
    if not path or not seed:
        return stats
    key = os.path.abspath(path)
    if not force and ids is None and key in _OVERLAID:
        stats["skip"] = 1
        return stats
    want = [str(s).strip() for s in (ids or seed.keys()) if str(s).strip()]
    conn = sqlite3.connect(path)
    try:
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
        rows = conn.execute(
            "SELECT stock_id, chain, tags_json FROM stock_fine_industry"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return stats
    current = {}
    for sid, chain, tags_json in rows:
        try:
            tags = json.loads(tags_json) if tags_json else split_chain(chain)
        except Exception:
            tags = split_chain(chain)
        current[str(sid)] = str(tags[-1] if tags else "")
    live = set(current)
    try:
        for (sid,) in conn.execute(
            """
            SELECT stock_id FROM stock_universe
            WHERE is_active=1 AND length(stock_id)=4
              AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
            """
        ):
            live.add(str(sid))
    except sqlite3.Error:
        pass
    conn.close()
    buf: List[Dict[str, Any]] = []
    for sid, rec in seed.items():
        if ids is not None and sid not in set(want):
            continue
        if sid not in live:
            continue
        cur_fine = str(current.get(sid) or "")
        if cur_fine and not is_catchall_label(cur_fine):
            stats["keep"] += 1
            continue
        buf.append(rec)
    if buf:
        save_fine_industry_many(path, buf)
        stats["write"] = len(buf)
    if ids is None:
        _OVERLAID.add(key)
    logger.info("櫃買產業鏈 overlay：%s", stats)
    return stats
