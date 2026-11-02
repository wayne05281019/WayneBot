#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序0：盤點／補本地照片庫＋凍結報告。

硬邊界：只寫本機 ``data/decade_lab.db``（與可選回寫 ``index_daily`` TWII）；
不准碰 Telegram／Render／黃金買點／海選／洞燭。盤中未收不當收；缺柱標缺。
時區 Asia/Taipei。三鍋：他說／我估／實驗室 — 本腳本只凍照片，不判浪。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
REPORT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
)

# Yahoo lab 符號 → 實驗室 symbol／時區規則
YAHOO_PACKS: Tuple[Tuple[str, str, str, str], ...] = (
    # (pack, lab_symbol, yahoo_sym, session_tz_note)
    ("A", "TWII", "^TWII", "Asia/Taipei calendar from UTC stamp"),
    ("C", "2330", "2330.TW", "Asia/Taipei; adjclose=還原權息；quote=未還原"),
    ("D", "SOX", "^SOX", "America/New_York session day; map to TW as-of via prior US close"),
    ("D", "IXIC", "^IXIC", "America/New_York session day; map to TW as-of via prior US close"),
)


def _now_tp() -> datetime:
    return datetime.now(TP)


def _ymd(s: Any) -> str:
    return str(s or "").replace("-", "")[:8]


def ensure_lab_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS lab_daily (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL,
                adj_close REAL,
                adj_kind TEXT NOT NULL DEFAULT 'yahoo_adjclose',
                source TEXT NOT NULL DEFAULT 'yahoo_lab',
                pack TEXT,
                tz_rule TEXT,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (symbol, date, adj_kind)
            );
            CREATE TABLE IF NOT EXISTS lab_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lab_gaps (
                pack TEXT NOT NULL,
                symbol TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                as_of TEXT NOT NULL,
                PRIMARY KEY (pack, symbol, kind)
            );
            """
        )
        con.commit()
    finally:
        con.close()


def fetch_yahoo_daily_full(
    sym: str, *, range_: str = "10y", tz_name: str
) -> List[Dict[str, Any]]:
    """Yahoo 日 K；同時抓 quote 與 adjclose。失敗回空。"""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1d&range={range_}"
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
    adj_list = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get(
        "adjclose"
    ) or []
    tz = ZoneInfo(tz_name)
    out: List[Dict[str, Any]] = []
    for i, ts in enumerate(stamps):
        closes = q.get("close") or []
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        day = datetime.fromtimestamp(int(ts), tz=ZoneInfo("UTC")).astimezone(tz)
        ymd = day.strftime("%Y%m%d")
        def _f(arr, idx, default=None):
            if not arr or idx >= len(arr) or arr[idx] is None:
                return default
            try:
                return float(arr[idx])
            except (TypeError, ValueError):
                return default

        adj = _f(adj_list, i, None)
        out.append(
            {
                "date": ymd,
                "open": _f(q.get("open"), i, c),
                "high": _f(q.get("high"), i, c),
                "low": _f(q.get("low"), i, c),
                "close": c,
                "volume": _f(q.get("volume"), i, 0.0) or 0.0,
                "adj_close": adj,
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def upsert_lab_bars(
    db_path: Path,
    *,
    symbol: str,
    pack: str,
    tz_rule: str,
    bars: Sequence[Dict[str, Any]],
) -> int:
    now = _now_tp().isoformat()
    con = sqlite3.connect(str(db_path))
    n = 0
    try:
        for b in bars:
            # 未還原列
            con.execute(
                """
                INSERT INTO lab_daily(
                    symbol, date, open, high, low, close, volume,
                    adj_close, adj_kind, source, pack, tz_rule, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol, date, adj_kind) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    adj_close=excluded.adj_close, source=excluded.source,
                    pack=excluded.pack, tz_rule=excluded.tz_rule,
                    fetched_at=excluded.fetched_at
                """,
                (
                    symbol,
                    b["date"],
                    b.get("open"),
                    b.get("high"),
                    b.get("low"),
                    b.get("close"),
                    b.get("volume"),
                    b.get("adj_close"),
                    "raw_quote",
                    "yahoo_lab",
                    pack,
                    tz_rule,
                    now,
                ),
            )
            n += 1
            # 還原列（用 adj_close 當 close；高低按比例縮放若有 adj）
            adj = b.get("adj_close")
            raw_c = b.get("close")
            if adj is not None and raw_c and float(raw_c) > 0:
                factor = float(adj) / float(raw_c)
                con.execute(
                    """
                    INSERT INTO lab_daily(
                        symbol, date, open, high, low, close, volume,
                        adj_close, adj_kind, source, pack, tz_rule, fetched_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol, date, adj_kind) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume,
                        adj_close=excluded.adj_close, source=excluded.source,
                        pack=excluded.pack, tz_rule=excluded.tz_rule,
                        fetched_at=excluded.fetched_at
                    """,
                    (
                        symbol,
                        b["date"],
                        (b.get("open") or 0) * factor,
                        (b.get("high") or 0) * factor,
                        (b.get("low") or 0) * factor,
                        float(adj),
                        b.get("volume"),
                        float(adj),
                        "yahoo_adjclose",
                        "yahoo_lab",
                        pack,
                        tz_rule + "｜十年高低語意用還原列",
                        now,
                    ),
                )
                n += 1
        con.commit()
    finally:
        con.close()
    return n


def set_gap(db_path: Path, pack: str, symbol: str, kind: str, detail: str) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            """
            INSERT INTO lab_gaps(pack, symbol, kind, detail, as_of)
            VALUES (?,?,?,?,?)
            ON CONFLICT(pack, symbol, kind) DO UPDATE SET
                detail=excluded.detail, as_of=excluded.as_of
            """,
            (pack, symbol, kind, detail, _now_tp().strftime("%Y%m%d")),
        )
        con.commit()
    finally:
        con.close()


def inventory_market(db_path: Path) -> Dict[str, Any]:
    if not db_path.exists():
        return {"ok": False, "error": "missing_market_db", "path": str(db_path)}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: Dict[str, Any] = {"ok": True, "path": str(db_path)}
    try:
        twii = con.execute(
            "SELECT COUNT(*) n, MIN(date) mn, MAX(date) mx FROM index_daily WHERE symbol='TWII'"
        ).fetchone()
        out["TWII"] = dict(twii) if twii else {}
        tsmc = con.execute(
            "SELECT COUNT(*) n, MIN(date) mn, MAX(date) mx FROM daily_quotes WHERE stock_id='2330'"
        ).fetchone()
        out["2330_daily_quotes"] = dict(tsmc) if tsmc else {}
        fut = [
            dict(r)
            for r in con.execute(
                """
                SELECT symbol, session, COUNT(*) n, MIN(date) mn, MAX(date) mx
                FROM futures_daily GROUP BY 1,2 ORDER BY 1,2
                """
            )
        ]
        out["futures_daily"] = fut
        mins = [
            dict(r)
            for r in con.execute(
                """
                SELECT stock_id, interval, COUNT(*) n, MIN(ts) mn, MAX(ts) mx
                FROM minute_bars GROUP BY 1,2 ORDER BY 1,2
                """
            )
        ]
        out["minute_bars"] = mins
        us = con.execute(
            "SELECT COUNT(*) n, MIN(as_of) mn, MAX(as_of) mx FROM us_overnight"
        ).fetchone()
        out["us_overnight"] = dict(us) if us else {}
        # 語料底圖：本機可能空；標缺
        try:
            posts = con.execute("SELECT COUNT(*) n FROM biaoke_posts").fetchone()
            out["biaoke_posts_n"] = int(posts["n"] if posts else 0)
        except sqlite3.Error:
            out["biaoke_posts_n"] = None
    finally:
        con.close()
    return out


def maybe_backfill_twii_index(market_db: Path, bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """可選：把 Yahoo TWII 十年寫進 wayne_market.index_daily（lab 允許）。"""
    if not market_db.exists() or not bars:
        return {"ok": False, "rows": 0}
    try:
        import sys

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from taiwan_market import ensure_index_daily_table, sync_index_daily

        ensure_index_daily_table(str(market_db))
        # 用既有 sync（Yahoo+官方合併）；range 10y
        stats = sync_index_daily(str(market_db), range_="10y")
        return {"ok": bool(stats.get("ok")), "via": "sync_index_daily", **stats}
    except Exception as exc:
        # 退回純 Yahoo upsert
        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        con = sqlite3.connect(str(market_db))
        n = 0
        try:
            for b in bars:
                c = float(b["close"])
                con.execute(
                    """
                    INSERT INTO index_daily(
                        date, symbol, open, high, low, close, volume, pct_change, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, symbol) DO UPDATE SET
                        open=COALESCE(NULLIF(excluded.open, 0), index_daily.open),
                        high=COALESCE(NULLIF(excluded.high, 0), index_daily.high),
                        low=COALESCE(NULLIF(excluded.low, 0), index_daily.low),
                        close=excluded.close,
                        volume=CASE
                            WHEN index_daily.volume > 0 THEN index_daily.volume
                            ELSE excluded.volume END,
                        updated_at=excluded.updated_at
                    """,
                    (
                        b["date"],
                        "TWII",
                        float(b.get("open") or c),
                        float(b.get("high") or c),
                        float(b.get("low") or c),
                        c,
                        float(b.get("volume") or 0),
                        0.0,
                        now,
                    ),
                )
                n += 1
            con.commit()
        finally:
            con.close()
        return {"ok": True, "via": "yahoo_direct", "rows": n, "note": str(exc)}


def fingerprint_near_window(
    db_path: Path, symbol: str, as_of: str, *, window: int = 20, adj_kind: str = "raw_quote"
) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """
            SELECT date, open, high, low, close, volume FROM lab_daily
            WHERE symbol=? AND adj_kind=? AND date<=?
            ORDER BY date DESC LIMIT ?
            """,
            (symbol, adj_kind, as_of, window),
        ).fetchall()
    finally:
        con.close()
    blob = "|".join(
        f"{r[0]}:{r[1]}:{r[2]}:{r[3]}:{r[4]}:{r[5]}" for r in reversed(rows)
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # 人類可讀摘要
    md = path.with_suffix(".md")
    lines = [
        "# 十年回測｜序0 凍結報告",
        "",
        f"時區：`Asia/Taipei`。凍結時刻：`{payload.get('frozen_at')}`。",
        f"鍋標：`實驗室`（照片凍結；非他說／非我估判斷）。",
        "",
        "## 照片庫覆蓋",
        "",
        "| 包 | 符號 | 列數 | 起 | 迄 | 口徑 |",
        "|----|------|------|----|----|------|",
    ]
    for row in payload.get("lab_spans") or []:
        lines.append(
            f"| {row.get('pack')} | {row.get('symbol')}／{row.get('adj_kind')} | "
            f"{row.get('n')} | {row.get('mn')} | {row.get('mx')} | {row.get('tz_rule','')} |"
        )
    lines.extend(["", "## 缺口（只標缺）", ""])
    gaps = payload.get("gaps") or []
    if not gaps:
        lines.append("- （本輪無新增缺口列）")
    else:
        for g in gaps:
            lines.append(
                f"- **{g.get('pack')}／{g.get('symbol')}／{g.get('kind')}**：{g.get('detail')}"
            )
    lines.extend(
        [
            "",
            "## 指紋抽樣（同一日重跑應一致）",
            "",
        ]
    )
    for k, v in (payload.get("fingerprints") or {}).items():
        lines.append(f"- `{k}` → `{v}`")
    lines.extend(
        [
            "",
            "## 本機市場庫盤點（只讀）",
            "",
            "```json",
            json.dumps(payload.get("market_inventory") or {}, ensure_ascii=False, indent=2),
            "```",
            "",
            "不是買訊。不准寫回黃金買點／海選／洞燭。",
            "",
        ]
    )
    md.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ensure_lab_schema(LAB_DB)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    market_inv = inventory_market(MARKET_DB)
    gaps: List[Dict[str, Any]] = []
    fetch_stats: Dict[str, Any] = {}

    # A/C/D Yahoo 十年
    for pack, lab_sym, ysym, tz_rule in YAHOO_PACKS:
        tz_name = "America/New_York" if lab_sym in ("SOX", "IXIC") else "Asia/Taipei"
        bars = fetch_yahoo_daily_full(ysym, range_="10y", tz_name=tz_name)
        time.sleep(0.12)
        if not bars:
            detail = f"Yahoo {ysym} 10y 抓空；標缺"
            set_gap(LAB_DB, pack, lab_sym, "yahoo_empty", detail)
            gaps.append(
                {"pack": pack, "symbol": lab_sym, "kind": "yahoo_empty", "detail": detail}
            )
            fetch_stats[lab_sym] = {"ok": False, "n": 0}
            continue
        wrote = upsert_lab_bars(
            LAB_DB, symbol=lab_sym, pack=pack, tz_rule=tz_rule, bars=bars
        )
        fetch_stats[lab_sym] = {
            "ok": True,
            "yahoo_bars": len(bars),
            "upsert_rows": wrote,
            "span": [bars[0]["date"], bars[-1]["date"]],
            "source": "yahoo_lab",
            "yahoo_sym": ysym,
        }
        if lab_sym == "TWII":
            tw_stats = maybe_backfill_twii_index(MARKET_DB, bars)
            fetch_stats["TWII_market_backfill"] = tw_stats

    # B 台指期／分鐘：只盤點＋標缺，不腦補
    fut = (market_inv.get("futures_daily") or []) if market_inv.get("ok") else []
    tx_reg = next((x for x in fut if x.get("symbol") == "TX" and x.get("session") == "regular"), None)
    tx_night = next((x for x in fut if x.get("symbol") == "TX" and x.get("session") == "night"), None)
    if not tx_reg or str(tx_reg.get("mn") or "") > "20170101":
        detail = (
            f"台指期日盤 futures_daily TX regular 僅 "
            f"{(tx_reg or {}).get('mn')}→{(tx_reg or {}).get('mx')} "
            f"n={(tx_reg or {}).get('n')}；十年窗更早缺；轉倉／連續契約未凍成單一連續序列"
        )
        set_gap(LAB_DB, "B", "TX", "futures_history_short", detail)
        gaps.append(
            {
                "pack": "B",
                "symbol": "TX",
                "kind": "futures_history_short",
                "detail": detail,
            }
        )
    if not tx_night:
        detail = "台指期夜盤缺表"
        set_gap(LAB_DB, "B", "TX", "night_missing", detail)
        gaps.append(
            {"pack": "B", "symbol": "TX", "kind": "night_missing", "detail": detail}
        )

    mins = (market_inv.get("minute_bars") or []) if market_inv.get("ok") else []
    for sid, interval in (("TWII", "15"), ("TWII", "60"), ("TX", "15"), ("TX", "60"), ("2330", "15"), ("2330", "60"), ("SOX", "15"), ("SOX", "60")):
        row = next(
            (x for x in mins if x.get("stock_id") == sid and str(x.get("interval")) == interval),
            None,
        )
        if not row or str(row.get("mn") or "") > "201701010000":
            detail = (
                f"minute_bars {sid}/{interval} 僅 "
                f"{(row or {}).get('mn')}→{(row or {}).get('mx')} "
                f"n={(row or {}).get('n')}；更早年分鐘缺窗標缺（Yahoo 日盤可補日K，分鐘不腦補）"
            )
            set_gap(LAB_DB, "B", f"{sid}_{interval}", "minute_gap", detail)
            gaps.append(
                {
                    "pack": "B",
                    "symbol": f"{sid}_{interval}",
                    "kind": "minute_gap",
                    "detail": detail,
                }
            )

    # E 旁證：us_overnight 極短
    us = market_inv.get("us_overnight") or {}
    if int(us.get("n") or 0) < 200:
        detail = (
            f"us_overnight 僅 n={us.get('n')} span {us.get('mn')}→{us.get('mx')}；"
            f"油／匯／完整美股已收十年未凍進該表（SOX/IXIC 已另凍 lab_daily）"
        )
        set_gap(LAB_DB, "E", "us_overnight", "short_history", detail)
        gaps.append(
            {
                "pack": "E",
                "symbol": "us_overnight",
                "kind": "short_history",
                "detail": detail,
            }
        )

    # F 語料
    posts_n = market_inv.get("biaoke_posts_n")
    if posts_n is not None and int(posts_n) < 1700:
        detail = (
            f"本機 biaoke_posts n={posts_n}＜1700；融合底圖應在 Render／archive_1709，"
            f"本實驗室本輪不重抓社團、不進話筒"
        )
        set_gap(LAB_DB, "F", "biaoke_posts", "corpus_not_seeded_local", detail)
        gaps.append(
            {
                "pack": "F",
                "symbol": "biaoke_posts",
                "kind": "corpus_not_seeded_local",
                "detail": detail,
            }
        )

    # G DC 末端
    dc_path = ROOT / "docs" / "expert_notes" / "dc_wave" / "dc-wave-digest.md"
    if dc_path.exists():
        set_gap(
            LAB_DB,
            "G",
            "DC",
            "terminal_pending",
            "DC 末端／motive 全表待補；擴延1618／前端傾斜見 digest，末端教材未齊不准當他說",
        )
        gaps.append(
            {
                "pack": "G",
                "symbol": "DC",
                "kind": "terminal_pending",
                "detail": "末端／motive 全表待補",
            }
        )
    else:
        set_gap(
            LAB_DB,
            "G",
            "DC",
            "digest_missing",
            "docs/expert_notes/dc_wave/dc-wave-digest.md 本分支缺檔；DC 末端／motive 全表待補，不准冒充他說",
        )
        gaps.append(
            {
                "pack": "G",
                "symbol": "DC",
                "kind": "digest_missing",
                "detail": "digest 缺檔＋末端待補",
            }
        )

    # H 課綱／J 社團72：只盤點
    curr = ROOT / "docs" / "expert_notes" / "飆客" / "wave_fib_morph_curriculum.md"
    if not curr.exists():
        set_gap(LAB_DB, "H", "curriculum", "missing", "wave_fib_morph_curriculum.md 缺")
        gaps.append(
            {
                "pack": "H",
                "symbol": "curriculum",
                "kind": "missing",
                "detail": "課綱缺檔",
            }
        )
    club = ROOT / "docs" / "expert_notes" / "飆客" / "archive_club.json.gz"
    if not club.exists():
        set_gap(
            LAB_DB,
            "J",
            "club72",
            "archive_missing_or_private",
            "社團72 規則包本機未見（不進公開庫／不進話筒原文）；內化另軌",
        )
        gaps.append(
            {
                "pack": "J",
                "symbol": "club72",
                "kind": "archive_missing_or_private",
                "detail": "本機未見 archive_club",
            }
        )

    # lab spans
    con = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        spans = [
            dict(r)
            for r in con.execute(
                """
                SELECT pack, symbol, adj_kind, COUNT(*) n, MIN(date) mn, MAX(date) mx,
                       MIN(tz_rule) tz_rule
                FROM lab_daily GROUP BY 1,2,3 ORDER BY 1,2,3
                """
            )
        ]
        gap_rows = [dict(r) for r in con.execute("SELECT * FROM lab_gaps ORDER BY pack, symbol, kind")]
    finally:
        con.close()

    # 指紋：用各符號最新日
    fps: Dict[str, str] = {}
    for sp in spans:
        if sp.get("adj_kind") != "raw_quote":
            continue
        sym = sp["symbol"]
        mx = sp["mx"]
        fps[f"{sym}@{mx}/w20"] = fingerprint_near_window(LAB_DB, sym, mx, window=20)
        # 重算一次對質一致
        fps[f"{sym}@{mx}/w20_rerun"] = fingerprint_near_window(
            LAB_DB, sym, mx, window=20
        )

    # 口徑寫死
    calibers = {
        "A_TWII": "Yahoo ^TWII 日K；Asia/Taipei 日；指數非還原；量為 Yahoo 指數量（與證交所 FMTQIK 張數口徑不同，對質用價優先）",
        "B_TX": "期交所近月日／夜分 session；未建連續契約；轉倉週降權；缺窗標缺不腦補",
        "C_2330": "Yahoo 2330.TW；raw_quote=未還原；yahoo_adjclose=還原權息（十年高低語意用還原列）；本機 daily_quotes 另有官方未還原短史",
        "D_US": "Yahoo ^SOX/^IXIC；America/New_York session day；對台北開市日 as-of＝嚴格早於該台北日的最近美股已收",
        "DST": "美股夏令：用 America/New_York ZoneInfo，不手調 UTC-4/5",
    }

    payload = {
        "frozen_at": _now_tp().isoformat(),
        "tz": "Asia/Taipei",
        "pot": "實驗室",
        "lab_db": str(LAB_DB),
        "market_db": str(MARKET_DB),
        "fetch_stats": fetch_stats,
        "lab_spans": spans,
        "gaps": gap_rows,
        "calibers": calibers,
        "fingerprints": fps,
        "market_inventory": market_inv,
        "notes": [
            "圖務收尾（教具排版／PR#750）與本實驗室分開驗收",
            "不是買訊；不准寫回黃金買點／海選／洞燭",
            "盤中未收不當收；本輪 Yahoo 只凍已回傳日K",
        ],
    }
    stamp = _now_tp().strftime("%Y%m%d_%H%M%S")
    out_json = REPORT_DIR / f"freeze_report_{stamp}.json"
    write_report(out_json, payload)
    # 穩定別名
    write_report(REPORT_DIR / "freeze_report_latest.json", payload)
    print(json.dumps({"ok": True, "report": str(out_json), "gaps": len(gap_rows), "spans": len(spans)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
