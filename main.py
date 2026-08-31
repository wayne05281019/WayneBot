"""
main.py - WayneBot 統一啟動入口

- Render / Docker 常駐：python main.py
  提供 :PORT/health，並啟動 Telegram 互動 Bot。
- 一次性盤後排程（GitHub Actions）：python main.py --once
"""

import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import (
    daily_scheduler_enabled,
    get_port,
    get_telegram_token,
    is_once_mode,
    skip_telegram_polling,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# httpx 預設 INFO 會把 Bot token 印在 getUpdates URL 裡
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("WayneBot")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            '{"status":"healthy","service":"WayneBot 24H Online","ok":true}'
        ).encode("utf-8")
        if self.path.split("?")[0] in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server(port: int) -> threading.Thread:
    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    def _run():
        logger.info("Health server 監聽 0.0.0.0:%s (/health)", port)
        server.serve_forever()

    t = threading.Thread(target=_run, name="health-http", daemon=True)
    t.start()
    return t


def _taipei_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        return datetime.now()


def _seconds_until_1630() -> float:
    now = _taipei_now()
    target = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return max(5.0, (target - now).total_seconds())


def start_daily_scheduler():
    def _loop():
        from main_runner import MainRunner
        while True:
            wait_s = _seconds_until_1630()
            logger.info("盤後排程執行緒：約 %.0f 秒後嘗試台灣時間 16:30 流水線", wait_s)
            time.sleep(wait_s)
            try:
                now = _taipei_now()
                if now.weekday() >= 5:
                    logger.info("週末略過盤後流水線")
                    continue
                MainRunner().run_pipeline(skip_if_done=True)
            except Exception as e:
                logger.error("內建盤後排程失敗: %s", e, exc_info=True)

    t = threading.Thread(target=_loop, name="daily-scheduler", daemon=True)
    t.start()
    return t


def ensure_market_db() -> None:
    """Render 磁碟沒有 Git 裡的 sqlite；沒有日K時打南亞不會出圖。"""
    import os
    import shutil
    import tempfile
    import zipfile
    import urllib.request

    from config import get_db_path, get_github_release_url

    path = get_db_path()
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            logger.info("行情庫已存在（%.0f MB）", os.path.getsize(path) / 1e6)
            return
    except OSError:
        pass
    url = get_github_release_url()
    logger.info("雲端尚無行情庫，開始下載公開 Release（可能要幾分鐘）")
    tmpdir = tempfile.mkdtemp(prefix="wayne-db-")
    zpath = os.path.join(tmpdir, "db.zip")
    try:
        urllib.request.urlretrieve(url, zpath)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmpdir)
        found = None
        for root, _, files in os.walk(tmpdir):
            for name in files:
                if name.endswith(".db"):
                    cand = os.path.join(root, name)
                    if found is None or os.path.getsize(cand) > os.path.getsize(found):
                        found = cand
        if not found:
            logger.warning("Release zip 內找不到 .db")
            return
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(found, path)
        logger.info("已安裝行情庫 %.0f MB", os.path.getsize(path) / 1e6)
    except Exception:
        logger.exception("下載行情庫失敗（Telegram 仍可回 /start，但單檔圖卡沒有日K）")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def run_once():
    from main_runner import main as runner_main
    runner_main()


def run_web():
    from wayne_db import ensure_core_schema
    from config import get_db_path, get_telegram_chat_id

    start_health_server(get_port())
    ensure_market_db()
    logger.info("檢查資料庫索引（大檔可能要一兩分鐘，請等 Telegram polling 啟動再打字）")
    ensure_core_schema(get_db_path())
    logger.info("資料庫索引完成")
    if daily_scheduler_enabled():
        start_daily_scheduler()

    token = get_telegram_token()
    if token and not skip_telegram_polling():
        logger.info("載入 Telegram 模組（尚未出圖，先開聽筒）")
        from bot_servers import WayneTelegramBot

        logger.info("正在啟動 Telegram 聽筒")
        bot = WayneTelegramBot(token=token, chat_id=get_telegram_chat_id(), db_path=get_db_path())

        def _warmup_charts():
            try:
                logger.info("背景預熱出圖模組")
                import cary_navigator  # noqa: F401
                logger.info("出圖模組已預熱")
            except Exception:
                logger.exception("出圖預熱失敗")

        threading.Thread(target=_warmup_charts, daemon=True, name="chart-warmup").start()
        bot.run_polling()
    elif token:
        logger.info("WAYNE_SKIP_POLLING：不搶 Render 的 Telegram 輪詢，僅保留寄訊與 /health")
        while True:
            time.sleep(3600)
    else:
        logger.warning("未設定 TELEGRAM_BOT_TOKEN，僅維持 /health 以通過 Render 健康檢查。")
        while True:
            time.sleep(3600)


def main():
    try:
        if is_once_mode():
            logger.info("執行模式：一次性盤後流水線 (--once / WAYNE_MODE=once)")
            run_once()
        else:
            logger.info("執行模式：常駐 Web + Telegram 互動（Render）")
            run_web()
    except KeyboardInterrupt:
        print("\n[WayneBot] 收到使用者中斷信號，安全退出。")
        sys.exit(0)


if __name__ == "__main__":
    main()
