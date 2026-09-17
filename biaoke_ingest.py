# -*- coding: utf-8 -*-
"""飆大公開發文＋最新文討論串匯入。不進海選。

交易日 08:00–09:00 每 10 分；09:01–13:30 每 3 分；13:30–15:00 每 10 分。
15:00 起到隔天 08:00、週末、國定假、颱風停市每 1 小時。
主文通常只改最新一篇。討論串每次都重讀最近兩則。
討論串要齊：他自己回、別人回他、他回別人（含回在很早留言、回文裡的回文）。
路人正文收進討論串、不當他的判斷。引號裡不是他的話。
主文走公開 HTML。樓下走同學會公開訪客 grant 打 Comments JSON。
樓中樓＝把該則留言 id 當 article 再打 Comments（不是 /Comment/…/Replies）。
對圖以主文點名的股票為準；附圖對不上主文就略過該圖。
不准把 Bearer／localStorage／帳密寫進 git。不准放 Bearer 字串當密鑰進 repo。CMONEY_AUTH_TOKEN 只當備援。
社團不抓。抓到新文立刻對官方 K 建檔，並做成判斷卡接到神經元。
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import time
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
SESSION_EVERY_SEC = 3 * 60  # 交易日 09:01–13:30
AFTER_EVERY_SEC = 1 * 60 * 60
NIGHT_EVERY_SEC = AFTER_EVERY_SEC  # 休市／週末／凌晨也每小時，不再等到開盤
PREOPEN_EVERY_SEC = 10 * 60  # 交易日 08:00–09:00
AFTER_CLOSE_EVERY_SEC = 10 * 60  # 交易日 13:30–15:00
PREOPEN_FROM_MIN = 8 * 60
PREOPEN_UNTIL_MIN = 9 * 60  # [08:00, 09:00)
SESSION_FROM_MIN = 9 * 60 + 1  # 09:01 才進 3 分
CLOSE_MIN = 13 * 60 + 30
AFTER_CLOSE_UNTIL_MIN = 15 * 60
AFTER_UNTIL_HOUR = 3  # 舊常數：排程已改成全天有抓，不再當停止線
REFRESH_LATEST = 2  # 視窗：最新兩則。平時只重讀最新一篇主文＋討論串
REFRESH_PREOPEN = 2  # 同一套；剛發新主文才連前一篇樓下
FRESH_POST_HOURS = 8  # 「剛剛發的」：這幾小時內才連前一篇討論串
GUEST_TOKEN_URL = "https://www.cmoney.tw/api/identity/token"
GUEST_CLIENT_ID = "cmstockcommunity-web"
GUEST_GRANT_TYPE = "guest"
_COMMENT_API_TIMEOUT = 12
_GUEST_TOKEN_CACHE: Dict[str, Any] = {"token": "", "expires_at": 0.0}
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
_NUXT_IIFE = re.compile(r"window\.__NUXT__=\(function\(([^)]*)\)\{")
_NUXT_ART_ITEM = re.compile(
    r'\{id:(?:"(\d{6,})"|([A-Za-z_$][\w$]*)),creatorId:(?:"(\d+)"|([A-Za-z_$][\w$]*))'
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
_CITE_RE = re.compile(r'^\s*[「『"“](.+?)[」』"”]\s*(.+)$', re.S)
_USER_HREF = re.compile(
    r'href="(?:https://www\.cmoney\.tw)?/forum/user/(\d+)"',
    re.I,
)

def split_author_cite(text: str) -> tuple[str, str]:
    """他習慣用引號包留言者的話，後面才是自己回答。引號裡不是他的判斷。"""
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    m = _CITE_RE.match(raw)
    if not m:
        return "", raw
    cite = re.sub(r"\s+", " ", m.group(1) or "").strip()
    spoken = str(m.group(2) or "").strip()
    if len(cite) < 2 or len(spoken) < 2:
        return "", raw
    return cite, spoken


def spoken_text(text: str) -> str:
    """回文只取他自己答的部分；引號裡的路人話丟掉。"""
    _cite, spoken = split_author_cite(text)
    return spoken or str(text or "").strip()


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
        r"(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{1,2})",
        s,
    )
    if not m:
        return "", ""
    y, mo, d, hh, mm = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", f"{int(hh):02d}:{int(mm):02d}"


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


def _charts_for_body(body: str, *blobs: str, limit: int = 6) -> str:
    """主文點名的股票對不上附圖就略過該圖。時間戳另用來鎖定文內那檔當下。"""
    urls = chart_urls(*blobs)
    try:
        from biaoke_charts import keep_charts_for_text

        urls = keep_charts_for_text(body, urls)
    except Exception:
        pass
    return _append_charts(body, urls, limit=limit)


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


def _split_js_args(src: str) -> List[str]:
    """切開 Nuxt IIFE 參數。字串／括號內的逗號不要切。"""
    args: List[str] = []
    buf: List[str] = []
    depth = 0
    in_str = ""
    esc = False
    for ch in src or "":
        if in_str:
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = ""
            continue
        if ch in ('"', "'"):
            in_str = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
            buf.append(ch)
            continue
        if ch in ")]}":
            depth -= 1
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return args


def _js_literal(raw: str) -> Any:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith('"') and s.endswith('"'):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    if s in ("true", "!0"):
        return True
    if s in ("false", "!1"):
        return False
    if s in ("null", "void 0"):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _nuxt_iife_env(html_text: str) -> Dict[str, Any]:
    """解開 window.__NUXT__=(function(aP,...){...}("184578674",...))。失敗就空。"""
    raw = html_text or ""
    m = _NUXT_IIFE.search(raw)
    if not m:
        return {}
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    if not params:
        return {}
    start = m.end()
    script_end = raw.find("</script>", start)
    chunk = raw[start : script_end if script_end > 0 else start + 400000]
    pos = chunk.rfind("}(")
    if pos < 0:
        return {}
    args_src = chunk[pos + 2 :].strip()
    args_src = re.sub(r"\)+\s*;?\s*$", "", args_src)
    args = _split_js_args(args_src)
    env: Dict[str, Any] = {}
    for key, val in zip(params, args):
        env[key] = _js_literal(val)
    return env


def _nuxt_token(raw: str, env: Dict[str, Any]) -> str:
    tok = str(raw or "").strip().strip('"')
    if not tok:
        return ""
    if tok in env and env[tok] not in (None, ""):
        return str(env[tok])
    return tok


def parse_user_article_ids(html_text: str) -> List[str]:
    """只收飆客自己個人頁的主文 id。側欄、別人文章、utm 分享連結不要。

    只吃 Nuxt SSR 的 articles[]（帶 creatorId，可濾掉側欄）。
    純 href 不夠——側欄／推薦文也是 /forum/article/…。
    最新一篇常被縮成 id:aP（數字在 IIFE 參數裡），不能只認 id:"184…"。
    """
    raw = html_text or ""
    start = raw.find("articles:[")
    if start < 0:
        return []
    env = _nuxt_iife_env(raw)
    chunk = raw[start : start + 180000]
    ids: List[str] = []
    seen = set()
    owner_tok = ""
    owner_val = ""
    for qid, vid, qcid, vcid in _NUXT_ART_ITEM.findall(chunk):
        aid_tok = qid or vid
        cid_tok = qcid or vcid
        aid = _nuxt_token(aid_tok, env)
        cid = _nuxt_token(cid_tok, env)
        if not re.fullmatch(r"\d{6,}", aid):
            continue
        if not owner_tok:
            owner_tok = cid_tok
            owner_val = cid
        same = cid_tok == owner_tok or (owner_val and cid == owner_val)
        if not same:
            continue
        if aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
        if len(ids) >= 20:
            break
    if ids:
        return ids
    m = _NUXT_FEED.search(raw)
    if not m:
        return []
    owner = m.group(2)
    chunk = raw[m.start() : m.start() + 180000]
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
    text = _charts_for_body(text, main)
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


def _open_calendar_day(dt: datetime) -> bool:
    ymd = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_tw_open_calendar_day

        return bool(is_tw_open_calendar_day(ymd))
    except Exception:
        return dt.weekday() < 5


def in_preopen_window(now: Optional[datetime] = None) -> bool:
    """台股交易日開盤前：08:00 ≤ t < 09:00。週末／國定假／颱風停市不算。"""
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    if not _open_calendar_day(dt):
        return False
    hm = dt.hour * 60 + dt.minute
    return PREOPEN_FROM_MIN <= hm < PREOPEN_UNTIL_MIN


def refresh_latest_now(now: Optional[datetime] = None) -> int:
    """掃窗固定最新兩則。真正重讀哪幾串由 ingest 依「剛發／第一次看到」決定。"""
    return REFRESH_LATEST


def _row_is_fresh(
    row: Optional[Dict[str, Any]],
    now: Optional[datetime] = None,
    *,
    hours: int = FRESH_POST_HOURS,
) -> bool:
    """最新主文是剛剛發的才連前一篇樓下。沒日期就不當剛發。"""
    if not row:
        return False
    day = str(row.get("date") or "")
    hm = str(row.get("time") or "00:00") or "00:00"
    try:
        posted = datetime.strptime(f"{day} {hm[:5]}", "%Y-%m-%d %H:%M").replace(
            tzinfo=TAIPEI
        )
    except ValueError:
        return False
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    return (dt - posted) <= timedelta(hours=max(1, int(hours)))


def poll_wait_seconds(now: Optional[datetime] = None) -> int:
    """交易日 08:00–09:00 每 10 分；09:01–13:30 每 3 分；13:30–15:00 每 10 分；其餘每 1 小時。

    08:59 不准睡 10 分睡過 09:01。09:00 整點最多等到 09:01。
    討論串（自己回、別人回他、他回別人）跟主文同一套節奏。
    不准再用「等到開盤」把凌晨到 8 點、週末、颱風天空掉。
    """
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    open_day = _open_calendar_day(dt)
    hm = dt.hour * 60 + dt.minute
    if open_day and PREOPEN_FROM_MIN <= hm < SESSION_FROM_MIN:
        remain = max(30, (SESSION_FROM_MIN - hm) * 60)
        if hm < PREOPEN_UNTIL_MIN:
            return min(PREOPEN_EVERY_SEC, remain)
        return remain
    if open_day and SESSION_FROM_MIN <= hm <= CLOSE_MIN:
        return SESSION_EVERY_SEC
    if open_day and CLOSE_MIN < hm < AFTER_CLOSE_UNTIL_MIN:
        remain = max(30, (AFTER_CLOSE_UNTIL_MIN - hm) * 60)
        return min(AFTER_CLOSE_EVERY_SEC, remain)
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


def _html_comment_member_id(chunk: str) -> str:
    """這則留言塊的作者＝第一個 /forum/user/ 連結。正文提到他的名字不算他。"""
    m = _USER_HREF.search(chunk or "")
    return m.group(1) if m else ""


def parse_author_replies(
    html_text: str,
    *,
    parent_id: str,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """只收飆大自己的一、二、三層樓中樓。路人正文不收。

    第一層＝直接回主文。第二層＝回在別人留言裡。第三層＝回文裡的回文。三層都要。
    他自己附的 attachment 圖一併留下。公開頁沒 SSR 就空列表。
    認人只看會員號，不看正文有沒有他的名字。
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
        if _html_comment_member_id(ch) != AUTHOR_ID:
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
        if not body:
            plain = _plain(ch)
            plain = re.sub(rf"{AUTHOR_NAME}|讚|回覆|超級幫手|Lv\.\d+", " ", plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            if 8 <= len(plain) <= 400 and not _reply_noise(plain):
                body = plain
        body = _charts_for_body(body, ch, limit=4)
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


def _cmoney_api_headers(token: str = "") -> Dict[str, str]:
    """同學會 Comments 標頭。token 由呼叫端傳入，沒有就不帶 Authorization。"""
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-version": "2.0",
        "cmoneyapi-trace-context": '{"device":"Mozilla/5.0"}',
        "referer": USER_URL,
        "origin": "https://www.cmoney.tw",
    }
    raw = str(token or "").strip()
    if not raw:
        try:
            from config import get_cmoney_auth_token

            raw = get_cmoney_auth_token()
        except Exception:
            raw = ""
    if raw:
        headers["authorization"] = f"Bearer {raw}"
    return headers


def _clear_guest_token_cache() -> None:
    _GUEST_TOKEN_CACHE["token"] = ""
    _GUEST_TOKEN_CACHE["expires_at"] = 0.0


def _fetch_guest_access_token(session: Optional[requests.Session] = None) -> str:
    """同學會網頁每個訪客都會拿的 grant，不是登入帳密。不准寫進 git／log。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "WAYNE_CMONEY_GUEST_TEST"
    ):
        return ""
    cached = str(_GUEST_TOKEN_CACHE.get("token") or "")
    expires_at = float(_GUEST_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached and time.time() < expires_at - 60:
        return cached
    try:
        sess = session if session is not None else requests
        resp = sess.post(
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
            timeout=_COMMENT_API_TIMEOUT,
        )
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return ""
        payload = resp.json() if getattr(resp, "content", None) else {}
    except Exception:
        return ""
    token = str((payload or {}).get("access_token") or "").strip()
    if not token:
        return ""
    try:
        ttl = int((payload or {}).get("expires_in") or 0)
    except (TypeError, ValueError):
        ttl = 0
    _GUEST_TOKEN_CACHE["token"] = token
    _GUEST_TOKEN_CACHE["expires_at"] = time.time() + max(ttl, 60)
    return token


def _env_cmoney_token() -> str:
    try:
        from config import get_cmoney_auth_token

        return get_cmoney_auth_token()
    except Exception:
        return ""


def _comment_tokens(session: Optional[requests.Session] = None) -> List[str]:
    tokens: List[str] = []
    guest = _fetch_guest_access_token(session)
    if guest:
        tokens.append(guest)
    env_token = _env_cmoney_token()
    if env_token and env_token not in tokens:
        tokens.append(env_token)
    return tokens


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
    if _api_member_id(item) == AUTHOR_ID:
        return True
    return _api_nickname(item) == AUTHOR_NAME


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
    n = len(_api_children(item))
    for key in ("replyCount", "repliesCount", "commentCount"):
        try:
            n = max(n, int(item.get(key) or 0))
        except (TypeError, ValueError):
            n = n
    return n


def _reply_row(
    item: Dict[str, Any],
    *,
    parent_id: str,
    layer: int,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    body = _api_text(item)
    body = _charts_for_body(body, json.dumps(item, ensure_ascii=False), limit=4)
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
        "reply_to": "",
        "reply_to_text": "",
        "voice": "author",
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


def parse_api_thread(
    payload: Any,
    *,
    parent_id: str,
    now: Optional[datetime] = None,
    nested_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    keep_bystander: bool = True,
) -> List[Dict[str, Any]]:
    """JSON 留言：他自己回、別人回他、他回別人。路人 kind=bystander，不當他的判斷。

    一／二／三層都收。第四層起不往下走。
    """
    nested_by_id = nested_by_id or {}
    out: List[Dict[str, Any]] = []
    seen = set()

    def walk(items: Sequence[Any], layer: int, parent_cm: Optional[Dict[str, Any]] = None) -> None:
        for cm in items:
            if not isinstance(cm, dict):
                continue
            cid = _api_comment_id(cm)
            if _api_is_author(cm):
                row = _reply_row(cm, parent_id=parent_id, layer=layer, now=now)
                if row:
                    if parent_cm is not None and not _api_is_author(parent_cm):
                        row["reply_to"] = _api_comment_id(parent_cm)
                        row["reply_to_text"] = _api_text(parent_cm)[:240]
                        row["layer"] = max(int(row.get("layer") or 2), 2)
                    key = row["text"]
                    if key not in seen:
                        seen.add(key)
                        out.append(row)
            elif keep_bystander:
                row = _reply_row(cm, parent_id=parent_id, layer=layer, now=now)
                if row:
                    row["kind"] = "bystander"
                    row["voice"] = "bystander"
                    if parent_cm is not None:
                        row["reply_to"] = _api_comment_id(parent_cm)
                        row["reply_to_text"] = _api_text(parent_cm)[:240]
                    key = "b:" + (cid or row["text"])
                    if key not in seen:
                        seen.add(key)
                        out.append(row)
            kids = list(_api_children(cm))
            extra = nested_by_id.get(cid or "") or []
            if extra:
                have = {_api_comment_id(k) for k in kids}
                for sub in extra:
                    sid = _api_comment_id(sub)
                    if sid and sid in have:
                        continue
                    kids.append(sub)
            if kids and layer < 3:
                walk(kids, layer + 1, cm)

    walk(_comment_list(payload), 1, None)
    return out


def parse_api_author_replies(
    payload: Any,
    *,
    parent_id: str,
    now: Optional[datetime] = None,
    nested_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """JSON 留言只收飆大本人。路人樓裡的自回、回文裡的回文都收，層數最多三。"""
    rows = parse_api_thread(
        payload,
        parent_id=parent_id,
        now=now,
        nested_by_id=nested_by_id,
        keep_bystander=False,
    )
    return [r for r in rows if r.get("kind") == "reply"]


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


def _get_json(
    session: requests.Session,
    url: str,
    timeout: int = 12,
    token: str = "",
) -> Any:
    payload, _code = _get_json_resp(session, url, timeout=timeout, token=token)
    return payload


def _get_json_resp(
    session: requests.Session,
    url: str,
    timeout: int = 12,
    token: str = "",
) -> tuple[Any, int]:
    try:
        resp = session.get(
            url, headers=_cmoney_api_headers(token), timeout=timeout
        )
    except Exception:
        _note_comment_api(http=0)
        return None, 0
    code = int(getattr(resp, "status_code", 0) or 0)
    _note_comment_api(http=code)
    if code != 200:
        logger.info("飆大留言 JSON http=%s url=%s", code, url.split("?")[0])
        return None, code
    try:
        return resp.json(), code
    except Exception:
        return None, code


def _fetch_comment_pages(
    sess: requests.Session, aid: str, auth: str
) -> tuple[List[Dict[str, Any]], int]:
    comments: List[Dict[str, Any]] = []
    seen: set[str] = set()
    start_index = 0
    status = 0
    for _ in range(8):
        url = (
            f"https://www.cmoney.tw/api/mach/api/Article/{aid}/Comments"
            f"?startCommentIndex={int(start_index)}&fetch=-100"
        )
        payload, status = _get_json_resp(
            sess, url, timeout=_COMMENT_API_TIMEOUT, token=auth
        )
        if status != 200 or payload is None:
            return comments, status
        page = _comment_list(payload)
        for cm in page:
            cid = _api_comment_id(cm)
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
    return comments, status


def fetch_author_replies_api(
    article_id: str,
    session: Optional[requests.Session] = None,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """訪客 grant 打 Comments 分頁；缺樓中樓再打 Replies。401 換備援 token。"""
    aid = str(article_id or "").strip()
    if not aid:
        _note_comment_api(http=0, replies=0)
        return []
    tokens = _comment_tokens(session)
    if not tokens:
        _note_comment_api(http=0, replies=0)
        return []
    sess = session or _session()
    last_status = 0
    for auth in tokens:
        rows, status = _fetch_author_replies_with_token(
            aid, auth, sess, now=now, keep_bystander=False
        )
        last_status = int(status or 0)
        if status == 200:
            _note_comment_api(http=200, replies=len(rows), aid=aid)
            return rows
        _note_comment_api(http=last_status, replies=0, aid=aid)
        if status not in (401, 403):
            logger.info("飆大留言 JSON 讀不到 id=%s http=%s", aid, last_status)
            return []
    logger.info("飆大留言 JSON 讀不到 id=%s http=%s", aid, last_status)
    return []


def fetch_article_thread_api(
    article_id: str,
    session: Optional[requests.Session] = None,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """整串：作者自回＋路人回他＋他回路人。路人 kind=bystander。"""
    aid = str(article_id or "").strip()
    if not aid:
        _note_comment_api(http=0, replies=0)
        return []
    tokens = _comment_tokens(session)
    if not tokens:
        _note_comment_api(http=0, replies=0)
        return []
    sess = session or _session()
    last_status = 0
    for auth in tokens:
        rows, status = _fetch_author_replies_with_token(
            aid, auth, sess, now=now, keep_bystander=True
        )
        last_status = int(status or 0)
        if status == 200:
            n_auth = sum(1 for r in rows if r.get("kind") == "reply")
            _note_comment_api(http=200, replies=n_auth, aid=aid)
            return rows
        _note_comment_api(http=last_status, replies=0, aid=aid)
        if status not in (401, 403):
            logger.info("飆大討論串 JSON 讀不到 id=%s http=%s", aid, last_status)
            return []
    logger.info("飆大討論串 JSON 讀不到 id=%s http=%s", aid, last_status)
    return []


def _merge_comment_kids(
    inline: Sequence[Any], extra: Sequence[Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for cm in list(inline or []) + list(extra or []):
        if not isinstance(cm, dict):
            continue
        cid = _api_comment_id(cm)
        key = cid or f"anon:{len(out)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(cm)
    return out


def _fetch_replies_payload(
    sess: requests.Session, aid: str, cid: str, auth: str
) -> tuple[List[Dict[str, Any]], int]:
    """樓中樓＝該則留言自己當 article 再打 Comments。舊 Replies 路徑會 404。"""
    extra, extra_status = _get_json_resp(
        sess,
        f"https://www.cmoney.tw/api/mach/api/Article/{cid}/Comments"
        f"?startCommentIndex=0&fetch=-50",
        timeout=_COMMENT_API_TIMEOUT,
        token=auth,
    )
    kids = _comment_list(extra) if extra is not None else []
    if not kids and extra_status == 404:
        extra, extra_status = _get_json_resp(
            sess,
            f"https://www.cmoney.tw/api/mach/api/Article/{aid}/Comment/{cid}/Replies"
            f"?fetch=-50",
            timeout=_COMMENT_API_TIMEOUT,
            token=auth,
        )
        kids = _comment_list(extra) if extra is not None else []
    if not kids and isinstance(extra, dict):
        kids = _api_children(extra)
    return kids, extra_status


def _fill_nested_replies(
    sess: requests.Session,
    aid: str,
    auth: str,
    comments: Sequence[Dict[str, Any]],
) -> tuple[Dict[str, List[Dict[str, Any]]], int]:
    """缺的樓中樓再打 Replies。回文裡還有回文也走一遍。"""
    nested: Dict[str, List[Dict[str, Any]]] = {}
    status = 200
    queue: List[Dict[str, Any]] = [c for c in comments if isinstance(c, dict)]
    seen: set[str] = set()
    pulls = 0
    while queue and pulls < 150:
        cm = queue.pop(0)
        cid = _api_comment_id(cm)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        kids = list(_api_children(cm))
        count = _api_child_count(cm)
        if count > len(kids):
            extra, extra_status = _fetch_replies_payload(sess, aid, cid, auth)
            pulls += 1
            if extra_status not in (0, 200):
                status = extra_status
            kids = _merge_comment_kids(kids, extra)
        if kids:
            nested[cid] = kids
            queue.extend(kids)
    return nested, status


def _fetch_author_replies_with_token(
    aid: str,
    auth: str,
    sess: requests.Session,
    *,
    now: Optional[datetime] = None,
    keep_bystander: bool = False,
) -> tuple[List[Dict[str, Any]], int]:
    comments, status = _fetch_comment_pages(sess, aid, auth)
    if status != 200:
        return [], status
    nested, nest_status = _fill_nested_replies(sess, aid, auth, comments)
    if nest_status not in (0, 200):
        status = nest_status
    rows = parse_api_thread(
        comments,
        parent_id=aid,
        now=now,
        nested_by_id=nested,
        keep_bystander=keep_bystander,
    )
    if not keep_bystander:
        rows = [r for r in rows if r.get("kind") == "reply"]
    return rows, status


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
    if str(row.get("kind") or "") == "bystander" or str(row.get("voice") or "") == "bystander":
        return ""
    if not is_biaoke_voice(str(row.get("text") or "")):
        return ""
    old = by_id.get(aid)
    if old:
        changed = False
        for k in (
            "date",
            "time",
            "tags",
            "text",
            "parent",
            "layer",
            "kind",
            "reply_to",
            "reply_to_text",
            "voice",
        ):
            if k in row and old.get(k) != row.get(k):
                old[k] = row[k]
                changed = True
        return "updated" if changed else ""
    posts.append(row)
    by_id[aid] = row
    return "added"


_THREAD_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_thread (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL DEFAULT '',
    reply_to TEXT NOT NULL DEFAULT '',
    layer INTEGER NOT NULL DEFAULT 1,
    voice TEXT NOT NULL DEFAULT 'bystander',
    date TEXT NOT NULL DEFAULT '',
    time TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT ''
);
"""


def upsert_biaoke_thread(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    """路人樓＋他回路人的上下文。正文不當飆大判斷。"""
    if not db_path or not rows:
        return 0
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        conn.executescript(_THREAD_DDL)
        now = taipei_now().strftime("%Y-%m-%dT%H:%M:%S")
        for row in rows:
            rid = str(row.get("id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not rid or not text:
                continue
            conn.execute(
                """
                INSERT INTO biaoke_thread(
                    id, article_id, reply_to, layer, voice, date, time, text, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    article_id=excluded.article_id,
                    reply_to=excluded.reply_to,
                    layer=excluded.layer,
                    voice=excluded.voice,
                    date=excluded.date,
                    time=excluded.time,
                    text=excluded.text,
                    fetched_at=excluded.fetched_at
                """,
                (
                    rid,
                    str(row.get("parent") or ""),
                    str(row.get("reply_to") or ""),
                    int(row.get("layer") or 1),
                    str(row.get("voice") or row.get("kind") or "bystander"),
                    str(row.get("date") or ""),
                    str(row.get("time") or ""),
                    text[:1200],
                    now,
                ),
            )
            n += 1
        conn.commit()
    except sqlite3.Error:
        logger.debug("討論串路人樓寫不進", exc_info=True)
        return 0
    finally:
        conn.close()
    return n


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
    """抓公開個人頁最新文＋最新討論串的飆大一／二／三層回覆。失敗不改海選。

    融合基準永遠是 Drive 那一千七百多則公開主文（archive_1709.json.gz），
    不是 git 裡 520 篇種子。空檔／指定 dump 路徑也不能從 0 或 520 起算。
    正式碟：先把缺的 1709 列補進 biaoke_posts，再 UPSERT 盤中新文。
    corpus_index.json 不准當起點、不准寫回。
    已知主文：只重讀最新一篇正文。討論串每次重讀最近兩則（含回在很早留言、一／二／三層回文）。
    新 id 第一次進來連樓下也收。
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
    window = max(1, min(int(refresh_latest or REFRESH_LATEST), 2))
    for i, aid in enumerate(ids):
        known = aid in by_id and (by_id[aid].get("kind") or "post") != "reply"
        if not known:
            want_body = i < window
            want_thread = i < window
        else:
            want_body = i == 0
            want_thread = i < window
        if not want_body and not want_thread:
            continue
        html_text = ""
        row: Optional[Dict[str, Any]] = None
        hit = ""
        if want_body:
            try:
                html_text = fetch_html(ARTICLE_URL.format(aid=aid), sess)
                if html_text:
                    row = parse_article_html(aid, html_text)
            except Exception:
                logger.debug("飆大單篇失敗 id=%s", aid, exc_info=True)
                html_text = ""
                row = None
            if html_text:
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
        if not want_thread:
            continue
        thread_rows: List[Dict[str, Any]] = []
        try:
            thread_rows = fetch_article_thread_api(str(aid), sess)
        except Exception:
            logger.debug("飆大討論串 JSON 失敗 id=%s", aid, exc_info=True)
        api_reps = [
            r for r in thread_rows if (r.get("kind") or "reply") == "reply"
        ]
        bystanders = [r for r in thread_rows if r.get("kind") == "bystander"]
        html_reps = (
            parse_author_replies(html_text, parent_id=str(aid)) if html_text else []
        )
        by_text = {}
        for rep in html_reps + api_reps:
            key = str(rep.get("id") or "") or str(rep.get("text") or "")
            if key:
                by_text[key] = rep
        for rep in by_text.values():
            rhit = _merge_row(posts, by_id, rep)
            if rhit:
                replies += 1
                rid = str(rep.get("id") or "")
                if rid:
                    touched.append(rid)
                events.append(dict(rep))
        if dbp and bystanders:
            try:
                stats["thread"] = int(stats.get("thread") or 0) + upsert_biaoke_thread(
                    dbp, bystanders
                )
            except Exception:
                logger.exception("飆大路人樓寫入失敗")
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
            from kline_hop import refresh_biaoke_minutes

            stats["minutes"] = refresh_biaoke_minutes(dbp)
        except Exception:
            logger.exception("飆大日盤15分續補失敗")
        try:
            from biaoke_tape import refresh_published_official

            stats["official"] = refresh_published_official(dbp)
        except Exception:
            logger.exception("飆大官方收盤補寫失敗")
        if uniq:
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
        else:
            stats["skipped_walk"] = True
    if dbp:
        try:
            from biaoke_absorb import absorb_slot_id, run_absorb, taipei_now

            slot = absorb_slot_id(taipei_now())
            if slot:
                stats["absorb"] = run_absorb(dbp, slot=slot)
        except Exception:
            logger.exception("飆大神經元彙整窗略過")
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
    """抓到就存官方 tape、緊急推播、輔助匣。神經元等台北 02:00／開市日 13:00。"""
    try:
        from biaoke_desk import load_corpus_cache_clear

        load_corpus_cache_clear()
    except Exception:
        pass
    packed = list(events or [])
    try:
        from biaoke_tape import record_events

        record_events(db_path, packed)
    except Exception:
        logger.exception("飆大官方K即時建檔失敗")
    try:
        from biaoke_absorb import queue_absorb_events

        queue_absorb_events(db_path, packed)
    except Exception:
        logger.exception("飆大輔助匣寫入失敗")
    try:
        from biaoke_alert import maybe_push_drop_alert

        maybe_push_drop_alert(db_path, packed)
    except Exception:
        logger.exception("飆大緊急推播略過")


def run_biaoke_ingest_quiet() -> None:
    """排程／輪詢用：失敗不影響 16:30 融合、不進海選。"""
    try:
        from config import get_db_path

        ingest_public_posts(
            db_path=get_db_path(),
            refresh_latest=refresh_latest_now(),
        )
    except Exception:
        logger.exception("飆大定時匯入失敗")


def start_biaoke_poller() -> Optional[Any]:
    """常駐：抓文節奏不變；彙整另開台北 02:00／開市日 13:00。GHA --once 不開。"""
    import threading
    import time as _time

    from config import daily_scheduler_enabled, is_once_mode

    if is_once_mode() or not daily_scheduler_enabled():
        return None

    def _loop() -> None:
        _time.sleep(90)
        try:
            from biaoke_alert import wipe_biaoke_phone_pushes_once

            wipe_biaoke_phone_pushes_once()
        except Exception:
            logger.exception("飆大舊推文清除略過")
        while True:
            run_biaoke_ingest_quiet()
            wait = poll_wait_seconds()
            logger.info("飆大輪詢：%s 秒後再抓公開文／最新文討論串", wait)
            _time.sleep(max(30, int(wait)))

    t = threading.Thread(target=_loop, name="biaoke-poll", daemon=True)
    t.start()
    try:
        from biaoke_absorb import start_biaoke_absorb_scheduler

        start_biaoke_absorb_scheduler()
    except Exception:
        logger.exception("飆大神經元彙整排程沒開起來")
    return t
