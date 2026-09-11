# -*- coding: utf-8 -*-
"""三遍交叉比對：原文盤點跑三次指紋必須相同，再對規則抽取與官方 OHLC／附圖。

Pass1 原文：每則全文雜湊、每個數字、每張附圖網址、每個點名。
Pass2 規則：目標／支撐／波浪／例子／大盤點位。
Pass3 官方：當日 OHLC、本機佐證圖、庫缺標缺；夜盤目標對台指期夜盤。
不是買訊。15 分 K 不數。CMoney 圖像素不 OCR。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.BiaokeAudit")

TAIPEI = ZoneInfo("Asia/Taipei")
_PASSES = 3
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
_SOURCES = os.path.join(_DIR, "sources")
_CHARTS = os.path.join(_DIR, "charts")

_NUM = re.compile(r"(?<![\d.])(\d{1,5}(?:\.\d+)?)(?![\d])")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_WAVE = re.compile(
    r"(細微波|下降軌|上升軌|右肩|頭肩頂|破底翻|等幅測距|[59]段|[1一]\s*[-~～到至]?\s*[4四]\s*重疊)"
)
_AUDIT_ASK = re.compile(
    r"(三次|三遍|一千|1000|五百|一百|交叉|一字不漏|佐證|圖文|全部資料|"
    r"從頭到尾|所有所有|補齊|建檔|回測全部|一步一腳印)"
)
_SKIP_AFTER = re.compile(
    r"^\s*(日|天|週|周|月|年|段|波|浪|成|倍|根|檔|篇|次|分|小時|%|％|張|人|家)"
)

_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_audit_runs (
    pass_i INTEGER NOT NULL,
    fingerprint TEXT NOT NULL DEFAULT '',
    n_posts INTEGER NOT NULL DEFAULT 0,
    n_replies INTEGER NOT NULL DEFAULT 0,
    n_chars INTEGER NOT NULL DEFAULT 0,
    n_charts INTEGER NOT NULL DEFAULT 0,
    n_mentions INTEGER NOT NULL DEFAULT 0,
    n_numbers INTEGER NOT NULL DEFAULT 0,
    n_claims INTEGER NOT NULL DEFAULT 0,
    n_levels INTEGER NOT NULL DEFAULT 0,
    n_with_bar INTEGER NOT NULL DEFAULT 0,
    n_missing_bar INTEGER NOT NULL DEFAULT 0,
    n_unbound INTEGER NOT NULL DEFAULT 0,
    n_local_charts INTEGER NOT NULL DEFAULT 0,
    stable INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (pass_i)
);
"""
_GAPS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_audit_gaps (
    gap_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT '',
    post_id TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    stock_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    club INTEGER NOT NULL DEFAULT 0
);
"""
_CHARTS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_audit_charts (
    url TEXT NOT NULL,
    post_id TEXT NOT NULL,
    post_date TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'cmoney',
    path TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (url, post_id)
);
"""


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _iso_day(ymd: str) -> str:
    s = _ymd(ymd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else str(ymd or "")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _sha1(text: str) -> str:
    return hashlib.sha1(_nfkc(text).encode("utf-8")).hexdigest()


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def ensure_biaoke_audit_tables(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_RUNS_DDL)
        conn.execute(_GAPS_DDL)
        conn.execute(_CHARTS_DDL)
        conn.commit()
    finally:
        conn.close()


def is_audit_ask(ask: str) -> bool:
    return bool(_AUDIT_ASK.search(ask or ""))


def local_evidence_files() -> List[Dict[str, str]]:
    """本機已存的佐證圖（CMoney 截圖／重畫水平線）。不 OCR。"""
    out: List[Dict[str, str]] = []
    for folder, kind in ((_SOURCES, "local_source"), (_CHARTS, "local_chart")):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.startswith("."):
                continue
            low = name.lower()
            if not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            path = os.path.join(folder, name)
            m = re.match(r"(\d{8})", name)
            out.append(
                {
                    "url": f"local://{kind}/{name}",
                    "path": path,
                    "kind": kind,
                    "date": _iso_day(m.group(1)) if m else "",
                    "name": name,
                }
            )
    return out


def numbers_in(text: str) -> List[Dict[str, Any]]:
    """正文裡每一個數字＋前後文。年份／天期略過，沒檔名的也留下。"""
    blob = _nfkc(text)
    hits: List[Dict[str, Any]] = []
    seen = set()
    for m in _NUM.finditer(blob):
        raw = m.group(1)
        whole = raw.split(".")[0]
        after = blob[m.end() : m.end() + 8]
        before = blob[max(0, m.start() - 16) : m.start()]
        if _YEAR.fullmatch(whole) and "." not in raw:
            continue
        if _SKIP_AFTER.match(after):
            continue
        if re.search(r"[/／]\s*$", before):
            continue
        try:
            n = float(raw)
        except ValueError:
            continue
        key = (round(n, 4), _clip(blob[max(0, m.start() - 12) : m.end() + 12], 40))
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "n": n,
                "ctx": _clip(blob[max(0, m.start() - 24) : m.end() + 18], 72),
            }
        )
    return hits


def inventory_posts(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    club: int = 0,
) -> Dict[str, Any]:
    """Pass1：一字不漏盤點。不解釋、不對價。"""
    from biaoke_link import extract_mentions
    from biaoke_walk import post_chart_urls

    rows: List[Dict[str, Any]] = []
    n_chars = 0
    n_charts = 0
    n_mentions = 0
    n_numbers = 0
    n_wave = 0
    chart_rows: List[Dict[str, str]] = []
    fp_bits: List[str] = []
    for p in posts:
        aid = str(p.get("id") or "")
        if not aid:
            continue
        text = str(p.get("text") or "")
        body = _nfkc(text)
        digest = _sha1(body)
        charts = post_chart_urls(text)
        nums = numbers_in(text)
        mentions = extract_mentions(
            text, tags=list(p.get("tags") or []), db_path=db_path
        )
        waves = _WAVE.findall(body)
        n_chars += len(body)
        n_charts += len(charts)
        n_mentions += len(mentions)
        n_numbers += len(nums)
        if waves:
            n_wave += 1
        kind = str(p.get("kind") or "post")
        day = str(p.get("date") or "")
        fp_bits.append(
            f"{aid}|{day}|{p.get('time') or ''}|{kind}|{digest}|{len(charts)}|{len(nums)}|{len(mentions)}"
        )
        for url in charts:
            chart_rows.append(
                {
                    "url": url,
                    "post_id": aid,
                    "post_date": day,
                    "kind": "cmoney",
                    "path": "",
                }
            )
        rows.append(
            {
                "id": aid,
                "date": day,
                "time": str(p.get("time") or ""),
                "kind": kind,
                "club": int(club),
                "sha1": digest,
                "chars": len(body),
                "charts": charts,
                "mentions": mentions,
                "numbers": nums,
                "waves": waves[:8],
            }
        )
    mains = [r for r in rows if r.get("kind") != "reply"]
    replies = [r for r in rows if r.get("kind") == "reply"]
    fp_bits.sort()
    return {
        "fingerprint": hashlib.sha1("\n".join(fp_bits).encode("utf-8")).hexdigest(),
        "n_posts": len(mains),
        "n_replies": len(replies),
        "n_chars": n_chars,
        "n_charts": n_charts,
        "n_mentions": n_mentions,
        "n_numbers": n_numbers,
        "n_wave_posts": n_wave,
        "rows": rows,
        "charts": chart_rows,
        "club": int(club),
    }


def repeat_inventory(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    club: int = 0,
    times: int = _PASSES,
) -> Dict[str, Any]:
    """同一批文連續盤點三次。指紋必須全同，才算一字不漏。"""
    runs = [
        inventory_posts(posts, db_path=db_path, club=club) for _ in range(max(1, int(times)))
    ]
    fps = [str(r.get("fingerprint") or "") for r in runs]
    stable = bool(fps) and len(set(fps)) == 1 and all(fps)
    return {
        "stable": stable,
        "fingerprints": fps,
        "times": len(runs),
        "last": runs[-1] if runs else {},
        "runs": runs,
    }


def extract_pass(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
) -> Dict[str, Any]:
    """Pass2：規則抽取。跟 Pass1 分開走，才能交叉。"""
    from biaoke_claims import extract_claims
    from biaoke_walk import extract_index_levels

    n_claims = 0
    n_levels = 0
    n_examples = 0
    n_waves = 0
    bound: set = set()
    bits: List[str] = []
    for p in posts:
        aid = str(p.get("id") or "")
        text = str(p.get("text") or "")
        mentions = []
        sids = list(p.get("_sids") or [])
        names = list(p.get("_snames") or [])
        for i, sid in enumerate(sids):
            mentions.append(
                {
                    "stock_id": sid,
                    "stock_name": names[i] if i < len(names) else sid,
                }
            )
        claims = extract_claims(text, mentions=mentions or None, db_path=db_path)
        levels = extract_index_levels(text)
        n_claims += len(claims)
        n_levels += len(levels)
        for c in claims:
            role = str(c.get("role") or "")
            if role == "example":
                n_examples += 1
            if role == "wave":
                n_waves += 1
            if c.get("lo") is not None:
                bound.add((aid, round(float(c["lo"]), 4)))
            if c.get("hi") is not None:
                bound.add((aid, round(float(c["hi"]), 4)))
            bits.append(
                f"{aid}|{c.get('stock_id')}|{role}|{c.get('lo')}|{c.get('hi')}"
            )
        for hit in levels:
            lv = hit.get("level")
            if lv is not None:
                bound.add((aid, round(float(lv), 4)))
            bits.append(f"{aid}|TWII|{hit.get('role')}|{lv}|")
    bits.sort()
    return {
        "fingerprint": hashlib.sha1("\n".join(bits).encode("utf-8")).hexdigest(),
        "n_claims": n_claims,
        "n_levels": n_levels,
        "n_examples": n_examples,
        "n_waves": n_waves,
        "bound": bound,
    }


def _load_public_and_club(db_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    from biaoke_archive import load_bundled_club
    from biaoke_desk import load_corpus
    from biaoke_link import MentionGraph

    public = list((load_corpus(db_path if db_path else None) or {}).get("posts") or [])
    club = list((load_bundled_club() or {}).get("posts") or [])
    if db_path:
        public = list(MentionGraph(public, db_path=db_path).posts)
        if club:
            club = list(MentionGraph(club, db_path=db_path).posts)
    return public, club


def _bar_map(
    db_path: str, mentions: Sequence[Tuple[str, str, str]]
) -> Tuple[int, int, List[Dict[str, str]]]:
    """mentions: (post_id, date, stock_id) → 有／沒有當日官方 K。"""
    from biaoke_link import bar_on

    with_bar = 0
    missing = 0
    gaps: List[Dict[str, str]] = []
    cache: Dict[Tuple[str, str], Any] = {}
    for aid, day, sid in mentions:
        key = (sid, _ymd(day))
        if key not in cache:
            cache[key] = bar_on(db_path, sid, day) if db_path else None
        if cache[key]:
            with_bar += 1
        else:
            missing += 1
            gaps.append(
                {
                    "kind": "missing_bar",
                    "post_id": aid,
                    "post_date": day,
                    "stock_id": sid,
                    "detail": f"{sid} {day} 庫沒這天",
                }
            )
    return with_bar, missing, gaps


def _unbound_gaps(inv: Dict[str, Any], extracted: Dict[str, Any]) -> List[Dict[str, str]]:
    bound = extracted.get("bound") or set()
    out: List[Dict[str, str]] = []
    for row in inv.get("rows") or []:
        aid = str(row.get("id") or "")
        sids = {str(h.get("stock_id") or "") for h in (row.get("mentions") or [])}
        for hit in row.get("numbers") or []:
            n = round(float(hit["n"]), 4)
            if (aid, n) in bound:
                continue
            if n >= 15000:
                continue
            if not sids:
                out.append(
                    {
                        "kind": "unbound_number",
                        "post_id": aid,
                        "post_date": str(row.get("date") or ""),
                        "stock_id": "",
                        "detail": _clip(hit.get("ctx") or "", 80),
                    }
                )
    return out


def evidence_pass(
    inv: Dict[str, Any],
    extracted: Dict[str, Any],
    *,
    db_path: str = "",
    club: int = 0,
) -> Dict[str, Any]:
    """Pass3：官方價＋本機圖＋Pass1/2 缺口。"""
    mentions = []
    for row in inv.get("rows") or []:
        for h in row.get("mentions") or []:
            sid = str(h.get("stock_id") or "")
            if sid:
                mentions.append((str(row.get("id") or ""), str(row.get("date") or ""), sid))
    with_bar, missing, miss_gaps = _bar_map(db_path, mentions)
    unbound = _unbound_gaps(inv, extracted)
    local = local_evidence_files()
    charts = list(inv.get("charts") or [])
    for ev in local:
        charts.append(
            {
                "url": ev["url"],
                "post_id": "",
                "post_date": ev.get("date") or "",
                "kind": ev.get("kind") or "local",
                "path": ev.get("path") or "",
            }
        )
    return {
        "n_with_bar": with_bar,
        "n_missing_bar": missing,
        "n_unbound": len(unbound),
        "n_local_charts": len(local),
        "n_chart_urls": len(inv.get("charts") or []),
        "gaps": miss_gaps + unbound,
        "charts": charts,
        "club": int(club),
    }


def _persist(
    db_path: str,
    *,
    public_inv: Dict[str, Any],
    public_ext: Dict[str, Any],
    public_ev: Dict[str, Any],
    club_inv: Dict[str, Any],
    stable: bool,
    fps: Sequence[str],
    note: str,
) -> None:
    if not db_path:
        return
    ensure_biaoke_audit_tables(db_path)
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    runs = [
        (
            1,
            str((fps or [""])[0] if fps else public_inv.get("fingerprint") or ""),
            int(public_inv.get("n_posts") or 0),
            int(public_inv.get("n_replies") or 0),
            int(public_inv.get("n_chars") or 0),
            int(public_inv.get("n_charts") or 0),
            int(public_inv.get("n_mentions") or 0),
            int(public_inv.get("n_numbers") or 0),
            0,
            0,
            0,
            0,
            0,
            0,
            1 if stable else 0,
            "原文盤點×3 " + ("指紋相同" if stable else "指紋不同"),
            now,
        ),
        (
            2,
            str(public_ext.get("fingerprint") or ""),
            int(public_inv.get("n_posts") or 0),
            int(public_inv.get("n_replies") or 0),
            int(public_inv.get("n_chars") or 0),
            int(public_inv.get("n_charts") or 0),
            int(public_inv.get("n_mentions") or 0),
            int(public_inv.get("n_numbers") or 0),
            int(public_ext.get("n_claims") or 0),
            int(public_ext.get("n_levels") or 0),
            0,
            0,
            0,
            0,
            1 if stable else 0,
            "規則抽取 目標／支撐／波浪／例子／點位",
            now,
        ),
        (
            3,
            str(public_inv.get("fingerprint") or ""),
            int(public_inv.get("n_posts") or 0),
            int(public_inv.get("n_replies") or 0),
            int(public_inv.get("n_chars") or 0),
            int(public_inv.get("n_charts") or 0),
            int(public_inv.get("n_mentions") or 0),
            int(public_inv.get("n_numbers") or 0),
            int(public_ext.get("n_claims") or 0),
            int(public_ext.get("n_levels") or 0),
            int(public_ev.get("n_with_bar") or 0),
            int(public_ev.get("n_missing_bar") or 0),
            int(public_ev.get("n_unbound") or 0),
            int(public_ev.get("n_local_charts") or 0),
            1 if stable else 0,
            note,
            now,
        ),
    ]
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("DELETE FROM biaoke_audit_runs")
        conn.executemany(
            """
            INSERT INTO biaoke_audit_runs (
                pass_i, fingerprint, n_posts, n_replies, n_chars, n_charts,
                n_mentions, n_numbers, n_claims, n_levels, n_with_bar,
                n_missing_bar, n_unbound, n_local_charts, stable, note, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            runs,
        )
        conn.execute("DELETE FROM biaoke_audit_gaps")
        gap_rows = []
        seen = set()
        for g in (public_ev.get("gaps") or [])[:4000]:
            key = "|".join(
                [
                    str(g.get("kind") or ""),
                    str(g.get("post_id") or ""),
                    str(g.get("stock_id") or ""),
                    str(g.get("post_date") or ""),
                    _clip(g.get("detail") or "", 40),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            gap_rows.append(
                (
                    hashlib.sha1(key.encode("utf-8")).hexdigest()[:24],
                    str(g.get("kind") or ""),
                    str(g.get("post_id") or ""),
                    str(g.get("post_date") or ""),
                    str(g.get("stock_id") or ""),
                    _clip(g.get("detail") or "", 160),
                    0,
                )
            )
        if gap_rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO biaoke_audit_gaps (
                    gap_key, kind, post_id, post_date, stock_id, detail, club
                ) VALUES (?,?,?,?,?,?,?)
                """,
                gap_rows,
            )
        conn.execute("DELETE FROM biaoke_audit_charts")
        chart_rows = []
        seen_c = set()
        for c in (public_ev.get("charts") or []) + (club_inv.get("charts") or []):
            url = str(c.get("url") or "")
            pid = str(c.get("post_id") or "")
            if not url or (url, pid) in seen_c:
                continue
            seen_c.add((url, pid))
            chart_rows.append(
                (
                    url,
                    pid,
                    str(c.get("post_date") or ""),
                    str(c.get("kind") or "cmoney"),
                    str(c.get("path") or ""),
                )
            )
        if chart_rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO biaoke_audit_charts (
                    url, post_id, post_date, kind, path
                ) VALUES (?,?,?,?,?)
                """,
                chart_rows,
            )
        conn.commit()
    finally:
        conn.close()


def run_three_passes(
    db_path: str = "",
    *,
    fetch_missing: bool = False,
    fetch_limit: int = 0,
) -> Dict[str, Any]:
    """公開＋社團各走原文×3、規則、官方。pytest 不打外網。"""
    if db_path:
        try:
            from biaoke_archive import seed_biaoke_archive

            seed_biaoke_archive(db_path)
        except Exception:
            logger.debug("三遍交叉先補 overlay 略過", exc_info=True)
    public, club = _load_public_and_club(db_path)
    pub_rep = repeat_inventory(public, db_path=db_path, club=0, times=_PASSES)
    club_rep = repeat_inventory(club, db_path=db_path, club=1, times=_PASSES) if club else {
        "stable": True,
        "fingerprints": [],
        "last": {"n_posts": 0, "n_replies": 0, "rows": [], "charts": []},
    }
    pub_inv = pub_rep.get("last") or {}
    club_inv = club_rep.get("last") or {}
    pub_ext = extract_pass(public, db_path=db_path)
    club_ext = extract_pass(club, db_path=db_path) if club else {
        "n_claims": 0,
        "n_levels": 0,
        "bound": set(),
        "fingerprint": "",
    }
    fetched = {"months": 0, "rows": 0, "fail": 0}
    if (
        fetch_missing
        and db_path
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        try:
            from biaoke_verify import refresh_recent_twii

            refresh_recent_twii(db_path, range_="max")
        except Exception:
            logger.debug("三遍交叉補加權略過", exc_info=True)
        try:
            from biaoke_walk import fetch_missing_quotes

            fetched = fetch_missing_quotes(
                db_path, public, limit=int(fetch_limit or 0)
            )
        except Exception:
            logger.exception("三遍交叉補日K失敗")
    pub_ev = evidence_pass(pub_inv, pub_ext, db_path=db_path, club=0)
    club_ev = evidence_pass(club_inv, club_ext, db_path=db_path, club=1) if club else {
        "n_with_bar": 0,
        "n_missing_bar": 0,
        "n_unbound": 0,
        "n_local_charts": 0,
        "gaps": [],
        "charts": [],
    }
    stable = bool(pub_rep.get("stable")) and bool(club_rep.get("stable"))
    note = (
        f"官方交叉 有K {pub_ev.get('n_with_bar')}/缺 {pub_ev.get('n_missing_bar')}；"
        f"沒對到檔名的數字 {pub_ev.get('n_unbound')}；"
        f"本機佐證圖 {pub_ev.get('n_local_charts')}；"
        f"補月 {fetched.get('months') or 0}"
    )
    try:
        _persist(
            db_path,
            public_inv=pub_inv,
            public_ext=pub_ext,
            public_ev=pub_ev,
            club_inv=club_inv,
            stable=stable,
            fps=list(pub_rep.get("fingerprints") or []),
            note=note,
        )
    except Exception:
        logger.exception("三遍交叉寫庫失敗")
    angles: List[Dict[str, Any]] = []
    try:
        from biaoke_angles import (
            format_angles,
            load_angle_context,
            persist_angles,
            run_angles,
            summarize_angles,
        )

        ctx = load_angle_context(
            public,
            db_path=db_path,
            inventory=pub_inv,
            extract=pub_ext,
            evidence=pub_ev,
            stable=stable,
        )
        angles = run_angles(ctx)
        persist_angles(db_path, angles)
        ang_st = summarize_angles(angles)
        note = note + f"；一千角 {ang_st.get('passed')}/{ang_st.get('n')}"
    except Exception:
        logger.exception("一千角交叉失敗")
        ang_st = {"n": 0, "passed": 0, "failed": 0}
        ctx = {"today_reps": []}
    out = {
        "stable": stable,
        "fingerprints": list(pub_rep.get("fingerprints") or []),
        "public": {
            "inventory": {
                k: pub_inv.get(k)
                for k in (
                    "fingerprint",
                    "n_posts",
                    "n_replies",
                    "n_chars",
                    "n_charts",
                    "n_mentions",
                    "n_numbers",
                    "n_wave_posts",
                )
            },
            "extract": {
                k: pub_ext.get(k)
                for k in ("fingerprint", "n_claims", "n_levels", "n_examples", "n_waves")
            },
            "evidence": {
                k: pub_ev.get(k)
                for k in (
                    "n_with_bar",
                    "n_missing_bar",
                    "n_unbound",
                    "n_local_charts",
                    "n_chart_urls",
                )
            },
        },
        "club": {
            "n_posts": club_inv.get("n_posts") or 0,
            "n_replies": club_inv.get("n_replies") or 0,
            "n_claims": club_ext.get("n_claims") or 0,
            "n_with_bar": club_ev.get("n_with_bar") or 0,
            "n_missing_bar": club_ev.get("n_missing_bar") or 0,
        },
        "fetched": fetched,
        "n_gaps": len(pub_ev.get("gaps") or []),
        "angles": ang_st,
        "today_replies": len(ctx.get("today_reps") or []),
        "angle_text": format_angles(angles, today_replies=len(ctx.get("today_reps") or []))
        if angles
        else "",
    }
    logger.info(
        "飆大三遍交叉 stable=%s posts=%s claims=%s with_bar=%s missing=%s unbound=%s charts=%s local=%s",
        stable,
        pub_inv.get("n_posts"),
        pub_ext.get("n_claims"),
        pub_ev.get("n_with_bar"),
        pub_ev.get("n_missing_bar"),
        pub_ev.get("n_unbound"),
        pub_inv.get("n_charts"),
        pub_ev.get("n_local_charts"),
    )
    return out


def load_audit_runs(db_path: str) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_audit_runs'"
        ).fetchone()
        if not hit:
            return []
        rows = conn.execute(
            """
            SELECT pass_i, fingerprint, n_posts, n_replies, n_chars, n_charts,
                   n_mentions, n_numbers, n_claims, n_levels, n_with_bar,
                   n_missing_bar, n_unbound, n_local_charts, stable, note, updated_at
            FROM biaoke_audit_runs ORDER BY pass_i
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    keys = (
        "pass_i",
        "fingerprint",
        "n_posts",
        "n_replies",
        "n_chars",
        "n_charts",
        "n_mentions",
        "n_numbers",
        "n_claims",
        "n_levels",
        "n_with_bar",
        "n_missing_bar",
        "n_unbound",
        "n_local_charts",
        "stable",
        "note",
        "updated_at",
    )
    return [dict(zip(keys, r)) for r in rows]


def format_audit(db_path: str = "", *, result: Optional[Dict[str, Any]] = None) -> str:
    """給對話腦：三遍交叉摘要。沒跑過就現算（pytest 不補日 K）。"""
    data = result
    if data is None and db_path:
        runs = load_audit_runs(db_path)
        if runs:
            p1 = next((r for r in runs if r.get("pass_i") == 1), {})
            p2 = next((r for r in runs if r.get("pass_i") == 2), {})
            p3 = next((r for r in runs if r.get("pass_i") == 3), {})
            data = {
                "stable": bool(p1.get("stable")),
                "public": {
                    "inventory": p1,
                    "extract": p2,
                    "evidence": p3,
                },
                "club": {},
                "fetched": {},
            }
    if data is None:
        data = run_three_passes(db_path, fetch_missing=False)
    pub = data.get("public") or {}
    inv = pub.get("inventory") or {}
    ext = pub.get("extract") or {}
    ev = pub.get("evidence") or {}
    club = data.get("club") or {}
    stable = data.get("stable")
    lines = [
        "三遍交叉：原文盤點連跑 3 次"
        + ("，指紋全同。" if stable else "，指紋不一致，這次當失敗。"),
        (
            f"公開主文 {inv.get('n_posts') or 0}＋樓下 {inv.get('n_replies') or 0}，"
            f"全文 {inv.get('n_chars') or 0} 字，附圖網址 {inv.get('n_charts') or 0}。"
        ),
        (
            f"點名 {inv.get('n_mentions') or 0} 次、數字 {inv.get('n_numbers') or 0} 個；"
            f"規則抽出目標／支撐／波浪／例子 {ext.get('n_claims') or 0}，"
            f"大盤點位 {ext.get('n_levels') or 0}。"
        ),
        (
            f"有當日官方日 K {ev.get('n_with_bar') or 0}；"
            f"庫沒這天 {ev.get('n_missing_bar') or 0}（多半 2023–2024，已標缺不編）；"
            f"數字沒對到檔名 {ev.get('n_unbound') or 0} 則（沒檔名不編目標）。"
        ),
        (
            f"本機佐證圖 {ev.get('n_local_charts') or 0} 張（截圖／重畫水平線）。"
            "CMoney 附圖只建網址檔，不讀像素、不數 15 分 5／9 段。"
        ),
    ]
    if club.get("n_posts"):
        lines.append(
            f"社團 {club.get('n_posts')} 則只對價建檔，不進公開 overlay、不進話筒原文。"
        )
    fetched = data.get("fetched") or {}
    if fetched.get("months"):
        lines.append(
            f"這次補官方月 K {fetched.get('months')} 個月、{fetched.get('rows')} 根。"
        )
    ang_text = str(data.get("angle_text") or "")
    if not ang_text and db_path:
        try:
            from biaoke_angles import format_angles, load_angles

            arows = load_angles(db_path)
            if arows:
                ang_text = format_angles(
                    arows, today_replies=int(data.get("today_replies") or 0)
                )
        except Exception:
            ang_text = ""
    if ang_text:
        lines.insert(0, ang_text.split("\n")[0])
        for extra in ang_text.split("\n")[1:]:
            if extra and extra not in lines:
                lines.append(extra)
    lines.append("不是買訊。")
    # 去重最後的不是買訊
    seen_l = []
    for ln in lines:
        if ln == "不是買訊。" and ln in seen_l:
            continue
        seen_l.append(ln)
    return "\n".join(seen_l)


def format_audit_html(db_path: str = "") -> str:
    raw = format_audit(db_path)
    if not raw:
        return ""
    return "\n".join(html_escape(line) for line in raw.split("\n"))
