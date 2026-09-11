# -*- coding: utf-8 -*-
"""Drive 1709 公開文 → 同一顆行情庫 overlay。社團文不進公開庫。

手機要查得到 2023-12 起的主文＋樓中樓，不是只靠 git 裡 520 篇種子。
種子 JSON 不整檔改寫；缺的 id 才 UPSERT。
"""
from __future__ import annotations

import gzip
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
ARCHIVE_GZ = os.path.join(_DIR, "archive_1709.json.gz")
_SEED = os.path.join(_DIR, "corpus_index.json")
# 融合／匯入唯一底圖＝雲端硬碟那一千七百多則公開主文，不是 git 520 篇種子。
# 資料夾：https://drive.google.com/drive/folders/1z4iNeBhO2-r1tlOLmv_vS-oNaAMaatXG
# 另檔：https://drive.google.com/file/d/1Nw79n7rNgIfnmcQzPjf-jNGEIAYKlw-n/view?usp=sharing
ARCHIVE_BASELINE_N = 1700

_POST_HEAD = re.compile(
    r"^## \[(社團)?貼文 (\d+)\]\s+(.+?)\s*$",
    re.M,
)
_LINK = re.compile(r"https://www\.cmoney\.tw/forum/article/(\d+)")
_DT = re.compile(
    r"(\d{4})/(\d{1,2})/(\d{1,2})\s*(上午|下午)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"
)
_REPLY = re.compile(
    r"^- \*\*\[(.+?)\] \((.+?)\)\*\*：(.*)$"
)
_CHART_URL = re.compile(
    r"https://image\.cmoney\.tw/attachment/[^\s)>\"]+",
    re.I,
)
_AVATAR_URL = re.compile(
    r"https://image\.cmoney\.tw/profile/",
    re.I,
)


def parse_archive_clock(raw: str) -> tuple[str, str]:
    m = _DT.search(raw or "")
    if not m:
        return "", ""
    y, mo, d, ap, hh, mm, _ss = m.groups()
    hour = int(hh)
    if ap == "下午" and hour < 12:
        hour += 12
    elif ap == "上午" and hour == 12:
        hour = 0
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", f"{hour:02d}:{mm}"


def _chunk_posts(text: str) -> List[str]:
    parts = re.split(r"(?=^## \[(?:社團)?貼文 \d+\])", text or "", flags=re.M)
    return [p.strip() for p in parts if _POST_HEAD.search(p or "")]


def _body_text(chunk: str) -> str:
    m = re.search(r"### 📌 主文分析\s*(.*?)(?=\n### |\n---\s*$|\Z)", chunk, re.S)
    if not m:
        return ""
    body = m.group(1).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def chart_urls(*blobs: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for blob in blobs:
        for url in _CHART_URL.findall(blob or ""):
            if _AVATAR_URL.search(url):
                continue
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out


def _append_charts(text: str, urls: Sequence[str], *, limit: int = 6) -> str:
    body = (text or "").rstrip()
    for url in list(urls)[:limit]:
        if url and url not in body:
            body = (body + "\n附圖：" + url).strip()
    return body


def _section(chunk: str, heading: str) -> str:
    m = re.search(
        rf"{re.escape(heading)}\s*(.*?)(?=\n### |\n---\s*$|\Z)",
        chunk or "",
        re.S,
    )
    return m.group(1) if m else ""


def _replies(chunk: str, parent_id: str) -> List[Dict[str, Any]]:
    block = re.search(
        r"### 💬 .*?\n(.*?)(?=\n---\s*$|\n## \[|\Z)",
        chunk,
        re.S,
    )
    if not block:
        return []
    lines = (block.group(1) or "").splitlines()
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for ln in lines:
        m = _REPLY.match(ln.strip()) if ln.startswith("- **[") else None
        if m:
            date_s, time_s = parse_archive_clock(m.group(1))
            kind_label = m.group(2) or ""
            layer = 2 if ("回覆" in kind_label and "主文" not in kind_label) else 1
            cur = {
                "n": 0,
                "date": date_s,
                "time": time_s,
                "id": f"{parent_id}:a{len(out)+1}",
                "parent": parent_id,
                "layer": layer,
                "kind": "reply",
                "tags": [],
                "text": (m.group(3) or "").strip(),
            }
            out.append(cur)
            continue
        if cur is None:
            continue
        s = ln.strip()
        if s.startswith("- **["):
            continue
        charts = chart_urls(s)
        if charts:
            cur["text"] = _append_charts(str(cur.get("text") or ""), charts, limit=4)
            continue
        if s.startswith("- 補充圖表") or s.startswith("補充圖表"):
            continue
        if s:
            cur["text"] = (cur["text"] + "\n" + s).strip()
    return [r for r in out if (r.get("text") or "").strip()]


def parse_archive_markdown(text: str) -> Dict[str, Any]:
    """公開 1709 或社團稿都能解析。club=True 的不進 seed_biaoke_archive。"""
    raw = text or ""
    club = "社團貼文" in raw[:800] or bool(re.search(r"^## \[社團貼文", raw, re.M))
    posts: List[Dict[str, Any]] = []
    for chunk in _chunk_posts(raw):
        head = _POST_HEAD.search(chunk)
        if not head:
            continue
        is_club_post = bool(head.group(1))
        date_s, time_s = parse_archive_clock(head.group(3) or "")
        aid = ""
        lm = _LINK.search(chunk)
        if lm:
            aid = lm.group(1)
        if not aid:
            continue
        body = _body_text(chunk)
        if not body:
            continue
        body = _append_charts(body, chart_urls(_section(chunk, "### 🖼️ 主文附圖")))
        posts.append(
            {
                "n": 0,
                "date": date_s,
                "time": time_s,
                "id": aid,
                "parent": "",
                "layer": 0,
                "kind": "post",
                "tags": [],
                "text": body,
                "club": bool(club or is_club_post),
            }
        )
        posts.extend(_replies(chunk, aid))
    mains = [p for p in posts if p.get("kind") != "reply"]
    dates = [str(p.get("date") or "") for p in mains if p.get("date")]
    return {
        "source": "drive-club" if club else "drive-1709-public",
        "club": club,
        "n": len(mains),
        "replies": sum(1 for p in posts if p.get("kind") == "reply"),
        "from": min(dates) if dates else "",
        "to": max(dates) if dates else "",
        "posts": posts,
    }


def _seed_tags_by_id() -> Dict[str, List[str]]:
    if not os.path.isfile(_SEED):
        return {}
    with open(_SEED, encoding="utf-8") as fh:
        blob = json.load(fh)
    out: Dict[str, List[str]] = {}
    names: List[str] = []
    seen = set()
    for p in blob.get("posts") or []:
        aid = str(p.get("id") or "")
        tags = [str(t) for t in (p.get("tags") or []) if t]
        if aid:
            out[aid] = tags
        for t in tags:
            if t not in seen:
                seen.add(t)
                names.append(t)
    out["__names__"] = sorted(names, key=len, reverse=True)
    extra = [
        "智原",
        "廣達",
        "技嘉",
        "緯創",
        "光聖",
        "志聖",
        "欣興",
        "台積電",
        "奇鋐",
        "健策",
        "聯亞",
        "南亞科",
        "群聯",
        "勤誠",
        "金像電",
        "台光電",
        "富喬",
        "穎崴",
        "穎葳",
        "致茂",
        "記憶體",
        "散熱",
        "光通訊",
        "PCB",
        "無人機",
    ]
    for t in extra:
        if t not in seen:
            names.append(t)
            seen.add(t)
    out["__names__"] = sorted(names, key=len, reverse=True)
    return out


def _extract_tags(text: str, names: Sequence[str], *, limit: int = 8) -> List[str]:
    found: List[str] = []
    blob = text or ""
    for name in names:
        if name and name in blob and name not in found:
            found.append(name)
        if len(found) >= limit:
            break
    return found


def attach_tags(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = _seed_tags_by_id()
    names = list(by_id.get("__names__") or [])
    for row in rows:
        if row.get("kind") == "reply":
            continue
        aid = str(row.get("id") or "")
        tags = list(by_id.get(aid) or [])
        if not tags:
            tags = _extract_tags(str(row.get("text") or ""), names)
        row["tags"] = tags[:8]
        row.pop("club", None)
    return rows


def load_bundled_archive() -> Dict[str, Any]:
    if not os.path.isfile(ARCHIVE_GZ):
        return {}
    with gzip.open(ARCHIVE_GZ, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def write_archive_gzip(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or ARCHIVE_GZ
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    posts = list(blob.get("posts") or [])
    attach_tags(posts)
    mains = [p for p in posts if p.get("kind") != "reply"]
    payload = {
        "source": "drive-1709-public",
        "club": False,
        "n": len(mains),
        "replies": sum(1 for p in posts if p.get("kind") == "reply"),
        "from": blob.get("from") or "",
        "to": blob.get("to") or "",
        "posts": posts,
    }
    tmp = dest + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dest)
    return dest


def seed_biaoke_archive(db_path: str, *, force: bool = False) -> int:
    """缺的公開文才寫進 biaoke_posts。已有的列（盤中 ingest）不覆蓋。"""
    if not db_path:
        return 0
    blob = load_bundled_archive()
    rows = [r for r in (blob.get("posts") or []) if not r.get("club")]
    if not rows:
        return 0
    from biaoke_desk import ensure_biaoke_posts_table, upsert_biaoke_posts

    ensure_biaoke_posts_table(db_path)
    import sqlite3

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        existing_text = {
            str(r[0]): str(r[1] or "")
            for r in conn.execute("SELECT id, text FROM biaoke_posts").fetchall()
        }
    except sqlite3.Error:
        existing_text = {}
    finally:
        conn.close()
    if force:
        todo = rows
    else:
        todo = []
        for r in rows:
            aid = str(r.get("id") or "")
            if not aid:
                continue
            old = existing_text.get(aid)
            if old is None:
                todo.append(r)
                continue
            new = str(r.get("text") or "")
            if (
                "image.cmoney.tw/attachment" in new
                and "image.cmoney.tw/attachment" not in old
            ):
                todo.append(r)
    if not todo:
        return 0
    return upsert_biaoke_posts(db_path, todo)
