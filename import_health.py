# -*- coding: utf-8 -*-
"""盤後匯入健康檢查：上市／上櫃必須同一開盤日都進庫，並核對法人與財報快照。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List


def list_coverage_issues(
    db_path: str,
    min_tw: int = 800,
    min_two: int = 400,
    min_total: int = 1500,
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
            problems.append(f"全日只有 {n_i} 檔")
        if tw_i >= min_tw and two_i < min_two:
            problems.append(f"上櫃只有 {two_i}（上市 {tw_i}）")
        if two_i >= min_two and tw_i < min_tw:
            problems.append(f"上市只有 {tw_i}（上櫃 {two_i}）")
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
    if tw >= 800 and two < 400:
        problems.append(f"上櫃只有 {two} 檔（上市 {tw}），櫃買收盤可能沒寫進")
    if two >= 400 and tw < 800:
        problems.append(f"上市只有 {tw} 檔（上櫃 {two}），證交所收盤可能沒寫進")
    if total >= 800 and chip_n < 100:
        problems.append("法人買賣超幾乎全 0，T86 可能失敗")
    if int(m_n[0] or 0) < 200:
        problems.append("月營收列過少，官方月報尚未同步")
    if int(x_n[0] or 0) < 50:
        problems.append("除權息列過少，官方 TWT49U／櫃買尚未同步")
    hist = list_coverage_issues(db_path)
    return {
        "date": yyyymmdd,
        "tw": int(tw or 0),
        "two": int(two or 0),
        "total": int(total or 0),
        "chips_nonzero": int(chip_n or 0),
        "monthly_n": int(m_n[0] or 0),
        "latest_month": m_n[1] or "",
        "income_n": int(q_n[0] or 0),
        "latest_quarter": f"{q_n[1]}Q{q_n[2]}" if q_n[1] else "",
        "ex_rights_n": int(x_n[0] or 0),
        "latest_ex": x_n[1] or "",
        "ok": not problems,
        "problems": problems,
        "history_issues": hist,
        "history_issue_n": len(hist),
    }


def format_audit_plain(health: Dict[str, Any]) -> str:
    lines = [
        f"盤後匯入 {health.get('date')}：上市 {health.get('tw')}　上櫃 {health.get('two')}　合計 {health.get('total')}",
        f"法人非0 {health.get('chips_nonzero')}　月營收 {health.get('monthly_n')}（{health.get('latest_month')}）　季報 {health.get('income_n')}（{health.get('latest_quarter')}）　除權息 {health.get('ex_rights_n')}（{health.get('latest_ex')}）",
    ]
    if health.get("problems"):
        lines.append("當日問題：" + "；".join(health["problems"]))
    n = int(health.get("history_issue_n") or 0)
    if n:
        sample = health.get("history_issues") or []
        bits = [f"{x['date']} 上市{x['tw']}/上櫃{x['two']}" for x in sample[:6]]
        lines.append(f"歷史缺邊 {n} 日：" + "、".join(bits))
    else:
        lines.append("歷史開盤日上市／上櫃兩邊都齊。")
    return "\n".join(lines)
