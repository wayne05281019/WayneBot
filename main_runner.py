"""
main_runner.py - WayneBot Phase 10 全系統非同步總控排程器 (完整數據流水線版)
"""

import os
import sys
import asyncio
import signal
import logging
import sqlite3
import subprocess
import requests
from datetime import datetime, time, timedelta
from typing import Optional
from aiohttp import web
from dotenv import load_dotenv

from screening_engine import ScreeningEngine, format_telegram_report

load_dotenv()

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

    def sync_market_data_if_needed(self):
        """執行 wayne_market_db.py 下載全市場 2,233 檔行情數據"""
        logger.info("📥 [Database] 正在執行全市場行情同步 (wayne_market_db.py)...")
        if os.path.exists("wayne_market_db.py"):
            try:
                res = subprocess.run([sys.executable, "wayne_market_db.py"], capture_output=True, text=True, timeout=600)
                if res.stdout:
                    logger.info(f"wayne_market_db 輸出: {res.stdout[-300:]}")
                if res.returncode == 0:
                    logger.info("✅ [Database] 行情同步執行成功！")
                    return True
                else:
                    logger.error(f"❌ [Database] 行情同步回傳錯誤碼 {res.returncode}: {res.stderr[-300:]}")
            except Exception as e:
                logger.error(f"❌ [Database] 執行 wayne_market_db.py 失敗: {e}")
        else:
            logger.warning("⚠️ [Database] 目錄中未找到 wayne_market_db.py。")
        return False

    def send_telegram_direct(self, text: str):
        if not self.tg_bot_token or not self.tg_chat_id:
            logger.warning("⚠️ [Telegram] 未設定金鑰，跳過發送。")
            return
        url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                logger.info("📢 [Telegram] 批次推播成功發送！")
            else:
                logger.error(f"❌ [Telegram] 推播失敗 HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"❌ [Telegram] 發送請求異常: {e}")

    def run_github_actions_batch(self):
        logger.info("⚡ [WayneBot] 偵測到 GitHub Actions 自動化環境，啟動【全市場量化流水線】...")
        
        # 1. 抓取證交所 2,233 檔資料
        self.sync_market_data_if_needed()
        
        # 2. 重新連接並掃描海選
        self.screening_engine = ScreeningEngine(db_path=self.db_path)
        logger.info("🔍 [Screening] 正在執行 CaryBot 全市場起漲第 1 天海選掃描...")
        results = self.screening_engine.run_full_market_screening()
        
        # 3. 排版報表
        report_text = format_telegram_report(results)
        print("\n" + "=" * 50)
        print(report_text)
        print("=" * 50 + "\n")
        
        # 4. 發送 Telegram
        self.send_telegram_direct(report_text)
        
        # 5. 釋放 WAL
        self.execute_wal_checkpoint()
        logger.info("🏁 [WayneBot] GitHub Actions 批次任務順利完成，安全退出。")
        sys.exit(0)

    async def handle_health_check(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "online",
            "service": "WayneBot Master System (Phase 10)",
            "timestamp": datetime.now().isoformat(),
            "db_status": "connected" if os.path.exists(self.db_path) else "pending"
        })

    async def handle_manual_screen(self, request: web.Request) -> web.Response:
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

    async def run_telegram_worker(self):
        logger.info("🤖 [Telegram] Bot 常駐工作元已上線運作。")
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
        logger.info("✅ [Telegram] Telegram 工作元已安全退出。")

    async def run_daily_scheduler(self):
        logger.info("⏰ [Scheduler] 每日 16:30 自動化增量排程器已啟動。")
        last_executed_date = None

        while not self.shutdown_event.is_set():
            try:
                # 採用台北時間計算
                try:
                    from zoneinfo import ZoneInfo
                    now = datetime.now(ZoneInfo("Asia/Taipei"))
                except Exception:
                    now = datetime.utcnow() + timedelta(hours=8)

                target_time = time(16, 30, 0)
                current_time = now.time()
                today_str = now.strftime("%Y-%m-%d")

                if current_time >= target_time and last_executed_date != today_str:
                    logger.info("🎯 [Scheduler] 觸發 16:30 盤後官方增量更新與 CaryBot 海選運算...")
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self.sync_market_data_if_needed)
                    results = await loop.run_in_executor(None, self.screening_engine.run_full_market_screening)
                    report = format_telegram_report(results)
                    self.send_telegram_direct(report)
                    last_executed_date = today_str

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ [Scheduler] 排程運算異常: {e}")
                await asyncio.sleep(60)

        logger.info("✅ [Scheduler] 排程器已安全退出。")

    async def run_forever(self):
        logger.info("⚡ [WayneBot Phase 10] 全系統核心調度啟動中... (24H 常駐模式)")

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

    if os.getenv("GITHUB_ACTIONS") == "true" or "--once" in sys.argv or "--batch" in sys.argv:
        runner.run_github_actions_batch()
        return

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
