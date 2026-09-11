# -*- coding: utf-8 -*-
"""費半先行／1-4 重疊：只收他寫「重疊」的原句，對 Yahoo 費半日 K 與加權。

不編 15 分段數。不是買訊、不進海選。1-4 浪支撐≠1-4 重疊。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote

import requests

from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
SNAPSHOT_JSON = os.path.join(_DIR, "sox_14.json")
SNAPSHOT_MD = os.path.join(_DIR, "sox_14.md")

# 只收「重疊」。1-4 浪／114-114 會誤中，不准當重疊。
OVERLAP_RE = re.compile(
    r"(?:1\s*[\-－—]?\s*4|１\s*[\-－]?\s*４|一四|１４|14)\s*重疊"
)
SOX_RE = re.compile(r"(費半|費城半導體|(?<![A-Za-z])SOX(?![A-Za-z]))")
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

Bar = Tuple[str, float, float, float]  # ymd, high, low, close


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_overlap_text(text: str) -> bool:
    return bool(OVERLAP_RE.search(text or ""))


def is_sox_text(text: str) -> bool:
    return bool(SOX_RE.search(text or ""))


def claim_posts(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """主文＋自回。只留費半或『重疊』。"""
    out: List[Dict[str, Any]] = []
    for p in posts:
        text = str(p.get("text") or "")
        ov = is_overlap_text(text)
        sox = is_sox_text(text)
        if not ov and not sox:
            continue
        out.append(
            {
                "id": str(p.get("id") or ""),
                "date": str(p.get("date") or ""),
                "kind": str(p.get("kind") or "post"),
                "overlap": ov,
                "sox": sox,
                "snip": _plain(text)[:120],
            }
        )
    out.sort(key=lambda r: (r["date"], r["id"]))
    return out


def fetch_sox_daily(*, range_: str = "5y") -> List[Bar]:
    """Yahoo ^SOX 日 K。研究對表用，不寫進海選、不寫進行情庫。"""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote('^SOX', safe='')}?interval=1d&range={range_}"
    )
    resp = requests.get(url, headers=_UA, timeout=30)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    out: List[Bar] = []
    for ts, h, lo, c in zip(stamps, highs, lows, closes):
        if h is None or lo is None or c is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y%m%d")
        out.append((day, float(h), float(lo), float(c)))
    out.sort(key=lambda r: r[0])
    return out


def load_twii(db_path: str) -> List[Bar]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        rows = conn.execute(
            "SELECT date, high, low, close FROM index_daily WHERE symbol='TWII' ORDER BY date"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    out: List[Bar] = []
    for d, h, lo, c in rows:
        y = _ymd(d)
        try:
            out.append((y, float(h), float(lo), float(c)))
        except (TypeError, ValueError):
            continue
    return out


def _days_apart(a: str, b: str) -> int:
    try:
        da = datetime.strptime(_ymd(a), "%Y%m%d")
        db = datetime.strptime(_ymd(b), "%Y%m%d")
    except ValueError:
        return 9999
    return abs((da - db).days)


def _idx_on_or_after(series: Sequence[Bar], day: str) -> Optional[int]:
    d = _ymd(day)
    if not d:
        return None
    for i, row in enumerate(series):
        if row[0] >= d:
            if _days_apart(row[0], d) > 10:
                return None
            return i
    return None


def follow_low(
    series: Sequence[Bar], day: str, *, n: int = 20
) -> Dict[str, Any]:
    """發文日那根低點，後 n 根有沒有再破（0.5% 緩衝）。缺 K 就空。"""
    i = _idx_on_or_after(series, day)
    empty = {
        "date": "",
        "low": None,
        "close": None,
        "n": 0,
        "broke": None,
        "min_low": None,
        "ret": None,
    }
    if i is None:
        return empty
    win = list(series[i : i + n + 1])
    if not win:
        return empty
    low0 = win[0][2]
    later = win[1:]
    min_low = min(r[2] for r in later) if later else None
    ret = None
    if len(win) >= n + 1 and win[0][3] > 0:
        ret = round((win[n][3] / win[0][3] - 1.0) * 100.0, 2)
    broke = None
    if min_low is not None and low0:
        broke = bool(min_low < low0 * 0.995)
    return {
        "date": win[0][0],
        "low": round(float(win[0][2]), 2),
        "close": round(float(win[0][3]), 2),
        "n": len(later),
        "broke": broke,
        "min_low": round(float(min_low), 2) if min_low is not None else None,
        "ret": ret,
    }


def score_event(claim: Dict[str, Any], sox: Sequence[Bar], twii: Sequence[Bar]) -> Dict[str, Any]:
    day = claim.get("date") or ""
    row = dict(claim)
    row["sox20"] = follow_low(sox, day, n=20)
    row["sox60"] = follow_low(sox, day, n=60)
    row["twii20"] = follow_low(twii, day, n=20)
    row["twii60"] = follow_low(twii, day, n=60)
    return row


def summarize_sox(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ov = [e for e in events if e.get("overlap")]
    sox_talk = [e for e in events if e.get("sox")]

    def _hold_rate(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
        bits = [r.get(key) or {} for r in rows]
        known = [b for b in bits if b.get("broke") is not None]
        if not known:
            return {"n": 0, "hold": None, "mean_ret": None}
        hold = sum(1 for b in known if b.get("broke") is False)
        rets = [float(b["ret"]) for b in known if b.get("ret") is not None]
        return {
            "n": len(known),
            "hold": round(100.0 * hold / len(known), 1),
            "mean_ret": round(sum(rets) / len(rets), 2) if rets else None,
        }

    return {
        "n_events": len(events),
        "n_overlap": len(ov),
        "n_sox": len(sox_talk),
        "overlap_twii20": _hold_rate(ov, "twii20"),
        "overlap_sox20": _hold_rate(ov, "sox20"),
        "sox_twii20": _hold_rate(sox_talk, "twii20"),
        "sox_sox20": _hold_rate(sox_talk, "sox20"),
        "events": events,
        "not_buy": True,
        "not_screen": True,
    }


def run_sox_14(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    sox_bars: Optional[Sequence[Bar]] = None,
) -> Dict[str, Any]:
    claims = claim_posts(posts)
    sox = list(sox_bars) if sox_bars is not None else fetch_sox_daily()
    twii = load_twii(db_path)
    scored = [score_event(c, sox, twii) for c in claims]
    snap = summarize_sox(scored)
    snap["sox_from"] = sox[0][0] if sox else ""
    snap["sox_to"] = sox[-1][0] if sox else ""
    snap["twii_from"] = twii[0][0] if twii else ""
    snap["twii_to"] = twii[-1][0] if twii else ""
    return snap


def save_sox_snapshot(snap: Dict[str, Any], *, dest_json: str = "", dest_md: str = "") -> None:
    dest_json = dest_json or SNAPSHOT_JSON
    dest_md = dest_md or SNAPSHOT_MD
    os.makedirs(os.path.dirname(dest_json), exist_ok=True)
    slim = dict(snap)
    # 明細只留重疊＋費半主文，避免整包過長
    slim["events"] = [
        e
        for e in (snap.get("events") or [])
        if e.get("overlap") or (e.get("sox") and (e.get("kind") or "post") != "reply")
    ]
    tmp = dest_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, dest_json)
    with open(dest_md, "w", encoding="utf-8") as fh:
        fh.write(render_sox_md(slim))


def load_sox_snapshot(*, path: str = "") -> Dict[str, Any]:
    p = path or SNAPSHOT_JSON
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _fmt_follow(title: str, row: Any) -> str:
    row = row or {}
    if not row.get("n"):
        return f"{title}：沒有夠長的日 K"
    broke = row.get("broke")
    flag = "後續再破低" if broke else ("後續沒再破低" if broke is False else "不明")
    ret = row.get("ret")
    ret_s = f"，{row.get('n')} 根後 {ret}%" if ret is not None else ""
    return f"{title}：當根低 {row.get('low')} {flag}{ret_s}"


def render_sox_md(snap: Dict[str, Any]) -> str:
    ov20 = snap.get("overlap_twii20") or {}
    sox20 = snap.get("overlap_sox20") or {}
    lines = [
        "# 費半先行／1-4 重疊對表",
        "",
        "只收原文「重疊」。**1-4 浪支撐不是 1-4 重疊。** 費半日 K 來自 Yahoo `^SOX`（對表用，不進海選）。",
        "沒有費半 15 分就不數段，只看發文日後 20 根有沒有再破當根低。不是買訊。",
        "",
        f"- 費半日 K：{snap.get('sox_from')}～{snap.get('sox_to')}",
        f"- 加權日 K：{snap.get('twii_from')}～{snap.get('twii_to')}",
        f"- 重疊原句 {snap.get('n_overlap')} 則；講費半 {snap.get('n_sox')} 則",
        f"- 重疊後加權 20 根沒再破低：{ov20.get('hold')}%（n={ov20.get('n')}），平均 {ov20.get('mean_ret')}%",
        f"- 重疊後費半 20 根沒再破低：{sox20.get('hold')}%（n={sox20.get('n')}），平均 {sox20.get('mean_ret')}%",
        "",
        "## 重疊原句",
        "",
    ]
    for e in snap.get("events") or []:
        if not e.get("overlap"):
            continue
        lines.append(f"### {e.get('date')} {'費半' if e.get('sox') else ''}".rstrip())
        lines.append("")
        lines.append(_plain(e.get("snip") or ""))
        lines.append("")
        lines.append("- " + _fmt_follow("費半", e.get("sox20")))
        lines.append("- " + _fmt_follow("加權", e.get("twii20")))
        lines.append("")
    lines.extend(["## 他講費半、當先行的主文（節錄）", ""])
    for e in snap.get("events") or []:
        if e.get("overlap") or not e.get("sox"):
            continue
        if (e.get("kind") or "post") == "reply":
            continue
        tag = "再破低" if (e.get("twii20") or {}).get("broke") is True else (
            "沒再破低" if (e.get("twii20") or {}).get("broke") is False else "缺日K"
        )
        lines.append(
            f"- {e.get('date')} 加權20根 {((e.get('twii20') or {}).get('ret'))}% "
            f"{tag}：{_plain(e.get('snip') or '')[:80]}"
        )
    lines.extend(["", "這份表不是買賣清單，也不進海選。", ""])
    return "\n".join(lines) + "\n"


def format_sox_html(snap: Optional[Dict[str, Any]] = None) -> str:
    data = snap if snap is not None else load_sox_snapshot()
    if not data:
        return (
            "1-4 重疊＝下跌趨勢化解。費半若出現，他當台股先行。"
            "沒費半 15 分就不數段，只看收盤還破不破低。不是買訊、不進海選。"
        )
    ov = data.get("overlap_twii20") or {}
    sx = data.get("overlap_sox20") or {}
    lines = [
        "1-4 重疊只收他寫「重疊」的原句，不是 1-4 浪支撐。",
        f"重疊後 20 根：加權沒再破低 {ov.get('hold')}%（n={ov.get('n')}，平均 {ov.get('mean_ret')}%）；"
        f"費半沒再破低 {sx.get('hold')}%（n={sx.get('n')}，平均 {sx.get('mean_ret')}%）。"
        "日 K 代理偏弱，他真正看的是 15／60 分；日線重疊不能當低點保證。",
        "2026-06-15 他說費半 1-4 重疊＝下跌趨勢化解、台股跟隨；6/16 說幾乎不會再測 42000，"
        "7/29 加權低 39385，這條「不再測」後來錯。重疊≠低點保證。",
        "沒有費半 15 分就不數段。不是買訊、不進海選。",
    ]
    return html_escape(" ".join(lines))


def is_sox_query(ask: str) -> bool:
    q = ask or ""
    return bool(
        OVERLAP_RE.search(q)
        or re.search(r"(費半|費城半導體|(?<![A-Za-z])SOX(?![A-Za-z])|台股先行)", q)
    )
