"""
WayneBot 台股量化交易系統
Phase 9: AI 模擬買賣持倉追蹤與自我進化閉環模組 (portfolio_engine.py)
"""

import os
import json
import sqlite3
import datetime
from typing import List, Dict, Any, Tuple, Optional


class PortfolioEngine:
    """
    持倉管理、部位體檢、出場判定、績效覆盤與因子權重自我校準引擎
    """

    def __init__(
        self,
        db_path: str = "wayne_bot.db",
        weights_path: str = "model_weights.json",
        default_stop_loss_pct: float = 0.07,
        default_take_profit_pct: float = 0.15,
        default_trailing_stop_pct: float = 0.05
    ):
        self.db_path = db_path
        self.weights_path = weights_path
        self.default_stop_loss_pct = default_stop_loss_pct
        self.default_take_profit_pct = default_take_profit_pct
        self.default_trailing_stop_pct = default_trailing_stop_pct

        self._init_db()
        self._init_weights_file()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化資料庫表結構 (WAL 模式加速寫入)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")

        # 模擬持倉表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulated_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL NOT NULL,
            highest_price REAL NOT NULL,
            stop_loss_pct REAL NOT NULL,
            take_profit_pct REAL NOT NULL,
            trailing_stop_pct REAL NOT NULL,
            trigger_factors TEXT NOT NULL,
            holding_days INTEGER DEFAULT 0,
            consecutive_chip_sell_days INTEGER DEFAULT 0,
            unrealized_pnl_pct REAL DEFAULT 0.0,
            max_drawdown_pct REAL DEFAULT 0.0,
            status TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 交易歷史表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            exit_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            holding_days INTEGER NOT NULL,
            exit_reason TEXT NOT NULL,
            trigger_factors TEXT NOT NULL,
            attribution TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        conn.close()

    def _init_weights_file(self) -> None:
        """若權重設定檔不存在，建立預設權重"""
        if not os.path.exists(self.weights_path):
            default_weights = {
                "technical_breakout": 0.35,
                "institutional_flow": 0.30,
                "chip_concentration": 0.20,
                "fundamental_growth": 0.15
            }
            self.save_weights(default_weights)

    def load_weights(self) -> Dict[str, float]:
        """讀取模型權重"""
        if not os.path.exists(self.weights_path):
            self._init_weights_file()
        with open(self.weights_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_weights(self, weights: Dict[str, float]) -> None:
        """儲存模型權重"""
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=4, ensure_ascii=False)

    # -------------------------------------------------------------
    # 1. 模擬自動建倉 (Paper Trade Entry)
    # -------------------------------------------------------------
    def auto_entry(
        self,
        screened_candidates: List[Dict[str, Any]],
        trade_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        對評分 >= 85 的標的進行建倉。已在倉中則不重複建立。
        """
        if trade_date is None:
            trade_date = datetime.date.today().strftime("%Y-%m-%d")

        entered_trades = []
        conn = self._get_connection()
        cursor = conn.cursor()

        # 取得目前已在倉的股票代碼
        cursor.execute("SELECT stock_id FROM simulated_positions WHERE status = 'OPEN'")
        open_stock_ids = {row["stock_id"] for row in cursor.fetchall()}

        for candidate in screened_candidates:
            score = candidate.get("score", 0)
            stock_id = candidate.get("stock_id", "")
            stock_name = candidate.get("stock_name", "")
            entry_price = candidate.get("close_price", candidate.get("entry_price", 0.0))
            factors = candidate.get("trigger_factors", candidate.get("factors", {}))

            if score >= 85 and stock_id not in open_stock_ids and entry_price > 0:
                cursor.execute("""
                INSERT INTO simulated_positions (
                    stock_id, stock_name, entry_date, entry_price, current_price,
                    highest_price, stop_loss_pct, take_profit_pct, trailing_stop_pct,
                    trigger_factors, holding_days, consecutive_chip_sell_days,
                    unrealized_pnl_pct, max_drawdown_pct, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0.0, 0.0, 'OPEN')
                """, (
                    stock_id,
                    stock_name,
                    trade_date,
                    entry_price,
                    entry_price,
                    entry_price,
                    self.default_stop_loss_pct,
                    self.default_take_profit_pct,
                    self.default_trailing_stop_pct,
                    json.dumps(factors, ensure_ascii=False)
                ))

                open_stock_ids.add(stock_id)
                entered_trades.append({
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "entry_date": trade_date,
                    "entry_price": entry_price,
                    "score": score,
                    "factors": factors
                })

        conn.commit()
        conn.close()
        return entered_trades

    # -------------------------------------------------------------
    # 2. 每日持倉追蹤與體檢 (Position Monitoring)
    # -------------------------------------------------------------
    def update_daily_positions(
        self,
        market_quotes: Dict[str, Dict[str, Any]],
        benchmark_return_pct: float = 0.0,
        trade_date: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        更新在倉標的損益並判定出場條件。
        market_quotes 格式:
        {
            "2330": {"close": 980.0, "is_chip_net_sell": False},
            "2454": {"close": 1200.0, "is_chip_net_sell": True}
        }
        """
        if trade_date is None:
            trade_date = datetime.date.today().strftime("%Y-%m-%d")

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN'")
        open_positions = cursor.fetchall()

        updated_positions = []
        closed_trades = []

        for pos in open_positions:
            pos_id = pos["id"]
            stock_id = pos["stock_id"]
            stock_name = pos["stock_name"]
            entry_price = pos["entry_price"]
            highest_price = pos["highest_price"]
            stop_loss_pct = pos["stop_loss_pct"]
            take_profit_pct = pos["take_profit_pct"]
            trailing_stop_pct = pos["trailing_stop_pct"]
            trigger_factors = json.loads(pos["trigger_factors"])
            holding_days = pos["holding_days"] + 1
            chip_sell_days = pos["consecutive_chip_sell_days"]

            quote = market_quotes.get(stock_id)
            if not quote:
                continue

            current_price = float(quote.get("close", pos["current_price"]))
            is_chip_sell = bool(quote.get("is_chip_net_sell", False))

            # 籌碼連續大賣天數計數
            chip_sell_days = (chip_sell_days + 1) if is_chip_sell else 0

            # 更新最高價與未實現損益
            new_highest = max(highest_price, current_price)
            unrealized_pnl_pct = (current_price - entry_price) / entry_price
            mdd_pct = (new_highest - current_price) / new_highest if new_highest > 0 else 0.0

            # 出場信號判定
            exit_reason = None
            if unrealized_pnl_pct <= -stop_loss_pct:
                exit_reason = f"觸發停損 (跌幅 {unrealized_pnl_pct * 100:.2f}% <= -{stop_loss_pct * 100:.1f}%)"
            elif unrealized_pnl_pct >= take_profit_pct:
                exit_reason = f"達成停利目標 (漲幅 {unrealized_pnl_pct * 100:.2f}% >= +{take_profit_pct * 100:.1f}%)"
            elif new_highest >= entry_price * (1 + take_profit_pct * 0.7) and mdd_pct >= trailing_stop_pct:
                exit_reason = f"觸發移動停利保護 (自高點回撤 {mdd_pct * 100:.2f}% >= {trailing_stop_pct * 100:.1f}%)"
            elif chip_sell_days >= 3:
                exit_reason = "籌碼異常 (主力/外資法人連續3日大賣超)"

            if exit_reason:
                # 執行平倉與歸因分析
                attribution = self._attribute_trade(
                    pnl_pct=unrealized_pnl_pct,
                    benchmark_return_pct=benchmark_return_pct,
                    chip_sell_days=chip_sell_days,
                    exit_reason=exit_reason
                )

                # 寫入歷史表
                cursor.execute("""
                INSERT INTO trade_history (
                    position_id, stock_id, stock_name, entry_date, exit_date,
                    entry_price, exit_price, pnl_pct, holding_days, exit_reason,
                    trigger_factors, attribution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pos_id, stock_id, stock_name, pos["entry_date"], trade_date,
                    entry_price, current_price, unrealized_pnl_pct, holding_days,
                    exit_reason, json.dumps(trigger_factors, ensure_ascii=False),
                    attribution
                ))

                # 更新持倉狀態為 CLOSED
                cursor.execute("""
                UPDATE simulated_positions
                SET status = 'CLOSED', current_price = ?, highest_price = ?,
                    holding_days = ?, unrealized_pnl_pct = ?, max_drawdown_pct = ?,
                    consecutive_chip_sell_days = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, (current_price, new_highest, holding_days, unrealized_pnl_pct, mdd_pct, chip_sell_days, pos_id))

                closed_trades.append({
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "entry_date": pos["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "pnl_pct": unrealized_pnl_pct,
                    "holding_days": holding_days,
                    "exit_reason": exit_reason,
                    "attribution": attribution,
                    "factors": trigger_factors
                })
            else:
                # 維持在倉更新狀態
                cursor.execute("""
                UPDATE simulated_positions
                SET current_price = ?, highest_price = ?, holding_days = ?,
                    unrealized_pnl_pct = ?, max_drawdown_pct = ?,
                    consecutive_chip_sell_days = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, (current_price, new_highest, holding_days, unrealized_pnl_pct, mdd_pct, chip_sell_days, pos_id))

                updated_positions.append({
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "highest_price": new_highest,
                    "holding_days": holding_days,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "max_drawdown_pct": mdd_pct,
                    "chip_sell_days": chip_sell_days
                })

        conn.commit()
        conn.close()
        return updated_positions, closed_trades

    # -------------------------------------------------------------
    # 3. 覆盤報告與自我進化閉環 (Feedback & Self-Improvement Loop)
    # -------------------------------------------------------------
    def _attribute_trade(
        self,
        pnl_pct: float,
        benchmark_return_pct: float,
        chip_sell_days: int,
        exit_reason: str
    ) -> str:
        """失敗與成功案例歸因分析"""
        if pnl_pct > 0:
            return "技術突破與動能延續獲利"

        # 虧損分析
        if benchmark_return_pct < -0.015:
            return "系統性大盤下殺受阻"
        elif chip_sell_days >= 2:
            return "主力籌碼獲利了結出貨"
        elif "停損" in exit_reason:
            return "假突破引發之多頭力竭回撤"
        return "常態震盪洗盤出場"

    def evaluate_performance(self, lookback_trades: int = 50) -> Dict[str, Any]:
        """計算歷史勝率、賺賠比、累積報酬率"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT pnl_pct, holding_days, trigger_factors, attribution
        FROM trade_history
        ORDER BY id DESC LIMIT ?
        """, (lookback_trades,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "cumulative_return_pct": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0
            }

        wins = [r["pnl_pct"] for r in rows if r["pnl_pct"] > 0]
        losses = [r["pnl_pct"] for r in rows if r["pnl_pct"] <= 0]

        total_trades = len(rows)
        win_count = len(wins)
        win_rate = (win_count / total_trades) * 100.0

        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (abs(sum(losses) / len(losses))) if losses else 0.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 1.0)

        # 複利累計報酬率計算
        cum_ret = 1.0
        for r in reversed(rows):
            cum_ret *= (1.0 + r["pnl_pct"])
        cumulative_return_pct = (cum_ret - 1.0) * 100.0

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(pl_ratio, 2),
            "cumulative_return_pct": round(cumulative_return_pct, 2),
            "avg_win_pct": round(avg_win * 100, 2),
            "avg_loss_pct": round(avg_loss * 100, 2)
        }

    def self_evolving_loop(
        self,
        learning_rate: float = 0.03,
        min_trades: int = 5
    ) -> Dict[str, Any]:
        """
        動態調整機制：
        根據近期交易結果與因子表現，校準 model_weights.json 中的篩選因子權重。
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT pnl_pct, trigger_factors
        FROM trade_history
        ORDER BY id DESC LIMIT 30
        """)
        trades = cursor.fetchall()
        conn.close()

        if len(trades) < min_trades:
            return {"status": "SKIPPED", "reason": f"樣本數不足 ({len(trades)}/{min_trades})"}

        current_weights = self.load_weights()
        factor_scores: Dict[str, float] = {k: 0.0 for k in current_weights}

        for t in trades:
            pnl = t["pnl_pct"]
            factors = json.loads(t["trigger_factors"])
            # 因子貢獻度回饋：獲利交易增加觸發因子權重，虧損交易壓低權重
            for factor_key in current_weights.keys():
                if factor_key in factors:
                    factor_val = float(factors[factor_key])
                    factor_scores[factor_key] += (pnl * factor_val)

        # 梯度更新與權重平滑
        updated_weights = {}
        for k, current_w in current_weights.items():
            delta = factor_scores.get(k, 0.0) * learning_rate
            # 限制單次調整幅度
            delta = max(-0.05, min(0.05, delta))
            new_w = max(0.05, current_w + delta)  # 設定單一因子最低保底權重 5%
            updated_weights[k] = new_w

        # 重新歸一化 (Sum = 1.0)
        total_w = sum(updated_weights.values())
        final_weights = {k: round(v / total_w, 4) for k, v in updated_weights.items()}

        self.save_weights(final_weights)

        return {
            "status": "SUCCESS",
            "previous_weights": current_weights,
            "updated_weights": final_weights
        }

    # -------------------------------------------------------------
    # 4. 戰報推播文字生成 (Telegram / LINE)
    # -------------------------------------------------------------
    def generate_telegram_report(
        self,
        entered_trades: List[Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
        active_positions: List[Dict[str, Any]],
        perf_metrics: Optional[Dict[str, Any]] = None,
        weight_update: Optional[Dict[str, Any]] = None
    ) -> str:
        """產出格式化 Telegram / LINE 戰報訊息"""
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        lines = [
            f"📊 <b>【WayneBot 量化持倉與閉環戰報】</b>",
            f"📅 統計日期：<code>{today_str}</code>",
            "───────────────────"
        ]

        # 1. 今日模擬建倉
        if entered_trades:
            lines.append("🚀 <b>【今日觸發模擬建倉】</b>")
            for trade in entered_trades:
                lines.append(
                    f"• <b>{trade['stock_id']} {trade['stock_name']}</b> | 評分: <code>{trade['score']}</code>\n"
                    f"  進場價: <code>{trade['entry_price']:.2f}</code> | 停損: -7% | 停利: +15%"
                )
            lines.append("───────────────────")

        # 2. 今日平倉與停利停損
        if closed_trades:
            lines.append("🔔 <b>【今日觸發平倉出場】</b>")
            for trade in closed_trades:
                pnl_icon = "🟢" if trade["pnl_pct"] >= 0 else "🔴"
                lines.append(
                    f"{pnl_icon} <b>{trade['stock_id']} {trade['stock_name']}</b>\n"
                    f"  損益: <b>{trade['pnl_pct'] * 100:+.2f}%</b> (持有 {trade['holding_days']} 天)\n"
                    f"  原因: {trade['exit_reason']}\n"
                    f"  歸因: <i>{trade['attribution']}</i>"
                )
            lines.append("───────────────────")

        # 3. 目前在庫持倉體檢
        if active_positions:
            lines.append(f"📦 <b>【在倉部位體檢 (共 {len(active_positions)} 檔)】</b>")
            for pos in active_positions:
                pnl_str = f"{pos['unrealized_pnl_pct'] * 100:+.2f}%"
                icon = "🔺" if pos["unrealized_pnl_pct"] >= 0 else "🔻"
                lines.append(
                    f"{icon} <code>{pos['stock_id']} {pos['stock_name']}</code> | "
                    f"現價: <code>{pos['current_price']:.2f}</code> | "
                    f"未實現: <b>{pnl_str}</b> (MDD: <code>{pos['max_drawdown_pct'] * 100:.1f}%</code>)"
                )
            lines.append("───────────────────")

        # 4. 累計歷史總績效
        if perf_metrics:
            lines.append("📈 <b>【系統累計績效指標】</b>")
            lines.append(
                f"• 總平倉筆數: <code>{perf_metrics['total_trades']}</code> 筆\n"
                f"• 總勝率: <b>{perf_metrics['win_rate']}%</b>\n"
                f"• 賺賠比 (P/L Ratio): <b>{perf_metrics['profit_loss_ratio']}</b>\n"
                f"• 累計複利報酬: <b>{perf_metrics['cumulative_return_pct']:+}%</b>"
            )
            lines.append("───────────────────")

        # 5. AI 模型動態權重進化
        if weight_update and weight_update.get("status") == "SUCCESS":
            lines.append("🧠 <b>【AI 因子權重自我校準更新】</b>")
            for factor, w in weight_update["updated_weights"].items():
                prev_w = weight_update["previous_weights"].get(factor, w)
                diff = w - prev_w
                diff_str = f"({diff:+.3f})" if abs(diff) > 0.0001 else "(持平)"
                lines.append(f"• <code>{factor}</code>: <b>{w:.3f}</b> {diff_str}")

        return "\n".join(lines)
