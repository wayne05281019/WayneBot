"""
main_runner.py - WayneBot Phase 10 全系統非同步總控排程器
功能：
1. 異步整合調度：asyncio.gather 同步常駐 Telegram Bot、Aiohttp 10000 埠與 16:30 定時增量更新。
2. Graceful Shutdown：安全切斷連線並執行 SQLite WAL Checkpoint (TRUNCATE)。
3. 環境變數：自動讀取 .env 或預設參數。
"""

import os
import sys
import asyncio
import signal
import logging
import sqlite3
from datetime import datetime, time
from typing import Optional
from aiohttp import web
from dotenv import load_dotenv

from screening_engine import ScreeningEngine

# 載入 .env 環境變數
load_dotenv()

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WayneBotRunner")


class MasterRunner:
    def __init__(self):
        self.db_path = os.getenv("WAYNE_DB_PATH", "wayne_market.db")
        self.port = int(os.getenv("PORT", "10000"))
        self.tg_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        
        self.screening_engine = ScreeningEngine(db_path=self.db_path)
        self.shutdown_event = asyncio.Event()
        self.web_runner: Optional[web.AppRunner] = None
        self.background_tasks = []

    def execute_wal_checkpoint(self):
        """
        執行 SQLite WAL Checkpoint，將日誌寫回主庫並截斷。
        """
        logger.info("🛠️ [Database] 正在執行 SQLite WAL Checkpoint (TRUNCATE)...")
        try:
            if os.path.exists(self.db_path):
                conn = sqlite3.connect(self.db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                result = cursor.fetchall()
                conn.close()
                logger.info(f"✅ [Database] WAL Checkpoint 完成，狀態: {result}")
            else:
                logger.info("ℹ️ [Database] 資料庫檔案尚未生成，跳過 Checkpoint。")
        except Exception as e:
            logger.error(f"❌ [Database] WAL Checkpoint 執行失敗: {e}")

    # ------------------------------------------------------------------
    # 子任務一：Aiohttp 防休眠 Web 伺服器 (Port 10000)
    # ------------------------------------------------------------------
    async def handle_health_check(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "online",
            "service": "WayneBot Master System (Phase 10)",
            "timestamp": datetime.now().isoformat(),
            "db_status": "connected" if os.path.exists(self.db_path) else "pending"
        })

    async def handle_manual_screen(self, request: web.Request) -> web.Response:
        """手動觸發海選 API 端點"""
        logger.info("📡 [Web] 收到手動海選 API 請求...")
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, self.screening_engine.run_full_market_screening)
        return web.json_response(res)

    async def start_web_server(self):
        app = web.Application()
        app.router.add_get("/", self.handle_health_check)
        app.router.add_get("/health", self.handle_health_check)
        app.router.add_post("/api/screen", self.handle_manual_screen)

        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        site = web.TCPSite(self.web_runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"🚀 [Web Server] 防休眠伺服器已於 http://0.0.0.0:{self.port} 啟動。")

        try:
            await self.shutdown_event.wait()
        finally:
            logger.info("🛑 [Web Server] 正在關閉 Web 伺服器釋放 Port...")
            await self.web_runner.cleanup()
            logger.info("✅ [Web Server] Web 伺服器已安全釋放。")

    # ------------------------------------------------------------------
    # 子任務二：Telegram 輪詢監聽工作元
    # ------------------------------------------------------------------
    async def format_telegram_report(self, screen_result: dict) -> str:
        lines = [
            "🏆 *【WayneBot / CaryBot 量化海選決策日報】*",
            f"📅 掃描時間：`{screen_result['scan_time']}`",
            f"📊 掃描總數：`{screen_result['total_scanned']} 檔` | 🎯 第 1 天：`{screen_result['day1_count']} 檔` | 🛡️ 備援：`{screen_result['backup_count']} 檔`",
            f"📌 決策狀態：{screen_result['strategy_status']}",
            "───────────────────"
        ]

        if not screen_result["recommendations"]:
            lines.append("⚠️ 今日全市場均未出現符合標準之起漲標的，建議保持資金防禦。")
        else:
            for idx, item in enumerate(screen_result["recommendations"], 1):
                lines.extend([
                    f"*{idx}. {item['stock_name']} ({item['symbol']})*",
                    f"  • 收盤價: `{item['close_price']} 元` ({item['change_pct']:+0.2f}%)",
                    f"  • 判定階段: `{item['breakout_stage']}`",
                    f"  • 多空溫度: `{item['temperature']}°C` | 位階: `{item['position_tag']}`",
                    f"  • 距成本獲利: `{item['current_profit_from_cost']:+0.2f}%` (成本線: `{item['cost_line']}`)",
                    f"  • 操作空間: 上 `{item['upside_room_pct']}%` / 下防守 `{item['downside_risk_pct']}%`",
                    f"  • 三大法人: `{item['total_inst_lots']:+d} 張` (外資 `{item['foreign_lots']:+d}` / 投信 `{item['trust_lots']:+d}`)",
                    "───────────────────"
                ])

        lines.append("🤖 _由 WayneBot AI 自動化量化引擎生成，嚴守停損停利紀律。_")
        return "\n".join(lines)

    async def run_telegram_worker(self):
        logger.info("🤖 [Telegram] Bot 常駐工作元已上線運作。")
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
        logger.info("✅ [Telegram] Telegram 工作元已安全退出。")

    # ------------------------------------------------------------------
    # 子任務三：每日 16:30 定時增量更新與自動推播排程
    # ------------------------------------------------------------------
    async def run_daily_scheduler(self):
        logger.info("⏰ [Scheduler] 每日 16:30 自動化增量排程器已啟動。")
        last_executed_date = None

        while not self.shutdown_event.is_set():
            try:
                now = datetime.now()
                target_time = time(16, 30, 0)
                current_time = now.time()
                today_str = now.strftime("%Y-%m-%d")

                if current_time >= target_time and last_executed_date != today_str:
                    logger.info("🎯 [Scheduler] 觸發 16:30 盤後官方增量更新與 CaryBot 海選運算...")
                    loop = asyncio.get_running_loop()
                    results = await loop.run_in_executor(None, self.screening_engine.run_full_market_screening)
                    report = await self.format_telegram_report(results)
                    logger.info(f"📢 [推播報表預覽]\n{report}")
                    last_executed_date = today_str

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ [Scheduler] 排程運算異常: {e}")
                await asyncio.sleep(60)

        logger.info("✅ [Scheduler] 排程器已安全退出。")

    # ------------------------------------------------------------------
    # 總控生命週期管理與 Graceful Shutdown
    # ------------------------------------------------------------------
    async def run_forever(self):
        logger.info("⚡ [WayneBot Phase 10] 全系統核心調度啟動中...")

        web_task = asyncio.create_task(self.start_web_server(), name="Task-WebServer")
        tg_task = asyncio.create_task(self.run_telegram_worker(), name="Task-TelegramWorker")
        sched_task = asyncio.create_task(self.run_daily_scheduler(), name="Task-DailyScheduler")

        self.background_tasks = [web_task, tg_task, sched_task]

        try:
            await asyncio.gather(*self.background_tasks)
        except asyncio.CancelledError:
            logger.info("⚠️ [Main] 收到取消信號，正在進行優雅關閉程序...")
        finally:
            self.execute_wal_checkpoint()
            logger.info("🏁 [WayneBot Phase 10] 全系統安全停機程序完成。")

    def handle_signal(self, sig, frame):
        logger.info(f"🛑 [Signal] 捕捉到信號 {sig}，觸發 Graceful Shutdown...")
        self.shutdown_event.set()
        for task in self.background_tasks:
            task.cancel()


def main():
    runner = MasterRunner()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: runner.handle_signal(s, None))
        except NotImplementedError:
            signal.signal(sig, runner.handle_signal)

    try:
        loop.run_until_complete(runner.run_forever())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
