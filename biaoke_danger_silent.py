# -*- coding: utf-8 -*-
"""飆大危險時段靜默對質。只屬於飆大按鍵。

層級：飆大抓文之後的靜默對質，不在話筒買訊、不在黃金買點。
新鍵 ``biaoke_danger_window``。表 ``biaoke_danger_window``／``biaoke_danger_rules``
跟海選、查股、洞燭、大盤環境、AI倉、情境預估、壓撐、他說我說分軌分開。
那些功能不准讀這張表。

現在只建檔開收集。獨立交易日 n≥20 且下一版贏這一軌現況才換編碼；
換的時候候選已經在同一張表。不准提前改黃金買點、不准改話筒買訊。
空判斷不算有記。時區 Asia/Taipei。盤中未收不當收。不是買訊。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
TRACK_KEY = "biaoke_danger_window"
POST_ID = "185962404"
AS_OF = "2026-10-16"
VARIANT_CURRENT = "current"
VARIANT_NEXT = "next"
MIN_UNIQUE_DAYS = 20

LIANYA_LINE = (
    "有人問全部清光是否也包含聯亞，他澄清聯亞還在；"
    "清的是持股，含台積電 2200，不是聯亞。"
)
JUDGMENT = (
    "下週起應該會殺兩週左右。"
    "23:12 他說應該差不多兩周就結束。"
    "10:50 和 17:25 都說還有兩段要跌，現在只是 C-3-4，不是 C-4。"
    "台指期反彈沒過 48240 就當誘多，仍偏空。"
    "現金至少五成、最好七成，後來現金超過九成。"
    "這段 C 波不一定破七月下旬低點，約 39000。"
    + LIANYA_LINE
)

# 只列他 10/16 主文＋自回講過的。不准加他沒點過的工具。
PRINCIPLES: Tuple[str, ...] = (
    "台指期反彈沒過 48240 就當誘多，仍偏空",
    "不看均線，尤其季線有支撐",
    "大盤帶量跌破支撐就先走",
    "現金至少五成、最好七成，後來超過九成",
    "波浪只服務這段大盤判斷",
)
TOOLS: Tuple[str, ...] = (
    "台指期",
    "創意當風向",
    "量能跌破就走",
    "現金比例",
    "波浪（只服務這段大盤判斷）",
    "均線／季線（他說不要看，尤其季線撐）",
)
NAMED_PRICES: Tuple[Dict[str, Any], ...] = (
    {"series": "TX", "name": "台指期", "px": 48240, "role": "沒過就當誘多"},
    {"series": "TWII", "name": "加權", "px": 39000, "role": "C波不一定破"},
    {"series": "2330", "name": "台積電", "px": 2200, "role": "清光持股含這價，不是聯亞"},
)

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_danger_window (
    danger_key TEXT PRIMARY KEY,
    track_key TEXT NOT NULL,
    variant TEXT NOT NULL,
    as_of TEXT NOT NULL,
    post_id TEXT NOT NULL,
    judgment TEXT NOT NULL,
    prices_json TEXT NOT NULL,
    bars_json TEXT NOT NULL,
    principles_json TEXT NOT NULL,
    tools_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'collecting',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_biaoke_danger_asof
    ON biaoke_danger_window(as_of, variant);
CREATE TABLE IF NOT EXISTS biaoke_danger_rules (
    variant TEXT PRIMARY KEY,
    track_key TEXT NOT NULL,
    label TEXT NOT NULL,
    rule_note TEXT NOT NULL,
    gen INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

_RULES = (
    (
        VARIANT_CURRENT,
        "當日高低有沒有碰到他點過的價",
        "現況。只對這段危險時段。不是買訊。",
        1,
    ),
    (
        VARIANT_NEXT,
        "收盤有沒有站回他點過的價",
        "下一版候選。現在只收集，n 不夠不准換編碼。",
        0,
    ),
)


def _now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(TAIPEI)
    if now.tzinfo is None:
        return now.replace(tzinfo=TAIPEI)
    return now.astimezone(TAIPEI)


def _stamp(now: Optional[datetime] = None) -> str:
    return _now(now).strftime("%Y-%m-%d %H:%M:%S")


def _iso(ymd: str) -> str:
    s = str(ymd or "").replace("-", "")[:8]
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(ymd or "")


def _ymd(raw: str) -> str:
    return str(raw or "").replace("-", "")[:8]


def _closed(date_iso: str, now: Optional[datetime] = None) -> bool:
    """盤中未收不當官方收。日盤 13:45 台北之後才算當日已收。"""
    dt = _now(now)
    today = dt.strftime("%Y-%m-%d")
    if date_iso < today:
        return True
    if date_iso > today:
        return False
    return (dt.hour, dt.minute) >= (13, 45)


def _fmt_px(val: Any) -> str:
    try:
        x = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _touch(high: float, low: float, px: float) -> str:
    p = _fmt_px(px)
    if low <= px <= high:
        return f"這根高低包住他說的{p}"
    if high < px:
        return f"高還沒到他說的{p}"
    return f"低還在他說的{p}之上"


def is_danger_main(row: Optional[Dict[str, Any]]) -> bool:
    if not row:
        return False
    aid = str(row.get("id") or row.get("post_id") or "")
    return aid == POST_ID or aid.endswith(":" + POST_ID) or POST_ID in aid.split(":")


def ensure_biaoke_danger_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.executescript(_DDL)
        ts = _stamp()
        for variant, label, note, active in _RULES:
            conn.execute(
                "INSERT OR IGNORE INTO biaoke_danger_rules"
                "(variant, track_key, label, rule_note, gen, active, updated_at)"
                " VALUES(?,?,?,?,1,?,?)",
                (variant, TRACK_KEY, label, note, int(active), ts),
            )
        conn.commit()
    finally:
        conn.close()


def _bar_on(
    db_path: str,
    series: str,
    as_of: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """當日完整開高低收才算已收。沒有、缺欄、或還沒收，都不拿別日來填。"""
    iso = _iso(as_of)
    ymd = _ymd(as_of)
    out: Dict[str, Any] = {
        "series": series,
        "date": iso,
        "status": "missing",
        "note": "缺完整官方開高低收",
    }
    if not db_path or not os.path.isfile(db_path):
        return out
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return out
    try:
        if series == "TX":
            row = conn.execute(
                "SELECT date, open, high, low, close, volume FROM futures_daily "
                "WHERE symbol='TX' AND session='regular' "
                "AND replace(date,'-','')=? "
                "AND open IS NOT NULL AND high IS NOT NULL "
                "AND low IS NOT NULL AND close IS NOT NULL",
                (ymd,),
            ).fetchone()
        elif series == "TWII":
            row = conn.execute(
                "SELECT date, open, high, low, close, volume FROM index_daily "
                "WHERE symbol='TWII' AND replace(date,'-','')=? "
                "AND open IS NOT NULL AND high IS NOT NULL "
                "AND low IS NOT NULL AND close IS NOT NULL",
                (ymd,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT date, open, high, low, close, volume FROM daily_quotes "
                "WHERE stock_id=? AND replace(date,'-','')=? "
                "AND open IS NOT NULL AND high IS NOT NULL "
                "AND low IS NOT NULL AND close IS NOT NULL",
                (series, ymd),
            ).fetchone()
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    if not row:
        return out
    if not _closed(iso, now):
        return {
            "series": series,
            "date": iso,
            "status": "unclosed",
            "note": "盤中未收，不當官方收",
        }
    try:
        bar = {
            "series": series,
            "date": iso,
            "status": "closed",
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": row[5],
        }
    except (TypeError, ValueError):
        return out
    return bar


def official_lines(
    db_path: str,
    as_of: str = AS_OF,
    *,
    now: Optional[datetime] = None,
) -> List[str]:
    lines: List[str] = []
    for spec in NAMED_PRICES:
        bar = _bar_on(db_path, str(spec["series"]), as_of, now=now)
        name = str(spec["name"])
        iso = _iso(as_of)
        if bar.get("status") != "closed":
            note = str(bar.get("note") or "缺完整官方開高低收")
            lines.append(f"官方柱：{name}{iso}{note}。")
            continue
        sess = "日盤" if spec["series"] == "TX" else ""
        vol = bar.get("volume")
        vol_txt = _fmt_px(vol) if vol not in (None, "") else ""
        vol_bit = f" 量{vol_txt}" if vol_txt and vol_txt != "0" else ""
        touch = _touch(float(bar["high"]), float(bar["low"]), float(spec["px"]))
        lines.append(
            f"官方柱：{name}{iso}{sess} "
            f"開{_fmt_px(bar['open'])} 高{_fmt_px(bar['high'])} "
            f"低{_fmt_px(bar['low'])} 收{_fmt_px(bar['close'])}{vol_bit}，"
            f"{touch}。"
        )
    return lines


def bars_payload(
    db_path: str,
    as_of: str = AS_OF,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    rows = []
    for spec in NAMED_PRICES:
        bar = dict(_bar_on(db_path, str(spec["series"]), as_of, now=now))
        bar["name"] = spec["name"]
        bar["px"] = spec["px"]
        rows.append(bar)
    return rows


def _norm(text: str) -> str:
    return "".join(str(text or "").split())


def _contained(bit: str, blobs: Sequence[str]) -> bool:
    n = _norm(bit)
    if len(n) < 12:
        return False
    for s in blobs:
        t = _norm(s)
        if t and n in t:
            return True
    return False


def _drop_other_day_index(official: Sequence[str], as_of: str) -> List[str]:
    """這段點過的台指期／加權／台積電，不准拿別日的柱填當日。"""
    iso = _iso(as_of)
    kept: List[str] = []
    for line in official:
        text = str(line or "")
        if any(name in text for name in ("台指期", "加權", "台積電")) and iso not in text:
            continue
        kept.append(text)
    return kept


def apply_danger_window(
    latest: Dict[str, Any],
    chunks: Sequence[str],
    official: Sequence[str],
    db_path: str = "",
    *,
    now: Optional[datetime] = None,
) -> Tuple[List[str], List[str]]:
    """最新主文是 10/16 這篇才把重組句放進黃金脈絡，並寫進飆大自己的表。"""
    chunks_l = [str(x) for x in chunks if str(x or "").strip()]
    official_l = [str(x) for x in official if str(x or "").strip()]
    if not is_danger_main(latest):
        return chunks_l, official_l
    speech = JUDGMENT
    kept = [c for c in chunks_l if not _contained(c, [speech])]
    fresh_official = official_lines(db_path, AS_OF, now=now)
    official_l = _drop_other_day_index(official_l, AS_OF)
    seen = {_norm(x) for x in official_l}
    for line in fresh_official:
        if _norm(line) not in seen:
            official_l.append(line)
            seen.add(_norm(line))
    if db_path:
        try:
            record_danger_window(db_path, now=now)
        except Exception:
            pass
    return [speech] + kept, official_l


def record_danger_window(
    db_path: str,
    *,
    as_of: str = AS_OF,
    post_id: str = POST_ID,
    now: Optional[datetime] = None,
) -> int:
    """同一日同一規則只留一列。空判斷不寫。不碰別的表。"""
    if not db_path or not JUDGMENT.strip() or not NAMED_PRICES:
        return 0
    ensure_biaoke_danger_table(db_path)
    bars = bars_payload(db_path, as_of, now=now)
    prices = [dict(p) for p in NAMED_PRICES]
    ts = _stamp(now)
    ymd = _ymd(as_of)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        n = 0
        for variant in (VARIANT_CURRENT, VARIANT_NEXT):
            key = f"{ymd}|{post_id}|{variant}"
            prev = conn.execute(
                "SELECT created_at FROM biaoke_danger_window WHERE danger_key=?",
                (key,),
            ).fetchone()
            created = str(prev[0]) if prev and prev[0] else ts
            conn.execute(
                "INSERT OR REPLACE INTO biaoke_danger_window("
                "danger_key, track_key, variant, as_of, post_id, judgment,"
                "prices_json, bars_json, principles_json, tools_json,"
                "status, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    TRACK_KEY,
                    variant,
                    ymd,
                    post_id,
                    JUDGMENT,
                    json.dumps(prices, ensure_ascii=False),
                    json.dumps(bars, ensure_ascii=False),
                    json.dumps(list(PRINCIPLES), ensure_ascii=False),
                    json.dumps(list(TOOLS), ensure_ascii=False),
                    "collecting",
                    created,
                    ts,
                ),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def record_from_events(
    db_path: str,
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> int:
    """飆大抓文之後才寫。批次裡沒有這篇主文就不記。"""
    hit = False
    for ev in events or []:
        blob = " ".join(
            str(ev.get(k) or "")
            for k in ("id", "post_id", "parent")
        )
        if POST_ID in blob:
            hit = True
            break
    if not hit:
        return 0
    return record_danger_window(db_path, now=now)


def collected_days(db_path: str) -> int:
    if not db_path or not os.path.isfile(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return 0
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "biaoke_danger_window" not in names:
            return 0
        row = conn.execute(
            "SELECT COUNT(DISTINCT as_of) FROM biaoke_danger_window "
            "WHERE track_key=? AND variant=? "
            "AND trim(judgment)!='' AND prices_json NOT IN ('', '[]')",
            (TRACK_KEY, VARIANT_CURRENT),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def replace_if_gated(db_path: str) -> Dict[str, Any]:
    """n 不夠、或下一版還沒贏現況，就不換。這支也不寫黃金買點。"""
    n = collected_days(db_path)
    out = {
        "replaced": False,
        "n": n,
        "track_key": TRACK_KEY,
        "reason": "collecting",
    }
    if n < MIN_UNIQUE_DAYS:
        out["reason"] = "n_short"
        return out
    out["reason"] = "not_ahead"
    return out
