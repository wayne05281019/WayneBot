# -*- coding: utf-8 -*-
"""AI倉選股研究輔助＋買進理由落檔。

選隔日標的前可調庫內與公開來源；查不到寫「未取得」，不准編假數。
凡有買進理由都要寫進表（台北時間），不准只留對話。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

MISSING = "未取得"


def _taipei_stamp() -> str:
    try:
        from config import taipei_now

        return taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "").strip()[:8]


def ensure_ai_research_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_buy_research (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                researched_at TEXT NOT NULL,
                fundamentals_summary TEXT DEFAULT '',
                news_summary TEXT DEFAULT '',
                industry_summary TEXT DEFAULT '',
                price_volume_summary TEXT DEFAULT '',
                public_notes TEXT DEFAULT '',
                sources_json TEXT DEFAULT '[]',
                UNIQUE(user_id, as_of, stock_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_buy_reasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                bucket TEXT NOT NULL DEFAULT 'winrate_active',
                reason TEXT NOT NULL,
                sources_summary TEXT NOT NULL DEFAULT '',
                target_exit TEXT DEFAULT '',
                stop_pct REAL,
                take_pct REAL,
                logged_at TEXT NOT NULL,
                research_id INTEGER,
                UNIQUE(user_id, as_of, stock_id, bucket)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_buy_research_asof "
            "ON ai_buy_research(as_of, stock_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_buy_reasons_asof "
            "ON ai_buy_reasons(as_of, stock_id);"
        )
        conn.commit()
    finally:
        conn.close()


def _ohlcv_summary(db_path: str, stock_id: str, as_of: str) -> tuple[str, List[str]]:
    """近窗官方開高低收＋量（加近20日高低／量比）；缺＝未取得。"""
    day = _ymd(as_of)
    sid = str(stock_id or "").strip()
    sources: List[str] = []
    if not sid:
        return MISSING, sources
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=? AND date<=?
            ORDER BY date DESC LIMIT 20
            """,
            (sid, day or "99999999"),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    if not rows:
        return MISSING, sources
    sources.append("daily_quotes")
    bits = []
    for d, o, h, l, c, v in rows[:5]:
        bits.append(f"{d} 開{o}高{h}低{l}收{c}量{v}")
    try:
        closes = [float(r[4]) for r in rows if r[4] is not None]
        highs = [float(r[2]) for r in rows if r[2] is not None]
        lows = [float(r[3]) for r in rows if r[3] is not None]
        vols = [float(r[5] or 0) for r in rows]
        if closes:
            last = closes[0]
            hi20 = max(highs) if highs else None
            lo20 = min(lows) if lows else None
            avg_vol = (sum(vols[1:]) / max(1, len(vols) - 1)) if len(vols) > 1 else None
            vol_ratio = (vols[0] / avg_vol) if avg_vol and avg_vol > 0 else None
            extra = [f"近收{last}"]
            if hi20 is not None:
                extra.append(f"20高{hi20}")
            if lo20 is not None:
                extra.append(f"20低{lo20}")
            if vol_ratio is not None:
                extra.append(f"量比{vol_ratio:.2f}")
            bits.append("｜".join(extra))
    except (TypeError, ValueError):
        pass
    return "；".join(bits), sources


def _fundamentals_summary(db_path: str, stock_id: str) -> tuple[str, List[str]]:
    sid = str(stock_id or "").strip()
    sources: List[str] = []
    if not sid:
        return MISSING, sources
    conn = sqlite3.connect(db_path)
    try:
        # 月營收最近一筆
        rev = None
        try:
            rev = conn.execute(
                """
                SELECT yyyymm, revenue FROM monthly_revenue
                WHERE stock_id=? ORDER BY yyyymm DESC LIMIT 1
                """,
                (sid,),
            ).fetchone()
        except sqlite3.OperationalError:
            rev = None
        eps = None
        try:
            eps = conn.execute(
                """
                SELECT year, season, eps FROM income_statements
                WHERE stock_id=? ORDER BY year DESC, season DESC LIMIT 1
                """,
                (sid,),
            ).fetchone()
        except sqlite3.OperationalError:
            eps = None
    finally:
        conn.close()
    bits = []
    if rev and rev[1] is not None:
        bits.append(f"月營收{rev[0]}={rev[1]}")
        sources.append("monthly_revenue")
    if eps and eps[2] is not None:
        bits.append(f"EPS{eps[0]}Q{eps[1]}={eps[2]}")
        sources.append("income_statements")
    return ("；".join(bits) if bits else MISSING), sources


def _news_summary(db_path: str, stock_id: str, stock_name: str = "") -> tuple[str, List[str]]:
    sid = str(stock_id or "").strip()
    sources: List[str] = []
    if not sid:
        return MISSING, sources
    try:
        from stock_news import fetch_stock_news_stats

        st = fetch_stock_news_stats(db_path, sid, stock_name or "") or {}
        recent = st.get("recent_n")
        prev = st.get("prev_n")
        label = st.get("label") or ""
        url = st.get("url") or ""
        if recent is None and prev is None and not label:
            return MISSING, sources
        sources.append("stock_news_rss")
        if url:
            sources.append(str(url)[:120])
        return (
            f"近訊{recent if recent is not None else MISSING}"
            f"／前窗{prev if prev is not None else MISSING}"
            f"{('　' + label) if label else ''}"
        ), sources
    except Exception:
        return MISSING, sources


def _industry_summary(db_path: str, stock_id: str) -> tuple[str, List[str]]:
    sid = str(stock_id or "").strip()
    sources: List[str] = []
    if not sid:
        return MISSING, sources
    bits = []
    conn = sqlite3.connect(db_path)
    try:
        try:
            row = conn.execute(
                """
                SELECT industry, chain, tags_json FROM industry_fine
                WHERE stock_id=? LIMIT 1
                """,
                (sid,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        if row:
            ind, chain, tags = row[0], row[1], row[2]
            if ind or chain:
                bits.append(f"產業{ind or ''}　鏈{chain or ''}".strip())
                sources.append("industry_fine")
            if tags:
                bits.append(f"標籤{str(tags)[:80]}")
    finally:
        conn.close()
    try:
        from money_flow import industry_flows_for_stocks

        flows = industry_flows_for_stocks(db_path, [sid]) or {}
        flow = str(flows.get(sid) or "").strip()
        if flow:
            bits.append(flow.rstrip("。"))
            sources.append("money_flow")
    except Exception:
        pass
    return ("；".join(bits) if bits else MISSING), sources


def _try_public_notes(stock_id: str, stock_name: str = "") -> tuple[str, List[str]]:
    """公開來源輔助（不編數）。連線失敗＝未取得。不抓驗證碼頁。"""
    sid = str(stock_id or "").strip()
    sources: List[str] = []
    if not sid:
        return MISSING, sources
    notes: List[str] = []
    mops = f"https://mops.twse.com.tw/mops/web/t05st03?encodeURIComponent=1&step=1&firstin=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn=&queryName=co_id&TYPEK=all&isnew=true&co_id={sid}"
    notes.append("公開資訊觀測站頁已備查")
    sources.append(mops[:160])
    try:
        from stock_links import yahoo_urls

        y_tw, y_us = yahoo_urls(sid)
        if y_tw:
            notes.append("Yahoo台股頁已備查")
            sources.append(str(y_tw)[:160])
        if y_us:
            sources.append(str(y_us)[:160])
    except Exception:
        pass
    # Yahoo chart API：有數才寫；失敗標未取得，不准編價
    try:
        import urllib.request

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sid}.TW"
        req = urllib.request.Request(url, headers={"User-Agent": "WayneBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        meta = (((data or {}).get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
        px = meta.get("regularMarketPrice")
        if px is not None:
            notes.append(f"Yahoo公開現價參考={px}")
            sources.append(url)
        else:
            notes.append(f"Yahoo公開現價{MISSING}")
    except Exception:
        notes.append(f"Yahoo公開現價{MISSING}")
    return ("；".join(notes) if notes else MISSING), sources


def gather_buy_research(
    db_path: str,
    user_id: str,
    as_of: str,
    stock_id: str,
    stock_name: str = "",
    *,
    allow_public: bool = True,
) -> Dict[str, Any]:
    """彙整一檔研究並落檔。缺欄＝未取得。"""
    ensure_ai_research_tables(db_path)
    day = _ymd(as_of)
    sid = str(stock_id or "").strip()
    uid = str(user_id or "").strip()
    name = str(stock_name or "").strip()
    stamp = _taipei_stamp()
    sources: List[str] = []

    fund_s, s1 = _fundamentals_summary(db_path, sid)
    sources.extend(s1)
    news_s, s2 = _news_summary(db_path, sid, name)
    sources.extend(s2)
    ind_s, s3 = _industry_summary(db_path, sid)
    sources.extend(s3)
    pv_s, s4 = _ohlcv_summary(db_path, sid, day)
    sources.extend(s4)
    if allow_public:
        pub_s, s5 = _try_public_notes(sid, name)
        sources.extend(s5)
    else:
        pub_s = MISSING

    # 去重來源
    seen = set()
    uniq_sources = []
    for x in sources:
        k = str(x)
        if k and k not in seen:
            seen.add(k)
            uniq_sources.append(k)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO ai_buy_research(
                user_id, as_of, stock_id, stock_name, researched_at,
                fundamentals_summary, news_summary, industry_summary,
                price_volume_summary, public_notes, sources_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id, as_of, stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                researched_at=excluded.researched_at,
                fundamentals_summary=excluded.fundamentals_summary,
                news_summary=excluded.news_summary,
                industry_summary=excluded.industry_summary,
                price_volume_summary=excluded.price_volume_summary,
                public_notes=excluded.public_notes,
                sources_json=excluded.sources_json
            """,
            (
                uid,
                day,
                sid,
                name,
                stamp,
                fund_s,
                news_s,
                ind_s,
                pv_s,
                pub_s,
                json.dumps(uniq_sources, ensure_ascii=False),
            ),
        )
        conn.commit()
        rid = conn.execute(
            "SELECT id FROM ai_buy_research WHERE user_id=? AND as_of=? AND stock_id=?",
            (uid, day, sid),
        ).fetchone()
        research_id = int(rid[0]) if rid else 0
    finally:
        conn.close()

    return {
        "research_id": research_id,
        "user_id": uid,
        "as_of": day,
        "stock_id": sid,
        "stock_name": name,
        "researched_at": stamp,
        "fundamentals_summary": fund_s,
        "news_summary": news_s,
        "industry_summary": ind_s,
        "price_volume_summary": pv_s,
        "public_notes": pub_s,
        "sources": uniq_sources,
    }


def build_buy_reason_from_research(
    research: Dict[str, Any],
    *,
    signal_label: str = "勝率買點",
    bucket: str = "winrate_active",
) -> Dict[str, str]:
    """從研究摘要組可落檔理由／目標出場句；缺資料不編。"""
    fund = str(research.get("fundamentals_summary") or MISSING)
    news = str(research.get("news_summary") or MISSING)
    ind = str(research.get("industry_summary") or MISSING)
    pv = str(research.get("price_volume_summary") or MISSING)
    pub = str(research.get("public_notes") or MISSING)
    # 理由要看得出「有做比對」：訊號＋產業＋量價重點＋新聞狀態
    pv_short = pv.split("；")[-1] if pv and pv != MISSING else MISSING
    reason = (
        f"{signal_label}"
        f"；產業={ind if ind != MISSING else MISSING}"
        f"；量價={pv_short}"
        f"；新聞={news if news != MISSING else MISSING}"
        f"；基本面={fund if fund != MISSING else MISSING}"
    )
    sources_summary = (
        f"基本面={fund}｜新聞={news}｜產業={ind}｜量價={pv}｜公開={pub}"
    )
    target = "停利達標或作者公開如何賣位階協助出場；非自動賣"
    return {
        "reason": reason[:800],
        "sources_summary": sources_summary[:4000],
        "target_exit": target,
        "bucket": bucket,
    }


def persist_buy_reason(
    db_path: str,
    *,
    user_id: str,
    as_of: str,
    stock_id: str,
    stock_name: str = "",
    bucket: str = "winrate_active",
    reason: str,
    sources_summary: str,
    target_exit: str = "",
    stop_pct: float = -7.0,
    take_pct: float = 8.0,
    research_id: Optional[int] = None,
) -> int:
    """有買進理由就落檔。回傳 row id。"""
    ensure_ai_research_tables(db_path)
    day = _ymd(as_of)
    uid = str(user_id or "").strip()
    sid = str(stock_id or "").strip()
    why = str(reason or "").strip()
    if not day or not uid or not sid or not why:
        return 0
    stamp = _taipei_stamp()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO ai_buy_reasons(
                user_id, as_of, stock_id, stock_name, bucket, reason,
                sources_summary, target_exit, stop_pct, take_pct,
                logged_at, research_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id, as_of, stock_id, bucket) DO UPDATE SET
                stock_name=excluded.stock_name,
                reason=excluded.reason,
                sources_summary=excluded.sources_summary,
                target_exit=excluded.target_exit,
                stop_pct=excluded.stop_pct,
                take_pct=excluded.take_pct,
                logged_at=excluded.logged_at,
                research_id=excluded.research_id
            """,
            (
                uid,
                day,
                sid,
                str(stock_name or ""),
                str(bucket or "winrate_active"),
                why,
                str(sources_summary or MISSING),
                str(target_exit or ""),
                float(stop_pct),
                float(take_pct),
                stamp,
                int(research_id) if research_id else None,
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT id FROM ai_buy_reasons
            WHERE user_id=? AND as_of=? AND stock_id=? AND bucket=?
            """,
            (uid, day, sid, str(bucket or "winrate_active")),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def latest_buy_reason(
    db_path: str, user_id: str, stock_id: str
) -> Optional[Dict[str, Any]]:
    ensure_ai_research_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT * FROM ai_buy_reasons
            WHERE user_id=? AND stock_id=?
            ORDER BY logged_at DESC, id DESC LIMIT 1
            """,
            (str(user_id), str(stock_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def research_batch(
    db_path: str,
    user_id: str,
    as_of: str,
    rows: Sequence[Dict[str, Any]],
    *,
    allow_public: bool = True,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """對母體逐檔研究落檔（選隔日前）。"""
    out: List[Dict[str, Any]] = []
    n = 0
    for it in rows or []:
        if n >= int(limit):
            break
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid or sid.startswith("__"):
            continue
        name = str(it.get("stock_name") or it.get("name") or "")
        out.append(
            gather_buy_research(
                db_path, user_id, as_of, sid, name, allow_public=allow_public
            )
        )
        n += 1
    return out
