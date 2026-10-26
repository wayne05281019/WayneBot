# -*- coding: utf-8 -*-
"""出貨痕跡／下降通道／第二段下殺・靜默對質（D6＋D7＋D9；非買訊；face=false）。

分軌 kind（勝率不准混）：
  - biaoke_dist_trace      D6 過壓掉回撐下＝出貨痕跡
  - biaoke_desc_channel    D7 下降通道中段／破平行撐
  - biaoke_second_leg      D9 第一段破大量區撐後再破下一關鍵撐

硬規則：官方已收 OHLC＋量；裸 K＋量；盤中未收不當收；無假數；
不准改 leave_zero／golden_buy／海選；n≥20 獨立交易日且留白贏基線才談上臉；
Asia/Taipei；規則 13 每軌再生下一版。失敗不擋出卡。過程／％不准進對話。

對齊：概念計畫 §D6／D7／D9；價量深拆出貨／洗盤定義（不重造輪，分軌落檔）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND_D6 = "biaoke_dist_trace"
KIND_D7 = "biaoke_desc_channel"
KIND_D9 = "biaoke_second_leg"
KINDS = (KIND_D6, KIND_D7, KIND_D9)

# D6 變體
D6_DIST = "distribution"
D6_WASH = "wash"  # 對照：破撐又站回
D6_BREAK = "break_only"  # 基線：僅破撐無過壓
D6_NEXT = "dist_v2_over_vol"  # 下一版：過壓日量 ≥ 爆量日 ×0.7
D6_VARIANTS = (D6_DIST, D6_WASH, D6_BREAK, D6_NEXT)

# D7 變體
D7_BREAK = "desc_break_par"  # 現況：收盤切入破平行撐
D7_MID = "desc_mid"  # 附：切入下降通道中段（轉移率）
D7_BASE = "vol_break"  # 基線：無通道、僅破大量區撐
D7_NEXT = "desc_break_v2_from_mid"  # 下一版：中段→破平行撐（轉移確認）
D7_VARIANTS = (D7_BREAK, D7_MID, D7_BASE, D7_NEXT)

# D9 變體
D9_SECOND = "second_leg"
D9_FIRST = "first_break_only"  # 基線：僅一次破撐
D9_NEXT = "second_v2_channel"  # 下一版：下一撐來源＝平行撐／通道下緣
D9_VARIANTS = (D9_SECOND, D9_FIRST, D9_NEXT)

FORWARD_H = (1, 3, 5)
MAX_FORWARD = 5
MIN_BARS = 40
LOOKBACK_BARS = 120
SPIKE_LOOKBACK = 40
SPIKE_PCT = 90.0
PATH_WITHIN = 15
EVENT_COOLDOWN = 5
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
FACE_DEFAULT = False
CHANNEL_WIN = 60
BUSY_WINDOWS_HHMM = (
    (630, 700),
    (1630, 1700),
    (300, 400),
)

POS_BREAK = "破平行撐"
POS_MID = "下降通道中段"
POS_NEAR_BASE = "靠近平行撐"


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
            CREATE TABLE IF NOT EXISTS biaoke_dcs_events (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                level REAL,
                spike_hi REAL,
                spike_lo REAL,
                spike_date TEXT,
                next_source TEXT,
                next_price REAL,
                channel_pos TEXT,
                meta_json TEXT,
                close REAL,
                o REAL, h REAL, l REAL, c REAL, v REAL,
                PRIMARY KEY (kind, as_of, stock_id, variant)
            );
            CREATE TABLE IF NOT EXISTS biaoke_dcs_outcomes (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                cont_down INTEGER,
                ret REAL,
                min_low REAL,
                mae REAL,
                hit_next INTEGER,
                transferred INTEGER,
                done INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, as_of, stock_id, variant, horizon)
            );
            CREATE INDEX IF NOT EXISTS idx_dcs_events_kind_day
                ON biaoke_dcs_events(kind, as_of);
            CREATE INDEX IF NOT EXISTS idx_dcs_out_kind_var
                ON biaoke_dcs_outcomes(kind, variant, horizon, done);
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
                "WHERE length(stock_id)=4 AND stock_id GLOB '[0-9][0-9][0-9][0-9]' "
                "AND COALESCE(market,'') IN ('TW','TWO','') "
                "ORDER BY stock_id"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        con.close()
    out = [
        str(r[0]).strip()
        for r in rows
        if r and str(r[0] or "").strip() and not str(r[0]).startswith("00")
    ]
    if limit and limit > 0:
        return out[: int(limit)]
    return out


def load_all_bars(db_path: str, sid: str) -> List[Dict[str, Any]]:
    sid = str(sid or "").strip()
    if not sid or not db_path:
        return []
    con = _conn(db_path)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume, stock_name
            FROM daily_quotes
            WHERE stock_id=? AND close>0 AND open>0 AND high>0 AND low>0
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


def load_bars_thru(
    db_path: str,
    sid: str,
    as_of: str,
    *,
    need: int = LOOKBACK_BARS,
) -> List[Dict[str, Any]]:
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


def _pctile(xs: Sequence[float], p: float) -> Optional[float]:
    arr = sorted(float(x) for x in xs if x is not None and x == x and x > 0)
    if len(arr) < 3:
        return None
    # 線性分位（與 deepdive 對齊精神；免 numpy）
    k = (len(arr) - 1) * (float(p) / 100.0)
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return arr[f]
    return arr[f] + (arr[c] - arr[f]) * (k - f)


def _own_vol_ge_pct(
    vols: Sequence[float], i: int, *, lookback: int, pct: float
) -> bool:
    if i < lookback or i >= len(vols):
        return False
    prior = [float(v) for v in vols[i - lookback : i] if v and v > 0]
    thr = _pctile(prior, pct)
    vt = float(vols[i] or 0)
    return thr is not None and vt > 0 and vt >= thr


def find_spike_indices(
    vols: Sequence[float], *, lookback: int = SPIKE_LOOKBACK, pct: float = SPIKE_PCT
) -> List[int]:
    n = len(vols)
    out: List[int] = []
    last_emit = -(10**9)
    for i in range(lookback, n - 1):
        if not _own_vol_ge_pct(vols, i, lookback=lookback, pct=pct):
            continue
        if i - last_emit < EVENT_COOLDOWN:
            continue
        out.append(i)
        last_emit = i
    return out


def classify_path_at(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vols: Sequence[float],
    spike_i: int,
    *,
    within: int = PATH_WITHIN,
) -> Dict[str, Any]:
    """對齊價量深拆／analyze_structure：洗盤／出貨／僅破撐。"""
    n = len(closes)
    if spike_i < 0 or spike_i >= n - 1:
        return {"path": "insufficient", "event_i": None}
    hi = float(highs[spike_i] or 0)
    lo = float(lows[spike_i] or 0)
    v0 = float(vols[spike_i] or 0)
    if hi <= 0 or lo <= 0 or v0 <= 0:
        return {"path": "insufficient", "event_i": None}
    end = min(n - 1, spike_i + within)
    broke = False
    reclaim = False
    saw_over = False
    over_i: Optional[int] = None
    over_vol = 0.0
    break_i: Optional[int] = None
    dist_i: Optional[int] = None
    wash_i: Optional[int] = None
    for j in range(spike_i + 1, end + 1):
        cj = float(closes[j] or 0)
        lj = float(lows[j] or 0)
        if cj <= 0:
            continue
        if lj < lo or cj < lo:
            broke = True
            if break_i is None:
                break_i = j
        if broke and cj >= lo:
            reclaim = True
            if wash_i is None:
                wash_i = j
        if cj >= hi:
            saw_over = True
            if over_i is None:
                over_i = j
                over_vol = float(vols[j] or 0)
        # 出貨確認：已過壓且當日收在撐下（首日）
        if saw_over and cj < lo and dist_i is None:
            dist_i = j
    last = float(closes[end] or 0)
    path = "undecided"
    event_i: Optional[int] = None
    if broke and reclaim and last >= lo and wash_i is not None:
        path = "wash"
        event_i = wash_i
    elif saw_over and dist_i is not None:
        path = "distribution"
        event_i = dist_i
    elif broke and last < lo and break_i is not None:
        path = "break_only"
        event_i = break_i
    return {
        "path": path,
        "event_i": event_i,
        "spike_i": spike_i,
        "spike_hi": hi,
        "spike_lo": lo,
        "broke": broke,
        "reclaim": reclaim,
        "saw_over": saw_over,
        "over_i": over_i,
        "over_vol": over_vol,
        "spike_vol": v0,
    }


def _spike_lo_hi_at(bars: Sequence[Dict[str, Any]]) -> Tuple[float, float, str]:
    """近窗爆大量高低（產品 volume_first_price）。"""
    try:
        from biaoke_brain import volume_first_price

        st = volume_first_price(list(bars), lookback=min(40, len(bars)))
        return (
            _num(st.get("spike_low")),
            _num(st.get("spike_high")),
            _ymd(st.get("spike_date")),
        )
    except Exception:
        return 0.0, 0.0, ""


def _infer_channel(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        from biaoke_chart import infer_parallel_channel

        win = list(bars)[-CHANNEL_WIN:]
        return dict(infer_parallel_channel(win) or {})
    except Exception:
        return {}


def _first_break(prev_c: float, cur_c: float, level: float) -> bool:
    if level <= 0:
        return False
    return prev_c >= level - 1e-12 and cur_c < level - 1e-12


def _bar_pack(bars: Sequence[Dict[str, Any]], i: int, **extra: Any) -> Dict[str, Any]:
    b = bars[i]
    out = {
        "as_of": _ymd(b.get("date")),
        "stock_id": str(b.get("stock_id") or "").strip(),
        "close": _num(b.get("close")),
        "o": _num(b.get("open")),
        "h": _num(b.get("high")),
        "l": _num(b.get("low")),
        "c": _num(b.get("close")),
        "v": _num(b.get("volume")),
        "_i": i,
    }
    out.update(extra)
    return out


def scan_d6_stock(
    bars: Sequence[Dict[str, Any]],
    sid: str,
    *,
    max_events_per_variant: int = 0,
) -> List[Dict[str, Any]]:
    """D6：出貨／洗盤／僅破撐／下一版。"""
    n = len(bars)
    if n < MIN_BARS + MAX_FORWARD:
        return []
    highs = [_num(b.get("high")) for b in bars]
    lows = [_num(b.get("low")) for b in bars]
    closes = [_num(b.get("close")) for b in bars]
    vols = [_num(b.get("volume")) for b in bars]
    spikes = find_spike_indices(vols)
    collected: List[Dict[str, Any]] = []
    last_idx = {v: -(10**9) for v in D6_VARIANTS}
    counts = {v: 0 for v in D6_VARIANTS}

    def _ok(v: str, i: int) -> bool:
        if max_events_per_variant > 0 and counts[v] >= max_events_per_variant:
            return False
        return i - last_idx[v] >= EVENT_COOLDOWN

    for si in spikes:
        if si + MAX_FORWARD >= n:
            continue
        info = classify_path_at(highs, lows, closes, vols, si, within=PATH_WITHIN)
        path = str(info.get("path") or "")
        ei = info.get("event_i")
        if ei is None:
            continue
        ei = int(ei)
        if ei + MAX_FORWARD >= n:
            continue
        spike_d = _ymd(bars[si].get("date"))
        common = dict(
            kind=KIND_D6,
            level=_num(info.get("spike_lo")),
            spike_hi=_num(info.get("spike_hi")),
            spike_lo=_num(info.get("spike_lo")),
            spike_date=spike_d,
            next_source="",
            next_price=0.0,
            channel_pos="",
            stock_id=str(sid).strip(),
        )
        if path == "distribution" and _ok(D6_DIST, ei):
            collected.append(
                _bar_pack(
                    bars,
                    ei,
                    variant=D6_DIST,
                    meta_json=json.dumps(
                        {"path": path, "over_i": info.get("over_i")}, ensure_ascii=False
                    ),
                    **common,
                )
            )
            last_idx[D6_DIST] = ei
            counts[D6_DIST] += 1
            # 下一版：過壓日量門檻
            over_vol = _num(info.get("over_vol"))
            spike_vol = _num(info.get("spike_vol"))
            if (
                spike_vol > 0
                and over_vol >= spike_vol * 0.7
                and _ok(D6_NEXT, ei)
            ):
                collected.append(
                    _bar_pack(
                        bars,
                        ei,
                        variant=D6_NEXT,
                        meta_json=json.dumps(
                            {
                                "path": path,
                                "over_vol": over_vol,
                                "spike_vol": spike_vol,
                            },
                            ensure_ascii=False,
                        ),
                        **common,
                    )
                )
                last_idx[D6_NEXT] = ei
                counts[D6_NEXT] += 1
        elif path == "wash" and _ok(D6_WASH, ei):
            collected.append(
                _bar_pack(
                    bars,
                    ei,
                    variant=D6_WASH,
                    meta_json=json.dumps({"path": path}, ensure_ascii=False),
                    **common,
                )
            )
            last_idx[D6_WASH] = ei
            counts[D6_WASH] += 1
        elif path == "break_only" and _ok(D6_BREAK, ei):
            collected.append(
                _bar_pack(
                    bars,
                    ei,
                    variant=D6_BREAK,
                    meta_json=json.dumps({"path": path}, ensure_ascii=False),
                    **common,
                )
            )
            last_idx[D6_BREAK] = ei
            counts[D6_BREAK] += 1
    return collected


def scan_d7_stock(
    bars: Sequence[Dict[str, Any]],
    sid: str,
    *,
    max_events_per_variant: int = 0,
) -> List[Dict[str, Any]]:
    """D7：下降通道中段／破平行撐／基線破大量區撐／中段→破下一版。"""
    n = len(bars)
    if n < CHANNEL_WIN + MAX_FORWARD:
        return []
    collected: List[Dict[str, Any]] = []
    last_idx = {v: -(10**9) for v in D7_VARIANTS}
    counts = {v: 0 for v in D7_VARIANTS}
    prev_pos = ""
    mid_open_i: Optional[int] = None

    def _ok(v: str, i: int) -> bool:
        if max_events_per_variant > 0 and counts[v] >= max_events_per_variant:
            return False
        return i - last_idx[v] >= EVENT_COOLDOWN

    # 通道每日算一次（近窗）；基線大量區破撐另掃
    for i in range(CHANNEL_WIN - 1, n - MAX_FORWARD):
        window = bars[max(0, i + 1 - CHANNEL_WIN) : i + 1]
        ch = _infer_channel(window)
        kind = str(ch.get("kind") or "")
        pos = str(ch.get("pos") or "") if kind == "desc" else ""
        base_now = _num(ch.get("base_now"))
        # 切入破平行撐
        if (
            pos == POS_BREAK
            and prev_pos != POS_BREAK
            and kind == "desc"
            and _ok(D7_BREAK, i)
        ):
            from_mid = prev_pos in (POS_MID, POS_NEAR_BASE) or (
                mid_open_i is not None and i - mid_open_i <= 20
            )
            collected.append(
                _bar_pack(
                    bars,
                    i,
                    kind=KIND_D7,
                    variant=D7_BREAK,
                    level=base_now,
                    spike_hi=_num(ch.get("rail_now")),
                    spike_lo=base_now,
                    spike_date="",
                    next_source="平行撐",
                    next_price=base_now,
                    channel_pos=pos,
                    stock_id=str(sid).strip(),
                    meta_json=json.dumps(
                        {
                            "prev_pos": prev_pos,
                            "score": ch.get("score"),
                            "from_mid": from_mid,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            last_idx[D7_BREAK] = i
            counts[D7_BREAK] += 1
            if from_mid and _ok(D7_NEXT, i):
                collected.append(
                    _bar_pack(
                        bars,
                        i,
                        kind=KIND_D7,
                        variant=D7_NEXT,
                        level=base_now,
                        spike_hi=_num(ch.get("rail_now")),
                        spike_lo=base_now,
                        spike_date="",
                        next_source="平行撐",
                        next_price=base_now,
                        channel_pos=pos,
                        stock_id=str(sid).strip(),
                        meta_json=json.dumps(
                            {"prev_pos": prev_pos, "from_mid": True},
                            ensure_ascii=False,
                        ),
                    )
                )
                last_idx[D7_NEXT] = i
                counts[D7_NEXT] += 1
            mid_open_i = None
        # 切入中段
        if pos == POS_MID and prev_pos != POS_MID and kind == "desc" and _ok(D7_MID, i):
            collected.append(
                _bar_pack(
                    bars,
                    i,
                    kind=KIND_D7,
                    variant=D7_MID,
                    level=base_now,
                    spike_hi=_num(ch.get("rail_now")),
                    spike_lo=base_now,
                    spike_date="",
                    next_source="",
                    next_price=0.0,
                    channel_pos=pos,
                    stock_id=str(sid).strip(),
                    meta_json=json.dumps({"prev_pos": prev_pos}, ensure_ascii=False),
                )
            )
            last_idx[D7_MID] = i
            counts[D7_MID] += 1
            mid_open_i = i
        if pos and pos != POS_MID and pos != POS_NEAR_BASE and mid_open_i is not None:
            # 離開中段族且非破 → 清
            if pos != POS_BREAK:
                mid_open_i = None
        prev_pos = pos if kind == "desc" else ""

        # 基線：大量區撐收盤首破（無通道條件）
        if _ok(D7_BASE, i) and i >= 20:
            spike_lo, spike_hi, spike_d = _spike_lo_hi_at(window)
            if spike_lo > 0:
                prev_c = _num(bars[i - 1].get("close"))
                cur_c = _num(bars[i].get("close"))
                if _first_break(prev_c, cur_c, spike_lo):
                    collected.append(
                        _bar_pack(
                            bars,
                            i,
                            kind=KIND_D7,
                            variant=D7_BASE,
                            level=spike_lo,
                            spike_hi=spike_hi,
                            spike_lo=spike_lo,
                            spike_date=spike_d,
                            next_source="",
                            next_price=0.0,
                            channel_pos="",
                            stock_id=str(sid).strip(),
                            meta_json=json.dumps(
                                {"baseline": "vol_break"}, ensure_ascii=False
                            ),
                        )
                    )
                    last_idx[D7_BASE] = i
                    counts[D7_BASE] += 1
    return collected


def scan_d9_stock(
    bars: Sequence[Dict[str, Any]],
    sid: str,
    *,
    max_events_per_variant: int = 0,
) -> List[Dict[str, Any]]:
    """D9：破大量區撐＝第一段；再收破下一關鍵撐＝第二段。"""
    n = len(bars)
    if n < MIN_BARS + MAX_FORWARD:
        return []
    collected: List[Dict[str, Any]] = []
    last_idx = {v: -(10**9) for v in D9_VARIANTS}
    counts = {v: 0 for v in D9_VARIANTS}

    def _ok(v: str, i: int) -> bool:
        if max_events_per_variant > 0 and counts[v] >= max_events_per_variant:
            return False
        return i - last_idx[v] >= EVENT_COOLDOWN

    # 進行中第一段：等第二段
    pending: Optional[Dict[str, Any]] = None
    pending_expire = -1

    for i in range(MIN_BARS, n - MAX_FORWARD):
        window = bars[: i + 1]
        spike_lo, spike_hi, spike_d = _spike_lo_hi_at(window[-80:])
        cur_c = _num(bars[i].get("close"))
        prev_c = _num(bars[i - 1].get("close"))

        # 若有 pending，檢查是否收破 NEXT（現況）／通道平行撐（下一版）
        if pending is not None and i <= pending_expire:
            next_px = _num(pending.get("next_price"))
            src = str(pending.get("next_source") or "")
            ch_base = _num(pending.get("channel_base"))
            # 下一版：破下降通道平行撐（與 primary NEXT 分軌；產品 NEXT 可不搶通道名）
            if (
                ch_base > 0
                and not pending.get("v2_done")
                and _first_break(prev_c, cur_c, ch_base)
                and _ok(D9_NEXT, i)
            ):
                collected.append(
                    _bar_pack(
                        bars,
                        i,
                        kind=KIND_D9,
                        variant=D9_NEXT,
                        level=ch_base,
                        spike_hi=spike_hi,
                        spike_lo=_num(pending.get("spike_lo")),
                        spike_date=str(pending.get("spike_date") or ""),
                        next_source="平行撐",
                        next_price=ch_base,
                        channel_pos=str(pending.get("channel_pos") or ""),
                        stock_id=str(sid).strip(),
                        meta_json=json.dumps(
                            {
                                "first_as_of": pending.get("as_of"),
                                "channel": True,
                                "primary_next": src,
                                "primary_px": next_px,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                last_idx[D9_NEXT] = i
                counts[D9_NEXT] += 1
                pending["v2_done"] = True
            if next_px > 0 and _first_break(prev_c, cur_c, next_px):
                if _ok(D9_SECOND, i):
                    collected.append(
                        _bar_pack(
                            bars,
                            i,
                            kind=KIND_D9,
                            variant=D9_SECOND,
                            level=next_px,
                            spike_hi=spike_hi,
                            spike_lo=_num(pending.get("spike_lo")),
                            spike_date=str(pending.get("spike_date") or ""),
                            next_source=src,
                            next_price=next_px,
                            channel_pos=str(pending.get("channel_pos") or ""),
                            stock_id=str(sid).strip(),
                            meta_json=json.dumps(
                                {
                                    "first_as_of": pending.get("as_of"),
                                    "first_level": pending.get("spike_lo"),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    last_idx[D9_SECOND] = i
                    counts[D9_SECOND] += 1
                pending = None
                continue
        elif pending is not None and i > pending_expire:
            # 窗內未出第二段 → 記基線 first_break_only（第一段日）
            fi = int(pending.get("_i") or -1)
            if fi >= 0 and _ok(D9_FIRST, fi):
                collected.append(
                    _bar_pack(
                        bars,
                        fi,
                        kind=KIND_D9,
                        variant=D9_FIRST,
                        level=_num(pending.get("spike_lo")),
                        spike_hi=_num(pending.get("spike_hi")),
                        spike_lo=_num(pending.get("spike_lo")),
                        spike_date=str(pending.get("spike_date") or ""),
                        next_source=str(pending.get("next_source") or ""),
                        next_price=_num(pending.get("next_price")),
                        channel_pos="",
                        stock_id=str(sid).strip(),
                        meta_json=json.dumps(
                            {"no_second_within": PATH_WITHIN + 10}, ensure_ascii=False
                        ),
                    )
                )
                last_idx[D9_FIRST] = fi
                counts[D9_FIRST] += 1
            pending = None

        # 新第一段：收盤首破大量區撐
        if pending is None and spike_lo > 0 and _first_break(prev_c, cur_c, spike_lo):
            channel = _infer_channel(window[-CHANNEL_WIN:])
            next_source = ""
            next_price = 0.0
            channel_pos = str(channel.get("pos") or "")
            channel_base = 0.0
            if str(channel.get("kind")) == "desc":
                cb = _num(channel.get("base_now"))
                if cb > 0 and cb < spike_lo - 1e-9:
                    channel_base = cb
            # NEXT 候選：對齊 D4 resolve（產品主選）；通道下緣另留作 v2
            try:
                from biaoke_next_support import resolve_next_support

                pack = resolve_next_support(
                    window,
                    sid=sid,
                    close=cur_c,
                    support=spike_lo,
                    spike_date=spike_d,
                    channel=channel,
                    under_support=True,
                )
                prim = pack.get("primary") or {}
                next_price = _num(prim.get("price"))
                next_source = str(prim.get("source") or "")
            except Exception:
                if channel_base > 0:
                    next_price = channel_base
                    next_source = "平行撐"
            if (next_price <= 0 or next_price >= spike_lo) and channel_base <= 0:
                # 無有效更低 NEXT／無通道下緣 → 只記基線
                if _ok(D9_FIRST, i):
                    collected.append(
                        _bar_pack(
                            bars,
                            i,
                            kind=KIND_D9,
                            variant=D9_FIRST,
                            level=spike_lo,
                            spike_hi=spike_hi,
                            spike_lo=spike_lo,
                            spike_date=spike_d,
                            next_source="",
                            next_price=0.0,
                            channel_pos=channel_pos,
                            stock_id=str(sid).strip(),
                            meta_json=json.dumps(
                                {"no_next": True}, ensure_ascii=False
                            ),
                        )
                    )
                    last_idx[D9_FIRST] = i
                    counts[D9_FIRST] += 1
                continue
            if next_price <= 0 or next_price >= spike_lo:
                next_price = channel_base
                next_source = "平行撐" if channel_base > 0 else next_source
            pending = {
                "as_of": _ymd(bars[i].get("date")),
                "_i": i,
                "spike_lo": spike_lo,
                "spike_hi": spike_hi,
                "spike_date": spike_d,
                "next_price": next_price,
                "next_source": next_source,
                "channel_pos": channel_pos,
                "channel_base": channel_base,
            }
            pending_expire = i + PATH_WITHIN + 10
    return collected


def SOURCE_CHANNEL_ALIASES() -> Tuple[str, ...]:
    try:
        from biaoke_next_support import SOURCE_CHANNEL, SOURCE_CHANNEL_DASH

        return (SOURCE_CHANNEL, SOURCE_CHANNEL_DASH, "平行撐", "通道下緣")
    except Exception:
        return ("平行撐", "通道下緣")


def score_event(
    event: Dict[str, Any],
    bars: Sequence[Dict[str, Any]],
    *,
    horizons: Sequence[int] = FORWARD_H,
) -> List[Dict[str, Any]]:
    """前瞻 h1／h3／h5；續跌／MAE／觸及下一撐。"""
    i = int(event.get("_i") if event.get("_i") is not None else -1)
    entry = _num(event.get("close"))
    next_px = _num(event.get("next_price"))
    kind = str(event.get("kind") or "")
    variant = str(event.get("variant") or "")
    day = _ymd(event.get("as_of"))
    sid = str(event.get("stock_id") or "").strip()
    out: List[Dict[str, Any]] = []
    # 中段→破轉移：D7 mid 變體附欄
    transferred = 0
    if kind == KIND_D7 and variant == D7_MID and i >= 0:
        for j in range(i + 1, min(len(bars), i + 1 + 20)):
            # 簡易：後窗收破事件 level（平行撐）
            lvl = _num(event.get("level"))
            if lvl > 0 and _num(bars[j].get("close")) < lvl:
                transferred = 1
                break
    for h in horizons:
        done = 0
        cont = 0
        ret = None
        min_low = None
        mae = None
        hit_next = 0
        if i >= 0 and i + int(h) < len(bars):
            done = 1
            fwd = bars[i + 1 : i + 1 + int(h)]
            lows = [_num(r.get("low")) for r in fwd]
            closes = [_num(r.get("close")) for r in fwd]
            min_low = min(lows) if lows else None
            last_c = closes[-1] if closes else 0.0
            if entry > 0 and last_c > 0:
                ret = (last_c / entry) - 1.0
                cont = 1 if last_c < entry else 0
            if entry > 0 and min_low is not None:
                mae = (min_low / entry) - 1.0
            if next_px > 0 and min_low is not None and min_low <= next_px + 1e-9:
                hit_next = 1
        out.append(
            {
                "kind": kind,
                "as_of": day,
                "stock_id": sid,
                "variant": variant,
                "horizon": int(h),
                "cont_down": cont,
                "ret": ret,
                "min_low": min_low,
                "mae": mae,
                "hit_next": hit_next,
                "transferred": transferred if int(h) == 5 else 0,
                "done": done,
            }
        )
    return out


def remember_event(db_path: str, event: Dict[str, Any]) -> None:
    if not event:
        return
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO biaoke_dcs_events (
                kind, as_of, stock_id, variant, level, spike_hi, spike_lo,
                spike_date, next_source, next_price, channel_pos, meta_json,
                close, o, h, l, c, v
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(event.get("kind") or ""),
                _ymd(event.get("as_of")),
                str(event.get("stock_id") or "").strip(),
                str(event.get("variant") or ""),
                _num(event.get("level")),
                _num(event.get("spike_hi")),
                _num(event.get("spike_lo")),
                _ymd(event.get("spike_date")),
                str(event.get("next_source") or ""),
                _num(event.get("next_price")),
                str(event.get("channel_pos") or ""),
                str(event.get("meta_json") or ""),
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
                INSERT OR REPLACE INTO biaoke_dcs_outcomes (
                    kind, as_of, stock_id, variant, horizon,
                    cont_down, ret, min_low, mae, hit_next, transferred, done
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(r.get("kind") or ""),
                    _ymd(r.get("as_of")),
                    str(r.get("stock_id") or "").strip(),
                    str(r.get("variant") or ""),
                    int(r.get("horizon") or 0),
                    int(r.get("cont_down") or 0),
                    r.get("ret"),
                    r.get("min_low"),
                    r.get("mae"),
                    int(r.get("hit_next") or 0),
                    int(r.get("transferred") or 0),
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


def _agg_from_outcomes(
    outcomes: Sequence[Dict[str, Any]],
    *,
    kind: str,
    holdout_from: str = "",
    in_holdout: Optional[bool] = None,
) -> Dict[str, Any]:
    tracks: Dict[str, Any] = {}
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    days: Dict[Tuple[str, int], set] = {}
    for r in outcomes:
        if str(r.get("kind") or "") != kind:
            continue
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
        downs = sum(1 for r in done_rows if int(r.get("cont_down") or 0) == 1)
        hits = sum(1 for r in done_rows if int(r.get("hit_next") or 0) == 1)
        xfers = sum(1 for r in done_rows if int(r.get("transferred") or 0) == 1)
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
            "cont_down_rate": (downs / nd) if nd else None,
            "hit_next_rate": (hits / nd) if nd else None,
            "transfer_rate": (xfers / nd) if nd else None,
            "mean_ret": (sum(rets) / len(rets)) if rets else None,
            "median_ret": _median(rets),
            "mean_mae": (sum(maes) / len(maes)) if maes else None,
            "gate_ready": udays >= MIN_UNIQUE_DAYS,
            "face": FACE_DEFAULT,
        }
    return tracks


def holdout_cut_ymd(days: Sequence[str]) -> str:
    uniq = sorted({_ymd(d) for d in days if _ymd(d)})
    if not uniq:
        return ""
    k = max(1, int(round(len(uniq) * 0.2)))
    return uniq[-k]


def gate_compare_d6(tracks: Dict[str, Any], *, horizon: int = 5) -> Dict[str, Any]:
    """出貨續跌應高於洗盤／僅破撐。"""

    def _get(v: str) -> Dict[str, Any]:
        return dict(tracks.get(f"{v}:h{horizon}") or {})

    cand = _get(D6_DIST)
    wash = _get(D6_WASH)
    brk = _get(D6_BREAK)
    nxt = _get(D6_NEXT)
    c = cand.get("cont_down_rate")
    w = wash.get("cont_down_rate")
    b = brk.get("cont_down_rate")
    n_ok = bool(cand.get("gate_ready")) and (
        bool(wash.get("gate_ready")) or bool(brk.get("gate_ready"))
    )
    beat_wash = c is not None and w is not None and float(c) > float(w)
    beat_brk = c is not None and b is not None and float(c) > float(b)
    # 對照軌：洗盤優先；無洗盤則比僅破撐
    beats = bool(n_ok and ((wash.get("gate_ready") and beat_wash) or (not wash.get("gate_ready") and beat_brk)))
    if wash.get("gate_ready") and brk.get("gate_ready"):
        beats = bool(n_ok and beat_wash and beat_brk)
    return {
        "horizon": horizon,
        "n_ok": n_ok,
        "candidate_unique_days": cand.get("unique_days"),
        "wash_unique_days": wash.get("unique_days"),
        "break_unique_days": brk.get("unique_days"),
        "next_unique_days": nxt.get("unique_days"),
        "cont_down_beats_wash": beat_wash,
        "cont_down_beats_break": beat_brk,
        "beats_baseline": beats,
        "face": False,
        "face_reason": "face_default_false; need n>=20 and beats + holdout + explicit promote",
        "next_variant": D6_NEXT,
    }


def gate_compare_d7(tracks: Dict[str, Any], *, horizon: int = 5) -> Dict[str, Any]:
    """破平行撐續跌應高於僅破大量區撐。"""

    def _get(v: str) -> Dict[str, Any]:
        return dict(tracks.get(f"{v}:h{horizon}") or {})

    cand = _get(D7_BREAK)
    base = _get(D7_BASE)
    mid = _get(D7_MID)
    nxt = _get(D7_NEXT)
    c = cand.get("cont_down_rate")
    b = base.get("cont_down_rate")
    n_ok = bool(cand.get("gate_ready")) and bool(base.get("gate_ready"))
    beat = c is not None and b is not None and float(c) > float(b)
    return {
        "horizon": horizon,
        "n_ok": n_ok,
        "candidate_unique_days": cand.get("unique_days"),
        "baseline_unique_days": base.get("unique_days"),
        "mid_unique_days": mid.get("unique_days"),
        "next_unique_days": nxt.get("unique_days"),
        "mid_transfer_rate": mid.get("transfer_rate"),
        "cont_down_beats": beat,
        "beats_baseline": bool(n_ok and beat),
        "face": False,
        "face_reason": "face_default_false; need n>=20 and beats + holdout + explicit promote",
        "next_variant": D7_NEXT,
    }


def gate_compare_d9(tracks: Dict[str, Any], *, horizon: int = 5) -> Dict[str, Any]:
    """第二段續跌／下探應深於僅一次破撐。"""

    def _get(v: str) -> Dict[str, Any]:
        return dict(tracks.get(f"{v}:h{horizon}") or {})

    cand = _get(D9_SECOND)
    base = _get(D9_FIRST)
    nxt = _get(D9_NEXT)
    c = cand.get("cont_down_rate")
    b = base.get("cont_down_rate")
    c_mae = cand.get("mean_mae")
    b_mae = base.get("mean_mae")
    n_ok = bool(cand.get("gate_ready")) and bool(base.get("gate_ready"))
    beat_cont = c is not None and b is not None and float(c) > float(b)
    # MAE 更負＝下探更深
    beat_mae = (
        c_mae is not None and b_mae is not None and float(c_mae) < float(b_mae)
    )
    beats = bool(n_ok and beat_cont and beat_mae)
    return {
        "horizon": horizon,
        "n_ok": n_ok,
        "candidate_unique_days": cand.get("unique_days"),
        "baseline_unique_days": base.get("unique_days"),
        "next_unique_days": nxt.get("unique_days"),
        "cont_down_beats": beat_cont,
        "mae_deeper": beat_mae,
        "beats_baseline": beats,
        "face": False,
        "face_reason": "face_default_false; need n>=20 and beats + holdout + explicit promote",
        "next_variant": D9_NEXT,
    }


def scan_stock_history(
    db_path: str,
    sid: str,
    *,
    max_events_per_variant: int = 0,
    persist: bool = True,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
    tracks: Sequence[str] = KINDS,
) -> Dict[str, Any]:
    rows = list(bars) if bars is not None else load_all_bars(db_path, sid)
    for b in rows:
        b["stock_id"] = str(sid).strip()
    collected: List[Dict[str, Any]] = []
    track_set = set(tracks)
    if KIND_D6 in track_set:
        collected.extend(
            scan_d6_stock(rows, sid, max_events_per_variant=max_events_per_variant)
        )
    if KIND_D7 in track_set:
        collected.extend(
            scan_d7_stock(rows, sid, max_events_per_variant=max_events_per_variant)
        )
    if KIND_D9 in track_set:
        collected.extend(
            scan_d9_stock(rows, sid, max_events_per_variant=max_events_per_variant)
        )
    scored: List[Dict[str, Any]] = []
    n_wrote = 0
    counts: Dict[str, int] = {}
    for ev in collected:
        outs = score_event(ev, rows)
        scored.extend(outs)
        vkey = f"{ev.get('kind')}:{ev.get('variant')}"
        counts[vkey] = counts.get(vkey, 0) + 1
        if persist:
            clean = {k: v for k, v in ev.items() if not str(k).startswith("_")}
            remember_event(db_path, clean)
            remember_outcomes(db_path, outs)
            n_wrote += 1
    return {
        "stock_id": sid,
        "events": collected,
        "outcomes": scored,
        "n_wrote": n_wrote,
        "counts": counts,
    }


def rates_summary(db_path: str, *, kind: str) -> Dict[str, Any]:
    ensure_tables(db_path)
    store = tape_store_path(db_path) if os.path.isfile(db_path) else db_path
    con = _conn(store)
    try:
        rows = con.execute(
            """
            SELECT variant, horizon,
                   COUNT(*) AS n,
                   SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) AS n_done,
                   SUM(CASE WHEN done=1 AND cont_down=1 THEN 1 ELSE 0 END) AS downs,
                   SUM(CASE WHEN done=1 AND hit_next=1 THEN 1 ELSE 0 END) AS hits,
                   SUM(CASE WHEN done=1 AND transferred=1 THEN 1 ELSE 0 END) AS xfers,
                   COUNT(DISTINCT as_of) AS days,
                   AVG(CASE WHEN done=1 THEN ret END) AS mean_ret,
                   AVG(CASE WHEN done=1 THEN mae END) AS mean_mae
            FROM biaoke_dcs_outcomes
            WHERE kind=?
            GROUP BY variant, horizon
            """,
            (kind,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    next_map = {
        KIND_D6: D6_NEXT,
        KIND_D7: D7_NEXT,
        KIND_D9: D9_NEXT,
    }
    out: Dict[str, Any] = {
        "kind": kind,
        "face": FACE_DEFAULT,
        "next_variant": next_map.get(kind, ""),
        "tracks": {},
    }
    for variant, horizon, n, n_done, downs, hits, xfers, days, mean_ret, mean_mae in rows:
        nd = int(n_done or 0)
        key = f"{variant}:h{horizon}"
        out["tracks"][key] = {
            "variant": variant,
            "horizon": int(horizon),
            "n": int(n or 0),
            "n_done": nd,
            "unique_days": int(days or 0),
            "cont_down_rate": (float(downs) / nd) if nd else None,
            "hit_next_rate": (float(hits) / nd) if nd else None,
            "transfer_rate": (float(xfers) / nd) if nd else None,
            "mean_ret": mean_ret,
            "mean_mae": mean_mae,
            "gate_ready": int(days or 0) >= MIN_UNIQUE_DAYS,
            "face": FACE_DEFAULT,
        }
    return out


def run_full_backtest(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 0,
    persist: bool = False,
    skip_busy: bool = True,
    tracks: Sequence[str] = KINDS,
) -> Dict[str, Any]:
    """全宇宙長窗回測（逐檔串流；預設不寫碟）。"""
    if skip_busy and in_busy_window():
        return {
            "ok": False,
            "skipped": "busy_window",
            "hhmm": _taipei_hhmm(),
            "kinds": list(tracks),
        }
    if persist:
        ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    if limit_stocks > 0:
        sids = sids[: int(limit_stocks)]
    all_outcomes: List[Dict[str, Any]] = []
    all_days: List[str] = []
    n_events: Dict[str, int] = {}
    t0 = time.time()
    for sid in sids:
        if skip_busy and in_busy_window():
            break
        pack = scan_stock_history(
            db_path,
            sid,
            max_events_per_variant=0,
            persist=persist,
            tracks=tracks,
        )
        for ev in pack.get("events") or []:
            k = f"{ev.get('kind')}:{ev.get('variant')}"
            n_events[k] = n_events.get(k, 0) + 1
            all_days.append(_ymd(ev.get("as_of")))
        all_outcomes.extend(pack.get("outcomes") or [])
    ho = holdout_cut_ymd(all_days)
    by_kind: Dict[str, Any] = {}
    for kind in tracks:
        tracks_all = _agg_from_outcomes(all_outcomes, kind=kind)
        tracks_train = _agg_from_outcomes(
            all_outcomes, kind=kind, holdout_from=ho, in_holdout=False
        )
        tracks_hold = _agg_from_outcomes(
            all_outcomes, kind=kind, holdout_from=ho, in_holdout=True
        )
        if kind == KIND_D6:
            gate_all = gate_compare_d6(tracks_all)
            gate_hold = gate_compare_d6(tracks_hold)
            next_v = D6_NEXT
        elif kind == KIND_D7:
            gate_all = gate_compare_d7(tracks_all)
            gate_hold = gate_compare_d7(tracks_hold)
            next_v = D7_NEXT
        else:
            gate_all = gate_compare_d9(tracks_all)
            gate_hold = gate_compare_d9(tracks_hold)
            next_v = D9_NEXT
        promote = bool(
            gate_all.get("beats_baseline")
            and gate_hold.get("beats_baseline")
            and gate_all.get("n_ok")
        )
        by_kind[kind] = {
            "face": FACE_DEFAULT,
            "promote_face": False,
            "would_pass_gate": promote,
            "next_variant": next_v,
            "tracks": tracks_all,
            "tracks_train": tracks_train,
            "tracks_holdout": tracks_hold,
            "gate": gate_all,
            "gate_holdout": gate_hold,
        }
    return {
        "ok": True,
        "face": FACE_DEFAULT,
        "stocks": len(sids),
        "event_counts": n_events,
        "holdout_from": ho,
        "elapsed_sec": round(time.time() - t0, 2),
        "kinds": by_kind,
        "definition": {
            "d6": "過壓後收掉回大量區撐下＝出貨；對照洗盤／僅破撐；下一版過壓日量門檻",
            "d7": "下降通道切入破平行撐；基線僅破大量區撐；下一版中段→破",
            "d9": "破大量區撐後再破 NEXT＝第二段；基線僅一次破撐；下一版 NEXT＝通道平行撐",
            "cooldown": EVENT_COOLDOWN,
            "holdout": "事件日排序末約20%",
        },
    }


def run_skeleton(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 40,
    max_events_per_stock: int = 20,
    skip_busy: bool = True,
    tracks: Sequence[str] = KINDS,
) -> Dict[str, Any]:
    if skip_busy and in_busy_window():
        return {
            "ok": False,
            "skipped": "busy_window",
            "hhmm": _taipei_hhmm(),
        }
    ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    prefer = ["3081", "3017", "3653", "2454", "2368"]
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
            tracks=tracks,
        )
        total += int(pack.get("n_wrote") or 0)
    summaries = {k: rates_summary(db_path, kind=k) for k in tracks}
    return {
        "ok": True,
        "events_written": total,
        "stocks": len(ordered),
        "elapsed_sec": round(time.time() - t0, 2),
        "face": FACE_DEFAULT,
        "tracks": summaries,
        "next_variants": {
            KIND_D6: D6_NEXT,
            KIND_D7: D7_NEXT,
            KIND_D9: D9_NEXT,
        },
    }


def snapshot_day(market_db: str, as_of: str = "", *, limit: int = 60) -> int:
    """當日三軌事件落檔（沒按也留）；失敗吞掉。"""
    try:
        day = _ymd(as_of)
        if not day:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(market_db))
        if not day:
            return 0
        if in_busy_window():
            sids = ["3081", "3017", "3653", "2454", "2368"]
        else:
            sids = list_stock_ids(market_db, limit=limit)
            for p in ("3081", "3017", "3653", "2454", "2368"):
                if p not in sids:
                    sids.insert(0, p)
        n = 0
        for sid in sids:
            bars = load_bars_thru(market_db, sid, day, need=LOOKBACK_BARS)
            if len(bars) < MIN_BARS:
                continue
            # 只評 as_of 當日：掃全窗但過濾 as_of
            pack = scan_stock_history(
                market_db,
                sid,
                max_events_per_variant=3,
                persist=False,
                bars=bars,
            )
            for ev in pack.get("events") or []:
                if _ymd(ev.get("as_of")) != day:
                    continue
                outs = [
                    o
                    for o in score_event(ev, bars)
                    if _ymd(o.get("as_of")) == day
                ]
                clean = {k: v for k, v in ev.items() if not str(k).startswith("_")}
                remember_event(market_db, clean)
                remember_outcomes(market_db, outs)
                n += 1
        return n
    except Exception:
        return 0
