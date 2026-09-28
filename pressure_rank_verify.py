# -*- coding: utf-8 -*-
"""壓撐觀察・排序靜默對質（不是買訊）。

主線（改碼候選只認這條）：
  A 現況碼：離壓近 → 量縮加分 → 代號；截 12
  B 第一次優化：三鈕不同「強」定義＋順序（見 rank_key_first）
  再擠：暫不開改碼候選（缺獨立掃檔證明能贏 B）

另軌（只靜默／之後，不准當現階段改碼候選、不准建議上話筒）：
  biaoke_silent：第一次優化主鍵上再疊飆大硬砍／加分、截 5～8

結構門檻不動（N=2／≤0.5%／W=5）。未過 n≥20 獨立交易日且贏現況 → 不准改話筒。
失敗不准打斷出卡／海選。過程／％不准進對話。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from pressure_support_watch import (
    MAX_ROWS,
    TAG_ORDER,
    TAG_SIDEWAYS,
    TAG_STAND_SUPPORT,
    TAG_TEST_PRESS,
    collect_pressure_pool,
    normalize_tag,
    rank_key_current,
)

KIND = "pressure_rank"
VARIANT_CURRENT = "current"
VARIANT_FIRST = "first"  # 第一次優化＝勝率優化層
VARIANT_BIAOKE_SILENT = "biaoke_silent"  # 只靜默／之後
PROMOTE_VARIANTS = (VARIANT_CURRENT, VARIANT_FIRST)
SILENT_ONLY_VARIANTS = (VARIANT_BIAOKE_SILENT,)
FORWARD_H = 5
# 剛站上撐「離壓適中」錨：離壓約 2%（太貼像又測壓；太遠像半山／區外）
STAND_MODERATE_DIST_ANCHOR = 2.0
BIAOKE_TOP_LO = 5
BIAOKE_TOP_HI = 8
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _num(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _thin(r: Dict[str, Any]) -> int:
    """量縮加分：相對爆大量日量比 <0.35 → 0（較前），否則 1。"""
    if r.get("vol_thin_bonus"):
        return 0
    vr = _num(r.get("vol_ratio"), 99.0)
    return 0 if 0 < vr < 0.35 else 1


def rank_key_first(tag: str, r: Dict[str, Any]) -> Tuple[Any, ...]:
    """第一次優化建議（鎖死原文・可重跑）。

    1. 壓力橫盤：量縮加分 → 離壓近 → 代號
       強＝還在區裡、量縮、收偏區上緣（離壓近但不破）
    2. 測壓未破：離壓近 → 量縮 → 代號
       強＝真貼壓、收仍守、最好量縮
    3. 剛站上撐：收在〔撐,壓〕內 → 離壓適中 → 量比 → 代號
       強＝站穩後收往區內、離壓還有空間、量溫和
       離壓適中＝|離壓％ − 2.0| 愈小愈前（太貼壓像又要測壓）
    """
    tag = normalize_tag(tag) or str(tag or "")
    sid = str(r.get("stock_id") or r.get("code") or "")
    dist = _num(r.get("dist_to_press_pct"), 99.0)
    thin = _thin(r)
    vr = _num(r.get("vol_ratio"), 99.0)
    if vr <= 0:
        vr = 99.0
    if tag == TAG_SIDEWAYS:
        return (thin, dist, sid)
    if tag == TAG_TEST_PRESS:
        return (dist, thin, sid)
    # stand_support
    press = _num(r.get("pressure"))
    support = _num(r.get("support"))
    close = _num(r.get("close"))
    in_band = 0 if (support > 0 and press > 0 and support <= close <= press) else 1
    moderate = abs(dist - STAND_MODERATE_DIST_ANCHOR)
    return (in_band, moderate, vr, sid)


def biaoke_hard_cut(r: Dict[str, Any], tag: str) -> bool:
    """飆大草案硬砍（只靜默軌）。砍＝True 不進起手。"""
    if r.get("dump_pause") or r.get("half_mountain") or r.get("chase_no_consol"):
        return True
    # 關前空手：近史高且無 wash／窒息
    if r.get("near_hist_high") and not (r.get("wash") or r.get("vol_asphyx")):
        return True
    # 死水無長紅語感：極縮量＋轉弱Ｋ（測壓／站上撐才砍；橫盤安靜是優點）
    if tag != TAG_SIDEWAYS and r.get("dead_weak"):
        return True
    return False


def biaoke_score(r: Dict[str, Any]) -> float:
    """飆大草案加分（只靜默軌）；分數愈高愈前。"""
    s = 0.0
    if r.get("vol_asphyx"):
        s += 3.0
    if not r.get("weak_k"):
        s += 1.5
    if r.get("wash"):
        s += 2.0
    if r.get("attack_vol"):
        s += 2.5
    # 龍頭位階：無官方可重述欄就不加（不准假資料）
    return s


def rank_pool(
    pool: Sequence[Dict[str, Any]],
    tag: str,
    variant: str,
) -> List[Dict[str, Any]]:
    """同一資格池 → 依變體排序並截斷。不改結構門檻。"""
    tag = normalize_tag(tag) or str(tag or "")
    rows = [dict(r) for r in pool if isinstance(r, dict)]
    variant = str(variant or "").strip()
    if variant == VARIANT_CURRENT:
        rows.sort(key=rank_key_current)
        return rows[:MAX_ROWS]
    if variant == VARIANT_FIRST:
        rows.sort(key=lambda r: rank_key_first(tag, r))
        return rows[:MAX_ROWS]
    if variant == VARIANT_BIAOKE_SILENT:
        kept = [r for r in rows if not biaoke_hard_cut(r, tag)]
        # 主鍵仍是第一次優化；同分再用飆大加分（降序）
        kept.sort(
            key=lambda r: (
                rank_key_first(tag, r),
                -biaoke_score(r),
                str(r.get("stock_id") or ""),
            )
        )
        top = min(BIAOKE_TOP_HI, max(BIAOKE_TOP_LO, 6))
        # 不准湊滿：合格不足就少秀
        n = min(top, len(kept))
        if n < BIAOKE_TOP_LO:
            n = len(kept)
        return kept[:n]
    return []


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pressure_rank_tape (
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                tag TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                rank_i INTEGER NOT NULL,
                name TEXT DEFAULT '',
                close REAL,
                pressure REAL,
                support REAL,
                vol_ratio REAL,
                dist_to_press_pct REAL,
                extra TEXT DEFAULT '',
                PRIMARY KEY (kind, variant, tag, as_of, sid)
            );
            CREATE TABLE IF NOT EXISTS pressure_rank_score (
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                tag TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL,
                hold_support INTEGER NOT NULL DEFAULT 0,
                stand_press INTEGER NOT NULL DEFAULT 0,
                broke_support INTEGER NOT NULL DEFAULT 0,
                fwd_pct REAL,
                win INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, variant, tag, as_of, sid, horizon)
            );
            CREATE TABLE IF NOT EXISTS pressure_rank_rates (
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n_days INTEGER NOT NULL,
                n_rows INTEGER NOT NULL,
                win_rate REAL,
                hold_support_rate REAL,
                stand_press_rate REAL,
                avg_fwd_pct REAL,
                PRIMARY KEY (kind, variant, tag, horizon)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return store


def _quote_dates(db_path: str, up_to: str) -> List[str]:
    day = _ymd(up_to)
    if not db_path or not os.path.isfile(db_path) or not day:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT replace(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE close>0 AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY d
            """,
            (day,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def _forward_bars(
    db_path: str, sid: str, as_of: str, horizon: int
) -> Tuple[str, List[Dict[str, float]]]:
    """回傳 (check_as_of, bars[1..horizon])；柱不足則 check 空。"""
    dates = _quote_dates(db_path, "99991231")
    by_i = {d: i for i, d in enumerate(dates)}
    as_of = _ymd(as_of)
    if as_of not in by_i:
        return "", []
    start = by_i[as_of]
    want = start + int(horizon)
    if want >= len(dates):
        return "", []
    check = dates[want]
    window = dates[start + 1 : want + 1]
    if len(window) < int(horizon):
        return "", []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT replace(CAST(date AS TEXT),'-',''), close, high, low
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')>?
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY 1
            """,
            (sid, as_of, check),
        ).fetchall()
        if len(rows) < int(horizon):
            rows = conn.execute(
                """
                SELECT replace(CAST(date AS TEXT),'-',''), close, high, low
                FROM emerging_quotes
                WHERE stock_id=? AND close>0
                  AND replace(CAST(date AS TEXT),'-','')>?
                  AND replace(CAST(date AS TEXT),'-','')<=?
                ORDER BY 1
                """,
                (sid, as_of, check),
            ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    bars = []
    for d, c, h, l in rows:
        bars.append(
            {
                "date": _ymd(d),
                "close": _num(c),
                "high": _num(h),
                "low": _num(l),
            }
        )
    if len(bars) < int(horizon):
        return "", []
    return check, bars[: int(horizon)]


def outcome_win(
    tag: str,
    *,
    pressure: float,
    support: float,
    entry: float,
    bars: Sequence[Dict[str, float]],
) -> Dict[str, Any]:
    """前瞻窗怎麼算贏（官方已收柱；盤中未收不當收）。

    窗＝後續 FORWARD_H 個交易日。
    - 橫盤主判：窗內任一日收 > 壓（站上壓）
    - 測壓／剛站上撐主判：窗內每日收 ≥ 撐（守撐）
    另記破撐、fwd_pct（第 H 根收／進場收）。
    """
    tag = normalize_tag(tag) or str(tag or "")
    closes = [_num(b.get("close")) for b in bars if _num(b.get("close")) > 0]
    hold = bool(closes) and support > 0 and all(c >= support for c in closes)
    broke = bool(closes) and support > 0 and any(c < support for c in closes)
    stand = bool(closes) and pressure > 0 and any(c > pressure for c in closes)
    last = closes[-1] if closes else 0.0
    fwd = round((last / entry - 1.0) * 100.0, 4) if entry > 0 and last > 0 else None
    if tag == TAG_SIDEWAYS:
        win = 1 if stand else 0
    else:
        win = 1 if hold else 0
    return {
        "hold_support": 1 if hold else 0,
        "stand_press": 1 if stand else 0,
        "broke_support": 1 if broke else 0,
        "fwd_pct": fwd,
        "win": win,
    }


def persist_ranked(
    db_path: str,
    as_of: str,
    tag: str,
    variant: str,
    rows: Sequence[Dict[str, Any]],
) -> int:
    store = ensure_tables(db_path)
    day = _ymd(as_of)
    tag = normalize_tag(tag) or str(tag or "")
    variant = str(variant or "").strip()
    if not day or not tag or not variant:
        return 0
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        conn.execute(
            "DELETE FROM pressure_rank_tape WHERE kind=? AND variant=? AND tag=? AND as_of=?",
            (KIND, variant, tag, day),
        )
        for i, raw in enumerate(rows):
            sid = str(raw.get("stock_id") or raw.get("code") or "").strip()
            if not sid:
                continue
            extra = {
                k: raw.get(k)
                for k in (
                    "vol_thin_bonus",
                    "weak_k",
                    "wash",
                    "dump_pause",
                    "half_mountain",
                    "attack_vol",
                    "why",
                )
                if raw.get(k) not in (None, "", [], {})
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO pressure_rank_tape(
                    kind, variant, tag, as_of, sid, rank_i, name, close,
                    pressure, support, vol_ratio, dist_to_press_pct, extra
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    variant,
                    tag,
                    day,
                    sid,
                    i + 1,
                    str(raw.get("stock_name") or raw.get("name") or "")[:40],
                    _num(raw.get("close"), None) if raw.get("close") is not None else None,
                    _num(raw.get("pressure"), None) if raw.get("pressure") is not None else None,
                    _num(raw.get("support"), None) if raw.get("support") is not None else None,
                    _num(raw.get("vol_ratio"), None) if raw.get("vol_ratio") is not None else None,
                    _num(raw.get("dist_to_press_pct"), None)
                    if raw.get("dist_to_press_pct") is not None
                    else None,
                    json.dumps(extra, ensure_ascii=False) if extra else "",
                ),
            )
            n += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return n


def score_pending(db_path: str, cap: str = "") -> int:
    """官方柱走完才填 FORWARD_H 對質。未收不當收。"""
    store = ensure_tables(db_path)
    day = _ymd(cap)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not day:
        return 0
    conn = sqlite3.connect(store, timeout=30.0)
    conn.row_factory = sqlite3.Row
    filled = 0
    try:
        rows = conn.execute(
            "SELECT variant, tag, as_of, sid, close, pressure, support FROM pressure_rank_tape WHERE kind=?",
            (KIND,),
        ).fetchall()
        scored = {
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]), int(r[4]))
            for r in conn.execute(
                "SELECT variant, tag, as_of, sid, horizon FROM pressure_rank_score WHERE kind=?",
                (KIND,),
            )
        }
        for row in rows:
            as_of = _ymd(row["as_of"])
            sid = str(row["sid"] or "")
            key = (str(row["variant"]), str(row["tag"]), as_of, sid, FORWARD_H)
            if key in scored or not sid or not as_of:
                continue
            check, bars = _forward_bars(db_path, sid, as_of, FORWARD_H)
            if not check or check > day or not bars:
                continue
            entry = _num(row["close"])
            if entry <= 0:
                continue
            out = outcome_win(
                str(row["tag"]),
                pressure=_num(row["pressure"]),
                support=_num(row["support"]),
                entry=entry,
                bars=bars,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO pressure_rank_score(
                    kind, variant, tag, as_of, sid, horizon, check_as_of,
                    hold_support, stand_press, broke_support, fwd_pct, win
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    str(row["variant"]),
                    str(row["tag"]),
                    as_of,
                    sid,
                    FORWARD_H,
                    check,
                    out["hold_support"],
                    out["stand_press"],
                    out["broke_support"],
                    out["fwd_pct"],
                    out["win"],
                ),
            )
            filled += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    if filled:
        recompute_rates(db_path)
    return filled


def recompute_rates(db_path: str) -> None:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute("DELETE FROM pressure_rank_rates WHERE kind=?", (KIND,))
        rows = conn.execute(
            """
            SELECT variant, tag, horizon,
                   COUNT(DISTINCT as_of) AS n_days,
                   COUNT(*) AS n_rows,
                   AVG(win) AS win_rate,
                   AVG(hold_support) AS hold_support_rate,
                   AVG(stand_press) AS stand_press_rate,
                   AVG(fwd_pct) AS avg_fwd_pct
            FROM pressure_rank_score
            WHERE kind=?
            GROUP BY variant, tag, horizon
            """,
            (KIND,),
        ).fetchall()
        for variant, tag, hz, n_days, n_rows, wr, hs, sp, af in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO pressure_rank_rates(
                    kind, variant, tag, horizon, n_days, n_rows,
                    win_rate, hold_support_rate, stand_press_rate, avg_fwd_pct
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    str(variant),
                    str(tag),
                    int(hz),
                    int(n_days or 0),
                    int(n_rows or 0),
                    float(wr or 0),
                    float(hs or 0),
                    float(sp or 0),
                    float(af or 0) if af is not None else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def snapshot_day(db_path: str, as_of: str = "", *, enrich_biaoke: bool = True) -> Dict[str, int]:
    """盤後默默落三軌排名（同一資格池）。失敗回空，不准擋主流程。"""
    stats: Dict[str, int] = {}
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not db_path or not day:
        return stats
    try:
        ensure_tables(db_path)
        for tag in TAG_ORDER:
            pool = collect_pressure_pool(
                db_path, tag, as_of=day, enrich=bool(enrich_biaoke)
            )
            for variant in (VARIANT_CURRENT, VARIANT_FIRST, VARIANT_BIAOKE_SILENT):
                ranked = rank_pool(pool, tag, variant)
                key = f"{variant}_{tag}"
                stats[key] = persist_ranked(db_path, day, tag, variant, ranked)
    except Exception:
        return stats
    return stats


def unique_days(db_path: str, variant: str = VARIANT_FIRST) -> int:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT as_of) FROM pressure_rank_score
            WHERE kind=? AND variant=? AND horizon=?
            """,
            (KIND, variant, FORWARD_H),
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def gate_status(db_path: str) -> Dict[str, Any]:
    """明確優化狀態：n 夠不夠、誰贏現況、要不要改碼。

    只比較 PROMOTE_VARIANTS（現況 vs 第一次）。biaoke_silent 永不 promote。
    """
    store = ensure_tables(db_path)
    by: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT variant, tag, n_days, win_rate, hold_support_rate, stand_press_rate
            FROM pressure_rank_rates
            WHERE kind=? AND horizon=?
            """,
            (KIND, FORWARD_H),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for variant, tag, n_days, wr, hs, sp in rows:
        by.setdefault(str(variant), {})[str(tag)] = {
            "n_days": int(n_days or 0),
            "win_rate": float(wr or 0),
            "hold_support_rate": float(hs or 0),
            "stand_press_rate": float(sp or 0),
        }

    def _mean_win(variant: str) -> Optional[float]:
        block = by.get(variant) or {}
        if not block:
            return None
        vals = [float(v.get("win_rate") or 0) for v in block.values()]
        return sum(vals) / len(vals) if vals else None

    n = unique_days(db_path, VARIANT_FIRST)
    n_ok = n >= MIN_UNIQUE_DAYS
    cur = _mean_win(VARIANT_CURRENT)
    first = _mean_win(VARIANT_FIRST)
    beats = bool(n_ok and cur is not None and first is not None and first > cur)
    # 再擠：現階段不開
    squeeze_open = False
    promote = bool(beats and squeeze_open is False and first is not None)
    # 只有第一次贏現況且 n 夠才「可考慮改碼」；仍須人工／專件才改話筒
    return {
        "n_days": n,
        "n_ok": n_ok,
        "min_n": MIN_UNIQUE_DAYS,
        "current_win": cur,
        "first_win": first,
        "first_beats_current": beats,
        "biaoke_silent_only": True,
        "squeeze_candidate": False,
        "promote_ready": promote,
        "note": (
            "第一次優化贏現況且 n 夠 → 可考慮只改排序鍵（另開專件）；未改買訊"
            if promote
            else "繼續收集／尚未改碼"
        ),
    }


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """接默默落檔節奏：落排名＋對質＋重算。失敗吞掉。"""
    out: Dict[str, Any] = {"wrote": {}, "scored": 0, "gate": {}}
    try:
        out["wrote"] = snapshot_day(db_path, as_of=as_of)
        out["scored"] = score_pending(db_path, cap=as_of)
        out["gate"] = gate_status(db_path)
    except Exception:
        return out
    return out


def optimize_status_one_liner(db_path: str) -> str:
    """報告結論唯一准講的一句（明確優化狀態）。"""
    g = gate_status(db_path)
    n = int(g.get("n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if not g.get("n_ok"):
        return f"明確優化狀態：n={n}/{need} 不夠，第一次優化尚未贏現況可證，繼續收集／尚未改碼。"
    if g.get("first_beats_current") and g.get("promote_ready"):
        return (
            f"明確優化狀態：n={n} 夠且第一次優化贏現況，可考慮只改話筒排序鍵（另開專件）；"
            "飆大靜默軌不當改碼候選。"
        )
    return (
        f"明確優化狀態：n={n} 夠但第一次優化未贏現況，不改碼；"
        "再擠暫不開；飆大只靜默／之後。"
    )
