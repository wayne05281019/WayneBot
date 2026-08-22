# -*- coding: utf-8 -*-
"""
WayneBot 總控核心 (Phase 8)：All_In_One 總控排程與 AI 模擬操盤自我進化閉環
檔案名稱：main_runner.py
作者：Wayne (WayneBot Quantitative System Architect)

核心功能：
  1. 整合 Phase 5 數據採集 (data_fetcher.py)
  2. 執行 Phase 7 籌碼多因子海選評分 (screening_engine.py)
  3. AI 模擬部位管理：槓鈴策略分配 (Core 40% / Satellite 35% / Momentum 25%)
  4. 每日持倉健康度檢查 (防甩轎停損 / 波段達標停利 / 浮動損益結算)
  5. 自動推播整合戰報至 Telegram (bot_servers.py)
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
    """AI 模擬操盤與自我進化引擎"""
    def __init__(self, db_path: str = DB_PATH, weights_path: str = WEIGHTS_FILE):
        self.db_path = db_path
        self.weights_path = weights_path
        self.init_schema()

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

    def auto_simulate_entry(self, candidates: List[Dict[str, Any]], total_capital: float = 100000.0) -> List[Dict[str, Any]]:
        """自動根據海選 Top 3 標的，依槓鈴策略配置虛擬資金建倉"""
        if not candidates:
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
            for idx, item in enumerate(candidates[:3]):
                pos_type, capital_ratio = allocations[idx]
                sid = str(item.get("stock_id", item.get("code", "")))
                sname = str(item.get("stock_name", item.get("name", sid)))
                c_p = float(item.get("close", 0.0))
                if c_p <= 0.0:
                    continue

                pos_capital = total_capital * capital_ratio
                shares = max(1, int(pos_capital / c_p))
                pos_id = f"POS_{trade_date.replace('-','')}_{sid}_{idx+1}"

                stop_loss = float(item.get("stop_loss", round(c_p * 0.955, 2)))
                take_profit = float(item.get("take_profit", round(c_p * 1.15, 2)))

                cur.execute("""
                    INSERT OR REPLACE INTO simulated_positions (
                        position_id, stock_id, stock_name, entry_date, entry_price,
                        current_price, shares, position_type, stop_loss_price,
                        take_profit_price, trailing_stop_price, highest_price_since_entry,
                        holding_days, trigger_factors, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    pos_id, sid, sname, trade_date, c_p, c_p, shares, pos_type,
                    stop_loss, take_profit, stop_loss, c_p, 1,
                    json.dumps(item, ensure_ascii=False), "OPEN", now_str, now_str
                ))

                new_positions.append({
                    "pos_id": pos_id, "stock_id": sid, "stock_name": sname,
                    "type": pos_type, "entry_price": c_p, "shares": shares,
                    "stop_loss": stop_loss, "take_profit": take_profit
                })
        return new_positions

    def daily_portfolio_checkup(self) -> Dict[str, Any]:
        """每日持倉健康檢查：檢查是否觸發停損、停利，並計算未實現損益"""
        active_pos = []
        closed_trades = []
        total_unrealized = 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with screening_engine.get_db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
            rows = cur.fetchall()

            for r in rows:
                sid = r["stock_id"]
                # 讀取最新收盤價
                cur.execute("SELECT close FROM daily_quotes WHERE stock_id = ? ORDER BY date DESC LIMIT 1;", (sid,))
                q = cur.fetchone()
                latest_p = float(q["close"]) if q else float(r["current_price"])

                entry_p = float(r["entry_price"])
                shares = int(r["shares"])
                unrealized_pnl = (latest_p - entry_p) * shares
                unrealized_pct = ((latest_p - entry_p) / entry_p) * 100.0
                total_unrealized += unrealized_pnl

                exit_reason = None
                if latest_p <= float(r["stop_loss_price"]):
                    exit_reason = "STOP_LOSS (防甩轎頸線停損觸發)"
                elif latest_p >= float(r["take_profit_price"]):
                    exit_reason = "TAKE_PROFIT (波段達標停利獲利了結)"

                if exit_reason:
                    trade_id = f"TRD_{r['position_id']}"
                    cur.execute("""
                        INSERT INTO trade_history (
                            trade_id, position_id, stock_id, stock_name, entry_date,
                            exit_date, entry_price, exit_price, shares, pnl_amount,
                            pnl_percentage, holding_days, exit_reason, trigger_factors, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        trade_id, r["position_id"], sid, r["stock_name"], r["entry_date"],
                        datetime.datetime.now().strftime("%Y-%m-%d"), entry_p, latest_p,
                        shares, unrealized_pnl, unrealized_pct, r["holding_days"] + 1,
                        exit_reason, r["trigger_factors"], now_str
                    ))
                    cur.execute("UPDATE simulated_positions SET status = 'CLOSED', updated_at = ? WHERE position_id = ?;", (now_str, r["position_id"]))
                    closed_trades.append({"stock_id": sid, "stock_name": r["stock_name"], "pnl": unrealized_pnl, "reason": exit_reason})
                else:
                    cur.execute("""
                        UPDATE simulated_positions SET current_price = ?, holding_days = holding_days + 1, updated_at = ?
                        WHERE position_id = ?;
                    """, (latest_p, now_str, r["position_id"]))
                    active_pos.append({
                        "stock_id": sid, "stock_name": r["stock_name"], "type": r["position_type"],
                        "entry": entry_p, "current": latest_p, "shares": shares,
                        "pnl_pct": f"{unrealized_pct:+.2f}%", "pnl_amount": round(unrealized_pnl, 2)
                    })

        return {"active": active_pos, "closed": closed_trades, "total_unrealized": round(total_unrealized, 2)}


def run_daily_pipeline():
    """每日盤後全自動總控流水線"""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    logger.info("=== 啟動 WayneBot 每日盤後自動化量化總控流程: %s ===", today_str)

    # 1. 執行 Phase 7 多因子海選評分
    logger.info(">>> [階段 1] 執行全市場籌碼多因子海選評分...")
    df_top = screening_engine.run_full_screening(top_n=15, save_cache=True)
    top_list = df_top.to_dict(orient="records") if len(df_top) > 0 else []
    logger.info("海選完成，共計選出 %d 檔優質標的", len(top_list))

    # 2. AI 模擬部位操盤與檢查
    logger.info(">>> [階段 2] 執行 AI 模擬持倉檢查與槓鈴策略建倉...")
    sim_engine = AISimulationEngine()
    checkup_result = sim_engine.daily_portfolio_checkup()
    new_entries = sim_engine.auto_simulate_entry(top_list[:3])
    logger.info("持倉檢查完成: 開倉 %d 檔，平倉 %d 檔，總未實現損益: $%s", len(new_entries), len(checkup_result["closed"]), checkup_result["total_unrealized"])

    # 3. 生成與發送 Telegram 戰報
    logger.info(">>> [階段 3] 生成 Telegram 盤後視覺化戰報...")
    report_text = screening_engine.format_telegram_report(stock_list=top_list, trade_date=today_str)
    
    # 附加持倉摘要
    if checkup_result["active"]:
        report_text += "\n\n💼 <b>【AI 模擬持倉即時監控】</b>\n"
        for pos in checkup_result["active"]:
            report_text += f"• <code>{pos['stock_id']} {pos['stock_name']}</code> | 損益: <b>{pos['pnl_pct']}</b> (${pos['pnl_amount']})\n"

    # 發送 Telegram 推播
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
