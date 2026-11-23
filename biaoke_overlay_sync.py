# -*- coding: utf-8 -*-
"""SYNC-OVERLAY：公開主文＋自回＋附圖補至今日，增量合併 atoms／chart 索引。

只認他自己（Member-All 頻道＋討論串自回）。社團不進公開 overlay。
不准假圖：只記他附的 image.cmoney.tw/attachment URL，不下載、不 OCR 發明。
時區 Asia/Taipei。不是買訊。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
_OUT_DIR = os.path.join(_DIR, "observe_manual")
OVERLAY_DELTA_GZ = os.path.join(_OUT_DIR, "overlay_delta.json.gz")
OVERLAY_REPORT_JSON = os.path.join(_OUT_DIR, "OVERLAY_SYNC_REPORT.json")
OVERLAY_DOC_MD = os.path.join(_OUT_DIR, "OVERLAY_SYNC.md")

ARCHIVE_END = "2026-09-10"  # archive_1709 末日；之後靠 catchup／ingest／本腳本
CHANNEL_WEIGHT_URL = (
    "https://www.cmoney.tw/api/mach/api/Article/GetChannelsArticleByWeight"
)
_AVATAR = "image.cmoney.tw/profile/"
_CODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _taipei_from_ms(ms: Any) -> Tuple[str, str]:
    try:
        n = int(ms or 0)
    except (TypeError, ValueError):
        return "", ""
    if n <= 0:
        return "", ""
    if n > 10_000_000_000:  # ms
        n = n / 1000.0
    dt = datetime.fromtimestamp(n, tz=timezone.utc).astimezone(TAIPEI)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _tag_names(commodity_tags: Any) -> List[str]:
    out: List[str] = []
    for item in commodity_tags or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().upper()
        if not key or key in {"TWA00", "TWII", "IX0001"}:
            continue
        if re.fullmatch(r"\d{4}", key):
            if key not in out:
                out.append(key)
            continue
        # 其餘代號不當股名猜；交給正文點名
    return out[:8]


def _media_urls(multi_media: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in multi_media or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or _AVATAR in url:
            continue
        if "image.cmoney.tw/attachment/" not in url:
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def api_article_to_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GetChannelsArticleByWeight 一則 → biaoke_posts 列。"""
    if not isinstance(raw, dict):
        return None
    aid = str(raw.get("id") or "").strip()
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    try:
        creator = int(content.get("creatorId") or 0)
    except (TypeError, ValueError):
        creator = 0
    from biaoke_ingest import AUTHOR_ID

    if creator and creator != int(AUTHOR_ID):
        return None
    text = str(content.get("text") or "").strip()
    if not text:
        return None
    from biaoke_ingest import is_biaoke_voice, scrub_cmoney_chrome, _append_charts

    if not is_biaoke_voice(text):
        return None
    date_s, time_s = _taipei_from_ms(raw.get("createTime"))
    if not date_s:
        return None
    urls = _media_urls(content.get("multiMedia"))
    body = scrub_cmoney_chrome(_append_charts(text, urls, limit=8))
    tags = _tag_names(content.get("commodityTags"))
    return {
        "n": 0,
        "date": date_s,
        "time": time_s,
        "id": aid,
        "parent": "",
        "layer": 0,
        "kind": "post",
        "tags": tags,
        "text": body,
        "weight": raw.get("weight"),
    }


def fetch_member_articles_page(
    *,
    start_score: str = "0",
    count: int = 30,
    session: Any = None,
) -> List[Dict[str, Any]]:
    """公開 Member-All 分頁（X-Version 3.0）。"""
    from biaoke_ingest import (
        AUTHOR_ID,
        _cmoney_api_headers,
        _comment_tokens,
        _session,
    )

    sess = session or _session()
    tokens = _comment_tokens(sess)
    if not tokens:
        return []
    headers = _cmoney_api_headers(tokens[0])
    headers["x-version"] = "3.0"
    headers["X-Version"] = "3.0"
    channel = f"Member-All.{AUTHOR_ID}"
    try:
        resp = sess.post(
            CHANNEL_WEIGHT_URL,
            headers=headers,
            params={"startScore": str(start_score or "0"), "count": int(count)},
            json={"items": [channel]},
            timeout=30,
        )
    except Exception:
        logger.exception("Member-All 分頁失敗 score=%s", start_score)
        return []
    if int(getattr(resp, "status_code", 0) or 0) != 200:
        logger.info(
            "Member-All http=%s score=%s",
            getattr(resp, "status_code", None),
            start_score,
        )
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    return list(payload) if isinstance(payload, list) else []


def iter_member_articles_since(
    since_date: str = ARCHIVE_END,
    *,
    page_size: int = 30,
    max_pages: int = 80,
    session: Any = None,
) -> List[Dict[str, Any]]:
    """由新到舊翻頁，收到 since_date（含）之後的主文列。"""
    since = str(since_date or ARCHIVE_END).strip() or ARCHIVE_END
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    score = "0"
    for _ in range(max(1, int(max_pages))):
        page = fetch_member_articles_page(
            start_score=score, count=page_size, session=session
        )
        if not page:
            break
        stop = False
        last_weight = None
        for raw in page:
            row = api_article_to_row(raw)
            last_weight = raw.get("weight")
            if not row:
                continue
            if str(row.get("date") or "") < since:
                stop = True
                continue
            aid = str(row.get("id") or "")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            out.append(row)
        if stop:
            break
        if last_weight is None:
            break
        nxt = str(last_weight)
        if nxt == score:
            break
        score = nxt
        time.sleep(0.15)
    out.sort(key=lambda r: (r.get("date") or "", r.get("time") or "", r.get("id") or ""))
    return out


def fetch_author_replies_for(
    article_id: str,
    *,
    session: Any = None,
) -> List[Dict[str, Any]]:
    """只留他自己的回文（kind=reply）；路人丟棄。"""
    from biaoke_ingest import fetch_article_thread_api

    rows = fetch_article_thread_api(str(article_id), session=session) or []
    return [r for r in rows if str(r.get("kind") or "") == "reply"]


def seed_and_deep_upsert(
    db_path: str,
    *,
    since_date: str = ARCHIVE_END,
    fetch_replies: bool = True,
    max_pages: int = 80,
    reply_sleep_s: float = 0.25,
    session: Any = None,
) -> Dict[str, Any]:
    """本機／Render 有碟：1709＋catchup 補缺 → Member-All 深抓 → 自回 UPSERT。"""
    from biaoke_archive import seed_biaoke_archive
    from biaoke_desk import ensure_biaoke_posts_table, upsert_biaoke_posts
    from biaoke_ingest import _session

    stats: Dict[str, Any] = {
        "ok": False,
        "db": db_path,
        "seeded": 0,
        "posts_fetched": 0,
        "posts_upserted": 0,
        "replies_upserted": 0,
        "charts_in_posts": 0,
        "from": "",
        "to": "",
        "since": since_date,
    }
    if not db_path:
        stats["reason"] = "no_db"
        return stats
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    ensure_biaoke_posts_table(db_path)
    try:
        stats["seeded"] = int(seed_biaoke_archive(db_path) or 0)
    except Exception:
        logger.exception("1709／catchup seed 失敗")
    sess = session or _session()
    posts = iter_member_articles_since(
        since_date, max_pages=max_pages, session=sess
    )
    stats["posts_fetched"] = len(posts)
    if posts:
        stats["from"] = posts[0].get("date") or ""
        stats["to"] = posts[-1].get("date") or ""
        stats["charts_in_posts"] = sum(
            1
            for p in posts
            if "附圖：https://image.cmoney.tw/attachment/" in str(p.get("text") or "")
        )
        stats["posts_upserted"] = upsert_biaoke_posts(db_path, posts)
    reply_rows: List[Dict[str, Any]] = []
    if fetch_replies:
        for i, p in enumerate(posts):
            aid = str(p.get("id") or "")
            if not aid:
                continue
            try:
                reps = fetch_author_replies_for(aid, session=sess)
            except Exception:
                logger.exception("自回抓取失敗 id=%s", aid)
                reps = []
            reply_rows.extend(reps)
            if reply_sleep_s > 0 and i + 1 < len(posts):
                time.sleep(float(reply_sleep_s))
        if reply_rows:
            stats["replies_upserted"] = upsert_biaoke_posts(db_path, reply_rows)
    stats["ok"] = True
    stats["reply_n"] = len(reply_rows)
    return stats


def load_overlay_delta(path: str = "") -> Dict[str, Any]:
    dest = path or OVERLAY_DELTA_GZ
    if not dest or not os.path.isfile(dest):
        return {"n": 0, "replies": 0, "posts": [], "source": "overlay_delta"}
    try:
        with gzip.open(dest, "rt", encoding="utf-8") as fh:
            blob = json.load(fh) or {}
    except (OSError, json.JSONDecodeError, EOFError):
        return {"n": 0, "replies": 0, "posts": [], "source": "overlay_delta"}
    if not isinstance(blob, dict):
        return {"n": 0, "replies": 0, "posts": [], "source": "overlay_delta"}
    return blob


def export_overlay_delta(
    db_path: str,
    *,
    since_date: str = ARCHIVE_END,
    path: str = "",
) -> Dict[str, Any]:
    """把 since_date 之後的公開列凍成 gzip，給無碟／CI 合併 atoms。"""
    dest = path or OVERLAY_DELTA_GZ
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    since = str(since_date or ARCHIVE_END).strip()
    rows: List[Dict[str, Any]] = []
    if db_path and os.path.isfile(db_path):
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
            ).fetchone()
            if hit:
                for r in conn.execute(
                    "SELECT id, n, date, time, parent, layer, kind, tags, text "
                    "FROM biaoke_posts WHERE date >= ? ORDER BY date, time, id",
                    (since,),
                ):
                    tags = r[7]
                    if isinstance(tags, str):
                        try:
                            tags = json.loads(tags)
                        except Exception:
                            tags = []
                    rows.append(
                        {
                            "id": r[0],
                            "n": r[1] or 0,
                            "date": r[2] or "",
                            "time": r[3] or "",
                            "parent": r[4] or "",
                            "layer": int(r[5] or 0),
                            "kind": r[6] or "post",
                            "tags": tags or [],
                            "text": r[8] or "",
                        }
                    )
        finally:
            conn.close()
    posts = [r for r in rows if str(r.get("kind") or "post") != "reply"]
    replies = [r for r in rows if str(r.get("kind") or "") == "reply"]
    chart_urls: List[str] = []
    seen_u = set()
    for r in rows:
        for m in re.findall(
            r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
            str(r.get("text") or ""),
            flags=re.I,
        ):
            if m not in seen_u:
                seen_u.add(m)
                chart_urls.append(m)
    blob = {
        "source": "overlay_sync",
        "note": (
            f"archive_1709 之後（>={since}）公開主文＋自回增量；"
            "只認他自己；附圖只留 URL；社團不進。"
        ),
        "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S"),
        "since": since,
        "n": len(posts),
        "replies": len(replies),
        "chart_urls_n": len(chart_urls),
        "from": posts[0]["date"] if posts else (rows[0]["date"] if rows else ""),
        "to": posts[-1]["date"] if posts else (rows[-1]["date"] if rows else ""),
        "posts": rows,
        "chart_urls": chart_urls,
    }
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, separators=(",", ":"))
    return blob


def merge_chart_index_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    src: str = "overlay_sync",
    index_path: str = "",
) -> Dict[str, Any]:
    """增量把新附圖 URL 併進 chart_index；不准假圖、不下載。"""
    import gzip as _gzip

    from biaoke_charts import (
        AVATAR_NEEDLE,
        CHART_INDEX_GZ,
        load_chart_index,
        write_chart_index,
    )

    dest = index_path or CHART_INDEX_GZ
    blob: Dict[str, Any]
    if index_path:
        if os.path.isfile(dest):
            with _gzip.open(dest, "rt", encoding="utf-8") as fh:
                blob = json.load(fh) or {}
        else:
            blob = {}
    else:
        blob = load_chart_index() or {}
    if not isinstance(blob, dict):
        blob = {}
    charts = list(blob.get("charts") or [])
    seen = {str(c.get("url") or "") for c in charts if c.get("url")}
    added = 0
    for row in rows:
        kind = str(row.get("kind") or "post")
        if kind == "bystander":
            continue
        aid = str(row.get("id") or "")
        date_s = str(row.get("date") or "")
        text = str(row.get("text") or "")
        urls = re.findall(
            r"https://image\.cmoney\.tw/attachment/[^\s\"'<>]+",
            text,
            flags=re.I,
        )
        tickers = _CODE.findall(text)
        tickers = [t for t in tickers if t not in {"2023", "2024", "2025", "2026"}][:6]
        for url in urls:
            if not url or url in seen or AVATAR_NEEDLE in url:
                continue
            seen.add(url)
            charts.append(
                {
                    "src": src,
                    "date": date_s,
                    "aid": aid,
                    "url": url,
                    "kind": "attachment",
                    "tickers": tickers,
                    "note": "",  # 不准發明圖註；BK-CHART 再標
                }
            )
            added += 1
    sources = dict(blob.get("sources") or {})
    sources[src] = int(sources.get(src) or 0) + added
    out = {
        "n": len(charts),
        "sources": sources,
        "note": blob.get("note")
        or "圖檔不進 git；頭像已剔除。overlay 只併 URL。",
        "charts": charts,
    }
    write_chart_index(out, dest)
    try:
        load_chart_index.cache_clear()
    except Exception:
        pass
    return {"added": added, "n": out["n"], "sources": sources}


def write_overlay_doc() -> str:
    body = """# 飆大 overlay 同步（SYNC-OVERLAY）

目標：把公開主文＋他自己回文＋附圖 URL 補到**今日**，餵 atoms／圖比對。  
邊界：`MISSION_LOCK_20261123.md`；只認他自己；社團不准話筒原文；不准假圖。

## 本機／Render 有碟

```bash
# 預設讀 config.get_db_path()（Render 永久碟 data/wayne_market.db）
python3 scripts/biaoke_sync_overlay_heal.py

# 指定碟＋只補主文（略過自回，較快）
python3 scripts/biaoke_sync_overlay_heal.py --db /opt/render/project/src/data/wayne_market.db --no-replies

# 自訂起日（預設 2026-09-10＝1709 末日）
python3 scripts/biaoke_sync_overlay_heal.py --since 2026-09-10
```

流程：`seed_biaoke_archive`（1709＋git catchup）→ Member-All 深抓 → 討論串自回 → 凍 `overlay_delta.json.gz` → 增量 chart_index → 重抽 atoms。

## 雲端無 Render 碟

- 仍可對公開 API 深抓，寫進本機暫存 DB 後匯出 `overlay_delta.json.gz`（進 git／observe_manual）。
- atoms 會合併：archive_1709 ＋ catchup ＋ **overlay_delta** ＋ DB overlay ＋社團後台。
- 正式碟上線後再跑同一腳本 UPSERT，讓 Render `biaoke_posts` 與 delta 對齊。

## 不准

- 假圖／假柱；把社團原文當公開 overlay
- 搶正式 `TELEGRAM_BOT_TOKEN` getUpdates
- 改黃金買點
"""
    os.makedirs(os.path.dirname(OVERLAY_DOC_MD) or ".", exist_ok=True)
    with open(OVERLAY_DOC_MD, "w", encoding="utf-8") as fh:
        fh.write(body)
    return OVERLAY_DOC_MD


def run_heal(
    *,
    db_path: str = "",
    since_date: str = ARCHIVE_END,
    fetch_replies: bool = True,
    max_pages: int = 80,
    extract_atoms: bool = True,
    merge_charts: bool = True,
) -> Dict[str, Any]:
    """一鍵 heal：有碟就寫庫；一定凍 delta；可重抽 atoms／併圖索引。"""
    from config import get_db_path

    dbp = str(db_path or os.environ.get("WAYNE_DB_PATH") or get_db_path() or "").strip()
    write_overlay_doc()
    sync = seed_and_deep_upsert(
        dbp,
        since_date=since_date,
        fetch_replies=fetch_replies,
        max_pages=max_pages,
    )
    delta = export_overlay_delta(dbp, since_date=since_date)
    chart_stats: Dict[str, Any] = {}
    if merge_charts:
        chart_stats = merge_chart_index_from_rows(delta.get("posts") or [])
    atom_stats: Dict[str, Any] = {}
    if extract_atoms:
        try:
            from biaoke_observe_atoms import run_extract

            payload = run_extract(db_path=dbp)
            cov = payload.get("coverage") or {}
            meta = payload.get("corpus") or {}
            atom_stats = {
                "atom_n": payload.get("atom_n"),
                "core_n": cov.get("core_n"),
                "merged_n": meta.get("merged_n"),
                "from": meta.get("from"),
                "to": meta.get("to"),
                "db_n": meta.get("db_n"),
                "delta_n": meta.get("delta_n"),
                "gaps": cov.get("gaps") or [],
            }
        except Exception as exc:
            logger.exception("atoms 重抽失敗")
            atom_stats = {"error": str(exc)}
    report = {
        "generated_at": datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S"),
        "sync": sync,
        "delta": {
            "n": delta.get("n"),
            "replies": delta.get("replies"),
            "chart_urls_n": delta.get("chart_urls_n"),
            "from": delta.get("from"),
            "to": delta.get("to"),
            "path": OVERLAY_DELTA_GZ,
        },
        "charts": chart_stats,
        "atoms": atom_stats,
    }
    os.makedirs(os.path.dirname(OVERLAY_REPORT_JSON) or ".", exist_ok=True)
    with open(OVERLAY_REPORT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return report
