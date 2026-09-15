# -*- coding: utf-8 -*-
"""五件工具回測：波浪／形態／量價／關鍵K（碎形）對官方柱。

不是關鍵字偏多偏空。個股不數 5／9。缺官方就記缺。不進海選、不是買訊。
最後官方收以庫為準。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
SNAPSHOT_JSON = os.path.join(_DIR, "five_bt.json")
SNAPSHOT_MD = os.path.join(_DIR, "five_bt.md")

_WAVE = re.compile(
    r"(細微波|C-2|C-3|C-1|右肩|位階|頭肩底|築底|下降壓|下降軌|"
    r"1-4\s*重疊|逃命波|修正末端|波浪|不可能破|難破|大盤.{0,16}不破)"
)
_MORPH = re.compile(r"(平台|頸線|下飄旗|破線|假跌破|頭肩|整理末端|突破回測|跌破)")
_VOL = re.compile(r"(爆大量|量先價行|籌碼交換|先看量|量縮|量價結構|裸K)")
_KEYK = re.compile(r"(轉折K|止漲整理K|關鍵K|碎形|轉折K棒|關鍵k棒)")
_SUPPORT = re.compile(r"(不破|沒破|守住|有守|築底|支撐|難破|不可能破)")
_TARGET = re.compile(r"(穿越|至少要|至少|測|過前|穿刺)")
_NUM = re.compile(r"(?<![\d.])(\d{4,5})(?:\.\d+)?(?![\d])")
_YMD = re.compile(r"^\d{8}$")
_SKIP_SID = frozenset({"TWII", "TX", "TXN", "^TWII"})
_INDEX_LV = frozenset(
    {
        "43500",
        "45415",
        "45839",
        "46250",
        "46506",
        "46767",
        "47578",
        "48218",
        "40000",
        "42000",
        "39385",
        "39384",
    }
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if _YMD.match(t) else ""


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return _plain(raw)


def _tools(text: str) -> List[str]:
    hit: List[str] = []
    if _WAVE.search(text):
        hit.append("wave")
    if _MORPH.search(text):
        hit.append("morph")
    if _VOL.search(text):
        hit.append("vol")
    if _KEYK.search(text):
        hit.append("keyk")
    return hit


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
            y = _ymd(d)
            if not y:
                continue
            try:
                rows.append((y, float(c or 0), float(h or 0), float(lo or 0), float(v or 0)))
            except (TypeError, ValueError):
                continue
    except sqlite3.OperationalError:
        rows = []
    cache[sid] = rows
    return rows


def _after(
    series: Sequence[Tuple[str, float, float, float, float]], day: str
) -> List[Tuple[str, float, float, float, float]]:
    d = _ymd(day)
    return [r for r in series if r[0] >= d]


def _on_or_before(
    series: Sequence[Tuple[str, float, float, float, float]], day: str
) -> Optional[Tuple[str, float, float, float, float]]:
    d = _ymd(day)
    past = [r for r in series if r[0] <= d]
    return past[-1] if past else None


def _days_apart(a: str, b: str) -> int:
    try:
        from datetime import datetime

        da = datetime.strptime(_ymd(a), "%Y%m%d")
        db = datetime.strptime(_ymd(b), "%Y%m%d")
    except ValueError:
        return 9999
    return abs((db - da).days)


def _fwd(
    series: Sequence[Tuple[str, float, float, float, float]], day: str, n: int
) -> Optional[float]:
    d = _ymd(day)
    tail = _after(series, d)
    if len(tail) < n + 1:
        return None
    if _days_apart(tail[0][0], d) > 10:
        return None
    a, b = tail[0][1], tail[n][1]
    if a <= 0:
        return None
    return round((b / a - 1.0) * 100.0, 2)


def _aligned(
    series: Sequence[Tuple[str, float, float, float, float]], day: str
) -> bool:
    bar = _on_or_before(series, day)
    if not bar:
        return False
    return _days_apart(bar[0], day) <= 10


def _levels(text: str, mentioned: Sequence[str], twii_close: float, day: str) -> List[float]:
    named = {float(x) for x in _INDEX_LV if x.isdigit()}
    out: List[float] = []
    for m in _NUM.finditer(text):
        raw = m.group(1)
        if raw in mentioned:
            continue
        try:
            n = float(raw)
        except ValueError:
            continue
        ctx = text[max(0, m.start() - 18) : m.end() + 8]
        if not re.search(r"(大盤|加權|夜盤|台指|指數|C-2|C-3|右肩|不破|穿越)", ctx):
            if n not in named:
                continue
        if twii_close > 0 and (n > twii_close * 1.35 or n < twii_close * 0.65):
            if not (n in named and _ymd(day) >= "20260601"):
                continue
        if n in named or 18000 <= n <= 49000:
            out.append(n)
    seen = set()
    uniq: List[float] = []
    for n in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq[:6]


def _verdict_wave(
    series: Sequence[Tuple[str, float, float, float, float]],
    day: str,
    px: float,
    text: str,
) -> Dict[str, Any]:
    tail = _after(series, day)
    win = tail[:20]
    if len(win) < 8:
        return {"ok": None, "note": "後續加權不夠 8 根"}
    lo = min(r[3] for r in win)
    hi = max(r[2] for r in win)
    if _SUPPORT.search(text):
        hit = lo >= px * 0.995
        return {
            "ok": hit,
            "note": f"後20日最低 {lo:.0f} vs 不破 {px:.0f}",
        }
    if _TARGET.search(text):
        hit = hi >= px * 0.995
        return {
            "ok": hit,
            "note": f"後20日最高 {hi:.0f} vs 水平 {px:.0f}",
        }
    return {"ok": None, "note": "水平沒判方向"}


def _verdict_morph(
    series: Sequence[Tuple[str, float, float, float, float]], day: str, text: str
) -> Dict[str, Any]:
    if not _aligned(series, day):
        return {"ok": None, "note": "發文日附近沒官方柱"}
    bar = _on_or_before(series, day)
    if not bar:
        return {"ok": None, "note": "沒官方柱"}
    tail = [r for r in _after(series, day) if r[0] > bar[0]]
    if len(tail) < 3:
        return {"ok": None, "note": "後續不夠 3 根，還沒走完"}
    ev_h, ev_l, ev_c = bar[2], bar[3], bar[1]
    d3 = tail[:3]
    reclaim = any(r[1] > ev_h for r in d3)
    d10 = tail[:10]
    still_soft = bool(d10) and max(r[2] for r in d10) <= ev_h * 1.01 and d10[-1][1] < ev_c
    if "假跌破" in text:
        return {
            "ok": reclaim,
            "note": "3 日內收過當日高＝假跌破對上" if reclaim else "3 日內沒收過當日高",
        }
    if re.search(r"(跌破平台|破線|跌破頸線|跌破支撐)", text):
        if reclaim:
            return {"ok": False, "note": "說破了但 3 日內收過當日高，比較像假跌破"}
        if len(d10) < 8:
            return {"ok": None, "note": "破線後還沒走完 10 根"}
        return {
            "ok": still_soft,
            "note": "10 日仍弱於當日高" if still_soft else "10 日內又過當日高",
        }
    return {"ok": None, "note": "形態句沒有可對的破／假跌破"}


def _verdict_vol(
    series: Sequence[Tuple[str, float, float, float, float]], day: str
) -> Dict[str, Any]:
    d = _ymd(day)
    if not _aligned(series, day):
        return {"ok": None, "note": "發文日附近沒官方柱"}
    past = [r for r in series if r[0] <= d][-20:]
    if len(past) < 8:
        return {"ok": None, "note": "量價窗不夠"}
    spike = max(past, key=lambda r: r[4])
    if spike[4] <= 0:
        return {"ok": None, "note": "沒量"}
    after = [r for r in series if r[0] > spike[0]][:12]
    if len(after) < 5:
        return {"ok": None, "note": "爆量後不夠 5 根"}
    shrink = [r for r in after if r[4] < 0.65 * spike[4] and r[1] >= spike[3]]
    r20 = _fwd(series, spike[0], 20)
    if r20 is None:
        return {"ok": None, "note": "後 20 根還沒齊", "r20": None}
    held = bool(shrink)
    if not held:
        return {
            "ok": None,
            "note": f"爆量日 {spike[0]} 後還沒量縮站撐，這條不計",
            "r20": r20,
            "held": False,
        }
    return {
        "ok": r20 >= 0,
        "note": f"爆量日 {spike[0]} 量縮站撐後20日 {r20}%",
        "r20": r20,
        "held": True,
    }


def _verdict_keyk(
    series: Sequence[Tuple[str, float, float, float, float]], day: str, text: str
) -> Dict[str, Any]:
    if not _aligned(series, day):
        return {"ok": None, "note": "發文日附近沒官方柱"}
    bar = _on_or_before(series, day)
    if not bar:
        return {"ok": None, "note": "沒官方柱"}
    tail = [r for r in _after(series, day) if r[0] > bar[0]]
    if len(tail) < 5:
        return {"ok": None, "note": "關鍵K後還沒走完 5 根"}
    ev_h = bar[2]
    d10 = tail[:10]
    new_high = max(r[2] for r in d10) > ev_h * 1.01
    if re.search(r"(止漲整理|轉折|轉弱)", text):
        return {
            "ok": not new_high,
            "note": "10 日沒過當日高＝轉折K對上" if not new_high else "10 日內又過當日高，轉折偏早",
        }
    return {"ok": None, "note": "關鍵K句沒有轉折／止漲"}


def _bucket() -> Dict[str, Any]:
    return {"n": 0, "hit": 0, "miss": 0, "pending": 0, "samples": []}


def _add(bucket: Dict[str, Any], row: Dict[str, Any]) -> None:
    bucket["n"] += 1
    ok = row.get("ok")
    if ok is True:
        bucket["hit"] += 1
    elif ok is False:
        bucket["miss"] += 1
    else:
        bucket["pending"] += 1
    bucket["samples"].append(row)
    if len(bucket["samples"]) > 48:
        bucket["samples"] = bucket["samples"][-48:]


def load_posts(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, date, time, kind, text
        FROM biaoke_posts
        WHERE IFNULL(kind, 'post') != 'bystander'
        ORDER BY date, time
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "date": r[1],
            "time": r[2],
            "kind": r[3] or "post",
            "text": r[4] or "",
        }
        for r in rows
    ]


def load_mentions(conn: sqlite3.Connection) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    try:
        rows = conn.execute(
            "SELECT post_id, stock_id, stock_name FROM biaoke_mentions"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for pid, sid, name in rows:
        sid = str(sid or "").strip()
        if not sid or sid in _SKIP_SID:
            continue
        out[str(pid)].append((sid, str(name or sid)))
    return out


def run_five_bt(db_path: str) -> Dict[str, Any]:
    if not db_path or not os.path.isfile(db_path):
        return {"ok": False, "error": "沒這顆庫"}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    try:
        posts = load_posts(conn)
        mentions = load_mentions(conn)
        cache: Dict[str, List[Tuple[str, float, float, float, float]]] = {}
        twii = _series(conn, "TWII", cache)
        buckets = {
            "wave": _bucket(),
            "morph": _bucket(),
            "vol": _bucket(),
            "keyk": _bucket(),
            "leader": _bucket(),
        }
        n_tool = 0
        for p in posts:
            spoken = _spoken(p["text"])
            if not spoken:
                continue
            tools = _tools(spoken)
            if not tools:
                continue
            n_tool += 1
            day = _ymd(p["date"])
            pairs = mentions.get(str(p["id"]) or "", [])
            sids = [s for s, _n in pairs]
            if "wave" in tools:
                tw = _on_or_before(twii, day)
                close = float(tw[1]) if tw else 0.0
                for px in _levels(spoken, sids, close, day):
                    row = _verdict_wave(twii, day, px, spoken)
                    if "水平沒判方向" in str(row.get("note")):
                        continue
                    _add(
                        buckets["wave"],
                        {
                            "id": p["id"],
                            "date": p["date"],
                            "px": px,
                            "ok": row.get("ok"),
                            "note": row.get("note"),
                        },
                    )
            stock_tools = [t for t in tools if t in ("morph", "vol", "keyk")]
            for sid, name in pairs[:6]:
                series = _series(conn, sid, cache)
                if "morph" in stock_tools:
                    row = _verdict_morph(series, day, spoken)
                    note = str(row.get("note") or "")
                    if "沒有可對" in note or "發文日附近沒官方柱" in note:
                        pass
                    elif note:
                        _add(
                            buckets["morph"],
                            {
                                "id": p["id"],
                                "date": p["date"],
                                "sid": sid,
                                "name": name,
                                "ok": row.get("ok"),
                                "note": note,
                            },
                        )
                if "vol" in stock_tools:
                    row = _verdict_vol(series, day)
                    note = str(row.get("note") or "")
                    if note.startswith("這條不計") or "發文日附近沒官方柱" in note:
                        pass
                    else:
                        _add(
                            buckets["vol"],
                            {
                                "id": p["id"],
                                "date": p["date"],
                                "sid": sid,
                                "name": name,
                                "ok": row.get("ok"),
                                "note": note,
                                "r20": row.get("r20"),
                            },
                        )
                if "keyk" in stock_tools:
                    row = _verdict_keyk(series, day, spoken)
                    note = str(row.get("note") or "")
                    if "沒有轉折" in note or "發文日附近沒官方柱" in note:
                        pass
                    elif note:
                        _add(
                            buckets["keyk"],
                            {
                                "id": p["id"],
                                "date": p["date"],
                                "sid": sid,
                                "name": name,
                                "ok": row.get("ok"),
                                "note": note,
                            },
                        )
            if "keyk" in tools or "morph" in tools:
                try:
                    from biaoke_judge import leader_of
                except Exception:
                    leader_of = None  # type: ignore
                if leader_of and len(pairs) >= 2:
                    seen_lead = set()
                    for sid, name in pairs:
                        lid, lname, _why = leader_of("", sid, name)
                        if not lid or lid == sid or lid not in sids:
                            continue
                        key = (day, sid, lid)
                        if key in seen_lead:
                            continue
                        seen_lead.add(key)
                        ls = _series(conn, lid, cache)
                        fs = _series(conn, sid, cache)
                        if not _aligned(ls, day) or not _aligned(fs, day):
                            continue
                        lr = _fwd(ls, day, 10)
                        fr = _fwd(fs, day, 10)
                        if lr is None or fr is None:
                            _add(
                                buckets["leader"],
                                {
                                    "id": p["id"],
                                    "date": p["date"],
                                    "sid": sid,
                                    "leader": lid,
                                    "ok": None,
                                    "note": "龍頭或跟漲後 10 根還沒齊",
                                },
                            )
                            continue
                        ok = fr <= lr + 3.0
                        _add(
                            buckets["leader"],
                            {
                                "id": p["id"],
                                "date": p["date"],
                                "sid": sid,
                                "name": name,
                                "leader": lid,
                                "lname": lname,
                                "ok": ok,
                                "note": f"跟漲 10 日 {fr}% vs 龍頭 {lr}%",
                            },
                        )
        last = twii[-1][0] if twii else ""
        snap = {
            "ok": True,
            "n_posts": len(posts),
            "n_tool": n_tool,
            "last_official": last,
            "tools": buckets,
            "disclaimer": "不是買訊、不進海選。個股不數 5／9。對跟錯一起留。",
        }
        return snap
    finally:
        conn.close()


def _rate(b: Dict[str, Any]) -> str:
    done = int(b.get("hit") or 0) + int(b.get("miss") or 0)
    if done <= 0:
        return "還沒走完"
    pct = 100.0 * int(b.get("hit") or 0) / done
    return f"{pct:.0f}%（{b.get('hit')}/{done}，未走完 {b.get('pending')}）"


def render_md(snap: Dict[str, Any]) -> str:
    tools = snap.get("tools") or {}
    lines = [
        "# 五件工具回測（官方柱）",
        "",
        snap.get("disclaimer") or "",
        "",
        f"發言（主文＋自回）{snap.get('n_posts')} 則，五件有打到 {snap.get('n_tool')} 則。"
        f"最後官方收 {snap.get('last_official') or '缺'}。",
        "",
        "| 工具 | 對上 | 說明 |",
        "|------|------|------|",
        f"| 波浪（只解大盤水平） | {_rate(tools.get('wave') or {})} | 不數個股 5／9 |",
        f"| 形態（平台／頸線／破線／假跌破） | {_rate(tools.get('morph') or {})} | 3 日內收過當日高＝假跌破 |",
        f"| 量價結構 | {_rate(tools.get('vol') or {})} | 爆量後日縮站撐才算這條 |",
        f"| 關鍵K／碎形 | {_rate(tools.get('keyk') or {})} | 轉折後 10 日不過當日高 |",
        f"| 龍頭碎形→跟漲 | {_rate(tools.get('leader') or {})} | 跟漲 10 日不該強過龍頭太多 |",
        "",
        "關鍵字偏多偏空那張表不能當勝率：他常對還在漲的龍頭說不要追。五件是另一個角度。",
        "",
        "## 樣本（每件最多 10 則）",
        "",
    ]
    titles = {
        "wave": "波浪",
        "morph": "形態",
        "vol": "量價",
        "keyk": "關鍵K",
        "leader": "龍頭碎形",
    }
    for key, title in titles.items():
        b = tools.get(key) or {}
        lines.append(f"### {title}")
        lines.append("")
        rows = list(b.get("samples") or [])
        hits = [s for s in rows if s.get("ok") is True][-4:]
        miss = [s for s in rows if s.get("ok") is False][-4:]
        pend = [s for s in rows if s.get("ok") is None][-2:]
        shown = miss + hits + pend
        for s in shown:
            flag = "對" if s.get("ok") is True else ("錯" if s.get("ok") is False else "還沒")
            who = s.get("name") or s.get("sid") or "加權"
            extra = s.get("px")
            head = f"{s.get('date')} {who}"
            if extra:
                head += f" {extra:.0f}"
            lines.append(f"- {flag}　{head}　{s.get('note')}")
        if not shown:
            lines.append("- （沒打到）")
        lines.append("")
    lines.append("重跑：`python3 scripts/biaoke_five_bt.py`。")
    lines.append("")
    return "\n".join(lines)


def save_snapshot(snap: Dict[str, Any]) -> None:
    os.makedirs(_DIR, exist_ok=True)
    with open(SNAPSHOT_JSON, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(SNAPSHOT_MD, "w", encoding="utf-8") as f:
        f.write(render_md(snap))


def load_snapshot() -> Dict[str, Any]:
    if not os.path.isfile(SNAPSHOT_JSON):
        return {}
    with open(SNAPSHOT_JSON, encoding="utf-8") as f:
        return json.load(f)


def one_liner(snap: Optional[Dict[str, Any]] = None) -> str:
    snap = snap or load_snapshot()
    if not snap or not snap.get("ok"):
        return "五件回測這顆庫還沒跑完。"
    t = snap.get("tools") or {}
    return (
        f"五件對官方柱：波浪 {_rate(t.get('wave') or {})}；"
        f"形態 {_rate(t.get('morph') or {})}；"
        f"量價 {_rate(t.get('vol') or {})}；"
        f"關鍵K {_rate(t.get('keyk') or {})}；"
        f"龍頭碎形 {_rate(t.get('leader') or {})}。"
        f"最後官方收 {snap.get('last_official') or '缺'}。對跟錯一起留。不是買訊。"
    )
