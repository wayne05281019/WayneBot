# -*- coding: utf-8 -*-
"""
WayneBot 核心持倉引擎 (Phase 9 終極修復版)
檔案名稱：portfolio_engine.py
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import List, Dict, Any, Tuple, Optional

BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_trading.db")
WEIGHTS_FILE = os.path.join(BASE_DIR, "model_weights.json")

logger = logging.getLogger("WayneBot.PortfolioEngine")


class PortfolioEngine:
    def __init__(
        self,
        db_path: str = DB_PATH,
        weights_path: str = WEIGHTS_FILE,
        total_capital: float = 300000.0,
        tranches_count: int = 4,
        stop_loss_pct: float = 0.07,
        take_profit_pct: float = 0.15,
        trailing_stop_pct: float = 0.05
    ):
        self.db_path = db_path
        self.weights_path = weights_path
        self.total_capital = total_capital
        self.tranches_count = tranches_count
        self.tranche_size = total_capital / tranches_count
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

        self._init_db()
        self._init_weights_file()

    def get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS simulated_positions (
                position_id TEXT PRIMARY KEY,
                stock_id TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                avg_entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                total_shares INTEGER NOT NULL,
                total_cost REAL NOT NULL,
                tranches_used INTEGER DEFAULT 1,
                stop_loss_price REAL NOT NULL,
                take_profit_price REAL NOT NULL,
                trailing_stop_price REAL NOT NULL,
                highest_price_since_entry REAL NOT NULL,
                holding_days INTEGER DEFAULT 0,
                consecutive_chip_sell_days INTEGER DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0.0,
                entry_history TEXT NOT NULL,
                trigger_factors TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                trade_id TEXT PRIMARY KEY,
                position_id TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                exit_date TEXT NOT NULL,
                avg_entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                total_shares INTEGER NOT NULL,
                total_cost REAL NOT NULL,
                pnl_amount REAL NOT NULL,
                pnl_percentage REAL NOT NULL,
                holding_days INTEGER NOT NULL,
                exit_reason TEXT NOT NULL,
                failure_attribution TEXT,
                created_at TEXT NOT NULL
            );
            """)
            conn.commit()

    def _init_weights_file(self) -> None:
        if not os.path.exists(self.weights_path):
            default_weights = {
                "technical_breakout": 0.35,
                "institutional_flow": 0.30,
                "chip_concentration": 0.20,
                "fundamental_growth": 0.15
            }
            self.save_weights(default_weights)

    def load_weights(self) -> Dict[str, float]:
        if not os.path.exists(self.weights_path):
            self._init_weights_file()
        with open(self.weights_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_weights(self, weights: Dict[str, float]) -> None:
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=4, ensure_ascii=False)

    def auto_entry(self, candidates: List[Dict[str, Any]], min_score: float = 85.0) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        qualified = [c for c in candidates if float(c.get("score", c.get("total_score", 0))) >= min_score]
        new_actions = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trade_date = datetime.date.today().strftime("%Y-%m-%d")

        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT SUM(total_cost) as total_invested, SUM(tranches_used) as total_tranches FROM simulated_positions WHERE status = 'OPEN';")
            acc = cur.fetchone()
            used_tranches = dict(acc).get("total_tranches") if acc and dict(acc).get("total_tranches") else 0

            cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
            open_positions = {r["stock_id"]: dict(r) for r in cur.fetchall()}

            for item in qualified:
                if used_tranches >= self.tranches_count:
                    break

                sid = str(item.get("stock_id", item.get("symbol", "")))
                sname = str(item.get("stock_name", item.get("name", sid)))
                c_p = float(item.get("close", 0.0))
                if c_p <= 0.0:
                    continue

                if sid not in open_positions:
                    shares = max(1, int(self.tranche_size / c_p))
                    pos_id = f"POS_{trade_date.replace('-', '')}_{sid}_T1"
                    cost = shares * c_p
                    stop_loss = round(c_p * (1.0 - self.stop_loss_pct), 2)
                    take_profit = round(c_p * (1.0 + self.take_profit_pct), 2)
                    history_entry = [{"date": trade_date, "price": c_p, "shares": shares, "type": "第1段初次試單"}]

                    cur.execute("""
                        INSERT INTO simulated_positions (
                            position_id, stock_id, stock_name, entry_date, avg_entry_price,
                            current_price, total_shares, total_cost, tranches_used,
                            stop_loss_price, take_profit_price, trailing_stop_price,
                            highest_price_since_entry, holding_days, consecutive_chip_sell_days,
                            max_drawdown_pct, entry_history, trigger_factors, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 0, 0, 0.0, ?, ?, 'OPEN', ?, ?);
                    """, (
                        pos_id, sid, sname, trade_date, c_p, c_p, shares, cost,
                        stop_loss, take_profit, stop_loss, c_p,
                        json.dumps(history_entry, ensure_ascii=False),
                        json.dumps(item, ensure_ascii=False), now_str, now_str
                    ))
                    used_tranches += 1
                    open_positions[sid] = {"stock_id": sid}
                    new_actions.append({"stock_id": sid, "stock_name": sname, "action": "第1段建倉", "shares": shares, "cost": cost})
            conn.commit()
        return new_actions

    def daily_portfolio_checkup(self, benchmark_return_pct: float = 0.0) -> Dict[str, Any]:
        active_pos, closed_trades = [], []
        total_unrealized = 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
            rows = cur.fetchall()

            for r in rows:
                r_dict = dict(r)
                sid = r_dict["stock_id"]
                avg_p = float(r_dict["avg_entry_price"])
                latest_p = float(r_dict["current_price"])
                highest_p = max(float(r_dict["highest_price_since_entry"]), latest_p)
                total_shares = int(r_dict["total_shares"])
                total_cost = float(r_dict["total_cost"])
                holding_days = int(r_dict["holding_days"]) + 1
                chip_sell_days = int(r_dict.get("consecutive_chip_sell_days", 0))

                unrealized_pnl = (latest_p - avg_p) * total_shares
                unrealized_pct = ((latest_p - avg_p) / avg_p) * 100.0
                total_unrealized += unrealized_pnl
                mdd_pct = ((highest_p - latest_p) / highest_p * 100.0) if highest_p > 0 else 0.0

                exit_reason = None
                if latest_p <= float(r_dict["stop_loss_price"]):
                    exit_reason = f"觸發停損 ({unrealized_pct:.2f}% <= -{self.stop_loss_pct*100:.1f}%)"
                elif latest_p >= float(r_dict["take_profit_price"]):
                    exit_reason = f"達成停利 ({unrealized_pct:.2f}% >= +{self.take_profit_pct*100:.1f}%)"
                elif chip_sell_days >= 3:
                    exit_reason = "主力籌碼連續3日大賣"

                if exit_reason:
                    attribution = "技術突破與動能延續獲利" if unrealized_pct > 0 else "系統性大盤下殺受阻"
                    trade_id = f"TRD_{r_dict['position_id']}_{today_str.replace('-','')}"
                    cur.execute("""
                        INSERT INTO trade_history (
                            trade_id, position_id, stock_id, stock_name, entry_date,
                            exit_date, avg_entry_price, exit_price, total_shares, total_cost,
                            pnl_amount, pnl_percentage, holding_days, exit_reason,
                            failure_attribution, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        trade_id, r_dict["position_id"], sid, r_dict["stock_name"], r_dict["entry_date"],
                        today_str, avg_p, latest_p, total_shares, total_cost, unrealized_pnl,
                        unrealized_pct, holding_days, exit_reason, attribution, now_str
                    ))
                    cur.execute("UPDATE simulated_positions SET status = 'CLOSED', updated_at = ? WHERE position_id = ?;", (now_str, r_dict["position_id"]))
                    closed_trades.append({"stock_id": sid, "pnl_pct": f"{unrealized_pct:+.2f}%", "reason": exit_reason})
                else:
                    cur.execute("UPDATE simulated_positions SET current_price = ?, highest_price_since_entry = ?, holding_days = ?, max_drawdown_pct = ?, updated_at = ? WHERE position_id = ?;", (latest_p, highest_p, holding_days, mdd_pct, now_str, r_dict["position_id"]))
                    active_pos.append({
                        "stock_id": sid, "stock_name": r_dict["stock_name"],
                        "avg_price": avg_p, "current": latest_p, "shares": total_shares,
                        "cost": total_cost, "tranches": r_dict.get("tranches_used", 1),
                        "pnl_pct": f"{unrealized_pct:+.2f}%", "pnl_amount": round(unrealized_pnl, 2),
                        "mdd_pct": f"{mdd_pct:.1f}%", "holding_days": holding_days,
                        "history": json.loads(r_dict.get("entry_history", "[]"))
                    })
        return {"active": active_pos, "closed": closed_trades, "total_unrealized": round(total_unrealized, 2)}

    def evaluate_performance(self, lookback_trades: int = 50) -> Dict[str, Any]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pnl_percentage, pnl_amount FROM trade_history ORDER BY created_at DESC LIMIT ?;", (lookback_trades,))
            rows = cur.fetchall()

        if not rows:
            return {"total_trades": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0, "cumulative_return_pct": 0.0, "total_pnl_cash": 0.0}

        pnls = [float(r["pnl_percentage"]) / 100.0 for r in rows]
        pnl_cash = sum([float(r["pnl_amount"]) for r in rows])
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = len(pnls)
        win_rate = (len(wins) / total) * 100.0 if total > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 1.0

        cum_ret = 1.0
        for p in reversed(pnls): cum_ret *= (1.0 + p)
        cumulative_return_pct = (cum_ret - 1.0) * 100.0

        return {"total_trades": total, "win_rate": round(win_rate, 2), "profit_loss_ratio": round(pl_ratio, 2), "cumulative_return_pct": round(cumulative_return_pct, 2), "total_pnl_cash": round(pnl_cash, 2)}

    def self_evolving_loop(self, learning_rate: float = 0.03, min_trades: int = 5) -> Dict[str, Any]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pnl_percentage, trigger_factors FROM trade_history ORDER BY created_at DESC LIMIT 30;")
            trades = cur.fetchall()

        if len(trades) < min_trades:
            return {"status": "SKIPPED", "reason": f"樣本數不足 ({len(trades)}/{min_trades})"}

        current_weights = self.load_weights()
        factor_scores = {k: 0.0 for k in current_weights}
        for t in trades:
            pnl = float(t["pnl_percentage"]) / 100.0
            try: factors = json.loads(t["trigger_factors"])
            except Exception: factors = {}
            for k in current_weights.keys():
                if k in factors:
                    val = float(factors[k]) if isinstance(factors[k], (int, float)) else 0.5
                    factor_scores[k] += (pnl * val)

        updated_weights = {}
        for k, current_w in current_weights.items():
            delta = max(-0.05, min(0.05, factor_scores.get(k, 0.0) * learning_rate))
            updated_weights[k] = max(0.05, current_w + delta)

        total_w = sum(updated_weights.values())
        final_weights = {k: round(v / total_w, 4) for k, v in updated_weights.items()}
        self.save_weights(final_weights)
        return {"status": "SUCCESS", "previous_weights": current_weights, "updated_weights": final_weights}
