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
        route = self.path.split("?")[0]
        if route in ("/", "/health"):
            body = (
                '{"status":"healthy","service":"WayneBot 24H Online","ok":true}'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route.startswith("/line"):
            from config import get_charts_dir, get_db_path
            from line_hop import hop_response, hop_stock_response, render_line_rich_share_html
            from line_rich_pack import load_latest_bucket_rich_manifest, resolve_rich_asset_path

            parts = [p for p in route.split("/") if p]
            if len(parts) >= 3 and parts[0] == "line" and parts[1] == "rich":
                bucket_key = parts[2]
                if len(parts) >= 5:
                    as_of = parts[3]
                    rel = "/".join(parts[4:])
                    asset = resolve_rich_asset_path(get_charts_dir(), bucket_key, as_of, rel)
                    if not asset:
                        self.send_response(404)
                        self.end_headers()
                        return
                    with open(asset, "rb") as f:
                        data = f.read()
                    ctype = "image/png" if asset.lower().endswith(".png") else "application/octet-stream"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                manifest = load_latest_bucket_rich_manifest(get_db_path(), bucket_key, get_charts_dir())
                if not manifest.get("line_text"):
                    body = "尚無圖文包，請回 Telegram 按「一鍵傳 LINE」生成。".encode("utf-8")
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                page = render_line_rich_share_html(manifest).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if len(parts) >= 3 and parts[0] == "line" and parts[1] == "stock":
                hop = hop_stock_response(get_db_path(), parts[2])
            else:
                pack_id = parts[1] if len(parts) > 1 else ""
                hop = hop_response(get_db_path(), pack_id)
                if not hop:
                    self.send_response(404)
                    self.end_headers()
                    return
            target = (hop or {}).get("redirect")
            text = str((hop or {}).get("text") or "").strip()
            if text:
                from line_hop import render_line_redirect_html

                page = render_line_redirect_html(text).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if target:
                from line_hop import render_line_redirect_html_for_url

                page = render_line_redirect_html_for_url(target).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            err = str((hop or {}).get("error") or "無法開啟 LINE")
            body = err.encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route in ("/inventory", "/db-status"):
            import json

            try:
                from config import get_db_path
                from import_health import inventory_payload

                payload = inventory_payload(get_db_path())
                payload["status"] = "inventory"
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8")
                self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server(port: int) -> threading.Thread:
    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    def _run():
        logger.info("Health server 監聽 0.0.0.0:%s (/health /inventory)", port)
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


def _seconds_until(hour: int, minute: int) -> float:
    now = _taipei_now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return max(5.0, (target - now).total_seconds())


def start_daily_scheduler():
    def _next_slot():
        from datetime import timedelta

        now = _taipei_now()
        slots = (
            (6, 30, "morning"),
            (12, 45, "midday"),
            (16, 30, "fuse"),
            (20, 0, "evening"),
        )
        best = None
        for day_off in range(0, 8):
            day = now + timedelta(days=day_off)
            if day.weekday() >= 5:
                continue
            for hour, minute, kind in slots:
                t = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if t <= now:
                    continue
                wait = (t - now).total_seconds()
                if best is None or wait < best[0]:
                    best = (max(5.0, wait), kind, t)
        return best

    def _catch_up_missed():
        """重啟若已過 06:30 而今早沒寄過，立刻補寄，避免再空窗。"""
        now = _taipei_now()
        if now.weekday() >= 5:
            return
        mins = now.hour * 60 + now.minute
        if mins < 6 * 60 + 30:
            return
        from main_runner import MainRunner

        logger.info("補跑：已過台灣 06:30，若今早海選沒寄過就補寄")
        MainRunner().run_morning_screen(skip_if_done=True)

    def _loop():
        from main_runner import MainRunner

        try:
            _catch_up_missed()
        except Exception:
            logger.exception("補跑今早海選失敗")

        while True:
            nxt = _next_slot()
            if not nxt:
                time.sleep(3600)
                continue
            wait, kind, when = nxt
            logger.info("排程：約 %.0f 秒後台灣 %s %s", wait, when.strftime("%m/%d %H:%M"), kind)
            time.sleep(wait)
            try:
                now = _taipei_now()
                if now.weekday() >= 5:
                    continue
                runner = MainRunner()
                if kind == "morning":
                    runner.run_morning_screen(skip_if_done=True)
                elif kind == "midday":
                    runner.run_midday_review(skip_if_done=True)
                elif kind == "evening":
                    runner.run_evening_screen(skip_if_done=True, notify=False)
                else:
                    runner.run_increment_job(skip_if_done=True)
            except Exception as e:
                logger.error("排程 %s 失敗: %s", kind, e, exc_info=True)

    t = threading.Thread(target=_loop, name="daily-scheduler", daemon=True)
    t.start()
    return t


def start_market_backfill():
    """Deploy 後 Release zip 可能缺最近交易日；背景 UPSERT 進現有 wayne_market.db。"""

    def _run():
        try:
            logger.info("啟動後融合官方日K／法人／財報（不推播）")
            from main_runner import MainRunner

            n = MainRunner().run_daily_increment(notify=False)
            logger.info("啟動後融合完成（當日檔數／回補 %s）", n)
        except Exception:
            logger.exception("啟動後融合失敗")

    t = threading.Thread(target=_run, name="market-fuse", daemon=True)
    t.start()
    return t


def ensure_market_db() -> None:
    """Render 磁碟沒有 Git 裡的 sqlite；沒有日K時打南亞不會出圖。損壞則從 Release 重建。"""
    import os
    import shutil
    import sqlite3
    import tempfile
    import zipfile
    import urllib.request

    from config import get_db_path, get_github_release_url
    from import_health import db_quick_check_ok

    path = get_db_path()
    try:
        if db_quick_check_ok(path):
            logger.info("行情庫已存在且通過 integrity（%.0f MB）", os.path.getsize(path) / 1e6)
            return
    except OSError:
        pass
    if os.path.isfile(path):
        corrupt = f"{path}.corrupt-{int(time.time())}"
        try:
            shutil.move(path, corrupt)
            logger.error("行情庫 quick_check 失敗，已搬至 %s，改從 Release 重建", corrupt)
        except OSError:
            logger.exception("搬移損壞行情庫失敗")
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
        logger.exception("下載行情庫失敗（Telegram 仍可回 /start，但單檔看這檔沒有日K）")
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
    try:
        from quote_integrity import ensure_quote_integrity

        stats = ensure_quote_integrity(get_db_path())
        if any(int(v or 0) for v in stats.values()):
            logger.info("啟動清假資料：%s", stats)
    except Exception:
        logger.debug("啟動清假略過", exc_info=True)
    logger.info("資料庫索引完成")
    start_market_backfill()
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
                logger.info("背景預熱出圖（字型＋南亞試畫，避免第一檔查詢空等）")
                from wayne_navigator import prewarm_card_fonts, render_stock_pack

                prewarm_card_fonts()
                pack = render_stock_pack("1303", get_db_path())
                logger.info(
                    "出圖預熱完成 glance=%s card=%s chart=%s chips=%s",
                    bool(pack.get("glance")),
                    bool(pack.get("card")),
                    bool(pack.get("chart")),
                    bool(pack.get("chips")),
                )
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
            from config import job_kind

            logger.info("執行模式：一次性工作 %s", job_kind())
            run_once()
        else:
            logger.info("執行模式：常駐 Web + Telegram 互動（Render）")
            run_web()
    except KeyboardInterrupt:
        print("\n[WayneBot] 收到使用者中斷信號，安全退出。")
        sys.exit(0)


if __name__ == "__main__":
    main()
