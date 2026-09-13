# -*- coding: utf-8 -*-
"""1709／社團附圖索引。圖檔不進 git，只留 URL＋短註＋代號。

頭像不算圖。這一檔只給查；神經元下一件才讀圖，不准在這裡改話筒鏈。
"""
from __future__ import annotations

import gzip
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
CHART_INDEX_GZ = os.path.join(_DIR, "chart_index.json.gz")
AVATAR_NEEDLE = "image.cmoney.tw/profile/"
_CODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEARS = {str(y) for y in range(1990, 2036)}

# 已目視過的關鍵圖。不准靠 OCR 亂猜，也不准發明建築兩檔代號。
_NOTE_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": "平台依賴度排名（當時 F10）",
    "f04ffb08-735d-42f8-a1c4-c473afa72034": "紅框：台光電量縮站上1265、金像電量縮小紅",
    "57effce7-7abf-4894-9354-e5d3812260d1": "紅框：漢唐量沒再放大",
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": "台光電 AI 高速 CCL 護城河 S+++",
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": "穎崴 2027 EPS 190～200",
    "59129621-6b40-42b2-90fa-74a1945b3b48": "金像電 CCL 漲價侵蝕毛利＝舊利空發酵",
    "9de6eef2-0bfa-4eb1-bf1f-47216dde15e0": "AI 族群重要性表：記憶體不宜當主線",
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": "勤誠破支撐就不適合操作",
    "nu9_05aT_7A": "YouTube 縮圖：PCB開始震",
}
_TICKERS_BY_SNIP = {
    "516b26b0-786e-494d-bf8f-1897b6f7dd7f": [
        "2330",
        "2383",
        "2059",
        "3017",
        "2308",
        "6223",
        "6515",
        "2368",
        "8210",
        "3081",
        "2454",
        "7769",
    ],
    "f04ffb08-735d-42f8-a1c4-c473afa72034": ["2383", "2368"],
    "57effce7-7abf-4894-9354-e5d3812260d1": ["2404"],
    "0fdcb54f-cbc3-45cf-bf40-51a99eb15aee": ["2383"],
    "57e9c59f-ebcc-46b2-8c51-6f9d452e2575": ["6515"],
    "59129621-6b40-42b2-90fa-74a1945b3b48": ["2368"],
    "4ffd8f7b-ffe7-4ee0-b6ce-945c153c1c3e": ["8210"],
}
_ALIAS = {
    "穎葳": "6515",
    "川湖": "2059",
    "聖暉": "5536",
    "旺矽": "6223",
    "鴻勁": "7769",
    "志聖": "2467",
    "漢唐": "2404",
}


def _snip_note(url: str) -> str:
    u = url or ""
    for snip, note in _NOTE_BY_SNIP.items():
        if snip in u:
            return note
    return ""


def _snip_tickers(url: str) -> List[str]:
    u = url or ""
    for snip, ids in _TICKERS_BY_SNIP.items():
        if snip in u:
            return list(ids)
    return []


def _add_sid(found: List[str], sid: str, valid: Optional[set]) -> None:
    sid = str(sid or "").strip()
    if not sid or sid in found:
        return
    if valid is not None and sid not in valid:
        return
    found.append(sid)


def extract_tickers(
    ocr: str = "",
    blob: str = "",
    *,
    url: str = "",
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
    limit: int = 12,
) -> List[str]:
    found: List[str] = []
    valid = set(valid_ids) if valid_ids is not None else None
    for sid in _snip_tickers(url):
        _add_sid(found, sid, valid)
    names = dict(_ALIAS)
    if name_to_sid:
        names.update(name_to_sid)
    text = (ocr or "") + "\n" + (blob or "")
    for name in sorted(names, key=len, reverse=True):
        if name and name in text:
            _add_sid(found, names[name], valid)
        if len(found) >= limit:
            return found[:limit]
    for code in _CODE.findall(ocr or ""):
        if code in _YEARS:
            continue
        _add_sid(found, code, valid)
        if len(found) >= limit:
            break
    return found[:limit]


def _short_note(kind: str, tickers: Sequence[str], url: str) -> str:
    known = _snip_note(url)
    if known:
        return known[:80]
    ids = ",".join(list(tickers)[:4])
    if kind == "kline":
        return ("日K截圖 " + ids).strip()[:80]
    if kind == "screenshot":
        return ("討論截圖 " + ids).strip()[:80]
    return ("其他附圖 " + ids).strip()[:80]


def _texts_for_aid(posts: Sequence[Dict[str, Any]], aid: str) -> str:
    aid = str(aid or "")
    if not aid:
        return ""
    chunks: List[str] = []
    for row in posts or []:
        pid = str(row.get("id") or "")
        parent = str(row.get("parent") or "")
        if pid == aid or parent == aid or pid.startswith(aid + ":"):
            tags = " ".join(str(t) for t in (row.get("tags") or []) if t)
            chunks.append(tags)
            chunks.append(str(row.get("text") or ""))
    return "\n".join(chunks)


def build_chart_index(
    catalog: Sequence[Dict[str, Any]],
    *,
    posts: Optional[Sequence[Dict[str, Any]]] = None,
    name_to_sid: Optional[Dict[str, str]] = None,
    valid_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """用已下載分類結果建精簡索引。不准塞整段 OCR，不准把頭像算進去。"""
    rows: List[Dict[str, Any]] = []
    seen = set()
    src_count: Dict[str, int] = {}
    post_rows = list(posts or [])
    valid = list(valid_ids) if valid_ids is not None else None
    for raw in catalog or []:
        url = str(raw.get("url") or "").strip()
        if not url or AVATAR_NEEDLE in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        src = str(raw.get("src") or "")
        aid = str(raw.get("aid") or "")
        kind = str(raw.get("kind") or "other")
        blob = _texts_for_aid(post_rows, aid)
        tickers = extract_tickers(
            str(raw.get("ocr") or ""),
            blob,
            url=url,
            name_to_sid=name_to_sid,
            valid_ids=valid,
        )
        rows.append(
            {
                "src": src,
                "date": str(raw.get("date") or ""),
                "aid": aid,
                "url": url,
                "kind": kind,
                "tickers": tickers,
                "note": _short_note(kind, tickers, url),
            }
        )
        src_count[src] = src_count.get(src, 0) + 1
    return {
        "n": len(rows),
        "sources": src_count,
        "note": "圖檔不進 git；頭像已剔除。神經元下一件才讀圖。",
        "charts": rows,
    }


def write_chart_index(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or CHART_INDEX_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    return dest


@lru_cache(maxsize=1)
def load_chart_index() -> Dict[str, Any]:
    if not os.path.isfile(CHART_INDEX_GZ):
        return {}
    with gzip.open(CHART_INDEX_GZ, "rt", encoding="utf-8") as fh:
        blob = json.load(fh) or {}
    if not isinstance(blob, dict):
        return {}
    return blob


def charts_for(sid: str) -> List[Dict[str, Any]]:
    """這檔出現在附圖索引裡的列。沒有就空。"""
    want = str(sid or "").strip()
    if not want:
        return []
    out: List[Dict[str, Any]] = []
    for row in load_chart_index().get("charts") or []:
        ticks = [str(t) for t in (row.get("tickers") or [])]
        if want in ticks:
            out.append(row)
    return out


def load_name_map(db_path: str = "") -> Dict[str, str]:
    """官方股名→代號。前華科對不到就不編。"""
    out = dict(_ALIAS)
    path = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "wayne_market.db"
    )
    if not path or not os.path.isfile(path):
        return out
    try:
        import sqlite3

        conn = sqlite3.connect(path, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT stock_id, stock_name FROM stock_universe"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return out
    for sid, name in rows:
        sid_s = str(sid or "").strip()
        name_s = str(name or "").replace("*", "").strip()
        if sid_s and name_s and name_s not in out:
            out[name_s] = sid_s
    return out


def valid_stock_ids(db_path: str = "") -> List[str]:
    names = load_name_map(db_path)
    return sorted(set(names.values()))
