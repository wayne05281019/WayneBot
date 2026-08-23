# -*- coding: utf-8 -*-
"""
WayneBot 核心持倉引擎 (Phase 9)：槓鈴策略分配、7%停損/15%停利、歸因分析與自我進化閉環
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
    """持倉管理、部位體檢、出場判定、績效覆盤與因子權重自我校準引擎"""

    def __init__(
        self,
        db_path: str = DB_PATH,
        weights_path: str = WEIGHTS_FILE,
        stop_loss_pct: float = 0.07,
        take_profit_pct: float = 0.15,
        trailing_stop_pct: float = 0.05
    ):
        self.db_path = db_path
        self.weights_path = weights_path
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
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                shares INTEGER NOT NULL,
                position_type TEXT NOT NULL,
                stop_loss_price REAL NOT NULL,
                take_profit_price REAL NOT NULL,
                trailing_stop_price REAL NOT NULL,
                highest_price_since_entry REAL NOT NULL,
                holding_days INTEGER DEFAULT 0,
                consecutive_chip_sell_days INTEGER DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0.0,
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
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                shares INTEGER NOT NULL,
                pnl_amount REAL NOT NULL,
                pnl_percentage REAL NOT NULL,
                holding_days INTEGER NOT NULL,
                exit_reason TEXT NOT NULL,
                trigger_factors TEXT NOT NULL,
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

    def auto_entry(
        self,
        candidates: List[Dict[str, Any]],
        total_capital: float = 100000.0,
        min_score: float = 85.0
    ) -> List[Dict[str, Any]]:
        """Phase 9 規範：得分 >= 85 自動依槓鈴策略 (40%/35%/25%) 建倉"""
        if not candidates:
            return []

        qualified = [c for c in candidates if float(c.get("score", c.get("total_score", 0))) >= min_score]
        if not qualified:
            return []

        allocations = [
            ("CORE (核心 40%)", 0.40),
            ("SATELLITE (衛星 35%)", 0.35),
            ("MOMENTUM (動能 25%)", 0.25)
        ]
        
        new_positions = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trade_date = datetime.datetime.now().strftime("%Y-%m-%d")

        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT stock_id FROM simulated_positions WHERE status = 'OPEN';")
            open_stock_ids = {row["stock_id"] for row in cur.fetchall()}

            for idx, item in enumerate(qualified[:3]):
                sid = str(item.get("stock_id", item.get("symbol", "")))
                if sid in open_stock_ids:
                    continue

                pos_type, capital_ratio = allocations[idx]
                sname = str(item.get("stock_name", item.get("name", sid)))
                c_p = float(item.get("close", 0.0))
                if c_p <= 0.0:
                    continue

                pos_capital = total_capital * capital_ratio
                shares = max(1, int(pos_capital / c_p))
                pos_id = f"POS_{trade_date.replace('-', '')}_{sid}_{idx+1}"

                stop_loss = round(c_p * (1.0 - self.stop_loss_pct), 2)
                take_profit = round(c_p * (1.0 + self.take_profit_pct), 2)

                cur.execute("""
                    INSERT OR REPLACE INTO simulated_positions (
                        position_id, stock_id, stock_name, entry_date, entry_price,
                        current_price, shares, position_type, stop_loss_price,
                        take_profit_price, trailing_stop_price, highest_price_since_entry,
                        holding_days, consecutive_chip_sell_days, max_drawdown_pct,
                        trigger_factors, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0.0, ?, 'OPEN', ?, ?);
                """, (
                    pos_id, sid, sname, trade_date, c_p, c_p, shares, pos_type,
                    stop_loss, take_profit, stop_loss, c_p,
                    json.dumps(item, ensure_ascii=False), now_str, now_str
                ))

                open_stock_ids.add(sid)
                new_positions.append({
                    "pos_id": pos_id, "stock_id": sid, "stock_name": sname,
                    "type": pos_type, "entry_price": c_p, "shares": shares,
                    "stop_loss": stop_loss, "take_profit": take_profit,
                    "score": item.get("score", item.get("total_score", min_score))
                })
        return new_positions

    def daily_portfolio_checkup(self, benchmark_return_pct: float = 0.0) -> Dict[str, Any]:
        """每日持倉體檢 (7% 停損 / 15% 停利 / 主力大賣 3 日 / MDD)"""
        active_pos, closed_trades = [], []
        total_unrealized = 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
            rows = cur.fetchall()

            for r in rows:
                sid = r["stock_id"]
                entry_p = float(r["entry_price"])
                latest_p = float(r["current_price"])
                highest_p = max(float(r["highest_price_since_entry"]), latest_p)
                shares = int(r["shares"])
                holding_days = int(r["holding_days"]) + 1
                chip_sell_days = int(r["consecutive_chip_sell_days"])

                unrealized_pnl = (latest_p - entry_p) * shares
                unrealized_pct = ((latest_p - entry_p) / entry_p) * 100.0
                total_unrealized += unrealized_pnl
                mdd_pct = ((highest_p - latest_p) / highest_p * 100.0) if highest_p > 0 else 0.0

                exit_reason = None
                if latest_p <= float(r["stop_loss_price"]):
                    exit_reason = f"觸發停損 (跌幅 {unrealized_pct:.2f}% <= -{self.stop_loss_pct*100:.1f}%)"
                elif latest_p >= float(r["take_profit_price"]):
                    exit_reason = f"達成停利目標 (漲幅 {unrealized_pct:.2f}% >= +{self.take_profit_pct*100:.1f}%)"
                elif highest_p >= entry_p * (1.0 + self.take_profit_pct * 0.7) and (mdd_pct / 100.0) >= self.trailing_stop_pct:
                    exit_reason = f"觸發移動停利 (自高點回撤 {mdd_pct:.2f}% >= {self.trailing_stop_pct*100:.1f}%)"
                elif chip_sell_days >= 3:
                    exit_reason = "籌碼異常 (主力籌碼連續3日大賣超)"

                if exit_reason:
                    attribution = self._attribute_trade(unrealized_pct / 100.0, benchmark_return_pct, chip_sell_days, exit_reason)
                    trade_id = f"TRD_{r['position_id']}_{today_str.replace('-','')}"

                    cur.execute("""
                        INSERT INTO trade_history (
                            trade_id, position_id, stock_id, stock_name, entry_date,
                            exit_date, entry_price, exit_price, shares, pnl_amount,
                            pnl_percentage, holding_days, exit_reason, trigger_factors,
                            failure_attribution, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        trade_id, r["position_id"], sid, r["stock_name"], r["entry_date"],
                        today_str, entry_p, latest_p, shares, unrealized_pnl,
                        unrealized_pct, holding_days, exit_reason, r["trigger_factors"],
                        attribution, now_str
                    ))
                    
                    cur.execute("""
                        UPDATE simulated_positions
                        SET status = 'CLOSED', current_price = ?, highest_price_since_entry = ?,
                            holding_days = ?, max_drawdown_pct = ?, updated_at = ?
                        WHERE position_id = ?;
                    """, (latest_p, highest_p, holding_days, mdd_pct, now_str, r["position_id"]))

                    closed_trades.append({
                        "stock_id": sid, "stock_name": r["stock_name"],
                        "pnl_amount": round(unrealized_pnl, 2), "pnl_pct": f"{unrealized_pct:+.2f}%",
                        "holding_days": holding_days, "reason": exit_reason, "attribution": attribution
                    })
                else:
                    cur.execute("""
                        UPDATE simulated_positions
                        SET current_price = ?, highest_price_since_entry = ?, holding_days = ?,
                            max_drawdown_pct = ?, updated_at = ?
                        WHERE position_id = ?;
                    """, (latest_p, highest_p, holding_days, mdd_pct, now_str, r["position_id"]))

                    active_pos.append({
                        "stock_id": sid, "stock_name": r["stock_name"], "type": r["position_type"],
                        "entry": entry_p, "current": latest_p, "shares": shares,
                        "pnl_pct": f"{unrealized_pct:+.2f}%", "pnl_amount": round(unrealized_pnl, 2),
                        "mdd_pct": f"{mdd_pct:.1f}%", "holding_days": holding_days
                    })

        return {"active": active_pos, "closed": closed_trades, "total_unrealized": round(total_unrealized, 2)}

    def _attribute_trade(self, pnl_pct: float, benchmark_return_pct: float, chip_sell_days: int, exit_reason: str) -> str:
        if pnl_pct > 0: return "技術突破與多頭動能延續獲利"
        if benchmark_return_pct < -0.015: return "系統性大盤下殺受阻"
        if chip_sell_days >= 2: return "主力籌碼獲利了結出貨"
        if "停損" in exit_reason: return "假突破多頭力竭回撤"
        return "常態震盪洗盤出場"

    def evaluate_performance(self, lookback_trades: int = 50) -> Dict[str, Any]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pnl_percentage FROM trade_history ORDER BY created_at DESC LIMIT ?;", (lookback_trades,))
            rows = cur.fetchall()

        if not rows:
            return {"total_trades": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0, "cumulative_return_pct": 0.0}

        pnls = [float(r["pnl_percentage"]) / 100.0 for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total = len(pnls)
        win_rate = (len(wins) / total) * 100.0 if total > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 1.0

        cum_ret = 1.0
        for p in reversed(pnls):
            cum_ret *= (1.0 + p)
        cumulative_return_pct = (cum_ret - 1.0) * 100.0

        return {
            "total_trades": total,
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(pl_ratio, 2),
            "cumulative_return_pct": round(cumulative_return_pct, 2)
        }

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
            delta = factor_scores.get(k, 0.0) * learning_rate
            delta = max(-0.05, min(0.05, delta))
            updated_weights[k] = max(0.05, current_w + delta)

        total_w = sum(updated_weights.values())
        final_weights = {k: round(v / total_w, 4) for k, v in updated_weights.items()}
        self.save_weights(final_weights)

        return {"status": "SUCCESS", "previous_weights": current_weights, "updated_weights": final_weights}
