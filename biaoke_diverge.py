# -*- coding: utf-8 -*-
"""飆大點位／大盤走法：他說＋我說＋之後官方柱（靜默對質分軌）。

鎖死（2026-10-15）：
- 他講到點位或大盤後續走法 → **必須**有可重算「我說／下一步」（不是可有可無）
- 只進靜默對質；**不准**話筒抬槓、不准當買訊、不准發明他沒說過的價
- 落檔＝他說＋我說＋之後官方柱；柱走完標 對／偏／未完
- §13：獨立交易日 n≥20 **且** 下一版贏該軌現況 → 換該軌編碼並再生下一版；
  空列／空點位不算；未過閘不改買訊、不進話筒
- 過程％不准進對話；與情境預估 D.C 軌隔離
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("WayneBot.BiaokeDiverge")

TAIPEI = ZoneInfo("Asia/Taipei")
HORIZON_BARS = 5
LOOKBACK_DEFAULT = 20
SWING_DEFAULT = 5
MIN_UNIQUE_DAYS = 20
VARIANT_CURRENT = "current"
VARIANT_NEXT = "next"
TRACK_VARIANTS = (VARIANT_CURRENT, VARIANT_NEXT)

# 預設現況＝近5高低錨；下一版候選＝近10高低錨（可重算，非買訊）
_DEFAULT_RULES = {
    VARIANT_CURRENT: {"lookback": 20, "swing": 5, "label": "近5窗錨"},
    VARIANT_NEXT: {"lookback": 20, "swing": 10, "label": "近10窗錨"},
}

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_diverge (
    diverge_key TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    post_id TEXT NOT NULL DEFAULT '',
    stock_id TEXT NOT NULL DEFAULT '',
    stock_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    his_lo REAL,
    his_hi REAL,
    his_snippet TEXT NOT NULL DEFAULT '',
    his_json TEXT NOT NULL DEFAULT '{}',
    our_lo REAL,
    our_hi REAL,
    our_basis TEXT NOT NULL DEFAULT '',
    our_path TEXT NOT NULL DEFAULT '',
    our_json TEXT NOT NULL DEFAULT '{}',
    diverged INTEGER NOT NULL DEFAULT 0,
    then_open REAL,
    then_high REAL,
    then_low REAL,
    then_close REAL,
    then_volume INTEGER,
    check_n INTEGER NOT NULL DEFAULT 0,
    check_high REAL,
    check_low REAL,
    check_close REAL,
    his_verdict TEXT NOT NULL DEFAULT '',
    our_verdict TEXT NOT NULL DEFAULT '',
    winner TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    variant TEXT NOT NULL DEFAULT 'current'
);
CREATE INDEX IF NOT EXISTS idx_biaoke_diverge_asof
    ON biaoke_diverge(as_of, stock_id);
CREATE INDEX IF NOT EXISTS idx_biaoke_diverge_pending
    ON biaoke_diverge(winner, as_of);
CREATE TABLE IF NOT EXISTS biaoke_diverge_rules (
    variant TEXT PRIMARY KEY,
    lookback INTEGER NOT NULL DEFAULT 20,
    swing INTEGER NOT NULL DEFAULT 5,
    label TEXT NOT NULL DEFAULT '',
    gen INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS biaoke_diverge_rates (
    variant TEXT NOT NULL,
    n_days INTEGER NOT NULL DEFAULT 0,
    n_rows INTEGER NOT NULL DEFAULT 0,
    our_hit INTEGER NOT NULL DEFAULT 0,
    his_hit INTEGER NOT NULL DEFAULT 0,
    our_rate REAL NOT NULL DEFAULT 0,
    his_rate REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (variant)
);
"""

_PATH_MARK = re.compile(
    r"(大盤|台指|加權|夜盤|細微波|後續|走法|回測|破線|止跌|化解|再打|還會|"
    r"支撐|壓力|目標|不跌破|不破|站上|穿越|過前高)"
)
# 大盤點位常見句：破／跌破／點位在／收盤收 47300~47500（extract_claims 沒抓到時補）
_IDX_LEVEL = re.compile(
    r"(?:有效)?(?:往下)?(?:跌)?破|"
    r"點位(?:在|約)?|"
    r"收盤收|"
    r"臨界|"
    r"分界"
)
_IDX_NUM = re.compile(
    r"(?<![\d.])(\d{4,5}(?:\.\d+)?)\s*[~\-～至]\s*(\d{4,5}(?:\.\d+)?)(?![\d])"
    r"|(?<![\d.])(\d{4,5}(?:\.\d+)?)(?![\d])"
)
_IDX_CTX_LOCAL = re.compile(r"(夜盤|台指期|台指|加權|大盤|細微波)")


def _extract_index_levels(text: str) -> List[Dict[str, Any]]:
    """從大盤句補抽他說過的指數點位（破／點位在／收盤收）。不准發明新價。"""
    blob = str(text or "")
    if not blob.strip() or not _IDX_CTX_LOCAL.search(blob):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for sent in re.split(r"[。！？!?\n；;]+", blob):
        if not sent.strip() or not _IDX_LEVEL.search(sent):
            continue
        # 只收「關鍵字附近」的數字，避免同句遠距 40000 被破47500 誤綁
        for km in _IDX_LEVEL.finditer(sent):
            window = sent[max(0, km.start() - 2) : km.end() + 16]
            for m in _IDX_NUM.finditer(window):
                if m.group(1) and m.group(2):
                    try:
                        a, b = float(m.group(1)), float(m.group(2))
                    except ValueError:
                        continue
                    lo, hi = (a, b) if a <= b else (b, a)
                else:
                    try:
                        n = float(m.group(3))
                    except (TypeError, ValueError):
                        continue
                    lo = hi = n
                if hi < 8000 or hi >= 100000:
                    continue
                key = (round(lo, 2), round(hi, 2))
                if key in seen:
                    continue
                seen.add(key)
                role = "support"
                if re.search(r"壓力|目標|邁進|會到", window + sent[km.start() : km.end() + 40]):
                    role = (
                        "target"
                        if re.search(r"目標|邁進|會到", sent[km.start() : km.end() + 40])
                        else "pressure"
                    )
                if re.search(r"破|跌破|守|支撐|分界|臨界|收盤收", window):
                    role = "support"
                out.append(
                    {
                        "stock_id": "TWII",
                        "stock_name": "加權" if "加權" in sent else "台指",
                        "role": role,
                        "verb": "點位",
                        "lo": lo,
                        "hi": hi,
                        "snippet": _clip(sent, 110),
                    }
                )
    return out


def ensure_biaoke_diverge_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        # 舊庫補 variant 欄
        cols = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(biaoke_diverge)").fetchall()
        }
        if "variant" not in cols:
            conn.execute(
                "ALTER TABLE biaoke_diverge ADD COLUMN variant TEXT NOT NULL DEFAULT 'current'"
            )
        _ensure_default_rules(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_default_rules(conn: sqlite3.Connection) -> None:
    now = _now()
    for variant, spec in _DEFAULT_RULES.items():
        hit = conn.execute(
            "SELECT 1 FROM biaoke_diverge_rules WHERE variant=?", (variant,)
        ).fetchone()
        if hit:
            continue
        conn.execute(
            """
            INSERT INTO biaoke_diverge_rules(variant, lookback, swing, label, gen, active, updated_at)
            VALUES (?,?,?,?,1,1,?)
            """,
            (
                variant,
                int(spec["lookback"]),
                int(spec["swing"]),
                str(spec["label"]),
                now,
            ),
        )


def load_rules(db_path: str) -> Dict[str, Dict[str, Any]]:
    """讀該軌現況／下一版參數；缺則回預設。"""
    out = {
        VARIANT_CURRENT: dict(_DEFAULT_RULES[VARIANT_CURRENT]),
        VARIANT_NEXT: dict(_DEFAULT_RULES[VARIANT_NEXT]),
    }
    if not db_path or not os.path.isfile(db_path):
        return out
    ensure_biaoke_diverge_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT variant, lookback, swing, label, gen FROM biaoke_diverge_rules"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for variant, lookback, swing, label, gen in rows:
        out[str(variant)] = {
            "lookback": int(lookback or LOOKBACK_DEFAULT),
            "swing": int(swing or SWING_DEFAULT),
            "label": str(label or ""),
            "gen": int(gen or 1),
        }
    return out


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _num(val: Any) -> Optional[float]:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n or n <= 0:
        return None
    return n


def _clip(text: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _px_s(val: Any) -> str:
    n = _num(val)
    if n is None:
        return "—"
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _load_bars(conn: sqlite3.Connection, sid: str, night: bool = False) -> List[Dict[str, Any]]:
    sid = str(sid or "").strip()
    if not sid:
        return []
    try:
        if sid in ("TWII", "TX") or night:
            if night or sid == "TX" or (sid == "TWII" and night):
                rows = conn.execute(
                    "SELECT date, open, high, low, close, volume FROM futures_daily "
                    "WHERE symbol='TX' AND session=? ORDER BY date",
                    ("night" if night else "regular",),
                ).fetchall()
                if rows:
                    return [
                        {
                            "date": _ymd(r[0]),
                            "open": _num(r[1]),
                            "high": _num(r[2]),
                            "low": _num(r[3]),
                            "close": _num(r[4]),
                            "volume": r[5],
                        }
                        for r in rows
                        if _ymd(r[0])
                    ]
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume FROM index_daily "
                "WHERE symbol='TWII' ORDER BY date"
            ).fetchall()
            return [
                {
                    "date": _ymd(r[0]),
                    "open": _num(r[1]),
                    "high": _num(r[2]),
                    "low": _num(r[3]),
                    "close": _num(r[4]),
                    "volume": r[5],
                }
                for r in rows
                if _ymd(r[0])
            ]
        rows = conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume "
            "FROM daily_quotes WHERE stock_id=? ORDER BY 1",
            (sid,),
        ).fetchall()
        return [
            {
                "date": _ymd(r[0]),
                "open": _num(r[1]),
                "high": _num(r[2]),
                "low": _num(r[3]),
                "close": _num(r[4]),
                "volume": r[5],
            }
            for r in rows
            if _ymd(r[0])
        ]
    except sqlite3.Error:
        return []


def _bars_upto(bars: Sequence[Dict[str, Any]], as_of: str) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    if not day:
        return []
    # 盤中未收不當收：只用 as_of 當日以前（不含當日）若當日柱不完整；
    # 有完整 close 的列才納入；as_of 當日有 close 才含當日。
    out = []
    for b in bars:
        d = _ymd(b.get("date"))
        if not d or d > day:
            continue
        if _num(b.get("close")) is None:
            continue
        out.append(b)
    return out


def _bar_at(bars: Sequence[Dict[str, Any]], as_of: str) -> Optional[Dict[str, Any]]:
    day = _ymd(as_of)
    for b in reversed(list(bars)):
        if _ymd(b.get("date")) == day and _num(b.get("close")) is not None:
            return b
    return None


def _later_bars(
    bars: Sequence[Dict[str, Any]], as_of: str, n: int = HORIZON_BARS
) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    if not day or n <= 0:
        return []
    out = []
    for b in bars:
        d = _ymd(b.get("date"))
        if not d or d <= day:
            continue
        if _num(b.get("close")) is None:
            continue
        out.append(b)
        if len(out) >= n:
            break
    return out


def our_recalc_view(
    bars: Sequence[Dict[str, Any]],
    as_of: str,
    *,
    role: str = "",
    his_lo: Optional[float] = None,
    his_hi: Optional[float] = None,
    snippet: str = "",
    lookback: int = LOOKBACK_DEFAULT,
    swing: int = SWING_DEFAULT,
    label: str = "",
) -> Dict[str, Any]:
    """可重算「我說／下一步」：只認官方近窗高低／昨收，不抄他沒說過的價當他的。"""
    lb = max(3, int(lookback or LOOKBACK_DEFAULT))
    sw = max(2, int(swing or SWING_DEFAULT))
    upto = _bars_upto(bars, as_of)
    if not upto:
        # 沒柱仍要有看法骨架，標缺料，不准假數
        return {
            "our_lo": None,
            "our_hi": None,
            "our_basis": "庫缺官方近窗柱，我側暫不給價",
            "our_path": "等官方收齊近窗再重算走法（非買訊）",
            "diverged": 0,
            "then": {},
        }
    win = upto[-lb:] if len(upto) >= lb else list(upto)
    swing_bars = win[-sw:] if len(win) >= sw else list(win)
    last = win[-1]
    swing_hi = max((_num(b.get("high")) or 0) for b in swing_bars) or None
    swing_lo = min(
        (x for x in (_num(b.get("low")) for b in swing_bars) if x is not None),
        default=None,
    )
    d20_hi = max((_num(b.get("high")) or 0) for b in win) or None
    d20_lo = min(
        (x for x in (_num(b.get("low")) for b in win) if x is not None),
        default=None,
    )
    tag = str(label or f"近{len(swing_bars)}窗")
    role_l = str(role or "").lower()
    snip = str(snippet or "")
    if role_l in ("support", "stop") or re.search(r"支撐|不跌破|不破|有守", snip):
        our_lo = our_hi = swing_lo
        basis = f"{tag}官方低={_px_s(our_lo)}（{lb}窗低={_px_s(d20_lo)}）"
        path = "收在我側錨上偏震盪；破錨則看下一官方低（可重算，非買訊）"
    elif role_l in ("pressure", "target") or re.search(
        r"壓力|目標|上看|穿越|過前高|挑戰", snip
    ):
        our_lo = our_hi = swing_hi
        basis = f"{tag}官方高={_px_s(our_hi)}（{lb}窗高={_px_s(d20_hi)}）"
        path = "未過我側錨前偏壓；過錨且收穩才看延續（可重算，非買訊）"
    else:
        # 大盤走法／波浪語：仍必須有可重算下一步看法
        our_lo = swing_lo
        our_hi = swing_hi
        mid = None
        if our_lo is not None and our_hi is not None:
            mid = (our_lo + our_hi) / 2.0
        basis = (
            f"{tag}低/高={_px_s(our_lo)}/{_px_s(our_hi)}；"
            f"昨收={_px_s(last.get('close'))}"
        )
        path = (
            f"下一步以近窗中軸{_px_s(mid)}為界：收上偏續、收下偏收斂"
            "（可重算，非買訊；不准發明他沒說過的價）"
        )
    his_ref = _num(his_hi) if _num(his_hi) else _num(his_lo)
    our_ref = _num(our_hi) if _num(our_hi) else _num(our_lo)
    diverged = 0
    if his_ref and our_ref and our_ref > 0:
        pct = abs(his_ref - our_ref) / our_ref
        # 指數／期點門檻稍寬（點數大）；個股較緊
        thr = 0.002 if our_ref >= 8000 else 0.008
        if pct > thr:
            diverged = 1
    then = {
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "close": last.get("close"),
        "volume": last.get("volume"),
        "date": last.get("date"),
    }
    # 若 as_of 當日有完整柱，優先用當日當 then
    at = _bar_at(upto, as_of)
    if at:
        then = {
            "open": at.get("open"),
            "high": at.get("high"),
            "low": at.get("low"),
            "close": at.get("close"),
            "volume": at.get("volume"),
            "date": at.get("date"),
        }
    return {
        "our_lo": our_lo,
        "our_hi": our_hi,
        "our_basis": basis,
        "our_path": path,
        "diverged": diverged,
        "then": then,
    }


def _judge_side(
    role: str,
    lo: Optional[float],
    hi: Optional[float],
    later: Sequence[Dict[str, Any]],
) -> str:
    """對／偏／未完。沒有後來柱＝未完；沒有可對價＝未完。"""
    if not later:
        return "未完"
    role_l = str(role or "").lower()
    lo_n = _num(lo)
    hi_n = _num(hi)
    ref = hi_n if hi_n else lo_n
    if ref is None:
        # 走法／無點位：用後來收相對首根開／中軸粗判——無價就不判準
        return "未完"
    highs = [_num(b.get("high")) for b in later]
    lows = [_num(b.get("low")) for b in later]
    closes = [_num(b.get("close")) for b in later]
    highs = [x for x in highs if x is not None]
    lows = [x for x in lows if x is not None]
    closes = [x for x in closes if x is not None]
    if not highs or not lows or not closes:
        return "未完"
    mx, mn, last_c = max(highs), min(lows), closes[-1]
    tol = ref * (0.003 if ref >= 8000 else 0.01)
    if role_l in ("support", "stop"):
        # 有守：低點未深破；或測到附近後收回
        if mn >= ref - tol:
            return "對"
        if mn < ref - tol * 3 and last_c < ref - tol:
            return "偏"
        if abs(mn - ref) <= tol * 2:
            return "對"
        return "偏"
    if role_l in ("pressure", "target"):
        if mx >= ref - tol:
            return "對"
        if last_c < ref - tol * 2 and mx < ref - tol:
            return "偏"
        return "未完"
    # 一般走法：看收是否朝我側／他側錨靠攏——無明確方向句只標未完
    return "未完"


def _winner(his_v: str, our_v: str) -> str:
    if his_v == "未完" or our_v == "未完" or not his_v or not our_v:
        return "pending"
    if his_v == "對" and our_v != "對":
        return "his"
    if our_v == "對" and his_v != "對":
        return "our"
    if his_v == our_v:
        return "tie"
    return "tie"


def _diverge_key(
    post_id: str, claim_key: str, as_of: str, sid: str, role: str, variant: str = ""
) -> str:
    return "|".join(
        [
            str(post_id or ""),
            str(claim_key or "")[:80],
            _ymd(as_of),
            str(sid or ""),
            str(role or "")[:20],
            str(variant or VARIANT_CURRENT),
        ]
    )


def _instrument(
    sid: str, snippet: str
) -> Tuple[str, bool]:
    """回傳 (load_sid, night)。台指／夜盤走 TX。"""
    snip = str(snippet or "")
    night = "夜盤" in snip
    s = str(sid or "").strip() or "TWII"
    if s in ("TWII", "TX") or re.search(r"台指|大盤|加權", snip):
        if night or "台指" in snip:
            return "TX", night
        return "TWII", False
    return s, False


def record_diverge_rows(
    db_path: str,
    rows: Sequence[Dict[str, Any]],
) -> int:
    """寫入／更新分軌列。每列必須帶可重算 our_*（呼叫端已算或此處補）。"""
    if not db_path or not rows:
        return 0
    ensure_biaoke_diverge_table(db_path)
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for row in rows:
            key = str(row.get("diverge_key") or "").strip()
            if not key:
                continue
            conn.execute(
                """
                INSERT INTO biaoke_diverge (
                    diverge_key, as_of, post_id, stock_id, stock_name, role,
                    his_lo, his_hi, his_snippet, his_json,
                    our_lo, our_hi, our_basis, our_path, our_json, diverged,
                    then_open, then_high, then_low, then_close, then_volume,
                    check_n, check_high, check_low, check_close,
                    his_verdict, our_verdict, winner, checked_at, created_at,
                    variant
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(diverge_key) DO UPDATE SET
                    his_lo=excluded.his_lo,
                    his_hi=excluded.his_hi,
                    his_snippet=excluded.his_snippet,
                    his_json=excluded.his_json,
                    our_lo=excluded.our_lo,
                    our_hi=excluded.our_hi,
                    our_basis=excluded.our_basis,
                    our_path=excluded.our_path,
                    our_json=excluded.our_json,
                    diverged=excluded.diverged,
                    then_open=excluded.then_open,
                    then_high=excluded.then_high,
                    then_low=excluded.then_low,
                    then_close=excluded.then_close,
                    then_volume=excluded.then_volume,
                    variant=excluded.variant,
                    created_at=COALESCE(NULLIF(biaoke_diverge.created_at,''), excluded.created_at)
                """,
                (
                    key,
                    _ymd(row.get("as_of")),
                    str(row.get("post_id") or ""),
                    str(row.get("stock_id") or ""),
                    str(row.get("stock_name") or ""),
                    str(row.get("role") or ""),
                    row.get("his_lo"),
                    row.get("his_hi"),
                    str(row.get("his_snippet") or "")[:200],
                    json.dumps(row.get("his_json") or {}, ensure_ascii=False)[:2000],
                    row.get("our_lo"),
                    row.get("our_hi"),
                    str(row.get("our_basis") or "")[:240],
                    str(row.get("our_path") or "")[:240],
                    json.dumps(row.get("our_json") or {}, ensure_ascii=False)[:2000],
                    int(row.get("diverged") or 0),
                    row.get("then_open"),
                    row.get("then_high"),
                    row.get("then_low"),
                    row.get("then_close"),
                    row.get("then_volume"),
                    int(row.get("check_n") or 0),
                    row.get("check_high"),
                    row.get("check_low"),
                    row.get("check_close"),
                    str(row.get("his_verdict") or ""),
                    str(row.get("our_verdict") or ""),
                    str(row.get("winner") or ""),
                    str(row.get("checked_at") or ""),
                    str(row.get("created_at") or _now()),
                    str(row.get("variant") or VARIANT_CURRENT),
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def build_diverge_from_claim(
    db_path: str,
    claim: Dict[str, Any],
    *,
    bar_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    variants: Sequence[str] = TRACK_VARIANTS,
) -> List[Dict[str, Any]]:
    """單一他說點位／走法 → 現況＋下一版必填我說列（空點位／空看法不算）。"""
    post_id = str(claim.get("post_id") or claim.get("id") or "")
    as_of = _ymd(claim.get("post_date") or claim.get("date") or claim.get("as_of"))
    if not post_id or not as_of:
        return []
    sid = str(claim.get("stock_id") or "").strip()
    snip = str(claim.get("snippet") or claim.get("text") or "")
    role = str(claim.get("role") or "")
    his_lo = _num(claim.get("lo") if "lo" in claim else claim.get("his_lo"))
    his_hi = _num(claim.get("hi") if "hi" in claim else claim.get("his_hi"))
    # 無點位也要有走法列：正文要有大盤／點位語
    if his_lo is None and his_hi is None and role not in ("wave", "path"):
        if not _PATH_MARK.search(snip):
            return []
        role = role or "path"
    load_sid, night = _instrument(sid or "TWII", snip)
    cache = bar_cache if bar_cache is not None else {}
    ck = f"{load_sid}:{'night' if night else 'day'}"
    if ck not in cache:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            cache[ck] = _load_bars(conn, load_sid, night=night)
        finally:
            conn.close()
    claim_key = str(claim.get("claim_key") or "")
    if not claim_key:
        claim_key = "|".join(
            [post_id, sid, role, _px_s(his_lo), _px_s(his_hi)]
        )
    rules = load_rules(db_path)
    out: List[Dict[str, Any]] = []
    for variant in variants:
        spec = rules.get(str(variant)) or _DEFAULT_RULES.get(
            str(variant), _DEFAULT_RULES[VARIANT_CURRENT]
        )
        view = our_recalc_view(
            cache[ck],
            as_of,
            role=role,
            his_lo=his_lo,
            his_hi=his_hi,
            snippet=snip,
            lookback=int(spec.get("lookback") or LOOKBACK_DEFAULT),
            swing=int(spec.get("swing") or SWING_DEFAULT),
            label=str(spec.get("label") or ""),
        )
        # 空看法（無官方錨且無他說價）不算有記
        if (
            view.get("our_lo") is None
            and view.get("our_hi") is None
            and his_lo is None
            and his_hi is None
        ):
            continue
        then = view.get("then") or {}
        out.append(
            {
                "diverge_key": _diverge_key(
                    post_id, claim_key, as_of, sid or load_sid, role, str(variant)
                ),
                "as_of": as_of,
                "post_id": post_id,
                "stock_id": sid or load_sid,
                "stock_name": str(claim.get("stock_name") or ""),
                "role": role or "path",
                "his_lo": his_lo,
                "his_hi": his_hi,
                "his_snippet": _clip(snip),
                "his_json": {
                    "verb": str(claim.get("verb") or ""),
                    "claim_key": claim_key,
                    "kind": str(claim.get("kind") or "post"),
                },
                "our_lo": view.get("our_lo"),
                "our_hi": view.get("our_hi"),
                "our_basis": view.get("our_basis"),
                "our_path": view.get("our_path"),
                "our_json": {
                    "basis": view.get("our_basis"),
                    "path": view.get("our_path"),
                    "instrument": load_sid,
                    "night": night,
                    "variant": str(variant),
                    "lookback": int(spec.get("lookback") or LOOKBACK_DEFAULT),
                    "swing": int(spec.get("swing") or SWING_DEFAULT),
                    "gen": int(spec.get("gen") or 1),
                },
                "diverged": int(view.get("diverged") or 0),
                "then_open": then.get("open"),
                "then_high": then.get("high"),
                "then_low": then.get("low"),
                "then_close": then.get("close"),
                "then_volume": then.get("volume"),
                "his_verdict": "",
                "our_verdict": "",
                "winner": "",
                "variant": str(variant),
                "created_at": _now(),
            }
        )
    return out


def record_from_events(db_path: str, events: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """ingest 後：從主文／自回抽點位與大盤走法，必寫他說＋我說。

    路人正文不當他的判斷（呼叫端應已只傳 kind=post／reply）。
    失敗不擋抓文；不准推話筒。
    """
    stats = {"events": 0, "claims": 0, "rows": 0, "path_only": 0}
    if not db_path or not events:
        return stats
    ensure_biaoke_diverge_table(db_path)
    try:
        from biaoke_claims import extract_claims
        from biaoke_ingest import spoken_text
    except Exception:
        logger.exception("飆大分軌對質：依賴載入失敗")
        return stats
    built: List[Dict[str, Any]] = []
    cache: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        kind = str(ev.get("kind") or "post")
        if kind not in ("post", "reply", ""):
            continue
        if kind == "bystander":
            continue
        stats["events"] += 1
        text = spoken_text(str(ev.get("text") or ""))
        if not text.strip():
            continue
        day = str(ev.get("date") or "")
        aid = str(ev.get("id") or "")
        mentions = []
        tags = ev.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        claims = extract_claims(text, mentions=mentions, db_path=db_path)
        # 大盤破／點位句補抽（他說過的價才記；不准發明）
        if _PATH_MARK.search(text) or _IDX_CTX_LOCAL.search(text):
            for extra in _extract_index_levels(text):
                claims.append(extra)
        if claims:
            for c in claims:
                c = dict(c)
                c["post_id"] = aid
                c["post_date"] = day
                c["kind"] = kind or "post"
                c["claim_key"] = c.get("claim_key") or "|".join(
                    [aid, str(c.get("stock_id") or ""), str(c.get("role") or ""),
                     _px_s(c.get("lo")), _px_s(c.get("hi"))]
                )
                rows = build_diverge_from_claim(db_path, c, bar_cache=cache)
                if rows:
                    built.extend(rows)
                    stats["claims"] += 1
        elif _PATH_MARK.search(text):
            # 無抽到數字點位，仍必須有大盤／走法下一步我說
            sid = "TWII"
            c = {
                "post_id": aid,
                "post_date": day,
                "stock_id": sid,
                "stock_name": "台指" if "台指" in text else "加權",
                "role": "path",
                "lo": None,
                "hi": None,
                "snippet": _clip(text, 110),
                "kind": kind or "post",
                "claim_key": f"{aid}|path|{_ymd(day)}",
            }
            rows = build_diverge_from_claim(db_path, c, bar_cache=cache)
            if rows:
                built.extend(rows)
                stats["path_only"] += 1
    stats["rows"] = record_diverge_rows(db_path, built)
    try:
        stats["scored"] = verify_diverge_due(db_path)
    except Exception:
        logger.exception("飆大分軌對質覆盤失敗")
        stats["scored"] = 0
    return stats


def record_from_claims(db_path: str, claims: Sequence[Dict[str, Any]]) -> int:
    """file_biaoke_claims 後補寫：每筆點位必有我說（現況＋下一版）。"""
    if not db_path or not claims:
        return 0
    cache: Dict[str, List[Dict[str, Any]]] = {}
    built: List[Dict[str, Any]] = []
    for c in claims:
        built.extend(build_diverge_from_claim(db_path, c, bar_cache=cache))
    return record_diverge_rows(db_path, built)


def verify_diverge_due(db_path: str, *, horizon: int = HORIZON_BARS) -> int:
    """官方柱走完 → 標他／我 對／偏／未完與 winner。不推話筒。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    ensure_biaoke_diverge_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        pending = conn.execute(
            """
            SELECT diverge_key, as_of, stock_id, role, his_lo, his_hi,
                   our_lo, our_hi, his_snippet, our_json
            FROM biaoke_diverge
            WHERE IFNULL(winner,'') IN ('', 'pending')
               OR IFNULL(his_verdict,'') IN ('', '未完')
               OR IFNULL(our_verdict,'') IN ('', '未完')
            """
        ).fetchall()
        cache: Dict[str, List[Dict[str, Any]]] = {}
        for key, as_of, sid, role, his_lo, his_hi, our_lo, our_hi, snip, our_json in pending:
            night = False
            try:
                meta = json.loads(our_json or "{}")
                night = bool(meta.get("night"))
                load_sid = str(meta.get("instrument") or sid or "TWII")
            except Exception:
                load_sid, night = _instrument(str(sid or ""), str(snip or ""))
            ck = f"{load_sid}:{'night' if night else 'day'}"
            if ck not in cache:
                cache[ck] = _load_bars(conn, load_sid, night=night)
            later = _later_bars(cache[ck], as_of, n=horizon)
            his_v = _judge_side(str(role or ""), his_lo, his_hi, later)
            our_v = _judge_side(str(role or ""), our_lo, our_hi, later)
            win = _winner(his_v, our_v)
            check_high = check_low = check_close = None
            if later:
                highs = [_num(b.get("high")) for b in later]
                lows = [_num(b.get("low")) for b in later]
                highs = [x for x in highs if x is not None]
                lows = [x for x in lows if x is not None]
                check_high = max(highs) if highs else None
                check_low = min(lows) if lows else None
                check_close = _num(later[-1].get("close"))
            conn.execute(
                """
                UPDATE biaoke_diverge SET
                    check_n=?, check_high=?, check_low=?, check_close=?,
                    his_verdict=?, our_verdict=?, winner=?, checked_at=?
                WHERE diverge_key=?
                """,
                (
                    len(later),
                    check_high,
                    check_low,
                    check_close,
                    his_v,
                    our_v,
                    win,
                    _now() if later else "",
                    key,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def snapshot_biaoke_diverge(market_db: str, as_of: str = "") -> int:
    """當日分軌列凍進 live_judge（輔助，不是選股勝率／買訊）。只凍現況軌。"""
    day = _ymd(as_of)
    if not day and market_db:
        try:
            from judge_tape import _as_of as jt_as_of

            day = _ymd(jt_as_of(market_db, as_of))
        except Exception:
            day = datetime.now(TAIPEI).strftime("%Y%m%d")
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    ensure_biaoke_diverge_table(market_db)
    try:
        from judge_tape import remember_rows
    except Exception:
        return 0
    conn = sqlite3.connect(market_db, timeout=8.0)
    try:
        hits = conn.execute(
            """
            SELECT diverge_key, stock_id, stock_name, role, his_lo, his_hi,
                   our_lo, our_hi, diverged, his_snippet, our_basis, our_path,
                   then_close, winner, his_verdict, our_verdict, variant
            FROM biaoke_diverge
            WHERE REPLACE(CAST(as_of AS TEXT),'-','')=?
              AND IFNULL(variant,'current')=?
            """,
            (day, VARIANT_CURRENT),
        ).fetchall()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    rows = []
    for (
        dk,
        sid,
        name,
        role,
        his_lo,
        his_hi,
        our_lo,
        our_hi,
        diverged,
        snip,
        basis,
        path,
        then_c,
        winner,
        his_v,
        our_v,
        variant,
    ) in hits:
        code = str(sid or "").strip() or f"_BKDV_{str(dk)[:20]}"
        if code in ("TWII", "TX") or not code.startswith("_"):
            if code in ("TWII", "TX") or len(code) > 6:
                code = f"_BKDV_{code}"[:32]
        rows.append(
            {
                "sid": code,
                "stock_id": code,
                "name": str(name or role or "分軌"),
                "px": _num(then_c) or _num(his_hi) or _num(our_hi),
                "close": _num(then_c) or _num(his_hi) or _num(our_hi),
                "lo": his_lo,
                "hi": his_hi,
                "our_lo": our_lo,
                "our_hi": our_hi,
                "diverged": int(diverged or 0),
                "snippet": _clip(str(snip or ""), 120),
                "our_basis": _clip(str(basis or ""), 120),
                "our_path": _clip(str(path or ""), 120),
                "winner": str(winner or ""),
                "his_verdict": str(his_v or ""),
                "our_verdict": str(our_v or ""),
                "claim_key": str(dk or "")[:80],
                "role": str(role or ""),
                "variant": str(variant or VARIANT_CURRENT),
            }
        )
    if not rows:
        return 0
    return int(
        remember_rows(
            market_db,
            "biaoke_diverge",
            rows,
            as_of=day,
            pick="rule",
            src="biaoke_dv",
        )
        or 0
    )


def refresh_rates(db_path: str) -> Dict[str, Any]:
    """重算各變體獨立交易日勝率。空列／未完不算。"""
    out: Dict[str, Any] = {}
    if not db_path or not os.path.isfile(db_path):
        return out
    ensure_biaoke_diverge_table(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        for variant in TRACK_VARIANTS:
            rows = conn.execute(
                """
                SELECT as_of, our_verdict, his_verdict
                FROM biaoke_diverge
                WHERE IFNULL(variant,'current')=?
                  AND IFNULL(our_verdict,'') NOT IN ('', '未完')
                  AND (our_lo IS NOT NULL OR our_hi IS NOT NULL
                       OR his_lo IS NOT NULL OR his_hi IS NOT NULL)
                """,
                (variant,),
            ).fetchall()
            days = sorted({_ymd(r[0]) for r in rows if _ymd(r[0])})
            # 空日不算：該日至少一列有真錨
            n_days = len(days)
            our_hit = sum(1 for r in rows if r[1] == "對")
            his_hit = sum(1 for r in rows if r[2] == "對")
            n_rows = len(rows)
            our_rate = (our_hit / n_rows) if n_rows else 0.0
            his_rate = (his_hit / n_rows) if n_rows else 0.0
            conn.execute(
                """
                INSERT OR REPLACE INTO biaoke_diverge_rates(
                    variant, n_days, n_rows, our_hit, his_hit, our_rate, his_rate, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    variant,
                    n_days,
                    n_rows,
                    our_hit,
                    his_hit,
                    our_rate,
                    his_rate,
                    _now(),
                ),
            )
            out[variant] = {
                "n_days": n_days,
                "n_rows": n_rows,
                "our_hit": our_hit,
                "his_hit": his_hit,
                "our_rate": our_rate,
                "his_rate": his_rate,
            }
        conn.commit()
    finally:
        conn.close()
    return out


def gate_status(db_path: str) -> Dict[str, Any]:
    """明確優化狀態：n 夠不夠、下一版有沒有贏該軌現況、要不要換碼。

    未過閘＝不改買訊、不進話筒。過程％不准進對話。
    """
    rates = refresh_rates(db_path) if db_path else {}
    cur = rates.get(VARIANT_CURRENT) or {}
    nxt = rates.get(VARIANT_NEXT) or {}
    n = int(nxt.get("n_days") or 0)
    # 用下一版獨立日數當閘（與現況同窗收）；兩邊都要有列
    n_cur = int(cur.get("n_days") or 0)
    n_ok = n >= MIN_UNIQUE_DAYS and n_cur >= MIN_UNIQUE_DAYS
    cur_rate = float(cur.get("our_rate") or 0)
    next_rate = float(nxt.get("our_rate") or 0)
    # 空不算：n_rows=0 → 不准過閘
    has_rows = int(cur.get("n_rows") or 0) > 0 and int(nxt.get("n_rows") or 0) > 0
    beats = bool(n_ok and has_rows and next_rate > cur_rate)
    return {
        "n_days": n,
        "n_current": n_cur,
        "n_ok": n_ok,
        "min_n": MIN_UNIQUE_DAYS,
        "current_our_rate": cur_rate,
        "next_our_rate": next_rate,
        "current_his_rate": float(cur.get("his_rate") or 0),
        "promote_ready": beats,
        "has_rows": has_rows,
        "note": (
            "下一版贏該軌現況且 n≥20 → 換該軌編碼並再生下一版；未過閘不改買訊／不進話筒"
            if beats
            else "繼續收集／尚未改碼；空列不算"
        ),
    }


def promote_if_ready(db_path: str) -> Dict[str, Any]:
    """§13：下一版贏現況 → 換該軌編碼，並再生下一版候選。不准改買訊／話筒。"""
    out: Dict[str, Any] = {"promoted": False, "gate": {}}
    if not db_path:
        return out
    g = gate_status(db_path)
    out["gate"] = g
    if not g.get("promote_ready"):
        return out
    rules = load_rules(db_path)
    cur = rules.get(VARIANT_CURRENT) or dict(_DEFAULT_RULES[VARIANT_CURRENT])
    nxt = rules.get(VARIANT_NEXT) or dict(_DEFAULT_RULES[VARIANT_NEXT])
    new_gen = int(nxt.get("gen") or 1) + 0
    # 下一版參數升成現況
    promoted = {
        "lookback": int(nxt.get("lookback") or LOOKBACK_DEFAULT),
        "swing": int(nxt.get("swing") or SWING_DEFAULT),
        "label": str(nxt.get("label") or "升現況"),
        "gen": int(nxt.get("gen") or 1),
    }
    # 再生下一版：swing 交替 5↔10↔15（可重算窗），lookback 維持 20
    swing_cycle = (5, 10, 15)
    try:
        idx = swing_cycle.index(int(promoted["swing"]))
        next_swing = swing_cycle[(idx + 1) % len(swing_cycle)]
    except ValueError:
        next_swing = 10 if int(promoted["swing"]) != 10 else 5
    regenerated = {
        "lookback": int(promoted["lookback"]),
        "swing": int(next_swing),
        "label": f"近{next_swing}窗錨",
        "gen": int(promoted["gen"]) + 1,
    }
    ensure_biaoke_diverge_table(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        now = _now()
        conn.execute(
            """
            INSERT OR REPLACE INTO biaoke_diverge_rules
            (variant, lookback, swing, label, gen, active, updated_at)
            VALUES (?,?,?,?,?,1,?)
            """,
            (
                VARIANT_CURRENT,
                promoted["lookback"],
                promoted["swing"],
                promoted["label"],
                promoted["gen"],
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO biaoke_diverge_rules
            (variant, lookback, swing, label, gen, active, updated_at)
            VALUES (?,?,?,?,?,1,?)
            """,
            (
                VARIANT_NEXT,
                regenerated["lookback"],
                regenerated["swing"],
                regenerated["label"],
                regenerated["gen"],
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    out["promoted"] = True
    out["from"] = cur
    out["to"] = promoted
    out["next"] = regenerated
    out["prev_gen_note"] = new_gen
    return out


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """盤後節奏：覆盤分軌＋凍 live_judge＋§13 閘。失敗吞掉；不推話筒、不改買訊。"""
    out: Dict[str, Any] = {
        "scored": 0,
        "snapshot": 0,
        "gate": {},
        "promoted": False,
    }
    if not db_path:
        return out
    try:
        out["scored"] = verify_diverge_due(db_path)
        out["snapshot"] = snapshot_biaoke_diverge(db_path, as_of=as_of)
        promo = promote_if_ready(db_path)
        out["gate"] = promo.get("gate") or gate_status(db_path)
        out["promoted"] = bool(promo.get("promoted"))
        if out["promoted"]:
            out["promo"] = {k: promo.get(k) for k in ("to", "next") if k in promo}
    except Exception:
        logger.exception("飆大分軌 night_tick 失敗")
    return out


def optimize_status_one_liner(db_path: str) -> str:
    """唯一准講的一句明確優化狀態。"""
    g = gate_status(db_path)
    n = int(g.get("n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if g.get("promote_ready"):
        return (
            f"明確優化狀態：分軌 n={n} 夠且下一版贏現況 → 已／可換該軌編碼並再生下一版；"
            "未改買訊、不進話筒。"
        )
    if not g.get("n_ok"):
        return (
            f"明確優化狀態：分軌 n={n}/{need} 不夠，繼續收集／尚未改碼。"
        )
    return (
        f"明確優化狀態：分軌 n={n} 夠但下一版未贏現況，不改碼。"
    )
