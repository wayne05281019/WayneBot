# -*- coding: utf-8 -*-
"""飆大視窗專用：單向讀主程式全部行情／籌碼／產業／持倉。

按了「飆大」之後，對話可以調主庫去比對、用飆大那套想。
海選／持股／決策卡／查股兩張圖不准 import 這支，也不准讀 biaoke_* overlay。

不要另開第二套行情庫。每天回傳融合仍寫進同一顆 wayne_market.db：
  05:10／22:15  停班年曆
  06:30         美股隔夜 + 早上海選（海選名單不吃飆大 overlay）
  12:45         尾盤複核現價
  16:30         盤後日K／法人／產業資金／月營收／季報／除權息／興櫃／
                加權／台指期／官方快照；之後把新收盤對回飆大建檔
  20:00         AI 模擬倉用收盤（不推播）
盤中每 10 分、休市每 1 小時抓公開文；日盤 Yahoo 15／60、夜盤期交所成交進 minute_bars。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("WayneBot.BiaokeFacts")

# 主功能模組不准碰飆大 overlay。測試會掃這些檔的 import。
MAIN_FEATURE_MODULES: Tuple[str, ...] = (
    "screening_engine.py",
    "chips.py",
    "decision_card_signals.py",
    "portfolio_engine.py",
    "industry_card.py",
    "money_flow.py",
    "wayne_navigator.py",
    "buy_streak.py",
    "sell_discipline.py",
    "live_quote.py",
)

DAILY_FUSE_SLOTS: Tuple[Tuple[str, str], ...] = (
    ("05:10", "颱風／停班年曆"),
    ("06:30", "美股隔夜寫入 us_overnight；早上海選（不讀飆大 overlay）"),
    ("12:45", "尾盤複核現價"),
    ("16:30", "盤後融合日K／法人／產業／基本面／加權／台指期，再對回飆大建檔"),
    ("20:00", "晚間海選快照＋AI 模擬倉（不寄）"),
    ("22:15", "停班年曆"),
)

_TICKER = re.compile(r"\b(\d{3,6}[A-Za-z]?)\b", re.I)
_TALK = re.compile(
    r"(你怎麼看|我怎麼看|怎麼看|怎麼想|你覺得|我覺得|幫我看|分析一下|"
    r"能不能買|可以買嗎|該買嗎|會不會跌|的走勢|這檔|看看|如何看|"
    r"的看法|看法如何|觀點)"
)
_LEAD = re.compile(r"^(飆大|飆客|AI飆客)\s*")
_PRONOUN = re.compile(r"^(你|妳|我|我們)+")


def talk_core(ask: str) -> str:
    """把口語問句收成股名／代號。只給飆大視窗用，不改查股卡。"""
    q = unicodedata.normalize("NFKC", (ask or "").strip())
    q = _LEAD.sub("", q)
    q = _TALK.sub("", q)
    q = _PRONOUN.sub("", q)
    q = re.sub(r"(大概|何時|哪時候|什麼時候|止跌|會不會|嗎|呢)+", " ", q)
    return re.sub(r"\s+", " ", q).strip(" 　,，、?？")


def names_in_ask(ask: str) -> List[Tuple[str, str]]:
    """公開文常用股名（智原／勤誠／台光電…）從整句抓出來。"""
    blob = unicodedata.normalize("NFKC", ask or "")
    if not blob:
        return []
    try:
        from biaoke_why import _NAME_SID, _NAMES
    except Exception:
        return []
    used: List[str] = []
    out: List[Tuple[str, str]] = []
    seen = set()
    for name in _NAMES:
        if not name or name not in blob:
            continue
        if any(name != longer and name in longer for longer in used):
            continue
        used.append(name)
        sid = str(_NAME_SID.get(name) or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append((sid, name))
    return out


def _row(conn: sqlite3.Connection, sql: str, args: Sequence[Any] = ()) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    try:
        hit = conn.execute(sql, tuple(args)).fetchone()
    except sqlite3.Error:
        return {}
    return dict(hit) if hit else {}


def _rows(conn: sqlite3.Connection, sql: str, args: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    try:
        hits = conn.execute(sql, tuple(args)).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in hits]


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return bool(row)


def _open(db_path: str) -> Optional[sqlite3.Connection]:
    if not db_path or not os.path.isfile(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_quote(conn: sqlite3.Connection, sid: str) -> Dict[str, Any]:
    return _row(
        conn,
        """
        SELECT stock_id, stock_name, date, open, high, low, close, volume,
               pct_change, foreign_net, trust_net, dealer_net, market
        FROM daily_quotes
        WHERE stock_id=?
        ORDER BY date DESC
        LIMIT 1
        """,
        (sid,),
    )


def resolve_talk_stock(db_path: str, ask: str) -> List[Dict[str, Any]]:
    """口語「你怎麼看智原／智原／3035」對到主庫那一檔。"""
    raw = unicodedata.normalize("NFKC", (ask or "").strip())
    core = talk_core(raw)
    if not raw and not core:
        return []
    ordered: List[str] = []
    names: Dict[str, str] = {}
    m = _TICKER.search(core) or _TICKER.search(raw)
    if m:
        ordered.append(m.group(1).upper())
    for sid, name in names_in_ask(raw) + names_in_ask(core):
        names[sid] = name
        if sid not in ordered:
            ordered.append(sid)
    needle = core if core and not _TICKER.search(core) else ""
    conn = _open(db_path)
    if conn is None:
        return [{"stock_id": sid, "stock_name": names.get(sid, "")} for sid in ordered]
    try:
        if needle and len(re.sub(r"\s+", "", needle)) >= 2:
            exact = _rows(
                conn,
                """
                SELECT a.stock_id, a.stock_name, a.date, a.close, a.pct_change, a.volume
                FROM daily_quotes a
                JOIN (
                    SELECT stock_id, MAX(date) AS d FROM daily_quotes
                    WHERE stock_name=? OR REPLACE(stock_name,'-','')=?
                    GROUP BY stock_id
                ) b ON a.stock_id=b.stock_id AND a.date=b.d
                ORDER BY a.volume DESC
                LIMIT 8
                """,
                (needle, needle.replace("-", "")),
            )
            for h in exact:
                sid = str(h.get("stock_id") or "")
                if sid and sid not in ordered:
                    ordered.append(sid)
                    names[sid] = str(h.get("stock_name") or "")
        out: List[Dict[str, Any]] = []
        seen = set()
        for sid in ordered:
            if not sid or sid in seen:
                continue
            seen.add(sid)
            q = _latest_quote(conn, sid)
            if not q:
                q = {"stock_id": sid, "stock_name": names.get(sid, "")}
            elif names.get(sid) and not q.get("stock_name"):
                q["stock_name"] = names[sid]
            out.append(q)
        return out
    finally:
        conn.close()


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _pct(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    sign = "＋" if n > 0 else ""
    return f"{sign}{n:.2f}%".replace("＋-", "−").replace("-", "−")


def _cal60(conn: sqlite3.Connection, sid: str) -> Dict[str, Any]:
    rows = _rows(
        conn,
        """
        SELECT date, close, high, low, volume
        FROM daily_quotes WHERE stock_id=?
        ORDER BY date DESC LIMIT 80
        """,
        (sid,),
    )
    if not rows:
        return {}
    last = rows[0]
    ymd = str(last.get("date") or "").replace("-", "")[:8]
    if len(ymd) != 8:
        return {}
    try:
        from datetime import datetime, timedelta

        day = datetime.strptime(ymd, "%Y%m%d").date()
        cut = (day - timedelta(days=60)).strftime("%Y%m%d")
    except ValueError:
        return {}
    win = [r for r in rows if str(r.get("date") or "").replace("-", "")[:8] >= cut]
    closes = [float(r.get("close") or 0) for r in win if r.get("close") is not None]
    if not closes:
        return {}
    lo = min(closes)
    close = float(last.get("close") or 0)
    pct = ((close / lo) - 1.0) * 100.0 if lo else 0.0
    spike = max(win, key=lambda r: float(r.get("volume") or 0))
    return {
        "low": lo,
        "close": close,
        "pct": pct,
        "spike_date": spike.get("date"),
        "spike_high": spike.get("high"),
        "spike_low": spike.get("low"),
        "spike_vol": spike.get("volume"),
    }


def _industry(conn: sqlite3.Connection, sid: str) -> str:
    row = _row(conn, "SELECT industry FROM stock_universe WHERE stock_id=?", (sid,))
    return str(row.get("industry") or "").strip()


def _holding(db_path: str, uid: str, sid: str) -> Dict[str, Any]:
    if not uid or not sid:
        return {}
    conn = _open(db_path)
    if conn is None:
        return {}
    try:
        if not _has_table(conn, "user_holdings"):
            return {}
        return _row(
            conn,
            """
            SELECT stock_code, stock_name, shares, cost_price
            FROM user_holdings
            WHERE user_id=? AND stock_code=?
            """,
            (str(uid), sid),
        )
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _cash(db_path: str, uid: str) -> Optional[float]:
    if not uid:
        return None
    conn = _open(db_path)
    if conn is None:
        return None
    try:
        if not _has_table(conn, "user_funds"):
            return None
        row = _row(conn, "SELECT cash FROM user_funds WHERE user_id=?", (str(uid),))
        if row.get("cash") is None:
            return None
        return float(row["cash"])
    except (sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        conn.close()


def _live_now(sid: str, market: str = "") -> Dict[str, Any]:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    try:
        from live_quote import fetch_mis_quote

        return fetch_mis_quote(sid, market) or {}
    except Exception:
        return {}


def stock_pack(db_path: str, sid: str, *, uid: str = "") -> Dict[str, Any]:
    """一檔：官方日K、法人張數、產業、60曆日低、持股成本。沒有就空，不編。"""
    sid = str(sid or "").strip()
    pack: Dict[str, Any] = {"sid": sid}
    conn = _open(db_path)
    if conn is None or not sid:
        return pack
    try:
        q = _latest_quote(conn, sid)
        pack["quote"] = q
        pack["industry"] = _industry(conn, sid)
        pack["cal60"] = _cal60(conn, sid)
        if _has_table(conn, "monthly_revenue"):
            pack["revenue"] = _row(
                conn,
                """
                SELECT yyyymm, yoy_pct, mom_pct, revenue
                FROM monthly_revenue WHERE stock_id=?
                ORDER BY yyyymm DESC LIMIT 1
                """,
                (sid,),
            )
        if _has_table(conn, "quarterly_income"):
            pack["income"] = _row(
                conn,
                """
                SELECT year, season, gross_margin_pct, eps
                FROM quarterly_income WHERE stock_id=?
                ORDER BY year DESC, season DESC LIMIT 1
                """,
                (sid,),
            )
        if _has_table(conn, "company_events"):
            pack["event"] = _row(
                conn,
                """
                SELECT event_date, kind
                FROM company_events WHERE stock_id=?
                ORDER BY event_date DESC LIMIT 1
                """,
                (sid,),
            )
        if _has_table(conn, "minute_bars"):
            pack["minutes"] = _rows(
                conn,
                """
                SELECT interval, MAX(h) AS high, MIN(l) AS low, COUNT(*) AS n
                FROM minute_bars WHERE stock_id=?
                GROUP BY interval
                """,
                (sid,),
            )
    finally:
        conn.close()
    pack["holding"] = _holding(db_path, uid, sid)
    pack["cash"] = _cash(db_path, uid)
    pack["live"] = _live_now(sid, str((pack.get("quote") or {}).get("market") or ""))
    try:
        from biaoke_judge import judge_stock

        pack["judge"] = judge_stock(
            db_path, sid, name=str((pack.get("quote") or {}).get("stock_name") or "")
        )
    except Exception:
        pack["judge"] = {}
    try:
        from biaoke_claims import format_stock_claims

        pack["claims"] = format_stock_claims(
            db_path, sid, name=str((pack.get("quote") or {}).get("stock_name") or "")
        )
    except Exception:
        pack["claims"] = ""
    return pack


def market_pack(db_path: str) -> Dict[str, Any]:
    conn = _open(db_path)
    out: Dict[str, Any] = {}
    if conn is None:
        return out
    try:
        out["twii"] = _row(
            conn,
            """
            SELECT date, close, high, low, pct_change
            FROM index_daily
            WHERE symbol='TWII' OR symbol='' OR symbol IS NULL
            ORDER BY date DESC LIMIT 1
            """,
        )
        if _has_table(conn, "us_overnight"):
            out["us"] = _row(conn, "SELECT * FROM us_overnight ORDER BY as_of DESC LIMIT 1")
        if _has_table(conn, "futures_daily"):
            out["tx"] = _row(
                conn,
                """
                SELECT date, session, close, high, low, pct_change
                FROM futures_daily
                WHERE session='day' OR session='' OR session IS NULL
                ORDER BY date DESC LIMIT 1
                """,
            )
            out["txn"] = _row(
                conn,
                """
                SELECT date, session, close, high, low, pct_change
                FROM futures_daily
                WHERE session='night'
                ORDER BY date DESC LIMIT 1
                """,
            )
        if _has_table(conn, "minute_bars"):
            out["tx15"] = _row(
                conn,
                """
                SELECT MAX(h) AS high, MIN(l) AS low, COUNT(*) AS n
                FROM minute_bars WHERE stock_id='TX' AND interval='15'
                """,
            )
    finally:
        conn.close()
    return out


def format_market_facts(db_path: str, ask: str, *, uid: str = "") -> str:
    """給飆大對話線的主庫現況。不是買訊。"""
    bits: List[str] = [
        "主庫現況（官方數字可當現在怎樣；他原文點位仍只准用筆記出現過的。"
        "不准把官方收盤改寫成他沒說過的目標價。不是買訊。）"
    ]
    mkt = market_pack(db_path)
    tw = mkt.get("twii") or {}
    if tw:
        bits.append(
            f"官方加權 {tw.get('date') or ''} 收 {_px(tw.get('close'))}"
            f" 高 {_px(tw.get('high'))} 低 {_px(tw.get('low'))}"
            f" {_pct(tw.get('pct_change'))}"
        )
    tx = mkt.get("tx") or {}
    if tx:
        bits.append(
            f"官方台指期日盤 {tx.get('date') or ''} 收 {_px(tx.get('close'))}"
            f" 高 {_px(tx.get('high'))} 低 {_px(tx.get('low'))}"
        )
    txn = mkt.get("txn") or {}
    if txn:
        bits.append(
            f"官方台指期夜盤 {txn.get('date') or ''} 收 {_px(txn.get('close'))}"
            f" 高 {_px(txn.get('high'))} 低 {_px(txn.get('low'))}"
        )
    tx15 = mkt.get("tx15") or {}
    if tx15.get("n"):
        bits.append(
            f"期交所TX 15分 {int(tx15.get('n') or 0)} 根"
            f" 高 {_px(tx15.get('high'))} 低 {_px(tx15.get('low'))}；不數段"
        )
    us = mkt.get("us") or {}
    if us:
        bits.append(
            f"美股隔夜 {us.get('as_of') or ''} {us.get('regime') or ''}"
            f" 那指 {_pct(us.get('ixic_pct'))} 費半 {_pct(us.get('sox_pct'))}"
        )
    hits = resolve_talk_stock(db_path, ask)
    if not hits:
        return "\n".join(bits)
    hit = hits[0]
    sid = str(hit.get("stock_id") or "")
    pack = stock_pack(db_path, sid, uid=uid)
    q = pack.get("quote") or hit
    name = str(q.get("stock_name") or hit.get("stock_name") or sid)
    live = pack.get("live") or {}
    now_px = live.get("close") if live.get("close") else q.get("close")
    bits.append(
        f"問的檔 {sid} {name} 官方收 {q.get('date') or ''} {_px(q.get('close'))}"
        f"（{_pct(q.get('pct_change'))}）高 {_px(q.get('high'))} 低 {_px(q.get('low'))}"
        f" 量 {q.get('volume') or '—'}"
    )
    if live.get("close"):
        bits.append(
            f"盤中現價 {_px(live.get('close'))}（{_pct(live.get('pct_change'))}）"
            f" {live.get('update_time') or ''}"
        )
    chips = []
    for key, lab in (("foreign_net", "外資"), ("trust_net", "投信"), ("dealer_net", "自營")):
        if q.get(key) is None:
            continue
        chips.append(f"{lab} {q.get(key)}張")
    if chips:
        bits.append("法人（張，不是主力成本） " + " ".join(chips))
    if pack.get("industry"):
        bits.append(f"產業 {pack.get('industry')}")
    judged = pack.get("judge") or {}
    leader = judged.get("leader") or {}
    if leader.get("sid"):
        ls = leader.get("struct") or {}
        bits.append(
            f"這族龍頭 {leader.get('sid')} {leader.get('name')}（{leader.get('why') or ''}）"
            f" 收 {_px(ls.get('close'))} 站上撐={ls.get('above_support')} 過高={ls.get('broke_resistance')}"
        )
    if judged.get("pace"):
        bits.append("量價 " + str(judged.get("pace")))
    if judged.get("catchup"):
        bits.append("位階／補漲 " + str(judged.get("catchup")))
    audit = judged.get("audit") or {}
    if audit.get("verdict"):
        bits.append("融會貫通審核 " + str(audit.get("verdict")))
    cal = pack.get("cal60") or {}
    if cal.get("low"):
        bits.append(
            f"近60曆日低 {_px(cal.get('low'))} 距低 {_pct(cal.get('pct'))}"
            f"；窗內爆量日 {cal.get('spike_date') or ''}"
            f" 高 {_px(cal.get('spike_high'))} 低 {_px(cal.get('spike_low'))}"
        )
    rev = pack.get("revenue") or {}
    if rev:
        bits.append(
            f"月營收 {rev.get('yyyymm') or ''} YoY {_pct(rev.get('yoy_pct'))}"
            f" MoM {_pct(rev.get('mom_pct'))}"
        )
    inc = pack.get("income") or {}
    if inc:
        bits.append(
            f"季報 {inc.get('year') or ''}/{inc.get('season') or ''}季"
            f" 毛利 {_pct(inc.get('gross_margin_pct'))} EPS {_px(inc.get('eps'))}"
        )
    ev = pack.get("event") or {}
    if ev:
        bits.append(f"公司行事 {ev.get('event_date') or ''} {ev.get('kind') or ''}")
    held = pack.get("holding") or {}
    if held:
        shares = float(held.get("shares") or 0)
        cost = float(held.get("cost_price") or 0)
        lots = shares / 1000.0 if shares >= 1000 else shares
        px = float(now_px or 0)
        pnl = ""
        if cost and px:
            pnl = f" 對現價 {_pct((px / cost - 1) * 100.0)}"
        bits.append(
            f"這個人持股 {sid} {lots:g}張 成本 {_px(cost)}{pnl}。"
            "買多少只對他成本／60低／量價結構講，不准當買訊下單。"
        )
    elif uid:
        bits.append("這檔這個人沒記在持股。")
    cash = pack.get("cash")
    if cash is not None:
        bits.append(f"這個人記的現金 {_px(cash)}")
    claims = str(pack.get("claims") or "").strip()
    if claims:
        bits.append(re.sub(r"<[^>]+>", "", claims))
    return "\n".join(x for x in bits if x)


def refresh_after_market_fuse(db_path: str, *, kind: str = "fuse") -> Dict[str, Any]:
    """16:30 主庫融合後：用最新收盤對回飆大建檔。不改海選。"""
    stats: Dict[str, Any] = {"kind": kind, "ok": False}
    if kind != "fuse":
        return {**stats, "skipped": kind}
    path = str(db_path or "").strip()
    if not path:
        return stats
    try:
        from biaoke_link import link_biaoke_db

        stats["link"] = link_biaoke_db(path)
    except Exception:
        logger.exception("飆大連回行情庫略過")
    try:
        from biaoke_walk import walk_biaoke_posts

        stats["walk"] = walk_biaoke_posts(path, fetch_missing=False)
    except Exception:
        logger.exception("飆大對回收盤略過")
    try:
        from biaoke_claims import refresh_wave_minute_hits

        stats["wave"] = refresh_wave_minute_hits(path)
    except Exception:
        logger.exception("飆大波浪柱對回略過")
    stats["ok"] = True
    return stats
