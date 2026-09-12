# -*- coding: utf-8 -*-
"""飆大公開發文＋最新文一二層回覆匯入。不進海選。

盤中 10 分。收盤後、凌晨、週末、國定假、颱風停市都每 1 小時——他常不發新主文，改在最近幾篇樓下補觀點或改主文。
討論串只重讀個人頁最新 3 篇（他幾乎不回三篇之前）。新主文仍從個人頁偵測。
主文走公開 HTML。樓下自回走 /api/mach/.../Comments（偉權抓碼那組網址）。
不准把 Bearer／localStorage／帳密寫進 git；token 只讀環境變數 CMONEY_AUTH_TOKEN。
不准放 Bearer 字串當密鑰進 repo。沒設 token：公開 HTML 沒留言正文就不假裝聽到。社團不抓。
只收飆大本人主文＋一／二層樓中樓（含回在別人留言裡的）＋他自己附的圖。
路人留言不收。抓到新文立刻對官方 K 建檔，不清空再等。
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import requests

from biaoke_archive import ARCHIVE_BASELINE_N, seed_biaoke_archive
from biaoke_desk import (
    ensure_biaoke_posts_table,
    load_corpus,
    load_corpus_cache_clear,
    upsert_biaoke_posts,
)

logger = logging.getLogger("WayneBot.BiaokeIngest")

AUTHOR_ID = "25263"
AUTHOR_NAME = "期股多空雙飆客"
USER_URL = f"https://www.cmoney.tw/forum/user/{AUTHOR_ID}"
ARTICLE_URL = "https://www.cmoney.tw/forum/article/{aid}"
TAIPEI = ZoneInfo("Asia/Taipei")
# 自訂 UA 會 403；公開頁用一般瀏覽器標頭。不准帶 token。
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
SESSION_EVERY_SEC = 10 * 60
AFTER_EVERY_SEC = 1 * 60 * 60
NIGHT_EVERY_SEC = AFTER_EVERY_SEC  # 休市／週末／凌晨也每小時，不再等到開盤
AFTER_UNTIL_HOUR = 3  # 舊常數：排程已改成全天有抓，不再當停止線
REFRESH_LATEST = 3  # 他幾乎不回三篇之前的貼文
_ID_RE = re.compile(r"/forum/article/(\d{6,})")
_HREF_OWN = re.compile(
    r'href="(?:https://www\.cmoney\.tw)?/forum/article/(\d{6,})"'
)
_NUXT_FEED = re.compile(
    r'articles:\[\{id:"(\d{6,})",creatorId:([A-Za-z_$][\w$]*)'
)
_NUXT_ID_CREATOR = re.compile(
    r'\{id:"(\d{6,})",creatorId:([A-Za-z_$][\w$]*)'
)
_CHART_URL = re.compile(
    r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
    re.I,
)
_PUB_RE = re.compile(
    r'property="article:published_time"\s+content="([^"]+)"',
    re.I,
)
_TAG_RE = re.compile(r'property="article:tag"\s+content="([^"]+)"', re.I)
_META_AUTHOR = re.compile(
    r'<meta[^>]*name=["\']author["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_META_AUTHOR_ALT = re.compile(
    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']author["\']',
    re.I,
)
_BODY_START = re.compile(
    r"(1[\.、．]\s*台指期|目前台股|今天盤後|大盤)",
)
# 別人的價值投資長文。側欄出現飆客名字不算他寫的。
_ALIEN_MARK = re.compile(
    r"(模糊的精確|安全邊際|沉澱帶|淨利息收入|淨利息支出|估值位階|因果鏈才是)"
)
_VOICE_MARK = re.compile(
    r"(台指期|細微波|夜盤|費半|破線|洗盤|長線主流|下降軌道|"
    r"15\s*分|60\s*分|量先價行|右肩|護城河)"
)

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_UA)
    return s


def parse_published(raw: str) -> tuple[str, str]:
    """2026-9-10T9:51:28+08:00 → (2026-09-10, 09:51)。"""
    s = (raw or "").strip()
    if not s:
        return "", ""
    s = s.replace("Z", "+00:00")
    m = re.match(
        r"(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})",
        s,
    )
    if not m:
        return "", ""
    y, mo, d, hh, mm = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", f"{int(hh):02d}:{mm}"


def chart_urls(*blobs: str) -> List[str]:
    """只收飆大附在主文／樓中樓的 attachment 圖，不要頭像、不要路人圖。"""
    out: List[str] = []
    seen = set()
    for blob in blobs:
        for url in _CHART_URL.findall(blob or ""):
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


def is_biaoke_voice(text: str) -> bool:
    """別人的文即使頁面上出現飆客名字也不收。"""
    t = text or ""
    if _ALIEN_MARK.search(t) and not _VOICE_MARK.search(t):
        return False
    return True


def _meta_author(html_text: str) -> str:
    raw = html_text or ""
    m = _META_AUTHOR.search(raw) or _META_AUTHOR_ALT.search(raw)
    return html.unescape(m.group(1)).strip() if m else ""


def page_is_author_article(html_text: str) -> bool:
    """只認這篇的 author meta／主文區。側欄、推薦文、別人主文不要。"""
    raw = html_text or ""
    meta = _meta_author(raw)
    if meta:
        return AUTHOR_NAME in meta
    art = re.search(r"<article[^>]*>(.*)</article>", raw, re.S | re.I)
    head = art.group(1) if art else raw
    head = re.split(
        r"articleComment|articleReply|replyRespond",
        head,
        maxsplit=1,
    )[0]
    head = head[:4000]
    return AUTHOR_NAME in head or f"/forum/user/{AUTHOR_ID}" in head


def parse_user_article_ids(html_text: str) -> List[str]:
    """只收飆客自己個人頁的主文 id。側欄、別人文章、utm 分享連結不要。

    只吃 Nuxt SSR 的 articles[]（帶 creatorId，可濾掉側欄）。
    純 href 不夠——側欄／推薦文也是 /forum/article/…。
    """
    raw = html_text or ""
    m = _NUXT_FEED.search(raw)
    if not m:
        return []
    owner = m.group(2)
    chunk = raw[m.start() : m.start() + 180000]
    ids: List[str] = []
    seen = set()
    for aid, cid in _NUXT_ID_CREATOR.findall(chunk):
        if cid != owner or len(aid) <= 6:
            continue
        if aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
        if len(ids) >= 20:
            break
    return ids


def _strip_article_text(html_text: str) -> str:
    m = re.search(r"<article[^>]*>(.*)</article>", html_text or "", re.S | re.I)
    inner = m.group(1) if m else (html_text or "")
    inner = re.sub(r"<script.*?</script>", " ", inner, flags=re.S)
    inner = re.sub(r"<style.*?</style>", " ", inner, flags=re.S)
    inner = re.sub(r"<[^>]+>", "\n", inner)
    inner = html.unescape(inner)
    lines = [ln.strip() for ln in inner.splitlines() if ln.strip()]
    skip = {
        "追蹤",
        "展開",
        "打賞",
        "分享",
        "留言",
        "讚",
        "取消",
        "送出",
        "加入Google偏好",
        "超級幫手",
    }
    kept: List[str] = []
    started = False
    for ln in lines:
        if ln in skip or ln.startswith("查看 ") or ln.endswith("則留言"):
            if started and (ln.startswith("查看 ") or ln in {"打賞", "分享", "留言"}):
                break
            continue
        if re.fullmatch(r"Lv\.\d+", ln) or re.fullmatch(r"\d+P", ln) or re.fullmatch(r"\d+", ln):
            continue
        if not started and (
            _BODY_START.search(ln)
            or ln[:2] in ("1.", "2.", "3.")
            or ln.startswith("今天")
            or ln.startswith("大盤")
        ):
            started = True
        if started:
            kept.append(ln)
    return "\n".join(kept).strip()


def parse_article_html(aid: str, html_text: str) -> Optional[Dict[str, Any]]:
    pub = ""
    m = _PUB_RE.search(html_text or "")
    if m:
        pub = m.group(1)
    date, time_s = parse_published(pub)
    tags = []
    for tag in _TAG_RE.findall(html_text or ""):
        t = html.unescape(tag).strip()
        t = re.sub(r"^[A-Z]{0,5}\d{3,6}", "", t).strip()
        if t and t not in tags and t not in {"加權指數"}:
            tags.append(t)
    raw = html_text or ""
    if not page_is_author_article(raw):
        return None
    text = _strip_article_text(raw)
    if not date or not text or not is_biaoke_voice(text):
        return None
    main = raw
    art = re.search(r"<article[^>]*>(.*)</article>", raw, re.S | re.I)
    if art:
        main = re.split(
            r"articleComment|articleReply|replyRespond",
            art.group(1),
            maxsplit=1,
        )[0]
    text = _append_charts(text, chart_urls(main))
    return {
        "n": 0,
        "date": date,
        "time": time_s,
        "id": str(aid),
        "tags": tags[:8],
        "text": text,
    }


def fetch_html(url: str, session: Optional[requests.Session] = None, timeout: int = 12) -> str:
    sess = session or _session()
    resp = sess.get(url, timeout=timeout)
    if getattr(resp, "status_code", 200) == 404:
        return ""
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text or ""


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


def poll_wait_seconds(now: Optional[datetime] = None) -> int:
    """開市盤中 10 分；其餘時間（盤後、凌晨、週末、國定假、颱風停市）每 1 小時。

    他週四／週五發文後，週末仍可能在最近三篇樓下回別人、補觀點、或改主文。
    不准再用「等到開盤」把凌晨到 9 點、週末、颱風天空掉。
    """
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    ymd = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_tw_open_calendar_day

        open_day = bool(is_tw_open_calendar_day(ymd))
    except Exception:
        open_day = dt.weekday() < 5
    hm = dt.hour * 60 + dt.minute
    if open_day and 9 * 60 <= hm <= 13 * 60 + 40:
        return SESSION_EVERY_SEC
    return AFTER_EVERY_SEC


def parse_display_time(
    raw: str, *, now: Optional[datetime] = None
) -> tuple[str, str]:
    """昨天 10:23／9/9 10:23 → (日期, 時分)。相對時間以台灣現在為準。"""
    s = (raw or "").strip()
    dt = now or taipei_now()
    m = re.search(r"(昨天|昨日|前天)?\s*(\d{1,2}):(\d{2})", s)
    if m:
        label, hh, mm = m.group(1) or "", int(m.group(2)), m.group(3)
        day = dt
        if label in ("昨天", "昨日"):
            day = dt - timedelta(days=1)
        elif label == "前天":
            day = dt - timedelta(days=2)
        return day.strftime("%Y-%m-%d"), f"{hh:02d}:{mm}"
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", s)
    if m:
        y, mo, d, hh, mm = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", f"{int(hh):02d}:{mm}"
    m = re.search(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
    if m:
        mo, d, hh, mm = m.groups()
        return f"{dt.year:04d}-{int(mo):02d}-{int(d):02d}", f"{int(hh):02d}:{mm}"
    return "", ""


def _plain(html_text: str) -> str:
    t = re.sub(r"<script.*?</script>", " ", html_text or "", flags=re.S)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = html.unescape(t)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    return "\n".join(lines)


def _reply_noise(body: str) -> bool:
    s = body or ""
    if not s.strip():
        return True
    if "data-v-" in s or ".article" in s:
        return True
    if "查看" in s and "則留言" in s:
        return True
    if s.count("{") >= 2:
        return True
    return False


def parse_author_replies(
    html_text: str,
    *,
    parent_id: str,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """只收飆大自己的一、二層樓中樓。路人正文不收。

    他常回在別人留言裡面（nested / 樓中樓），那一則仍要收。
    他自己附的 attachment 圖一併留下。公開頁沒 SSR 就空列表。
    """
    raw = html_text or ""
    if f"/forum/user/{AUTHOR_ID}" not in raw and AUTHOR_NAME not in raw:
        return []
    chunks = re.split(
        r'(?=<[^>]+class="[^"]*\b(?:articleReply|articleComment|replyRespond)(?:\s|")[^"]*")',
        raw,
    )
    out: List[Dict[str, Any]] = []
    seen = set()
    for ch in chunks:
        if f"/forum/user/{AUTHOR_ID}" not in ch and AUTHOR_NAME not in ch:
            continue
        if (
            "articleContent__baseCont" in ch
            and "articleReply" not in ch
            and "articleComment__content" not in ch
            and "replyRespond" not in ch
        ):
            continue
        layer = 2 if re.search(
            r"articleReply[^>]*nested|replyRespond|層回覆|樓中樓", ch
        ) else 1
        body = ""
        for cls in (
            r'articleReply__content[^>]*>(.*?)</div>',
            r'articleComment__content[^>]*>(.*?)</div>',
            r'replyRespond__body[^>]*>(.*?)</div>',
        ):
            m = re.search(cls, ch, re.S | re.I)
            if m:
                body = _plain(m.group(1))
                if body:
                    break
        imgs = chart_urls(ch)
        if not body:
            plain = _plain(ch)
            plain = re.sub(rf"{AUTHOR_NAME}|讚|回覆|超級幫手|Lv\.\d+", " ", plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            if 8 <= len(plain) <= 400 and not _reply_noise(plain):
                body = plain
        body = _append_charts(body, imgs, limit=4)
        if _reply_noise(body) or body in seen:
            continue
        tm_raw = ""
        tm = re.search(r"(昨天|昨日|前天)?\s*\d{1,2}:\d{2}", ch)
        if tm:
            tm_raw = tm.group(0)
        date_s, time_s = parse_display_time(tm_raw, now=now)
        rid = f"{parent_id}:r{len(out)+1}"
        seen.add(body)
        out.append(
            {
                "n": 0,
                "date": date_s,
                "time": time_s,
                "id": rid,
                "parent": str(parent_id),
                "layer": layer,
                "kind": "reply",
                "tags": [],
                "text": body[:1200],
            }
        )
        if len(out) >= 40:
            break
    return out


def _cmoney_api_headers() -> Dict[str, str]:
    """偉權抓碼那組標頭。token 只從環境變數來，沒有就不帶 Authorization。"""
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-version": "2.0",
        "cmoneyapi-trace-context": '{"device":"Mozilla/5.0"}',
        "referer": USER_URL,
        "origin": "https://www.cmoney.tw",
    }
    try:
        from config import get_cmoney_auth_token

        token = get_cmoney_auth_token()
    except Exception:
        token = ""
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _api_member_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("creatorInfo") or {}
    if not isinstance(info, dict):
        info = {}
    return str(
        item.get("memberId")
        or item.get("creatorId")
        or info.get("memberId")
        or ""
    )


def _api_nickname(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    info = item.get("creatorInfo") or {}
    if not isinstance(info, dict):
        info = {}
    return str(item.get("nickname") or info.get("nickname") or "")


def _api_is_author(item: Any) -> bool:
    return _api_member_id(item) == AUTHOR_ID or AUTHOR_NAME in _api_nickname(item)


def _api_text(item: Any) -> str:
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


def _api_comment_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or item.get("commentId") or "").strip()


def _api_stamp(item: Any, now: Optional[datetime] = None) -> tuple[str, str]:
    raw = (item or {}).get("createTime") if isinstance(item, dict) else ""
    if raw in (None, ""):
        raw = (item or {}).get("createdAt") if isinstance(item, dict) else ""
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
        try:
            n = int(raw)
            if n > 10_000_000_000:
                n = n / 1000.0
            dt = datetime.fromtimestamp(n, TAIPEI)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except (OSError, OverflowError, ValueError):
            pass
    date_s, time_s = parse_published(str(raw or ""))
    if date_s:
        return date_s, time_s
    return parse_display_time(str(raw or ""), now=now)


def _api_children(item: Any) -> List[Dict[str, Any]]:
    if not isinstance(item, dict):
        return []
    for key in ("replies", "subComments", "childComments"):
        chunk = item.get(key)
        if isinstance(chunk, list):
            return [c for c in chunk if isinstance(c, dict)]
    return []


def _api_child_count(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    kids = _api_children(item)
    if kids:
        return len(kids)
    for key in ("replyCount", "repliesCount"):
        try:
            n = int(item.get(key) or 0)
        except (TypeError, ValueError):
            n = 0
        if n:
            return n
    return 0


def _reply_row(
    item: Dict[str, Any],
    *,
    parent_id: str,
    layer: int,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    body = _api_text(item)
    imgs = chart_urls(json.dumps(item, ensure_ascii=False))
    body = _append_charts(body, imgs, limit=4)
    if _reply_noise(body):
        return None
    cid = _api_comment_id(item)
    rid = f"{parent_id}:c{cid}" if cid else f"{parent_id}:t{body[:40]}"
    date_s, time_s = _api_stamp(item, now=now)
    return {
        "n": 0,
        "date": date_s,
        "time": time_s,
        "id": rid,
        "parent": str(parent_id),
        "layer": int(layer),
        "kind": "reply",
        "tags": [],
        "text": body[:1200],
    }


def _comment_list(payload: Any) -> List[Dict[str, Any]]:
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
        return _comment_list(data)
    result = payload.get("result")
    if isinstance(result, dict):
        return _comment_list(result)
    return []


def parse_api_author_replies(
    payload: Any,
    *,
    parent_id: str,
    now: Optional[datetime] = None,
    nested_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """JSON 留言只收飆大本人。路人樓裡的自回（二層）仍收。"""
    nested_by_id = nested_by_id or {}
    out: List[Dict[str, Any]] = []
    seen = set()
    for cm in _comment_list(payload):
        if _api_is_author(cm):
            row = _reply_row(cm, parent_id=parent_id, layer=1, now=now)
            if row and row["text"] not in seen:
                seen.add(row["text"])
                out.append(row)
        kids = list(_api_children(cm))
        extra = nested_by_id.get(_api_comment_id(cm) or "") or []
        for sub in kids + extra:
            if not _api_is_author(sub):
                continue
            row = _reply_row(sub, parent_id=parent_id, layer=2, now=now)
            if row and row["text"] not in seen:
                seen.add(row["text"])
                out.append(row)
        if len(out) >= 40:
            break
    return out


_LAST_COMMENT_API: Dict[str, Any] = {"http": 0, "replies": 0, "aid": ""}


def comment_api_status() -> Dict[str, Any]:
    """給 /health：只有狀態碼與則數，不准帶 token。"""
    return {
        "http": int(_LAST_COMMENT_API.get("http") or 0),
        "replies": int(_LAST_COMMENT_API.get("replies") or 0),
        "aid": str(_LAST_COMMENT_API.get("aid") or ""),
    }


def _note_comment_api(*, http: int = 0, replies: Optional[int] = None, aid: str = "") -> None:
    _LAST_COMMENT_API["http"] = int(http or 0)
    if replies is not None:
        _LAST_COMMENT_API["replies"] = int(replies)
    if aid:
        _LAST_COMMENT_API["aid"] = str(aid)


def _get_json(session: requests.Session, url: str, timeout: int = 12) -> Any:
    try:
        resp = session.get(url, headers=_cmoney_api_headers(), timeout=timeout)
    except Exception:
        _note_comment_api(http=0)
        return None
    code = int(getattr(resp, "status_code", 0) or 0)
    _note_comment_api(http=code)
    if code != 200:
        logger.info("飆大留言 JSON http=%s url=%s", code, url.split("?")[0])
        return None
    try:
        return resp.json()
    except Exception:
        return None


def fetch_author_replies_api(
    article_id: str,
    session: Optional[requests.Session] = None,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """偉權抓碼：Comments?startCommentIndex=0&fetch=-100，缺樓中樓再打 Replies。"""
    try:
        from config import get_cmoney_auth_token

        if not get_cmoney_auth_token():
            _note_comment_api(http=0, replies=0)
            return []
    except Exception:
        _note_comment_api(http=0, replies=0)
        return []
    aid = str(article_id or "").strip()
    if not aid:
        return []
    sess = session or _session()
    payload = _get_json(
        sess,
        f"https://www.cmoney.tw/api/mach/api/Article/{aid}/Comments"
        f"?startCommentIndex=0&fetch=-100",
    )
    if payload is None:
        logger.info("飆大留言 JSON 讀不到 id=%s（沒 token 或非 200）", aid)
        return []
    nested: Dict[str, List[Dict[str, Any]]] = {}
    for cm in _comment_list(payload):
        cid = _api_comment_id(cm)
        if not cid or _api_children(cm) or _api_child_count(cm) <= 0:
            continue
        extra = _get_json(
            sess,
            f"https://www.cmoney.tw/api/mach/api/Article/{aid}/Comment/{cid}/Replies"
            f"?fetch=-50",
        )
        kids = _comment_list(extra) if extra is not None else []
        if not kids and isinstance(extra, dict):
            kids = _api_children(extra)
        if kids:
            nested[cid] = kids
    rows = parse_api_author_replies(
        payload, parent_id=aid, now=now, nested_by_id=nested
    )
    _note_comment_api(
        http=int(_LAST_COMMENT_API.get("http") or 200),
        replies=len(rows),
        aid=aid,
    )
    return rows


def _save_corpus(path: str, blob: Dict[str, Any], posts: List[Dict[str, Any]]) -> None:
    posts.sort(
        key=lambda p: (
            str(p.get("date") or ""),
            str(p.get("time") or ""),
            0 if p.get("kind") != "reply" else 1,
            str(p.get("id") or ""),
        )
    )
    for i, p in enumerate(posts, 1):
        p["n"] = i
    dates = [str(p.get("date") or "") for p in posts if p.get("date")]
    n_post = sum(1 for p in posts if (p.get("kind") or "post") != "reply")
    n_rep = sum(1 for p in posts if p.get("kind") == "reply")
    blob["posts"] = posts
    blob["n"] = n_post
    blob["replies"] = n_rep
    blob["from"] = min(dates) if dates else blob.get("from") or ""
    blob["to"] = max(dates) if dates else blob.get("to") or ""
    blob["source"] = blob.get("source") or "drive-1709-public"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    os.replace(tmp, path)
    try:
        load_corpus_cache_clear()
    except Exception:
        pass


def _is_git_seed_path(path: str) -> bool:
    """git 裡 520 篇種子不准當融合起點、也不准寫回。"""
    return os.path.basename(os.path.abspath(path or "")) == "corpus_index.json"


def _merge_row(posts: List[Dict[str, Any]], by_id: Dict[str, Dict[str, Any]], row: Dict[str, Any]) -> str:
    aid = str(row.get("id") or "")
    if not aid:
        return ""
    if not is_biaoke_voice(str(row.get("text") or "")):
        return ""
    old = by_id.get(aid)
    if old:
        changed = False
        for k in ("date", "time", "tags", "text", "parent", "layer", "kind"):
            if k in row and old.get(k) != row.get(k):
                old[k] = row[k]
                changed = True
        return "updated" if changed else ""
    posts.append(row)
    by_id[aid] = row
    return "added"


def purge_alien_overlay(db_path: str) -> int:
    """把不是飆客聲音的 overlay 列清掉。側欄誤抓的長文不要留在庫裡。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return 0
        rows = conn.execute("SELECT id, text FROM biaoke_posts").fetchall()
        drop = [str(rid) for rid, text in rows if not is_biaoke_voice(str(text or ""))]
        for rid in drop:
            conn.execute("DELETE FROM biaoke_posts WHERE id=?", (rid,))
            n += 1
        if n:
            conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return n


def ingest_public_posts(
    corpus_path: str = "",
    *,
    db_path: str = "",
    session: Optional[requests.Session] = None,
    max_ids: int = 12,
    refresh_latest: int = REFRESH_LATEST,
) -> Dict[str, Any]:
    """抓公開個人頁最新文＋最近三篇的飆大一／二層回覆。失敗不改海選。

    融合基準永遠是 Drive 那一千七百多則公開主文（archive_1709.json.gz），
    不是 git 裡 520 篇種子。空檔／指定 dump 路徑也不能從 0 或 520 起算。
    正式碟：先把缺的 1709 列補進 biaoke_posts，再 UPSERT 盤中新文。
    corpus_index.json 不准當起點、不准寫回。
    討論串只重讀個人頁最新 refresh_latest 篇（預設 3）；更早的主文他幾乎不回。
    新 id 仍會抓主文（含他改過的正文）。
    """
    dest = str(corpus_path or "").strip()
    dbp = str(db_path or "").strip()
    if not dbp and not dest:
        try:
            from config import get_db_path

            dbp = str(get_db_path() or "").strip()
        except Exception:
            dbp = ""
    sess = session or _session()
    stats = {
        "fetched": 0,
        "added": 0,
        "updated": 0,
        "replies": 0,
        "n": 0,
        "db": 0,
        "links": 0,
        "baseline": "archive_1709",
    }
    if dbp:
        ensure_biaoke_posts_table(dbp)
        try:
            seed_biaoke_archive(dbp)
        except Exception:
            logger.exception("飆大 1709 融合底圖寫庫失敗")
        try:
            stats["purged"] = purge_alien_overlay(dbp)
        except Exception:
            logger.exception("飆大清掉誤抓別人的文失敗")

    blob = load_corpus(dbp if dbp and os.path.isfile(dbp) else None)
    posts: List[Dict[str, Any]] = list(blob.get("posts") or [])
    by_id = {str(p.get("id") or ""): p for p in posts}
    stats["n"] = sum(1 for p in posts if (p.get("kind") or "post") != "reply")

    try:
        user_html = fetch_html(USER_URL, sess)
        ids = parse_user_article_ids(user_html)[: max(1, int(max_ids))]
    except Exception:
        logger.exception("飆大公開頁讀不到")
        return {**stats, "ok": False}
    if not ids:
        return {**stats, "ok": False, "reason": "no_ids"}

    added = 0
    updated = 0
    replies = 0
    touched: List[str] = []
    events: List[Dict[str, Any]] = []
    refresh_n = max(1, min(int(refresh_latest), max(1, len(ids))))
    for i, aid in enumerate(ids):
        known = aid in by_id and (by_id[aid].get("kind") or "post") != "reply"
        if known and i >= refresh_n:
            continue
        try:
            html_text = fetch_html(ARTICLE_URL.format(aid=aid), sess)
            if not html_text:
                continue
            row = parse_article_html(aid, html_text)
        except Exception:
            logger.debug("飆大單篇失敗 id=%s", aid, exc_info=True)
            continue
        stats["fetched"] += 1
        if row:
            hit = _merge_row(posts, by_id, row)
            if hit:
                touched.append(str(row.get("id") or aid))
                events.append(dict(row))
            if hit == "added":
                added += 1
            elif hit == "updated":
                updated += 1
        if i < refresh_n:
            api_reps = []
            try:
                api_reps = fetch_author_replies_api(str(aid), sess)
            except Exception:
                logger.debug("飆大留言 JSON 失敗 id=%s", aid, exc_info=True)
            html_reps = parse_author_replies(html_text, parent_id=str(aid))
            by_text = {}
            for rep in html_reps + api_reps:
                key = str(rep.get("id") or "") or str(rep.get("text") or "")
                if key:
                    by_text[key] = rep
            for rep in by_text.values():
                hit = _merge_row(posts, by_id, rep)
                if hit:
                    replies += 1
                    rid = str(rep.get("id") or "")
                    if rid:
                        touched.append(rid)
                    events.append(dict(rep))
    n_post = sum(1 for p in posts if (p.get("kind") or "post") != "reply")
    if dbp:
        ensure_biaoke_posts_table(dbp)
        uniq = []
        seen = set()
        for aid in touched:
            if aid and aid not in seen and aid in by_id:
                seen.add(aid)
                uniq.append(by_id[aid])
        stats["db"] = upsert_biaoke_posts(dbp, uniq)
        try:
            from biaoke_digest import record_ingest_events

            stats["inbox"] = record_ingest_events(dbp, events)
        except Exception:
            logger.exception("飆大未讀匣寫入失敗")
        try:
            from biaoke_link import link_biaoke_db

            linked = link_biaoke_db(dbp)
            stats["links"] = int(linked.get("mentions") or 0)
            from biaoke_walk import walk_biaoke_posts

            walked = walk_biaoke_posts(dbp, fetch_missing=False)
            stats["facts"] = int(walked.get("facts") or 0)
            try:
                from biaoke_walk import run_quote_month_backfill

                filled = run_quote_month_backfill(
                    dbp, limit=12, sleep_s=0.5, rewalk=True
                )
                stats["quote_months"] = int(filled.get("months") or 0)
            except Exception:
                logger.exception("飆大缺月日K續補失敗")
        except Exception:
            logger.exception("飆大公開文連到行情庫失敗")
        _after_ingest_analyze(dbp, events)
    if dest and not _is_git_seed_path(dest):
        _save_corpus(dest, blob, posts)
    else:
        load_corpus_cache_clear()
    stats.update(
        {
            "ok": True,
            "added": added,
            "updated": updated,
            "replies": replies,
            "n": n_post,
        }
    )
    if n_post < ARCHIVE_BASELINE_N:
        logger.warning(
            "飆大融合底圖不足 n=%s（應 >= %s，Drive 那一千七百多則）",
            n_post,
            ARCHIVE_BASELINE_N,
        )
    logger.info(
        "飆大公開匯入 added=%s updated=%s replies=%s n=%s db=%s baseline=archive_1709",
        added,
        updated,
        replies,
        stats["n"],
        stats.get("db") or 0,
    )
    return stats


def _after_ingest_analyze(db_path: str, events: Sequence[Dict[str, Any]]) -> None:
    """新文／樓下／改主文進庫後立刻建檔左證，不等下次開機。"""
    try:
        from biaoke_desk import load_corpus_cache_clear

        load_corpus_cache_clear()
    except Exception:
        pass
    try:
        from biaoke_why import ingest_why_events

        ingest_why_events(list(events or []), db_path)
    except Exception:
        logger.exception("飆大判斷鏈即時建檔失敗")
    try:
        from biaoke_weave import load_weave

        load_weave.cache_clear()
    except Exception:
        pass
    try:
        from biaoke_alert import maybe_push_drop_alert

        maybe_push_drop_alert(db_path, events)
    except Exception:
        logger.exception("飆大緊急推播略過")


def run_biaoke_ingest_quiet() -> None:
    """排程／輪詢用：失敗不影響 16:30 融合、不進海選。"""
    try:
        from config import get_db_path

        ingest_public_posts(db_path=get_db_path())
    except Exception:
        logger.exception("飆大定時匯入失敗")


def start_biaoke_poller() -> Optional[Any]:
    """常駐：盤中 10 分；其餘時間每 1 小時抓最新主文＋最近三篇樓下。GHA --once 不開。"""
    import threading
    import time as _time

    from config import daily_scheduler_enabled, is_once_mode

    if is_once_mode() or not daily_scheduler_enabled():
        return None

    def _loop() -> None:
        _time.sleep(90)
        while True:
            run_biaoke_ingest_quiet()
            wait = poll_wait_seconds()
            logger.info("飆大輪詢：%s 秒後再抓公開文／最新文回覆", wait)
            _time.sleep(max(30, int(wait)))

    t = threading.Thread(target=_loop, name="biaoke-poll", daemon=True)
    t.start()
    return t
