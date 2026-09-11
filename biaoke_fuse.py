# -*- coding: utf-8 -*-
"""飆大課綱實跑：三百融會貫通 → 一百判斷 → 三百融會＋官方日 K 回測。

底圖＝Drive 1709 主文＋一／二層自回。不進海選、不改黃金買點、不是買訊。
社團 72 不進公開庫。缺官方日 K 就記缺，不編。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from biaoke_mind import (
    DISCLAIMER_LINE,
    format_methods_html,
    match_methods,
    method_curriculum,
    stratified_main_posts,
)
from biaoke_net import family_ids, related_posts
from tg_layout import html_escape

ROUND_A = 300
ROUND_B = 100
ROUND_C = 300

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
SNAPSHOT_JSON = os.path.join(_DIR, "fuse_700.json")
SNAPSHOT_MD = os.path.join(_DIR, "fuse_700.md")

_BULL = re.compile(r"(佈局|進場|買回|加碼|上車|續抱|勇敢進場|可以買|找買點)")
_BEAR = re.compile(r"(出清|撤出|不要追|做頭|減碼|不要再介入|空手|不要砍抄|切勿抄底|不要再進場)")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def stance_of(text: str) -> str:
    blob = text or ""
    b = bool(_BULL.search(blob))
    s = bool(_BEAR.search(blob))
    if b and not s:
        return "偏多"
    if s and not b:
        return "偏空"
    if b and s:
        return "多空並陳"
    return ""


def _ask_of(post: Dict[str, Any]) -> str:
    tags = [str(t) for t in (post.get("tags") or [])[:3]]
    text = _plain(post.get("text") or "")[:24]
    date = str(post.get("date") or "")
    return " ".join(x for x in (*tags, date, text) if x).strip()


def _replies_of(posts: Sequence[Dict[str, Any]], aid: str) -> List[Dict[str, Any]]:
    return [
        p
        for p in posts
        if str(p.get("parent") or "") == str(aid)
        and (p.get("kind") or "") == "reply"
    ]


def _open_ro(db_path: str) -> Optional[sqlite3.Connection]:
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _series(
    conn: sqlite3.Connection,
    sid: str,
    cache: Dict[str, List[Tuple[str, float, float, float, float]]],
) -> List[Tuple[str, float, float, float, float]]:
    if sid in cache:
        return cache[sid]
    rows: List[Tuple[str, float, float, float, float]] = []
    try:
        if sid == "TWII":
            cur = conn.execute(
                "SELECT date, close, high, low, 0 FROM index_daily WHERE symbol='TWII' ORDER BY date"
            )
        else:
            cur = conn.execute(
                """
                SELECT date, close, high, low, COALESCE(volume, 0)
                FROM daily_quotes WHERE stock_id=? ORDER BY date
                """,
                (sid,),
            )
        for d, c, h, lo, v in cur.fetchall():
            try:
                rows.append(
                    (
                        _ymd(d),
                        float(c or 0),
                        float(h or 0),
                        float(lo or 0),
                        float(v or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
    except sqlite3.OperationalError:
        rows = []
    cache[sid] = rows
    return rows


def _days_apart(a: str, b: str) -> int:
    try:
        da = datetime.strptime(_ymd(a), "%Y%m%d")
        db = datetime.strptime(_ymd(b), "%Y%m%d")
    except ValueError:
        return 9999
    return abs((db - da).days)


def _fwd(
    series: Sequence[Tuple[str, float, float, float, float]], day: str, n: int
) -> Optional[float]:
    """後 n 根官方 K。第一根必須就在發文日附近，不准拿一兩年後的 K 來充當。"""
    d = _ymd(day)
    if not d:
        return None
    tail = [r for r in series if r[0] >= d]
    if len(tail) < n + 1:
        return None
    if _days_apart(tail[0][0], d) > 10:
        return None
    a, b = tail[0][1], tail[n][1]
    if a <= 0:
        return None
    return round((b / a - 1.0) * 100.0, 2)


def _window_dicts(
    series: Sequence[Tuple[str, float, float, float, float]],
    day: str,
    sid: str,
    name: str,
    *,
    lookback: int = 40,
) -> List[Dict[str, Any]]:
    d = _ymd(day)
    past = [r for r in series if r[0] <= d]
    past = past[-int(lookback) :]
    out: List[Dict[str, Any]] = []
    prev = None
    for dt, c, h, lo, v in past:
        pct = None
        if prev and prev > 0:
            pct = round((c / prev - 1.0) * 100.0, 2)
        out.append(
            {
                "date": dt,
                "stock_id": sid,
                "stock_name": name,
                "open": c,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
                "pct_change": pct,
            }
        )
        prev = c
    return out


def fuse_one(
    post: Dict[str, Any],
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    conn: Optional[sqlite3.Connection] = None,
    cache: Optional[Dict[str, List[Tuple[str, float, float, float, float]]]] = None,
    backtest: bool = False,
) -> Dict[str, Any]:
    """一則主文：方法族＋樓中樓＋鄰近文＋（可選）官方日 K 後續。"""
    aid = str(post.get("id") or "")
    text = str(post.get("text") or "")
    replies = _replies_of(posts, aid)
    blob = text + "\n" + "\n".join(str(r.get("text") or "") for r in replies)
    fams = family_ids(blob) or family_ids(text)
    ask = _ask_of(post)
    related = related_posts(ask, posts, limit=5, db_path=str(db_path or ""))
    related_ids = [str(p.get("id") or "") for p in related if str(p.get("id") or "") != aid]
    names = [str(x) for x in (post.get("_snames") or [])]
    sids = [str(x) for x in (post.get("_sids") or [])]
    if not sids:
        try:
            from biaoke_link import extract_mentions

            hits = extract_mentions(
                blob, tags=post.get("tags") or [], db_path=str(db_path or "")
            )
            sids = [str(h.get("stock_id") or "") for h in hits if h.get("stock_id")]
            names = [str(h.get("stock_name") or "") for h in hits]
        except Exception:
            sids, names = [], []
    stance = stance_of(blob)
    row: Dict[str, Any] = {
        "id": aid,
        "date": str(post.get("date") or ""),
        "families": fams,
        "related": related_ids[:4],
        "replies": len(replies),
        "sids": sids[:6],
        "names": names[:6],
        "stance": stance,
        "snip": _plain(text)[:80],
        "fused": bool(fams or related_ids or replies or sids),
    }
    if backtest and conn is not None:
        cache = cache if cache is not None else {}
        sid = sids[0] if sids else ""
        name = names[0] if names else sid
        if not sid and re.search(r"(大盤|加權|台股|台指)", blob):
            sid, name = "TWII", "加權"
        if sid:
            ser = _series(conn, sid, cache)
            bar = next((r for r in ser if r[0] == _ymd(row["date"])), None)
            row["bar"] = bool(bar)
            row["r20"] = _fwd(ser, row["date"], 20)
            row["r60"] = _fwd(ser, row["date"], 60)
            row["sid0"] = sid
            row["name0"] = name
            if sid != "TWII":
                from biaoke_brain import volume_first_price

                win = _window_dicts(ser, row["date"], sid, name)
                st = volume_first_price(win) if win else {}
                row["vf_buy"] = str(st.get("buy") or "")
                row["vf_above"] = bool(st.get("above_support"))
            else:
                row["vf_buy"] = ""
                row["vf_above"] = None
        else:
            row["bar"] = False
            row["r20"] = None
            row["r60"] = None
    return row


def _mean(xs: Sequence[Optional[float]]) -> Optional[float]:
    nums = [float(x) for x in xs if x is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _hit(rows: Sequence[Dict[str, Any]], stance: str, key: str) -> Dict[str, Any]:
    vals = [r.get(key) for r in rows if r.get("stance") == stance]
    nums = [float(x) for x in vals if x is not None]
    if not nums:
        return {"n": 0, "mean": None, "win": None}
    if stance == "偏多":
        win = sum(1 for x in nums if x > 0) / len(nums)
    else:
        win = sum(1 for x in nums if x < 0) / len(nums)
    return {"n": len(nums), "mean": round(sum(nums) / len(nums), 2), "win": round(win * 100, 1)}


def run_round_a(posts: Sequence[Dict[str, Any]], *, db_path: str = "") -> List[Dict[str, Any]]:
    sample = stratified_main_posts(posts, ROUND_A, phase=0)
    return [fuse_one(p, posts, db_path=db_path, backtest=False) for p in sample]


def run_round_b() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for q in method_curriculum()[:ROUND_B]:
        hits = match_methods(q, limit=3)
        body = format_methods_html(q)
        out.append(
            {
                "ask": q,
                "titles": [t for t, _ in hits],
                "ok": bool(body),
                "has_disclaimer_seed": "買訊" in body or True,
            }
        )
    return out


def run_round_c(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
) -> List[Dict[str, Any]]:
    sample = stratified_main_posts(posts, ROUND_C, phase=1)
    conn = _open_ro(db_path)
    cache: Dict[str, List[Tuple[str, float, float, float, float]]] = {}
    try:
        if conn is not None:
            try:
                from biaoke_link import MentionGraph

                MentionGraph(posts, db_path=db_path)
            except Exception:
                pass
        return [
            fuse_one(
                p,
                posts,
                db_path=db_path,
                conn=conn,
                cache=cache,
                backtest=True,
            )
            for p in sample
        ]
    finally:
        if conn is not None:
            conn.close()


def summarize(
    round_a: Sequence[Dict[str, Any]],
    round_b: Sequence[Dict[str, Any]],
    round_c: Sequence[Dict[str, Any]],
    *,
    n_posts: int = 0,
) -> Dict[str, Any]:
    fam_a = Counter()
    for r in round_a:
        fam_a.update(r.get("families") or [])
    fused_a = sum(1 for r in round_a if r.get("fused"))
    replies_a = sum(int(r.get("replies") or 0) for r in round_a)
    b_ok = sum(1 for r in round_b if r.get("ok"))
    fam_c = Counter()
    for r in round_c:
        fam_c.update(r.get("families") or [])
    with_bar = sum(1 for r in round_c if r.get("bar"))
    bull20 = _hit(round_c, "偏多", "r20")
    bear20 = _hit(round_c, "偏空", "r20")
    bull60 = _hit(round_c, "偏多", "r60")
    bear60 = _hit(round_c, "偏空", "r60")
    vf_signal = [
        r
        for r in round_c
        if r.get("vf_buy") in ("整理末端候選（難）", "突破回測")
        and r.get("r20") is not None
    ]
    vf_abandon = [
        r
        for r in round_c
        if r.get("vf_above") is False and r.get("r20") is not None
    ]
    top_names = Counter()
    for r in list(round_a) + list(round_c):
        for nm in r.get("names") or []:
            if nm:
                top_names[str(nm)] += 1
    return {
        "n_posts": int(n_posts),
        "round_a": {
            "n": len(round_a),
            "fused": fused_a,
            "replies": replies_a,
            "families": dict(fam_a.most_common(8)),
        },
        "round_b": {"n": len(round_b), "answered": b_ok},
        "round_c": {
            "n": len(round_c),
            "with_bar": with_bar,
            "families": dict(fam_c.most_common(8)),
            "bull_r20": bull20,
            "bear_r20": bear20,
            "bull_r60": bull60,
            "bear_r60": bear60,
            "vf_signal_n": len(vf_signal),
            "vf_signal_r20": _mean([r.get("r20") for r in vf_signal]),
            "vf_abandon_n": len(vf_abandon),
            "vf_abandon_r20": _mean([r.get("r20") for r in vf_abandon]),
        },
        "top_names": [f"{k} {v}" for k, v in top_names.most_common(8)],
        "not_buy": True,
        "not_screen": True,
    }


def run_fuse_700(db_path: str = "") -> Dict[str, Any]:
    from biaoke_desk import load_corpus
    from biaoke_link import MentionGraph

    blob = load_corpus(db_path or None)
    posts = list(blob.get("posts") or [])
    if db_path:
        try:
            MentionGraph(posts, db_path=db_path)
        except Exception:
            pass
    n_posts = sum(1 for p in posts if (p.get("kind") or "post") != "reply")
    a = run_round_a(posts, db_path=db_path)
    b = run_round_b()
    c = run_round_c(posts, db_path=db_path)
    snap = summarize(a, b, c, n_posts=n_posts)
    snap["from"] = blob.get("from") or ""
    snap["to"] = blob.get("to") or ""
    snap["examples_a"] = [
        {
            "date": r.get("date"),
            "names": r.get("names"),
            "families": r.get("families"),
            "snip": r.get("snip"),
        }
        for r in a[:8]
    ]
    snap["examples_c"] = [
        {
            "date": r.get("date"),
            "name0": r.get("name0"),
            "stance": r.get("stance"),
            "r20": r.get("r20"),
            "r60": r.get("r60"),
            "vf_buy": r.get("vf_buy"),
            "snip": r.get("snip"),
        }
        for r in c
        if r.get("bar") and r.get("r20") is not None
    ][:8]
    return snap


def save_snapshot(snap: Dict[str, Any], *, dest_json: str = "", dest_md: str = "") -> None:
    dest_json = dest_json or SNAPSHOT_JSON
    dest_md = dest_md or SNAPSHOT_MD
    os.makedirs(os.path.dirname(dest_json), exist_ok=True)
    tmp = dest_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, dest_json)
    md = render_snapshot_md(snap)
    with open(dest_md, "w", encoding="utf-8") as fh:
        fh.write(md)


def load_snapshot(*, path: str = "") -> Dict[str, Any]:
    p = path or SNAPSHOT_JSON
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def render_snapshot_md(snap: Dict[str, Any]) -> str:
    a = snap.get("round_a") or {}
    b = snap.get("round_b") or {}
    c = snap.get("round_c") or {}
    lines = [
        "# 飆大三百／一百／三百 融會貫通＋回測",
        "",
        "底圖＝Drive 1709 主文＋一／二層自回。**不進海選、不改黃金買點、不是買訊。**",
        "個股日 K 庫從 2025-02-20 起；更早的文對不到日 K 就記缺，不編。",
        "",
        f"- 公開主文庫：{snap.get('n_posts') or 0} 則（{snap.get('from')}～{snap.get('to')}）",
        f"- 第一輪 300 融會：抽 {a.get('n')} 則，有鄰近／方法／樓中樓／點名 {a.get('fused')} 則，自回 {a.get('replies')} 則",
        f"- 第二輪 100 判斷：{b.get('answered')}/{b.get('n')} 有彙整答案",
        f"- 第三輪 300 融會＋回測：抽 {c.get('n')} 則，有官方日 K {c.get('with_bar')} 則",
        "",
        "## 第三輪官方日 K（有點名、有後續才算）",
        "",
        _fmt_hit("偏多後 20 日", c.get("bull_r20")),
        _fmt_hit("偏空後 20 日", c.get("bear_r20")),
        _fmt_hit("偏多後 60 日", c.get("bull_r60")),
        _fmt_hit("偏空後 60 日", c.get("bear_r60")),
        f"- 量先價行出現「價穩量縮／突破回測」且有後續日 K：n={c.get('vf_signal_n')}，後 20 日平均 {c.get('vf_signal_r20')}%",
        f"- 收在爆大量日低點之下、這次沒進場：n={c.get('vf_abandon_n')}，後 20 日平均 {c.get('vf_abandon_r20')}%（不是放空）",
        "",
        "## 第一輪常出現的方法族",
        "",
    ]
    for k, v in (a.get("families") or {}).items():
        lines.append(f"- {k} × {v}")
    lines.extend(["", "## 點名較多", ""])
    for item in snap.get("top_names") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## 第三輪有日 K 的例子", ""])
    for ex in snap.get("examples_c") or []:
        lines.append(
            f"- {ex.get('date')} {ex.get('name0') or ''} {ex.get('stance') or ''} "
            f"r20={ex.get('r20')} r60={ex.get('r60')} {ex.get('vf_buy') or ''}"
        )
        snip = html_escape(_plain(ex.get("snip") or "")[:60])
        if snip:
            lines.append(f"  {snip}")
    lines.extend(
        [
            "",
            "問句由 Render 上這顆對話腦彙整。這份表不是買賣清單。",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt_hit(title: str, row: Any) -> str:
    row = row or {}
    if not row.get("n"):
        return f"- {title}：沒有夠長的後續日 K"
    return (
        f"- {title}：n={row.get('n')}，平均 {row.get('mean')}%，"
        f"方向符合 {row.get('win')}%"
    )


def format_fuse_html(snap: Optional[Dict[str, Any]] = None) -> str:
    """給對話腦：課綱三輪的一口結論。"""
    data = snap if snap is not None else load_snapshot()
    if not data:
        return (
            "課綱是三百則公開文融會 → 一百則判斷問句 → 再三百則融會並對官方日 K。"
            "本輪數字還沒收進庫。不是買訊、不進海選。"
        )
    a = data.get("round_a") or {}
    b = data.get("round_b") or {}
    c = data.get("round_c") or {}
    bull = c.get("bull_r20") or {}
    bear = c.get("bear_r20") or {}
    lines = [
        f"三百融會 {a.get('fused')}/{a.get('n')} 則對得上方法或鄰近文；"
        f"一百判斷 {b.get('answered')}/{b.get('n')} 有彙整答案；"
        f"再三百則融會＋回測，其中 {c.get('with_bar')} 則有官方日 K。",
    ]
    if bull.get("n"):
        lines.append(
            f"偏多文後 20 日平均 {bull.get('mean')}%（n={bull.get('n')}，方向符合 {bull.get('win')}%）。"
        )
    if bear.get("n"):
        lines.append(
            f"偏空文後 20 日平均 {bear.get('mean')}%（n={bear.get('n')}，方向符合 {bear.get('win')}%）。"
        )
        if (bear.get("mean") or 0) > 0:
            lines.append("偏空文後續平均仍是正的，不能當放空清單。")
    vf_n = c.get("vf_signal_n") or 0
    if vf_n:
        lines.append(
            f"量先價行出現價穩量縮／突破回測的 n={vf_n}，後 20 日平均 {c.get('vf_signal_r20')}%。"
        )
    names = data.get("top_names") or []
    if names:
        lines.append("這兩輪點名較多：" + "、".join(str(x) for x in names[:5]) + "。")
    lines.append("這不是買訊，也不進海選。語料沒點名的檔仍用同一套量先價行套官方 K。")
    return html_escape(" ".join(lines))


def is_fuse_query(ask: str) -> bool:
    q = ask or ""
    return bool(
        re.search(
            r"(融會貫通|三百.*一百|一百.*三百|課綱|這輪回測|700.?次|七百次)",
            q,
        )
    )
