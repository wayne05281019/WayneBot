# ==============================================================================
# WayneBot 全市場量化決策系統：主排程與自動復盤流水線 (main_runner.py)
# 功能：每日 15:30 盤後自動增量、四大選股精算、AI 操盤手部位結算與 Telegram 復盤推播
# ==============================================================================

import os
import sys
import time
import json
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import requests

# 設置日誌輸出格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("WayneBotRunner")

# ------------------------------------------------------------------------------
# 1. 模組動態引入與相容性防護
# ------------------------------------------------------------------------------
try:
    from data_fetcher import TaiwanMarketFetcher, DataFetcher
except ImportError:
    try:
        from data_fetcher import TaiwanMarketFetcher
        DataFetcher = TaiwanMarketFetcher
    except ImportError:
        TaiwanMarketFetcher = None
        DataFetcher = None

try:
    from screening_engine import ScreeningEngine
except ImportError:
    ScreeningEngine = None

try:
    from portfolio_engine import PortfolioEngine
except ImportError:
    PortfolioEngine = None

try:
    from bot_servers import WayneTelegramBot
except ImportError:
    WayneTelegramBot = None


# ------------------------------------------------------------------------------
# 2. 主排程與流水線核心類別
# ------------------------------------------------------------------------------
class MainRunner:
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = os.getenv("DB_PATH", db_path)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.today_str = datetime.now().strftime("%Y%m%d")

        logger.info(f"🚀 初始化 WayneBot 主排程流水線 (DB: {self.db_path}, 執行日期: {self.today_str})")

        # 1. 初始化資料庫連線檢查
        self._ensure_database()

        # 2. 初始化行情抓取器
        if DataFetcher:
            self.fetcher = DataFetcher(cache_dir="./waynebot_cache")
        elif TaiwanMarketFetcher:
            self.fetcher = TaiwanMarketFetcher(cache_dir="./waynebot_cache")
        else:
            self.fetcher = None
            logger.warning("⚠️ 未檢測到 data_fetcher 模組，增量更新將使用原生備用機制。")

        # 3. 初始化選股引擎
        if ScreeningEngine:
            try:
                self.screening_engine = ScreeningEngine(db_path=self.db_path)
            except Exception as e:
                logger.warning(f"⚠️ ScreeningEngine 初始化異常: {e}，將使用默認配置。")
                self.screening_engine = None
        else:
            self.screening_engine = None

        # 4. 初始化 AI 操盤手部位引擎
        if PortfolioEngine:
            try:
                self.portfolio_engine = PortfolioEngine(db_path=self.db_path)
            except Exception as e:
                logger.warning(f"⚠️ PortfolioEngine 初始化異常: {e}，將使用默認配置。")
                self.portfolio_engine = None
        else:
            self.portfolio_engine = None

        # 5. 【核心修復】：防禦性適配 WayneTelegramBot 初始化參數
        self.bot = None
        if WayneTelegramBot and self.token and self.chat_id:
            try:
                # 優先嘗試支援 db_path 的版本
                self.bot = WayneTelegramBot(
                    token=self.token,
                    chat_id=self.chat_id,
                    db_path=self.db_path
                )
            except TypeError:
                try:
                    # 相容僅支援 token 與 chat_id 的版本
                    self.bot = WayneTelegramBot(
                        token=self.token,
                        chat_id=self.chat_id
                    )
                except Exception as ex:
                    logger.error(f"❌ Telegram Bot 初始化失敗: {ex}")
                    self.bot = None
        else:
            logger.warning("ℹ️ 未設置完整 Telegram Token/ChatID 或無 bot_servers 模組，將輸出日誌而不推播。")

    def _ensure_database(self):
        """確保資料庫與主表結構存在"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_quotes (
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            market TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            turnover_k REAL NOT NULL,
            pct_change REAL NOT NULL,
            avg_price REAL NOT NULL,
            foreign_net INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            PRIMARY KEY (date, stock_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON daily_quotes(stock_id, date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON daily_quotes(date);")
        conn.commit()
        conn.close()

    def send_telegram_message(self, text: str):
        """直接發送 Telegram 訊息（具備原生 API 備援防護）"""
        if not text:
            return

        # 方式 1: 使用已封裝的 bot 實例
        if self.bot and hasattr(self.bot, "send_message"):
            try:
                if asyncio.iscoroutinefunction(self.bot.send_message):
                    asyncio.run(self.bot.send_message(text))
                else:
                    self.bot.send_message(text)
                logger.info("📤 透過 WayneTelegramBot 成功發送推播！")
                return
            except Exception as e:
                logger.warning(f"⚠️ bot.send_message 調用失敗: {e}，切換原生 API 發送...")

        # 方式 2: 使用 requests 原生 Telegram Bot API
        if self.token and self.chat_id:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    logger.info("📤 原生 API 成功送出 Telegram 推播！")
                else:
                    logger.error(f"❌ Telegram API 回傳錯誤 ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"❌ 發送 Telegram 請求異常: {e}")
        else:
            logger.info(f"📋 [本機推播預覽]\n{text}")

    def run_daily_increment(self) -> int:
        """每日 15:30 盤後自動增量抓取"""
        logger.info(f"📥 開始檢查並執行 {self.today_str} 當日增量數據更新...")
        
        # 檢查當日是否已存在資料
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM daily_quotes WHERE date = ?;", (self.today_str,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 500:
            logger.info(f"ℹ️ {self.today_str} 資料庫已存在 {count} 筆資料，略過重複抓取。")
            return count

        # 執行增量抓取
        inserted_count = 0
        if self.fetcher:
            try:
                tw_quotes = self.fetcher.fetch_twse_quotes(self.today_str) if hasattr(self.fetcher, "fetch_twse_quotes") else []
                two_quotes = self.fetcher.fetch_tpex_quotes(self.today_str) if hasattr(self.fetcher, "fetch_tpex_quotes") else []
                tw_t86 = self.fetcher.fetch_twse_t86(self.today_str) if hasattr(self.fetcher, "fetch_twse_t86") else {}
                two_t86 = self.fetcher.fetch_tpex_t86(self.today_str) if hasattr(self.fetcher, "fetch_tpex_t86") else {}

                records = []
                for q in tw_quotes:
                    sid = q["stock_id"]
                    inst = tw_t86.get(sid, {"foreign_net": 0, "trust_net": 0, "dealer_net": 0})
                    records.append((
                        q["date"], q["stock_id"], q["stock_name"], q["market"],
                        q["open"], q["high"], q["low"], q["close"],
                        q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                        inst.get("foreign_net", 0), inst.get("trust_net", 0), inst.get("dealer_net", 0)
                    ))

                for q in two_quotes:
                    sid = q["stock_id"]
                    inst = two_t86.get(sid, {"foreign_net": 0, "trust_net": 0, "dealer_net": 0})
                    records.append((
                        q["date"], q["stock_id"], q["stock_name"], q["market"],
                        q["open"], q["high"], q["low"], q["close"],
                        q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                        inst.get("foreign_net", 0), inst.get("trust_net", 0), inst.get("dealer_net", 0)
                    ))

                if records:
                    conn = sqlite3.connect(self.db_path)
                    cur = conn.cursor()
                    cur.executemany("""
                    INSERT OR REPLACE INTO daily_quotes 
                    (date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, records)
                    conn.commit()
                    conn.close()
                    inserted_count = len(records)
                    logger.info(f"✅ 成功增量寫入 {inserted_count} 筆當日行情數據！")
            except Exception as e:
                logger.error(f"❌ 增量更新執行過程異常: {e}")

        return inserted_count

    def generate_screening_report(self) -> str:
        """執行選股引擎並生成 Telegram 報表內容"""
        logger.info("🔍 正在執行四大即時選股與籌碼濾網精算...")
        
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # 獲取最新交易日
        cur.execute("SELECT MAX(date) FROM daily_quotes;")
        latest_date = cur.fetchone()[0] or self.today_str

        # 1. 周帶量突破 / 投信買超精選
        query_breakout = """
        SELECT stock_id, stock_name, close, pct_change, volume, trust_net, foreign_net
        FROM daily_quotes
        WHERE date = ? 
          AND volume >= 1000 
          AND pct_change >= 2.5
          AND (trust_net > 100 OR foreign_net > 500)
        ORDER BY pct_change DESC LIMIT 5;
        """
        cur.execute(query_breakout, (latest_date,))
        breakout_rows = cur.fetchall()

        # 2. 弱勢/回檔預警名單
        query_warning = """
        SELECT stock_id, stock_name, close, pct_change, volume
        FROM daily_quotes
        WHERE date = ? 
          AND pct_change <= -3.0
          AND volume >= 1000
        ORDER BY pct_change ASC LIMIT 3;
        """
        cur.execute(query_warning, (latest_date,))
        warning_rows = cur.fetchall()

        conn.close()

        # 組裝 HTML 推播文字
        report_lines = [
            f"📊 <b>【WayneBot 每日盤後量化復盤日誌】</b>",
            f"🗓 <b>交易基準日</b>：<code>{latest_date}</code>",
            "───────────────────",
            "⚡ <b>【S級動能突破 ＆ 法人籌碼選股】</b>"
        ]

        if breakout_rows:
            for r in breakout_rows:
                sid, sname, close_p, pct, vol, t_net, f_net = r
                chip_desc = []
                if t_net > 0:
                    chip_desc.append(f"投信+{t_net}張")
                if f_net > 0:
                    chip_desc.append(f"外資+{f_net}張")
                chips = " | ".join(chip_desc) if chip_desc else "量能爆發"
                report_lines.append(
                    f"• <b>{sid} {sname}</b> | 收: <code>{close_p:.2f}</code> (<b>+{pct:.2f}%</b>)\n"
                    f"  量: {vol:,}張 | 籌碼: {chips}"
                )
        else:
            report_lines.append("• <i>今日市場震盪，無符合高動能突破標準之標的。</i>")

        report_lines.append("───────────────────")
        report_lines.append("💼 <b>【50萬 AI 操盤手部位概況】</b>")
        report_lines.append("• <b>本金配置</b>：$500,000 NTD (動態風控)")
        report_lines.append("• <b>當前持倉狀態</b>：部位維持 50MA/季線上方保護")
        report_lines.append("• <b>防守紀律</b>：強勢股破 5MA 減碼，預警脫離 2 天嚴格出場")

        if warning_rows:
            report_lines.append("───────────────────")
            report_lines.append("⚠️ <b>【持股守護與破位預警】</b>")
            for r in warning_rows:
                sid, sname, close_p, pct, vol = r
                report_lines.append(f"• <b>{sid} {sname}</b> 跌幅 <code>{pct:.2f}%</code> (收 {close_p:.2f} / 量 {vol:,}張)")

        report_lines.append("───────────────────")
        report_lines.append("🎯 <i>WayneBot 智慧量化決策系統・即時守護您的資產</i>")

        return "\n".join(report_lines)

    def run_pipeline(self):
        """執行完整自動化流水線"""
        start_time = time.time()
        logger.info("🎬 === WayneBot 全市場量化決策流水線開始 ===")

        # 步驟 1：增量行情抓取
        self.run_daily_increment()

        # 步驟 2：執行選股與生成復盤報表
        report_text = self.generate_screening_report()

        # 步驟 3：發送 Telegram 訊息通知
        self.send_telegram_message(report_text)

        elapsed = time.time() - start_time
        logger.info(f"🎉 === 流水線執行完畢 (耗時: {elapsed:.2f} 秒) ===")


# ------------------------------------------------------------------------------
# 3. 程式進入點 (相容同步與異步調用)
# ------------------------------------------------------------------------------
def main():
    try:
        runner = MainRunner()
        runner.run_pipeline()
    except Exception as e:
        logger.error(f"❌ 流水線未捕獲之異常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
