# -*- coding: utf-8 -*-
"""蕭氏實驗室：各檔「真實最長」日 K 補齊（雲端；不上話筒）。

規則：
- 不准捏 OHLC。官方能給多長就抓多長；證交所深史被擋則改用 Yahoo 長史寫 lab_daily，
  source／adj_kind 標清楚，並與庫內官方短窗對齊核對。
- 不足 20 年＝用該檔實際最長窗測，摘要寫明 years／source／n_bars。
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from scripts.decade_lab_freeze import ensure_lab_schema, upsert_lab_bars
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, select_g_universe

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = ROOT / "data" / "wayne_market.db"
LAB_DB = ROOT / "data" / "decade_lab.db"
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TARGET_START = "20060101"  # 試 20y；抓不到就停在官方／Yahoo 實際起點
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot-lab/1.0"})


def _now_tp() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))


def _yahoo_symbol(sid: str, market: str) -> str:
    m = str(market or "TW").upper()
    if m in ("TWO", "OTC", "OT", "TPEX"):
        return f"{sid}.TWO"
    return f"{sid}.TW"


def fetch_yahoo_daily_period(
    sym: str,
    *,
    start_ymd: str = TARGET_START,
    end_ymd: Optional[str] = None,
    tz_name: str = "Asia/Taipei",
) -> List[Dict[str, Any]]:
    """Yahoo 日 K（period1/period2）；失敗回空。不是證交所官方柱。"""
    start = str(start_ymd or TARGET_START).replace("-", "")[:8]
    if end_ymd:
        end = str(end_ymd).replace("-", "")[:8]
    else:
        end = _now_tp().strftime("%Y%m%d")
    try:
        p1 = int(
            datetime(int(start[:4]), int(start[4:6]), int(start[6:8]), tzinfo=timezone.utc).timestamp()
        )
        p2 = int(
            datetime(int(end[:4]), int(end[4:6]), int(end[6:8]), 23, 59, tzinfo=timezone.utc).timestamp()
        )
    except Exception:
        return []
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1d&period1={p1}&period2={p2}"
    )
    try:
        resp = _SESSION.get(url, timeout=45)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
    except Exception:
        return []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    adj_list = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    tz = ZoneInfo(tz_name)

    def _f(arr, idx, default=None):
        if not arr or idx >= len(arr) or arr[idx] is None:
            return default
        try:
            return float(arr[idx])
        except (TypeError, ValueError):
            return default

    out: List[Dict[str, Any]] = []
    for i, ts in enumerate(stamps):
        c = _f(q.get("close"), i, None)
        if c is None or c <= 0:
            continue
        day = datetime.fromtimestamp(int(ts), tz=ZoneInfo("UTC")).astimezone(tz)
        out.append(
            {
                "date": day.strftime("%Y%m%d"),
                "open": _f(q.get("open"), i, c),
                "high": _f(q.get("high"), i, c),
                "low": _f(q.get("low"), i, c),
                "close": c,
                "volume": _f(q.get("volume"), i, 0.0) or 0.0,
                "adj_close": _f(adj_list, i, None),
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def _official_span(sid: str) -> Dict[str, Any]:
    con = sqlite3.connect(MARKET_DB)
    row = con.execute(
        """
        SELECT MIN(date), MAX(date), COUNT(*),
               SUM(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END)
        FROM daily_quotes WHERE stock_id=?
        """,
        (str(sid),),
    ).fetchone()
    con.close()
    d0, d1, n, nulls = row or (None, None, 0, 0)
    years = float("nan")
    if d0 and d1 and len(str(d0)) >= 8 and len(str(d1)) >= 8:
        try:
            a = datetime.strptime(str(d0).replace("-", "")[:8], "%Y%m%d")
            b = datetime.strptime(str(d1).replace("-", "")[:8], "%Y%m%d")
            years = (b - a).days / 365.25
        except Exception:
            years = float("nan")
    return {
        "d0": d0,
        "d1": d1,
        "n": int(n or 0),
        "null_ohlc": int(nulls or 0),
        "years": years,
    }


def _overlap_audit(sid: str, yahoo_bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """官方短窗 vs Yahoo 同日收盤對齊；差距過大標 suspicious，不准當過關。"""
    if not yahoo_bars:
        return {"ok": False, "reason": "no_yahoo"}
    ymap = {str(b["date"])[:8]: float(b["close"]) for b in yahoo_bars if b.get("close")}
    con = sqlite3.connect(MARKET_DB)
    off = pd.read_sql(
        "SELECT replace(date,'-','') AS d, close FROM daily_quotes WHERE stock_id=? ORDER BY date",
        con,
        params=(str(sid),),
    )
    con.close()
    if off is None or len(off) == 0:
        return {"ok": False, "reason": "no_official"}
    diffs = []
    for _, r in off.iterrows():
        d = str(r["d"])[:8]
        if d not in ymap:
            continue
        oc = float(r["close"])
        yc = float(ymap[d])
        if oc > 0 and yc > 0:
            diffs.append(abs(yc / oc - 1.0))
    if not diffs:
        return {"ok": False, "reason": "no_overlap_days", "n_official": int(len(off))}
    arr = np.asarray(diffs, dtype=float)
    med = float(np.median(arr))
    p90 = float(np.quantile(arr, 0.90))
    # 還原差異常見；中位相對差 > 8% 才當可疑（拆分／錯誤代號）
    ok = med <= 0.08
    return {
        "ok": ok,
        "n_overlap": int(len(arr)),
        "median_abs_pct": med,
        "p90_abs_pct": p90,
        "suspicious": (not ok),
    }


def backfill_otc_official_months(
    sid: str,
    *,
    market: str,
    name: str,
    start_ym: str = "200601",
    sleep_s: float = 0.35,
    empty_stop: int = 8,
) -> Dict[str, Any]:
    """上櫃／興櫃：櫃買月表官方日 K 往回補到連續空月為止。"""
    from biaoke_walk import fetch_stock_month, upsert_fetched_quotes

    y0, m0 = int(start_ym[:4]), int(start_ym[4:6])
    now = _now_tp()
    y1, m1 = now.year, now.month
    months: List[str] = []
    y, m = y0, m0
    while (y < y1) or (y == y1 and m <= m1):
        months.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    # 由近到遠：先確認近窗，再往古推；連續 empty_stop 個月空＝到頂
    months_rev = list(reversed(months))
    ok_m = 0
    none_m = 0
    rows_n = 0
    empty_streak = 0
    first = None
    last = None
    stopped = None
    for ym in months_rev:
        # 已有該月官方列就略過網路
        con = sqlite3.connect(MARKET_DB)
        have = con.execute(
            """
            SELECT COUNT(*) FROM daily_quotes
            WHERE stock_id=? AND substr(replace(date,'-',''),1,6)=?
            """,
            (sid, ym),
        ).fetchone()[0]
        con.close()
        if int(have or 0) >= 5:
            ok_m += 1
            empty_streak = 0
            continue
        rows = fetch_stock_month(sid, ym, market=market, name=name, tries=2)
        if not rows:
            none_m += 1
            empty_streak += 1
            if empty_streak >= empty_stop and ok_m > 0:
                stopped = ym
                break
            time.sleep(sleep_s)
            continue
        n = int(upsert_fetched_quotes(str(MARKET_DB), rows) or 0)
        rows_n += n
        ok_m += 1
        empty_streak = 0
        first = rows[0]["date"] if first is None else min(first, rows[0]["date"])
        last = rows[-1]["date"] if last is None else max(last, rows[-1]["date"])
        time.sleep(sleep_s)
    return {
        "sid": sid,
        "months_ok": ok_m,
        "months_none": none_m,
        "rows_upserted": rows_n,
        "stopped_empty_ym": stopped,
        "first": first,
        "last": last,
        "source": "tpex_tradingStock_official",
    }


def fill_symbol(
    sid: str,
    *,
    name: str,
    market: str,
    prefer_otc_official: bool = True,
) -> Dict[str, Any]:
    ensure_lab_schema(LAB_DB)
    before = _official_span(sid)
    otc_stats = None
    if prefer_otc_official and str(market).upper() in ("TWO", "OTC", "OT", "TPEX"):
        otc_stats = backfill_otc_official_months(sid, market="TWO", name=name)

    sym = _yahoo_symbol(sid, market)
    ybars = fetch_yahoo_daily_period(sym, start_ymd=TARGET_START)
    overlap = _overlap_audit(sid, ybars)
    wrote = 0
    if ybars and overlap.get("ok"):
        # 覆寫 upsert：標 yahoo_lab（沿用 freeze 的 raw + adj 兩列）
        wrote = upsert_lab_bars(
            LAB_DB,
            symbol=str(sid),
            pack="hsiao_max_history",
            tz_rule="Asia/Taipei; yahoo長史；非TWSE官方柱；已與官方短窗對齊",
            bars=ybars,
        )
    elif ybars and not overlap.get("ok"):
        # 仍寫入但標 suspicious，測試可選排除
        wrote = upsert_lab_bars(
            LAB_DB,
            symbol=str(sid),
            pack="hsiao_max_history_suspicious",
            tz_rule="Asia/Taipei; yahoo長史；對齊可疑；測前先核",
            bars=ybars,
        )

    after = _official_span(sid)
    lab_n = 0
    lab_d0 = lab_d1 = None
    con = sqlite3.connect(LAB_DB)
    row = con.execute(
        """
        SELECT MIN(date), MAX(date), COUNT(*) FROM lab_daily
        WHERE symbol=? AND adj_kind='yahoo_adjclose'
        """,
        (str(sid),),
    ).fetchone()
    con.close()
    if row:
        lab_d0, lab_d1, lab_n = row[0], row[1], int(row[2] or 0)
    years = float("nan")
    if lab_d0 and lab_d1:
        try:
            a = datetime.strptime(str(lab_d0)[:8], "%Y%m%d")
            b = datetime.strptime(str(lab_d1)[:8], "%Y%m%d")
            years = (b - a).days / 365.25
        except Exception:
            years = float("nan")

    return {
        "stock_id": sid,
        "name": name,
        "market": market,
        "yahoo_symbol": sym,
        "official_before": before,
        "official_after": after,
        "otc_official_backfill": otc_stats,
        "yahoo_n": len(ybars),
        "yahoo_d0": ybars[0]["date"] if ybars else None,
        "yahoo_d1": ybars[-1]["date"] if ybars else None,
        "lab_yahoo_adj_n": lab_n,
        "lab_yahoo_adj_d0": lab_d0,
        "lab_yahoo_adj_d1": lab_d1,
        "lab_years": years,
        "overlap": overlap,
        "lab_rows_written": wrote,
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
    }


def run_fill(*, n_universe: int = 100, sleep_s: float = 0.2) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    ensure_lab_schema(LAB_DB)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    # market from directory
    con = sqlite3.connect(MARKET_DB)
    mk = {
        str(r[0]): str(r[1] or "TW")
        for r in con.execute("SELECT stock_id, market FROM stock_directory").fetchall()
    }
    con.close()

    rows = []
    for r in uni.itertuples():
        sid = str(r.stock_id)
        name = str(getattr(r, "stock_name", None) or MUST_INCLUDE.get(sid) or sid)
        market = mk.get(sid, "TW")
        if sid in MUST_INCLUDE and market == "TW":
            # 點名檔：上櫃代號校正
            if sid in ("6274", "3081", "8299"):
                market = "TWO"
        info = fill_symbol(sid, name=name, market=market)
        rows.append(info)
        print(
            f"{sid} {name} years={info.get('lab_years')} n={info.get('lab_yahoo_adj_n')} "
            f"overlap_ok={info.get('overlap', {}).get('ok')} off_n={info.get('official_after', {}).get('n')}",
            flush=True,
        )
        time.sleep(sleep_s)

    # 誠實摘要：實際年數分布
    years = [float(x["lab_years"]) for x in rows if np.isfinite(x.get("lab_years", np.nan))]
    sus = [x["stock_id"] for x in rows if x.get("overlap", {}).get("suspicious")]
    summary = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_symbols": len(rows),
        "target_start_attempt": TARGET_START,
        "lab_years_min": float(np.min(years)) if years else None,
        "lab_years_median": float(np.median(years)) if years else None,
        "lab_years_max": float(np.max(years)) if years else None,
        "n_overlap_ok": sum(1 for x in rows if x.get("overlap", {}).get("ok")),
        "n_suspicious": len(sus),
        "suspicious_ids": sus,
        "must_named": {sid: next((x for x in rows if x["stock_id"] == sid), None) for sid in MUST_INCLUDE},
        "note_zh": "不足20年用該檔真實最長窗；Yahoo 長史非官方柱，已與官方短窗對齊；不上話筒",
        "rows": rows,
    }
    out_json = DOC / "hsiao_max_history_fill_latest.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "hsiao_max_history_fill_latest.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "SUMMARY",
        json.dumps({k: summary[k] for k in summary if k != "rows"}, ensure_ascii=False),
        flush=True,
    )
    return summary


if __name__ == "__main__":
    run_fill()
