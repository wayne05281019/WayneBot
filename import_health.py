# -*- coding: utf-8 -*-
"""盤後匯入健康檢查：上市／上櫃必須同一開盤日都進庫，並核對法人與財報快照。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

MIN_TW = 800
MIN_TWO = 600
MIN_CHIPS_NONZERO = 100  # total 夠多時法人非0不能是 0


def increment_health_ok(health: Dict[str, Any]) -> bool:
    """盤後融合是否達標：該有的數字絕不能是 0，且上市／上櫃都要過門檻。"""
    if not health:
        return False
    total = int(health.get("total") or 0)
    tw = int(health.get("tw") or 0)
    two = int(health.get("two") or 0)
    chips = int(health.get("chips_nonzero") or 0)
    if total == 0 or tw == 0 or two == 0:
        return False
    if total >= 800 and chips < MIN_CHIPS_NONZERO:
        return False
    return sides_complete(tw, two)


def increment_health_failures(health: Dict[str, Any], cap: str = "") -> List[str]:
    """回傳盤後未達標原因（給 CI／日誌）；零就是錯。"""
    label = str(cap or health.get("date") or "").strip()
    reasons: List[str] = []
    if not health:
        return ["無匯入健康資料"]
    total = int(health.get("total") or 0)
    tw = int(health.get("tw") or 0)
    two = int(health.get("two") or 0)
    chips = int(health.get("chips_nonzero") or 0)
    if total == 0:
        reasons.append(f"{label} 日 K 合計為 0")
    if tw == 0:
        reasons.append(f"{label} 上市為 0")
    if two == 0:
        reasons.append(f"{label} 上櫃為 0")
    if total >= 800 and chips < MIN_CHIPS_NONZERO:
        reasons.append(f"{label} 法人非0僅 {chips}（<{MIN_CHIPS_NONZERO}）")
    if total > 0 and tw > 0 and two > 0 and not sides_complete(tw, two):
        reasons.append(f"{label} 上市 {tw}/{MIN_TW} 上櫃 {two}/{MIN_TWO} 未齊")
    return reasons
MIN_TOTAL = 1500
_COMPLETE_DATE_CACHE: Dict[str, Any] = {}


def clear_complete_date_cache(db_path: str = "") -> None:
    if db_path:
        _COMPLETE_DATE_CACHE.pop(str(db_path), None)
    else:
        _COMPLETE_DATE_CACHE.clear()


def db_quick_check_ok(db_path: str, min_bytes: int = 1_000_000) -> bool:
    """PRAGMA quick_check；損壞庫會讓基準日／資金輪動全亂。"""
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) < int(min_bytes):
            return False
    except OSError:
        return False
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.DatabaseError:
        return False


def sides_complete(tw: int, two: int, min_tw: int = MIN_TW, min_two: int = MIN_TWO) -> bool:
    return int(tw or 0) >= int(min_tw) and int(two or 0) >= int(min_two)


def should_commit_quote_fetch(
    *,
    existing_tw: int,
    existing_two: int,
    new_tw: int,
    new_two: int,
) -> bool:
    """半套日（上市齊、上櫃 0）不能寫進庫，也不能覆蓋已經齊的完整日。"""
    if sides_complete(new_tw, new_two):
        return True
    return False


def count_markets(db_path: str, yyyymmdd: str) -> Tuple[int, int, int]:
    yyyymmdd = str(yyyymmdd or "").replace("-", "")[:8]
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT
            SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END),
            SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END),
            COUNT(*)
        FROM daily_quotes
        WHERE replace(date,'-','')=?
        """,
        (yyyymmdd,),
    ).fetchone()
    conn.close()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def latest_complete_quote_date(
    db_path: str,
    min_tw: int = MIN_TW,
    min_two: int = MIN_TWO,
    now=None,
) -> Optional[str]:
    """海選／決策用的基準日：上市＋上櫃同一天都進庫、週一～五、且不晚於 fuse 上限。"""
    from trading_calendar import fuse_end_trading_date, is_trading_weekday, normalize_ymd

    cap = fuse_end_trading_date(now)
    stamp = None
    try:
        st = os.stat(db_path)
        stamp = (st.st_mtime_ns, st.st_size, min_tw, min_two, cap)
        hit = _COMPLETE_DATE_CACHE.get(db_path)
        if hit and hit[0] == stamp:
            return hit[1]
    except OSError:
        stamp = None
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT replace(date,'-','') AS d,
               SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END) AS tw,
               SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END) AS two
        FROM daily_quotes
        WHERE date IN (
            SELECT d FROM (
                SELECT DISTINCT date AS d FROM daily_quotes
                ORDER BY date DESC
                LIMIT 40
            )
        )
        GROUP BY replace(date,'-','')
        ORDER BY d DESC
        """
    ).fetchall()
    conn.close()
    found = None
    for date, tw, two in rows:
        d = normalize_ymd(date)
        if not d or d > cap:
            continue
        if not is_trading_weekday(d):
            continue
        if sides_complete(tw, two, min_tw=min_tw, min_two=min_two):
            found = d
            break
    if stamp is not None:
        _COMPLETE_DATE_CACHE[db_path] = (stamp, found)
    return found


def list_coverage_issues(
    db_path: str,
    min_tw: int = MIN_TW,
    min_two: int = MIN_TWO,
    min_total: int = MIN_TOTAL,
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT replace(date,'-','') AS d,
               COUNT(*) AS n,
               SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END) AS tw,
               SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END) AS two
        FROM daily_quotes
        GROUP BY replace(date,'-','')
        ORDER BY d
        """
    ).fetchall()
    conn.close()
    out = []
    for date, n, tw, two in rows:
        tw_i, two_i, n_i = int(tw or 0), int(two or 0), int(n or 0)
        problems = []
        if n_i < min_total:
            problems.append(f"待補全日 {n_i}")
        if tw_i >= min_tw and two_i < min_two:
            problems.append(f"待補上櫃 {two_i}（上市 {tw_i}）")
        if two_i >= min_two and tw_i < min_tw:
            problems.append(f"待補上市 {tw_i}（上櫃 {two_i}）")
        if problems:
            out.append({"date": str(date), "tw": tw_i, "two": two_i, "total": n_i, "problems": problems})
    return out


def audit_import(db_path: str, yyyymmdd: str = None) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if not yyyymmdd:
        row = cur.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes").fetchone()
        yyyymmdd = str(row[0] or "").replace("-", "")
    else:
        yyyymmdd = str(yyyymmdd).replace("-", "")
    tw = cur.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','')=? AND market IN ('TW','TSE')",
        (yyyymmdd,),
    ).fetchone()[0]
    two = cur.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','')=? AND market IN ('TWO','OTC','ROCO')",
        (yyyymmdd,),
    ).fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','')=?", (yyyymmdd,)).fetchone()[0]
    chip_n = cur.execute(
        """SELECT COUNT(*) FROM daily_quotes
           WHERE replace(date,'-','')=? AND (ABS(foreign_net)+ABS(trust_net)+ABS(dealer_net))>0""",
        (yyyymmdd,),
    ).fetchone()[0]
    try:
        m_n = cur.execute("SELECT COUNT(*), MAX(yyyymm) FROM monthly_revenue").fetchone()
        q_n = cur.execute("SELECT COUNT(*), MAX(year), MAX(season) FROM quarterly_income").fetchone()
    except sqlite3.OperationalError:
        m_n, q_n = (0, ""), (0, 0, 0)
    try:
        x_n = cur.execute("SELECT COUNT(*), MAX(ex_date) FROM ex_rights").fetchone()
    except sqlite3.OperationalError:
        x_n = (0, "")
    conn.close()
    problems: List[str] = []
    if total == 0:
        problems.append(f"{yyyymmdd} 沒有日 K（休市或匯入失敗）")
    if tw >= MIN_TW and two < MIN_TWO:
        problems.append(f"待補上櫃 {two}/{MIN_TWO}（上市 {tw}）")
    if two >= MIN_TWO and tw < MIN_TW:
        problems.append(f"待補上市 {tw}/{MIN_TW}（上櫃 {two}）")
    if total >= 800 and chip_n < 100:
        problems.append(f"待補法人（非0僅 {chip_n}）")
    latest_month = str(m_n[1] or "")
    monthly_note = monthly_revenue_status(int(m_n[0] or 0), latest_month, today_ymd=yyyymmdd)
    if monthly_note.get("missing"):
        problems.append(monthly_note["problem"])
    if int(x_n[0] or 0) < 50:
        problems.append("待補除權息")
    hist = list_coverage_issues(db_path)
    today_ok = increment_health_ok(
        {
            "date": yyyymmdd,
            "tw": int(tw or 0),
            "two": int(two or 0),
            "total": int(total or 0),
            "chips_nonzero": int(chip_n or 0),
        }
    ) and not problems
    return {
        "date": yyyymmdd,
        "tw": int(tw or 0),
        "two": int(two or 0),
        "total": int(total or 0),
        "chips_nonzero": int(chip_n or 0),
        "monthly_n": int(m_n[0] or 0),
        "latest_month": latest_month,
        "monthly_note": monthly_note,
        "income_n": int(q_n[0] or 0),
        "latest_quarter": f"{q_n[1]}Q{q_n[2]}" if q_n[1] else "",
        "ex_rights_n": int(x_n[0] or 0),
        "latest_ex": x_n[1] or "",
        "ok": today_ok,
        "today_ok": today_ok,
        "problems": problems,
        "history_issues": hist,
        "history_issue_n": len(hist),
    }


def expected_latest_revenue_month(today_ymd: str = "") -> str:
    """依法次月 10 日前應公布的最新月。10 號前通常還停在再上一個月。"""
    raw = _audit_today(today_ymd)
    y, m, d = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
    m -= 2 if d < 11 else 1
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}"


def previous_calendar_month(today_ymd: str = "") -> str:
    raw = _audit_today(today_ymd)
    y, m = int(raw[:4]), int(raw[4:6])
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    return f"{y:04d}{m:02d}"


def _audit_today(today_ymd: str = "") -> str:
    raw = str(today_ymd or "").replace("-", "")[:8]
    if len(raw) != 8 or not raw.isdigit():
        return datetime.now().strftime("%Y%m%d")
    return raw


def monthly_revenue_status(
    monthly_n: int,
    latest_month: str,
    *,
    today_ymd: str = "",
) -> Dict[str, Any]:
    """月營收要分「庫真的沒抓」跟「官方還沒公布」，不能天天喊待補。"""
    expected = expected_latest_revenue_month(today_ymd)
    prev = previous_calendar_month(today_ymd)
    latest = str(latest_month or "").replace("-", "")[:6]
    if int(monthly_n or 0) < 200:
        return {
            "ok": False,
            "missing": True,
            "unpublished": False,
            "expected": expected,
            "latest": latest,
            "problem": "待補月營收（庫內列數不足）",
            "label": "待補月營收（庫內列數不足）",
        }
    if latest and latest < prev:
        return {
            "ok": True,
            "missing": False,
            "unpublished": True,
            "expected": expected,
            "latest": latest,
            "problem": "",
            "label": f"{latest}（官方尚未公布 {prev}）",
        }
    return {
        "ok": True,
        "missing": False,
        "unpublished": False,
        "expected": expected,
        "latest": latest,
        "problem": "",
        "label": f"{latest or '—'}（已跟上官方）",
    }


def quote_lineage(db_path: str, days: int = 5) -> Dict[str, Any]:
    """最近幾個交易日的日K是哪個來源、哪一輪寫進來的。

    出現可疑數字時，沒有這個就只能猜是官方資料錯、還是我們某條補齊路徑寫壞。
    舊列（加欄位之前寫的）source 為空，這裡照實回報而不假裝知道。
    """
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return {"ok": False, "reason": "資料庫不存在", "days": []}
    try:
        conn = sqlite3.connect(path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_quotes)")}
        if "source" not in cols or "fetched_at" not in cols:
            conn.close()
            return {"ok": False, "reason": "尚未升級溯源欄位", "days": []}
        rows = conn.execute(
            """
            SELECT replace(date,'-','') AS d,
                   COALESCE(NULLIF(source,''),'(未記錄)') AS src,
                   COUNT(*) AS n,
                   MAX(fetched_at) AS last_fetch
            FROM daily_quotes
            WHERE replace(date,'-','') IN (
                SELECT replace(date,'-','') FROM daily_quotes
                GROUP BY replace(date,'-','')
                ORDER BY replace(date,'-','') DESC
                LIMIT ?
            )
            GROUP BY d, src
            ORDER BY d DESC, src
            """,
            (max(1, int(days)),),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return {"ok": False, "reason": str(exc), "days": []}

    by_day: Dict[str, Dict[str, Any]] = {}
    for d, src, n, last_fetch in rows:
        entry = by_day.setdefault(str(d), {"date": str(d), "sources": {}, "last_fetch": ""})
        entry["sources"][str(src)] = int(n or 0)
        if str(last_fetch or "") > entry["last_fetch"]:
            entry["last_fetch"] = str(last_fetch or "")
    return {"ok": True, "days": [by_day[k] for k in sorted(by_day, reverse=True)]}


def _schema_health_safe(db_path: str) -> Dict[str, Any]:
    try:
        from db_migrations import schema_health

        return schema_health(db_path)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def inventory_payload(db_path: str) -> Dict[str, Any]:
    """給 Render /inventory 對表：哪些日要補、財報／除權息／母體有幾列。"""
    if not db_quick_check_ok(db_path):
        return {
            "ok": False,
            "error": "database disk image is malformed",
            "latest_complete": "",
            "as_of": "",
        }
    health = audit_import(db_path)
    complete = latest_complete_quote_date(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    counts: Dict[str, int] = {}
    for t in (
        "daily_quotes",
        "monthly_revenue",
        "quarterly_income",
        "ex_rights",
        "stock_universe",
        "technical_indicators",
        "daily_sector_flow",
    ):
        if t in tables:
            counts[t] = int(cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] or 0)
        else:
            counts[t] = 0
    span = cur.execute(
        "SELECT MIN(replace(date,'-','')), MAX(replace(date,'-','')), COUNT(DISTINCT replace(date,'-','')) FROM daily_quotes"
    ).fetchone() if "daily_quotes" in tables else ("", "", 0)
    conn.close()
    gaps = health.get("history_issues") or []
    disk: Dict[str, Any] = {"path": str(db_path or ""), "bytes": 0, "mb": 0.0}
    try:
        nbytes = int(os.path.getsize(db_path))
        disk = {
            "path": str(db_path or ""),
            "bytes": nbytes,
            "mb": round(nbytes / (1024 * 1024), 1),
        }
    except OSError:
        pass
    today_ok = bool(health.get("today_ok") if "today_ok" in health else health.get("ok"))
    return {
        "ok": today_ok,
        "today_ok": today_ok,
        "history_ok": int(health.get("history_issue_n") or 0) == 0,
        "disk": disk,
        "latest_complete": complete or "",
        "as_of": health.get("date") or "",
        "quotes": {
            "rows": counts.get("daily_quotes") or 0,
            "days": int(span[2] or 0),
            "from": span[0] or "",
            "to": span[1] or "",
            "tw": int(health.get("tw") or 0),
            "two": int(health.get("two") or 0),
            "total": int(health.get("total") or 0),
            "chips_nonzero": int(health.get("chips_nonzero") or 0),
        },
        "monthly_revenue": {"rows": counts.get("monthly_revenue") or 0, "latest": health.get("latest_month") or ""},
        "quarterly_income": {"rows": counts.get("quarterly_income") or 0, "latest": health.get("latest_quarter") or ""},
        "ex_rights": {"rows": counts.get("ex_rights_n") or counts.get("ex_rights") or 0, "latest": health.get("latest_ex") or ""},
        "stock_universe": {"rows": counts.get("stock_universe") or 0},
        "daily_sector_flow": {"rows": counts.get("daily_sector_flow") or 0},
        "tables": tables,
        "schema": _schema_health_safe(db_path),
        "lineage": quote_lineage(db_path),
        "gap_n": int(health.get("history_issue_n") or 0),
        "gaps": [{"date": x.get("date"), "tw": x.get("tw"), "two": x.get("two"), "total": x.get("total")} for x in gaps[:50]],
        "fill": health.get("problems") or [],
    }


def release_publish_blockers(
    db_path: str,
    cap: str = None,
    min_quote_rows: int = 100000,
) -> List[str]:
    """盤後 zip 能不能蓋掉舊 Release：今天兩邊齊、法人、月營收、除權息都要在。"""
    try:
        from config import fuse_end_date

        cap = str(cap or fuse_end_date() or "").replace("-", "")[:8]
    except Exception:
        cap = str(cap or "").replace("-", "")[:8]
    inv = inventory_payload(db_path)
    quotes = inv.get("quotes") or {}
    reasons: List[str] = []
    if int(quotes.get("rows") or 0) < int(min_quote_rows):
        reasons.append(f"日K總列 {quotes.get('rows') or 0} 太少（<{min_quote_rows}）")
    complete = str(inv.get("latest_complete") or "")
    if not complete:
        reasons.append("沒有上市＋上櫃都齊的交易日")
    elif cap and complete < cap:
        reasons.append(f"基準日 {complete} 還沒到可融合日 {cap}，舊包不能蓋")
    if int(quotes.get("chips_nonzero") or 0) < 800:
        reasons.append(f"法人非0僅 {quotes.get('chips_nonzero') or 0}")
    monthly_n = int((inv.get("monthly_revenue") or {}).get("rows") or 0)
    if monthly_n < 200:
        reasons.append("月營收未進庫")
    ex_n = int((inv.get("ex_rights") or {}).get("rows") or 0)
    if ex_n < 100:
        reasons.append("除權息未進庫")
    return reasons


def can_publish_release(db_path: str, cap: str = None) -> Dict[str, Any]:
    inv = inventory_payload(db_path)
    reasons = release_publish_blockers(db_path, cap=cap)
    return {
        "ok": not reasons,
        "reasons": reasons,
        "latest_complete": inv.get("latest_complete") or "",
        "gap_n": int(inv.get("gap_n") or 0),
        "quotes": inv.get("quotes") or {},
        "monthly_revenue": inv.get("monthly_revenue") or {},
        "ex_rights": inv.get("ex_rights") or {},
        "daily_sector_flow": inv.get("daily_sector_flow") or {},
    }


def format_audit_plain(health: Dict[str, Any]) -> str:
    """人話報告：先講今天正不正常，再講真的缺什麼。官方還沒公布的不要當成故障。"""
    date = health.get("date") or ""
    today_ok = bool(health.get("today_ok") if "today_ok" in health else increment_health_ok(health))
    head = "今天正常" if today_ok and not health.get("problems") else "今天異常"
    lines = [
        f"盤後匯入 {date}：{head}。上市 {health.get('tw')}　上櫃 {health.get('two')}　合計 {health.get('total')}",
    ]
    month_note = health.get("monthly_note") or monthly_revenue_status(
        int(health.get("monthly_n") or 0),
        str(health.get("latest_month") or ""),
        today_ymd=str(date),
    )
    lines.append(
        f"法人非0 {health.get('chips_nonzero')}　月營收 {health.get('monthly_n')}（{month_note.get('label')}）"
        f"　季報 {health.get('income_n')}（{health.get('latest_quarter')}）"
        f"　除權息 {health.get('ex_rights_n')}（{health.get('latest_ex')}）"
    )
    if health.get("problems"):
        lines.append("今天真的缺：" + "；".join(health["problems"]))
    n = int(health.get("history_issue_n") or 0)
    if n:
        sample = health.get("history_issues") or []
        bits = [f"{x['date']} 上市{x['tw']}/上櫃{x['two']}" for x in sample[:6]]
        lines.append(f"舊日缺邊 {n} 日（不影響今天是否齊）：" + "、".join(bits))
    else:
        lines.append("歷史開盤日上市／上櫃兩邊都齊。")
    return "\n".join(lines)


def verify_increment_import(db_path: str, cap: str = None) -> Dict[str, Any]:
    """盤後 increment 跑完後的硬性關卡（CI／排程）。該有的數字為 0 一律不通過。

    只檢查當日上市／上櫃／合計／法人等非零門檻；Release zip 完整性另由 can_publish_release 關卡負責。
    """
    try:
        from config import fuse_end_date
    except Exception:
        fuse_end_date = lambda: ""  # type: ignore

    cap = str(cap or fuse_end_date() or "").replace("-", "")[:8]
    health = audit_import(db_path, cap) if cap else audit_import(db_path)
    reasons: List[str] = list(increment_health_failures(health, cap=cap))

    return {
        "ok": not reasons,
        "cap": cap,
        "reasons": reasons,
        "health": health,
    }
