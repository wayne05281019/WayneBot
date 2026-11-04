#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法人／投信判斷模組（靜默）｜一定納入大盤漲勢＋幅度預測。

資料：
- TWSE BFI82U 三大法人買賣金額統計（市場級，元→億）→ market_inst_bfi_daily
- daily_quotes 彙總張數（有才用）→ market_inst_lots_daily

規則：不准假成本；只記買賣超數字；不是買訊；不上話筒。
量化過關（n≥20 且 |edge|≥0.25）才進 path_forecast 投票。
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
UA = "Mozilla/5.0 (compatible; WayneBot-inst-module/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

MIN_N = 20
MIN_EDGE = 0.25
MIN_SIDE_HIT = 0.55  # 方向命中太低的旗標不准進投票（避免拉垮準度）

DDL = """
CREATE TABLE IF NOT EXISTS market_inst_bfi_daily (
    date TEXT NOT NULL PRIMARY KEY,
    trust_net_yi REAL,
    foreign_net_yi REAL,
    dealer_net_yi REAL,
    three_net_yi REAL,
    source TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS market_inst_lots_daily (
    date TEXT NOT NULL PRIMARY KEY,
    foreign_net INTEGER,
    trust_net INTEGER,
    dealer_net INTEGER,
    three_net INTEGER,
    nz_stocks INTEGER,
    source TEXT,
    updated_at TEXT
);
"""


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def parse_bfi82u(payload: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if str(payload.get("stat") or "") != "OK":
        return None
    trust = foreign = dealer = None
    for row in payload.get("data") or []:
        if not row:
            continue
        name = str(row[0] or "")
        net = _f(row[3]) if len(row) > 3 else None
        if net is None:
            continue
        yi = net / 1e8  # 元→億
        if name.startswith("投信"):
            trust = yi
        elif "外資及陸資" in name:
            foreign = yi
        elif name.startswith("自營商(自行買賣)"):
            dealer = (dealer or 0.0) + yi
        elif name.startswith("自營商(避險)"):
            dealer = (dealer or 0.0) + yi
    if trust is None and foreign is None and dealer is None:
        return None
    trust = float(trust or 0.0)
    foreign = float(foreign or 0.0)
    dealer = float(dealer or 0.0)
    return {
        "trust_net_yi": round(trust, 4),
        "foreign_net_yi": round(foreign, 4),
        "dealer_net_yi": round(dealer, 4),
        "three_net_yi": round(trust + foreign + dealer, 4),
    }


def fetch_bfi(day: str) -> Optional[Dict[str, float]]:
    day = _ymd(day)
    if not day:
        return None
    url = (
        "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
        f"?response=json&dayDate={day}&type=day"
    )
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        return parse_bfi82u(resp.json())
    except Exception:
        return None


def upsert_bfi(conn: sqlite3.Connection, day: str, row: Dict[str, float]) -> None:
    conn.execute(
        """
        INSERT INTO market_inst_bfi_daily(
            date, trust_net_yi, foreign_net_yi, dealer_net_yi, three_net_yi, source, updated_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            trust_net_yi=excluded.trust_net_yi,
            foreign_net_yi=excluded.foreign_net_yi,
            dealer_net_yi=excluded.dealer_net_yi,
            three_net_yi=excluded.three_net_yi,
            source=excluded.source, updated_at=excluded.updated_at
        """,
        (
            day,
            row["trust_net_yi"],
            row["foreign_net_yi"],
            row["dealer_net_yi"],
            row["three_net_yi"],
            "TWSE_BFI82U",
            _now(),
        ),
    )


def rebuild_lots_from_quotes(conn: sqlite3.Connection) -> int:
    """從個股張數彙總市場法人（有非零才寫）。"""
    ensure(conn)
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''),
               SUM(COALESCE(foreign_net,0)),
               SUM(COALESCE(trust_net,0)),
               SUM(COALESCE(dealer_net,0)),
               SUM(CASE WHEN COALESCE(foreign_net,0)<>0 OR COALESCE(trust_net,0)<>0
                         OR COALESCE(dealer_net,0)<>0 THEN 1 ELSE 0 END)
        FROM daily_quotes
        GROUP BY 1
        HAVING SUM(CASE WHEN COALESCE(foreign_net,0)<>0 OR COALESCE(trust_net,0)<>0
                         OR COALESCE(dealer_net,0)<>0 THEN 1 ELSE 0 END) > 50
        """
    ).fetchall()
    n = 0
    for d, f, t, dlr, nz in rows:
        day = _ymd(d)
        if not day:
            continue
        f_i, t_i, d_i = int(f or 0), int(t or 0), int(dlr or 0)
        conn.execute(
            """
            INSERT INTO market_inst_lots_daily(
                date, foreign_net, trust_net, dealer_net, three_net, nz_stocks, source, updated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                foreign_net=excluded.foreign_net, trust_net=excluded.trust_net,
                dealer_net=excluded.dealer_net, three_net=excluded.three_net,
                nz_stocks=excluded.nz_stocks, updated_at=excluded.updated_at
            """,
            (day, f_i, t_i, d_i, f_i + t_i + d_i, int(nz or 0), "daily_quotes_sum", _now()),
        )
        n += 1
    conn.commit()
    return n


def twii_days(conn: sqlite3.Connection, *, since: str = "20150101") -> List[str]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-','') FROM index_daily
        WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','') >= ?
        ORDER BY 1
        """,
        (since,),
    ).fetchall()
    return [_ymd(r[0]) for r in rows if _ymd(r[0])]


def backfill_bfi(
    db_path: Path = MARKET_DB,
    *,
    since: str = "20180101",
    sleep_s: float = 0.18,
    max_days: int = 0,
) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    ensure(conn)
    days = twii_days(conn, since=since)
    have = {
        _ymd(r[0])
        for r in conn.execute("SELECT date FROM market_inst_bfi_daily").fetchall()
    }
    todo = [d for d in days if d not in have]
    if max_days > 0:
        todo = todo[-max_days:]
    wrote = 0
    miss = 0
    for i, d in enumerate(todo):
        row = fetch_bfi(d)
        if row:
            upsert_bfi(conn, d, row)
            wrote += 1
            if wrote % 20 == 0:
                conn.commit()
        else:
            miss += 1
        time.sleep(sleep_s)
        if (i + 1) % 50 == 0:
            conn.commit()
    conn.commit()
    lots_n = rebuild_lots_from_quotes(conn)
    n_bfi = conn.execute("SELECT COUNT(*) FROM market_inst_bfi_daily").fetchone()[0]
    conn.close()
    out = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "todo": len(todo),
        "wrote": wrote,
        "miss": miss,
        "bfi_n": int(n_bfi),
        "lots_n": lots_n,
        "since": since,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "inst_backfill_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def _load_bfi(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for d, t, f, dlr, th in conn.execute(
        "SELECT date, trust_net_yi, foreign_net_yi, dealer_net_yi, three_net_yi FROM market_inst_bfi_daily ORDER BY 1"
    ):
        day = _ymd(d)
        if not day:
            continue
        out[day] = {
            "trust": float(t or 0),
            "foreign": float(f or 0),
            "dealer": float(dlr or 0),
            "three": float(th or 0),
        }
    return out


def _z_maps(series: Dict[str, float], look: int = 60) -> Dict[str, float]:
    """逐日用過去 look 日算 z（不含當日未來）。"""
    days = sorted(series)
    zs: Dict[str, float] = {}
    for i, d in enumerate(days):
        window = [series[days[j]] for j in range(max(0, i - look), i)]
        if len(window) < 20:
            continue
        mu = sum(window) / len(window)
        var = sum((x - mu) ** 2 for x in window) / len(window)
        sd = var ** 0.5
        if sd <= 1e-9:
            continue
        zs[d] = (series[d] - mu) / sd
    return zs


def quantify(conn: sqlite3.Connection) -> Dict[str, Any]:
    bfi = _load_bfi(conn)
    tw = {
        _ymd(d): float(c)
        for d, c in conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), close FROM index_daily WHERE symbol='TWII'"
        )
        if _ymd(d) and c
    }
    keys = sorted(tw)
    idx = {d: i for i, d in enumerate(keys)}

    def fwd3(d: str) -> Optional[float]:
        i = idx.get(d)
        if i is None or i + 3 >= len(keys):
            return None
        return (tw[keys[i + 3]] / tw[d] - 1.0) * 100.0

    trust_s = {d: v["trust"] for d, v in bfi.items()}
    foreign_s = {d: v["foreign"] for d, v in bfi.items()}
    three_s = {d: v["three"] for d, v in bfi.items()}
    zt = _z_maps(trust_s)
    zf = _z_maps(foreign_s)
    z3 = _z_maps(three_s)
    days = [d for d in sorted(bfi) if d in idx and fwd3(d) is not None and d in zt]
    base = [fwd3(d) for d in days]
    base_m = (sum(base) / len(base)) if base else 0.0

    flags: List[Dict[str, Any]] = []

    def add(code: str, mask, bias_if_edge: str) -> None:
        xs = [fwd3(d) for d in days if mask(d)]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - base_m
        if abs(edge) < MIN_EDGE:
            return
        # 方向命中：依 edge 符號押後窗
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
            bias = "up"
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
            bias = "down"
        # 均邊大但方向命中差＝噪音，不准進預測票
        if hit < MIN_SIDE_HIT:
            return
        flags.append(
            {
                "code": code,
                "n": len(xs),
                "mean3": round(m, 4),
                "edge3": round(edge, 4),
                "bias": bias,
                "hit_rate_side": round(hit, 4),
                "vote": round(edge, 4),  # 正＝偏多票
            }
        )

    add("inst_trust_z_le_m1", lambda d: zt.get(d, 0) <= -1.0, "up")
    add("inst_trust_z_ge_p1", lambda d: zt.get(d, 0) >= 1.0, "down")
    add("inst_foreign_z_ge_p1", lambda d: zf.get(d, 0) >= 1.0, "up")
    add("inst_foreign_z_le_m1", lambda d: zf.get(d, 0) <= -1.0, "down")
    add("inst_three_z_le_m1", lambda d: z3.get(d, 0) <= -1.0, "up")
    add("inst_three_z_ge_p1", lambda d: z3.get(d, 0) >= 1.0, "down")

    # 外資滾動分位（只用過去窗，不准偷看）
    def roll_pct_ge(series: Dict[str, float], pct: float, look: int = 120):
        ordered = sorted(series)

        def mask(d: str) -> bool:
            if d not in idx or d not in series:
                return False
            i = ordered.index(d) if d in ordered else -1
            if i < look:
                return False
            window = [series[ordered[j]] for j in range(i - look, i)]
            if len(window) < 40:
                return False
            window = sorted(window)
            cut = window[int((pct / 100.0) * (len(window) - 1))]
            return series[d] >= cut

        return mask

    def roll_pct_le(series: Dict[str, float], pct: float, look: int = 120):
        ordered = sorted(series)

        def mask(d: str) -> bool:
            if d not in idx or d not in series:
                return False
            i = ordered.index(d) if d in ordered else -1
            if i < look:
                return False
            window = [series[ordered[j]] for j in range(i - look, i)]
            if len(window) < 40:
                return False
            window = sorted(window)
            cut = window[int((pct / 100.0) * (len(window) - 1))]
            return series[d] <= cut

        return mask

    # 外資市場金額：大買超（高分位）→ 偏多
    add("inst_foreign_yi_p80", roll_pct_ge(foreign_s, 80), "up")
    add("inst_foreign_yi_p85", roll_pct_ge(foreign_s, 85), "up")
    add("inst_foreign_yi_p90", roll_pct_ge(foreign_s, 90), "up")
    # 外資大賣後（低分位）→ 可能反彈（對質過才留）
    add("inst_foreign_yi_p10", roll_pct_le(foreign_s, 10), "up")
    add("inst_foreign_yi_p15", roll_pct_le(foreign_s, 15), "up")

    # 2330 外資張數（權值代理）
    t2330: Dict[str, float] = {}
    for d, f in conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), COALESCE(foreign_net,0)
        FROM daily_quotes WHERE stock_id='2330'
        """
    ):
        day = _ymd(d)
        if day:
            t2330[day] = float(f or 0)
    add("inst_2330_foreign_ge_3k", lambda d: t2330.get(d, 0) >= 3000, "up")
    add("inst_2330_foreign_ge_5k", lambda d: t2330.get(d, 0) >= 5000, "up")
    add("inst_2330_foreign_le_m8k", lambda d: t2330.get(d, 0) <= -8000, "up")

    # 連續 2 日投信／外資／三大賣超
    def streak_neg(series: Dict[str, float], k: int = 2):
        def mask(d: str) -> bool:
            if d not in idx:
                return False
            i = idx[d]
            for j in range(i - k + 1, i + 1):
                if j < 0:
                    return False
                dj = keys[j]
                if series.get(dj, 1) >= 0:
                    return False
            return True

        return mask

    def streak_pos(series: Dict[str, float], k: int = 2):
        def mask(d: str) -> bool:
            if d not in idx:
                return False
            i = idx[d]
            for j in range(i - k + 1, i + 1):
                if j < 0:
                    return False
                dj = keys[j]
                if series.get(dj, -1) <= 0:
                    return False
            return True

        return mask

    add("inst_trust_neg_2d", streak_neg(trust_s, 2), "up")
    add("inst_three_neg_2d", streak_neg(three_s, 2), "up")
    add("inst_foreign_neg_2d", streak_neg(foreign_s, 2), "up")
    add("inst_foreign_pos_2d", streak_pos(foreign_s, 2), "up")
    add("inst_foreign_pos_3d", streak_pos(foreign_s, 3), "up")

    flags.sort(key=lambda x: -abs(float(x["edge3"])))
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "bfi_n": len(bfi),
        "scored_days": len(days),
        "base_mean3": round(base_m, 4),
        "flags": flags,
        "n_flags": len(flags),
        "gate": "n>=20 & |edge3|>=0.25",
        "goal_zh": "法人／投信模組提高大盤漲勢＋幅度判斷成功率",
        "not_buy_signal": True,
        "phone_sync": "blocked",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "inst_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "inst_quant_flags.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in flags:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def load_inst_votes(path: Optional[Path] = None) -> Dict[str, float]:
    p = path or (OUT_DIR / "inst_quant_latest.json")
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, float] = {}
    for row in d.get("flags") or []:
        code = str(row.get("code") or "")
        if not code:
            continue
        out[code] = float(row.get("vote") or row.get("edge3") or 0.0)
    return out


def snapshot_inst_factors(conn: sqlite3.Connection, as_of: str) -> Tuple[Dict[str, Any], List[str]]:
    """as-of 當日法人因素（只准用當日與以前）。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    row = conn.execute(
        "SELECT trust_net_yi, foreign_net_yi, dealer_net_yi, three_net_yi FROM market_inst_bfi_daily WHERE date=?",
        (day,),
    ).fetchone()
    if not row:
        missing.extend(["inst_trust_yi", "inst_foreign_yi", "inst_three_yi"])
        return factors, missing
    trust, foreign, dealer, three = [float(x or 0) for x in row]
    factors["inst_trust_yi"] = trust
    factors["inst_foreign_yi"] = foreign
    factors["inst_dealer_yi"] = dealer
    factors["inst_three_yi"] = three
    # rolling z with past 60
    past = conn.execute(
        """
        SELECT trust_net_yi, foreign_net_yi, three_net_yi FROM market_inst_bfi_daily
        WHERE date < ? ORDER BY date DESC LIMIT 60
        """,
        (day,),
    ).fetchall()
    if len(past) >= 20:
        def z_of(vals: Sequence[float], cur: float) -> float:
            mu = sum(vals) / len(vals)
            var = sum((x - mu) ** 2 for x in vals) / len(vals)
            sd = var ** 0.5
            return (cur - mu) / sd if sd > 1e-9 else 0.0

        factors["inst_trust_z"] = round(z_of([float(r[0] or 0) for r in past], trust), 4)
        factors["inst_foreign_z"] = round(z_of([float(r[1] or 0) for r in past], foreign), 4)
        factors["inst_three_z"] = round(z_of([float(r[2] or 0) for r in past], three), 4)
    else:
        missing.append("inst_z_window")
    # 前幾日（連買／連賣）
    prev_rows = conn.execute(
        """
        SELECT trust_net_yi, foreign_net_yi, three_net_yi FROM market_inst_bfi_daily
        WHERE date < ? ORDER BY date DESC LIMIT 3
        """,
        (day,),
    ).fetchall()
    if prev_rows:
        prev = prev_rows[0]
        factors["inst_trust_prev_yi"] = float(prev[0] or 0)
        factors["inst_foreign_prev_yi"] = float(prev[1] or 0)
        factors["inst_three_prev_yi"] = float(prev[2] or 0)
        factors["inst_trust_neg_2d"] = bool(trust < 0 and float(prev[0] or 0) < 0)
        factors["inst_three_neg_2d"] = bool(three < 0 and float(prev[2] or 0) < 0)
        factors["inst_foreign_neg_2d"] = bool(foreign < 0 and float(prev[1] or 0) < 0)
        factors["inst_foreign_pos_2d"] = bool(foreign > 0 and float(prev[1] or 0) > 0)
        if len(prev_rows) >= 2:
            factors["inst_foreign_pos_3d"] = bool(
                foreign > 0
                and float(prev_rows[0][1] or 0) > 0
                and float(prev_rows[1][1] or 0) > 0
            )
        else:
            factors["inst_foreign_pos_3d"] = False
    else:
        missing.append("inst_prev")

    # 外資滾動分位（過去 120 日，不含當日未來）
    hist = conn.execute(
        """
        SELECT foreign_net_yi FROM market_inst_bfi_daily
        WHERE date < ? ORDER BY date DESC LIMIT 120
        """,
        (day,),
    ).fetchall()
    if len(hist) >= 40:
        vals = sorted(float(r[0] or 0) for r in hist)

        def pct_cut(p: float) -> float:
            return vals[int((p / 100.0) * (len(vals) - 1))]

        factors["inst_foreign_yi_p80"] = bool(foreign >= pct_cut(80))
        factors["inst_foreign_yi_p85"] = bool(foreign >= pct_cut(85))
        factors["inst_foreign_yi_p90"] = bool(foreign >= pct_cut(90))
        factors["inst_foreign_yi_p10"] = bool(foreign <= pct_cut(10))
        factors["inst_foreign_yi_p15"] = bool(foreign <= pct_cut(15))
    else:
        missing.append("inst_foreign_pct_window")

    # 2330 外資張數
    r2330 = conn.execute(
        """
        SELECT COALESCE(foreign_net,0) FROM daily_quotes
        WHERE stock_id='2330' AND REPLACE(CAST(date AS TEXT),'-','')=?
        """,
        (day,),
    ).fetchone()
    if r2330 is not None:
        f2330 = float(r2330[0] or 0)
        factors["inst_2330_foreign_net"] = f2330
        factors["inst_2330_foreign_ge_3k"] = bool(f2330 >= 3000)
        factors["inst_2330_foreign_ge_5k"] = bool(f2330 >= 5000)
        factors["inst_2330_foreign_le_m8k"] = bool(f2330 <= -8000)
    else:
        missing.append("inst_2330_foreign")
    return factors, missing


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--since", default="20180101")
    ap.add_argument("--max-days", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.18)
    ap.add_argument("--quant-only", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    ensure(conn)
    report: Dict[str, Any] = {"written_at": _now()}
    if args.backfill:
        conn.close()
        report["backfill"] = backfill_bfi(
            since=args.since, sleep_s=args.sleep, max_days=args.max_days
        )
        conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
        ensure(conn)
    else:
        report["lots_n"] = rebuild_lots_from_quotes(conn)
    if not args.quant_only or True:
        report["quant"] = quantify(conn)
    conn.close()
    print(json.dumps(report, ensure_ascii=False, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
