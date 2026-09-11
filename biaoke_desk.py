# -*- coding: utf-8 -*-
"""飆客獨立區：公開文檢索與觀點頁。不進海選、不改高低卡。"""
from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
_INDEX = os.path.join(_DIR, "corpus_index.json")  # 只補標籤；不准當融合底圖

_YEAR_END = re.compile(r"(去年年底|去年底|年底|年終|過年|年終獎金|2025年底|12月)")
_PROGRESS = re.compile(r"(進步|怎麼觀察|如何觀察|為什麼進步|為何進步|觀察方法|細微波)")

_BIAOKE_POSTS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_posts (
    id TEXT PRIMARY KEY,
    n INTEGER NOT NULL DEFAULT 0,
    date TEXT NOT NULL DEFAULT '',
    time TEXT NOT NULL DEFAULT '',
    parent TEXT NOT NULL DEFAULT '',
    layer INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'post',
    tags TEXT NOT NULL DEFAULT '[]',
    text TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""


def ensure_biaoke_posts_table(db_path: str) -> None:
    """公開文 overlay。同一顆 wayne_market.db，不是私人表。"""
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_BIAOKE_POSTS_DDL)
        conn.commit()
    finally:
        conn.close()
    try:
        from biaoke_link import ensure_biaoke_mentions_table

        ensure_biaoke_mentions_table(db_path)
    except Exception:
        pass


def upsert_biaoke_posts(db_path: str, rows: List[Dict[str, Any]]) -> int:
    """只寫動到的列。種子 JSON 不動。"""
    if not db_path or not rows:
        return 0
    ensure_biaoke_posts_table(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for row in rows:
            aid = str(row.get("id") or "").strip()
            if not aid:
                continue
            tags = row.get("tags") or []
            if not isinstance(tags, str):
                tags = json.dumps(list(tags), ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO biaoke_posts (
                    id, n, date, time, parent, layer, kind, tags, text, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    n=excluded.n,
                    date=excluded.date,
                    time=excluded.time,
                    parent=excluded.parent,
                    layer=excluded.layer,
                    kind=excluded.kind,
                    tags=excluded.tags,
                    text=excluded.text,
                    updated_at=excluded.updated_at;
                """,
                (
                    aid,
                    int(row.get("n") or 0),
                    str(row.get("date") or ""),
                    str(row.get("time") or ""),
                    str(row.get("parent") or ""),
                    int(row.get("layer") or 0),
                    str(row.get("kind") or "post"),
                    tags,
                    str(row.get("text") or ""),
                    now,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _overlay_posts(db_path: Optional[str]) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return []
        rows = conn.execute(
            "SELECT id, n, date, time, parent, layer, kind, tags, text FROM biaoke_posts"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        raw_tags = r[7]
        try:
            tags = json.loads(raw_tags) if isinstance(raw_tags, str) else list(raw_tags or [])
        except json.JSONDecodeError:
            tags = []
        if not isinstance(tags, list):
            tags = []
        out.append(
            {
                "id": r[0],
                "n": r[1],
                "date": r[2] or "",
                "time": r[3] or "",
                "parent": r[4] or "",
                "layer": int(r[5] or 0),
                "kind": r[6] or "post",
                "tags": tags,
                "text": r[8] or "",
            }
        )
    return out


@lru_cache(maxsize=1)
def _load_seed() -> Dict[str, Any]:
    with open(_INDEX, encoding="utf-8") as fh:
        return json.load(fh)


def _empty_blob() -> Dict[str, Any]:
    return {
        "source": "drive-1709-public",
        "n": 0,
        "replies": 0,
        "from": "",
        "to": "",
        "posts": [],
    }


@lru_cache(maxsize=1)
def _load_archive() -> Dict[str, Any]:
    """Drive 公開主文＋樓中樓。沒這包就空，不准退回 520 篇種子。"""
    try:
        from biaoke_archive import load_bundled_archive

        blob = load_bundled_archive() or {}
    except Exception:
        return {}
    return blob if blob.get("posts") else {}


def _put_post(
    posts: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
    row: Dict[str, Any],
    *,
    overwrite: bool,
) -> None:
    aid = str(row.get("id") or "")
    if not aid:
        return
    old = by_id.get(aid)
    if old is None:
        posts.append(row)
        by_id[aid] = row
        return
    if not overwrite:
        if not (old.get("tags") or []) and (row.get("tags") or []):
            old["tags"] = list(row.get("tags") or [])
        if not str(old.get("text") or "").strip() and str(row.get("text") or "").strip():
            old["text"] = row.get("text")
        return
    keep_tags = list(old.get("tags") or [])
    keep_text = str(old.get("text") or "")
    old.update(row)
    if not (old.get("tags") or []) and keep_tags:
        old["tags"] = keep_tags
    if not str(old.get("text") or "").strip() and keep_text:
        old["text"] = keep_text


def load_corpus(db_path: Optional[str] = None) -> Dict[str, Any]:
    """完整公開文（Drive 約 1700 則主文）＋同一顆行情庫 overlay。

    融合基準永遠是 archive_1709.json.gz（雲端硬碟那一千七百多則）。
    不准用 corpus_index.json 當底。沒這包就空，不要退回 520。
    同一篇 id 以資料庫為準（盤中 ingest）。
    """
    arch = _load_archive()
    if arch.get("posts"):
        blob = copy.deepcopy(arch)
    else:
        blob = _empty_blob()
    posts: List[Dict[str, Any]] = list(blob.get("posts") or [])
    by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
    if arch.get("posts"):
        try:
            seed_rows = list((_load_seed() or {}).get("posts") or [])
        except Exception:
            seed_rows = []
        for row in seed_rows:
            _put_post(posts, by_id, copy.deepcopy(row), overwrite=False)
    for row in _overlay_posts(db_path):
        aid = str(row.get("id") or "")
        if not aid:
            continue
        old = by_id.get(aid)
        if old is None:
            posts.append(row)
            by_id[aid] = row
        else:
            keep_tags = list(old.get("tags") or [])
            keep_text = str(old.get("text") or "")
            old.update(row)
            if not (old.get("tags") or []) and keep_tags:
                old["tags"] = keep_tags
            if not str(old.get("text") or "").strip() and keep_text:
                old["text"] = keep_text
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
    return blob


def load_corpus_cache_clear() -> None:
    try:
        _load_seed.cache_clear()
    except Exception:
        pass
    try:
        _load_archive.cache_clear()
    except Exception:
        pass
    try:
        from biaoke_link import link_cache_clear

        link_cache_clear()
    except Exception:
        pass


def _default_db_path() -> Optional[str]:
    try:
        from config import get_db_path

        path = get_db_path()
        return path if path and os.path.isfile(path) else None
    except Exception:
        return None


def biaoke_article_url(aid: str) -> str:
    """樓中樓 id 是 184499206:a2，連結仍指主文。"""
    base = str(aid or "").split(":")[0]
    if not base.isdigit():
        return ""
    return f"https://www.cmoney.tw/forum/article/{base}"


def corpus_span(db_path: Optional[str] = None) -> str:
    blob = load_corpus(db_path if db_path is not None else _default_db_path())
    n = int(blob.get("n") or 0)
    replies = int(blob.get("replies") or 0)
    extra = f"＋{replies} 則回覆" if replies else ""
    return f"{blob.get('from') or ''}～{blob.get('to') or ''}　{n} 篇{extra}"


def format_biaoke_welcome_html() -> str:
    """按飆大進去：開成對話窗口，不倒課綱。問句走這顆對話腦。"""
    from biaoke_brain import WINDOW_OPEN

    return WINDOW_OPEN


def format_biaoke_desk_html() -> str:
    span = html_escape(corpus_span())
    return (
        "<b>飆客獨立區</b>\n"
        "這區跟海選／高低卡無關，也不改黃金買點。來源是 CMoney「期股多空雙飆客」公開發文"
        f"（{span}）。不是買訊。\n"
        "\n"
        "<b>兩年進步在哪</b>\n"
        "2025 夏：點族群、半山腰用隔日沖、漲一倍見好就收。\n"
        "2025 秋：開始用波浪＋夜盤，但點位被拿去打台指期，11 月起大盤點位少公開。\n"
        "2025-11-21：公開檢討「該看台積電量價、不該只看大盤沒出量」。\n"
        "2025 年底～2026 初：主戰場改記憶體（南亞科／華邦電／群聯／模組），PCB／F4 做頭就撤。\n"
        "2026：費半當台股先行、台指期細微波數 5／9 段、資金水位跟波段走。這套觀察幾乎沒人公開這樣做。\n"
        "\n"
        "<b>他怎麼看</b>\n"
        "1 夜盤／台指期連續盤細微波（15 分＋60 分），不是只看加權日 K。他自己寫的四步：認識調整型態 → 拆線 → 完整結構消去不符合的 → 升／降軌道破壞才算轉折\n"
        "2 夜盤先於日盤；多標籤並存時用台積電量價決勝（這塊他稱不公開）\n"
        "3 1-4 重疊＝下跌趨勢化解。費半 1-4 重疊＝下跌趨勢化解，台股跟進\n"
        "4 量先價行：爆大量當日高低當壓／撐，量縮站上才進，否則放棄\n"
        "5 連點：同次級浪 2 低連浪 4 低＝上升軌；高連更低高＝下降壓\n"
        "6 買點只有三個：整理末端／突破回測／行進中隔日沖。半山腰只隔日沖\n"
        "7 技術面領先新聞；新聞變多常是中短高點。同族群看次族群第一名整理完成、誰先過前高才接棒\n"
        "8 量價背離只認連續一波攻擊到頂（他 2025-06-27 原文），不是大盤反彈或台積電緩漲\n"
        "9 KD／MACD／布林他不算技術分析；認支撐、窒息量、波浪段數。停損約 7～10%（長線龍頭另論）\n"
        "\n"
        "<b>接著怎麼問</b>\n"
        "直接打字或語音即可，裡面沒有選單。問句會在這邊彙整後回你。"
        "精簡六顆沒這鈕，打 <code>飆大</code> 或「完整選單」。"
        "也可打 <code>飆大 勤誠</code>。資料庫沒寫過的檔（例如藝舍-KY）也會用同一套框架套官方 K，不上買訊。"
    )


def _date_ok(post: Dict[str, Any], start: str, end: str) -> bool:
    d = str(post.get("date") or "")
    return start <= d <= end


def search_biaoke(ask: str, *, limit: int = 6, db_path: Optional[str] = None) -> str:
    """關鍵字／時間查公開文。沒對上就交給對話腦用官方 K 套框架，不說不猜。"""
    q = (ask or "").strip()
    if not q:
        return format_biaoke_welcome_html()
    if _PROGRESS.search(q) and not re.search(r"\d{4}", q):
        return format_biaoke_desk_html()

    blob = load_corpus(db_path if db_path is not None else _default_db_path())
    posts: List[Dict[str, Any]] = list(blob.get("posts") or [])
    start, end = "", "9999"
    title = f"飆客公開文　{html_escape(q)}"
    year_end = bool(_YEAR_END.search(q))
    if year_end:
        start, end = "2025-11-15", "2026-01-20"
        title = "飆客　2025 年底～2026 年初在做什麼"
        head = (
            "當時主戰場是<b>記憶體</b>。"
            "12/17 起布局（群聯／華邦電量價到整理末端，盯美光財報）；"
            "之後南亞科、華邦電、群聯、模組（威剛／十銓）續抱。"
            "他明講：其他族群不要再介入，專心做記憶體。"
            "同時把 PCB／F4／散熱（台光電、金像電、金居、尖點、奇鋐、勤誠）當做出貨或做頭、要撤或等反彈出清。"
            "無塵室建廠（漢唐、聖暉、亞翔）12 月中有短暫配置。"
            "下面是原文摘錄。\n"
        )
    else:
        head = ""

    skip = {"飆客", "飆大", "AI飆客", "去年年底", "去年底", "年底", "年終"}
    keys = [k for k in re.split(r"[\s,，、]+", q) if k and k not in skip]
    scored: List[tuple] = []
    for p in posts:
        if start and not _date_ok(p, start, end):
            continue
        text = str(p.get("text") or "")
        tags = [str(t) for t in (p.get("tags") or [])]
        blob_l = text + " " + " ".join(tags)
        score = 2 if year_end else 0
        for k in keys:
            if k in tags:
                score += 6
            score += blob_l.count(k)
        if year_end and "記憶體" in tags:
            score += 8
        if score <= 0:
            continue
        scored.append((score, p))
    if year_end:
        # 「去年年底」先給 12 月，尤其 12/17 布局日；其餘由新到舊。
        scored.sort(
            key=lambda x: (
                0 if str(x[1].get("date") or "").startswith("2025-12") else 1,
                0 if str(x[1].get("date") or "") == "2025-12-17" else 1,
                -int(str(x[1].get("date") or "0").replace("-", "") or 0),
                -int(x[0]),
            )
        )
    else:
        scored.sort(
            key=lambda x: (
                -x[0],
                -int(str(x[1].get("date") or "0").replace("-", "") or 0),
            )
        )
    if not scored:
        return (
            f"<b>{title}</b>\n"
            "資料庫沒對上這句。會改用官方 K＋飆大框架來看；不是買訊。"
        )
    lines = [f"<b>{title}</b>", head] if head else [f"<b>{title}</b>"]
    for _sc, p in scored[:limit]:
        tags = "、".join(html_escape(t) for t in (p.get("tags") or [])[:6])
        snip = html_escape(re.sub(r"\s+", " ", str(p.get("text") or ""))[:180])
        aid = html_escape(str(p.get("id") or ""))
        href = biaoke_article_url(str(p.get("id") or ""))
        lines.append(
            f"{html_escape(p.get('date'))} {html_escape(p.get('time') or '')}"
            + (f"　{tags}" if tags else "")
            + "\n"
            + snip
            + (f"\n{html_escape(href)}" if href else "")
        )
    return "\n\n".join(x for x in lines if x)


def format_biaoke_html(ask: Optional[str] = None) -> str:
    return search_biaoke(ask or "")
