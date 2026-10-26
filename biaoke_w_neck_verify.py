# -*- coding: utf-8 -*-
"""W底破頸線（站上）・靜默對質／長窗回測（D2；非買訊；預設不上話筒臉）。

定義：近窗兩相近樞紐低（左底／右底）＋中間峰＝頸線；收盤站上峰高＝事件。
量：右底縮量作附欄；下一版候選 ``w_neck_v2_vol_confirm`` 才當硬門檻。
指標：站上後 h1／h3／h5；續漲機率（收＞事件收）；最大上探；假突破（3 日內收回頸下）。
基線：同檔「收破近 20 日高」無雙底條件（``break_20high``）。
分軌 kind＝biaoke_w_neck_break；勝率不准混海選／黃金買點。
n≥20 獨立交易日且贏基線才談上臉；本檔只落檔＋算率，不改買訊。
失敗不擋出卡。過程／％不准進對話。Asia/Taipei。
記憶體：逐檔串流；重活避開 06:30／16:30／DC 03–04。
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "biaoke_w_neck_break"
VARIANT_W_NECK = "w_neck"  # 現況候選 v1（裸 K 雙底站上頸）
VARIANT_BASELINE = "break_20high"  # 該軌基線
VARIANT_NEXT = "w_neck_v2_vol_confirm"  # 規則 13 再生：右底量＜左底才認
TRACK_VARIANTS = (VARIANT_W_NECK, VARIANT_BASELINE, VARIANT_NEXT)
FORWARD_H = (1, 3, 5)
FALSE_BREAK_H = 3
LOOKBACK_BARS = 120
MAX_FORWARD = 5
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
PIVOT_LEFT = 3
TROUGH_TOL = 0.03  # 兩底低「相近」相對差 ≤3%
MIN_TROUGH_SEP = 5
MAX_TROUGH_SEP = 40
MIN_BARS = 40
EVENT_COOLDOWN = 5  # 同檔同軌 5 交易日內只記首次
FACE_DEFAULT = False  # 預設不上話筒臉
BUSY_WINDOWS_HHMM = (
    (630, 700),
    (1630, 1700),
    (300, 400),
)


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


def _taipei_hhmm() -> int:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        now = datetime.now(ZoneInfo("Asia/Taipei"))
        return int(now.hour) * 100 + int(now.minute)
    except Exception:
        return -1


def in_busy_window(hhmm: Optional[int] = None) -> bool:
    """重活尖峰：06:30／16:30／DC 03–04（台北）。"""
    t = int(hhmm if hhmm is not None else _taipei_hhmm())
    if t < 0:
        return False
    for a, b in BUSY_WINDOWS_HHMM:
        if int(a) <= t < int(b):
            return True
    return False


def _conn(db_path: str):
    return sqlite3.connect(db_path, timeout=12.0)


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    store = tape_store_path(path) if os.path.isfile(path) else path
    con = _conn(store)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS biaoke_w_neck_events (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                neck REAL,
                left_trough REAL,
                right_trough REAL,
                left_i INTEGER,
                right_i INTEGER,
                left_vol REAL,
                right_vol REAL,
                right_vol_shrink INTEGER,
                close REAL,
                o REAL, h REAL, l REAL, c REAL, v REAL,
                PRIMARY KEY (as_of, stock_id, variant)
            );
            CREATE TABLE IF NOT EXISTS biaoke_w_neck_outcomes (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                cont_up INTEGER,
                ret REAL,
                min_low REAL,
                false_break INTEGER,
                mae REAL,
                done INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (as_of, stock_id, variant, horizon)
            );
            CREATE INDEX IF NOT EXISTS idx_bwn_events_day
                ON biaoke_w_neck_events(as_of);
            CREATE INDEX IF NOT EXISTS idx_bwn_out_var
                ON biaoke_w_neck_outcomes(variant, horizon, done);
            """
        )
        con.commit()
    finally:
        con.close()


def list_stock_ids(db_path: str, *, limit: int = 0) -> List[str]:
    """上市／上櫃股票／KY；擋 ETF。limit=0＝全取。"""
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT stock_id FROM stock_universe
            WHERE COALESCE(is_active,1)=1
              AND length(stock_id)=4
              AND UPPER(COALESCE(asset_type,'')) IN ('STOCK','KY','')
              AND UPPER(COALESCE(asset_type,'')) NOT LIKE '%ETF%'
              AND UPPER(COALESCE(market_type,'')) IN ('TW','TWO','')
            ORDER BY stock_id
            """
        ).fetchall()
    except sqlite3.Error:
        try:
            rows = con.execute(
                "SELECT DISTINCT stock_id FROM daily_quotes "
                "WHERE length(stock_id)=4 ORDER BY stock_id"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        con.close()
    out = [str(r[0]).strip() for r in rows if r and str(r[0] or "").strip()]
    if limit and limit > 0:
        return out[: int(limit)]
    return out


def load_bars_thru(
    db_path: str,
    sid: str,
    as_of: str,
    *,
    need: int = LOOKBACK_BARS,
) -> List[Dict[str, Any]]:
    """單檔官方日 K 至 as_of（含）；量小窗，防 OOM。"""
    day = _ymd(as_of)
    sid = str(sid or "").strip()
    if not sid or not day or not db_path:
        return []
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume, stock_name
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')<=?
            ORDER BY replace(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (sid, day, int(need) + MAX_FORWARD + 5),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for r in reversed(rows):
        out.append(
            {
                "date": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
                "stock_name": r[6],
                "stock_id": sid,
            }
        )
    return out


def load_all_bars(db_path: str, sid: str) -> List[Dict[str, Any]]:
    """單檔全長官方日 K（全量回測用；一次一檔）。"""
    sid = str(sid or "").strip()
    if not sid or not db_path:
        return []
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume, stock_name
            FROM daily_quotes
            WHERE stock_id=? AND close>0
            ORDER BY replace(CAST(date AS TEXT),'-','') ASC
            """,
            (sid,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [
        {
            "date": r[0],
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
            "stock_name": r[6],
            "stock_id": sid,
        }
        for r in rows
    ]


def pivots_hi_lo(
    highs: Sequence[float], lows: Sequence[float], *, left: int = PIVOT_LEFT
) -> Tuple[List[int], List[int]]:
    """裸 K 樞紐（不依賴 matplotlib／biaoke_chart）。"""
    n = len(highs)
    hi_p: List[int] = []
    lo_p: List[int] = []
    if n < left * 2 + 1:
        return hi_p, lo_p
    for i in range(left, n - left):
        window_h = highs[i - left : i + left + 1]
        window_l = lows[i - left : i + left + 1]
        if highs[i] >= max(window_h) and highs[i] > 0:
            hi_p.append(i)
        if lows[i] <= min(window_l) and lows[i] > 0:
            lo_p.append(i)
    return hi_p, lo_p


def _troughs_similar(h1: float, h2: float, *, tol: float = TROUGH_TOL) -> bool:
    top = max(h1, h2)
    if top <= 0:
        return False
    return abs(h1 - h2) / top <= float(tol)


def detect_w_structure(
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    event_i: int,
    *,
    trough_tol: float = TROUGH_TOL,
    require_vol_shrink: bool = False,
) -> Optional[Dict[str, Any]]:
    """在 event_i 當日可見的最近雙底＋峰頸線；無未來函數。

    右底須已確認（event_i >= right + left）；左底同。
    """
    if event_i < MIN_BARS or event_i >= len(highs):
        return None
    # 只許用到 event_i 為止的柱；樞紐確認要右底後 left 根已過
    end = event_i + 1
    hi = list(highs[:end])
    lo = list(lows[:end])
    vol = list(volumes[:end])
    _, lo_p = pivots_hi_lo(hi, lo, left=PIVOT_LEFT)
    # 樞紐點必須距離末日至少 PIVOT_LEFT（已確認）；掃時 end-1=event_i
    confirmed = [p for p in lo_p if p + PIVOT_LEFT <= event_i]
    if len(confirmed) < 2:
        return None
    # 由近到遠找一對相近底
    for r_idx in range(len(confirmed) - 1, 0, -1):
        right = confirmed[r_idx]
        for l_idx in range(r_idx - 1, -1, -1):
            left = confirmed[l_idx]
            sep = right - left
            if sep < MIN_TROUGH_SEP:
                continue
            if sep > MAX_TROUGH_SEP:
                break
            ll = float(lo[left])
            rl = float(lo[right])
            if not _troughs_similar(ll, rl, tol=trough_tol):
                continue
            # 中間不可有更低低（否則不是乾淨雙底）
            mid_l = lo[left + 1 : right]
            if mid_l and min(mid_l) < min(ll, rl) - 1e-9:
                continue
            peak_slice = hi[left : right + 1]
            if not peak_slice:
                continue
            neck = float(max(peak_slice))
            if neck <= 0:
                continue
            # 兩底須明顯低於頸線
            if max(ll, rl) > neck / 1.01:
                continue
            lv = float(vol[left]) if left < len(vol) else 0.0
            rv = float(vol[right]) if right < len(vol) else 0.0
            shrink = 1 if (lv > 0 and rv > 0 and rv < lv) else 0
            if require_vol_shrink and not shrink:
                continue
            return {
                "left_i": int(left),
                "right_i": int(right),
                "left_trough": ll,
                "right_trough": rl,
                "neck": neck,
                "left_vol": lv,
                "right_vol": rv,
                "right_vol_shrink": shrink,
            }
    return None


def _first_stand_above(close_prev: float, close_now: float, level: float) -> bool:
    """收盤首站上：昨收 ≤ 頸且今收 ＞ 頸。"""
    if level <= 0:
        return False
    return close_prev <= level + 1e-12 and close_now > level + 1e-12


def event_w_neck_at(
    bars: Sequence[Dict[str, Any]],
    event_i: int,
    *,
    sid: str,
    require_vol_shrink: bool = False,
    trough_tol: float = TROUGH_TOL,
) -> Optional[Dict[str, Any]]:
    """若 event_i 收盤首站上 W 頸線 → 事件。"""
    if event_i <= 0 or event_i >= len(bars):
        return None
    highs = [_num(b.get("high")) for b in bars]
    lows = [_num(b.get("low")) for b in bars]
    vols = [_num(b.get("volume")) for b in bars]
    closes = [_num(b.get("close")) for b in bars]
    struct = detect_w_structure(
        highs,
        lows,
        vols,
        event_i,
        trough_tol=trough_tol,
        require_vol_shrink=require_vol_shrink,
    )
    if not struct:
        return None
    neck = float(struct["neck"])
    if not _first_stand_above(closes[event_i - 1], closes[event_i], neck):
        return None
    day = _ymd(bars[event_i].get("date"))
    variant = VARIANT_NEXT if require_vol_shrink else VARIANT_W_NECK
    return {
        "as_of": day,
        "stock_id": str(sid).strip(),
        "variant": variant,
        "neck": neck,
        "left_trough": struct["left_trough"],
        "right_trough": struct["right_trough"],
        "left_i": struct["left_i"],
        "right_i": struct["right_i"],
        "left_vol": struct["left_vol"],
        "right_vol": struct["right_vol"],
        "right_vol_shrink": struct["right_vol_shrink"],
        "close": closes[event_i],
        "o": _num(bars[event_i].get("open")),
        "h": highs[event_i],
        "l": lows[event_i],
        "c": closes[event_i],
        "v": vols[event_i],
    }


def event_break_20high_at(
    bars: Sequence[Dict[str, Any]],
    event_i: int,
    *,
    sid: str,
) -> Optional[Dict[str, Any]]:
    """基線：收破近 20 日高（不含當日），無雙底條件。"""
    if event_i < 20 or event_i >= len(bars):
        return None
    highs = [_num(b.get("high")) for b in bars]
    lows = [_num(b.get("low")) for b in bars]
    closes = [_num(b.get("close")) for b in bars]
    prior_hi = max(highs[event_i - 20 : event_i])
    if prior_hi <= 0:
        return None
    if not _first_stand_above(closes[event_i - 1], closes[event_i], prior_hi):
        return None
    day = _ymd(bars[event_i].get("date"))
    return {
        "as_of": day,
        "stock_id": str(sid).strip(),
        "variant": VARIANT_BASELINE,
        "neck": prior_hi,
        "left_trough": 0.0,
        "right_trough": 0.0,
        "left_i": -1,
        "right_i": -1,
        "left_vol": 0.0,
        "right_vol": 0.0,
        "right_vol_shrink": 0,
        "close": closes[event_i],
        "o": _num(bars[event_i].get("open")),
        "h": highs[event_i],
        "l": lows[event_i],
        "c": closes[event_i],
        "v": _num(bars[event_i].get("volume")),
    }


def event_for_bar(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str,
    as_of: str,
    variant: str = VARIANT_W_NECK,
) -> Optional[Dict[str, Any]]:
    """若 as_of 收盤觸發指定變體 → 事件列。"""
    day = _ymd(as_of)
    rows = [r for r in bars if _ymd(r.get("date")) <= day]
    if len(rows) < MIN_BARS:
        return None
    if _ymd(rows[-1].get("date")) != day:
        return None
    i = len(rows) - 1
    v = str(variant or VARIANT_W_NECK)
    if v == VARIANT_BASELINE:
        return event_break_20high_at(rows, i, sid=sid)
    if v == VARIANT_NEXT:
        return event_w_neck_at(rows, i, sid=sid, require_vol_shrink=True)
    return event_w_neck_at(rows, i, sid=sid, require_vol_shrink=False)


def remember_event(db_path: str, event: Dict[str, Any]) -> None:
    if not event:
        return
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO biaoke_w_neck_events (
                as_of, stock_id, variant, neck, left_trough, right_trough,
                left_i, right_i, left_vol, right_vol, right_vol_shrink,
                close, o, h, l, c, v
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _ymd(event.get("as_of")),
                str(event.get("stock_id") or "").strip(),
                str(event.get("variant") or VARIANT_W_NECK),
                _num(event.get("neck")),
                _num(event.get("left_trough")),
                _num(event.get("right_trough")),
                int(event.get("left_i") if event.get("left_i") is not None else -1),
                int(event.get("right_i") if event.get("right_i") is not None else -1),
                _num(event.get("left_vol")),
                _num(event.get("right_vol")),
                int(event.get("right_vol_shrink") or 0),
                _num(event.get("close")),
                _num(event.get("o")),
                _num(event.get("h")),
                _num(event.get("l")),
                _num(event.get("c")),
                _num(event.get("v")),
            ),
        )
        con.commit()
    finally:
        con.close()


def _forward_slice(
    db_path: str, sid: str, as_of: str, horizon: int
) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND close>0
              AND replace(CAST(date AS TEXT),'-','')>?
            ORDER BY replace(CAST(date AS TEXT),'-','') ASC
            LIMIT ?
            """,
            (sid, day, int(horizon)),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [
        {
            "date": r[0],
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
        }
        for r in rows
    ]


def score_event(
    db_path: str,
    event: Dict[str, Any],
    *,
    horizons: Sequence[int] = FORWARD_H,
    fwd_bars: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """前瞻走完才記；不足根數 done=0。假突破＝3 日內收 ＜ 頸線。"""
    sid = str(event.get("stock_id") or "").strip()
    day = _ymd(event.get("as_of"))
    entry = _num(event.get("close"))
    neck = _num(event.get("neck"))
    out: List[Dict[str, Any]] = []
    for h in horizons:
        if fwd_bars is not None:
            fwd = list(fwd_bars[: int(h)])
        else:
            fwd = _forward_slice(db_path, sid, day, int(h))
        done = 1 if len(fwd) >= int(h) else 0
        cont = 0
        ret = None
        min_low = None
        false_break = 0
        mae = None
        if fwd:
            lows = [_num(r.get("low")) for r in fwd]
            highs = [_num(r.get("high")) for r in fwd]
            closes = [_num(r.get("close")) for r in fwd]
            min_low = min(lows) if lows else None
            max_high = max(highs) if highs else None
            last_c = closes[-1] if closes else 0.0
            if entry > 0 and last_c > 0:
                ret = (last_c / entry) - 1.0
                cont = 1 if last_c > entry else 0
            # 多頭不利偏移＝窗內最低相對事件收
            if entry > 0 and min_low is not None:
                mae = (min_low / entry) - 1.0
            # 假突破只在 h>=FALSE_BREAK_H 且該窗走完時有意義；短窗記 0
            if int(h) >= FALSE_BREAK_H and done and neck > 0:
                win = closes[:FALSE_BREAK_H]
                if any(c < neck + 1e-12 for c in win):
                    false_break = 1
        out.append(
            {
                "as_of": day,
                "stock_id": sid,
                "variant": str(event.get("variant") or ""),
                "horizon": int(h),
                "cont_up": cont,
                "ret": ret,
                "min_low": min_low,
                "false_break": false_break,
                "mae": mae,
                "done": done,
            }
        )
    return out


def remember_outcomes(db_path: str, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        return
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        for r in rows:
            con.execute(
                """
                INSERT OR REPLACE INTO biaoke_w_neck_outcomes (
                    as_of, stock_id, variant, horizon,
                    cont_up, ret, min_low, false_break, mae, done
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _ymd(r.get("as_of")),
                    str(r.get("stock_id") or "").strip(),
                    str(r.get("variant") or ""),
                    int(r.get("horizon") or 0),
                    int(r.get("cont_up") or 0),
                    r.get("ret"),
                    r.get("min_low"),
                    int(r.get("false_break") or 0),
                    r.get("mae"),
                    int(r.get("done") or 0),
                ),
            )
        con.commit()
    finally:
        con.close()


def _median(xs: Sequence[float]) -> Optional[float]:
    vals = sorted(float(x) for x in xs if x is not None)
    if not vals:
        return None
    m = len(vals) // 2
    if len(vals) % 2:
        return vals[m]
    return (vals[m - 1] + vals[m]) / 2.0


def rates_summary(db_path: str) -> Dict[str, Any]:
    """分軌續漲／假突破／報酬；獨立日 n。過程％不准進對話。"""
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        rows = con.execute(
            """
            SELECT variant, horizon,
                   COUNT(*) AS n,
                   SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) AS n_done,
                   SUM(CASE WHEN done=1 AND cont_up=1 THEN 1 ELSE 0 END) AS ups,
                   SUM(CASE WHEN done=1 AND false_break=1 THEN 1 ELSE 0 END) AS fakes,
                   COUNT(DISTINCT as_of) AS days,
                   AVG(CASE WHEN done=1 THEN ret END) AS mean_ret,
                   AVG(CASE WHEN done=1 THEN mae END) AS mean_mae
            FROM biaoke_w_neck_outcomes
            GROUP BY variant, horizon
            """
        ).fetchall()
        # 中位報酬另算
        rets = con.execute(
            """
            SELECT variant, horizon, ret FROM biaoke_w_neck_outcomes
            WHERE done=1 AND ret IS NOT NULL
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
        rets = []
    finally:
        con.close()
    by_vh: Dict[Tuple[str, int], List[float]] = {}
    for variant, horizon, ret in rets:
        by_vh.setdefault((str(variant), int(horizon)), []).append(float(ret))
    out: Dict[str, Any] = {
        "kind": KIND,
        "face": FACE_DEFAULT,
        "next_variant": VARIANT_NEXT,
        "tracks": {},
    }
    for variant, horizon, n, n_done, ups, fakes, days, mean_ret, mean_mae in rows:
        key = f"{variant}:h{horizon}"
        nd = int(n_done or 0)
        med = _median(by_vh.get((str(variant), int(horizon)), []))
        out["tracks"][key] = {
            "variant": variant,
            "horizon": int(horizon),
            "n": int(n or 0),
            "n_done": nd,
            "unique_days": int(days or 0),
            "cont_up_rate": (float(ups) / nd) if nd else None,
            "false_break_rate": (float(fakes) / nd) if nd else None,
            "mean_ret": mean_ret,
            "median_ret": med,
            "mean_mae": mean_mae,
            "gate_ready": int(days or 0) >= MIN_UNIQUE_DAYS,
            "face": FACE_DEFAULT,
        }
    return out


def holdout_cut_ymd(days: Sequence[str]) -> str:
    """最後約 20% 時間留白起日（含）。"""
    uniq = sorted({_ymd(d) for d in days if _ymd(d)})
    if not uniq:
        return ""
    k = max(1, int(round(len(uniq) * 0.2)))
    return uniq[-k]


def scan_stock_history(
    db_path: str,
    sid: str,
    *,
    max_events_per_variant: int = 0,
    persist: bool = True,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """單檔歷史：W 頸／基線／下一版；回寫入與內存事件。

    max_events_per_variant=0＝不截斷（全量）。
    """
    rows = list(bars) if bars is not None else load_all_bars(db_path, sid)
    if len(rows) < MIN_BARS + MAX_FORWARD:
        return {"stock_id": sid, "events": [], "n_wrote": 0}
    highs = [_num(b.get("high")) for b in rows]
    lows = [_num(b.get("low")) for b in rows]
    vols = [_num(b.get("volume")) for b in rows]
    closes = [_num(b.get("close")) for b in rows]
    collected: List[Dict[str, Any]] = []
    last_idx = {VARIANT_W_NECK: -10**9, VARIANT_BASELINE: -10**9, VARIANT_NEXT: -10**9}
    counts = {VARIANT_W_NECK: 0, VARIANT_BASELINE: 0, VARIANT_NEXT: 0}

    for i in range(MIN_BARS, len(rows) - MAX_FORWARD):
        # w_neck
        if max_events_per_variant <= 0 or counts[VARIANT_W_NECK] < max_events_per_variant:
            if i - last_idx[VARIANT_W_NECK] >= EVENT_COOLDOWN:
                struct = detect_w_structure(highs, lows, vols, i, require_vol_shrink=False)
                if struct and _first_stand_above(closes[i - 1], closes[i], float(struct["neck"])):
                    day = _ymd(rows[i].get("date"))
                    ev = {
                        "as_of": day,
                        "stock_id": str(sid).strip(),
                        "variant": VARIANT_W_NECK,
                        "neck": float(struct["neck"]),
                        "left_trough": struct["left_trough"],
                        "right_trough": struct["right_trough"],
                        "left_i": struct["left_i"],
                        "right_i": struct["right_i"],
                        "left_vol": struct["left_vol"],
                        "right_vol": struct["right_vol"],
                        "right_vol_shrink": struct["right_vol_shrink"],
                        "close": closes[i],
                        "o": _num(rows[i].get("open")),
                        "h": highs[i],
                        "l": lows[i],
                        "c": closes[i],
                        "v": vols[i],
                        "_i": i,
                    }
                    collected.append(ev)
                    last_idx[VARIANT_W_NECK] = i
                    counts[VARIANT_W_NECK] += 1
        # next: vol confirm
        if max_events_per_variant <= 0 or counts[VARIANT_NEXT] < max_events_per_variant:
            if i - last_idx[VARIANT_NEXT] >= EVENT_COOLDOWN:
                struct = detect_w_structure(highs, lows, vols, i, require_vol_shrink=True)
                if struct and _first_stand_above(closes[i - 1], closes[i], float(struct["neck"])):
                    day = _ymd(rows[i].get("date"))
                    ev = {
                        "as_of": day,
                        "stock_id": str(sid).strip(),
                        "variant": VARIANT_NEXT,
                        "neck": float(struct["neck"]),
                        "left_trough": struct["left_trough"],
                        "right_trough": struct["right_trough"],
                        "left_i": struct["left_i"],
                        "right_i": struct["right_i"],
                        "left_vol": struct["left_vol"],
                        "right_vol": struct["right_vol"],
                        "right_vol_shrink": struct["right_vol_shrink"],
                        "close": closes[i],
                        "o": _num(rows[i].get("open")),
                        "h": highs[i],
                        "l": lows[i],
                        "c": closes[i],
                        "v": vols[i],
                        "_i": i,
                    }
                    collected.append(ev)
                    last_idx[VARIANT_NEXT] = i
                    counts[VARIANT_NEXT] += 1
        # baseline
        if max_events_per_variant <= 0 or counts[VARIANT_BASELINE] < max_events_per_variant:
            if i - last_idx[VARIANT_BASELINE] >= EVENT_COOLDOWN:
                prior_hi = max(highs[i - 20 : i]) if i >= 20 else 0.0
                if prior_hi > 0 and _first_stand_above(closes[i - 1], closes[i], prior_hi):
                    day = _ymd(rows[i].get("date"))
                    ev = {
                        "as_of": day,
                        "stock_id": str(sid).strip(),
                        "variant": VARIANT_BASELINE,
                        "neck": prior_hi,
                        "left_trough": 0.0,
                        "right_trough": 0.0,
                        "left_i": -1,
                        "right_i": -1,
                        "left_vol": 0.0,
                        "right_vol": 0.0,
                        "right_vol_shrink": 0,
                        "close": closes[i],
                        "o": _num(rows[i].get("open")),
                        "h": highs[i],
                        "l": lows[i],
                        "c": closes[i],
                        "v": vols[i],
                        "_i": i,
                    }
                    collected.append(ev)
                    last_idx[VARIANT_BASELINE] = i
                    counts[VARIANT_BASELINE] += 1

    n_wrote = 0
    scored_rows: List[Dict[str, Any]] = []
    for ev in collected:
        i = int(ev.get("_i") or 0)
        fwd = [
            {
                "date": rows[j].get("date"),
                "open": rows[j].get("open"),
                "high": rows[j].get("high"),
                "low": rows[j].get("low"),
                "close": rows[j].get("close"),
                "volume": rows[j].get("volume"),
            }
            for j in range(i + 1, min(len(rows), i + 1 + MAX_FORWARD))
        ]
        outs = score_event(db_path, ev, fwd_bars=fwd)
        scored_rows.extend(outs)
        if persist:
            clean = {k: v for k, v in ev.items() if not str(k).startswith("_")}
            remember_event(db_path, clean)
            remember_outcomes(db_path, outs)
            n_wrote += 1
    return {
        "stock_id": sid,
        "events": collected,
        "outcomes": scored_rows,
        "n_wrote": n_wrote,
        "counts": counts,
    }


def _agg_from_outcomes(
    outcomes: Sequence[Dict[str, Any]],
    *,
    holdout_from: str = "",
    in_holdout: Optional[bool] = None,
) -> Dict[str, Any]:
    """內存 outcomes 彙總（全量／訓練／留白）。"""
    tracks: Dict[str, Any] = {}
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    days: Dict[Tuple[str, int], set] = {}
    for r in outcomes:
        d = _ymd(r.get("as_of"))
        if holdout_from:
            is_ho = d >= holdout_from
            if in_holdout is True and not is_ho:
                continue
            if in_holdout is False and is_ho:
                continue
        key = (str(r.get("variant")), int(r.get("horizon") or 0))
        buckets.setdefault(key, []).append(r)
        days.setdefault(key, set()).add(d)
    for (variant, horizon), rows in buckets.items():
        done_rows = [r for r in rows if int(r.get("done") or 0) == 1]
        nd = len(done_rows)
        ups = sum(1 for r in done_rows if int(r.get("cont_up") or 0) == 1)
        fakes = sum(1 for r in done_rows if int(r.get("false_break") or 0) == 1)
        rets = [float(r["ret"]) for r in done_rows if r.get("ret") is not None]
        maes = [float(r["mae"]) for r in done_rows if r.get("mae") is not None]
        udays = len(days.get((variant, horizon), set()))
        tkey = f"{variant}:h{horizon}"
        tracks[tkey] = {
            "variant": variant,
            "horizon": horizon,
            "n": len(rows),
            "n_done": nd,
            "unique_days": udays,
            "cont_up_rate": (ups / nd) if nd else None,
            "false_break_rate": (fakes / nd) if nd else None,
            "mean_ret": (sum(rets) / len(rets)) if rets else None,
            "median_ret": _median(rets),
            "mean_mae": (sum(maes) / len(maes)) if maes else None,
            "gate_ready": udays >= MIN_UNIQUE_DAYS,
            "face": FACE_DEFAULT,
        }
    return tracks


def gate_compare(tracks: Dict[str, Any], *, horizon: int = 5) -> Dict[str, Any]:
    """結構主句：續漲率高且假突破低＝贏基線；不上臉數字進對話。"""
    def _get(variant: str) -> Dict[str, Any]:
        return dict(tracks.get(f"{variant}:h{horizon}") or {})

    cand = _get(VARIANT_W_NECK)
    base = _get(VARIANT_BASELINE)
    nxt = _get(VARIANT_NEXT)
    c_up = cand.get("cont_up_rate")
    b_up = base.get("cont_up_rate")
    c_fake = cand.get("false_break_rate")
    b_fake = base.get("false_break_rate")
    n_ok = bool(cand.get("gate_ready")) and bool(base.get("gate_ready"))
    win_cont = (
        c_up is not None and b_up is not None and float(c_up) > float(b_up)
    )
    win_fake = (
        c_fake is not None and b_fake is not None and float(c_fake) < float(b_fake)
    )
    # 贏＝續漲優於基線，且假突破不大於基線（或兩者都優）
    beats = bool(n_ok and win_cont and (win_fake or c_fake == b_fake))
    face = False  # 硬鎖預設；即使 beats 本回合也不自動上臉
    return {
        "horizon": horizon,
        "n_ok": n_ok,
        "candidate_unique_days": cand.get("unique_days"),
        "baseline_unique_days": base.get("unique_days"),
        "next_unique_days": nxt.get("unique_days"),
        "cont_up_beats": win_cont,
        "false_break_beats": win_fake,
        "beats_baseline": beats,
        "face": face,
        "face_reason": "face_default_false; need n>=20 and beats + explicit promote",
        "next_variant": VARIANT_NEXT,
    }


def run_full_backtest(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 0,
    persist: bool = False,
    skip_busy: bool = True,
    progress_every: int = 200,
) -> Dict[str, Any]:
    """全宇宙長窗回測（逐檔串流；預設不寫碟以免碟滿，結果回傳）。"""
    if skip_busy and in_busy_window():
        return {
            "ok": False,
            "skipped": "busy_window",
            "hhmm": _taipei_hhmm(),
            "kind": KIND,
        }
    if persist:
        ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    if limit_stocks > 0:
        sids = sids[: int(limit_stocks)]
    all_outcomes: List[Dict[str, Any]] = []
    all_days: List[str] = []
    n_events = {v: 0 for v in TRACK_VARIANTS}
    t0 = time.time()
    for idx, sid in enumerate(sids):
        if skip_busy and in_busy_window():
            break
        pack = scan_stock_history(
            db_path, sid, max_events_per_variant=0, persist=persist
        )
        for ev in pack.get("events") or []:
            v = str(ev.get("variant"))
            if v in n_events:
                n_events[v] += 1
            all_days.append(_ymd(ev.get("as_of")))
        all_outcomes.extend(pack.get("outcomes") or [])
        if progress_every and (idx + 1) % int(progress_every) == 0:
            # 不印％到 stdout 當產品對話；腳本 --json 才帶進度欄
            pass
    ho = holdout_cut_ymd(all_days)
    tracks_all = _agg_from_outcomes(all_outcomes)
    tracks_train = _agg_from_outcomes(
        all_outcomes, holdout_from=ho, in_holdout=False
    )
    tracks_hold = _agg_from_outcomes(
        all_outcomes, holdout_from=ho, in_holdout=True
    )
    gate_all = gate_compare(tracks_all, horizon=5)
    gate_train = gate_compare(tracks_train, horizon=5)
    gate_hold = gate_compare(tracks_hold, horizon=5)
    # 留白也要贏才可換
    promote = bool(
        gate_all.get("beats_baseline")
        and gate_hold.get("beats_baseline")
        and gate_all.get("n_ok")
    )
    return {
        "ok": True,
        "kind": KIND,
        "face": FACE_DEFAULT,
        "promote_face": False,  # 本回合硬鎖不上臉
        "would_pass_gate": promote,
        "stocks": len(sids),
        "event_counts": n_events,
        "holdout_from": ho,
        "elapsed_sec": round(time.time() - t0, 2),
        "tracks": tracks_all,
        "tracks_train": tracks_train,
        "tracks_holdout": tracks_hold,
        "gate": gate_all,
        "gate_train": gate_train,
        "gate_holdout": gate_hold,
        "next_variant": VARIANT_NEXT,
        "definition": {
            "w_neck": "雙相近樞紐低＋中間峰高＝頸；收盤首站上",
            "trough_tol": TROUGH_TOL,
            "pivot_left": PIVOT_LEFT,
            "baseline": "收破近20日高無雙底",
            "next": "w_neck + 右底量<左底",
            "false_break": "站上後3日內收<頸",
            "cooldown": EVENT_COOLDOWN,
        },
    }


def run_skeleton(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 40,
    max_events_per_stock: int = 20,
    skip_busy: bool = True,
) -> Dict[str, Any]:
    """記憶體安全骨架跑：預設少數檔；全市場請用 run_full_backtest。"""
    if skip_busy and in_busy_window():
        return {
            "ok": False,
            "skipped": "busy_window",
            "hhmm": _taipei_hhmm(),
            "kind": KIND,
        }
    ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    prefer = ["3081", "3017", "3653", "2454"]
    ordered: List[str] = []
    for p in prefer:
        if p in sids and p not in ordered:
            ordered.append(p)
    for s in sids:
        if s not in ordered:
            ordered.append(s)
    if limit_stocks > 0:
        ordered = ordered[: int(limit_stocks)]
    total = 0
    t0 = time.time()
    for sid in ordered:
        if skip_busy and in_busy_window():
            break
        pack = scan_stock_history(
            db_path,
            sid,
            max_events_per_variant=int(max_events_per_stock),
            persist=True,
        )
        total += int(pack.get("n_wrote") or 0)
    summary = rates_summary(db_path)
    summary.update(
        {
            "ok": True,
            "events_written": total,
            "stocks": len(ordered),
            "elapsed_sec": round(time.time() - t0, 2),
            "kind": KIND,
            "face": FACE_DEFAULT,
            "next_variant": VARIANT_NEXT,
        }
    )
    return summary


def snapshot_day(market_db: str, as_of: str = "", *, limit: int = 80) -> int:
    """當日 W 頸／基線／下一版事件落檔（沒按也留）；回筆數。失敗吞掉。"""
    try:
        day = _ymd(as_of)
        if not day:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(market_db))
        if not day:
            return 0
        if in_busy_window():
            sids = ["3081", "3017", "3653", "2454"]
        else:
            sids = list_stock_ids(market_db, limit=limit)
            for p in ("3081", "3017", "3653", "2454"):
                if p not in sids:
                    sids.insert(0, p)
        n = 0
        for sid in sids:
            bars = load_bars_thru(market_db, sid, day, need=LOOKBACK_BARS)
            for variant in TRACK_VARIANTS:
                ev = event_for_bar(bars, sid=sid, as_of=day, variant=variant)
                if not ev:
                    continue
                remember_event(market_db, ev)
                remember_outcomes(market_db, score_event(market_db, ev))
                n += 1
        return n
    except Exception:
        return 0
