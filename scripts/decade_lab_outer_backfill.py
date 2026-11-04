#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年／大盤活資料｜外圍＋美股領導長史落 index_daily（靜默）。

正反一起想：預測要齊、覆盤歸因也要齊。目前 ``us_overnight`` 只有十來天 payload，
油／匯／VIX／道瓊／標普／台積美股／輝達／那指期 **沒有獨立長史日表** → 這裡補進
``index_daily``（精簡 OHLC＋量；標明 yahoo；不准當官方 TWSE 柱）。

仍缺、之後另補（不在本檔硬塞假數）：
- 主動 ETF／投信賣壓日流
- CNN 恐懼貪婪長史表
- 電子期 TE 長史、期貨法人 OI 長史（TAIFEX）
- 融資餘額更長官方窗（MI_MARGN 續跑）

不是買訊。不准寫回話筒／黃金買點。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (compatible; WayneBot-decade-outer/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

# symbol_in_db, yahoo_ticker, note
# 約 20 年重抓：上一輪十年窗＋舊規則找不出脈絡＝切法不對，不是沒資訊。
OUTER_SERIES: Tuple[Tuple[str, str, str], ...] = (
    ("TWII", "^TWII", "加權（Yahoo 補長史；話筒仍認官方融合柱）"),
    ("IXIC", "^IXIC", "那指"),
    ("SOX", "^SOX", "費半"),
    ("VIX", "^VIX", "恐慌指數"),
    ("DJI", "^DJI", "道瓊"),
    ("SPX", "^GSPC", "標普"),
    ("BRENT", "BZ=F", "布蘭特原油"),
    ("DXY", "DX-Y.NYB", "美元指數"),
    ("USDTWD", "TWD=X", "美元兌台幣"),
    ("TSM", "TSM", "台積美股"),
    ("NVDA", "NVDA", "輝達"),
    ("NQ_F", "NQ=F", "那指期"),
    ("ES_F", "ES=F", "標普期"),
)

STILL_MISSING = [
    "active_etf_flow_daily（主動 ETF／投信賣壓日流）",
    "fear_greed_daily（CNN 恐懼貪婪長史）",
    "TE futures 長史（現僅近窗）",
    "futures_inst_oi 長史（現僅近窗）",
    "market_margin_daily 更長窗（MI_MARGN 續補）",
    "market_tape_daily 2006–2016（FMTQIK 月檔續補）",
]


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def ensure_index(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            close REAL,
            volume REAL,
            pct_change REAL,
            ma20 REAL,
            ma60 REAL,
            regime TEXT,
            updated_at TEXT,
            open REAL,
            high REAL,
            low REAL,
            PRIMARY KEY (date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_index_daily_sym ON index_daily(symbol, date);
        """
    )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(index_daily)")}
    for name, typ in (("open", "REAL"), ("high", "REAL"), ("low", "REAL"), ("updated_at", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE index_daily ADD COLUMN {name} {typ}")


def fetch_yahoo(sym: str, range_: str = "10y") -> List[Dict[str, Any]]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1d&range={range_}"
    )
    try:
        resp = SESSION.get(url, timeout=45)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
    except Exception:
        return []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    vols = q.get("volume") or []
    out: List[Dict[str, Any]] = []
    prev = None
    for i, ts in enumerate(stamps):
        c = _f(closes[i]) if i < len(closes) else None
        if c is None or c <= 0:
            continue
        # 美股／外圍用美東日；匯／油同欄
        d = datetime.fromtimestamp(int(ts), tz=ZoneInfo("UTC")).astimezone(NY)
        ymd = d.strftime("%Y%m%d")
        pct = (c / prev - 1.0) * 100.0 if prev and prev > 0 else None
        out.append(
            {
                "date": ymd,
                "open": _f(opens[i]) if i < len(opens) else c,
                "high": _f(highs[i]) if i < len(highs) else c,
                "low": _f(lows[i]) if i < len(lows) else c,
                "close": c,
                "volume": _f(vols[i]) if i < len(vols) else None,
                "pct_change": pct,
            }
        )
        prev = c
    return out


def upsert_bars(
    conn: sqlite3.Connection, symbol: str, bars: Sequence[Dict[str, Any]], *, stamp: str
) -> int:
    """寫入精簡數字柱。TWII／已有官方列：只補缺日，不准覆寫官方開高低收量。"""
    wrote = 0
    protect = symbol in {"TWII"}
    for b in bars:
        day = str(b.get("date") or "")
        c = _f(b.get("close"))
        if len(day) != 8 or not c or c <= 0:
            continue
        if protect:
            exists = conn.execute(
                "SELECT 1 FROM index_daily WHERE date=? AND symbol=? LIMIT 1",
                (day, symbol),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, pct_change, regime, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    day,
                    symbol,
                    _f(b.get("open")),
                    _f(b.get("high")),
                    _f(b.get("low")),
                    c,
                    _f(b.get("volume")),
                    _f(b.get("pct_change")),
                    "yahoo_gapfill_20y",
                    stamp,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, pct_change, regime, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    pct_change=excluded.pct_change, regime=excluded.regime,
                    updated_at=excluded.updated_at
                """,
                (
                    day,
                    symbol,
                    _f(b.get("open")),
                    _f(b.get("high")),
                    _f(b.get("low")),
                    c,
                    _f(b.get("volume")),
                    _f(b.get("pct_change")),
                    "yahoo_outer",
                    stamp,
                ),
            )
        wrote += 1
    return wrote


def backfill_all(db_path: Path, *, range_: str = "10y", sleep_s: float = 0.12) -> Dict[str, Any]:
    if not db_path.parent.is_dir():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _now()
    out: Dict[str, Any] = {
        "written_at": stamp,
        "tz": "Asia/Taipei",
        "range": range_,
        "series": {},
        "still_missing": list(STILL_MISSING),
        "note": "yahoo 外圍／美股領導長史→index_daily；非 TWSE 官方柱；不是買訊",
    }
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_index(conn)
        for i, (sym, yahoo, note) in enumerate(OUTER_SERIES):
            print(f"… {sym} ({yahoo}) {note}", flush=True)
            bars = fetch_yahoo(yahoo, range_=range_)
            wrote = upsert_bars(conn, sym, bars, stamp=stamp) if bars else 0
            conn.commit()
            n = conn.execute(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM index_daily WHERE symbol=?",
                (sym,),
            ).fetchone()
            out["series"][sym] = {
                "yahoo": yahoo,
                "note": note,
                "wrote": wrote,
                "table_n": int(n[0] or 0) if n else 0,
                "from": n[1] if n else "",
                "to": n[2] if n else "",
                "ok": wrote > 0,
            }
            if i < len(OUTER_SERIES) - 1:
                time.sleep(max(0.0, sleep_s))
    finally:
        conn.close()
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default="20y")
    ap.add_argument("--sleep", type=float, default=0.12)
    args = ap.parse_args()
    summary = backfill_all(MARKET_DB, range_=args.range, sleep_s=args.sleep)
    summary["rule_reset_zh"] = (
        "上一輪找不出可過關脈絡＝規則／切法不對，不是沒資料。"
        "先重抓約20年數字柱，再重訂可對質規則重跑；不准堆圖。"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "outer_backfill_latest.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if any(v.get("ok") for v in summary["series"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
