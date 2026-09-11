# -*- coding: utf-8 -*-
"""飆大每一則：目標價／支撐／壓力／波浪／例子 → 當日官方價 → 後來實價 → 前後帖互參。

不是買訊。社團列進表但不進話筒原文。庫沒日 K 就標缺，不編。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

from biaoke_link import bar_on, extract_mentions

logger = logging.getLogger("WayneBot.BiaokeClaims")

_CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_claims (
    claim_key TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'post',
    club INTEGER NOT NULL DEFAULT 0,
    stock_id TEXT NOT NULL DEFAULT '',
    stock_name TEXT NOT NULL DEFAULT '',
    analog_id TEXT NOT NULL DEFAULT '',
    analog_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    verb TEXT NOT NULL DEFAULT '',
    lo REAL,
    hi REAL,
    snippet TEXT NOT NULL DEFAULT '',
    then_open REAL,
    then_high REAL,
    then_low REAL,
    then_close REAL,
    then_volume INTEGER,
    hit TEXT NOT NULL DEFAULT '',
    hit_date TEXT NOT NULL DEFAULT '',
    later_extreme REAL,
    prev_date TEXT NOT NULL DEFAULT '',
    prev_snippet TEXT NOT NULL DEFAULT '',
    next_date TEXT NOT NULL DEFAULT '',
    next_snippet TEXT NOT NULL DEFAULT '',
    mention_n INTEGER NOT NULL DEFAULT 0,
    mention_i INTEGER NOT NULL DEFAULT 0
);
"""
_CLAIMS_SID_IX = (
    "CREATE INDEX IF NOT EXISTS idx_biaoke_claims_sid "
    "ON biaoke_claims(stock_id, post_date, club);"
)

_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_NUM = re.compile(r"(?<![\d.])(\d{1,5}(?:\.\d+)?)(?![\d])")
_RANGE = re.compile(
    r"(?<![\d.])(\d{1,5}(?:\.\d+)?)\s*[~\-～至]\s*(\d{1,5}(?:\.\d+)?)(?![\d])"
)
_IDX_CTX = re.compile(
    r"(夜盤|台指期|台指|加權|大盤|細微波|穿刺|穿越)"
)
_TIME_AFTER = re.compile(
    r"^\s*(日|天|週|周|月|年|段|波|浪|成|倍|根|檔|篇|次|分|小時|%"
    r"|％|張|人|家|成機率)"
)
_ROLE = re.compile(
    r"(停損|"
    r"(?:第[一二三123]|型態)?(?:階段)?(?:滿足)?(?:目標價|目標區|目標)|"
    r"上看|挑戰|至少(?:會)?(?:到|測|穿越|反彈至|反彈到)?|"
    r"會到|會過|還會再測|一定還會測|測到|先看|過前高|"
    r"壓力(?:線|區)?|支撐(?:線|區|價)?|不跌破|不破|頸線|有守|站上|站穩|"
    r"低點確認)"
)
_WAVE = re.compile(
    r"(細微波|下降軌|上升軌|[1一]\s*[-~～到至]?\s*[4四]\s*重疊|"
    r"[59]段|頭肩頂|破底翻|等幅測距|右肩)"
)
_EXAMPLE = re.compile(r"(會像|走勢像|如同|類比)")
_SPLIT = re.compile(r"[。！？!?\n；;]+")
_LOOKAHEAD_BARS = 80


def ensure_biaoke_claims_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_CLAIMS_DDL)
        conn.execute(_CLAIMS_SID_IX)
        conn.commit()
    finally:
        conn.close()


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _px_s(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _skip_num(raw: str, before: str, after: str) -> bool:
    whole = raw.split(".")[0]
    if _YEAR.fullmatch(whole) and "." not in raw:
        if not re.search(r"(目標|支撐|壓力|價|到|測|穿越|上看|至少)", before[-12:]):
            if not re.match(r"^\s*[~\-～至]", after):
                return True
    if after[:1] and after[:1] in "*＊xXＸ":
        return True
    if _TIME_AFTER.match(after):
        return True
    if re.search(r"[/／]\s*$", before):
        return True
    if re.search(r"(第|MA|均線)$", before) and re.match(
        r"^\s*(個)?(段|波|浪|日)", after
    ):
        return True
    if re.match(r"^\s*/\s*\d", after):
        return True
    if re.match(r"^\s*[~\-～]\s*\d+", after) and re.search(
        r"(天|日|週|周|月|年)", after[:16]
    ):
        return True
    if "資金" in after[:8] or "持股" in after[:8]:
        return True
    if re.match(r"^\s*(個)?(日|天|週|周|月|年)", after):
        return True
    if re.match(r"^\s*點", after):
        try:
            if float(raw) < 8000:
                return True
        except ValueError:
            return True
    return False


def _role_of(window: str) -> str:
    if re.search(r"停損", window):
        return "stop"
    if re.search(
        r"(?:第[一二三123]|型態)?(?:階段)?(?:滿足)?(?:目標價|目標區|目標)|"
        r"上看|挑戰|至少(?:會)?(?:到|測|穿越|反彈)?|會到|會過|"
        r"還會再測|一定還會測|測到|過前高",
        window,
    ):
        return "target"
    if re.search(r"壓力", window):
        return "pressure"
    if re.search(
        r"支撐|不跌破|不破|頸線|有守|站上|站穩|低點確認",
        window,
    ):
        return "support"
    if re.search(r"先看", window):
        return "target"
    return ""


def _verb_of(window: str) -> str:
    m = re.search(r"(目標價|目標區|目標)", window)
    if m:
        return m.group(0)[:12]
    m = re.search(
        r"(上看|挑戰|至少(?:會)?(?:到|測|穿越|反彈至|反彈到)|"
        r"會到|會過|還會再測|測到|過前高|至少)",
        window,
    )
    if m:
        return m.group(0)[:12]
    m = _ROLE.search(window)
    return (m.group(0) if m else "")[:12]


def _nearest_stock(
    sent: str, pos: int, mentions: Sequence[Dict[str, str]]
) -> Optional[Dict[str, str]]:
    best = None
    best_d = 10**9
    for hit in mentions:
        name = str(hit.get("stock_name") or "")
        sid = str(hit.get("stock_id") or "")
        for key in (name, sid):
            if not key:
                continue
            start = 0
            while True:
                i = sent.find(key, start)
                if i < 0:
                    break
                d = min(abs(i - pos), abs(i + len(key) - pos))
                if d < best_d:
                    best_d = d
                    best = {"stock_id": sid, "stock_name": name or sid}
                start = i + len(key)
    if best is not None and best_d <= 72:
        return best
    return None


def _bind(
    sent: str,
    pos: int,
    n: float,
    mentions: Sequence[Dict[str, str]],
    last: Optional[Dict[str, str]],
    post_mentions: Sequence[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    window = sent[max(0, pos - 28) : pos + 18]
    if n >= 15000 or (n >= 8000 and _IDX_CTX.search(window or sent)):
        name = "台指" if re.search(r"台指|夜盤", window or sent) else "加權"
        return {"stock_id": "TWII", "stock_name": name}
    hit = _nearest_stock(sent, pos, mentions)
    if hit:
        return hit
    if last:
        return last
    if len(post_mentions) == 1:
        h = post_mentions[0]
        return {
            "stock_id": str(h.get("stock_id") or ""),
            "stock_name": str(h.get("stock_name") or ""),
        }
    return None


def extract_claims(
    text: str,
    *,
    mentions: Optional[Sequence[Dict[str, str]]] = None,
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """一段正文 → 目標／支撐／壓力／波浪／例子。沒對到檔名的數字丟掉。"""
    blob = _norm(text)
    if not blob.strip():
        return []
    post_mentions = list(mentions or [])
    if not post_mentions:
        post_mentions = extract_mentions(blob, db_path=db_path)
    out: List[Dict[str, Any]] = []
    seen = set()
    last: Optional[Dict[str, str]] = None
    parts = [p for p in _SPLIT.split(blob) if p.strip()]
    if not parts:
        parts = [blob]

    def add(row: Dict[str, Any]) -> None:
        sid = str(row.get("stock_id") or "")
        role = str(row.get("role") or "")
        lo = row.get("lo")
        hi = row.get("hi")
        verb = str(row.get("verb") or "")
        key = (sid, role, lo, hi, verb, str(row.get("snippet") or "")[:40])
        if not sid or not role or key in seen:
            return
        seen.add(key)
        out.append(row)

    for sent in parts:
        local = extract_mentions(sent, db_path=db_path) or []
        if local:
            last = {
                "stock_id": str(local[0].get("stock_id") or ""),
                "stock_name": str(local[0].get("stock_name") or ""),
            }
        used = set()
        for m in _RANGE.finditer(sent):
            a_s, b_s = m.group(1), m.group(2)
            before, after = sent[: m.start()], sent[m.end() :]
            if _skip_num(a_s, before, after) or _skip_num(b_s, before, after):
                continue
            window = sent[max(0, m.start() - 24) : m.end() + 10]
            role = _role_of(window)
            if not role:
                continue
            try:
                a, b = float(a_s), float(b_s)
            except ValueError:
                continue
            lo, hi = (a, b) if a <= b else (b, a)
            if hi >= 8000 and lo < 8000:
                continue
            bind = _bind(sent, m.start(), hi, local, last, post_mentions)
            if not bind:
                continue
            used.update(range(m.start(), m.end()))
            last = bind
            add(
                {
                    "stock_id": bind["stock_id"],
                    "stock_name": bind["stock_name"],
                    "role": role,
                    "verb": _verb_of(window),
                    "lo": lo,
                    "hi": hi,
                    "snippet": _clip(sent, 110),
                    "analog_id": "",
                    "analog_name": "",
                }
            )
        for m in _NUM.finditer(sent):
            if any(p in used for p in range(m.start(), m.end())):
                continue
            raw = m.group(1)
            before, after = sent[: m.start()], sent[m.end() :]
            if _skip_num(raw, before, after):
                continue
            window = sent[max(0, m.start() - 24) : m.end() + 12]
            role = _role_of(window)
            if not role:
                continue
            try:
                n = float(raw)
            except ValueError:
                continue
            if n <= 0:
                continue
            bind = _bind(sent, m.start(), n, local, last, post_mentions)
            if not bind:
                continue
            last = bind
            add(
                {
                    "stock_id": bind["stock_id"],
                    "stock_name": bind["stock_name"],
                    "role": role,
                    "verb": _verb_of(window),
                    "lo": n,
                    "hi": n,
                    "snippet": _clip(sent, 110),
                    "analog_id": "",
                    "analog_name": "",
                }
            )
        if _WAVE.search(sent):
            bind = None
            if _IDX_CTX.search(sent) or re.search(r"15\s*分|60\s*分", sent):
                bind = {"stock_id": "TWII", "stock_name": "加權"}
            elif local:
                bind = {
                    "stock_id": str(local[0].get("stock_id") or ""),
                    "stock_name": str(local[0].get("stock_name") or ""),
                }
            elif last:
                bind = last
            elif len(post_mentions) == 1:
                bind = {
                    "stock_id": str(post_mentions[0].get("stock_id") or ""),
                    "stock_name": str(post_mentions[0].get("stock_name") or ""),
                }
            if bind and bind.get("stock_id"):
                note = _clip(sent, 110)
                if re.search(r"15\s*分|60\s*分", sent):
                    note = "庫沒15分K不數段。" + note
                add(
                    {
                        "stock_id": bind["stock_id"],
                        "stock_name": bind["stock_name"],
                        "role": "wave",
                        "verb": (_WAVE.search(sent).group(0) if _WAVE.search(sent) else "波浪")[:12],
                        "lo": None,
                        "hi": None,
                        "snippet": note,
                        "analog_id": "",
                        "analog_name": "",
                    }
                )
        if _EXAMPLE.search(sent):
            names = local or post_mentions
            if len(names) >= 2:
                a, b = names[0], names[1]
                add(
                    {
                        "stock_id": str(a.get("stock_id") or ""),
                        "stock_name": str(a.get("stock_name") or ""),
                        "role": "example",
                        "verb": (
                            _EXAMPLE.search(sent).group(0)
                            if _EXAMPLE.search(sent)
                            else "如同"
                        )[:12],
                        "lo": None,
                        "hi": None,
                        "snippet": _clip(sent, 110),
                        "analog_id": str(b.get("stock_id") or ""),
                        "analog_name": str(b.get("stock_name") or ""),
                    }
                )
    return out


def _claim_key(
    post_id: str,
    club: int,
    row: Dict[str, Any],
) -> str:
    lo = row.get("lo")
    hi = row.get("hi")
    lo_s = "" if lo is None else _px_s(lo)
    hi_s = "" if hi is None else _px_s(hi)
    return "|".join(
        [
            str(post_id),
            str(int(club)),
            str(row.get("stock_id") or ""),
            str(row.get("role") or ""),
            lo_s,
            hi_s,
            str(row.get("verb") or "")[:12],
        ]
    )


def _load_tx_bars(conn: sqlite3.Connection, session: str) -> List[Dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM futures_daily "
            "WHERE symbol='TX' AND session=? ORDER BY date",
            (session,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        ymd = _ymd(r[0])
        if not ymd or r[2] is None or r[3] is None or r[4] is None:
            continue
        out.append(
            {
                "date": ymd,
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
            }
        )
    return out


def _load_bars(conn: sqlite3.Connection, sid: str) -> List[Dict[str, Any]]:
    try:
        if sid == "TWII":
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume FROM index_daily "
                "WHERE symbol='TWII' ORDER BY date"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume FROM daily_quotes "
                "WHERE stock_id=? ORDER BY date",
                (sid,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        ymd = _ymd(r[0])
        if not ymd:
            continue
        if r[2] is None or r[3] is None or r[4] is None:
            continue
        out.append(
            {
                "date": ymd,
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
            }
        )
    return out


def _bar_at(bars: Sequence[Dict[str, Any]], ymd: str) -> Optional[Dict[str, Any]]:
    key = _ymd(ymd)
    for b in bars:
        if b["date"] == key:
            return b
    return None


def _later(bars: Sequence[Dict[str, Any]], ymd: str) -> List[Dict[str, Any]]:
    key = _ymd(ymd)
    return [b for b in bars if b["date"] > key][:_LOOKAHEAD_BARS]


def _hit_claim(role: str, lo: Optional[float], hi: Optional[float], later: Sequence[Dict[str, Any]]) -> Tuple[str, str, Optional[float]]:
    if lo is None:
        return "", "", None
    goal = float(lo)
    if role in ("target", "pressure"):
        extreme = None
        for b in later:
            hi_b = b.get("high")
            if hi_b is None:
                continue
            h = float(hi_b)
            extreme = h if extreme is None else max(extreme, h)
            if h >= goal:
                return "後續高碰到", b["date"], h
        if later:
            return "後續高還沒到", "", extreme
        return "庫沒後續日K", "", None
    if role in ("support", "stop"):
        extreme = None
        for b in later:
            lo_b = b.get("low")
            if lo_b is None:
                continue
            l = float(lo_b)
            extreme = l if extreme is None else min(extreme, l)
            if l < goal:
                return "後續低跌破", b["date"], l
        if later:
            return "後續低有守", "", extreme
        return "庫沒後續日K", "", None
    return "", "", None


def _then_note(role: str, lo: Optional[float], bar: Optional[Dict[str, Any]]) -> str:
    if lo is None or not bar:
        return "庫沒這天" if not bar else ""
    try:
        goal = float(lo)
        hi = float(bar["high"]) if bar.get("high") is not None else None
        low = float(bar["low"]) if bar.get("low") is not None else None
    except (TypeError, ValueError):
        return ""
    if role in ("target", "pressure") and hi is not None:
        return "當日高過到" if hi >= goal else "當日高還沒到"
    if role in ("support", "stop") and low is not None:
        return "當日低有守" if low >= goal else "當日低跌破"
    return ""


def file_biaoke_claims(
    db_path: str,
    batches: Sequence[Tuple[Sequence[Dict[str, Any]], int]],
) -> Dict[str, int]:
    """把批次（公開／社團）寫進 biaoke_claims，對當日與後來官方日 K。"""
    stats = {"claims": 0, "with_bar": 0, "targets": 0, "cross": 0}
    if not db_path:
        return stats
    ensure_biaoke_claims_table(db_path)
    rows: List[Dict[str, Any]] = []
    for posts, club_flag in batches:
        for p in posts:
            aid = str(p.get("id") or "")
            day = str(p.get("date") or "")
            if not aid or not _ymd(day):
                continue
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
            for c in extract_claims(text, mentions=mentions, db_path=db_path):
                c = dict(c)
                c["post_id"] = aid
                c["post_date"] = day
                c["post_time"] = str(p.get("time") or "")
                c["kind"] = str(p.get("kind") or "post")
                c["club"] = int(club_flag)
                c["claim_key"] = _claim_key(aid, int(club_flag), c)
                rows.append(c)
    conn = sqlite3.connect(db_path, timeout=30.0)
    bar_cache: Dict[str, List[Dict[str, Any]]] = {}
    try:
        by_sid: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for c in rows:
            sid = str(c.get("stock_id") or "")
            snippet = str(c.get("snippet") or "")
            if sid == "TWII" and "夜盤" in snippet:
                cache_key = "TX:night"
                if cache_key not in bar_cache:
                    bar_cache[cache_key] = _load_tx_bars(conn, "night")
                bars = bar_cache[cache_key]
            else:
                if sid not in bar_cache:
                    bar_cache[sid] = _load_bars(conn, sid)
                bars = bar_cache[sid]
            bar = _bar_at(bars, c.get("post_date") or "")
            if bar:
                stats["with_bar"] += 1
                c["then_open"] = bar.get("open")
                c["then_high"] = bar.get("high")
                c["then_low"] = bar.get("low")
                c["then_close"] = bar.get("close")
                c["then_volume"] = bar.get("volume")
            else:
                c["then_open"] = c["then_high"] = c["then_low"] = None
                c["then_close"] = c["then_volume"] = None
            role = str(c.get("role") or "")
            if role == "wave" and "庫沒15分K" in str(c.get("snippet") or ""):
                c["hit"] = "庫沒15分K不數段"
                c["hit_date"] = ""
                c["later_extreme"] = None
            elif role in ("target", "pressure", "support", "stop"):
                then = _then_note(role, c.get("lo"), bar)
                later = _later(bars, c.get("post_date") or "") if bar else []
                later_hit, hit_date, extreme = _hit_claim(
                    role, c.get("lo"), c.get("hi"), later
                )
                bits = [x for x in (then, later_hit) if x]
                if not bar:
                    bits = ["庫沒這天"]
                c["hit"] = "；".join(bits)
                c["hit_date"] = hit_date or ""
                c["later_extreme"] = extreme
                if role == "target":
                    stats["targets"] += 1
            else:
                c["hit"] = ""
                c["hit_date"] = ""
                c["later_extreme"] = None
            by_sid.setdefault((sid, int(c.get("club") or 0)), []).append(c)
        for (_sid, _club), group in by_sid.items():
            group.sort(
                key=lambda r: (
                    str(r.get("post_date") or ""),
                    str(r.get("post_time") or ""),
                    str(r.get("post_id") or ""),
                    str(r.get("role") or ""),
                )
            )
            n = len(group)
            for i, c in enumerate(group):
                c["mention_n"] = n
                c["mention_i"] = i + 1
                if i:
                    prev = group[i - 1]
                    c["prev_date"] = str(prev.get("post_date") or "")
                    c["prev_snippet"] = _clip(prev.get("snippet") or "", 70)
                    stats["cross"] += 1
                else:
                    c["prev_date"] = c["prev_snippet"] = ""
                if i + 1 < n:
                    nxt = group[i + 1]
                    c["next_date"] = str(nxt.get("post_date") or "")
                    c["next_snippet"] = _clip(nxt.get("snippet") or "", 70)
                else:
                    c["next_date"] = c["next_snippet"] = ""
        payload = []
        for c in rows:
            payload.append(
                (
                    c.get("claim_key"),
                    c.get("post_id"),
                    c.get("post_date"),
                    c.get("post_time"),
                    c.get("kind"),
                    int(c.get("club") or 0),
                    c.get("stock_id"),
                    c.get("stock_name") or "",
                    c.get("analog_id") or "",
                    c.get("analog_name") or "",
                    c.get("role"),
                    c.get("verb") or "",
                    c.get("lo"),
                    c.get("hi"),
                    c.get("snippet") or "",
                    c.get("then_open"),
                    c.get("then_high"),
                    c.get("then_low"),
                    c.get("then_close"),
                    c.get("then_volume"),
                    c.get("hit") or "",
                    c.get("hit_date") or "",
                    c.get("later_extreme"),
                    c.get("prev_date") or "",
                    c.get("prev_snippet") or "",
                    c.get("next_date") or "",
                    c.get("next_snippet") or "",
                    int(c.get("mention_n") or 0),
                    int(c.get("mention_i") or 0),
                )
            )
        conn.execute("DELETE FROM biaoke_claims")
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_claims (
                claim_key, post_id, post_date, post_time, kind, club,
                stock_id, stock_name, analog_id, analog_name, role, verb,
                lo, hi, snippet, then_open, then_high, then_low, then_close,
                then_volume, hit, hit_date, later_extreme, prev_date, prev_snippet,
                next_date, next_snippet, mention_n, mention_i
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            payload,
        )
        conn.commit()
    finally:
        conn.close()
    stats["claims"] = len(rows)
    logger.info(
        "飆大建檔 claims=%s with_bar=%s targets=%s cross=%s",
        stats["claims"],
        stats["with_bar"],
        stats["targets"],
        stats["cross"],
    )
    return stats


def stock_claim_rows(
    db_path: str, sid: str, *, club: int = 0, limit: int = 12
) -> List[Dict[str, Any]]:
    sid = str(sid or "").strip()
    if not db_path or not os.path.isfile(db_path) or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_claims'"
        ).fetchone()
        if not hit:
            return []
        rows = conn.execute(
            """
            SELECT post_date, post_time, role, verb, lo, hi, snippet,
                   then_close, then_low, then_high, hit, hit_date,
                   prev_date, next_date, mention_n, mention_i,
                   analog_name, stock_name, kind
            FROM biaoke_claims
            WHERE stock_id=? AND IFNULL(club,0)=?
            ORDER BY post_date, post_time, post_id, role
            """,
            (sid, int(club)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    keys = (
        "post_date",
        "post_time",
        "role",
        "verb",
        "lo",
        "hi",
        "snippet",
        "then_close",
        "then_low",
        "then_high",
        "hit",
        "hit_date",
        "prev_date",
        "next_date",
        "mention_n",
        "mention_i",
        "analog_name",
        "stock_name",
        "kind",
    )
    out = [dict(zip(keys, r)) for r in rows]
    if limit and len(out) > limit:
        priced = [
            r
            for r in out
            if r.get("role") in ("target", "support", "stop", "pressure")
        ]
        pick = []
        if priced:
            pick.append(priced[0])
        targs = [r for r in priced if r.get("role") == "target"]
        if targs and targs[0] not in pick:
            pick.append(targs[0])
        tail = priced[-(limit - len(pick)) :] if priced else []
        rest = [r for r in out if r.get("role") in ("example", "wave")]
        seen = set()
        slim = []
        for r in pick + tail + rest[:2]:
            k = (r.get("post_date"), r.get("role"), r.get("lo"), r.get("verb"))
            if k in seen:
                continue
            seen.add(k)
            slim.append(r)
        return slim[:limit]
    return out


def format_stock_claims(db_path: str, sid: str, *, name: str = "") -> str:
    """給對話腦／手機：這檔他預估過的價，當日收，後來碰到沒。不是買訊。"""
    from tg_layout import html_escape

    rows = stock_claim_rows(db_path, sid, club=0, limit=10)
    if not rows:
        return ""
    nm = html_escape(rows[0].get("stock_name") or name or sid)
    n = int(rows[0].get("mention_n") or len(rows))
    lines = [
        f"{html_escape(sid)} {nm} 公開文對價 {n} 則（含前後互參）。"
    ]
    for r in rows:
        role = str(r.get("role") or "")
        bit = html_escape(str(r.get("post_date") or ""))
        if role == "example":
            bit += " 例子像 " + html_escape(str(r.get("analog_name") or ""))
        elif role == "wave":
            bit += " 波浪 " + html_escape(_clip(r.get("snippet") or "", 36))
        else:
            verb = html_escape(str(r.get("verb") or role))
            lo = _px_s(r.get("lo"))
            hi = _px_s(r.get("hi"))
            px = lo if lo == hi or not hi else f"{lo}～{hi}"
            bit += f" {verb}{html_escape(px)}"
            if r.get("then_close") is not None:
                bit += f" 當日收 {_px_s(r.get('then_close'))}"
            if r.get("hit"):
                bit += " " + html_escape(str(r.get("hit")))
            if r.get("hit_date"):
                bit += " " + html_escape(str(r.get("hit_date")))
        if r.get("prev_date"):
            bit += " 前次 " + html_escape(str(r.get("prev_date")))
        if r.get("next_date"):
            bit += " 後次 " + html_escape(str(r.get("next_date")))
        lines.append(bit)
    lines.append("不是買訊。")
    return "\n".join(lines)


def format_claim_notes(db_path: str, ask: str) -> str:
    """問句裡的檔名 → 目標價對照。沒點名就空。"""
    q = str(ask or "").strip()
    if not q or not db_path:
        return ""
    hits = extract_mentions(q, db_path=db_path)
    if not hits:
        try:
            from biaoke_brain import resolve_stock

            hits = resolve_stock(db_path, q) or []
        except Exception:
            hits = []
    if not hits:
        return ""
    sid = str(hits[0].get("stock_id") or "")
    name = str(hits[0].get("stock_name") or "")
    if not sid:
        return ""
    return format_stock_claims(db_path, sid, name=name)
