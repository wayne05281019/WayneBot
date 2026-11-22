#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMoney 作者「啾哈」(user id 20269) 公開語料建檔。

獨立輸出，不准寫進飆客庫／海選／黃金買點／洞燭名單。
主文：GetChannelsArticleByWeight（Member-All.20269）。
討論串：訪客 grant → Comments JSON；樓中樓＝留言 id 當 article 再打 Comments。
附圖：image.cmoney.tw/attachment/… 原圖存 data/jiuha_corpus/images/。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

import requests

AUTHOR_ID = "20269"
AUTHOR_NAME = "啾哈"
USER_URL = f"https://www.cmoney.tw/forum/user/{AUTHOR_ID}"
ARTICLE_URL = "https://www.cmoney.tw/forum/article/{aid}"
TAIPEI = ZoneInfo("Asia/Taipei")

GUEST_TOKEN_URL = "https://www.cmoney.tw/api/identity/token"
GUEST_CLIENT_ID = "cmstockcommunity-web"
GUEST_GRANT_TYPE = "guest"

CHANNEL_API = (
    "https://www.cmoney.tw/api/mach/api/Article/GetChannelsArticleByWeight"
)
COMMENTS_API = "https://www.cmoney.tw/api/mach/api/Article/{aid}/Comments"
ARTICLE_API = "https://www.cmoney.tw/api/mach/api/Article/{aid}"
MEMBER_CHANNEL = f"Member-All.{AUTHOR_ID}"

DEFAULT_OUT = Path("/workspace/data/jiuha_corpus")
DEFAULT_REPORT = Path("/opt/cursor/artifacts/jiuha")

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "origin": "https://www.cmoney.tw",
    "referer": USER_URL,
}

_CHART_URL = re.compile(
    r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
    re.I,
)
_GUEST_CACHE: Dict[str, Any] = {"token": "", "expires_at": 0.0}

logger = logging.getLogger("jiuha_ingest")


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(sh)
    root.addHandler(fh)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_UA)
    return s


def _env_cmoney_token() -> str:
    raw = (os.environ.get("CMONEY_AUTH_TOKEN") or "").strip()
    if raw:
        return raw
    try:
        from config import get_cmoney_auth_token  # type: ignore

        return str(get_cmoney_auth_token() or "").strip()
    except Exception:
        return ""


def fetch_guest_token(session: requests.Session) -> str:
    cached = str(_GUEST_CACHE.get("token") or "")
    expires_at = float(_GUEST_CACHE.get("expires_at") or 0.0)
    if cached and time.time() < expires_at - 60:
        return cached
    try:
        resp = session.post(
            GUEST_TOKEN_URL,
            data={
                "client_id": GUEST_CLIENT_ID,
                "grant_type": GUEST_GRANT_TYPE,
            },
            headers={
                "User-Agent": _UA["User-Agent"],
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cmoney.tw/",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning("guest token http=%s", resp.status_code)
            return ""
        payload = resp.json()
    except Exception as exc:
        logger.warning("guest token fail: %s", exc)
        return ""
    token = str((payload or {}).get("access_token") or "").strip()
    if not token:
        return ""
    try:
        ttl = int((payload or {}).get("expires_in") or 0)
    except (TypeError, ValueError):
        ttl = 0
    _GUEST_CACHE["token"] = token
    _GUEST_CACHE["expires_at"] = time.time() + max(ttl, 60)
    return token


def comment_tokens(session: requests.Session) -> List[str]:
    out: List[str] = []
    guest = fetch_guest_token(session)
    if guest:
        out.append(guest)
    env = _env_cmoney_token()
    if env and env not in out:
        out.append(env)
    return out


def api_headers(token: str = "", *, version: str = "3.0") -> Dict[str, str]:
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-version": version,
        "cmoneyapi-trace-context": '{"device":"Mozilla/5.0"}',
        "referer": USER_URL,
        "origin": "https://www.cmoney.tw",
    }
    raw = str(token or "").strip()
    if raw:
        h["authorization"] = f"Bearer {raw}"
    return h


def ms_to_taipei(raw: Any) -> str:
    """毫秒／秒時間戳 → Asia/Taipei ISO（含時區）。"""
    if raw in (None, ""):
        return ""
    try:
        n = float(raw)
    except (TypeError, ValueError):
        s = str(raw).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TAIPEI)
            return dt.astimezone(TAIPEI).isoformat(timespec="seconds")
        except ValueError:
            return ""
    if n > 10_000_000_000:
        n = n / 1000.0
    try:
        dt = datetime.fromtimestamp(n, TAIPEI)
    except (OSError, OverflowError, ValueError):
        return ""
    return dt.isoformat(timespec="seconds")


def throttle(sec: float) -> None:
    if sec > 0:
        time.sleep(sec)


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Any = None,
    json_body: Any = None,
    timeout: int = 30,
    retries: int = 3,
    sleep_sec: float = 0.6,
    binary: bool = False,
) -> Tuple[int, Any]:
    last_code = 0
    for attempt in range(1, retries + 1):
        try:
            resp = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            last_code = int(resp.status_code or 0)
            if last_code in (429, 500, 502, 503, 504) and attempt < retries:
                logger.warning(
                    "retry %s %s http=%s attempt=%s",
                    method,
                    url.split("?")[0],
                    last_code,
                    attempt,
                )
                throttle(sleep_sec * attempt * 2)
                continue
            if binary:
                return last_code, resp.content if last_code == 200 else b""
            if last_code != 200:
                return last_code, None
            if not resp.content:
                return last_code, None
            try:
                return last_code, resp.json()
            except Exception:
                return last_code, resp.text
        except Exception as exc:
            logger.warning(
                "request fail %s %s attempt=%s err=%s",
                method,
                url.split("?")[0],
                attempt,
                exc,
            )
            if attempt < retries:
                throttle(sleep_sec * attempt * 2)
                continue
            return 0, None
    return last_code, None


def list_member_articles(
    session: requests.Session,
    token: str,
    *,
    page_size: int = 50,
    sleep_sec: float = 0.5,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """掃 Member-All.{id} 到底。回傳真主文＋掃程證明。"""
    articles: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    score: Optional[Any] = None
    pages = 0
    filler_pages = 0
    proof: Dict[str, Any] = {
        "channel": MEMBER_CHANNEL,
        "pages": [],
        "expected_total_from_html": None,
    }
    while pages < 200:
        params: Dict[str, Any] = {"count": int(page_size)}
        if score is not None:
            params["startScore"] = str(score)
        code, payload = request_with_retry(
            session,
            "POST",
            CHANNEL_API,
            headers={
                **api_headers(token, version="3.0"),
                "Content-Type": "application/json",
            },
            params=params,
            json_body={"items": [MEMBER_CHANNEL]},
            sleep_sec=sleep_sec,
        )
        page_info: Dict[str, Any] = {
            "page": pages,
            "http": code,
            "startScore": score,
            "count": 0,
            "real_new": 0,
            "last_id": None,
            "last_weight": None,
        }
        if code != 200 or not isinstance(payload, list) or not payload:
            page_info["note"] = "empty_or_error"
            proof["pages"].append(page_info)
            break
        real_new = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            aid = str(item.get("id") or "")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            content = item.get("content") if isinstance(item.get("content"), dict) else {}
            creator = str(
                content.get("creatorId")
                or item.get("creatorId")
                or ""
            )
            try:
                aid_n = int(aid)
            except ValueError:
                aid_n = 0
            title = str(content.get("title") or "").strip()
            text = str(content.get("text") or "").strip()
            if creator == AUTHOR_ID and aid_n > 0 and (title or text):
                articles.append(item)
                real_new += 1
        last = payload[-1] if payload else {}
        weight = last.get("weight") if isinstance(last, dict) else None
        page_info.update(
            {
                "count": len(payload),
                "real_new": real_new,
                "last_id": last.get("id") if isinstance(last, dict) else None,
                "last_weight": weight,
            }
        )
        proof["pages"].append(page_info)
        pages += 1
        if real_new == 0:
            filler_pages += 1
            if filler_pages >= 1 or weight in (None, -1, "-1"):
                page_info["note"] = "filler_or_end"
                break
        if weight is None or weight == score or weight in (-1, "-1"):
            break
        score = weight
        throttle(sleep_sec)
    proof["listed_raw_ids"] = len(seen)
    proof["real_articles"] = len(articles)
    proof["stopped_after_pages"] = pages
    return articles, proof


def read_expected_article_count(session: requests.Session) -> Optional[int]:
    """個人頁 SSR 的 totalCountArticle 當「盡力掃完」佐證。"""
    code, raw = request_with_retry(
        session,
        "GET",
        USER_URL,
        headers={
            "User-Agent": _UA["User-Agent"],
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
        binary=True,
        retries=2,
    )
    if code != 200 or not raw:
        return None
    try:
        html = raw.decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"totalCountArticle\s*=\s*(\d+)", html)
    if m:
        return int(m.group(1))
    return None


def media_urls_from_obj(obj: Any) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()

    def add(u: str) -> None:
        u = str(u or "").strip()
        if not u or u in seen:
            return
        if not _CHART_URL.match(u):
            return
        seen.add(u)
        urls.append(u)

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("url", "src", "path", "imageUrl") and isinstance(v, str):
                    add(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)
        elif isinstance(x, str):
            for u in _CHART_URL.findall(x):
                add(u)

    walk(obj)
    return urls


def comment_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("comments", "items", "replies", "list"):
        chunk = payload.get(key)
        if isinstance(chunk, list):
            return [c for c in chunk if isinstance(c, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        return comment_list(data)
    return []


def api_member_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("creatorInfo") if isinstance(item.get("creatorInfo"), dict) else {}
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    return str(
        item.get("creatorId")
        or item.get("memberId")
        or info.get("memberId")
        or info.get("creatorId")
        or content.get("creatorId")
        or ""
    )


def api_nickname(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("creatorInfo") if isinstance(item.get("creatorInfo"), dict) else {}
    return str(item.get("nickname") or info.get("nickname") or "")


def is_author(item: Any) -> bool:
    if api_member_id(item) == AUTHOR_ID:
        return True
    return api_nickname(item) == AUTHOR_NAME


def api_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    content = item.get("content")
    if isinstance(content, dict):
        return str(content.get("text") or content.get("body") or "").strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("body") or "").strip())
            elif isinstance(block, str):
                parts.append(block.strip())
        return "\n".join(p for p in parts if p)
    if isinstance(content, str) and content.strip():
        return content.strip()
    return str(item.get("text") or item.get("body") or "").strip()


def api_comment_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or item.get("commentId") or "").strip()


def api_stamp(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    raw = item.get("createTime")
    if raw in (None, ""):
        raw = item.get("createdAt")
    return ms_to_taipei(raw)


def api_children(item: Any) -> List[Dict[str, Any]]:
    if not isinstance(item, dict):
        return []
    for key in ("replies", "subComments", "childComments", "comments"):
        chunk = item.get(key)
        if isinstance(chunk, list):
            return [c for c in chunk if isinstance(c, dict)]
    return []


def api_child_count(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    n = len(api_children(item))
    for key in ("commentCount", "replyCount", "repliesCount"):
        try:
            n = max(n, int(item.get(key) or 0))
        except (TypeError, ValueError):
            pass
    return n


def fetch_comment_pages(
    session: requests.Session,
    aid: str,
    token: str,
    *,
    sleep_sec: float = 0.35,
) -> Tuple[List[Dict[str, Any]], int]:
    comments: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    start_index = 0
    status = 0
    for _ in range(20):
        url = COMMENTS_API.format(aid=aid)
        code, payload = request_with_retry(
            session,
            "GET",
            url,
            headers=api_headers(token, version="2.0"),
            params={"startCommentIndex": int(start_index), "fetch": -100},
            sleep_sec=sleep_sec,
        )
        status = code
        if code != 200 or payload is None:
            return comments, status
        page = comment_list(payload)
        for cm in page:
            cid = api_comment_id(cm)
            key = cid or f"anon:{len(comments)}"
            if key in seen:
                continue
            seen.add(key)
            comments.append(cm)
        remain = 0
        nxt: Any = None
        if isinstance(payload, dict):
            try:
                remain = int(payload.get("remainCount") or 0)
            except (TypeError, ValueError):
                remain = 0
            nxt = payload.get("nextCommentIndex")
        if remain <= 0 or not page or nxt is None:
            break
        try:
            nxt_i = int(nxt)
        except (TypeError, ValueError):
            break
        if nxt_i == start_index:
            break
        start_index = nxt_i
        throttle(sleep_sec)
    return comments, status


def fetch_nested_comments(
    session: requests.Session,
    aid: str,
    cid: str,
    token: str,
    *,
    sleep_sec: float = 0.35,
) -> Tuple[List[Dict[str, Any]], int]:
    """樓中樓：留言 id 當 article 再打 Comments；404 才退回 Replies。"""
    kids: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    start = 0
    status = 0
    for _page in range(12):
        code, payload = request_with_retry(
            session,
            "GET",
            COMMENTS_API.format(aid=cid),
            headers=api_headers(token, version="2.0"),
            params={"startCommentIndex": int(start), "fetch": -50},
            sleep_sec=sleep_sec,
        )
        status = code
        page = comment_list(payload) if payload is not None else []
        if not page and start == 0 and code == 404:
            code, payload = request_with_retry(
                session,
                "GET",
                f"https://www.cmoney.tw/api/mach/api/Article/{aid}/Comment/{cid}/Replies",
                headers=api_headers(token, version="2.0"),
                params={"fetch": -50},
                sleep_sec=sleep_sec,
            )
            status = code
            page = comment_list(payload) if payload is not None else []
        for cm in page:
            if not isinstance(cm, dict):
                continue
            key = api_comment_id(cm) or f"anon:{len(kids)}"
            if key in seen:
                continue
            seen.add(key)
            kids.append(cm)
        remain = 0
        nxt: Any = None
        if isinstance(payload, dict):
            try:
                remain = int(payload.get("remainCount") or 0)
            except (TypeError, ValueError):
                remain = 0
            nxt = payload.get("nextCommentIndex")
        if remain <= 0 or not page or nxt is None:
            break
        try:
            nxt_i = int(nxt)
        except (TypeError, ValueError):
            break
        if nxt_i == start:
            break
        start = nxt_i
        throttle(sleep_sec)
    return kids, status


def fill_nested(
    session: requests.Session,
    aid: str,
    token: str,
    comments: Sequence[Dict[str, Any]],
    *,
    sleep_sec: float = 0.35,
    max_pulls: int = 200,
) -> Dict[str, List[Dict[str, Any]]]:
    nested: Dict[str, List[Dict[str, Any]]] = {}
    queue: List[Dict[str, Any]] = [c for c in comments if isinstance(c, dict)]
    seen: Set[str] = set()
    pulls = 0
    while queue and pulls < max_pulls:
        cm = queue.pop(0)
        cid = api_comment_id(cm)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        kids = list(api_children(cm))
        count = api_child_count(cm)
        if count > len(kids):
            extra, _st = fetch_nested_comments(
                session, aid, cid, token, sleep_sec=sleep_sec
            )
            pulls += 1
            have = {api_comment_id(k) for k in kids}
            for sub in extra:
                sid = api_comment_id(sub)
                if sid and sid in have:
                    continue
                kids.append(sub)
            throttle(sleep_sec)
        if kids:
            nested[cid] = kids
            queue.extend(kids)
    return nested


def walk_thread(
    comments: Sequence[Dict[str, Any]],
    *,
    article_id: str,
    nested_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """作者回覆 kind=reply；路人 kind=bystander（脈絡，不是他的判斷）。"""
    nested_by_id = nested_by_id or {}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    max_layer = 12

    def walk(items: Sequence[Any], layer: int, parent_cm: Optional[Dict[str, Any]]) -> None:
        for cm in items:
            if not isinstance(cm, dict):
                continue
            cid = api_comment_id(cm)
            text = api_text(cm)
            imgs = media_urls_from_obj(cm)
            parent_cid = api_comment_id(parent_cm) if parent_cm else ""
            if is_author(cm):
                kind = "reply"
                voice = "author"
                key = cid or f"a:{text[:40]}"
            else:
                kind = "bystander"
                voice = "bystander"
                key = "b:" + (cid or text[:40])
            if key and key not in seen and text:
                seen.add(key)
                out.append(
                    {
                        "article_id": str(article_id),
                        "comment_id": cid,
                        "kind": kind,
                        "voice": voice,
                        "text": text,
                        "published_at_taipei": api_stamp(cm),
                        "image_urls": imgs,
                        "image_paths": [],
                        "parent_comment_id": parent_cid or None,
                        "layer": int(layer),
                        "source_url": ARTICLE_URL.format(aid=article_id),
                        "is_author_judgment": kind == "reply",
                    }
                )
            kids = list(api_children(cm))
            extra = nested_by_id.get(cid or "") or []
            if extra:
                have = {api_comment_id(k) for k in kids}
                for sub in extra:
                    sid = api_comment_id(sub)
                    if sid and sid in have:
                        continue
                    kids.append(sub)
            if kids and layer < max_layer:
                walk(kids, layer + 1, cm)

    walk(list(comments), 1, None)
    return out


def download_image(
    session: requests.Session,
    url: str,
    images_dir: Path,
    *,
    article_id: str,
    sleep_sec: float = 0.25,
) -> Tuple[Optional[str], Optional[str]]:
    """回傳 (相對路徑, 錯誤訊息)。"""
    if not _CHART_URL.match(url):
        return None, "not_attachment_url"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = ".jpg"
    m = re.search(r"\.(jpe?g|png|gif|webp|bmp)(?:\?|$)", url, re.I)
    if m:
        ext = "." + m.group(1).lower().replace("jpeg", "jpg")
    name = f"{article_id}_{digest}{ext}"
    dest = images_dir / name
    rel = f"images/{name}"
    if dest.exists() and dest.stat().st_size > 0:
        return rel, None
    code, blob = request_with_retry(
        session,
        "GET",
        url,
        headers={
            "User-Agent": _UA["User-Agent"],
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": USER_URL,
        },
        binary=True,
        retries=3,
        sleep_sec=sleep_sec,
    )
    if code != 200 or not blob:
        return None, f"http_{code}"
    dest.write_bytes(blob)
    throttle(sleep_sec)
    return rel, None


def ensure_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            voice TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            published_at_taipei TEXT NOT NULL DEFAULT '',
            image_paths_json TEXT NOT NULL DEFAULT '[]',
            parent_comment_id TEXT,
            source_url TEXT NOT NULL DEFAULT '',
            is_author_judgment INTEGER NOT NULL DEFAULT 0,
            layer INTEGER NOT NULL DEFAULT 0,
            comment_id TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_records_article ON records(article_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind ON records(kind)")
    conn.commit()
    return conn


def upsert_record(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    rid = str(row.get("id") or "").strip()
    if not rid:
        return
    conn.execute(
        """
        INSERT INTO records(
            id, article_id, kind, voice, text, title, published_at_taipei,
            image_paths_json, parent_comment_id, source_url, is_author_judgment,
            layer, comment_id, raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            article_id=excluded.article_id,
            kind=excluded.kind,
            voice=excluded.voice,
            text=excluded.text,
            title=excluded.title,
            published_at_taipei=excluded.published_at_taipei,
            image_paths_json=excluded.image_paths_json,
            parent_comment_id=excluded.parent_comment_id,
            source_url=excluded.source_url,
            is_author_judgment=excluded.is_author_judgment,
            layer=excluded.layer,
            comment_id=excluded.comment_id,
            raw_json=excluded.raw_json
        """,
        (
            rid,
            str(row.get("article_id") or ""),
            str(row.get("kind") or ""),
            str(row.get("voice") or ""),
            str(row.get("text") or ""),
            str(row.get("title") or ""),
            str(row.get("published_at_taipei") or ""),
            json.dumps(row.get("image_paths") or [], ensure_ascii=False),
            row.get("parent_comment_id"),
            str(row.get("source_url") or ""),
            1 if row.get("is_author_judgment") else 0,
            int(row.get("layer") or 0),
            str(row.get("comment_id") or ""),
            json.dumps(row.get("raw") or {}, ensure_ascii=False),
        ),
    )


def article_to_main_row(item: Dict[str, Any]) -> Dict[str, Any]:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    aid = str(item.get("id") or "")
    title = str(content.get("title") or "").strip()
    text = str(content.get("text") or "").strip()
    body = text
    if title and title not in body:
        body = f"{title}\n\n{text}".strip()
    imgs = media_urls_from_obj(content.get("multiMedia") or [])
    imgs.extend(media_urls_from_obj(body))
    # dedupe keep order
    seen: Set[str] = set()
    uniq: List[str] = []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return {
        "id": f"main:{aid}",
        "article_id": aid,
        "kind": "main",
        "voice": "author",
        "title": title,
        "text": body,
        "published_at_taipei": ms_to_taipei(item.get("createTime")),
        "image_urls": uniq,
        "image_paths": [],
        "parent_comment_id": None,
        "source_url": ARTICLE_URL.format(aid=aid),
        "is_author_judgment": True,
        "layer": 0,
        "comment_id": "",
        "raw": {
            "id": item.get("id"),
            "createTime": item.get("createTime"),
            "weight": item.get("weight"),
            "title": title,
            "commodityTags": content.get("commodityTags"),
        },
    }


def run_ingest(
    out_dir: Path,
    report_dir: Path,
    *,
    sleep_sec: float = 0.45,
    max_articles: Optional[int] = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "ingest.log"
    setup_logging(log_path)

    jsonl_path = out_dir / "index.jsonl"
    db_path = out_dir / "jiuha.sqlite"
    meta_path = out_dir / "meta.json"
    orphan_log = report_dir / "orphan_images.log"

    session = _session()
    tokens = comment_tokens(session)
    if not tokens:
        raise RuntimeError("無法取得訪客 grant／CMONEY_AUTH_TOKEN，停止。")
    token = tokens[0]
    logger.info("token ok (guest/env); author=%s %s", AUTHOR_ID, AUTHOR_NAME)

    expected = read_expected_article_count(session)
    logger.info("user page totalCountArticle=%s", expected)

    articles, list_proof = list_member_articles(
        session, token, page_size=50, sleep_sec=sleep_sec
    )
    list_proof["expected_total_from_html"] = expected
    if max_articles is not None:
        articles = articles[: max(0, int(max_articles))]
    logger.info(
        "listed real mains=%s expected=%s pages=%s",
        len(articles),
        expected,
        len(list_proof.get("pages") or []),
    )

    conn = ensure_sqlite(db_path)
    jsonl_fp = open(jsonl_path, "w", encoding="utf-8")
    orphan_fp = open(orphan_log, "w", encoding="utf-8")

    stats = {
        "mains": 0,
        "author_replies": 0,
        "bystanders": 0,
        "images_ok": 0,
        "images_fail": 0,
        "comment_http_fail": 0,
        "articles_processed": 0,
    }
    sample_mains: List[Dict[str, str]] = []
    all_times: List[str] = []

    try:
        for i, item in enumerate(articles, 1):
            main = article_to_main_row(item)
            aid = main["article_id"]
            logger.info("[%s/%s] article %s %s", i, len(articles), aid, main["title"][:40])

            # download main images
            paths: List[str] = []
            for url in main.get("image_urls") or []:
                rel, err = download_image(
                    session, url, images_dir, article_id=aid, sleep_sec=sleep_sec * 0.5
                )
                if rel:
                    paths.append(rel)
                    stats["images_ok"] += 1
                else:
                    stats["images_fail"] += 1
                    orphan_fp.write(
                        json.dumps(
                            {
                                "article_id": aid,
                                "url": url,
                                "error": err,
                                "note": "main_image_fail",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            main["image_paths"] = paths

            # comments
            thread_rows: List[Dict[str, Any]] = []
            last_status = 0
            for auth in tokens:
                comments, status = fetch_comment_pages(
                    session, aid, auth, sleep_sec=sleep_sec
                )
                last_status = status
                if status == 200:
                    nested = fill_nested(
                        session, aid, auth, comments, sleep_sec=sleep_sec
                    )
                    thread_rows = walk_thread(
                        comments, article_id=aid, nested_by_id=nested
                    )
                    break
                if status not in (401, 403):
                    break
            if last_status != 200:
                stats["comment_http_fail"] += 1
                logger.warning("comments fail aid=%s http=%s", aid, last_status)

            # images on author/bystander replies (only keep attachment; map to article)
            for row in thread_rows:
                rpaths: List[str] = []
                for url in row.get("image_urls") or []:
                    rel, err = download_image(
                        session,
                        url,
                        images_dir,
                        article_id=aid,
                        sleep_sec=sleep_sec * 0.5,
                    )
                    if rel:
                        rpaths.append(rel)
                        stats["images_ok"] += 1
                    else:
                        stats["images_fail"] += 1
                        orphan_fp.write(
                            json.dumps(
                                {
                                    "article_id": aid,
                                    "comment_id": row.get("comment_id"),
                                    "url": url,
                                    "error": err,
                                    "note": "reply_image_fail",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                row["image_paths"] = rpaths
                row["id"] = (
                    f"reply:{row.get('comment_id')}"
                    if row.get("kind") == "reply"
                    else f"bystander:{row.get('comment_id')}"
                )
                if not row.get("comment_id"):
                    row["id"] = (
                        f"{row['kind']}:{aid}:{hashlib.sha1(row['text'].encode()).hexdigest()[:12]}"
                    )

            # write
            upsert_record(conn, main)
            jsonl_fp.write(json.dumps(main, ensure_ascii=False) + "\n")
            stats["mains"] += 1
            if main.get("published_at_taipei"):
                all_times.append(main["published_at_taipei"])
            if len(sample_mains) < 3:
                sample_mains.append(
                    {
                        "article_id": aid,
                        "title": main.get("title") or "",
                        "published_at_taipei": main.get("published_at_taipei") or "",
                        "excerpt": (main.get("text") or "").replace("\n", " ")[:120],
                        "source_url": main.get("source_url") or "",
                    }
                )

            for row in thread_rows:
                upsert_record(conn, row)
                jsonl_fp.write(json.dumps(row, ensure_ascii=False) + "\n")
                if row.get("kind") == "reply":
                    stats["author_replies"] += 1
                else:
                    stats["bystanders"] += 1
                if row.get("published_at_taipei"):
                    all_times.append(row["published_at_taipei"])

            conn.commit()
            stats["articles_processed"] += 1
            throttle(sleep_sec)
    finally:
        jsonl_fp.close()
        orphan_fp.close()
        conn.commit()
        conn.close()

    span = {
        "earliest": min(all_times) if all_times else "",
        "latest": max(all_times) if all_times else "",
    }
    report = {
        "author_id": AUTHOR_ID,
        "author_name": AUTHOR_NAME,
        "user_url": USER_URL,
        "generated_at_taipei": taipei_now().isoformat(timespec="seconds"),
        "stats": stats,
        "time_span_taipei": span,
        "expected_article_count": expected,
        "list_proof": list_proof,
        "outputs": {
            "index_jsonl": str(jsonl_path),
            "sqlite": str(db_path),
            "images_dir": str(images_dir),
            "meta": str(meta_path),
            "log": str(log_path),
            "orphan_images_log": str(orphan_log),
        },
        "sample_mains": sample_mains,
        "notes": [
            "獨立語料，不准混飆客庫，不准寫海選／黃金買點／洞燭。",
            "路人 kind=bystander，is_author_judgment=false。",
            "主文掃完佐證：API 真主文數 vs 個人頁 totalCountArticle。",
        ],
    }
    meta_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (report_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # human summary
    lines = [
        f"# 啾哈（{AUTHOR_ID}）語料建檔報告",
        "",
        f"- 主文篇數：{stats['mains']}（個人頁標示 {expected}）",
        f"- 他本人回覆則數：{stats['author_replies']}",
        f"- 路人脈絡則數：{stats['bystanders']}（非他判斷）",
        f"- 附圖成功／失敗：{stats['images_ok']}／{stats['images_fail']}",
        f"- 時間跨度（台北）：{span['earliest']} ～ {span['latest']}",
        f"- 索引：`{jsonl_path}`",
        f"- SQLite：`{db_path}`",
        f"- 圖檔：`{images_dir}`",
        "",
        "## 抽樣主文",
    ]
    for s in sample_mains:
        lines.append(
            f"- [{s['title']}]({s['source_url']})（{s['published_at_taipei']}）"
            f"：{s['excerpt']}"
        )
    if expected is not None and stats["mains"] != expected:
        lines.append("")
        lines.append(
            f"## 注意：主文數 {stats['mains']} ≠ 個人頁 totalCountArticle {expected}"
        )
    (report_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("done stats=%s span=%s", stats, span)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="啾哈 CMoney 語料建檔（獨立庫）")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    p.add_argument("--sleep", type=float, default=0.45)
    p.add_argument("--max-articles", type=int, default=0, help="0=全部")
    args = p.parse_args(argv)
    max_articles = args.max_articles if args.max_articles > 0 else None
    report = run_ingest(
        Path(args.out),
        Path(args.report),
        sleep_sec=float(args.sleep),
        max_articles=max_articles,
    )
    print(json.dumps({"ok": True, "stats": report.get("stats"), "span": report.get("time_span_taipei")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
