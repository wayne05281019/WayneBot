# -*- coding: utf-8 -*-
"""飆大公開發文＋最新文一二層回覆匯入。只抓 CMoney 公開頁，不進海選。

盤中 10 分、盤後到凌晨 1 點每 3 小時、夜間併入 06:30。
不准放 Bearer／localStorage／同學會 token。社團不抓。
只收飆大本人主文＋一／二層樓中樓（含回在別人留言裡的）＋他自己附的圖。
路人留言不收。公開 HTML 常常不帶留言正文：有 SSR 就收，沒有就只更新主文，不假裝聽到。
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
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
AFTER_EVERY_SEC = 3 * 60 * 60
NIGHT_EVERY_SEC = 3 * 60 * 60
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
_BODY_START = re.compile(
    r"(1[\.、．]\s*台指期|目前台股|今天盤後|大盤)",
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


def parse_user_article_ids(html_text: str) -> List[str]:
    """只收飆大自己個人頁的主文 id。側欄、別人文章、utm 分享連結不要。"""
    raw = html_text or ""
    m = _NUXT_FEED.search(raw)
    if m:
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
        if ids:
            return ids
    ids: List[str] = []
    seen = set()
    for aid in _HREF_OWN.findall(raw):
        if aid not in seen:
            seen.add(aid)
            ids.append(aid)
    if ids:
        return ids
    for aid in _ID_RE.findall(raw):
        if aid not in seen:
            seen.add(aid)
            ids.append(aid)
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
    if AUTHOR_NAME not in raw and f"/forum/user/{AUTHOR_ID}" not in raw:
        return None
    text = _strip_article_text(raw)
    if not date or not text:
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
    """盤中 10 分；收盤後到凌晨 1 點每 3 小時；1 點到 9 點等到開盤。週末 3 小時。"""
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    hm = dt.hour * 60 + dt.minute
    if dt.weekday() >= 5:
        return NIGHT_EVERY_SEC
    if 9 * 60 <= hm <= 13 * 60 + 40:
        return SESSION_EVERY_SEC
    if hm >= 13 * 60 + 40 or hm < 60:
        return AFTER_EVERY_SEC
    # 01:00～09:00：等到開盤再抓
    return max(60, 9 * 60 - hm) * 60


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


def ingest_public_posts(
    corpus_path: str = "",
    *,
    db_path: str = "",
    session: Optional[requests.Session] = None,
    max_ids: int = 12,
    refresh_latest: int = 4,
) -> Dict[str, Any]:
    """抓公開個人頁最新文＋最新兩篇的飆大一／二層回覆。失敗不改海選。

    融合基準永遠是 Drive 那一千七百多則公開主文（archive_1709.json.gz），
    不是 git 裡 520 篇種子。空檔／指定 dump 路徑也不能從 0 或 520 起算。
    正式碟：先把缺的 1709 列補進 biaoke_posts，再 UPSERT 盤中新文。
    corpus_index.json 不准當起點、不准寫回。
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
        "baseline": "archive_1709",
    }
    if dbp:
        ensure_biaoke_posts_table(dbp)
        try:
            seed_biaoke_archive(dbp)
        except Exception:
            logger.exception("飆大 1709 融合底圖寫庫失敗")

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
    refresh_n = max(1, int(refresh_latest))
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
            if hit == "added":
                added += 1
            elif hit == "updated":
                updated += 1
        if i < refresh_n:
            for rep in parse_author_replies(html_text, parent_id=str(aid)):
                hit = _merge_row(posts, by_id, rep)
                if hit:
                    replies += 1
                    rid = str(rep.get("id") or "")
                    if rid:
                        touched.append(rid)
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


def run_biaoke_ingest_quiet() -> None:
    """排程／輪詢用：失敗不影響 16:30 融合、不進海選。"""
    try:
        from config import get_db_path

        ingest_public_posts(db_path=get_db_path())
    except Exception:
        logger.exception("飆大定時匯入失敗")


def start_biaoke_poller() -> Optional[Any]:
    """常駐：盤中 10 分、盤後到凌晨 1 點每 3 小時抓飆大主文＋一／二層樓中樓。GHA --once 不開。"""
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
