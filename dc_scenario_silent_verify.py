# -*- coding: utf-8 -*-
"""情境預估 × D.C直流變頻 靜默對質（分軌）。

排程鍵：dc_sf_silent＝Asia/Taipei **03:30**（自 DC_SF_START 起每天，含週末）。
往回 **24 小時**主文；他幾篇就生成幾篇情境預估來比。錯開飆大隔日 **01:00**
盤後彙整；抓文窗／神經元照原本跑，本檔不准停它們。

硬規則（與飆大互不影響，鎖死）：
1. 各自排程鍵／pipeline_runs 前綴（dc-sf-silent-* ≠ biaoke_absorb_runs）。
2. 各自檔鎖／逾時（dc_sf_silent.lock；不准共用飆大鎖或清對方 actor）。
3. 失敗互不擋：本檔 exception 只記自己的 pipeline；不准 raise 打斷飆大 poller／absorb。
4. 不准呼叫 ingest_public_posts／run_absorb／寫 biaoke_posts；只寫 dc_sf_* 表與 media。
5. 資源強碰＝鐘點錯開（03:30）；01:00–02:19 若誤觸則延後，不准兩條長任務同時重壓。

日流程：03:30 抓過去 24 小時 D.C 全文＋圖＋圖注。他有幾篇，就先用我們的
官方股價把對應股號的情境預估全部畫完，然後才逐篇對他的圖。比的是波浪走法、
每個轉折落點、以及該轉折的點位數字。底圖仍是我們的官方 K。
有發文且轉折數字／文意尚未同時 ≥95% 才改 dc_sf_rules（話筒讀）。
已走的轉折改釘到最接近他那個價的官方高／低；還沒走的點位每天往他的數字走一步。
他圖≠我們圖時：不准只調 likeness／盲抄轉折；要落 why 卡（動機／滿足點／時間軸／
可遷移規則／僅此檔）進 dc_sf_learn，可遷移句另寫入 dc_sf_rules.learn_transfer，
供其他股預估路徑用。沒發文只落檔、不改畫法。不准把這組數字抄進買訊。永遠不是買訊；A+B+C。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import hashlib
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("WayneBot.DcScenarioSilent")

TAIPEI = ZoneInfo("Asia/Taipei")

DC_SF_AUTHOR_ID = "2590523"
DC_SF_AUTHOR_NAMES = ("D.C直流變頻", "D.C", "直流變頻", "DC直流變頻")
# 首跑日 2026-10-15。之後每天都跑；價格與文意同時 ≥95% 的那天停改畫法，隔天再量。
DC_SF_START = date(2026, 10, 15)
JOB_KIND = "dc_sf_silent"
PIPE_PREFIX = "dc-sf-silent-"
# 鐘點錯開：飆大隔日彙整 01:00；本檔 03:30（含週末日曆日）
SCHEDULE_HOUR = 3
SCHEDULE_MINUTE = 30
LOOKBACK_HOURS = 24
# 價格軸與文意軸都要到這個比例才停改畫法。缺任一軸不算到。
SIM_TARGET = 0.95
# 01:00–02:19 視為飆大夜檔窗，誤觸則跳過／等下一輪
_BIAOKE_NIGHT_BUSY_FROM = 1 * 60
_BIAOKE_NIGHT_BUSY_UNTIL = 2 * 60 + 20
LOCK_NAME = "dc_sf_silent.lock"  # 專鎖；不准與飆大共用
JOB_TIMEOUT_SEC = 45 * 60

_IMG_RE = re.compile(
    r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
    re.I,
)
_PRICE_RE = re.compile(
    r"(?<![\d.])(\d{2,5}(?:\.\d+)?)(?!\d)",
)
_WAVE_LAB_RE = re.compile(
    r"\(([1-5ivxIVX]|a|b|c|v|Y|W|X)\)|[（(]([1-5]|a|b|c|v)[）)]",
    re.I,
)


def _taipei_now() -> datetime:
    try:
        from config import taipei_now

        return taipei_now()
    except Exception:
        return datetime.now(TAIPEI)


def _ymd(d: Any) -> str:
    if isinstance(d, datetime):
        return d.astimezone(TAIPEI).strftime("%Y%m%d")
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    s = str(d or "").replace("-", "").strip()
    return s[:8] if len(s) >= 8 else s


def campaign_window(now: Optional[datetime] = None) -> Tuple[date, Optional[date]]:
    return DC_SF_START, None


def in_campaign(now: Optional[datetime] = None) -> bool:
    dt = now or _taipei_now()
    d = dt.astimezone(TAIPEI).date() if dt.tzinfo else dt.date()
    start, _end = campaign_window(dt)
    return d >= start


def prev_calendar_day(now: Optional[datetime] = None) -> date:
    dt = now or _taipei_now()
    d = dt.astimezone(TAIPEI).date() if dt.tzinfo else dt.date()
    return d - timedelta(days=1)


def window_bounds(
    now: Optional[datetime] = None, hours: float = LOOKBACK_HOURS
) -> Tuple[datetime, datetime]:
    """台北現在往回 hours 小時（含兩端）。"""
    dt = now or _taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    return dt - timedelta(hours=float(hours)), dt


def published_dt(row: Dict[str, Any]) -> Optional[datetime]:
    date_s = str((row or {}).get("date") or "").strip()
    time_s = str((row or {}).get("time") or "00:00").strip() or "00:00"
    if len(time_s) == 5:
        time_s += ":00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{date_s} {time_s[:8]}", fmt).replace(tzinfo=TAIPEI)
        except Exception:
            continue
    return None


def in_lookback(
    row: Dict[str, Any],
    now: Optional[datetime] = None,
    hours: float = LOOKBACK_HOURS,
) -> bool:
    pdt = published_dt(row)
    if pdt is None:
        return False
    start, end = window_bounds(now, hours)
    return start <= pdt <= end


def pipeline_key(run_day: Any) -> str:
    return f"{PIPE_PREFIX}{_ymd(run_day)}"


def biaoke_night_busy(now: Optional[datetime] = None) -> bool:
    """01:00–02:19：飆大隔日彙整優先窗；本檔不准同時重壓。"""
    dt = now or _taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    mins = dt.hour * 60 + dt.minute
    return _BIAOKE_NIGHT_BUSY_FROM <= mins < _BIAOKE_NIGHT_BUSY_UNTIL


def _lock_path(db_path: str = "") -> str:
    root = media_root(db_path)
    return os.path.join(root, LOCK_NAME)


def acquire_job_lock(db_path: str = "", *, timeout_sec: int = 0) -> Optional[Any]:
    """專屬檔鎖（與飆大分開）。拿不到＝略過本檔，不准清對方。"""
    path = _lock_path(db_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        import fcntl  # type: ignore
    except Exception:
        # 無 fcntl 時用存在即略過的哨兵（仍不碰飆大鎖）
        if os.path.isfile(path):
            try:
                age = time.time() - os.path.getmtime(path)
                if age < float(JOB_TIMEOUT_SEC):
                    return None
            except Exception:
                return None
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return path
        except Exception:
            return None
    fh = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()} kind={JOB_KIND}\n")
        fh.flush()
        return fh
    except BlockingIOError:
        try:
            fh.close()
        except Exception:
            pass
        return None
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        return None


def release_job_lock(handle: Any) -> None:
    if handle is None:
        return
    try:
        import fcntl  # type: ignore

        if hasattr(handle, "fileno"):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            return
    except Exception:
        pass
    # 哨兵路徑
    try:
        if isinstance(handle, str) and os.path.isfile(handle):
            os.remove(handle)
    except Exception:
        pass


def media_root(db_path: str = "") -> str:
    """圖檔落 data/dc_sf_media（Render 永久碟對 data/）。"""
    try:
        from config import get_db_path

        base = os.path.dirname(str(db_path or get_db_path() or "").strip()) or "data"
    except Exception:
        base = "data"
    root = os.path.join(base, "dc_sf_media")
    os.makedirs(root, exist_ok=True)
    return root


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dc_sf_posts (
                post_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                published TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                raw_meta TEXT NOT NULL DEFAULT '{}',
                fetched_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (post_id, as_of)
            );
            CREATE TABLE IF NOT EXISTS dc_sf_images (
                post_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                url TEXT NOT NULL,
                local_path TEXT NOT NULL DEFAULT '',
                sha256 TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (post_id, as_of, url)
            );
            CREATE TABLE IF NOT EXISTS dc_sf_compare (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                post_id TEXT NOT NULL DEFAULT '',
                our_png TEXT NOT NULL DEFAULT '',
                our_caption TEXT NOT NULL DEFAULT '',
                our_narrative TEXT NOT NULL DEFAULT '',
                our_wave_json TEXT NOT NULL DEFAULT '{}',
                his_excerpt TEXT NOT NULL DEFAULT '',
                his_narrative TEXT NOT NULL DEFAULT '',
                his_image_paths TEXT NOT NULL DEFAULT '[]',
                diff_json TEXT NOT NULL DEFAULT '{}',
                meaning_diff TEXT NOT NULL DEFAULT '',
                research_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (as_of, stock_id, post_id)
            );
            CREATE TABLE IF NOT EXISTS dc_sf_daily (
                as_of TEXT PRIMARY KEY,
                run_day TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                post_n INTEGER NOT NULL DEFAULT 0,
                stock_n INTEGER NOT NULL DEFAULT 0,
                compare_n INTEGER NOT NULL DEFAULT 0,
                rules_changed INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                report_json TEXT NOT NULL DEFAULT '{}',
                finished_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS dc_sf_rules (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL DEFAULT '{}',
                as_of TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS dc_sf_learn (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                post_id TEXT NOT NULL DEFAULT '',
                motive TEXT NOT NULL DEFAULT '',
                fulfill_json TEXT NOT NULL DEFAULT '[]',
                timeline_json TEXT NOT NULL DEFAULT '{}',
                transferable_json TEXT NOT NULL DEFAULT '[]',
                ticker_only_json TEXT NOT NULL DEFAULT '{}',
                card_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (as_of, stock_id, post_id)
            );
            """
        )
        # 舊庫補欄：文意／說法差異
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(dc_sf_compare)").fetchall()
        }
        for name, decl in (
            ("our_narrative", "TEXT NOT NULL DEFAULT ''"),
            ("his_narrative", "TEXT NOT NULL DEFAULT ''"),
            ("meaning_diff", "TEXT NOT NULL DEFAULT ''"),
            ("image_notes", "TEXT NOT NULL DEFAULT ''"),
            ("similarity", "REAL"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE dc_sf_compare ADD COLUMN {name} {decl}")
        conn.commit()
    finally:
        conn.close()


def load_rules(db_path: str) -> Dict[str, Any]:
    """話筒情境預估可讀的可調參數（分軌；空＝用程式預設）。"""
    path = str(db_path or "").strip()
    out: Dict[str, Any] = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        ensure_tables(path)
        conn = sqlite3.connect(path, timeout=15.0)
        try:
            rows = conn.execute("SELECT key, value_json FROM dc_sf_rules").fetchall()
        finally:
            conn.close()
        for k, raw in rows or []:
            try:
                out[str(k)] = json.loads(raw or "{}")
            except Exception:
                out[str(k)] = raw
    except Exception:
        logger.debug("dc_sf_rules 讀取略過", exc_info=True)
    return out


def upsert_rule(
    db_path: str,
    key: str,
    value: Any,
    *,
    as_of: str = "",
    note: str = "",
) -> bool:
    path = str(db_path or "").strip()
    if not path or not str(key or "").strip():
        return False
    ensure_tables(path)
    stamp = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                INSERT INTO dc_sf_rules(key, value_json, as_of, note, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  as_of=excluded.as_of,
                  note=excluded.note,
                  updated_at=excluded.updated_at
                """,
                (
                    str(key),
                    json.dumps(value, ensure_ascii=False),
                    _ymd(as_of),
                    str(note or "")[:500],
                    stamp,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        logger.exception("dc_sf_rules 寫入失敗")
        return False


def _page_is_dc(html_text: str) -> bool:
    raw = html_text or ""
    if f"/forum/user/{DC_SF_AUTHOR_ID}" in raw:
        return True
    low = raw.lower()
    if DC_SF_AUTHOR_ID in raw:
        return True
    for name in DC_SF_AUTHOR_NAMES:
        if name and name in raw:
            return True
    return "直流變頻" in raw or "d.c" in low


def _strip_html_text(html_text: str) -> str:
    raw = html_text or ""
    art = re.search(r"<article[^>]*>(.*)</article>", raw, re.S | re.I)
    chunk = art.group(1) if art else raw
    chunk = re.split(
        r"articleComment|articleReply|replyRespond|留言",
        chunk,
        maxsplit=1,
    )[0]
    chunk = re.sub(r"<script[^>]*>.*?</script>", " ", chunk, flags=re.S | re.I)
    chunk = re.sub(r"<style[^>]*>.*?</style>", " ", chunk, flags=re.S | re.I)
    chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"</p>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = re.sub(r"[ \t]+\n", "\n", chunk)
    chunk = re.sub(r"\n{3,}", "\n\n", chunk)
    return chunk.strip()


def parse_dc_article(aid: str, html_text: str) -> Optional[Dict[str, Any]]:
    """D.C 主文：不走飆大 is_biaoke_voice；認 author／user id。"""
    from biaoke_ingest import parse_published, _TAG_RE, _PUB_RE, _meta_description
    import html as html_mod

    raw = html_text or ""
    if not _page_is_dc(raw):
        return None
    pub = ""
    m = _PUB_RE.search(raw)
    if m:
        pub = m.group(1)
    date_s, time_s = parse_published(pub)
    tags = []
    for tag in _TAG_RE.findall(raw):
        t = html_mod.unescape(tag).strip()
        t = re.sub(r"^[A-Z]{0,5}\d{3,6}", "", t).strip()
        if t and t not in tags:
            tags.append(t)
    text = _strip_html_text(raw)
    if not text:
        text = _meta_description(raw)
    if not date_s or not text or len(text) < 12:
        return None
    imgs = list(dict.fromkeys(_IMG_RE.findall(raw)))
    return {
        "id": str(aid),
        "date": date_s,
        "time": time_s,
        "tags": tags[:12],
        "text": text,
        "images": imgs[:24],
        "image_notes": extract_image_notes(raw),
        "author_id": DC_SF_AUTHOR_ID,
    }


def extract_image_notes(html_text: str) -> str:
    """圖的 alt／title／figcaption。沒有 OCR 就不編圖上字。"""
    import html as html_mod

    raw = html_text or ""
    notes: List[str] = []

    def _add(blob: str) -> None:
        t = re.sub(r"\s+", " ", html_mod.unescape(blob or "")).strip()
        if len(t) < 2 or t.lower() in ("image", "photo", "img"):
            return
        if t not in notes:
            notes.append(t)

    for m in re.finditer(
        r"<(?:img|figure)[^>]*(?:alt|title|aria-label)\s*=\s*[\"']([^\"']{2,240})[\"']",
        raw,
        re.I,
    ):
        _add(m.group(1))
    for m in re.finditer(r"<figcaption[^>]*>(.*?)</figcaption>", raw, re.I | re.S):
        _add(re.sub(r"<[^>]+>", " ", m.group(1)))
    return "\n".join(notes)[:2000]


def fetch_dc_posts_for_day(
    as_of: str,
    *,
    session=None,
    max_ids: int = 40,
) -> List[Dict[str, Any]]:
    """抓作者個人頁，只留 published 落在 as_of（前一日曆日）的主文。"""
    from biaoke_ingest import fetch_html, parse_user_article_ids, ARTICLE_URL

    day = _ymd(as_of)
    if not day:
        return []
    user_url = f"https://www.cmoney.tw/forum/user/{DC_SF_AUTHOR_ID}"
    try:
        user_html = fetch_html(user_url, session)
        ids = parse_user_article_ids(user_html)[: max(1, int(max_ids))]
    except Exception:
        logger.exception("D.C 個人頁讀不到")
        return []
    out: List[Dict[str, Any]] = []
    for aid in ids:
        try:
            html_text = fetch_html(ARTICLE_URL.format(aid=aid), session)
            row = parse_dc_article(str(aid), html_text) if html_text else None
        except Exception:
            logger.debug("D.C 單篇失敗 id=%s", aid, exc_info=True)
            continue
        if not row:
            continue
        pub_day = _ymd(row.get("date"))
        if pub_day != day:
            # 個人頁由新到舊；已過目標日前可早停
            if pub_day and pub_day < day:
                break
            continue
        out.append(row)
    return out


def fetch_dc_posts_within(
    now: Optional[datetime] = None,
    *,
    hours: float = LOOKBACK_HOURS,
    session=None,
    max_ids: int = 40,
) -> List[Dict[str, Any]]:
    """個人頁由新到舊，只留過去 hours 小時內的主文。"""
    from biaoke_ingest import fetch_html, parse_user_article_ids, ARTICLE_URL

    dt = now or _taipei_now()
    start, _end = window_bounds(dt, hours)
    user_url = f"https://www.cmoney.tw/forum/user/{DC_SF_AUTHOR_ID}"
    try:
        user_html = fetch_html(user_url, session)
        ids = parse_user_article_ids(user_html)[: max(1, int(max_ids))]
    except Exception:
        logger.exception("D.C 個人頁讀不到")
        return []
    out: List[Dict[str, Any]] = []
    for aid in ids:
        try:
            html_text = fetch_html(ARTICLE_URL.format(aid=aid), session)
            row = parse_dc_article(str(aid), html_text) if html_text else None
        except Exception:
            logger.debug("D.C 單篇失敗 id=%s", aid, exc_info=True)
            continue
        if not row:
            continue
        pdt = published_dt(row)
        if pdt is not None and pdt < start:
            break
        if not in_lookback(row, dt, hours):
            continue
        out.append(row)
    return out


def _download_image(url: str, dest: str, session=None) -> Tuple[str, str]:
    import requests

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    sess = session or requests.Session()
    try:
        resp = sess.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.cmoney.tw/",
            },
        )
        if resp.status_code != 200 or not resp.content:
            return "", ""
        blob = resp.content
        with open(dest, "wb") as f:
            f.write(blob)
        return dest, hashlib.sha256(blob).hexdigest()
    except Exception:
        logger.debug("D.C 圖下載失敗 %s", url, exc_info=True)
        return "", ""


def save_posts_and_images(
    db_path: str,
    as_of: str,
    posts: Sequence[Dict[str, Any]],
    *,
    session=None,
) -> Dict[str, int]:
    ensure_tables(db_path)
    day = _ymd(as_of)
    stamp = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    root = os.path.join(media_root(db_path), day)
    os.makedirs(root, exist_ok=True)
    n_post = 0
    n_img = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for p in posts:
            pid = str(p.get("id") or "").strip()
            if not pid:
                continue
            conn.execute(
                """
                INSERT INTO dc_sf_posts(
                  post_id, as_of, published, title, body, tags_json, raw_meta, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(post_id, as_of) DO UPDATE SET
                  published=excluded.published,
                  body=excluded.body,
                  tags_json=excluded.tags_json,
                  raw_meta=excluded.raw_meta,
                  fetched_at=excluded.fetched_at
                """,
                (
                    pid,
                    day,
                    f"{p.get('date') or ''} {p.get('time') or ''}".strip(),
                    "",
                    str(p.get("text") or ""),
                    json.dumps(list(p.get("tags") or []), ensure_ascii=False),
                    json.dumps(
                        {"author_id": DC_SF_AUTHOR_ID, "images": list(p.get("images") or [])},
                        ensure_ascii=False,
                    ),
                    stamp,
                ),
            )
            n_post += 1
            for i, url in enumerate(list(p.get("images") or [])[:24]):
                ext = ".jpg"
                if ".png" in url.lower():
                    ext = ".png"
                elif ".webp" in url.lower():
                    ext = ".webp"
                dest = os.path.join(root, f"{pid}_{i}{ext}")
                local, sha = _download_image(str(url), dest, session=session)
                conn.execute(
                    """
                    INSERT INTO dc_sf_images(
                      post_id, as_of, url, local_path, sha256, fetched_at
                    ) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(post_id, as_of, url) DO UPDATE SET
                      local_path=excluded.local_path,
                      sha256=excluded.sha256,
                      fetched_at=excluded.fetched_at
                    """,
                    (pid, day, str(url), local or "", sha or "", stamp),
                )
                if local:
                    n_img += 1
        conn.commit()
    finally:
        conn.close()
    return {"posts": n_post, "images": n_img}


def stocks_from_posts(
    posts: Sequence[Dict[str, Any]], *, db_path: str = ""
) -> List[Dict[str, Any]]:
    """點名檔；空代號不算。"""
    from biaoke_link import extract_mentions

    by_sid: Dict[str, Dict[str, Any]] = {}
    for p in posts:
        hits = extract_mentions(
            str(p.get("text") or ""),
            tags=list(p.get("tags") or []),
            db_path=db_path,
        )
        for h in hits:
            sid = str(h.get("stock_id") or "").strip()
            if not sid:
                continue
            slot = by_sid.setdefault(
                sid,
                {
                    "stock_id": sid,
                    "stock_name": str(h.get("stock_name") or ""),
                    "post_ids": [],
                    "excerpts": [],
                },
            )
            pid = str(p.get("id") or "")
            if pid and pid not in slot["post_ids"]:
                slot["post_ids"].append(pid)
            excerpt = str(p.get("text") or "").strip()[:1200]
            if excerpt and excerpt not in slot["excerpts"]:
                slot["excerpts"].append(excerpt)
    return list(by_sid.values())


def _our_wave_summary(meta: Dict[str, Any]) -> Dict[str, Any]:
    wave = dict((meta or {}).get("wave") or {})
    return {
        "state": wave.get("state"),
        "labels": list(wave.get("labels") or []),
        "bubble": wave.get("bubble"),
        "confirmed": [
            {
                "label": c.get("label"),
                "i": c.get("i"),
                "price": c.get("price"),
                "date": c.get("date"),
            }
            for c in (wave.get("confirmed") or [])
        ],
        "projected": [
            {
                "label": c.get("label"),
                "i": c.get("i"),
                "price": c.get("price"),
            }
            for c in (wave.get("projected") or [])
        ],
        "abc": [
            {"label": c.get("label"), "price": c.get("price"), "date": c.get("date")}
            for c in (wave.get("abc") or [])
        ],
        "zones": list(wave.get("zones") or []),
        "wedge": bool(wave.get("wedge")),
        "deadline": wave.get("deadline") or {},
        "desc_press": {
            "pos": (wave.get("desc_press") or {}).get("pos"),
            "source": (wave.get("desc_press") or {}).get("source"),
        },
    }


def _his_signals(text: str) -> Dict[str, Any]:
    blob = str(text or "")
    labs = []
    for m in _WAVE_LAB_RE.finditer(blob):
        g = m.group(0)
        if g and g not in labs:
            labs.append(g)
    prices = []
    for m in _PRICE_RE.finditer(blob):
        try:
            v = float(m.group(1))
        except Exception:
            continue
        if not _keep_price_token(blob, m.start(1), v):
            continue
        prices.append(v)
        if len(prices) >= 40:
            break
    return {
        "wave_labels_guess": labs[:20],
        "prices_guess": prices[:40],
        "has_channel_words": any(
            k in blob for k in ("通道", "楔形", "平行", "下降壓", "壓力", "支撐", "滿足")
        ),
        "has_target_words": any(k in blob for k in ("目標", "上看", "下看", "區間")),
    }


def _keep_price_token(blob: str, index: int, value: float) -> bool:
    """留下像價的數字。年份、日期碎片不算預估數字。"""
    try:
        v = float(value)
    except Exception:
        return False
    if v < 8 or v > 200000:
        return False
    if float(v).is_integer() and 1990 <= int(v) <= 2039:
        return False
    prev = blob[index - 1] if index > 0 else ""
    if prev in "-/／年月.":
        return False
    return True


_TURN_AFTER = re.compile(
    r"[\(（]\s*(1|2|3|4|5|a|b|c|iii|ii|iv|v|i)\s*[\)）]\s*[：:、,，／/]?\s*(\d{2,5}(?:\.\d+)?)",
    re.I,
)
_TURN_BEFORE = re.compile(
    r"(\d{2,5}(?:\.\d+)?)\s*[\(（]\s*(1|2|3|4|5|a|b|c|iii|ii|iv|v|i)\s*[\)）]",
    re.I,
)
_ROMAN_TURN = {"i": "(1)", "ii": "(2)", "iii": "(3)", "iv": "(4)", "v": "(5)"}


def _norm_turn_label(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if s in _ROMAN_TURN:
        return _ROMAN_TURN[s]
    if s in ("a", "b", "c", "1", "2", "3", "4", "5"):
        return f"({s})"
    return ""


def parse_turn_prices(text: str) -> Dict[str, float]:
    """只收跟浪號綁在一起的點位。裸數字不當轉折價。"""
    blob = str(text or "")
    out: Dict[str, float] = {}

    def _take(lab_raw: str, num_raw: str, index: int) -> None:
        lab = _norm_turn_label(lab_raw)
        if not lab or lab in out:
            return
        try:
            v = float(num_raw)
        except Exception:
            return
        if not _keep_price_token(blob, index, v):
            return
        out[lab] = v

    for m in _TURN_AFTER.finditer(blob):
        _take(m.group(1), m.group(2), m.start(2))
    for m in _TURN_BEFORE.finditer(blob):
        _take(m.group(2), m.group(1), m.start(1))
    return out


def align_wave_turns(
    wave: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """底圖列不動。已走轉折改釘最接近他那個價的官方高／低；未走點位用每日走出來的數字。"""
    if not wave:
        return wave
    his = (spec or {}).get("his") or {}
    drawn = (spec or {}).get("drawn") or {}
    if not his and not drawn:
        return wave
    bars = list(rows or [])
    out = dict(wave)

    def _kind(node: Dict[str, Any]) -> str:
        k = str(node.get("kind") or "")
        if k in ("H", "L"):
            return k
        if str(node.get("label") or "") in ("(2)", "(4)", "(b)"):
            return "L"
        return "H"

    def _snap(kind: str, target: float):
        best = None
        best_err = 1e9
        for i, bar in enumerate(bars):
            try:
                px = float(bar.get("high") if kind == "H" else bar.get("low") or 0)
            except Exception:
                continue
            if px <= 0:
                continue
            err = abs(px - float(target)) / max(abs(float(target)), 1e-9)
            if err < best_err:
                best_err = err
                best = (float(i), px, str(bar.get("date") or ""))
        if best is None or best_err > 0.08:
            return None
        return best

    def _fix(node: Dict[str, Any], projected: bool) -> Dict[str, Any]:
        item = dict(node)
        lab = str(item.get("label") or "")
        if not projected and lab in his:
            try:
                hit = _snap(_kind(item), float(his[lab]))
            except Exception:
                hit = None
            if hit:
                item["i"], item["price"], item["date"] = hit
        elif projected and lab in drawn:
            try:
                item["price"] = float(drawn[lab])
            except Exception:
                pass
        return item

    confirmed = [_fix(n, False) for n in (out.get("confirmed") or [])]
    projected = [_fix(n, True) for n in (out.get("projected") or [])]
    abc = [
        _fix(n, str(n.get("date") or "") in ("", "估"))
        for n in (out.get("abc") or [])
    ]
    start = out.get("start") or {}
    path_done: List[Tuple[float, float]] = []
    if start:
        try:
            path_done.append((float(start.get("i") or 0), float(start.get("price") or 0)))
        except Exception:
            path_done = []
    for node in confirmed:
        try:
            path_done.append((float(node.get("i") or 0), float(node.get("price") or 0)))
        except Exception:
            continue
    path_proj: List[Tuple[float, float]] = []
    if projected and path_done:
        path_proj.append(path_done[-1])
    for node in projected:
        try:
            path_proj.append((float(node.get("i") or 0), float(node.get("price") or 0)))
        except Exception:
            continue
    out["confirmed"] = confirmed
    out["projected"] = projected
    out["abc"] = abc
    out["path_done"] = path_done
    out["path_proj"] = path_proj
    out["labels"] = (
        [str(n.get("label") or "") for n in confirmed]
        + [str(n.get("label") or "") for n in abc]
        + [str(n.get("label") or "") for n in projected]
    )
    return out


def step_turn_drawn(
    prev_drawn: Dict[str, Any],
    his: Dict[str, float],
    our_turns: Sequence[Dict[str, Any]],
) -> Dict[str, float]:
    """未走轉折的點位每天往他的數字走一半。已走的不在這裡改價，改去釘官方 K。"""
    our: Dict[str, Dict[str, Any]] = {}
    for node in our_turns or []:
        lab = str(node.get("label") or "")
        if lab and lab not in our:
            our[lab] = node
    drawn: Dict[str, float] = {}
    for lab, target in (his or {}).items():
        node = our.get(lab) or {}
        if node and not node.get("projected"):
            continue
        try:
            tgt = float(target)
        except Exception:
            continue
        base = (prev_drawn or {}).get(lab)
        if base is None:
            base = node.get("price", tgt)
        try:
            base_f = float(base)
        except Exception:
            base_f = tgt
        nxt = base_f + 0.5 * (tgt - base_f)
        if abs(nxt - tgt) / max(abs(tgt), 1e-9) <= 0.03:
            nxt = tgt
        drawn[lab] = round(float(nxt), 2)
    return drawn


def _narrative_tokens(text: str) -> set:
    blob = str(text or "")
    keys = (
        "上升",
        "下降",
        "修正",
        "衝動",
        "楔形",
        "通道",
        "下降壓",
        "支撐",
        "壓力",
        "滿足",
        "目標",
        "轉多",
        "轉空",
        "回測",
        "突破",
        "整理",
        "浪",
        "虛線",
        "已走",
        "未走",
        "觀察",
        "不保證",
    )
    hit = {k for k in keys if k in blob}
    for m in _WAVE_LAB_RE.finditer(blob):
        g = (m.group(0) or "").strip()
        if g:
            hit.add(g.lower())
    return hit


def meaning_diff_line(*, our_narrative: str, his_narrative: str) -> str:
    """文意／說法差異一句（落檔用；不准進話筒過程％）。"""
    ours = _narrative_tokens(our_narrative)
    his = _narrative_tokens(his_narrative)
    if not his and not ours:
        return "雙方無可對文意標"
    only_his = sorted(his - ours)
    only_ours = sorted(ours - his)
    if not only_his and not only_ours:
        return "文意標大致重疊"
    bits = []
    if only_his:
        bits.append("他有我們無：" + "／".join(only_his[:8]))
    if only_ours:
        bits.append("我們有他無：" + "／".join(only_ours[:8]))
    return "；".join(bits)


def compare_one(
    *,
    our_wave: Dict[str, Any],
    our_caption: str,
    our_narrative: str,
    his_text: str,
) -> Dict[str, Any]:
    """逐檔差異：浪點／連線／通道壓／目標／說法／文意。過程％不進話筒。"""
    his = _his_signals(his_text)
    our_labs = [str(x) for x in (our_wave.get("labels") or [])]
    our_prices = []
    for c in list(our_wave.get("confirmed") or []) + list(our_wave.get("projected") or []) + list(
        our_wave.get("abc") or []
    ):
        try:
            our_prices.append(float(c.get("price")))
        except Exception:
            pass
    his_set = {str(x).lower() for x in his.get("wave_labels_guess") or []}
    our_set = {str(x).lower() for x in our_labs}
    label_overlap = sorted(his_set & our_set)
    price_hits = 0
    for op in our_prices:
        for hp in his.get("prices_guess") or []:
            if abs(op - hp) / max(op, 1e-9) <= 0.03:
                price_hits += 1
                break
    narr = str(our_narrative or our_caption or "")
    meaning = meaning_diff_line(our_narrative=narr, his_narrative=his_text)
    gaps = []
    if his_set and not label_overlap:
        gaps.append("浪號標籤無交集")
    if (his.get("prices_guess") or []) and price_hits == 0 and our_prices:
        gaps.append("關鍵價未對上（±3%）")
    if his.get("has_channel_words") and not (
        our_wave.get("wedge") or (our_wave.get("desc_press") or {}).get("source")
    ):
        gaps.append("他提通道／壓線；我們幾何未掛")
    our_zones = list(our_wave.get("zones") or [])
    has_fulfill = any(str(z.get("kind") or "") in ("ok", "tgt") for z in our_zones)
    if his.get("has_target_words") and not (our_zones or our_wave.get("projected")):
        gaps.append("他提目標；我們無帶／虛線")
    # 他明文「滿足」或已有虛線 (4) 卻無滿足灰框 → 記缺層（可遷移）
    need_fulfill = ("滿足" in str(his_text or "")) or any(
        str(p.get("label") or "") == "(4)"
        for p in list(our_wave.get("projected") or [])
    )
    if need_fulfill and not has_fulfill:
        gaps.append("他有滿足區／目標帶；我們未畫滿足灰框")
    if meaning and meaning not in ("文意標大致重疊", "雙方無可對文意標"):
        gaps.append("文意／說法差異")
    note = "；".join(gaps) if gaps else "結構／價位／文意大致可對或他文無可量化浪標"
    our_turns: List[Dict[str, Any]] = []
    for c in list(our_wave.get("confirmed") or []):
        try:
            our_turns.append(
                {
                    "label": str(c.get("label") or ""),
                    "price": float(c.get("price")),
                    "projected": False,
                }
            )
        except Exception:
            continue
    for c in list(our_wave.get("projected") or []) + list(our_wave.get("abc") or []):
        try:
            walked = str(c.get("date") or "") not in ("", "估")
            our_turns.append(
                {
                    "label": str(c.get("label") or ""),
                    "price": float(c.get("price")),
                    "projected": not walked,
                }
            )
        except Exception:
            continue
    likeness = _likeness(
        his_labels=list(his.get("wave_labels_guess") or []),
        label_overlap=label_overlap,
        his_prices=list(his.get("prices_guess") or []),
        price_hits=price_hits,
        our_narrative=narr,
        his_narrative=his_text,
    )
    return {
        "label_overlap": label_overlap,
        "price_near_hits": price_hits,
        "his": his,
        "our_labels": our_labs,
        "our_prices": our_prices[:40],
        "our_turns": our_turns,
        "our_wave": {
            "deadline": dict((our_wave or {}).get("deadline") or {}),
            "labels": our_labs,
            "zones": list((our_wave or {}).get("zones") or []),
            "projected": list((our_wave or {}).get("projected") or []),
        },
        "gaps": gaps,
        "meaning_diff": meaning,
        "likeness": likeness,
        "research_note": note,
        "not_buy_signal": True,
        "has_actionable_diff": bool(gaps),
    }


def _likeness(
    *,
    his_labels: Sequence[str],
    label_overlap: Sequence[str],
    his_prices: Sequence[float],
    price_hits: int,
    our_narrative: str,
    his_narrative: str,
) -> Dict[str, Any]:
    """各軸 0～1。沒有可對的數字或文意標就留空，不准當成 95%。"""
    labels = None
    if his_labels:
        labels = len(list(label_overlap)) / float(len(list(his_labels)))
    prices = None
    if his_prices:
        prices = min(1.0, float(price_hits) / float(len(list(his_prices))))
    narrative = None
    his_tok = _narrative_tokens(his_narrative)
    if his_tok:
        narrative = len(his_tok & _narrative_tokens(our_narrative)) / float(len(his_tok))
    present = [x for x in (labels, prices, narrative) if x is not None]
    similarity = (sum(present) / len(present)) if present else None
    reached = (
        prices is not None
        and narrative is not None
        and float(prices) >= SIM_TARGET
        and float(narrative) >= SIM_TARGET
    )
    return {
        "labels": labels,
        "prices": prices,
        "narrative": narrative,
        "similarity": similarity,
        "reached_95": reached,
        "target": SIM_TARGET,
    }


def likeness_of(compares: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """一篇一列。價格、文意各自先平均，兩軸都 ≥ 目標才算到。"""
    px: List[float] = []
    narr: List[float] = []
    labs: List[float] = []
    for row in compares:
        like = ((row.get("diff") or {}).get("likeness") or {})
        if like.get("prices") is not None:
            px.append(float(like["prices"]))
        if like.get("narrative") is not None:
            narr.append(float(like["narrative"]))
        if like.get("labels") is not None:
            labs.append(float(like["labels"]))

    def _avg(xs: Sequence[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    prices, narrative = _avg(px), _avg(narr)
    reached = (
        prices is not None
        and narrative is not None
        and prices >= SIM_TARGET
        and narrative >= SIM_TARGET
    )
    return {
        "prices": prices,
        "narrative": narrative,
        "labels": _avg(labs),
        "n_price": len(px),
        "n_narrative": len(narr),
        "reached_95": reached,
        "target": SIM_TARGET,
    }


_METHOD_WORDS = (
    "上升",
    "下降",
    "修正",
    "衝動",
    "楔形",
    "通道",
    "下降壓",
    "支撐",
    "壓力",
    "滿足",
    "目標",
    "轉多",
    "轉空",
    "回測",
    "突破",
    "整理",
)


def method_words_missing(*, our_narrative: str, his_narrative: str) -> List[str]:
    """他有、我們敘事沒有的方法詞。不收價格。"""
    his = _narrative_tokens(his_narrative)
    ours = _narrative_tokens(our_narrative)
    return [w for w in _METHOD_WORDS if w in his and w not in ours]


def method_clause(body: str, wave: Dict[str, Any], method_words: Sequence[str]) -> str:
    """只把已經畫得出來的方法詞補進敘事。不寫他的目標價。"""
    blob = str(body or "")
    drawn = set()
    if wave.get("wedge") or (wave.get("desc_press") or {}).get("source"):
        drawn.update({"通道", "楔形", "下降壓", "壓力"})
    if wave.get("zones") or wave.get("projected"):
        drawn.update({"目標", "滿足"})
    if wave.get("confirmed"):
        drawn.update({"支撐", "回測"})
    extra = [w for w in method_words if w in drawn and w not in blob]
    if not extra:
        return ""
    return "；" + "／".join(extra[:6])


def render_our_bundle(
    stock_id: str,
    db_path: str,
    out_png: str,
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    from scenario_forecast_chart import render_scenario_forecast

    try:
        path, cap, meta = render_scenario_forecast(stock_id, db_path, out_png)
        return path, str(cap or ""), dict(meta or {})
    except Exception:
        logger.exception("情境預估渲圖失敗 sid=%s", stock_id)
        return None, "情境預估暫略。不是買訊。", {}


def _price_grain(prices: Sequence[float]) -> Optional[List[int]]:
    """他寫的價落在哪一種整數關。不回傳那些價本身。"""
    vals = []
    for p in prices:
        try:
            vals.append(float(p))
        except Exception:
            continue
    if not vals:
        return None
    n = len(vals)

    def _on(step: float) -> int:
        return sum(1 for p in vals if abs(p - round(p / step) * step) < 1e-6)

    if _on(10) >= max(1, n // 2) and _on(100) * 2 < n:
        return [10, 50, 100]
    if _on(50) >= max(1, n // 2):
        return [50, 100]
    return None


_DATE_HINT_RE = re.compile(
    r"(?:20\d{2}[-/])?(?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])"
    r"|(?:年底|年底前|月底|月底前|季底|兩週|三週|一週|幾週|交易日|開盤前|盤後)"
)
_FULFILL_NEAR_RE = re.compile(
    r"(?:滿足|目標|上看|下看|區間)[^0-9]{0,8}(\d{2,5}(?:\.\d+)?)"
    r"|(\d{2,5}(?:\.\d+)?)[^0-9]{0,8}(?:滿足|目標|上看|下看)",
)


def _timeline_cues(his_text: str, our_wave: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """時間軸線索：他文日期／窗詞＋我們 deadline（bar 軸）。不准發明浪號。"""
    blob = str(his_text or "")
    hints = []
    for m in _DATE_HINT_RE.finditer(blob):
        s = (m.group(0) or "").strip()
        if s and s not in hints:
            hints.append(s)
        if len(hints) >= 8:
            break
    deadline = dict((our_wave or {}).get("deadline") or {})
    out: Dict[str, Any] = {
        "his_timing_hints": hints,
        "our_deadline_label": str(deadline.get("label") or ""),
        "our_deadline_i": deadline.get("i"),
        "axis_note": "",
    }
    if hints and deadline.get("i") is not None:
        out["axis_note"] = "他有時間窗詞／日期；我們有 deadline bar——要比軸長是否跟浪段綁定"
    elif hints:
        out["axis_note"] = "他標了時間窗；我們軸長要依該檔結構分檔，不准固定終點"
    elif deadline.get("i") is not None:
        out["axis_note"] = "我們有 deadline；他文無明確時間詞——核對是否該縮／拉軸"
    return out


def _fulfill_targets(his_text: str) -> List[Dict[str, Any]]:
    """滿足點：浪號綁價＋「滿足／目標／上看／下看」近旁價。"""
    blob = str(his_text or "")
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for lab, px in parse_turn_prices(blob).items():
        key = f"{lab}:{px}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "turn", "label": lab, "price": float(px)})
    for m in _FULFILL_NEAR_RE.finditer(blob):
        raw = m.group(1) or m.group(2)
        try:
            px = float(raw)
        except Exception:
            continue
        if not _keep_price_token(blob, m.start(1) if m.group(1) else m.start(2), px):
            continue
        key = f"tgt:{px}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": "target_word", "label": "", "price": px})
        if len(out) >= 20:
            break
    return out


def build_why_card(
    *,
    as_of: str,
    stock_id: str,
    post_id: str = "",
    his_text: str,
    our_caption: str = "",
    our_wave: Optional[Dict[str, Any]] = None,
    diff: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """他圖≠我們圖時的 why 卡：動機／滿足點／時間軸／可遷移／僅此檔。

    可遷移＝方法句（無該檔絕對價）；僅此檔＝該檔轉折價與案號。不准當買訊。
    """
    d = dict(diff or {})
    gaps = [str(g) for g in (d.get("gaps") or []) if g]
    meaning = str(d.get("meaning_diff") or "")
    missing = method_words_missing(
        our_narrative=str(our_caption or ""),
        his_narrative=str(his_text or ""),
    )
    motive_bits = []
    if gaps:
        motive_bits.append("差距：" + "／".join(gaps[:6]))
    if meaning and meaning not in ("文意標大致重疊", "雙方無可對文意標"):
        motive_bits.append(meaning)
    if missing:
        motive_bits.append("方法詞他有我們無：" + "／".join(missing[:8]))
    if not motive_bits:
        motive_bits.append("結構可對但仍記滿足點／時間軸供遷移")
    fulfill = _fulfill_targets(his_text)
    timeline = _timeline_cues(his_text, our_wave)
    transferable: List[str] = []
    for g in gaps:
        if "通道" in g or "壓線" in g:
            transferable.append("他文有通道／壓線詞時補楔形＋下降壓＋區間帶幾何")
        if "目標" in g or "虛線" in g:
            transferable.append("他文有目標／上看時要畫未走虛線與滿足帶，不准只標已走轉折")
        if "浪號" in g:
            transferable.append("浪號選點優先夠幅度／夠間隔真轉折；未走從現在所在段延伸")
        if "關鍵價" in g:
            transferable.append("撐帶刻度跟他常用整數關（grain），不准抄單檔絕對價")
        if "文意" in g:
            transferable.append("敘事補他有我們無的方法詞（通道／滿足／轉多等），不寫他的目標價")
    if timeline.get("his_timing_hints") or timeline.get("axis_note"):
        transferable.append("未來時間軸長度依該檔浪段／時間對稱分檔，不准每檔同一終點")
    if missing:
        transferable.append("方法詞缺漏時優先補：" + "／".join(missing[:6]))
    # 8227 對照鎖死的可遷移層（無單檔絕對價）
    for g in gaps:
        if "滿足" in g:
            transferable.append(
                "(4)滿足區＝(1)鄰域∪(3)-(2)之0.5～0.618回撤帶，標hi/lo，(4)點落帶內"
            )
    transferable.extend(
        [
            "方向箭：修正腿綠下、衝動腿紅上；語意＝走勢意圖不是買訊",
            "Vegas藍＝EMA144/169、紅＝EMA576/676均線隧道；紫陰影＝未來浪路徑包絡，語意不同勿混",
            "樞紐差致點位差：他用已走真峰谷＋滿足帶定(3)(5)；勿只抄單夜絕對價",
        ]
    )
    # 去重保序
    seen_t: set = set()
    transfer_u: List[str] = []
    for t in transferable:
        if t not in seen_t:
            seen_t.add(t)
            transfer_u.append(t)
    his_turns = parse_turn_prices(his_text)
    ticker_only = {
        "stock_id": str(stock_id or ""),
        "post_id": str(post_id or ""),
        "his_turn_prices": his_turns,
        "fulfill_prices": [x.get("price") for x in fulfill],
        "note": "僅此檔對照用；不准當買訊、不准寫進黃金買點／海選／查股／飆大",
    }
    return {
        "as_of": _ymd(as_of),
        "stock_id": str(stock_id or ""),
        "post_id": str(post_id or ""),
        "motive": "；".join(motive_bits)[:800],
        "fulfill_targets": fulfill,
        "timeline": timeline,
        "transferable": transfer_u[:12],
        "ticker_only": ticker_only,
        "not_buy_signal": True,
        "has_actionable_diff": bool(d.get("has_actionable_diff")),
    }


def upsert_learn_card(db_path: str, card: Dict[str, Any]) -> bool:
    """落一張 why 卡進 dc_sf_learn（分軌；不碰飆大／買訊表）。"""
    path = str(db_path or "").strip()
    if not path:
        return False
    sid = str((card or {}).get("stock_id") or "").strip()
    as_of = _ymd((card or {}).get("as_of") or "")
    if not sid or not as_of:
        return False
    ensure_tables(path)
    stamp = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    pid = str((card or {}).get("post_id") or "")
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                INSERT INTO dc_sf_learn(
                  as_of, stock_id, post_id, motive, fulfill_json, timeline_json,
                  transferable_json, ticker_only_json, card_json, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(as_of, stock_id, post_id) DO UPDATE SET
                  motive=excluded.motive,
                  fulfill_json=excluded.fulfill_json,
                  timeline_json=excluded.timeline_json,
                  transferable_json=excluded.transferable_json,
                  ticker_only_json=excluded.ticker_only_json,
                  card_json=excluded.card_json,
                  created_at=excluded.created_at
                """,
                (
                    as_of,
                    sid,
                    pid,
                    str((card or {}).get("motive") or "")[:800],
                    json.dumps((card or {}).get("fulfill_targets") or [], ensure_ascii=False),
                    json.dumps((card or {}).get("timeline") or {}, ensure_ascii=False),
                    json.dumps((card or {}).get("transferable") or [], ensure_ascii=False),
                    json.dumps((card or {}).get("ticker_only") or {}, ensure_ascii=False),
                    json.dumps(card, ensure_ascii=False),
                    stamp,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        logger.exception("dc_sf_learn 寫入失敗")
        return False


def persist_mismatch_learn(
    db_path: str,
    as_of: str,
    compares: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """mismatch 夜：寫 why 卡＋把可遷移句併進 dc_sf_rules.learn_transfer。"""
    cards: List[Dict[str, Any]] = []
    transfer_all: List[str] = []
    for row in compares or []:
        diff = row.get("diff") or {}
        like = diff.get("likeness") or {}
        # 有可行動差距，或尚未雙軸 95%，才建卡（對齊＝不盲抄仍可略）
        if not (diff.get("has_actionable_diff") or not like.get("reached_95")):
            continue
        sid = str(row.get("stock_id") or "").strip()
        if not sid:
            continue
        card = build_why_card(
            as_of=as_of,
            stock_id=sid,
            post_id=str(row.get("post_id") or ""),
            his_text=str(row.get("his_text") or ""),
            our_caption=str(row.get("caption") or ""),
            our_wave=diff.get("our_wave") if isinstance(diff.get("our_wave"), dict) else None,
            diff=diff,
        )
        if upsert_learn_card(db_path, card):
            cards.append(card)
            for t in card.get("transferable") or []:
                if t and t not in transfer_all:
                    transfer_all.append(str(t))
    if not cards:
        return {"n": 0, "transfer_n": 0, "keys": []}
    prev = load_rules(db_path)
    old = prev.get("learn_transfer") if isinstance(prev.get("learn_transfer"), dict) else {}
    rules = [str(x) for x in (old.get("rules") or []) if x]
    for t in transfer_all:
        if t not in rules:
            rules.append(t)
    rules = rules[-40:]  # 留近窗，避免無限長
    paint = dict(old.get("paint") or {}) if isinstance(old.get("paint"), dict) else {}
    # 夜檔可吸收的畫層旗標（情境預估讀；預設開）
    paint.setdefault("fulfill_zone_w4", True)
    paint.setdefault("dir_arrows", True)
    paint.setdefault("vegas_dual_tunnel", True)
    val = {
        "as_of": _ymd(as_of),
        "rules": rules,
        "paint": paint,
        "n_cards_night": len(cards),
        "not_buy_signal": True,
        "note": "可遷移方法句＋paint 旗標；不含單檔絕對價；只進情境預估",
    }
    upsert_rule(
        db_path,
        "learn_transfer",
        val,
        as_of=as_of,
        note="日對質：可遷移 why／滿足點／時間軸／畫層",
    )
    return {"n": len(cards), "transfer_n": len(transfer_all), "keys": ["learn_transfer"]}


def _upsert_stock_turns(
    db_path: str,
    as_of: str,
    compares: Sequence[Dict[str, Any]],
    prev: Dict[str, Any],
) -> Dict[str, Any]:
    """一檔一個轉折表。底圖不換。已走的價留給官方 K 去釘；未走的點位往他的數字走。"""
    by_sid: Dict[str, Dict[str, Any]] = {}
    for row in compares:
        sid = str(row.get("stock_id") or "").strip()
        if not sid:
            continue
        his = parse_turn_prices(str(row.get("his_text") or ""))
        if not his:
            continue
        slot = by_sid.setdefault(sid, {"his": {}, "our": []})
        slot["his"].update(his)
        slot["our"].extend(list((row.get("diff") or {}).get("our_turns") or []))
    changed: Dict[str, Any] = {}
    for sid, slot in by_sid.items():
        key = f"turns:{sid}"
        old = prev.get(key) if isinstance(prev.get(key), dict) else {}
        drawn = step_turn_drawn(old.get("drawn") or {}, slot["his"], slot["our"])
        val = {
            "goal": "wave_turns",
            "base": "our_ohlc",
            "his": slot["his"],
            "drawn": drawn,
            "as_of": _ymd(as_of),
        }
        old_his = old.get("his") or {}
        old_drawn = old.get("drawn") or {}
        if old_his != slot["his"] or old_drawn != drawn:
            if upsert_rule(db_path, key, val, as_of=as_of, note="日對質：轉折位置與點位往他的浪走"):
                changed[key] = val
    return changed


def propose_rule_updates(
    db_path: str,
    as_of: str,
    compares: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """有發文且價格／文意還沒同時 ≥95% 才改話筒讀的 rules。

    改的是方法：敘事詞、撐帶刻度、通道幾何。不准寫入他的目標價。
    兩軸都到 95% 的那天停改。沒有比較列不改。不准改黃金買點／飆大／其他鈕。
    """
    like = likeness_of(compares)
    prev = load_rules(db_path)
    prev_absorb = prev.get("absorb") if isinstance(prev.get("absorb"), dict) else {}
    rev = int((prev_absorb or {}).get("rev") or 0)
    book = {
        "rev": rev,
        "as_of": _ymd(as_of),
        "reached_95": bool(like.get("reached_95")),
        "prices": like.get("prices"),
        "narrative": like.get("narrative"),
        "target": SIM_TARGET,
        "not_buy_signal": True,
    }
    if not compares:
        return {
            "changed": False,
            "keys": [],
            "values": {},
            "likeness": like,
            "held": False,
            "learn": {"n": 0, "transfer_n": 0},
        }
    # mismatch／未到 95%：先落 why 卡（動機／滿足點／時間軸／可遷移）；到 95% 仍可對有差距列建卡
    learn = persist_mismatch_learn(db_path, as_of, compares)
    if like.get("reached_95"):
        book["hold"] = True
        book["learn_n"] = int(learn.get("n") or 0)
        upsert_rule(db_path, "absorb", book, as_of=as_of, note="日對質：價格與文意已到 95%，停改畫法")
        return {
            "changed": False,
            "keys": list(learn.get("keys") or []),
            "values": {},
            "likeness": like,
            "held": True,
            "learn": learn,
        }

    changed: Dict[str, Any] = {}
    gap_channel = 0
    his_prices: List[float] = []
    missing_words: List[str] = []
    for row in compares:
        diff = row.get("diff") or {}
        gaps = list(diff.get("gaps") or [])
        if any("通道" in g or "壓線" in g for g in gaps):
            gap_channel += 1
        for p in list((diff.get("his") or {}).get("prices_guess") or []):
            try:
                his_prices.append(float(p))
            except Exception:
                continue
        his_text = str(row.get("his_text") or "")
        our_text = str(row.get("caption") or "")
        for w in method_words_missing(our_narrative=our_text, his_narrative=his_text):
            if w not in missing_words:
                missing_words.append(w)

    if gap_channel > 0:
        key = "paint_geometry"
        val = {"wedge": True, "desc_press_vb": True, "zones": True, "as_of": _ymd(as_of)}
        old = prev.get(key) if isinstance(prev.get(key), dict) else {}
        if old.get("wedge") is not True or old.get("zones") is not True:
            if upsert_rule(db_path, key, val, as_of=as_of, note="日對質：補通道／壓線幾何"):
                changed[key] = val

    px_score = like.get("prices")
    if px_score is not None and float(px_score) < SIM_TARGET:
        old_sb = prev.get("support_band") if isinstance(prev.get("support_band"), dict) else {}
        try:
            wick = float(old_sb.get("wick_ratio") or 0.975)
        except Exception:
            wick = 0.975
        wick = max(0.95, round(wick - 0.005, 3))
        grain = _price_grain(his_prices) or list(old_sb.get("psych_steps") or [50, 100])
        val = {"wick_ratio": wick, "psych_steps": grain, "as_of": _ymd(as_of)}
        old_grain = [int(x) for x in (old_sb.get("psych_steps") or [])]
        old_wick = None
        try:
            if old_sb.get("wick_ratio") is not None:
                old_wick = round(float(old_sb.get("wick_ratio")), 3)
        except Exception:
            old_wick = None
        if old_wick != wick or old_grain != [int(x) for x in grain]:
            if upsert_rule(db_path, key="support_band", value=val, as_of=as_of, note="日對質：撐帶刻度對齊他的整數關"):
                changed["support_band"] = val

    prev_narr = prev.get("narrative_template") if isinstance(prev.get("narrative_template"), dict) else {}
    prev_words = [str(w) for w in (prev_narr.get("method_words") or [])]
    words = list(prev_words)
    for w in missing_words:
        if w not in words:
            words.append(w)
    words = words[:12]
    if words != prev_words:
        val = {
            "as_of": _ymd(as_of),
            "suffix": "樞紐重算對照文意（不保證・不是買訊）",
            "prefer_meaning_align": True,
            "method_words": words,
        }
        if upsert_rule(db_path, "narrative_template", val, as_of=as_of, note="日對質：補他有我們無的方法詞"):
            changed["narrative_template"] = val

    changed.update(_upsert_stock_turns(db_path, as_of, compares, prev))

    book["rev"] = rev + (1 if changed else 0)
    book["goal"] = "wave_turns_on_our_ohlc"
    book["levers"] = list(changed.keys())
    book["learn_n"] = int(learn.get("n") or 0)
    upsert_rule(
        db_path,
        "absorb",
        book,
        as_of=as_of,
        note="日對質落檔" if not changed else "日對質：改畫法編碼",
    )
    keys_out = list(changed.keys())
    for k in learn.get("keys") or []:
        if k not in keys_out:
            keys_out.append(k)
    return {
        "changed": bool(changed),
        "keys": keys_out,
        "values": changed,
        "likeness": like,
        "held": False,
        "learn": learn,
    }


def _mark_pipeline(db_path: str, run_day: str, status: str, notes: str) -> None:
    """只寫本軌鍵 ``dc-sf-silent-{YYYYMMDD}``。不准別軌 success 蓋掉本軌失敗。

    empty／無發文仍記 success（notes 含 empty）；真正失敗記 error。
    """
    path = str(db_path or "").strip()
    if not path:
        return
    key = pipeline_key(run_day)
    if not key.startswith(PIPE_PREFIX):
        return
    st = str(status or "").strip().lower() or "error"
    # 只允許本軌狀態字；防止誤傳把別軌語意寫進來
    if st not in ("success", "error", "running", "computed", "empty"):
        st = "error"
    # empty 對外仍當 success（有跑完），notes 保留 empty_* 供健檢辨識
    if st == "empty":
        st = "success"
        if "empty" not in str(notes or "").lower():
            notes = f"empty:{notes}" if notes else "empty"
    stamp = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_date TEXT PRIMARY KEY,
                    finished_at TEXT,
                    status TEXT,
                    notes TEXT
                );
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs(run_date, finished_at, status, notes)
                VALUES (?,?,?,?)
                """,
                (key, stamp, st, str(notes or "")[:800]),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("dc_sf pipeline_runs 寫入失敗")


def stamp_status(db_path: str, run_day: Any = None) -> Optional[Dict[str, Any]]:
    """讀本軌成功／失敗戳（不受 recent 六筆限制）。缺＝None。"""
    path = str(db_path or "").strip()
    day = _ymd(run_day) if run_day is not None else _ymd(_taipei_now())
    key = pipeline_key(day)
    if not path or not key or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT run_date, finished_at, status, notes FROM pipeline_runs WHERE run_date=?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return {
        "run_date": row[0],
        "finished_at": row[1],
        "status": row[2],
        "notes": row[3] or "",
        "job": JOB_KIND,
        "label": "情境預估日對質",
        "as_of": day,
    }


def already_done(db_path: str, run_day: str) -> bool:
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return False
    hit = stamp_status(path, run_day)
    return bool(hit and str(hit.get("status") or "") == "success")


def night_tick(
    db_path: str = "",
    *,
    now: Optional[datetime] = None,
    skip_if_done: bool = True,
    session=None,
) -> Dict[str, Any]:
    """日流程：抓→渲→比→（可改就）更新 rules→落檔。永不推話筒。"""
    try:
        from config import get_db_path

        path = str(db_path or get_db_path() or "").strip()
    except Exception:
        path = str(db_path or "").strip()
    dt = now or _taipei_now()
    run_day = dt.astimezone(TAIPEI).date() if dt.tzinfo else dt.date()
    report: Dict[str, Any] = {
        "ok": False,
        "job": JOB_KIND,
        "run_day": _ymd(run_day),
        "as_of": "",
        "post_n": 0,
        "stock_n": 0,
        "compare_n": 0,
        "rules_changed": 0,
        "notes": "",
    }
    if not path:
        report["notes"] = "no_db"
        return report
    if not in_campaign(dt):
        report["notes"] = "out_of_campaign"
        report["ok"] = True
        return report
    # 硬規則：01:00–02:19 讓飆大；本檔不重壓
    if biaoke_night_busy(dt):
        report["notes"] = "defer_biaoke_night_window"
        report["ok"] = True
        return report
    if skip_if_done and already_done(path, run_day):
        report["notes"] = "skip_if_done"
        report["ok"] = True
        return report

    lock = acquire_job_lock(path)
    if lock is None:
        report["notes"] = "lock_busy"
        report["ok"] = True
        return report

    as_of = _ymd(run_day)
    win_start, win_end = window_bounds(dt, LOOKBACK_HOURS)
    report["as_of"] = as_of
    report["window"] = (
        f"{win_start.strftime('%Y-%m-%d %H:%M')}–{win_end.strftime('%Y-%m-%d %H:%M')}"
    )
    ensure_tables(path)
    _mark_pipeline(path, run_day, "running", f"dc_sf 24h as_of={as_of}")

    try:
        posts = fetch_dc_posts_within(dt, session=session)
        saved = save_posts_and_images(path, as_of, posts, session=session)
        report["post_n"] = int(saved.get("posts") or 0)
        # 24 小時沒有主文：只落檔，不改畫法。
        if not posts:
            note = "empty_posts"
            report["notes"] = note
            report["ok"] = True
            conn = sqlite3.connect(path, timeout=30.0)
            try:
                conn.execute(
                    """
                    INSERT INTO dc_sf_daily(
                      as_of, run_day, status, post_n, stock_n, compare_n,
                      rules_changed, notes, report_json, finished_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(as_of) DO UPDATE SET
                      run_day=excluded.run_day,
                      status=excluded.status,
                      post_n=excluded.post_n,
                      stock_n=excluded.stock_n,
                      notes=excluded.notes,
                      report_json=excluded.report_json,
                      finished_at=excluded.finished_at
                    """,
                    (
                        as_of,
                        _ymd(run_day),
                        "empty",
                        report["post_n"],
                        report["stock_n"],
                        0,
                        0,
                        note,
                        json.dumps(report, ensure_ascii=False),
                        _taipei_now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            _mark_pipeline(path, run_day, "success", f"dc_sf {note} as_of={as_of}")
            return report

        out_dir = os.path.join(media_root(path), as_of, "ours")
        os.makedirs(out_dir, exist_ok=True)
        compares: List[Dict[str, Any]] = []
        seen_stocks = set()
        unmapped = 0
        stamp = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
        # 先畫完我們的圖（股號＋我們的官方股價），再對他的圖。不准畫一篇比一篇。
        drawn_rows: List[Dict[str, Any]] = []
        conn = sqlite3.connect(path, timeout=60.0)
        try:
            for post in posts:
                pid = str(post.get("id") or "").strip()
                if not pid:
                    continue
                body = str(post.get("text") or "").strip()
                image_notes = str(post.get("image_notes") or "").strip()
                his_full = (body + ("\n" + image_notes if image_notes else "")).strip()
                picked = stocks_from_posts([post], db_path=path)
                sid = str(picked[0].get("stock_id") or "") if picked else ""
                extra = [
                    str(s.get("stock_id") or "")
                    for s in picked[1:]
                    if str(s.get("stock_id") or "")
                ]
                img_paths: List[str] = []
                rows = conn.execute(
                    """
                    SELECT local_path FROM dc_sf_images
                    WHERE as_of=? AND post_id=? AND local_path!=''
                    """,
                    (as_of, pid),
                ).fetchall()
                for (lp,) in rows or []:
                    if lp:
                        img_paths.append(str(lp))
                if not sid:
                    unmapped += 1
                    path_png, cap, wave, our_narr = "", "", {}, ""
                else:
                    seen_stocks.add(sid)
                    png = os.path.join(out_dir, f"{pid}-{sid}-scenario-forecast.png")
                    path_png, cap, meta = render_our_bundle(sid, path, png)
                    wave = _our_wave_summary(meta)
                    our_narr = str((wave.get("bubble") or "") or cap or "").strip()
                drawn_rows.append(
                    {
                        "pid": pid,
                        "sid": sid,
                        "extra": extra,
                        "body": body,
                        "his_full": his_full,
                        "image_notes": image_notes,
                        "img_paths": img_paths,
                        "path_png": path_png,
                        "cap": cap,
                        "wave": wave,
                        "our_narr": our_narr,
                    }
                )
            report["drawn_n"] = sum(1 for row in drawn_rows if row.get("sid"))
            for item in drawn_rows:
                pid = item["pid"]
                sid = item["sid"]
                path_png = item["path_png"]
                cap = item["cap"]
                wave = item["wave"]
                our_narr = item["our_narr"]
                his_full = item["his_full"]
                body = item["body"]
                image_notes = item["image_notes"]
                img_paths = item["img_paths"]
                extra = item["extra"]
                diff = compare_one(
                    our_wave=wave,
                    our_caption=cap,
                    our_narrative=our_narr,
                    his_text=his_full,
                )
                if extra:
                    diff["extra_stock_ids"] = extra
                research = str(diff.get("research_note") or "")
                if not sid:
                    research = "這篇沒有點到可畫的代號。" + research
                like = diff.get("likeness") or {}
                sim = like.get("similarity")
                conn.execute(
                    """
                    INSERT INTO dc_sf_compare(
                      as_of, stock_id, post_id, our_png, our_caption, our_narrative,
                      our_wave_json, his_excerpt, his_narrative, his_image_paths,
                      diff_json, meaning_diff, research_note, created_at,
                      image_notes, similarity
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(as_of, stock_id, post_id) DO UPDATE SET
                      our_png=excluded.our_png,
                      our_caption=excluded.our_caption,
                      our_narrative=excluded.our_narrative,
                      our_wave_json=excluded.our_wave_json,
                      his_excerpt=excluded.his_excerpt,
                      his_narrative=excluded.his_narrative,
                      his_image_paths=excluded.his_image_paths,
                      diff_json=excluded.diff_json,
                      meaning_diff=excluded.meaning_diff,
                      research_note=excluded.research_note,
                      created_at=excluded.created_at,
                      image_notes=excluded.image_notes,
                      similarity=excluded.similarity
                    """,
                    (
                        as_of,
                        sid or "_none",
                        pid,
                        path_png or "",
                        cap,
                        our_narr[:4000],
                        json.dumps(wave, ensure_ascii=False),
                        body[:4000],
                        his_full[:4000],
                        json.dumps(img_paths, ensure_ascii=False),
                        json.dumps(diff, ensure_ascii=False),
                        str(diff.get("meaning_diff") or ""),
                        research[:800],
                        stamp,
                        image_notes[:2000],
                        sim,
                    ),
                )
                if sid:
                    compares.append(
                        {
                            "stock_id": sid,
                            "post_id": pid,
                            "png": path_png,
                            "caption": our_narr or cap,
                            "his_text": his_full,
                            "diff": diff,
                        }
                    )
            conn.commit()
        finally:
            conn.close()

        report["stock_n"] = len(seen_stocks)
        report["unmapped_n"] = unmapped
        report["compare_n"] = len(compares)
        if report["compare_n"] <= 0:
            report["notes"] = "empty_stocks" if unmapped else "empty_compare"
            report["ok"] = True
            conn = sqlite3.connect(path, timeout=30.0)
            try:
                conn.execute(
                    """
                    INSERT INTO dc_sf_daily(
                      as_of, run_day, status, post_n, stock_n, compare_n,
                      rules_changed, notes, report_json, finished_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(as_of) DO UPDATE SET
                      run_day=excluded.run_day,
                      status=excluded.status,
                      post_n=excluded.post_n,
                      stock_n=excluded.stock_n,
                      compare_n=excluded.compare_n,
                      rules_changed=excluded.rules_changed,
                      notes=excluded.notes,
                      report_json=excluded.report_json,
                      finished_at=excluded.finished_at
                    """,
                    (
                        as_of,
                        _ymd(run_day),
                        "empty",
                        report["post_n"],
                        report["stock_n"],
                        0,
                        0,
                        report["notes"],
                        json.dumps(report, ensure_ascii=False),
                        _taipei_now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            _mark_pipeline(path, run_day, "success", f"dc_sf {report['notes']} as_of={as_of}")
            return report

        applied = propose_rule_updates(path, as_of, compares)
        report["rules_changed"] = 1 if applied.get("changed") else 0
        report["rule_keys"] = list(applied.get("keys") or [])
        report["likeness"] = applied.get("likeness") or {}
        report["learn"] = applied.get("learn") or {}
        like = report["likeness"]
        learn = report["learn"]

        def _fmt_axis(v: Any) -> str:
            if v is None:
                return "na"
            try:
                return f"{float(v):.2f}"
            except Exception:
                return "na"

        hold = "hold" if applied.get("held") else (
            "rules=" + (",".join(report["rule_keys"]) or "none")
        )
        report["notes"] = (
            f"posts={report['post_n']};drawn={report.get('drawn_n')};compared={report['compare_n']};"
            f"px={_fmt_axis(like.get('prices'))};narr={_fmt_axis(like.get('narrative'))};"
            f"learn={int(learn.get('n') or 0)};{hold}"
        )
        report["ok"] = True

        # 日報表
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                """
                INSERT INTO dc_sf_daily(
                  as_of, run_day, status, post_n, stock_n, compare_n,
                  rules_changed, notes, report_json, finished_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(as_of) DO UPDATE SET
                  run_day=excluded.run_day,
                  status=excluded.status,
                  post_n=excluded.post_n,
                  stock_n=excluded.stock_n,
                  compare_n=excluded.compare_n,
                  rules_changed=excluded.rules_changed,
                  notes=excluded.notes,
                  report_json=excluded.report_json,
                  finished_at=excluded.finished_at
                """,
                (
                    as_of,
                    _ymd(run_day),
                    "success",
                    report["post_n"],
                    report["stock_n"],
                    report["compare_n"],
                    report["rules_changed"],
                    report["notes"],
                    json.dumps(report, ensure_ascii=False),
                    _taipei_now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # 可改 rules 時另留提案檔（合主／health 由日更流程接；此處不推話筒）
        if applied.get("changed"):
            try:
                prop_dir = os.path.join(media_root(path), as_of)
                os.makedirs(prop_dir, exist_ok=True)
                with open(
                    os.path.join(prop_dir, "rules_patch.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(applied, f, ensure_ascii=False, indent=2)
            except Exception:
                logger.debug("rules_patch 落檔略過", exc_info=True)

        _mark_pipeline(path, run_day, "success", f"dc_sf {report['notes']}")
        return report
    except Exception as e:
        # 失敗只記本檔 pipeline；不准擋飆大／查股
        logger.exception("dc_sf_silent 日流程失敗（不擋飆大）")
        report["notes"] = f"error:{e}"
        try:
            _mark_pipeline(path, run_day, "error", report["notes"][:500])
        except Exception:
            pass
        return report
    finally:
        release_job_lock(lock)


def optimize_status_one_liner(db_path: str = "") -> str:
    """唯一准講的明確優化狀態一句（無過程％）。"""
    start, _end = campaign_window()
    path = str(db_path or "").strip()
    n = 0
    changed = 0
    if path and os.path.isfile(path):
        try:
            ensure_tables(path)
            conn = sqlite3.connect(path, timeout=10.0)
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(rules_changed),0)
                    FROM dc_sf_daily
                    WHERE status='success' AND compare_n>0
                    """
                ).fetchone()
                if row:
                    n = int(row[0] or 0)
                    changed = int(row[1] or 0)
            finally:
                conn.close()
        except Exception:
            pass
    return (
        f"明確優化狀態：情境預估×D.C 靜默對質 "
        f"{start.isoformat()} 起每天；"
        f"已落有效日 n={n}、rules 更新日={changed}；"
        f"永遠不是買訊"
    )
