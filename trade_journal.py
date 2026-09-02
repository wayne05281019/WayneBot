# -*- coding: utf-8 -*-
"""真實持股成交紀錄與復盤（與 AI 模擬倉 wayne_ai 完全分開）。"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def ensure_user_trade_logs(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            action TEXT NOT NULL,
            lots REAL NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            cost_price REAL,
            realized_pnl REAL,
            pnl_pct REAL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_trade_logs_uid ON user_trade_logs(user_id, id DESC);"
    )
    conn.commit()
    conn.close()


def parse_lots_price(
    text: str,
    *,
    default_lots: float = 1.0,
    price_only_sell_all: bool = False,
) -> Tuple[Optional[float], Optional[float]]:
    """
    簡化輸入：
    - 買：「68.5」→ 1張 @ 68.5；「2 68.5」「2@68.5」→ 2張
    - 賣（已選股）：「72」→ 全賣 @ 72；「1 72」→ 賣1張
    """
    raw = (text or "").strip()
    if not raw:
        return None, None
    if raw in ("全賣", "賣光", "全出", "all"):
        return 0.0, None
    t = raw.replace("，", " ").replace("@", " ").replace("＠", " ")
    t = re.sub(r"\s+", " ", t).strip()
    parts = t.split()
    if len(parts) == 1:
        try:
            v = float(parts[0])
        except ValueError:
            return None, None
        if price_only_sell_all:
            return 0.0, v
        return float(default_lots), v
    if len(parts) >= 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None, None
    return None, None


def log_user_trade(
    db_path: str,
    user_id: str,
    *,
    action: str,
    stock_code: str,
    stock_name: str,
    lots: float,
    price: float,
    cost_price: Optional[float] = None,
    realized_pnl: Optional[float] = None,
    pnl_pct: Optional[float] = None,
    note: str = "",
) -> None:
    ensure_user_trade_logs(db_path)
    lots = float(lots or 0)
    price = float(price or 0)
    amount = round(lots * price * 1000.0, 2)
    now = datetime.now()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO user_trade_logs
        (user_id, trade_date, stock_code, stock_name, action, lots, price, amount,
         cost_price, realized_pnl, pnl_pct, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(user_id),
            now.strftime("%Y%m%d"),
            str(stock_code).strip(),
            stock_name or stock_code,
            str(action).upper(),
            lots,
            price,
            amount,
            cost_price,
            realized_pnl,
            pnl_pct,
            note or "",
            now.isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def recent_user_trades(db_path: str, user_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    ensure_user_trade_logs(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT trade_date, action, stock_code, stock_name, lots, price,
               realized_pnl, pnl_pct, note, created_at
        FROM user_trade_logs
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (str(user_id), int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def format_user_trades_html(db_path: str, user_id: str, limit: int = 12) -> str:
    from tg_layout import html_escape, html_price, section_eq

    rows = recent_user_trades(db_path, user_id, limit)
    if not rows:
        return (
            f"{section_eq('我的成交紀錄')}\n"
            "尚無紀錄。買：查股→記買入→打 <code>68.5</code>（1張）或 <code>2 68.5</code>。\n"
            "賣：持股→賣出→打 <code>72</code>（全賣）或 <code>1 72</code>。"
        )
    lines = [
        section_eq("我的成交紀錄"),
        "<i>真實手記，與 AI 模擬倉無關。</i>",
    ]
    for t in rows:
        act = "買" if str(t.get("action") or "").upper() == "BUY" else "賣"
        d = str(t.get("trade_date") or "")
        if len(d) == 8:
            d = f"{d[4:6]}/{d[6:8]}"
        extra = ""
        if act == "賣" and t.get("realized_pnl") is not None:
            try:
                pnl = float(t["realized_pnl"])
                pct = float(t.get("pnl_pct") or 0)
                extra = f"　損益 {pnl:+,.0f}（{pct:+.2f}%）"
            except (TypeError, ValueError):
                pass
        lines.append(
            f"• {d} {act} <code>{html_escape(t.get('stock_code'))}</code> "
            f"{html_escape(t.get('stock_name') or '')} "
            f"{float(t.get('lots') or 0):g}張 @{html_price(t.get('price'), compact=True)}{extra}"
        )
        if t.get("note"):
            lines.append(f"　{html_escape(t['note'])}")
    return "\n".join(lines)


def format_user_review_html(db_path: str, user_id: str) -> str:
    """簡要復盤：賣出勝率、近筆損益。"""
    from tg_layout import html_escape, section_eq

    ensure_user_trade_logs(db_path)
    conn = sqlite3.connect(db_path)
    sells = conn.execute(
        """
        SELECT realized_pnl, pnl_pct, stock_code, stock_name, trade_date
        FROM user_trade_logs
        WHERE user_id=? AND action='SELL' AND realized_pnl IS NOT NULL
        ORDER BY id DESC LIMIT 30
        """,
        (str(user_id),),
    ).fetchall()
    buys = conn.execute(
        "SELECT COUNT(*) FROM user_trade_logs WHERE user_id=? AND action='BUY'",
        (str(user_id),),
    ).fetchone()[0]
    conn.close()
    lines = [section_eq("我的復盤"), "<i>只統計你手記的真實賣出，不含 AI 模擬倉。</i>"]
    lines.append(f"累計買進筆數　{int(buys or 0)}")
    if not sells:
        lines.append("尚無賣出紀錄，復盤會在第一次賣出後出現。")
        return "\n".join(lines)
    pnls = [float(r[0]) for r in sells]
    pcts = [float(r[1]) for r in sells if r[1] is not None]
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    lines.append(f"近 {n} 筆賣出勝率　{wins / n:.0%}")
    lines.append(f"近 {n} 筆平均損益　{sum(pnls) / n:+,.0f} 元")
    if pcts:
        lines.append(f"近 {len(pcts)} 筆平均報酬　{sum(pcts) / len(pcts):+.2f}%")
    best = max(sells, key=lambda r: float(r[0] or 0))
    worst = min(sells, key=lambda r: float(r[0] or 0))
    lines.append(
        f"最佳　<code>{html_escape(best[2])}</code> {float(best[0]):+,.0f} 元"
    )
    lines.append(
        f"最差　<code>{html_escape(worst[2])}</code> {float(worst[0]):+,.0f} 元"
    )
    return "\n".join(lines)


def record_buy(
    db_path: str,
    user_id: str,
    stock_code: str,
    stock_name: str,
    lots: float,
    price: float,
) -> str:
    """記入持股並寫成交日誌（與 AI 模擬倉分開）。"""
    from wayne_db import add_to_portfolio

    code = str(stock_code).strip()
    name = stock_name or code
    lots = float(lots)
    price = float(price)
    add_to_portfolio(db_path, user_id, code, name, lots, price)
    log_user_trade(
        db_path,
        user_id,
        action="BUY",
        stock_code=code,
        stock_name=name,
        lots=lots,
        price=price,
        cost_price=price,
    )
    return f"已記錄買入 {code} {name} {lots:g}張 @ {price}"


def record_sell(db_path: str, user_id: str, stock_code: str, lots: float, price: float) -> str:
    """賣出持股並寫成交日誌。"""
    from wayne_db import SellResult, sell_from_holdings

    result: SellResult = sell_from_holdings(db_path, user_id, stock_code, lots, price)
    if not result.ok:
        return result.message
    log_user_trade(
        db_path,
        user_id,
        action="SELL",
        stock_code=result.stock_code,
        stock_name=result.stock_name,
        lots=result.lots,
        price=result.price,
        cost_price=result.cost_price,
        realized_pnl=result.realized_pnl,
        pnl_pct=result.pnl_pct,
    )
    return result.message
