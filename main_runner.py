# -*- coding: utf-8 -*-
"""
WayneBot 總控核心 (Phase 9)：All_In_One 總控排程與 AI 模擬操盤自我進化閉環
檔案名稱：main_runner.py
作者：Wayne (WayneBot Quantitative System Architect)

核心功能：
  1. 整合 Phase 5 數據採集 (data_fetcher.py)
  2. 執行 Phase 7 籌碼多因子海選評分 (screening_engine.py)
  3. AI 模擬部位管理：得分 >= 85 標的 + 槓鈴策略分配 (Core 40% / Satellite 35% / Momentum 25%)
  4. 每日持倉健康度檢查 (7% 停損 / 15% 移動停利 / 主力連續 3 日大賣 / 浮動損益結算)
  5. 交易失敗歸因分析 (假突破 / 大盤下殺 / 主力倒貨)
  6. Phase 9 AI 因子動態權重自我校準 (model_weights.json)
  7. 自動推播整合戰報至 Telegram (bot_servers.py)
"""

import os
import sys
import json
import sqlite3
import datetime
import logging
from typing import Dict, List, Optional, Any

# 設定環境路徑
BASE_DIR = "/content/waynebot_data" if "google.colab" in sys.modules else os.getenv("WAYNEBOT_DATA_DIR", "/tmp/waynebot_data" if os.path.exists("/tmp") else "waynebot_data")
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "wayne_trading.db")
WEIGHTS_FILE = os.path.join(BASE_DIR, "model_weights.json")

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WayneBot.MainRunner")

# 匯入各模組
try:
    import data_fetcher
except ImportError:
    data_fetcher = None

import screening_engine

try:
    from bot_servers import init_telegram_bot, send_telegram_safely
except ImportError:
    init_telegram_bot = None
    send_telegram_safely = None


class AISimulationEngine:
    """AI 模擬操盤、持倉監控與自我進化引擎 (Phase 9 完整閉環)"""
    
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
        
        self.init_schema()
        self.init_weights_file()

    def init_schema(self):
        """初始化模擬持倉與交易紀錄資料表"""
        with screening_engine.get_db_connection(self.db_path) as conn:
            conn.executescript("""
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

    def init_weights_file(self):
        """初始化 model_weights.json 預設權重"""
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
            self.init_weights_file()
        with open(self.weights_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_weights(self, weights: Dict[str, float]):
        """儲存模型權重"""
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=4, ensure_ascii=False)

    def auto_simulate_entry(
        self,
        candidates: List[Dict[str, Any]],
        total_capital: float = 100000.0,
        min_score: float = 85.0
    ) -> List[Dict[str, Any]]:
        """
        Phase 9 規範：
        1. 嚴格篩選得分 >= 85 分之標的。
        2. 依槓鈴策略 (Core 40% / Satellite 35% / Momentum 25%) 配置虛擬資金建倉。
        3. 自動計算 7% 停損、15% 停利與移動停利。
        """
        if not candidates:
            return []

        # 過濾出得分 >= 85 分的標的
        qualified = [c for c in candidates if float(c.get("score", c.get("total_score", 0))) >= min_score]
        if not qualified:
            logger.info("今日無得分 >= %s 之標的，跳過建倉。", min_score)
            return []

        allocations = [
            ("CORE (核心 40%)", 0.40),
            ("SATELLITE (衛星 35%)", 0.35),
            ("MOMENTUM (動能 25%)", 0.25)
        ]
        
        new_positions = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trade_date = datetime.datetime.now().strftime("%Y-%m-%d")

        with screening_engine.get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            
            # 取得現有在倉代碼，避免重複建倉
            cur.execute("SELECT stock_id FROM simulated_positions WHERE status = 'OPEN';")
            open_stock_ids = {row["stock_id"] for row in cur.fetchall()}

            for idx, item in enumerate(qualified[:3]):
                sid = str(item.get("stock_id", item.get("code", "")))
                if sid in open_stock_ids:
                    continue

                pos_type, capital_ratio = allocations[idx]
                sname = str(item.get("stock_name", item.get("name", sid)))
                c_p = float(item.get("close", item.get("close_price", 0.0)))
                if c_p <= 0.0:
                    continue

                pos_capital = total_capital * capital_ratio
                shares = max(1, int(pos_capital / c_p))
                pos_id = f"POS_{trade_date.replace('-', '')}_{sid}_{idx+1}"

                # 依 Phase 9 標準計算 7% 停損與 15% 停利
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
        """
        每日持倉健康度檢查 (Phase 9)：
        1. 計算未實現損益、持股天數與最大回撤 (MDD)。
        2. 判定出場：達停利點(+15%)、跌破停損線(-7%)、移動停利回撤、或主力連續3日大賣。
        3. 進行失敗/成功案例歸因分析並寫入 trade_history。
        """
        active_pos = []
        closed_trades = []
        total_unrealized = 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        with screening_engine.get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
            rows = cur.fetchall()

            for r in rows:
                sid = r["stock_id"]
                # 讀取最新收盤價與籌碼狀態
                cur.execute("SELECT close FROM daily_quotes WHERE stock_id = ? ORDER BY date DESC LIMIT 1;", (sid,))
                q = cur.fetchone()
                latest_p = float(q["close"]) if q else float(r["current_price"])

                entry_p = float(r["entry_price"])
                highest_p = max(float(r["highest_price_since_entry"]), latest_p)
                shares = int(r["shares"])
                holding_days = int(r["holding_days"]) + 1
                chip_sell_days = int(r.get("consecutive_chip_sell_days", 0) if "consecutive_chip_sell_days" in r.keys() else 0)

                unrealized_pnl = (latest_p - entry_p) * shares
                unrealized_pct = ((latest_p - entry_p) / entry_p) * 100.0
                total_unrealized += unrealized_pnl

                # 計算自進場以來之最大回撤 (MDD)
                mdd_pct = ((highest_p - latest_p) / highest_p * 100.0) if highest_p > 0 else 0.0

                # 出場條件判定
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
                    # 執行平倉與失敗/成功案例歸因分析
                    attribution = self._attribute_trade(
                        pnl_pct=unrealized_pct / 100.0,
                        benchmark_return_pct=benchmark_return_pct,
                        chip_sell_days=chip_sell_days,
                        exit_reason=exit_reason
                    )

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

        return {
            "active": active_pos,
            "closed": closed_trades,
            "total_unrealized": round(total_unrealized, 2)
        }

    def _attribute_trade(self, pnl_pct: float, benchmark_return_pct: float, chip_sell_days: int, exit_reason: str) -> str:
        """歸因分析"""
        if pnl_pct > 0:
            return "技術突破與多頭動能延續獲利"
        if benchmark_return_pct < -0.015:
            return "系統性大盤下殺受阻"
        if chip_sell_days >= 2:
            return "主力籌碼獲利了結出貨"
        if "停損" in exit_reason:
            return "假突破多頭力竭回撤"
        return "常態震盪洗盤出場"

    def evaluate_performance(self, lookback_trades: int = 50) -> Dict[str, Any]:
        """計算歷史勝率、賺賠比、累計報酬率"""
        with screening_engine.get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT pnl_percentage FROM trade_history
                ORDER BY created_at DESC LIMIT ?;
            """, (lookback_trades,))
            rows = cur.fetchall()

        if not rows:
            return {"total_trades": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0, "cumulative_return_pct": 0.0}

        pnls = [float(r["pnl_percentage"]) / 100.0 for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_trades = len(pnls)
        win_rate = (len(wins) / total_trades) * 100.0 if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 1.0)

        cum_ret = 1.0
        for p in reversed(pnls):
            cum_ret *= (1.0 + p)
        cumulative_return_pct = (cum_ret - 1.0) * 100.0

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(pl_ratio, 2),
            "cumulative_return_pct": round(cumulative_return_pct, 2)
        }

    def self_evolving_loop(self, learning_rate: float = 0.03, min_trades: int = 5) -> Dict[str, Any]:
        """自我進化閉環：根據歷史勝負回饋動態微調 model_weights.json"""
        with screening_engine.get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT pnl_percentage, trigger_factors FROM trade_history
                ORDER BY created_at DESC LIMIT 30;
            """)
            trades = cur.fetchall()

        if len(trades) < min_trades:
            return {"status": "SKIPPED", "reason": f"樣本數不足 ({len(trades)}/{min_trades})"}

        current_weights = self.load_weights()
        factor_scores = {k: 0.0 for k in current_weights}

        for t in trades:
            pnl = float(t["pnl_percentage"]) / 100.0
            try:
                factors = json.loads(t["trigger_factors"])
            except Exception:
                factors = {}

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

        return {
            "status": "SUCCESS",
            "previous_weights": current_weights,
            "updated_weights": final_weights
        }


def run_daily_pipeline():
    """每日盤後全自動總控流水線 (Phase 1 ~ Phase 9 完整整合)"""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    logger.info("=== 啟動 WayneBot 每日盤後自動化量化總控流程: %s ===", today_str)

    # 1. 初始化 Phase 9 模擬操盤與自我進化引擎
    sim_engine = AISimulationEngine()
    current_weights = sim_engine.load_weights()
    logger.info("當前 AI 因子權重: %s", current_weights)

    # 2. 執行 Phase 7 多因子海選評分
    logger.info(">>> [階段 1] 執行全市場籌碼多因子海選評分...")
    df_top = screening_engine.run_full_screening(top_n=15, save_cache=True)
    top_list = df_top.to_dict(orient="records") if len(df_top) > 0 else []
    logger.info("海選完成，共計選出 %d 檔優質標的", len(top_list))

    # 3. 執行持倉健康檢查與平倉判定
    logger.info(">>> [階段 2] 執行持倉健康檢查與出場判定 (停損7%/停利15%/籌碼異常)...")
    checkup_result = sim_engine.daily_portfolio_checkup()
    
    # 4. 模擬自動建倉 (得分 >= 85 且依槓鈴策略配置)
    logger.info(">>> [階段 3] 執行高分標的 (Score >= 85) 自動模擬建倉...")
    new_entries = sim_engine.auto_simulate_entry(top_list, total_capital=100000.0, min_score=85.0)
    logger.info("持倉更新完成: 今日開倉 %d 檔，平倉 %d 檔，在庫總未實現損益: $%s", len(new_entries), len(checkup_result["closed"]), checkup_result["total_unrealized"])

    # 5. 績效統計與 AI 權重自我校準
    logger.info(">>> [階段 4] 執行歷史績效評估與 AI 權重自我校準閉環...")
    perf_metrics = sim_engine.evaluate_performance()
    weight_update = sim_engine.self_evolving_loop()

    # 6. 生成整合戰報
    logger.info(">>> [階段 5] 生成 Telegram 盤後視覺化戰報...")
    report_text = screening_engine.format_telegram_report(stock_list=top_list, trade_date=today_str)
    
    # 附加 Phase 9: 持倉與平倉通知
    if new_entries:
        report_text += "\n\n🚀 <b>【AI 模擬今日建倉 (Score ≥ 85)】</b>\n"
        for t in new_entries:
            report_text += f"• <b>{t['stock_id']} {t['stock_name']}</b> ({t['type']})\n  進場: <code>{t['entry_price']}</code> | 停損: <code>{t['stop_loss']}</code> | 停利: <code>{t['take_profit']}</code>\n"

    if checkup_result["closed"]:
        report_text += "\n\n🔔 <b>【AI 模擬今日平倉出場】</b>\n"
        for c in checkup_result["closed"]:
            pnl_icon = "🟢" if "+" in c["pnl_pct"] else "🔴"
            report_text += f"{pnl_icon} <b>{c['stock_id']} {c['stock_name']}</b> | 損益: <b>{c['pnl_pct']}</b> (${c['pnl_amount']})\n  原因: {c['reason']}\n  歸因: <i>{c['attribution']}</i>\n"

    if checkup_result["active"]:
        report_text += "\n\n💼 <b>【AI 模擬持倉即時監控】</b>\n"
        for pos in checkup_result["active"]:
            report_text += f"• <code>{pos['stock_id']} {pos['stock_name']}</code> | 損益: <b>{pos['pnl_pct']}</b> (${pos['pnl_amount']}) | MDD: <code>{pos['mdd_pct']}</code>\n"

    # 附加 Phase 9: 績效與權重進化摘要
    if perf_metrics["total_trades"] > 0:
        report_text += f"\n\n📈 <b>【系統累計績效】</b> 總交易: {perf_metrics['total_trades']} 筆 | 勝率: <b>{perf_metrics['win_rate']}%</b> | 賺賠比: <b>{perf_metrics['profit_loss_ratio']}</b> | 累積報酬: <b>{perf_metrics['cumulative_return_pct']:+}%</b>\n"

    if weight_update.get("status") == "SUCCESS":
        report_text += "\n🧠 <b>【AI 因子動態權重自我校準】</b>\n"
        for k, v in weight_update["updated_weights"].items():
            prev = weight_update["previous_weights"].get(k, v)
            diff = v - prev
            diff_str = f"({diff:+.3f})" if abs(diff) > 0.0001 else "(持平)"
            report_text += f"• <code>{k}</code>: <b>{v:.3f}</b> {diff_str}\n"

    # 7. 發送 Telegram 推播
    tg_token = os.getenv("TG_BOT_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    if tg_token and tg_chat_id and init_telegram_bot and send_telegram_safely:
        bot = init_telegram_bot(token=tg_token)
        send_telegram_safely(bot=bot, chat_id=tg_chat_id, full_text=report_text, parse_mode="HTML")
        logger.info("✅ 盤後總控戰報推播成功！")
    else:
        print("\n" + report_text)


if __name__ == "__main__":
    run_daily_pipeline()
