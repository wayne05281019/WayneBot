# -*- coding: utf-8 -*-
"""大量區 × 季線上升・靜默對質（不是買訊）。

三軌同一資格池、同一前瞻窗：
  current           ＝壓撐觀察結構門檻過關（大量區語境基線）
  ma60_rising       ＝同池 ∩ 官方收盤 MA60 近 5 交易日上升
  ma60_rising_thin  ＝季線上升再生下一版：再 ∩ 量縮（vol_ratio<0.35）

分軌記、分軌算；勝率不准混進海選／黃金買點／其他鈕。
獨立交易日 n≥20 且贏 current 才算過閘；過閘也不自動改黃金買點／海選／話筒買訊
（本檔只留閘狀態；改碼另件）。失敗不擋出卡／海選。過程／％不准進對話。
Asia/Taipei；官方已收柱；盤中未收不當收。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path
from pressure_rank_verify import (
    FORWARD_H,
    _forward_bars,
    outcome_win,
)
from pressure_support_watch import TAG_ORDER, collect_pressure_pool, normalize_tag
from vol_zone_chart import VOL_ZONE_MA60, attach_official_ma60, ma60_is_rising, official_work

KIND = "volzone_ma60"
VARIANT_CURRENT = "current"
VARIANT_MA60_RISING = "ma60_rising"
VARIANT_MA60_RISING_THIN = "ma60_rising_thin"  # 再生下一版：季線升＋量縮
TRACK_VARIANTS = (VARIANT_CURRENT, VARIANT_MA60_RISING, VARIANT_MA60_RISING_THIN)
MA60_SLOPE_BARS = 5
MAX_ROWS = 12
THIN_MAX_ROWS = 10
THIN_VOL_RATIO = 0.35
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


def _load_work(db_path: str, sid: str, as_of: str):
    """官方原柱至 as_of（含）；不足回 None。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not sid or not day or not db_path or not os.path.isfile(db_path):
        return None
    need = VOL_ZONE_MA60 + MA60_SLOPE_BARS + 40
    conn = sqlite3.connect(db_path, timeout=12.0)
    try:
        rows = conn.execute(
            """
            SELECT date, stock_name, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (sid, day, need),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    if len(rows) < VOL_ZONE_MA60 + MA60_SLOPE_BARS:
        return None
    import pandas as pd

    df = pd.DataFrame(
        rows, columns=["date", "stock_name", "open", "high", "low", "close", "volume"]
    )
    df["stock_id"] = sid
    work = official_work(df)
    if work is None or work.empty:
        return None
    # 切到 as_of（含）
    dnorm = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work = work.loc[dnorm <= day].reset_index(drop=True)
    if len(work) < VOL_ZONE_MA60 + MA60_SLOPE_BARS:
        return None
    return attach_official_ma60(work)


def row_ma60_rising(db_path: str, sid: str, as_of: str) -> Optional[bool]:
    """該檔 as_of 當日季線是否上升。柱不足回 None。"""
    work = _load_work(db_path, sid, as_of)
    if work is None or "ma60" not in work.columns:
        return None
    return ma60_is_rising(work["ma60"], slope_bars=MA60_SLOPE_BARS)


def filter_ma60_rising(
    pool: Sequence[Dict[str, Any]],
    db_path: str,
    as_of: str,
) -> List[Dict[str, Any]]:
    """同池 ∩ 季線上升；無真數／柱不足不進候選（不准假上升）。"""
    out: List[Dict[str, Any]] = []
    day = _ymd(as_of)
    for r in pool:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("stock_id") or r.get("code") or "").strip()
        if not sid:
            continue
        rising = row_ma60_rising(db_path, sid, day)
        if rising is not True:
            continue
        item = dict(r)
        item["ma60_rising"] = 1
        item["ma60_slope_bars"] = MA60_SLOPE_BARS
        out.append(item)
    return out


def _is_vol_thin(r: Dict[str, Any]) -> bool:
    if r.get("vol_thin_bonus"):
        return True
    vr = _num(r.get("vol_ratio"), 99.0)
    return 0 < vr < THIN_VOL_RATIO


def filter_ma60_rising_thin(
    pool: Sequence[Dict[str, Any]],
    db_path: str,
    as_of: str,
) -> List[Dict[str, Any]]:
    """季線上升再生軌：再 ∩ 量縮。無真量比不准假裝量縮。"""
    rising = filter_ma60_rising(pool, db_path, as_of)
    out: List[Dict[str, Any]] = []
    for r in rising:
        if not _is_vol_thin(r):
            continue
        item = dict(r)
        item["vol_thin"] = 1
        out.append(item)
    return out


def rank_pool(
    pool: Sequence[Dict[str, Any]],
    tag: str,
    *,
    max_rows: int = MAX_ROWS,
) -> List[Dict[str, Any]]:
    """基線排序：離壓近 → 量縮加分 → 代號（對齊壓撐現況鍵）。"""
    from pressure_support_watch import rank_key_current

    tag = normalize_tag(tag) or str(tag or "")
    rows = [dict(r) for r in pool if isinstance(r, dict)]
    rows.sort(key=rank_key_current)
    return rows[: max(1, int(max_rows or MAX_ROWS))]


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS volzone_ma60_tape (
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
                ma60_rising INTEGER DEFAULT 0,
                extra TEXT DEFAULT '',
                PRIMARY KEY (kind, variant, tag, as_of, sid)
            );
            CREATE TABLE IF NOT EXISTS volzone_ma60_score (
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
            CREATE TABLE IF NOT EXISTS volzone_ma60_rates (
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


def persist_ranked(
    db_path: str,
    as_of: str,
    tag: str,
    variant: str,
    ranked: Sequence[Dict[str, Any]],
) -> int:
    day = _ymd(as_of)
    tag = normalize_tag(tag) or str(tag or "")
    variant = str(variant or "").strip()
    if not day or not tag or not variant:
        return 0
    store = ensure_tables(db_path)
    wrote = 0
    conn = sqlite3.connect(store, timeout=12.0)
    try:
        for i, r in enumerate(ranked):
            sid = str(r.get("stock_id") or r.get("code") or "").strip()
            if not sid:
                continue
            extra = {
                k: r.get(k)
                for k in ("zone_date", "streak", "why", "ma60_slope_bars")
                if r.get(k) is not None
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO volzone_ma60_tape(
                    kind, variant, tag, as_of, sid, rank_i, name,
                    close, pressure, support, vol_ratio, dist_to_press_pct,
                    ma60_rising, extra
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    variant,
                    tag,
                    day,
                    sid,
                    int(i),
                    str(r.get("stock_name") or r.get("name") or ""),
                    _num(r.get("close")) or None,
                    _num(r.get("pressure")) or None,
                    _num(r.get("support")) or None,
                    _num(r.get("vol_ratio")) or None,
                    _num(r.get("dist_to_press_pct")) or None,
                    1 if r.get("ma60_rising") else 0,
                    json.dumps(extra, ensure_ascii=False) if extra else "",
                ),
            )
            wrote += 1
        conn.commit()
    finally:
        conn.close()
    return wrote


def snapshot_day(db_path: str, as_of: str = "") -> Dict[str, int]:
    """盤後默默落兩軌。空名單不算有記。失敗回空。"""
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
            pool = collect_pressure_pool(db_path, tag, as_of=day, enrich=False)
            if not pool:
                # 空名單不算有記：仍寫 0，不灌假代號
                stats[f"{VARIANT_CURRENT}_{tag}"] = 0
                stats[f"{VARIANT_MA60_RISING}_{tag}"] = 0
                stats[f"{VARIANT_MA60_RISING_THIN}_{tag}"] = 0
                continue
            cur = rank_pool(pool, tag)
            rising_pool = filter_ma60_rising(pool, db_path, day)
            rising = rank_pool(rising_pool, tag)
            thin_pool = filter_ma60_rising_thin(pool, db_path, day)
            thin = rank_pool(thin_pool, tag, max_rows=THIN_MAX_ROWS)
            stats[f"{VARIANT_CURRENT}_{tag}"] = persist_ranked(
                db_path, day, tag, VARIANT_CURRENT, cur
            )
            stats[f"{VARIANT_MA60_RISING}_{tag}"] = persist_ranked(
                db_path, day, tag, VARIANT_MA60_RISING, rising
            )
            stats[f"{VARIANT_MA60_RISING_THIN}_{tag}"] = persist_ranked(
                db_path, day, tag, VARIANT_MA60_RISING_THIN, thin
            )
        stats["tracks"] = len(TRACK_VARIANTS)
    except Exception:
        return stats
    return stats


def score_pending(db_path: str, cap: str = "") -> int:
    """官方柱走完才填 FORWARD_H 對質。"""
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
            "SELECT variant, tag, as_of, sid, close, pressure, support "
            "FROM volzone_ma60_tape WHERE kind=?",
            (KIND,),
        ).fetchall()
        scored = {
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]), int(r[4]))
            for r in conn.execute(
                "SELECT variant, tag, as_of, sid, horizon "
                "FROM volzone_ma60_score WHERE kind=?",
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
            out = outcome_win(
                str(row["tag"]),
                pressure=_num(row["pressure"]),
                support=_num(row["support"]),
                entry=_num(row["close"]),
                bars=bars,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO volzone_ma60_score(
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
                    int(out["hold_support"]),
                    int(out["stand_press"]),
                    int(out["broke_support"]),
                    out.get("fwd_pct"),
                    int(out["win"]),
                ),
            )
            filled += 1
        conn.commit()
    finally:
        conn.close()
    if filled:
        recompute_rates(db_path)
    return filled


def recompute_rates(db_path: str) -> None:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=12.0)
    try:
        conn.execute("DELETE FROM volzone_ma60_rates WHERE kind=?", (KIND,))
        rows = conn.execute(
            """
            SELECT variant, tag, horizon,
                   COUNT(DISTINCT as_of) AS n_days,
                   COUNT(*) AS n_rows,
                   AVG(win) AS win_rate,
                   AVG(hold_support) AS hold_support_rate,
                   AVG(stand_press) AS stand_press_rate,
                   AVG(fwd_pct) AS avg_fwd_pct
            FROM volzone_ma60_score
            WHERE kind=?
            GROUP BY variant, tag, horizon
            """,
            (KIND,),
        ).fetchall()
        for variant, tag, horizon, n_days, n_rows, wr, hs, sp, af in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO volzone_ma60_rates(
                    kind, variant, tag, horizon, n_days, n_rows,
                    win_rate, hold_support_rate, stand_press_rate, avg_fwd_pct
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    str(variant),
                    str(tag),
                    int(horizon),
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


def unique_days(db_path: str, variant: str = VARIANT_MA60_RISING) -> int:
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT as_of) FROM volzone_ma60_score
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
    """明確優化狀態。過閘也不自動改黃金買點／海選／話筒買訊。"""
    store = ensure_tables(db_path)
    by: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT variant, tag, n_days, win_rate
            FROM volzone_ma60_rates
            WHERE kind=? AND horizon=?
            """,
            (KIND, FORWARD_H),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for variant, tag, n_days, wr in rows:
        by.setdefault(str(variant), {})[str(tag)] = {
            "n_days": int(n_days or 0),
            "win_rate": float(wr or 0),
        }

    def _mean_win(variant: str) -> Optional[float]:
        block = by.get(variant) or {}
        if not block:
            return None
        vals = [float(v.get("win_rate") or 0) for v in block.values()]
        return sum(vals) / len(vals) if vals else None

    n = unique_days(db_path, VARIANT_MA60_RISING)
    n_thin = unique_days(db_path, VARIANT_MA60_RISING_THIN)
    n_ok = n >= MIN_UNIQUE_DAYS
    n_thin_ok = n_thin >= MIN_UNIQUE_DAYS
    cur = _mean_win(VARIANT_CURRENT)
    rising = _mean_win(VARIANT_MA60_RISING)
    thin = _mean_win(VARIANT_MA60_RISING_THIN)
    beats = bool(n_ok and cur is not None and rising is not None and rising > cur)
    # 再生軌要比季線升軌好（升軌已贏基線時），否則先要比 current
    thin_baseline = rising if beats and rising is not None else cur
    thin_beats = bool(
        n_thin_ok
        and thin_baseline is not None
        and thin is not None
        and thin > thin_baseline
    )
    return {
        "n_days": n,
        "n_ok": n_ok,
        "min_n": MIN_UNIQUE_DAYS,
        "current_win": cur,
        "ma60_rising_win": rising,
        "ma60_beats_current": beats,
        "ma60_thin_n_days": n_thin,
        "ma60_thin_win": thin,
        "ma60_thin_beats_baseline": thin_beats,
        # 永久：本軌過閘也不自動改買訊／海選／黃金買點
        "promote_buy_signals": False,
        "promote_ready": False,
        "gate_ready_for_review": beats or thin_beats,
        "tracks": list(TRACK_VARIANTS),
        "note": (
            "季線升＋量縮再生軌贏基線且 n 夠 → 僅可人工複審；不准自動改買訊"
            if thin_beats
            else (
                "季線上升軌勝率贏基線且 n 夠 → 僅可人工複審；再生量縮軌續收"
                if beats
                else "繼續收集／尚未改碼；大量區×季線上升／量縮三軌靜默對質中"
            )
        ),
    }


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """接默默落檔節奏。失敗吞掉。"""
    out: Dict[str, Any] = {"wrote": {}, "scored": 0, "gate": {}, "tracks": list(TRACK_VARIANTS)}
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
    nt = int(g.get("ma60_thin_n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if n < need and nt < need:
        return (
            f"大量區×季線上升靜默對質：升軌 n={n}/{need}、量縮再生 n={nt}/{need}，"
            "繼續收集／尚未改碼。"
        )
    if g.get("ma60_thin_beats_baseline"):
        return (
            f"大量區×季線升＋量縮再生：n={nt} 夠且贏基線 → "
            "可複審；未自動改黃金買點／海選／買訊。"
        )
    if g.get("ma60_beats_current"):
        return (
            f"大量區×季線上升靜默對質：n≥{need} 且贏基線 → "
            f"可複審；量縮再生 n={nt} 續收；未自動改買訊。"
        )
    return (
        f"大量區×季線上升靜默對質：升軌 n={n}、量縮再生 n={nt} 尚未贏基線 → "
        "繼續收集／尚未改碼。"
    )
