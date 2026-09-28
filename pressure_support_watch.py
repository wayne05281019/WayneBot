# -*- coding: utf-8 -*-
"""壓撐觀察：同一顆鈕三種標籤（壓力橫盤／測壓未破／剛站上撐）。

只觀察，不是買訊。接既有 find_volume_zone；上市／上櫃／興櫃同一套。
只用官方日Ｋ原柱；盤中未收不當收。不准改黃金買點／海選進場。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from vol_zone_chart import VOL_ZONE_LOOKBACK, find_volume_zone, official_work

logger = logging.getLogger("WayneBot.PressureSupport")

# 大數據定案門檻（見 docs/pressure-support-three-tags-recommend.md）
SIDEWAYS_N = 2
TEST_PRESS_DIST_PCT = 0.5  # 收離壓 ≤0.5%
STAND_SUPPORT_W = 5
TEST_PRESS_TOUCH_MULT = 1.0  # 高 ≥ 壓

TAG_SIDEWAYS = "sideways"
TAG_TEST_PRESS = "test_press"
TAG_STAND_SUPPORT = "stand_support"

TAG_LABELS = {
    TAG_SIDEWAYS: "壓力橫盤",
    TAG_TEST_PRESS: "測壓未破",
    TAG_STAND_SUPPORT: "剛站上撐",
}

TAG_ORDER = (TAG_SIDEWAYS, TAG_TEST_PRESS, TAG_STAND_SUPPORT)

TAG_SUBTITLES = {
    TAG_SIDEWAYS: (
        f"同一大量區內，收在〔撐,壓〕恰好 {SIDEWAYS_N} 根日Ｋ。"
        "只觀察，不是買訊。"
    ),
    TAG_TEST_PRESS: (
        f"高≥壓、收≤壓且≥撐、收離壓≤{TEST_PRESS_DIST_PCT:g}%。"
        "量縮可加分不強制。只觀察，不是買訊。"
    ),
    TAG_STAND_SUPPORT: (
        f"從破撐回來後，收≥撐連站恰好 {STAND_SUPPORT_W} 根日Ｋ。"
        "只觀察，不是買訊。"
    ),
}

# 名單上限：話筒可讀、不塞爆
MAX_ROWS = 12
_LOOKBACK_CAL_DAYS = 120
# 同標籤短快取：連按／雙人不會重掃兩千檔（門檻／排序不變）
_SCREEN_TTL_SEC = 45.0
_SCREEN_LOCK = threading.Lock()
_SCREEN_CACHE: Dict[Tuple[str, str, str, int], Tuple[float, List[Dict[str, Any]]]] = {}


def clear_pressure_screen_cache() -> None:
    with _SCREEN_LOCK:
        _SCREEN_CACHE.clear()


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(str(tag or "").strip(), "")


def normalize_tag(raw: str) -> str:
    t = str(raw or "").strip()
    if t in TAG_LABELS:
        return t
    for key, label in TAG_LABELS.items():
        if t == label:
            return key
    aliases = {
        "橫盤": TAG_SIDEWAYS,
        "壓力": TAG_SIDEWAYS,
        "測壓": TAG_TEST_PRESS,
        "未破": TAG_TEST_PRESS,
        "站上撐": TAG_STAND_SUPPORT,
        "剛站": TAG_STAND_SUPPORT,
        "stand": TAG_STAND_SUPPORT,
        "test": TAG_TEST_PRESS,
        "side": TAG_SIDEWAYS,
    }
    return aliases.get(t, "")


def _ymd(val: Any) -> str:
    s = str(val or "").replace("-", "").replace("/", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _px(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def classify_bars(
    work: pd.DataFrame,
    zone: Dict[str, Any],
    *,
    tag: str,
) -> Optional[Dict[str, Any]]:
    """依最後一根官方收判斷是否符合指定標籤。zone＝find_volume_zone 結果。"""
    if work is None or getattr(work, "empty", True) or not zone:
        return None
    tag = normalize_tag(tag) or str(tag or "").strip()
    hi = _px(zone.get("high"))
    lo = _px(zone.get("low"))
    zd = _ymd(zone.get("date"))
    if hi <= 0 or lo <= 0 or hi < lo or not zd:
        return None
    dates = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    closes = pd.to_numeric(work["close"], errors="coerce")
    highs = pd.to_numeric(work["high"], errors="coerce")
    vols = (
        pd.to_numeric(work["volume"], errors="coerce").fillna(0.0)
        if "volume" in work.columns
        else pd.Series(0.0, index=work.index)
    )
    halt = (
        work["is_halt"].fillna(False).astype(bool)
        if "is_halt" in work.columns
        else pd.Series(False, index=work.index)
    )
    n = len(work)
    i = n - 1
    if halt.iloc[i]:
        return None
    cl = float(closes.iloc[i] or 0)
    hi_bar = float(highs.iloc[i] or 0)
    last_d = _ymd(dates.iloc[i])
    if cl <= 0 or not last_d or last_d <= zd:
        return None

    def _same_zone_streak_in_band() -> int:
        """同參考日壓撐下，從最新往回連續收在〔撐,壓〕天數。"""
        streak = 0
        for k in range(i, -1, -1):
            if halt.iloc[k]:
                break
            dk = _ymd(dates.iloc[k])
            if not dk or dk <= zd:
                break
            ck = float(closes.iloc[k] or 0)
            if lo <= ck <= hi:
                streak += 1
            else:
                break
        return streak

    def _stand_streak() -> Tuple[int, bool]:
        """收≥撐連站天數；回傳 (streak, from_break_ok)。

        對齊掃檔：連站前一根若在參考日之後且收仍≥撐 → 不是剛站上；
        前一根是參考日邊界則可起算。
        """
        streak = 0
        for k in range(i, -1, -1):
            if halt.iloc[k]:
                break
            dk = _ymd(dates.iloc[k])
            if not dk or dk <= zd:
                break
            ck = float(closes.iloc[k] or 0)
            if ck >= lo:
                streak += 1
            else:
                break
        if streak <= 0:
            return 0, False
        start = i - streak + 1
        ok = True
        if start - 1 >= 0:
            prev_d = _ymd(dates.iloc[start - 1])
            if prev_d and prev_d > zd and not bool(halt.iloc[start - 1]):
                if float(closes.iloc[start - 1] or 0) >= lo:
                    ok = False
        return streak, ok

    zone_vol = _px(zone.get("volume"))
    last_vol = float(vols.iloc[i] or 0)
    vol_ratio = (last_vol / zone_vol) if zone_vol > 0 and last_vol > 0 else 0.0
    dist_pct = ((hi - cl) / hi * 100.0) if hi > 0 else 99.0

    meta: Dict[str, Any] = {
        "tag": tag,
        "tag_label": tag_label(tag) or tag,
        "zone_date": zd,
        "pressure": hi,
        "support": lo,
        "close": cl,
        "high": hi_bar,
        "volume": int(last_vol),
        "vol_ratio": round(vol_ratio, 4),
        "dist_to_press_pct": round(dist_pct, 4),
        "as_of": last_d,
        "zone_active": bool(zone.get("active")),
    }

    if tag == TAG_SIDEWAYS:
        if not (lo <= cl <= hi):
            return None
        streak = _same_zone_streak_in_band()
        if streak != SIDEWAYS_N:
            return None
        meta["streak"] = streak
        meta["why"] = f"同區橫盤滿{SIDEWAYS_N}根"
        return meta

    if tag == TAG_TEST_PRESS:
        if hi_bar < hi * TEST_PRESS_TOUCH_MULT:
            return None
        if cl > hi or cl < lo:
            return None
        if dist_pct > TEST_PRESS_DIST_PCT + 1e-9:
            return None
        meta["streak"] = 1
        thin = vol_ratio > 0 and vol_ratio < 0.35
        meta["vol_thin_bonus"] = bool(thin)
        meta["why"] = (
            f"測壓貼壓{dist_pct:.2f}%" + ("、量縮加分" if thin else "")
        )
        return meta

    if tag == TAG_STAND_SUPPORT:
        streak, came = _stand_streak()
        if streak != STAND_SUPPORT_W or not came:
            return None
        meta["streak"] = streak
        meta["in_band"] = bool(cl <= hi)
        meta["why"] = f"破撐回來連站{STAND_SUPPORT_W}根"
        return meta

    return None


def _universe_ids(db_path: str) -> List[Tuple[str, str]]:
    """活躍 STOCK（上市／上櫃／興櫃）。"""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT stock_id, IFNULL(stock_name,'')
            FROM stock_universe
            WHERE is_active=1 AND UPPER(IFNULL(asset_type,''))='STOCK'
            ORDER BY stock_id
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out: List[Tuple[str, str]] = []
    for sid, name in rows:
        s = str(sid or "").strip()
        if not s:
            continue
        try:
            from universe import is_screen_equity

            if not is_screen_equity(s, str(name or "")):
                continue
        except Exception:
            pass
        out.append((s, str(name or "")))
    return out


def _load_frames(
    db_path: str, as_of: str, codes: Sequence[str]
) -> Dict[str, pd.DataFrame]:
    """批量讀官方日Ｋ（daily_quotes + emerging_quotes），不含未收／假柱。"""
    codes = [str(c).strip() for c in codes if str(c).strip()]
    as_of = _ymd(as_of)
    if not codes or not as_of:
        return {}
    lo = ""
    try:
        lo = (
            datetime.strptime(as_of, "%Y%m%d") - timedelta(days=_LOOKBACK_CAL_DAYS)
        ).strftime("%Y%m%d")
    except ValueError:
        lo = ""
    conn = sqlite3.connect(db_path, timeout=60.0)
    frames: Dict[str, pd.DataFrame] = {}
    try:
        conn.execute("PRAGMA busy_timeout=15000;")
        placeholders = ",".join("?" * len(codes))
        params: List[Any] = list(codes) + [as_of]
        extra = " AND REPLACE(date,'-','') <= ?"
        if lo:
            extra += " AND REPLACE(date,'-','') >= ?"
            params.append(lo)
        for table in ("daily_quotes", "emerging_quotes"):
            try:
                df = pd.read_sql_query(
                    f"""
                    SELECT stock_id, stock_name, date, open, high, low, close, volume
                    FROM {table}
                    WHERE stock_id IN ({placeholders}) AND close > 0{extra}
                    ORDER BY stock_id, date
                    """,
                    conn,
                    params=params,
                )
            except Exception:
                continue
            if df is None or df.empty:
                continue
            df["date"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
            for sid, g in df.groupby("stock_id"):
                key = str(sid)
                if key in frames:
                    continue  # 已有上市櫃就不用興櫃撞號
                g = g.reset_index(drop=True)
                if str(g["date"].iloc[-1] or "")[:8] != as_of:
                    continue
                frames[key] = g
    finally:
        conn.close()
    return frames


def _ex_events_for(sid: str, db_path: str, d0: str, d1: str) -> List[Dict[str, Any]]:
    try:
        from ex_rights import load_scale_ex_events

        return list(load_scale_ex_events(sid, db_path, d0, d1) or [])
    except Exception:
        return []


def light_work(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """篩選用輕量整理：官方柱升冪＋停牌旗，不跑開市日對齊（對齊太慢）。

    出圖仍走 vol_zone_chart.official_work。
    """
    if df is None or getattr(df, "empty", True):
        return None
    work = df.copy()
    if "is_live" in work.columns:
        work = work.loc[~work["is_live"].fillna(False).astype(bool)].copy()
    if "source" in work.columns:
        work = work.loc[work["source"].astype(str) != "biaoke_stock_day"].copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in work.columns:
            return None
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["date"] = work["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    work = work.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if work.empty:
        return None
    work = work.sort_values("date", kind="mergesort").reset_index(drop=True)
    ok = (
        (work["close"] > 0)
        & (work["high"] > 0)
        & (work["low"] > 0)
        & (work["high"] >= work["low"])
    )
    work = work.loc[ok].reset_index(drop=True)
    if work.empty:
        return None
    vol = work["volume"].fillna(0.0)
    flat = (vol <= 0) & ((work["high"] - work["low"]).abs() <= 1e-8)
    work["is_halt"] = flat.fillna(False)
    return work


def classify_frame(
    df: pd.DataFrame,
    *,
    tag: str,
    db_path: str = "",
    sid: str = "",
    fast: bool = True,
) -> Optional[Dict[str, Any]]:
    work = light_work(df) if fast else official_work(df)
    if work is None or work.empty or len(work) < VOL_ZONE_LOOKBACK + SIDEWAYS_N + 2:
        return None
    d0 = _ymd(work["date"].iloc[0])
    d1 = _ymd(work["date"].iloc[-1])
    # 篩選預設略過逐檔除權息 HTTP；尺度切窗仍可用庫內已有事件（空列表＝不切）
    ex: List[Dict[str, Any]] = []
    if sid and db_path and not fast:
        ex = _ex_events_for(sid, db_path, d0, d1)
    zone = find_volume_zone(work, ex_events=ex or None)
    if not zone:
        return None
    if _ymd(zone.get("date")) >= d1:
        return None
    return classify_bars(work, zone, tag=tag)


def screen_pressure_support(
    db_path: str,
    tag: str,
    *,
    as_of: str = "",
    max_rows: int = MAX_ROWS,
) -> List[Dict[str, Any]]:
    """掃活躍 STOCK，回傳符合標籤的觀察名單（非買訊）。"""
    tag = normalize_tag(tag)
    if not tag or not db_path:
        return []
    if not as_of:
        try:
            from import_health import latest_complete_quote_date

            as_of = str(latest_complete_quote_date(db_path) or "")
        except Exception:
            as_of = ""
    as_of = _ymd(as_of)
    if not as_of:
        return []
    cache_key = (str(db_path), tag, as_of, int(max_rows or MAX_ROWS))
    now = time.monotonic()
    with _SCREEN_LOCK:
        hit = _SCREEN_CACHE.get(cache_key)
        if hit and now - hit[0] <= _SCREEN_TTL_SEC:
            # 淺拷貝列，避免呼叫端改到快取
            return [dict(r) for r in hit[1]]
    universe = _universe_ids(db_path)
    if not universe:
        return []
    codes = [s for s, _ in universe]
    name_map = {s: n for s, n in universe}
    frames = _load_frames(db_path, as_of, codes)
    out: List[Dict[str, Any]] = []
    for sid, df in frames.items():
        try:
            hit_row = classify_frame(df, tag=tag, db_path=db_path, sid=sid)
        except Exception:
            logger.debug("pressure classify fail %s", sid, exc_info=True)
            hit_row = None
        if not hit_row:
            continue
        name = str(name_map.get(sid) or "")
        if not name and "stock_name" in df.columns:
            name = str(df["stock_name"].iloc[-1] or "")
        item = {
            "stock_id": sid,
            "code": sid,
            "stock_name": name,
            "name": name,
            "close": hit_row.get("close"),
            "volume": hit_row.get("volume"),
            "as_of": hit_row.get("as_of") or as_of,
            "bucket_key": f"pressure_{tag}",
            "entry_stage_label": tag_label(tag),
            "tag": tag,
            "tag_label": tag_label(tag),
            "pressure": hit_row.get("pressure"),
            "support": hit_row.get("support"),
            "zone_date": hit_row.get("zone_date"),
            "dist_to_press_pct": hit_row.get("dist_to_press_pct"),
            "vol_ratio": hit_row.get("vol_ratio"),
            "vol_thin_bonus": hit_row.get("vol_thin_bonus"),
            "streak": hit_row.get("streak"),
            "why": hit_row.get("why"),
            "pattern": hit_row.get("why"),
            # 明確不是買訊：不給進場星等／買門
            "entry_stars": 0,
            "buy_gate": "no",
            "buy_gate_note": "壓撐觀察不是買訊",
        }
        out.append(item)
    # 排序：測壓貼壓近的優先；橫盤／站上撐按離壓近、量縮
    def _key(r: Dict[str, Any]):
        dist = float(r.get("dist_to_press_pct") or 99)
        thin = 0 if r.get("vol_thin_bonus") else 1
        return (dist, thin, str(r.get("stock_id") or ""))

    out.sort(key=_key)
    out = out[: max(1, int(max_rows or MAX_ROWS))]
    with _SCREEN_LOCK:
        _SCREEN_CACHE[cache_key] = (time.monotonic(), [dict(r) for r in out])
    return out


def pressure_card_html(item: Dict[str, Any], idx: int) -> str:
    """觀察名單卡：單位對齊、不寫買訊星等。"""
    from html import escape as html_escape

    from tg_layout import html_qty_tight
    from wayne_navigator import _fmt_price

    sid = str(item.get("stock_id") or item.get("code") or "")
    sname = str(item.get("stock_name") or item.get("name") or "")
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(sid, sname)
    except Exception:
        title = f"{html_escape(sid)} {html_escape(sname)}"
    tag_l = html_escape(str(item.get("tag_label") or tag_label(str(item.get("tag") or "")) or "壓撐觀察"))
    close_s = _fmt_price(item.get("close"))
    press_s = _fmt_price(item.get("pressure"))
    supp_s = _fmt_price(item.get("support"))
    vol = int(item.get("volume") or 0)
    dist = item.get("dist_to_press_pct")
    try:
        dist_s = f"{float(dist):.2f}%"
    except (TypeError, ValueError):
        dist_s = "—"
    why = html_escape(str(item.get("why") or "").strip())
    zd = _ymd(item.get("zone_date"))
    zd_s = f"{zd[4:6]}/{zd[6:8]}" if zd else "—"
    lines = [
        f"<b>{idx}.</b> {title}",
        f"標籤　{tag_l}　大量區　{zd_s}",
        f"收盤　{close_s}　壓　{press_s}　撐　{supp_s}",
        f"離壓　{dist_s}　量能　{html_qty_tight(vol, signed=False)}",
    ]
    if why:
        lines.append(f"說明　{why}")
    lines.append("<i>只觀察，不是買訊。</i>")
    return "\n".join(lines)
