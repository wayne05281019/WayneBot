# -*- coding: utf-8 -*-
"""勝率買點母體 × 大量區／均線再篩・靜默對質（不是買訊）。

母體＝當日勝率買點現況路徑（leave_zero 藍▲＋buy_exclude_v5 留下；
可選 AI 生態系 ONLY 與話筒對齊）。不准改 leave_zero／ma60_lower／黃金買點公式。

變體（同母體再篩；分軌記、分軌算；勝率不准混海選／壓撐／洞燭／AI倉／飆大）：
  current            ＝現況整包（對照基線；空名單不算）
  vz_mid_thin        ＝大量區內中下帶（區相對位置 0.15–0.70）＋量能／爆大量日 <0.50
  ma60_rising        ＝季線近 5 交易日上升
  space_h20          ＝收盤距近 20 收盤高 ≥5%（上檔空間）
  untangle_up        ＝5／10／月線未糾結（spread≥2.8%）且月線上升、收≥五日
  combo_vz_ma60      ＝vz_mid_thin ∩ ma60_rising
  combo_vz_untangle  ＝vz_mid_thin ∩ untangle_up（§13 再生下一版）
  combo_vz_space     ＝vz_mid_thin ∩ space_h20（§13 再生下一版）
  combo_triple       ＝vz_mid_thin ∩ ma60_rising ∩ untangle_up（§13 再生下一版）

開市日沒按也落檔：母體各檔＋各變體命中＋當日官方開高低收＋量。
獨立交易日 n≥20 且主窗（＋5）勝率贏 current、且平均報酬不差於 current 才算過閘；
不過閘不准改話筒排序／推播／硬標優先 1～2 檔。本軌只落檔，過閘也不自動改推薦。
失敗不擋出卡／海選／查股。Asia/Taipei；官方已收柱；盤中未收不當收；不准假資料。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "winrate_volzone_filter"
VARIANT_CURRENT = "current"
VARIANT_VZ_MID_THIN = "vz_mid_thin"
VARIANT_MA60_RISING = "ma60_rising"
VARIANT_SPACE_H20 = "space_h20"
VARIANT_UNTANGLE_UP = "untangle_up"
VARIANT_COMBO = "combo_vz_ma60"
VARIANT_COMBO_VZ_UNTANGLE = "combo_vz_untangle"  # §13 再生
VARIANT_COMBO_VZ_SPACE = "combo_vz_space"  # §13 再生
VARIANT_COMBO_TRIPLE = "combo_triple"  # §13 再生：中帶∩季線升∩解糾結
TRACK_VARIANTS: Tuple[str, ...] = (
    VARIANT_CURRENT,
    VARIANT_VZ_MID_THIN,
    VARIANT_MA60_RISING,
    VARIANT_SPACE_H20,
    VARIANT_UNTANGLE_UP,
    VARIANT_COMBO,
    VARIANT_COMBO_VZ_UNTANGLE,
    VARIANT_COMBO_VZ_SPACE,
    VARIANT_COMBO_TRIPLE,
)
# 篩選臂（不含 current）；current 列 extra.hit 記各臂命中結果
FILTER_VARIANTS: Tuple[str, ...] = tuple(
    v for v in TRACK_VARIANTS if v != VARIANT_CURRENT
)
SPACE_H20_MIN_PCT = 5.0
SCORE_HORIZONS: Tuple[int, ...] = (1, 3, 5, 10)
PRIMARY_H = 5
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
# 勝率抬幅門檻（分數，不是百分點）：0.01＝＋1.0pt；微升不算過閘
MIN_WR_LIFT = 0.01
MA60_SLOPE_BARS = 5
MA20_SLOPE_BARS = 5
# 均線糾結門檻：五日／十日／月線價差 ≤2.8% 視為糾結（本檔常數，不接形態偵測）
TANGLE_SPREAD_MAX = 0.028
VZ_POS_LO = 0.15
VZ_POS_HI = 0.70
VZ_VOL_RATIO_MAX = 0.50


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _now_iso() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS winrate_volzone_filter_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                variant TEXT NOT NULL,
                name TEXT DEFAULT '',
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                zone_pos REAL,
                vol_ratio REAL,
                ma60_rising INTEGER,
                ma_spread_pct REAL,
                dist_h20_pct REAL,
                extra TEXT DEFAULT '',
                PRIMARY KEY (kind, as_of, sid, variant)
            );
            CREATE TABLE IF NOT EXISTS winrate_volzone_filter_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                variant TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL,
                entry REAL,
                exit_close REAL,
                fwd_pct REAL,
                win INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, as_of, sid, variant, horizon)
            );
            CREATE TABLE IF NOT EXISTS winrate_volzone_filter_rates (
                kind TEXT NOT NULL,
                variant TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n_days INTEGER NOT NULL,
                n_rows INTEGER NOT NULL,
                win_rate REAL,
                avg_fwd_pct REAL,
                med_fwd_pct REAL,
                updated_at TEXT DEFAULT '',
                PRIMARY KEY (kind, variant, horizon)
            );
            """
        )
        # 舊庫補官方柱欄（開高低量）；缺真數可 NULL，不准假填
        cols = {
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(winrate_volzone_filter_tape)"
            ).fetchall()
        }
        for name, decl in (
            ("open", "REAL"),
            ("high", "REAL"),
            ("low", "REAL"),
            ("volume", "REAL"),
        ):
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE winrate_volzone_filter_tape ADD COLUMN {name} {decl}"
                )
        conn.commit()
    finally:
        conn.close()
    return store


def _signal_day_ohlcv(df) -> Dict[str, Optional[float]]:
    """訊號日（df 最後一根）官方開高低收＋量；缺＝None，不准假填。"""
    out: Dict[str, Optional[float]] = {
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
    }
    if df is None or len(df) < 1:
        return out
    try:
        last = df.iloc[-1]
    except Exception:
        return out
    for k in ("open", "high", "low", "close", "volume"):
        if k in df.columns:
            out[k] = _f(last.get(k) if hasattr(last, "get") else last[k])
    return out


def compute_filter_features(df) -> Optional[Dict[str, Any]]:
    """訊號日（df 最後一根）可重算欄。柱不足／缺真數＝None（不准假填）。"""
    if df is None or len(df) < 65:
        return None
    try:
        import pandas as pd
        from vol_zone_chart import (
            attach_official_ma5,
            attach_official_ma10,
            attach_official_ma20,
            attach_official_ma60,
            find_volume_zone,
            ma60_is_rising,
            official_work,
        )

        work = official_work(df)
        if work is None or work.empty or len(work) < 65:
            return None
        work = attach_official_ma5(work)
        work = attach_official_ma10(work)
        work = attach_official_ma20(work)
        work = attach_official_ma60(work)
        zone = find_volume_zone(work)
        if not zone:
            return None
        hi = _f(zone.get("high"))
        lo = _f(zone.get("low"))
        cl = _f(work["close"].iloc[-1])
        if None in (hi, lo, cl) or hi is None or lo is None or cl is None:
            return None
        if hi <= 0 or lo <= 0 or hi < lo or cl <= 0:
            return None
        span = hi - lo
        zone_pos = (cl - lo) / span if span > 0 else None
        zvol = _f(zone.get("volume")) or 0.0
        last_vol = _f(work["volume"].iloc[-1]) or 0.0
        vol_ratio = (last_vol / zvol) if zvol > 0 and last_vol > 0 else None
        ma60_r = ma60_is_rising(work["ma60"], slope_bars=MA60_SLOPE_BARS)
        ma20 = pd.to_numeric(work["ma20"], errors="coerce")
        ma5 = pd.to_numeric(work["ma5"], errors="coerce")
        ma10 = pd.to_numeric(work["ma10"], errors="coerce")
        if len(ma20.dropna()) < MA20_SLOPE_BARS + 1:
            return None
        m20_now = float(ma20.iloc[-1])
        m20_prev = float(ma20.iloc[-(MA20_SLOPE_BARS + 1)])
        ma20_rising = bool(m20_now > 0 and m20_prev > 0 and m20_now > m20_prev)
        m5 = float(ma5.iloc[-1]) if pd.notna(ma5.iloc[-1]) else None
        m10 = float(ma10.iloc[-1]) if pd.notna(ma10.iloc[-1]) else None
        m20 = m20_now if m20_now == m20_now else None
        mas = [x for x in (m5, m10, m20) if x is not None and x > 0]
        if len(mas) < 3:
            return None
        spread = (max(mas) - min(mas)) / min(mas)
        tangled = bool(spread <= TANGLE_SPREAD_MAX)
        close_s = pd.to_numeric(work["close"], errors="coerce")
        h20 = float(close_s.tail(20).max())
        dist_h20 = ((h20 - cl) / cl) if cl > 0 and h20 > 0 else None
        in_band = bool(lo <= cl <= hi)
        near_press = bool(hi > 0 and cl <= hi and (hi - cl) / hi <= 0.015)
        return {
            "close": cl,
            "zone_pos": round(zone_pos, 4) if zone_pos is not None else None,
            "vol_ratio": round(vol_ratio, 4) if vol_ratio is not None else None,
            "ma60_rising": bool(ma60_r) if ma60_r is not None else None,
            "ma20_rising": ma20_rising,
            "ma_spread_pct": round(spread * 100.0, 3),
            "tangled": tangled,
            "close_ge_ma5": bool(m5 is not None and cl >= m5),
            "dist_h20_pct": round(dist_h20 * 100.0, 3) if dist_h20 is not None else None,
            "in_band": in_band,
            "near_press": near_press,
            "pressure": hi,
            "support": lo,
            "zone_date": str(zone.get("date") or ""),
        }
    except Exception:
        return None


def variant_pass(feat: Dict[str, Any], variant: str) -> bool:
    """特徵是否通過該變體。缺真數＝不過（不准假過）。"""
    if not isinstance(feat, dict):
        return False
    v = str(variant or "")
    if v == VARIANT_CURRENT:
        return True
    zp = _f(feat.get("zone_pos"))
    vr = _f(feat.get("vol_ratio"))
    if v == VARIANT_VZ_MID_THIN:
        if zp is None or vr is None:
            return False
        if not bool(feat.get("in_band")):
            return False
        if bool(feat.get("near_press")):
            return False
        return bool(VZ_POS_LO <= zp <= VZ_POS_HI and 0 < vr < VZ_VOL_RATIO_MAX)
    if v == VARIANT_MA60_RISING:
        return feat.get("ma60_rising") is True
    if v == VARIANT_SPACE_H20:
        d = _f(feat.get("dist_h20_pct"))
        if d is None:
            return False
        return bool(d >= SPACE_H20_MIN_PCT)
    if v == VARIANT_UNTANGLE_UP:
        sp = _f(feat.get("ma_spread_pct"))
        if sp is None:
            return False
        if sp < TANGLE_SPREAD_MAX * 100.0:
            return False  # 仍糾結＝不過
        if not bool(feat.get("ma20_rising")):
            return False
        return bool(feat.get("close_ge_ma5"))
    if v == VARIANT_COMBO:
        return variant_pass(feat, VARIANT_VZ_MID_THIN) and variant_pass(
            feat, VARIANT_MA60_RISING
        )
    if v == VARIANT_COMBO_VZ_UNTANGLE:
        return variant_pass(feat, VARIANT_VZ_MID_THIN) and variant_pass(
            feat, VARIANT_UNTANGLE_UP
        )
    if v == VARIANT_COMBO_VZ_SPACE:
        return variant_pass(feat, VARIANT_VZ_MID_THIN) and variant_pass(
            feat, VARIANT_SPACE_H20
        )
    if v == VARIANT_COMBO_TRIPLE:
        return (
            variant_pass(feat, VARIANT_VZ_MID_THIN)
            and variant_pass(feat, VARIANT_MA60_RISING)
            and variant_pass(feat, VARIANT_UNTANGLE_UP)
        )
    return False


def hit_map(feat: Dict[str, Any]) -> Dict[str, bool]:
    """各篩選臂對該檔是否命中（可重算；缺真數＝False）。"""
    return {v: bool(variant_pass(feat, v)) for v in FILTER_VARIANTS}


def _load_baseline_rows(
    db_path: str, day: str
) -> List[Dict[str, Any]]:
    """現況勝率母體：優先讀當日 roster；缺則掃 leave_zero＋exclude（不含重渲圖）。"""
    day = _ymd(day)
    if not day or not db_path:
        return []
    try:
        from winrate_buypoint import load_winrate_roster, roster_is_current

        if roster_is_current(db_path, day):
            rows = load_winrate_roster(db_path, day)
            if rows:
                return rows
    except Exception:
        pass
    # 輕量掃：公式 leave_zero＋buy_exclude；不跑決策卡／出圖（骨架穩定閘）
    try:
        from buy_exclude import should_exclude_buy
        from decision_card_signals import leave_zero_from_quote_df
        from screening_engine import ScreeningEngine
        from wayne_navigator import frame_for_cal60_profit

        eng = ScreeningEngine(db_path)
        frames, em_ids = eng._load_profit_scan_frames(day)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for sid, df in (frames or {}).items():
        sid_s = str(sid or "").strip()
        if not sid_s or df is None or len(df) < 2:
            continue
        last = _ymd(df["date"].iloc[-1] if "date" in df.columns else "")
        if last != day:
            continue
        try:
            profit_df = frame_for_cal60_profit(df, db_path)
        except Exception:
            profit_df = df
        try:
            if not leave_zero_from_quote_df(profit_df):
                continue
        except Exception:
            continue
        em = sid_s in (em_ids or set())
        src = "emerging_quotes" if em else "daily_quotes"
        try:
            if should_exclude_buy(profit_df, emerging=em, quote_source=src):
                continue
        except Exception:
            continue
        try:
            close = _f(profit_df["close"].iloc[-1])
            name = (
                str(profit_df["stock_name"].iloc[-1] or "")
                if "stock_name" in profit_df.columns
                else ""
            )
        except Exception:
            continue
        if close is None or close <= 0:
            continue
        out.append(
            {
                "stock_id": sid_s,
                "stock_name": name,
                "close": close,
                "pick_close": close,
                "quote_source": src,
                "_df": profit_df,
            }
        )
    # 與話筒對齊：若 AI 分區可用則只留 AI 生態系（失敗＝保留全母體，不准假刪）
    try:
        from winrate_ai_priority import partition_winrate_ai_rows

        ai_rows, _non = partition_winrate_ai_rows(out, db_path)
        if ai_rows:
            # 保留 _df
            keep = {str(r.get("stock_id") or "") for r in ai_rows}
            out = [r for r in out if str(r.get("stock_id") or "") in keep]
    except Exception:
        pass
    return out


def _frame_for_sid(
    db_path: str, sid: str, as_of: str, cached_df=None
):
    if cached_df is not None and len(cached_df) >= 65:
        return cached_df
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not sid or not day or not os.path.isfile(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=12.0)
    try:
        rows = conn.execute(
            """
            SELECT date, stock_name, open, high, low, close, volume, turnover_k
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT 120
            """,
            (sid, day),
        ).fetchall()
        if len(rows) < 65:
            rows = conn.execute(
                """
                SELECT date, stock_name, open, high, low, close, volume, turnover_k
                FROM emerging_quotes
                WHERE stock_id=? AND close>0
                  AND replace(CAST(date AS TEXT),'-','')<=?
                ORDER BY replace(CAST(date AS TEXT),'-','') DESC
                LIMIT 120
                """,
                (sid, day),
            ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    if len(rows) < 65:
        return None
    import pandas as pd

    df = pd.DataFrame(
        list(reversed(rows)),
        columns=[
            "date",
            "stock_name",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover_k",
        ],
    )
    df["stock_id"] = sid
    return df


def persist_tape(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    n = 0
    try:
        for r in rows:
            extra = {
                k: r.get(k)
                for k in (
                    "in_band",
                    "near_press",
                    "ma20_rising",
                    "tangled",
                    "close_ge_ma5",
                    "pressure",
                    "support",
                    "zone_date",
                    "hit",
                )
                if r.get(k) is not None
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO winrate_volzone_filter_tape(
                    kind, as_of, sid, variant, name,
                    open, high, low, close, volume,
                    zone_pos, vol_ratio, ma60_rising, ma_spread_pct,
                    dist_h20_pct, extra
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND,
                    r["as_of"],
                    r["sid"],
                    r["variant"],
                    str(r.get("name") or "")[:40],
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    r.get("zone_pos"),
                    r.get("vol_ratio"),
                    1 if r.get("ma60_rising") else 0,
                    r.get("ma_spread_pct"),
                    r.get("dist_h20_pct"),
                    json.dumps(extra, ensure_ascii=False) if extra else "",
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def snapshot_day(db_path: str, as_of: str = "") -> Dict[str, int]:
    """盤後：凍現況母體＋各過濾變體命中＋官方開高低收量。空名單不算有記。失敗回空。"""
    counts = {v: 0 for v in TRACK_VARIANTS}
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not db_path or not day or not os.path.isfile(db_path):
        return counts
    try:
        ensure_tables(db_path)
        baseline = _load_baseline_rows(db_path, day)
    except Exception:
        return counts
    if not baseline:
        # 空名單不算有記：不灌假代號
        return counts
    rows: List[Dict[str, Any]] = []
    for item in baseline:
        sid = str(item.get("stock_id") or item.get("code") or "").strip()
        if not sid:
            continue
        df = item.get("_df")
        if df is None:
            df = _frame_for_sid(db_path, sid, day)
        feat = compute_filter_features(df)
        if not feat:
            continue
        # 訊號日官方柱：優先特徵 close；開高低量從當日棒讀
        ohlcv = _signal_day_ohlcv(df)
        if ohlcv.get("close") is None:
            ohlcv["close"] = feat.get("close") or _f(item.get("close"))
        # 缺完整官方收＝這檔不凍（不准假柱）
        if None in (
            ohlcv.get("open"),
            ohlcv.get("high"),
            ohlcv.get("low"),
            ohlcv.get("close"),
            ohlcv.get("volume"),
        ):
            continue
        if float(ohlcv["close"] or 0) <= 0 or float(ohlcv["volume"] or 0) < 0:
            continue
        name = str(item.get("stock_name") or item.get("name") or "")
        hits = hit_map(feat)
        for variant in TRACK_VARIANTS:
            if not variant_pass(feat, variant):
                continue
            row: Dict[str, Any] = {
                "as_of": day,
                "sid": sid,
                "variant": variant,
                "name": name,
                "open": ohlcv.get("open"),
                "high": ohlcv.get("high"),
                "low": ohlcv.get("low"),
                "close": ohlcv.get("close"),
                "volume": ohlcv.get("volume"),
                "zone_pos": feat.get("zone_pos"),
                "vol_ratio": feat.get("vol_ratio"),
                "ma60_rising": feat.get("ma60_rising"),
                "ma_spread_pct": feat.get("ma_spread_pct"),
                "dist_h20_pct": feat.get("dist_h20_pct"),
                "in_band": feat.get("in_band"),
                "near_press": feat.get("near_press"),
                "ma20_rising": feat.get("ma20_rising"),
                "tangled": feat.get("tangled"),
                "close_ge_ma5": feat.get("close_ge_ma5"),
                "pressure": feat.get("pressure"),
                "support": feat.get("support"),
                "zone_date": feat.get("zone_date"),
            }
            # current 列附各臂命中結果（建議哪檔靜默依據；不過閘不進話筒）
            if variant == VARIANT_CURRENT:
                row["hit"] = hits
            rows.append(row)
            counts[variant] = int(counts.get(variant) or 0) + 1
    persist_tape(db_path, rows)
    return counts


def _next_trading_close(
    conn: sqlite3.Connection,
    sid: str,
    as_of: str,
    horizon: int,
) -> Tuple[str, Optional[float]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
            FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','') > ?
              AND close > 0
            ORDER BY d
            LIMIT ?
            """,
            (sid, as_of, int(horizon)),
        ).fetchall()
        if len(rows) < int(horizon):
            rows = conn.execute(
                """
                SELECT REPLACE(CAST(date AS TEXT),'-','') AS d, close
                FROM emerging_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','') > ?
                  AND close > 0
                ORDER BY d
                LIMIT ?
                """,
                (sid, as_of, int(horizon)),
            ).fetchall()
    except sqlite3.Error:
        return "", None
    if len(rows) < int(horizon):
        return "", None
    d, c = rows[int(horizon) - 1]
    return _ymd(d), _f(c)


def score_pending(db_path: str, *, cap: str = "") -> int:
    """對已凍 tape 補前瞻 1／3／5／10 日官方收。未齊＝pending。"""
    store = ensure_tables(db_path)
    day_cap = _ymd(cap)
    conn_e = sqlite3.connect(store, timeout=8.0)
    try:
        tape = conn_e.execute(
            """
            SELECT as_of, sid, variant, close
            FROM winrate_volzone_filter_tape WHERE kind=?
            """,
            (KIND,),
        ).fetchall()
    finally:
        conn_e.close()
    if not tape or not os.path.isfile(db_path):
        return 0
    mconn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        store_conn = sqlite3.connect(store, timeout=8.0)
        try:
            for as_of, sid, variant, entry in tape:
                as_of = _ymd(as_of)
                sid = str(sid or "").strip()
                variant = str(variant or "")
                entry_f = _f(entry)
                if not as_of or not sid or variant not in TRACK_VARIANTS:
                    continue
                if entry_f is None or entry_f <= 0:
                    continue
                if day_cap and as_of > day_cap:
                    continue
                for h in SCORE_HORIZONS:
                    check, exit_c = _next_trading_close(mconn, sid, as_of, h)
                    if not check or exit_c is None or exit_c <= 0:
                        continue
                    if day_cap and check > day_cap:
                        continue
                    fwd = (exit_c - entry_f) / entry_f
                    win = 1 if exit_c > entry_f else 0
                    store_conn.execute(
                        """
                        INSERT OR REPLACE INTO winrate_volzone_filter_score(
                            kind, as_of, sid, variant, horizon, check_as_of,
                            entry, exit_close, fwd_pct, win
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            KIND,
                            as_of,
                            sid,
                            variant,
                            int(h),
                            check,
                            entry_f,
                            exit_c,
                            round(fwd * 100.0, 4),
                            win,
                        ),
                    )
                    n += 1
            store_conn.commit()
        finally:
            store_conn.close()
    finally:
        mconn.close()
    return n


def recompute_rates(db_path: str) -> Dict[str, Dict[int, Dict[str, float]]]:
    """按變體×窗：獨立交易日平均勝率（當日至少 1 檔才算 1 日）。"""
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    out: Dict[str, Dict[int, Dict[str, float]]] = {}
    try:
        conn.execute("DELETE FROM winrate_volzone_filter_rates WHERE kind=?", (KIND,))
        stamp = _now_iso()
        for variant in TRACK_VARIANTS:
            out[variant] = {}
            for h in SCORE_HORIZONS:
                rows = conn.execute(
                    """
                    SELECT as_of, win, fwd_pct
                    FROM winrate_volzone_filter_score
                    WHERE kind=? AND variant=? AND horizon=?
                    """,
                    (KIND, variant, int(h)),
                ).fetchall()
                by_day: Dict[str, List[Tuple[int, float]]] = {}
                for as_of, win, fwd in rows:
                    d = _ymd(as_of)
                    if not d:
                        continue
                    by_day.setdefault(d, []).append((int(win or 0), float(fwd or 0)))
                n_days = len(by_day)
                n_rows = sum(len(v) for v in by_day.values())
                if n_days <= 0:
                    wr = avg = med = None
                else:
                    day_wrs = [
                        sum(w for w, _ in xs) / len(xs) for xs in by_day.values() if xs
                    ]
                    all_fwd = [f for xs in by_day.values() for _, f in xs]
                    wr = sum(day_wrs) / len(day_wrs) if day_wrs else None
                    avg = sum(all_fwd) / len(all_fwd) if all_fwd else None
                    med = (
                        sorted(all_fwd)[len(all_fwd) // 2] if all_fwd else None
                    )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO winrate_volzone_filter_rates(
                        kind, variant, horizon, n_days, n_rows,
                        win_rate, avg_fwd_pct, med_fwd_pct, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        KIND,
                        variant,
                        int(h),
                        n_days,
                        n_rows,
                        wr,
                        avg,
                        med,
                        stamp,
                    ),
                )
                out[variant][int(h)] = {
                    "n_days": float(n_days),
                    "n_rows": float(n_rows),
                    "win_rate": float(wr) if wr is not None else float("nan"),
                    "avg_fwd_pct": float(avg) if avg is not None else float("nan"),
                    "med_fwd_pct": float(med) if med is not None else float("nan"),
                }
        conn.commit()
    finally:
        conn.close()
    return out


def gate_status(db_path: str) -> Dict[str, Any]:
    """明確優化狀態：n／哪條領先／是否過閘。"""
    store = ensure_tables(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT variant, n_days, n_rows, win_rate, avg_fwd_pct, med_fwd_pct
            FROM winrate_volzone_filter_rates
            WHERE kind=? AND horizon=?
            """,
            (KIND, PRIMARY_H),
        ).fetchall()
    finally:
        conn.close()
    by_v = {
        str(v): {
            "n_days": int(nd or 0),
            "n_rows": int(nr or 0),
            "win_rate": _f(wr),
            "avg_fwd_pct": _f(avg),
            "med_fwd_pct": _f(med),
        }
        for v, nd, nr, wr, avg, med in rows
    }
    base = by_v.get(VARIANT_CURRENT) or {}
    base_n = int(base.get("n_days") or 0)
    base_wr = base.get("win_rate")
    base_avg = base.get("avg_fwd_pct")
    best_v = VARIANT_CURRENT
    best_wr = base_wr
    best_avg = base_avg
    for v in TRACK_VARIANTS:
        if v == VARIANT_CURRENT:
            continue
        info = by_v.get(v) or {}
        wr = info.get("win_rate")
        avg = info.get("avg_fwd_pct")
        n_v = int(info.get("n_days") or 0)
        if wr is None or base_wr is None or n_v < MIN_UNIQUE_DAYS:
            continue
        # 真提升：勝率至少贏現況 MIN_WR_LIFT，且平均報酬不比現況差
        if wr < (base_wr + MIN_WR_LIFT):
            continue
        if base_avg is not None and avg is not None and avg < base_avg:
            continue
        if wr > (best_wr if best_wr is not None else -1):
            best_wr = wr
            best_avg = avg
            best_v = v
    passed = bool(
        base_n >= MIN_UNIQUE_DAYS
        and best_v != VARIANT_CURRENT
        and best_wr is not None
        and base_wr is not None
        and best_wr >= (base_wr + MIN_WR_LIFT)
    )
    return {
        "kind": KIND,
        "primary_h": PRIMARY_H,
        "min_n": MIN_UNIQUE_DAYS,
        "n_days": base_n,
        "baseline_wr": base_wr,
        "baseline_avg_fwd": base_avg,
        "best_variant": best_v,
        "best_wr": best_wr,
        "best_avg_fwd": best_avg,
        "passed": passed,
        "by_variant": by_v,
    }


def optimize_status_one_liner(db_path: str) -> str:
    """對話唯一准講的一句。"""
    g = gate_status(db_path)
    n = int(g.get("n_days") or 0)
    need = int(g.get("min_n") or MIN_UNIQUE_DAYS)
    if n < need:
        return f"勝率大量區再篩靜默對質收集中；獨立交易日 n={n}＜{need} → 尚未改話筒"
    if g.get("passed"):
        return (
            f"勝率大量區再篩 n={n} 且 {g.get('best_variant')} "
            f"＋{PRIMARY_H}日勝率贏現況 → 可另 PR 改建議哪檔；本軌只落檔不改話筒"
        )
    return (
        f"勝率大量區再篩 n={n} 已滿；領先 {g.get('best_variant')} "
        f"尚未穩贏現況整包 → 不改話筒／不硬標優先檔"
    )


def night_tick(db_path: str, as_of: str = "") -> Dict[str, Any]:
    """盤後掛點：snapshot → score → rates。失敗吞掉由呼叫端決定。"""
    day = _ymd(as_of)
    counts = snapshot_day(db_path, day)
    scored = score_pending(db_path, cap=day)
    rates = recompute_rates(db_path)
    return {
        "as_of": day,
        "counts": counts,
        "scored": scored,
        "rates_keys": list(rates.keys()),
        "gate": gate_status(db_path),
    }
