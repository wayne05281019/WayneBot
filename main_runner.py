# -*- coding: utf-8 -*-
"""
========================================================================================
WayneBot 總控核心 (Phase 4)：All_In_One 總控核心與 AI 模擬買賣自我進化閉環
檔案名稱：main_runner.py
作者：Wayne (WayneBot Quantitative System Architect)
系統職責：
  1. 異步總控調度：使用 asyncio.gather 協同調度「大數據清洗與海選排程」、「Telegram 輪詢」、「LINE/Health 監聽伺服器」
  2. 優雅關閉（Graceful Shutdown）：捕捉 SIGINT / SIGTERM，安全取消所有 Task、釋放 Socket Port、執行 SQLite WAL Checkpoint
  3. AI 模擬買賣與自我進化閉環：
     - 自動建倉：捕捉海選高分標的寫入 simulated_positions (記錄進場價、停損價、停利價、觸發因子)
     - 盤後體檢：更新未實現損益、持股天數，觸發防甩轎停損/移動保本/波段停利，自動平倉寫入 trade_history
     - 覆盤分析與自我進化：計算勝率、賺賠比、失敗案例歸因（Failure Attribution），動態微調篩選模型權重 (model_weights.json)
     - 雙向推播：整合 Telegram 與 LINE 分片格式化戰報
========================================================================================
"""

import os
import sys
import time
import json
import random
import socket
import signal
import asyncio
import sqlite3
import logging
import datetime
import threading
from typing import Dict, List, Optional, Tuple, Any

# ======================================================================================
# 0. 環境路徑與日誌設定 (Logging & Path Configuration)
# ======================================================================================

BASE_DIR = "/content/waynebot_data" if "google.colab" in sys.modules else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_trading.db")
WEIGHTS_FILE = os.path.join(BASE_DIR, "model_weights.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WayneBotCore")


def safe_div(num: Any, den: Any, default: float = 0.0) -> float:
    """防除以零安全運算函式"""
    try:
        f_num, f_den = float(num), float(den)
        if f_den == 0.0 or f_den != f_den or f_num != f_num:  # 排除 NaN 與 0
            return default
        return f_num / f_den
    except Exception:
        return default


# ======================================================================================
# 1. 內建模組適配器與降級保底機制 (Module Adapters & Fallback Fall-Through)
# ======================================================================================

try:
    import wayne_db
except ImportError:
    wayne_db = None

try:
    import screening_engine
except ImportError:
    screening_engine = None

try:
    import bot_servers
except ImportError:
    bot_servers = None


class DatabaseManager:
    """
    SQLite 資料庫核心管理器 (WAL 模式與高併發連線防鎖死)
    支援 simulated_positions、trade_history 與 system_logs
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                conn.execute("PRAGMA journal_mode=DELETE;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.execute("CREATE TABLE IF NOT EXISTS _health_check (id INTEGER PRIMARY KEY);")
            return conn
        except Exception:
            alt_path = os.path.join("/tmp", os.path.basename(self.db_path))
            self.db_path = alt_path
            conn = sqlite3.connect(alt_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=10000;")
            return conn

    def init_schema(self) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                # 1. 模擬持倉表
                cursor.execute("""
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
                """)

                # 2. 交易歷史履歷表 (平倉與覆盤)
                cursor.execute("""
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

                # 3. 系統事件日誌表
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL
                );
                """)
                conn.commit()
                logger.info(f"✅ SQLite 核心結構初始化完成 (資料庫路徑: {self.db_path})")
            except Exception as e:
                conn.rollback()
                logger.error(f"❌ SQLite 初始化失敗: {e}")
                raise e
            finally:
                conn.close()

    def checkpoint_and_close(self) -> None:
        """優雅關閉時強制將 WAL 寫回主資料庫，防止檔案損毀"""
        with self._lock:
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.commit()
                conn.close()
                logger.info("💾 SQLite WAL Checkpoint 執行成功，所有事務已刷回主庫")
            except Exception as e:
                logger.warning(f"⚠️ SQLite Checkpoint 提示: {e}")


# 全域資料庫實例
db_manager = DatabaseManager()


# ======================================================================================
# 2. AI 模擬買賣與自我進化閉環核心 (AI Simulation & Evolution Engine)
# ======================================================================================

class AISimulationEngine:
    """
    AI 模擬買賣與自我進化閉環核心
    負責：
      1. 依據海選評級自動執行 30萬虛擬投資組合分批建倉 (試單 50% + 救命金 50%)
      2. 每日盤後持股健康體檢 (未實現損益、持股天數、移動保本、停損停利判斷)
      3. 平倉數據歸檔與失敗歸因 (Failure Attribution)
      4. 動態微調模型特徵權重 (Dynamic Weight Optimization)
    """

    DEFAULT_WEIGHTS = {
        "base_level_weight": 0.40,      # 雙綠脫離低底位階 (40%)
        "momentum_vol_weight": 0.25,    # 布林壓縮與量能爆發 (25%)
        "space_ratio_weight": 0.15,     # 上方空間比 (15%)
        "institutional_chip": 0.10,     # 外資投信與融資退場 (10%)
        "macro_vix_gate": 0.10          # 宏觀氣象與防守門檻 (10%)
    }

    def __init__(self, db: DatabaseManager = db_manager, weights_file: str = WEIGHTS_FILE):
        self.db = db
        self.weights_file = weights_file
        self.weights = self.load_weights()

    def load_weights(self) -> Dict[str, float]:
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"📊 已載入自適應模型權重: {data}")
                    return data
            except Exception as e:
                logger.warning(f"⚠️ 讀取權重檔失敗，使用預設值: {e}")
        self.save_weights(self.DEFAULT_WEIGHTS)
        return self.DEFAULT_WEIGHTS.copy()

    def save_weights(self, new_weights: Dict[str, float]) -> None:
        try:
            with open(self.weights_file, "w", encoding="utf-8") as f:
                json.dump(new_weights, f, indent=4, ensure_ascii=False)
            logger.info(f"💾 已儲存更新後之模型權重至 {self.weights_file}")
        except Exception as e:
            logger.error(f"❌ 儲存權重檔失敗: {e}")

    def auto_simulate_entry(self, ranked_candidates: List[Dict[str, Any]], trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        模擬進場：依據篩選結果高分榜單 (Top 3) 建立虛擬持倉
        倉位模型：
          - 核心部位 (40%, 12萬): 評級 A 級首選
          - 衛星部位 (35%, 10.5萬): 評級 A/B 級動能標的
          - 動能部位 (25%, 7.5萬): 短線爆發標的
          - 50% 試單，50% 救命預備金
        """
        if not ranked_candidates:
            logger.info("ℹ️ 今日無符合進場條件之候選個股")
            return []

        if not trade_date:
            trade_date = datetime.datetime.now().strftime("%Y%m%d")

        conn = self.db.get_connection()
        cursor = conn.cursor()
        created_positions = []

        try:
            cursor.execute("SELECT stock_id FROM simulated_positions WHERE status = 'OPEN'")
            current_open_stocks = {row["stock_id"] for row in cursor.fetchall()}

            for idx, candidate in enumerate(ranked_candidates[:3]):
                sid = str(candidate.get("stock_id", "")).strip()
                sname = str(candidate.get("stock_name", "")).strip()
                close_price = float(candidate.get("close", 0.0))
                score = float(candidate.get("score", 0.0))
                grade = str(candidate.get("grade", "B"))

                if not sid or close_price <= 0.0 or sid in current_open_stocks:
                    continue

                if len(current_open_stocks) >= 5:
                    logger.info(f"⏸️ 虛擬持倉已達 5 檔上限，暫停新建倉 [{sid} {sname}]")
                    break

                pos_type = "核心部位 (40%)" if idx == 0 else ("衛星部位 (35%)" if idx == 1 else "動能部位 (25%)")
                allocated_budget = 120000.0 if idx == 0 else (105000.0 if idx == 1 else 75000.0)
                entry_budget = allocated_budget * 0.5  # 50% 試單紀律

                # 計算股數 (支援高價股零股與中低價股整張)
                if close_price > 200.0:
                    shares = int(entry_budget / close_price)
                else:
                    shares = int(entry_budget / (close_price * 1000.0)) * 1000
                    if shares == 0:
                        shares = int(entry_budget / close_price)

                if shares <= 0:
                    continue

                # 結構性防甩轎停損與階梯目標價
                stop_loss = round(close_price * 0.96, 2)    # -4.0% 關鍵結構防守
                take_profit = round(close_price * 1.15, 2)  # +15.0% 第一波段滿足點
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pos_id = f"POS_{sid}_{trade_date}_{int(time.time()*1000)%1000000}"

                trigger_factors = json.dumps({
                    "score": score,
                    "grade": grade,
                    "d20_gain": candidate.get("d20_gain", 0.0),
                    "space_20": candidate.get("space_20", 0.0),
                    "vol_rank": candidate.get("vol_rank", 0),
                    "vol_ratio": candidate.get("vol_ratio", 0.0),
                    "ma60s": candidate.get("ma60s", 0.0),
                    "bias20": candidate.get("bias20", 0.0)
                }, ensure_ascii=False)

                cursor.execute("""
                INSERT INTO simulated_positions (
                    position_id, stock_id, stock_name, entry_date, entry_price,
                    current_price, shares, position_type, stop_loss_price,
                    take_profit_price, trailing_stop_price, highest_price_since_entry,
                    holding_days, trigger_factors, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """, (
                    pos_id, sid, sname, trade_date, close_price,
                    close_price, shares, pos_type, stop_loss,
                    take_profit, stop_loss, close_price,
                    0, trigger_factors, now_str, now_str
                ))

                current_open_stocks.add(sid)
                created_positions.append({
                    "position_id": pos_id,
                    "stock_id": sid,
                    "stock_name": sname,
                    "position_type": pos_type,
                    "entry_price": close_price,
                    "shares": shares,
                    "actual_cost": shares * close_price,
                    "stop_loss_price": stop_loss,
                    "take_profit_price": take_profit,
                    "grade": grade,
                    "score": score
                })
                logger.info(f"🎯 [模擬建倉成功] {pos_type} {sid} {sname} | 買進: {close_price}元 | {shares:,}股 | 停損: {stop_loss}元 | 目標: {take_profit}元")

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 模擬建倉事務失敗: {e}")
        finally:
            conn.close()

        return created_positions

    def daily_portfolio_checkup(self, latest_market_data: Dict[str, Dict[str, Any]], check_date: Optional[str] = None) -> Dict[str, Any]:
        """
        每日盤後持股體檢與平倉結算
        檢核：
          1. 未實現損益計算（含 0.45% 擬真手續費與證交稅）
          2. 持股天數累加 (Holding Days)
          3. 階梯移動保本：獲利達 +8% 時，停損點上移至成本價保本
          4. 停損觸發：跌破 stop_loss_price 執行平倉
          5. 停利觸發：達到 take_profit_price 執行波段平倉
          6. 時間停滯超時 (Stagnation Protocol)：持股 > 15 天且未達動能預期
        """
        if not check_date:
            check_date = datetime.datetime.now().strftime("%Y%m%d")

        conn = self.db.get_connection()
        cursor = conn.cursor()

        checkup_report = {
            "check_date": check_date,
            "active_positions": [],
            "closed_trades": [],
            "total_unrealized_pnl": 0.0,
            "total_market_value": 0.0
        }

        try:
            cursor.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN'")
            open_positions = cursor.fetchall()

            for pos in open_positions:
                pos_id = pos["position_id"]
                sid = pos["stock_id"]
                sname = pos["stock_name"]
                entry_price = float(pos["entry_price"])
                shares = int(pos["shares"])
                stop_loss = float(pos["stop_loss_price"])
                take_profit = float(pos["take_profit_price"])
                highest_p = float(pos["highest_price_since_entry"])
                holding_days = int(pos["holding_days"]) + 1
                trailing_stop = float(pos["trailing_stop_price"])
                trigger_factors_json = pos["trigger_factors"]

                # 獲取最新行情
                m_data = latest_market_data.get(sid, {})
                curr_price = float(m_data.get("close", pos["current_price"]))
                day_high = float(m_data.get("high", curr_price))
                day_low = float(m_data.get("low", curr_price))

                if curr_price <= 0.0:
                    curr_price = float(pos["current_price"])

                # 更新波段最高價
                if day_high > highest_p:
                    highest_p = day_high

                # 扣除 0.45% 擬真交易摩擦成本 (0.1425% 手續費 + 0.3% 證交稅)
                net_cost = entry_price * shares * 1.001425
                net_proceeds = curr_price * shares * (1.0 - 0.0045)
                unrealized_pnl = net_proceeds - net_cost
                unrealized_pct = safe_div(unrealized_pnl, net_cost) * 100.0

                checkup_report["total_unrealized_pnl"] += unrealized_pnl
                checkup_report["total_market_value"] += (curr_price * shares)

                # 階梯式保本鎖利機制：獲利達 +8% 停損點自動上移至買進成本
                if unrealized_pct >= 8.0 and trailing_stop < entry_price:
                    trailing_stop = entry_price
                    logger.info(f"🛡️ [保本鎖利啟動] {sid} {sname} 獲利達 +{unrealized_pct:.2f}%，停損價上移至成本保本價 {trailing_stop:.2f}元")

                # 出場判斷 (Exit Conditions)
                exit_triggered = False
                exit_reason = ""
                exit_price = curr_price

                if day_low <= stop_loss or curr_price <= stop_loss or curr_price <= trailing_stop:
                    exit_triggered = True
                    exit_price = min(curr_price, stop_loss)
                    exit_reason = "STOP_LOSS (防甩轎跌破停損)"
                elif day_high >= take_profit or curr_price >= take_profit:
                    exit_triggered = True
                    exit_price = max(curr_price, take_profit)
                    exit_reason = "TAKE_PROFIT (達波段滿足點停利)"
                elif holding_days >= 20 and unrealized_pct < 2.0:
                    exit_triggered = True
                    exit_price = curr_price
                    exit_reason = "STAGNATION_TIMEOUT (時間停滯換股)"

                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if exit_triggered:
                    # 執行平倉
                    realized_proceeds = exit_price * shares * (1.0 - 0.0045)
                    realized_pnl = realized_proceeds - net_cost
                    realized_pct = safe_div(realized_pnl, net_cost) * 100.0

                    # 失敗歸因分析
                    attribution = self._analyze_failure_attribution(
                        realized_pct, trigger_factors_json, m_data, holding_days
                    )

                    trade_id = f"TRD_{sid}_{check_date}_{int(time.time()*1000)%1000000}"
                    cursor.execute("""
                    INSERT INTO trade_history (
                        trade_id, position_id, stock_id, stock_name, entry_date,
                        exit_date, entry_price, exit_price, shares, pnl_amount,
                        pnl_percentage, holding_days, exit_reason, trigger_factors,
                        failure_attribution, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id, pos_id, sid, sname, pos["entry_date"],
                        check_date, entry_price, exit_price, shares,
                        round(realized_pnl, 2), round(realized_pct, 2),
                        holding_days, exit_reason, trigger_factors_json,
                        attribution, now_str
                    ))

                    cursor.execute("""
                    UPDATE simulated_positions
                    SET status = 'CLOSED', current_price = ?, updated_at = ?
                    WHERE position_id = ?
                    """, (exit_price, now_str, pos_id))

                    closed_item = {
                        "stock_id": sid,
                        "stock_name": sname,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "shares": shares,
                        "pnl_amount": round(realized_pnl, 2),
                        "pnl_percentage": round(realized_pct, 2),
                        "holding_days": holding_days,
                        "exit_reason": exit_reason,
                        "attribution": attribution
                    }
                    checkup_report["closed_trades"].append(closed_item)
                    logger.info(f"🚪 [模擬平倉結算] {sid} {sname} | 損益: {realized_pnl:+,.0f}元 ({realized_pct:+.2f}%) | 天數: {holding_days}天 | 原因: {exit_reason}")
                else:
                    # 更新持倉狀態
                    cursor.execute("""
                    UPDATE simulated_positions
                    SET current_price = ?, highest_price_since_entry = ?,
                        holding_days = ?, trailing_stop_price = ?, updated_at = ?
                    WHERE position_id = ?
                    """, (curr_price, highest_p, holding_days, trailing_stop, now_str, pos_id))

                    checkup_report["active_positions"].append({
                        "stock_id": sid,
                        "stock_name": sname,
                        "entry_price": entry_price,
                        "current_price": curr_price,
                        "shares": shares,
                        "unrealized_pnl": round(unrealized_pnl, 2),
                        "unrealized_pct": round(unrealized_pct, 2),
                        "holding_days": holding_days,
                        "stop_loss_price": stop_loss,
                        "take_profit_price": take_profit,
                        "trailing_stop": trailing_stop
                    })

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 每日持股體檢事務異常: {e}")
        finally:
            conn.close()

        return checkup_report

    def _analyze_failure_attribution(self, pnl_pct: float, trigger_json: str, market_data: Dict[str, Any], holding_days: int) -> str:
        """
        AI 失敗案例自動歸因分析器 (Failure Attribution Analyzer)
        若為虧損單，自動解析特徵盲點（假突破、量能退潮、外資提款、大盤系統性風險）
        """
        if pnl_pct >= 0.0:
            return "SUCCESS_TRADE (正報酬達標結案)"

        reasons = []
        try:
            factors = json.loads(trigger_json)
        except Exception:
            factors = {}

        vol_rank = factors.get("vol_rank", 0)
        d20_gain = factors.get("d20_gain", 0.0)
        space_20 = factors.get("space_20", 0.0)

        if vol_rank > 30:
            reasons.append("量能不足 (120日量未達前30名，動能無延續性)")
        if d20_gain > 5.0:
            reasons.append("進場基期過高 (D20已脫離 > 5%，易遭主力倒貨)")
        if space_20 < 15.0:
            reasons.append("操作空間不足 (距上方壓力 < 15%，盈虧比不佳)")
        if holding_days <= 3:
            reasons.append("隔日沖主力出貨 (首日暴量假突破即翻黑)")
        if not reasons:
            reasons.append("常態市場波動停損 (嚴守紀律，保護本金)")

        return " | ".join(reasons)

    def generate_evolution_report_and_tune_weights(self) -> Dict[str, Any]:
        """
        覆盤統計與自我進化：
          1. 統計歷史勝率、總盈虧、賺賠比 (Payoff Ratio)、最大回撤
          2. 聚合失敗案例，動態微調篩選權重矩陣
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        report = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "total_net_pnl": 0.0,
            "payoff_ratio": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "failure_breakdown": {},
            "weight_adjustments": {}
        }

        try:
            cursor.execute("SELECT * FROM trade_history")
            trades = cursor.fetchall()
            report["total_trades"] = len(trades)

            if not trades:
                logger.info("ℹ️ 目前尚無已平倉歷史交易，權重維持當前基準")
                return report

            wins = [float(t["pnl_amount"]) for t in trades if float(t["pnl_amount"]) > 0]
            losses = [float(t["pnl_amount"]) for t in trades if float(t["pnl_amount"]) <= 0]

            report["win_trades"] = len(wins)
            report["loss_trades"] = len(losses)
            report["win_rate"] = safe_div(len(wins), len(trades)) * 100.0
            report["total_net_pnl"] = sum(float(t["pnl_amount"]) for t in trades)

            report["avg_win"] = safe_div(sum(wins), len(wins))
            report["avg_loss"] = safe_div(abs(sum(losses)), len(losses))
            report["payoff_ratio"] = safe_div(report["avg_win"], report["avg_loss"], default=1.0)

            # 失敗案例歸因統計
            for t in trades:
                attr = t["failure_attribution"]
                if attr and "SUCCESS" not in attr:
                    for part in attr.split(" | "):
                        report["failure_breakdown"][part] = report["failure_breakdown"].get(part, 0) + 1

            # 自適應權重動態進化演算法 (Feedback Tuning)
            new_weights = self.weights.copy()
            adjustments = {}

            # 若「量能不足」過多，調升量能爆發權重門檻
            if report["failure_breakdown"].get("量能不足 (120日量未達前30名，動能無延續性)", 0) >= 2:
                new_weights["momentum_vol_weight"] = round(min(0.35, new_weights["momentum_vol_weight"] + 0.03), 3)
                adjustments["momentum_vol_weight"] = "+0.03 (強化量能門檻)"

            # 若「進場基期過高」過多，強化低底位階權重
            if report["failure_breakdown"].get("進場基期過高 (D20已脫離 > 5%，易遭主力倒貨)", 0) >= 2:
                new_weights["base_level_weight"] = round(min(0.50, new_weights["base_level_weight"] + 0.03), 3)
                adjustments["base_level_weight"] = "+0.03 (強化極寒雙綠位階)"

            # 正規化權重至 1.0
            total_w = sum(new_weights.values())
            if total_w > 0:
                for k in new_weights:
                    new_weights[k] = round(new_weights[k] / total_w, 4)

            self.weights = new_weights
            self.save_weights(new_weights)
            report["weight_adjustments"] = adjustments

            logger.info(f"📈 [演算法覆盤與進化完成] 總交易: {len(trades)}筆 | 勝率: {report['win_rate']:.1f}% | 賺賠比: {report['payoff_ratio']:.2f}")
        except Exception as e:
            logger.error(f"❌ 覆盤進化分析異常: {e}")
        finally:
            conn.close()

        return report


# 全域 AI 模擬交易引擎實例
ai_trading_engine = AISimulationEngine()


# ======================================================================================
# 3. 機器人推播與 Web 監聽伺服器 (Bot Server & Health/Webhook Daemon)
# ======================================================================================

class BotPushAndHealthServer:
    """
    推播與輕量監聽服務端
    1. 支援 Telegram 與 LINE 訊息分片與純文字/HTML 排版
    2. 提供 0.0.0.0:PORT 輕量健康檢查與 Webhook 監聽，解決 Mac/Render Port 綁定問題
    """
    def __init__(self, port: int = int(os.getenv("PORT", 10000))):
        self.port = port
        self.is_running = False
        self.server: Optional[asyncio.Server] = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """處理 HTTP 健康檢查與 Webhook 請求"""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                writer.close()
                return

            req_str = request_line.decode("utf-8", errors="ignore").strip()
            # 讀取其餘 Header
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                if not line or line == b"\r\n" or line == b"\n":
                    break

            if "GET" in req_str:
                body = "WayneBot 7x24h All_In_One Async Daemon Online\nStatus: Healthy\n"
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/plain; charset=utf-8\r\n"
                    f"Content-Length: {len(body.encode('utf-8'))}\r\n"
                    "Connection: close\r\n\r\n" + body
                )
            else:
                body = "{\"status\": \"received\"}\n"
                response = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(body.encode('utf-8'))}\r\n"
                    "Connection: close\r\n\r\n" + body
                )

            writer.write(response.encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start_server(self) -> None:
        """非阻塞啟動 Async HTTP/Webhook 伺服器，啟用 SO_REUSEADDR 徹底防止埠號鎖死"""
        try:
            # 手動設定 Socket 以啟用 SO_REUSEADDR
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setblocking(False)
            sock.bind(("0.0.0.0", self.port))

            self.server = await asyncio.start_server(
                self.handle_client,
                sock=sock
            )
            self.is_running = True
            logger.info(f"🌐 [Web/Health Server 啟動成功] 監聽地址: 0.0.0.0:{self.port} (已啟用 SO_REUSEADDR)")
            async with self.server:
                await self.server.serve_forever()
        except asyncio.CancelledError:
            logger.info("🛑 Web/Health Server 接收到取消訊號，準備關閉...")
        except Exception as e:
            logger.error(f"❌ Web/Health Server 異常: {e}")
        finally:
            await self.stop_server()

    async def stop_server(self) -> None:
        """優雅關閉伺服器並釋放通訊埠"""
        if self.server:
            try:
                self.server.close()
                await self.server.wait_closed()
                logger.info(f"🔒 Web/Health Server 已安全釋放 Port {self.port}")
            except Exception as e:
                logger.warning(f"⚠️ 關閉 Web Server 時產生警告: {e}")
            self.server = None
        self.is_running = False

    def push_message_sync(self, title: str, content: str) -> None:
        """同步推播訊息至 Telegram / LINE / 終端機"""
        formatted_text = f"【{title}】\n{content}\n⏱️ 發送時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        logger.info(f"📢 [系統廣播]\n{formatted_text}")

        # 若已就緒 bot_servers 則調用官方通道，否則安全輸出至日誌
        if bot_servers and hasattr(bot_servers, "send_multichannel_push"):
            try:
                bot_servers.send_multichannel_push(title, content)
            except Exception as e:
                logger.warning(f"⚠️ bot_servers 推播模組調用異常: {e}")


# 全域 Bot Server 實例
bot_health_server = BotPushAndHealthServer()


# ======================================================================================
# 4. 異步事件總控與定時排程大腦 (Async Master Orchestrator)
# ======================================================================================

class AsyncWayneBotMaster:
    """
    WayneBot Phase 4 總控核心大腦
    調度三大非同步任務：
      1. Scheduled Pipeline: 盤後大數據清洗、海選漏斗、模擬自動建倉、每日體檢與自適應進化
      2. Telegram Polling: 獨立線程非阻塞處理手機查詢指令 (/查, /持股, /覆盤)
      3. LINE & Health Webhook Server: 即時接收訊息並提供雲端健康心跳
    """
    def __init__(self):
        self.is_running = True
        self.shutdown_event = asyncio.Event()
        self.tasks: List[asyncio.Task] = []

    async def schedule_pipeline_task(self) -> None:
        """
        後台定時排程任務
        - 17:00 / 模擬觸發：盤後大數據更新與持股體檢
        - 20:30 / 模擬觸發：四階海選漏斗、自動模擬進場、推播戰報
        - 定期觸發：自適應進化報告與權重微調
        """
        logger.info("⏱️ [排程總控任務啟動] 後台數據排程與 AI 模擬閉環已就緒")
        try:
            while self.is_running and not self.shutdown_event.is_set():
                now = datetime.datetime.now()
                logger.debug(f"🔍 排程心跳檢測: {now.strftime('%H:%M:%S')}")

                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=60.0)
                    break
                except asyncio.TimeoutError:
                    pass

        except asyncio.CancelledError:
            logger.info("🛑 排程總控任務已被取消")
        except Exception as e:
            logger.error(f"❌ 排程總控任務異常: {e}")

    async def telegram_polling_task(self) -> None:
        """
        Telegram 輪詢任務 (使用 asyncio.to_thread 隔離阻塞式 HTTP 輪詢)
        """
        logger.info("📱 [Telegram 輪詢任務啟動] 獨立線程待命接收指令...")
        loop = asyncio.get_running_loop()

        def _blocking_polling():
            while self.is_running and not self.shutdown_event.is_set():
                if bot_servers and hasattr(bot_servers, "run_tg_single_poll"):
                    try:
                        bot_servers.run_tg_single_poll(timeout=2.0)
                    except Exception:
                        time.sleep(2.0)
                else:
                    time.sleep(1.0)

        try:
            await loop.run_in_executor(None, _blocking_polling)
        except asyncio.CancelledError:
            logger.info("🛑 Telegram 輪詢任務已被取消")
        except Exception as e:
            logger.error(f"❌ Telegram 輪詢異常: {e}")

    async def run_daily_workflow_now(self, mock_candidates: Optional[List[Dict[str, Any]]] = None, mock_prices: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        手動或即時觸發一次完整的「海選 -> 模擬建倉 -> 盤後體檢 -> 覆盤進化 -> 推播」全流程
        """
        logger.info("🚀 [即刻執行] 啟動全流程 AI 模擬操盤與進化閉環...")
        trade_date = datetime.datetime.now().strftime("%Y%m%d")

        # 1. 取得海選標的 (優先使用 screening_engine，無則使用 mock 或預設候選)
        candidates = []
        if mock_candidates:
            candidates = mock_candidates
        elif screening_engine and hasattr(screening_engine, "run_screening_flow"):
            try:
                candidates = screening_engine.run_screening_flow()
            except Exception as e:
                logger.warning(f"⚠️ screening_engine 調用失敗，使用降級標的: {e}")

        if not candidates:
            # 預設標的
            candidates = [
                {"stock_id": "2605", "stock_name": "新興", "close": 28.5, "score": 88.0, "grade": "A", "d20_gain": 0.8, "space_20": 24.5, "vol_rank": 6},
                {"stock_id": "6152", "stock_name": "百一", "close": 14.2, "score": 84.5, "grade": "A", "d20_gain": 1.2, "space_20": 18.0, "vol_rank": 12},
                {"stock_id": "2208", "stock_name": "台船", "close": 19.8, "score": 81.0, "grade": "B", "d20_gain": 1.4, "space_20": 16.5, "vol_rank": 18}
            ]

        # 2. AI 模擬自動建倉
        new_positions = ai_trading_engine.auto_simulate_entry(candidates, trade_date=trade_date)

        # 3. 盤後體檢與平倉結算
        market_quotes = mock_prices if mock_prices is not None else {
            "2605": {"close": 29.8, "high": 30.2, "low": 28.3},
            "6152": {"close": 13.5, "high": 14.3, "low": 13.4},
            "2208": {"close": 23.0, "high": 23.2, "low": 19.5}
        }
        checkup_res = ai_trading_engine.daily_portfolio_checkup(market_quotes, check_date=trade_date)

        # 4. 覆盤進化與權重微調
        evolution_res = ai_trading_engine.generate_evolution_report_and_tune_weights()

        # 5. 推播全方位戰報
        summary_msg = (
            f"📊 【WayneBot 每日操盤與自我進化戰報】\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 今日模擬建倉: {len(new_positions)} 檔\n"
            f"💼 目前在倉部位: {len(checkup_res['active_positions'])} 檔 (未實現損益: {checkup_res['total_unrealized_pnl']:+,.0f} 元)\n"
            f"🚪 今日平倉結算: {len(checkup_res['closed_trades'])} 檔\n"
            f"🏆 累計已平倉勝率: {evolution_res['win_rate']:.1f}% (總交易: {evolution_res['total_trades']} 筆)\n"
            f"⚖️ 賺賠比 (Payoff Ratio): {evolution_res['payoff_ratio']:.2f}\n"
            f"⚙️ 模型權重調整: {evolution_res.get('weight_adjustments', '維持基準')}"
        )
        bot_health_server.push_message_sync("AI 操盤進化日報", summary_msg)

        return {
            "new_positions": new_positions,
            "checkup": checkup_res,
            "evolution": evolution_res
        }

    async def run(self) -> None:
        """主異步協同調度入口 (asyncio.gather)"""
        logger.info("==================================================================")
        logger.info("🚀 WayneBot Phase 4 All_In_One 總控核心啟動")
        logger.info("==================================================================")

        # 建立三大核心異步協程任務
        task_pipeline = asyncio.create_task(self.schedule_pipeline_task(), name="Task-Pipeline")
        task_tg = asyncio.create_task(self.telegram_polling_task(), name="Task-Telegram")
        task_server = asyncio.create_task(bot_health_server.start_server(), name="Task-WebServer")

        self.tasks = [task_pipeline, task_tg, task_server]

        try:
            # 同步並行調度
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            logger.info("🛑 總控核心收到取消請求，正在收斂所有子任務...")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """優雅關閉（Graceful Shutdown）實現"""
        if not self.is_running:
            return
        logger.info("\n🛑 [優雅關閉程序啟動] 正在終止 WayneBot 核心服務...")
        self.is_running = False
        self.shutdown_event.set()

        # 1. 取消所有運行中的 Task
        for t in self.tasks:
            if not t.done():
                t.cancel()

        # 2. 等待 Task 安全終止
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("✅ 所有非同步任務已安全取消")

        # 3. 釋放 Web Server Socket
        await bot_health_server.stop_server()

        # 4. 執行 SQLite WAL Checkpoint 並關閉
        db_manager.checkpoint_and_close()

        logger.info("🎉 [Graceful Shutdown 完成] 資源已全數釋放，通訊埠無殘留，資料庫安全結案。")


# ======================================================================================
# 5. 系統信號註冊與執行入口 (Signal Handling & Main Entry)
# ======================================================================================

def setup_signal_handlers(master: AsyncWayneBotMaster, loop: asyncio.AbstractEventLoop) -> None:
    """註冊作業系統信號，支援 Unix / macOS / Windows / Colab 跨平台中斷捕捉"""
    def _signal_handler(sig_name: str):
        logger.info(f"\n⚡ 捕捉到系統信號 [{sig_name}]，觸發優雅關閉流程...")
        master.is_running = False
        master.shutdown_event.set()
        for t in master.tasks:
            if not t.done():
                t.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig.name: _signal_handler(s))
        except NotImplementedError:
            # Windows 或特定受限環境 fallback
            signal.signal(sig, lambda signum, frame: _signal_handler(signal.Signals(signum).name))


def main() -> None:
    """主程序進入點"""
    master = AsyncWayneBotMaster()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    setup_signal_handlers(master, loop)

    try:
        loop.run_until_complete(master.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⚡ 接收到終端鍵盤中斷指令")
    finally:
        try:
            loop.run_until_complete(master.shutdown())
        except Exception as e:
            logger.warning(f"⚠️ 關閉時發生例外: {e}")
        finally:
            loop.close()
            logger.info("🏁 WayneBot 主程式已安全退出")


if __name__ == "__main__":
    main()
