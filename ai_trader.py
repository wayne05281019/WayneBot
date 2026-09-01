"""WayneBot AI 模擬操盤：50 萬本金、最多分 3 等份、海選紀律買賣、成交寫庫復盤。

不會改寫自己的程式碼；進化是調整倉位比例與哪類海選最近準（寫入資料庫）。
這是模擬倉，不是真實下單。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from portfolio_engine import PortfolioEngine

AI_USER = "wayne_ai"
MAX_SLOTS = 3
STOP_PCT = -7.0
TAKE_PCT = 8.0
STOP_MULT = 0.93
TAKE_MULT = 1.08


def slot_notional(initial_capital: float, size_mult: float = 1.0) -> float:
    """本金固定切成 MAX_SLOTS 等份，空槽不把剩餘現金重切給下一檔。"""
    try:
        cap = float(initial_capital or 0)
    except (TypeError, ValueError):
        cap = 0.0
    try:
        mult = float(size_mult or 1.0)
    except (TypeError, ValueError):
        mult = 1.0
    if cap <= 0:
        return 0.0
    return cap / float(MAX_SLOTS) * max(0.4, min(1.2, mult))


def _shares_for_budget(price: float, budget: float) -> int:
    if price <= 0 or budget <= 0:
        return 0
    lot_cost = price * 1000.0
    if budget >= lot_cost:
        return int(budget // lot_cost) * 1000
    return max(0, int(budget // price))


def _quotes_from_results(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    quotes: Dict[str, Dict[str, Any]] = {}
    for key in (
        "revenue_cross",
        "leave_zero",
        "golden_buy",
        "select_01",
        "select_02",
        "select_03",
        "day_trade",
        "overnight",
    ):
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid:
                continue
            quotes[sid] = {
                "close": float(it.get("close") or 0),
                "stock_name": it.get("stock_name") or it.get("name") or "",
                "is_k20_warning": bool(it.get("chase_warning")),
                "d20": 0.0,
                "pct_change": it.get("pct_change") or 0,
            }
    return quotes


def _candidates(results: Dict[str, List[Dict[str, Any]]], db_path: str = "") -> List[Dict[str, Any]]:
    """隔夜模擬倉：佈局／隔日沖，不拿當沖名單去隔夜。貼月高、美股電子逆風不買。"""
    out, seen = [], set()
    for key, reason in (
        ("leave_zero", "起漲：獲利離零"),
        ("golden_buy", "黃金買點：60低超跌"),
        ("revenue_cross", "優先看：營收轉強×突破"),
        ("overnight", "隔日沖佈局"),
        ("select_01", "周帶量突破"),
    ):
        if db_path:
            try:
                from screen_review import bucket_weight

                if bucket_weight(db_path, key) <= 0:
                    continue
            except Exception:
                pass
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid or sid in seen:
                continue
            if it.get("chase_warning") or it.get("us_peer_headwind") or it.get("us_risk_off"):
                continue
            if float(it.get("close") or 0) <= 0:
                continue
            seen.add(sid)
            row = dict(it)
            row["ai_reason"] = reason
            row["ai_bucket"] = key
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
    """用實際賣出損益＋買進隔日復盤調倉位倍數。"""
    notes = []
    conn = engine._get_connection()
    rows = conn.execute(
        """SELECT pnl_pct FROM trade_logs
           WHERE user_id=? AND action='SELL' AND pnl_pct IS NOT NULL
           ORDER BY id DESC LIMIT 10;""",
        (AI_USER,),
    ).fetchall()
    conn.close()
    wr_sell = None
    if len(rows) >= 5:
        wins = sum(1 for r in rows if float(r["pnl_pct"]) > 0)
        wr_sell = wins / len(rows)
        notes.append(f"賣出近 {len(rows)} 筆勝率 {wr_sell:.0%}")

    wr_buy = None
    try:
        from screen_review import ensure_ai_fills_table

        ensure_ai_fills_table(db_path)
        conn = sqlite3.connect(db_path)
        fills = conn.execute(
            """
            SELECT next_pct FROM ai_fills
            WHERE action='BUY' AND next_pct IS NOT NULL
            ORDER BY id DESC LIMIT 10
            """
        ).fetchall()
        conn.close()
        if len(fills) >= 5:
            hits = sum(1 for r in fills if float(r[0]) > 0)
            wr_buy = hits / len(fills)
            notes.append(f"買進隔日近 {len(fills)} 筆勝率 {wr_buy:.0%}")
    except sqlite3.OperationalError:
        wr_buy = None

    cur = _load_size_mult(db_path)
    wr = wr_buy if wr_buy is not None else wr_sell
    if wr is None:
        return "樣本不足，維持原倉位比例（本金仍分 3 等份）"
    if wr < 0.35:
        _save_size_mult(db_path, cur * 0.85)
        notes.append("縮小單筆倉位")
    elif wr > 0.6:
        _save_size_mult(db_path, cur * 1.05)
        notes.append("略增單筆倉位")
    else:
        notes.append("倉位倍數維持")
    return "，".join(notes)


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


def _last_buy_reasons(engine: PortfolioEngine) -> Dict[str, str]:
    conn = engine._get_connection()
    rows = conn.execute(
        """
        SELECT stock_id, reason FROM trade_logs
        WHERE user_id=? AND action='BUY' AND id IN (
            SELECT MAX(id) FROM trade_logs WHERE user_id=? AND action='BUY' GROUP BY stock_id
        )
        """,
        (AI_USER, AI_USER),
    ).fetchall()
    conn.close()
    return {str(r["stock_id"]): str(r["reason"] or "") for r in rows}


def _realized_pnl(engine: PortfolioEngine) -> float:
    conn = engine._get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl),0) FROM trade_logs WHERE user_id=? AND action='SELL'",
        (AI_USER,),
    ).fetchone()
    conn.close()
    return float(row[0] or 0) if row else 0.0


def _recent_fills(engine: PortfolioEngine, limit: int = 8) -> List[Dict[str, Any]]:
    conn = engine._get_connection()
    rows = conn.execute(
        """
        SELECT date, action, stock_id, stock_name, shares, price, realized_pnl, pnl_pct, reason
        FROM trade_logs WHERE user_id=? ORDER BY id DESC LIMIT ?
        """,
        (AI_USER, int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fmt_ymd(raw: str) -> str:
    s = str(raw or "").replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return str(raw or "")


def _fmt_lots_html(shares: int) -> str:
    from tg_layout import html_qty_tight

    sh = int(shares or 0)
    if sh >= 1000 and sh % 1000 == 0:
        return html_qty_tight(sh / 1000.0, "張", signed=False)
    return html_qty_tight(sh, "股", signed=False)


def format_ai_desk_html(engine: PortfolioEngine, quotes: Optional[dict] = None) -> str:
    """券商帳戶式：總資產／現金／市值／損益、等份槽、持倉停損停利、成交與復盤。"""
    from tg_layout import (
        html_escape,
        html_last_move,
        html_money,
        html_num_paren,
        html_pct,
        html_price,
        kv,
        kv_html,
        price_change,
        section_eq,
        _plain_num,
    )

    quotes = dict(quotes or {})
    held0 = engine.get_portfolio_summary(AI_USER, {})
    quotes = engine.load_quotes_for([p["stock_id"] for p in held0["positions"]], quotes)
    s = engine.get_portfolio_summary(AI_USER, quotes)
    size_mult = _load_size_mult(engine.db_path)
    initial = float(s.get("initial_capital") or 500000)
    slot = slot_notional(initial, size_mult)
    used = int(s["positions_count"])
    reasons = _last_buy_reasons(engine)
    realized = _realized_pnl(engine)
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in s["positions"])

    lines = [
        section_eq("AI 模擬帳戶"),
        "這是模擬倉，不是真實下單。本金最多分 3 等份，單檔不超過一槽；空槽不把剩錢加碼下一檔。",
        "停損 −7%、停利 ＋8%。06:30 海選後與盤後融合自動買賣；進化寫進資料庫，不改程式檔。",
        kv_html("總資產", html_money(s["total_assets"], signed=False), 8),
        kv_html("現金", html_money(s["cash"], signed=False), 8),
        kv_html("市值", html_money(s["stock_market_value"], signed=False), 8),
        kv_html("未實現", html_money(unreal), 8),
        kv_html("已實現", html_money(realized), 8),
        kv_html("總損益", html_num_paren(_plain_num(s["total_pnl"], signed=True), s["total_pnl_pct"]), 8),
        kv("已用槽", f"{used}/{MAX_SLOTS} 每槽上限 {slot:,.0f}", 8),
        kv("本金", f"{initial:,.0f} 倍數 {size_mult:.2f}", 8),
    ]
    if not s["positions"]:
        lines.append(
            f"<i>尚無持倉。{MAX_SLOTS} 個空槽、每槽 {slot:,.0f}。有名單才買；貼月高／美股逆風／當沖名單不隔夜。</i>"
        )
    else:
        lines.append("<b>持倉</b>")
        for i, p in enumerate(s["positions"]):
            if i:
                lines.append("")
            sid = p["stock_id"]
            name = p.get("stock_name") or ""
            cost = float(p["cost_price"] or 0)
            last = float(p["current_price"] or cost)
            pct = p.get("pct_change")
            chg = price_change(last, pct) if pct is not None else last - cost
            move_pct = float(pct) if pct is not None else float(p.get("pnl_pct") or 0)
            stop_px = float(p.get("stop_price") or (cost * STOP_MULT))
            take_px = float(p.get("take_price") or (cost * TAKE_MULT))
            try:
                from stock_links import html_stock_anchor

                title = html_stock_anchor(sid, name, engine.db_path)
            except Exception:
                title = f"<code>{html_escape(sid)}</code> {html_escape(name)}"
            lines.append(title)
            lines.append(kv_html("張數", _fmt_lots_html(int(p["shares"])), 8))
            lines.append(kv_html("成本", html_price(cost), 8))
            if chg is not None:
                lines.append(kv_html("現價", html_last_move(last, chg, move_pct), 8))
            else:
                lines.append(kv_html("現價", html_price(last), 8))
            lines.append(
                kv_html(
                    "未實現",
                    html_num_paren(_plain_num(p["unrealized_pnl"], signed=True), p["pnl_pct"]),
                    8,
                )
            )
            lines.append(
                kv_html("停損", html_num_paren(f"{stop_px:,.2f}", STOP_PCT), 8)
            )
            lines.append(
                kv_html("停利", html_num_paren(f"{take_px:,.2f}", TAKE_PCT), 8)
            )
            reason = reasons.get(sid) or "海選紀律"
            bought = _fmt_ymd(p.get("buy_date") or "")
            lines.append(kv("進場", f"{reason} {bought}".strip(), 8))
        empty = MAX_SLOTS - used
        if empty > 0:
            lines.append(f"<b>空槽</b>　{empty}/{MAX_SLOTS}　每槽仍 {slot:,.0f}（不把剩錢重切）")

    fills = _recent_fills(engine, 8)
    if fills:
        lines.append("<b>成交紀錄</b>")
        for t in fills:
            act = "買" if str(t.get("action") or "").upper() == "BUY" else "賣"
            lot = _fmt_lots_html(int(t.get("shares") or 0))
            extra = ""
            if str(t.get("action") or "").upper() == "SELL":
                extra = " " + html_num_paren(_plain_num(t.get("realized_pnl"), signed=True), t.get("pnl_pct"))
            lines.append(
                f"• {_fmt_ymd(t.get('date'))} {act} <code>{html_escape(t.get('stock_id'))}</code> "
                f"{html_escape(t.get('stock_name') or '')} {lot} @{html_price(t.get('price'))}"
                f"{extra}"
            )
            if t.get("reason"):
                lines.append(f"　{html_escape(t['reason'])}")

    conn = sqlite3.connect(engine.db_path)
    try:
        rows = conn.execute(
            "SELECT date, nav, pnl_pct FROM ai_nav_log ORDER BY date DESC LIMIT 5;"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    if rows:
        lines.append("<b>淨值</b>")
        for date, nav, pnl in rows:
            lines.append(
                f"• {_fmt_ymd(date)} {html_money(nav, signed=False)} {html_pct(pnl).strip()}"
            )
    try:
        from screen_review import format_ai_review_html, format_review_html

        ai_rev = format_ai_review_html(engine.db_path)
        if ai_rev:
            lines.append(ai_rev)
        rev = format_review_html(engine.db_path)
        if rev:
            lines.append(rev)
    except Exception:
        pass
    return "\n".join(lines)


def _record_fill(db_path: str, as_of: str, action: str, result: Dict[str, Any], reason: str = "", bucket: str = "") -> None:
    try:
        from screen_review import persist_ai_fill

        persist_ai_fill(
            db_path,
            as_of=as_of,
            stock_id=result.get("stock_id") or "",
            stock_name=result.get("stock_name") or "",
            action=action,
            price=float(result.get("price") or 0),
            shares=int(result.get("shares") or result.get("sold_shares") or 0),
            amount=float(result.get("total_cost") or result.get("net_proceeds") or 0),
            reason=reason or "",
            bucket=bucket or "",
            realized_pnl=float(result.get("realized_pnl") or 0),
            pnl_pct=float(result.get("pnl_pct") or 0),
        )
    except Exception:
        pass


def run_ai_desk(db_path: str, results: Dict[str, List[Dict[str, Any]]], as_of: str) -> Dict[str, Any]:
    engine = PortfolioEngine(db_path)
    engine.ensure_user_exists(AI_USER)
    try:
        from screen_review import score_ai_fills

        score_ai_fills(db_path)
    except Exception:
        pass
    lesson = _adapt_from_trades(engine, db_path)
    size_mult = _load_size_mult(db_path)

    seed = engine.get_portfolio_summary(AI_USER, {})
    result_quotes = _quotes_from_results(results)
    quotes = engine.load_quotes_for(
        [p["stock_id"] for p in seed["positions"]],
        result_quotes,
    )

    sold = []
    for sig in engine.evaluate_exit_signals(AI_USER, quotes):
        r = engine.sell(
            AI_USER, as_of, sig["stock_id"], float(sig["current_price"]),
            shares=int(sig["shares"]), reason=sig["reason"],
        )
        if r.get("success"):
            sold.append(r["msg"])
            _record_fill(db_path, as_of, "SELL", r, reason=sig.get("reason") or "")

    summary = engine.get_portfolio_summary(AI_USER, quotes)
    for p in list(summary["positions"]):
        if p["pnl_pct"] <= STOP_PCT:
            r = engine.sell(AI_USER, as_of, p["stock_id"], p["current_price"], reason="紀律停損 -7%")
            if r.get("success"):
                sold.append(r["msg"])
                _record_fill(db_path, as_of, "SELL", r, reason="紀律停損 -7%")
        elif p["pnl_pct"] >= TAKE_PCT:
            r = engine.sell(AI_USER, as_of, p["stock_id"], p["current_price"], reason="紀律停利 +8%")
            if r.get("success"):
                sold.append(r["msg"])
                _record_fill(db_path, as_of, "SELL", r, reason="紀律停利 +8%")

    summary = engine.get_portfolio_summary(AI_USER, quotes)
    held = {p["stock_id"] for p in summary["positions"]}
    slots = MAX_SLOTS - len(held)
    bought = []
    cash = summary["cash"]
    initial = float(summary.get("initial_capital") or 500000)
    budget = min(slot_notional(initial, size_mult), cash)
    cands = _candidates(results, db_path)
    for it in cands:
        if slots <= 0:
            break
        sid = str(it.get("stock_id") or it.get("code") or "")
        if sid in held:
            continue
        price = float(it.get("close") or 0)
        name = it.get("stock_name") or it.get("name") or sid
        if price <= 0:
            continue
        cash = engine.get_cash(AI_USER)
        budget = min(slot_notional(initial, size_mult), cash)
        shares = _shares_for_budget(price, budget)
        if shares <= 0:
            continue
        reason = it.get("ai_reason") or "海選紀律"
        r = engine.buy(
            AI_USER, as_of, sid, name, price, shares,
            reason=reason,
            strategy_type="MOMENTUM",
        )
        if r.get("success"):
            bought.append(r["msg"])
            held.add(sid)
            slots -= 1
            _record_fill(
                db_path, as_of, "BUY", r,
                reason=reason, bucket=str(it.get("ai_bucket") or ""),
            )

    _snapshot(engine, db_path, as_of, quotes, lesson)
    return {
        "sold": sold,
        "bought": bought,
        "lesson": lesson,
        "candidates": len(cands),
        "slot": slot_notional(initial, size_mult),
        "html": format_ai_desk_html(engine, quotes),
    }
