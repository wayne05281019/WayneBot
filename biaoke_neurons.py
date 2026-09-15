# -*- coding: utf-8 -*-
"""新文／自回進庫當下分進六顆神經元。開火只讀最近一句。

不是 CNN。不准等 Cursor 改 SYSTEM。路人引號不收。IET＝IET-KY 4971。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

NEURON_IDS = ("nest", "field", "leader", "tape", "hold", "doubt")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_neuron_hits (
    post_id TEXT NOT NULL,
    neuron_id TEXT NOT NULL,
    stock_id TEXT NOT NULL DEFAULT '',
    stock_name TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, neuron_id, stock_id)
);
CREATE INDEX IF NOT EXISTS idx_biaoke_neuron_hits_nid
    ON biaoke_neuron_hits(neuron_id, post_date, post_time);
"""

_PAT: Dict[str, re.Pattern[str]] = {
    "nest": re.compile(
        r"(逃命波|C-2|C-3|C-1|位階二|右肩|修正末端|第五波測底|頭肩底|"
        r"細微波|加權|大盤|夜盤|43500|45839|47578|46506|確認末端)"
    ),
    "field": re.compile(
        r"(產業|主戰場|CCL|InP|散熱|光通訊|光學|PCB|F10|ABF|記憶體|"
        r"下飄旗|矽光子|高階測試)"
    ),
    "leader": re.compile(r"(龍頭|護城河|次族群|一軍|二軍|風向球|第一名)"),
    "tape": re.compile(r"(破撐|跌破支撐|站回|洗盤|爆量|量縮|破線|支撐區|出貨)"),
    "hold": re.compile(r"(長抱|調節|抽出|出清|勿輕易|可抱到|先賣|不用管)"),
    "doubt": re.compile(
        r"(不是已確認|言之過早|無法判斷|模糊|證據不足|不能保證|"
        r"點到為止|還沒改口)"
    ),
}
_SPACE = re.compile(r"\s+")


def ensure_neuron_hits_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "").strip()


def _snip(text: str, needle: str, n: int = 96) -> str:
    blob = _SPACE.sub(" ", text or "").strip()
    if not blob:
        return ""
    i = blob.find(needle) if needle else -1
    if i < 0:
        return blob[:n]
    a = max(0, i - 8)
    return blob[a : a + n]


def classify_spoken(text: str, tags: Optional[Sequence[Any]] = None) -> List[Dict[str, str]]:
    """一句他的話 → 進哪幾顆、點了哪幾檔。沒點檔的產業／大盤 sid 空白。"""
    spoken = _spoken(text)
    if not spoken:
        return []
    hit_nids = [nid for nid, pat in _PAT.items() if pat.search(spoken)]
    if not hit_nids:
        return []
    try:
        from biaoke_tape import named_pairs

        pairs = named_pairs(text, tags)
    except Exception:
        pairs = []
    stocks = [(str(s), str(n)) for s, n in pairs if str(s) and str(s) != "TWII"]
    out: List[Dict[str, str]] = []
    seen = set()
    for nid in hit_nids:
        needle = ""
        m = _PAT[nid].search(spoken)
        if m:
            needle = m.group(0)
        snip = _snip(spoken, needle)
        if nid == "nest":
            sid, name = "", ""
            if any(s == "TWII" for s, _n in pairs) or re.search(
                r"(大盤|加權|台指|夜盤|逃命波|C-[123]|位階)", spoken
            ):
                sid, name = "TWII", "加權"
            key = (nid, sid)
            if key not in seen:
                seen.add(key)
                out.append({"neuron": nid, "sid": sid, "name": name, "snippet": snip})
            continue
        if nid == "tape":
            targets = stocks
        else:
            targets = stocks or [("", "")]
        for sid, name in targets:
            key = (nid, sid)
            if key in seen:
                continue
            seen.add(key)
            out.append({"neuron": nid, "sid": sid, "name": name, "snippet": snip})
    return out


def record_neuron_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """捕獲後立刻寫進六顆。同一則 UPSERT，不重掃 1709。"""
    if not db_path:
        return 0
    ensure_neuron_hits_table(db_path)
    rows: List[Tuple[Any, ...]] = []
    for ev in events:
        if str(ev.get("kind") or "") == "bystander":
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        day = str(ev.get("date") or "")
        hm = str(ev.get("time") or "")
        for hit in classify_spoken(raw, ev.get("tags")):
            rows.append(
                (
                    pid,
                    hit["neuron"],
                    hit["sid"],
                    hit["name"],
                    day,
                    hm,
                    hit["snippet"],
                )
            )
    if not rows:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_neuron_hits
            (post_id, neuron_id, stock_id, stock_name, post_date, post_time, snippet)
            VALUES (?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def latest_bundle(db_path: str, sid: str = "", *, n: int = 2) -> Dict[str, str]:
    """開火一次讀六顆最近句。個股帶這檔＋沒點檔的產業／大盤句。"""
    if not db_path or not os.path.isfile(db_path):
        return {}
    ensure_neuron_hits_table(db_path)
    want = str(sid or "").strip()
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT neuron_id, stock_id, post_date, post_time, snippet
            FROM biaoke_neuron_hits
            ORDER BY post_date DESC, post_time DESC
            LIMIT 80
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    picked: Dict[str, List[str]] = {nid: [] for nid in NEURON_IDS}
    for nid, stock, day, hm, snip in rows:
        nid = str(nid or "")
        if nid not in picked or len(picked[nid]) >= max(1, int(n)):
            continue
        stock = str(stock or "")
        snip = _SPACE.sub(" ", str(snip or "")).strip()
        if not snip:
            continue
        if nid == "nest":
            if stock and stock not in ("", "TWII"):
                continue
        elif want:
            if stock and stock != want:
                continue
        else:
            if stock:
                continue
        stamp = " ".join(x for x in (str(day or ""), str(hm or "")) if x)
        picked[nid].append(f"{stamp} {snip}".strip() if stamp else snip)
    return {k: "；".join(v) for k, v in picked.items() if v}


def backfill_recent_neurons(db_path: str, *, n: int = 80) -> int:
    """庫裡最近主文／自回補進六顆。UPSERT，不重掃 1709。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return 0
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
            ORDER BY date DESC, time DESC LIMIT ?
            """,
            (max(24, int(n)),),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    events = [
        {
            "id": r[0],
            "date": r[1],
            "time": r[2],
            "kind": r[3] or "post",
            "text": r[4] or "",
        }
        for r in rows
    ]
    return record_neuron_events(db_path, events)
