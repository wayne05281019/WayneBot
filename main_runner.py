# ==============================================================================
# WayneBot 全市場量化決策系統：主排程與自動復盤核心 (main_runner.py)
# 檔案用途：整合 Telegram 互動服務、定時增量更新、盤後選股復盤與 Render 防休眠
# ==============================================================================

import os
import sys
import time
import logging
import asyncio
from datetime import datetime, time as dtime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# 載入核心模組（已修正導入規範）
from data_fetcher import DataFetcher
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from bot_servers import WayneTelegramBot

# ------------------------------------------------------------------------------
# 1. 日誌設定
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(filename)s:%(lineno)d) - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WayneBot_Runner")

# ------------------------------------------------------------------------------
# 2. Render 免費版 Web Port 綁定服務（防休眠與健康檢查）
# ------------------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        response_text = f"WayneBot Quant Engine is Running!\nServer Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.wfile.write(response_text.encode("utf-8"))

    def log_message(self, format, *args):
        # 靜音常規健康檢查日誌以維持終端機整潔
        return

def start_render_keep_alive_server():
    """在背景線程啟動 HTTP 伺服器以符合 Render Port 綁定規範"""
    port = int(os.environ.get("PORT", 8080))
    server_address = ("0.0.0.0", port)
    try:
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"🌐 Render Keep-Alive 伺服器已啟動於通訊埠: {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"❌ Keep-Alive 伺服器啟動異常: {e}")

# ------------------------------------------------------------------------------
# 3. 盤後自動化任務協調器
# ------------------------------------------------------------------------------
class MainAutomationRunner:
    def __init__(self):
        self.fetcher = DataFetcher()
        self.screener = ScreeningEngine()
        self.portfolio = PortfolioEngine()
        self.bot = WayneTelegramBot()
        self.admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")

    async def execute_daily_1530_incremental(self):
        """每日 15:30 執行：增量抓取當日全市場 2,202 檔數據寫入 SQLite"""
        today_str = datetime.now().strftime("%Y%m%d")
        weekday = datetime.now().weekday()
        if weekday >= 5:
            logger.info("⏸️ 今日為週末，略過 15:30 行情抓取。")
            return

        logger.info(f"📥 開始執行 15:30 每日增量行情抓取 (日期: {today_str})...")
        try:
            # 呼叫資料庫增量更新函式
            loop = asyncio.get_running_loop()
            inserted_count = await loop.run_in_executor(None, self.fetcher.update_daily_incremental, today_str)
            logger.info(f"✅ 15:30 增量寫入完成，共計更新 {inserted_count} 筆資料。")
        except Exception as e:
            logger.error(f"❌ 15:30 增量行情抓取失敗: {e}", exc_info=True)

    async def execute_daily_1545_review_and_broadcast(self):
        """每日 15:45 執行：自動選股、多用戶持倉損益計算與復盤報告推播"""
        today_str = datetime.now().strftime("%Y%m%d")
        weekday = datetime.now().weekday()
        if weekday >= 5:
            logger.info("⏸️ 今日為週末，略過 15:45 復盤推播。")
            return

        logger.info(f"📊 開始執行 15:45 盤後自動選股與持倉復盤 (日期: {today_str})...")
        try:
            loop = asyncio.get_running_loop()

            # 1. 執行四大選股策略與 S 級籌碼篩選
            selection_results = await loop.run_in_executor(None, self.screener.run_all_strategies, today_str)
            
            # 2. 執行 AI 操盤手每日損益結算與脫離防守守護
            portfolio_summary = await loop.run_in_executor(None, self.portfolio.evaluate_daily_status, today_str)

            # 3. 組合 Telegram 專業排版訊息卡
            review_message = self._compose_daily_review_message(today_str, selection_results, portfolio_summary)

            # 4. 發送給管理員或群組
            if self.admin_chat_id:
                await self.bot.send_message_async(chat_id=self.admin_chat_id, text=review_message)
                logger.info(f"📨 15:45 復盤日誌已成功推播至 Telegram ({self.admin_chat_id})。")
            else:
                logger.warning("⚠️ 未設定 TELEGRAM_ADMIN_CHAT_ID，僅於日誌輸出復盤內容。")
                logger.info(f"\n{review_message}")

        except Exception as e:
            logger.error(f"❌ 15:45 復盤推播作業失敗: {e}", exc_info=True)

    def _compose_daily_review_message(self, date_str: str, selection_results: dict, portfolio_summary: dict) -> str:
        """格式化產出《今日持倉損益與明日規劃》與《盤後復盤日誌》"""
        lines = [
            f"📊 <b>WayneBot 盤後量化復盤日誌</b> ｜ <code>{date_str}</code>",
            "───────────────────",
            "💼 <b>【50萬 AI 操盤手持倉概況】</b>",
            f"• 總資產估值: <code>NT$ {portfolio_summary.get('total_asset', 500000):,.0f}</code>",
            f"• 今日實現/未實現損益: <code>{portfolio_summary.get('daily_pnl_str', '+0.00%')}</code>",
            f"• 當前水位: <code>{portfolio_summary.get('position_ratio', '0.0%')}</code>（現金: {portfolio_summary.get('cash', 500000):,.0f}）",
            f"• 持股檔數: <code>{portfolio_summary.get('holdings_count', 0)}</code> 檔",
            "───────────────────",
            "⚡ <b>【CaryBot 四大即時選股成果】</b>"
        ]

        # 整理四大選股清單
        strategies = [
            ("Select 01 周帶量突破", selection_results.get("sel_01", [])),
            ("Select 02 突破 Hi120", selection_results.get("sel_02", [])),
            ("Select 03 突破 Hi480", selection_results.get("sel_03", [])),
            ("Select 04 雙綠脫離", selection_results.get("sel_04", []))
        ]

        has_any_stock = False
        for title, stocks in strategies:
            if stocks:
                has_any_stock = True
                stock_str = " ".join([f"<code>{s['stock_id']} {s['stock_name']}</code>" for s in stocks[:5]])
                lines.append(f"• <b>{title}</b> ({len(stocks)} 檔):\n  └ {stock_str}")

        if not has_any_stock:
            lines.append("• 今日無符合四大突破策略之嚴選標的（盤勢多空震盪）。")

        lines.extend([
            "───────────────────",
            "🎯 <b>【明日操盤與防守規劃】</b>",
            "• 股海武僧紀律：強勢股若浮現粉紅標籤需連續 2 天確認脫離。",
            "• 隔日沖注意：開盤未達動態目標且 09:15 量能停滯者強制保本出場。",
            "🤖 <i>WayneBot Quantitative Decision System v2.0</i>"
        ])

        return "\n".join(lines)

    async def run_scheduler_loop(self):
        """精確非同步定時排程迴圈"""
        logger.info("⏰ 定時排程引擎啟動 (監聽時段: 15:30 增量更新, 15:45 復盤推播)...")
        last_executed_date_1530 = ""
        last_executed_date_1545 = ""

        while True:
            try:
                now = datetime.now()
                current_date = now.strftime("%Y%m%d")
                current_time = now.time()

                # 15:30 增量更新觸發判斷 (15:30:00 ~ 15:32:00)
                if dtime(15, 30) <= current_time <= dtime(15, 32) and last_executed_date_1530 != current_date:
                    last_executed_date_1530 = current_date
                    await self.execute_daily_1530_incremental()

                # 15:45 復盤推播觸發判斷 (15:45:00 ~ 15:47:00)
                if dtime(15, 45) <= current_time <= dtime(15, 47) and last_executed_date_1545 != current_date:
                    last_executed_date_1545 = current_date
                    await self.execute_daily_1545_review_and_broadcast()

                # 每 30 秒輪詢一次時鐘
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"❌ 排程迴圈異常: {e}")
                await asyncio.sleep(30)

# ------------------------------------------------------------------------------
# 4. 主程式入口
# ------------------------------------------------------------------------------
async def main():
    print("=" * 70)
    print("🚀 啟動 WayneBot 全市場量化決策系統主核心 (main_runner.py)")
    print("=" * 70)

    # 1. 在獨立線程中啟動 Render 防休眠 Web 伺服器
    keep_alive_thread = Thread(target=start_render_keep_alive_server, daemon=True)
    keep_alive_thread.start()

    # 2. 初始化自動化排程與 Telegram 機器人實例
    runner = MainAutomationRunner()

    # 3. 同時並行：啟動 Telegram 長輪詢服務 + 定時排程服務
    logger.info("🤖 正在啟動 Telegram 互動監聽與定時任務...")
    await asyncio.gather(
        runner.bot.start_polling_async(),
        runner.run_scheduler_loop()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 收到關閉信號，WayneBot 已安全停止。")
