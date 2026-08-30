"""WayneBot AI 模擬操盤：50 萬本金、海選紀律買賣、每日記帳。

不會改寫自己的程式碼；進化是調整倉位比例與停損參數（寫入資料庫）。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from portfolio_engine import PortfolioEngine

AI_USER = "wayne_ai"
MAX_SLOTS = 5
STOP_PCT = -7.0
TAKE_PCT = 8.0


def _quotes_from_results(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    quotes: Dict[str, Dict[str, Any]] = {}
    for key in ("revenue_cross", "select_01", "day_trade", "overnight", "select_02"):
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid:
                continue
            quotes[sid] = {
                "close": float(it.get("close") or 0),
                "stock_name": it.get("stock_name") or it.get("name") or "",
                "is_k20_warning": False,
                "d20": 0.0,
                "pct_change": it.get("pct_change") or 0,
            }
    return quotes


def _candidates(results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for key, reason in (
        ("revenue_cross", "優先看：營收轉強×突破"),
        ("day_trade", "當沖動能"),
        ("overnight", "隔日沖佈局"),
        ("select_01", "周帶量突破"),
    ):
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            row = dict(it)
            row["ai_reason"] = reason
            out.append(row)
    return out


def _load_size_mult(db_path: str) -> float:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL);"
    )
    row = conn.execute("SELECT v FROM ai_params WHERE k='size_mult'").fetchone()
    conn.close()
    return float(row[0]) if row else 1.0


def _save_size_mult(db_path: str, mult: float) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL);"
    )
    conn.execute(
        "INSERT OR REPLACE INTO ai_params (k, v) VALUES ('size_mult', ?);",
        (max(0.4, min(1.2, mult)),),
    )
    conn.commit()
    conn.close()


def _adapt_from_trades(engine: PortfolioEngine, db_path: str) -> str:
    conn = engine._get_connection()
    rows = conn.execute(
        """SELECT pnl_pct FROM trade_logs
           WHERE user_id=? AND action='SELL' AND pnl_pct IS NOT NULL
           ORDER BY id DESC LIMIT 10;""",
        (AI_USER,),
    ).fetchall()
    conn.close()
    if len(rows) < 5:
        return "樣本不足，維持原倉位比例"
    wins = sum(1 for r in rows if float(r["pnl_pct"]) > 0)
    wr = wins / len(rows)
    cur = _load_size_mult(db_path)
    if wr < 0.35:
        _save_size_mult(db_path, cur * 0.85)
        return f"近 {len(rows)} 筆勝率 {wr:.0%}，縮小單筆倉位"
    if wr > 0.6:
        _save_size_mult(db_path, cur * 1.05)
        return f"近 {len(rows)} 筆勝率 {wr:.0%}，略增單筆倉位"
    return f"近 {len(rows)} 筆勝率 {wr:.0%}，倉位比例維持"


def _snapshot(engine: PortfolioEngine, db_path: str, as_of: str, quotes: dict, note: str) -> None:
    s = engine.get_portfolio_summary(AI_USER, quotes)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_nav_log (
            date TEXT PRIMARY KEY,
            nav REAL, cash REAL, market_value REAL, pnl_pct REAL, note TEXT
        );"""
    )
    conn.execute(
        """INSERT OR REPLACE INTO ai_nav_log (date, nav, cash, market_value, pnl_pct, note)
           VALUES (?, ?, ?, ?, ?, ?);""",
        (as_of, s["total_assets"], s["cash"], s["stock_market_value"], s["total_pnl_pct"], note),
    )
    conn.commit()
    conn.close()


def format_ai_desk_html(engine: PortfolioEngine, quotes: dict | None = None) -> str:
    s = engine.get_portfolio_summary(AI_USER, quotes)
    lines = [
        "<b>AI 模擬操盤（50 萬本金）</b>",
        "本金分最多 5 等份；優先看→當沖→隔日沖→周突破；整張優先否則零股。",
        "停損 -7%、停利 +8%。進化是調倉位比例（寫入資料庫），不會改程式檔。",
        f"總資產 <code>{s['total_assets']:,.0f}</code>　現金 <code>{s['cash']:,.0f}</code>",
        f"損益 <code>{s['total_pnl']:+,.0f}</code>（{s['total_pnl_pct']:+.2f}%）　持股 {s['positions_count']}/{MAX_SLOTS} 檔",
    ]
    if not s["positions"]:
        lines.append("<i>尚無持倉。盤後自動買賣，或在持股頁按「立刻依海選操盤」。</i>")
    else:
        for p in s["positions"]:
            lot = p["shares"] / 1000.0
            lines.append(
                f"• {p['stock_id']} {p['stock_name']} {lot:g}張/{p['shares']}股 "
                f"成本 {p['cost_price']} 現 {p['current_price']} {p['pnl_pct']:+.2f}%"
            )
    conn = sqlite3.connect(engine.db_path)
    try:
        rows = conn.execute(
            "SELECT date, nav, pnl_pct FROM ai_nav_log ORDER BY date DESC LIMIT 7;"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    if rows:
        lines.append("<b>近況淨值</b>")
        for date, nav, pnl in rows:
            lines.append(f"• {date}　{nav:,.0f}　{pnl:+.2f}%")
    return "\n".join(lines)


def run_ai_desk(db_path: str, results: Dict[str, List[Dict[str, Any]]], as_of: str) -> Dict[str, Any]:
    engine = PortfolioEngine(db_path)
    engine.ensure_user_exists(AI_USER)
    quotes = _quotes_from_results(results)
    lesson = _adapt_from_trades(engine, db_path)
    size_mult = _load_size_mult(db_path)

    sold = []
    for sig in engine.evaluate_exit_signals(AI_USER, quotes):
        r = engine.sell(
            AI_USER, as_of, sig["stock_id"], float(sig["current_price"]),
            shares=int(sig["shares"]), reason=sig["reason"],
        )
        if r.get("success"):
            sold.append(r["msg"])

    summary = engine.get_portfolio_summary(AI_USER, quotes)
    for p in list(summary["positions"]):
        if p["pnl_pct"] <= STOP_PCT:
            r = engine.sell(AI_USER, as_of, p["stock_id"], p["current_price"], reason="紀律停損 -7%")
            if r.get("success"):
                sold.append(r["msg"])
        elif p["pnl_pct"] >= TAKE_PCT:
            r = engine.sell(AI_USER, as_of, p["stock_id"], p["current_price"], reason="紀律停利 +8%")
            if r.get("success"):
                sold.append(r["msg"])

    summary = engine.get_portfolio_summary(AI_USER, quotes)
    held = {p["stock_id"] for p in summary["positions"]}
    slots = MAX_SLOTS - len(held)
    bought = []
    cash = summary["cash"]
    if slots > 0:
        budget = (cash / slots) * size_mult
        for it in _candidates(results):
            if slots <= 0:
                break
            sid = str(it.get("stock_id") or it.get("code") or "")
            if sid in held:
                continue
            price = float(it.get("close") or 0)
            name = it.get("stock_name") or it.get("name") or sid
            if price <= 0:
                continue
            if budget >= price * 1000:
                shares = int(budget // (price * 1000)) * 1000
            else:
                shares = max(1, int(budget // price))
            if shares <= 0:
                continue
            r = engine.buy(
                AI_USER, as_of, sid, name, price, shares,
                reason=it.get("ai_reason") or "海選紀律",
                strategy_type="MOMENTUM",
            )
            if r.get("success"):
                bought.append(r["msg"])
                held.add(sid)
                slots -= 1
                cash = r["remaining_cash"]
                if slots > 0:
                    budget = (cash / slots) * size_mult

    _snapshot(engine, db_path, as_of, quotes, lesson)
    return {
        "sold": sold,
        "bought": bought,
        "lesson": lesson,
        "html": format_ai_desk_html(engine, quotes),
    }
