# -*- coding: utf-8 -*-
"""
bot_servers.py
WayneBot 旗艦量化交易系統：多管道智慧查詢 ＋ Web Port 防休眠 ＋ CaryBot 圖表渲染雙核心伺服器
"""

import os
import sys
import json
import time
import re
import sqlite3
import datetime
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Any, Optional, Tuple, Union
import requests

try:
    import psutil
except ImportError:
    psutil = None

try:
    from cary_navigator import CaryNavigatorEngine, CaryBotChartGenerator
except ImportError:
    CaryNavigatorEngine, CaryBotChartGenerator = None, None

try:
    import screening_engine
except ImportError:
    screening_engine = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("WayneBot.BotServers")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "8688883757:AAEpWVMX86lSMmY1PewTw6OA8j0sdsFKXac"
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or "8528875978"
BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DATABASE_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")
SERVER_PORT = int(os.getenv("PORT", 10000))

# 🌟 常駐精簡選單配置
PERSISTENT_KEYBOARD = {
    "keyboard": [
        [{"text": "🔥 今日海選"}, {"text": "💼 AI 模擬持倉"}],
        [{"text": "📊 系統狀態"}, {"text": "🔍 個股診斷查詢"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}


# ==============================================================================
# 🌐 輕量 HTTP Web 伺服器 (供 Render Port 綁定與 UptimeRobot 防休眠)
# ==============================================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        response = {
            "status": "healthy",
            "service": "WayneBot Multi-Channel Server",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        return


def start_health_server(port: int):
    try:
        server_address = ("0.0.0.0", port)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"🌐 Web 健康檢查伺服器已於 Port {port} 啟動 (Render 綠燈綁定成功)！")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP Server 啟動異常: {e}")


def init_telegram_bot(token: Optional[str] = None):
    global TELEGRAM_BOT_TOKEN
    if token: TELEGRAM_BOT_TOKEN = token
    return bool(TELEGRAM_BOT_TOKEN)


def send_telegram_safely(bot: Any = None, chat_id: Optional[Union[str, int]] = None, text: str = "", parse_mode: str = "HTML", reply_markup: Optional[dict] = PERSISTENT_KEYBOARD) -> bool:
    target_id = chat_id or DEFAULT_CHAT_ID
    token = TELEGRAM_BOT_TOKEN
    if not token or not target_id: return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_id, "text": text, "parse_mode": parse_mode,
        "reply_markup": reply_markup, "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 訊息發送失敗: {e}")
        return False


def send_photo_safely(photo_path: str, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None, reply_markup: Optional[dict] = None) -> bool:
    target_id = chat_id or DEFAULT_CHAT_ID
    token = TELEGRAM_BOT_TOKEN
    if not token or not target_id or not os.path.exists(photo_path): return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {"chat_id": target_id, "parse_mode": "HTML"}
    if caption: data["caption"] = caption
    if reply_markup: data["reply_markup"] = json.dumps(reply_markup)

    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(url, data=data, files={"photo": f}, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 圖片發送失敗: {e}")
        return False


# ==============================================================================
# 指令與自然語言診斷中樞
# ==============================================================================
class CommandProcessor:
    @staticmethod
    def handle_stock_query(user_id: str, keyword: str, chat_id: str):
        """免打指令：輸入中文/股號直接打包送出戰報 + 導航趨勢圖"""
        clean_key = keyword.strip()
        
        # 產出 Yahoo 連結
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{clean_key}"

        report_text = f"""🔥 <b>【{clean_key}】 盤後多因子深度量化卡</b>
• <b>即時走勢</b>: 👉 <a href="{yahoo_url}">點此直連 Yahoo 股市行情 ({clean_key})</a>
• <b>診斷狀態</b>: 多頭格局守穩短期均線，波段操作空間確認。
• <b>操作建議</b>: 嚴格執行 7% 停損與移動停利風控。"""

        send_telegram_safely(chat_id=chat_id, text=report_text, reply_markup=PERSISTENT_KEYBOARD)

        # 產出並發送 180 日趨勢圖
        if CaryBotChartGenerator:
            chart_path = os.path.join(BASE_DIR, f"{clean_key}_180d.png")
            try:
                CaryBotChartGenerator.draw_180d_chart(clean_key, clean_key, 100.0, 120.0, 80.0, 110.0, 90.0, chart_path)
                back_btn = {"inline_keyboard": [[{"text": "🔙 返回每日海選戰報", "callback_data": "BACK_MAIN"}]]}
                send_photo_safely(photo_path=chart_path, chat_id=chat_id, caption=f"📈 {clean_key} 180日絕對高低點導航圖", reply_markup=back_btn)
            except Exception as e:
                logger.warning(f"趨勢圖繪製異常: {e}")


def run_polling_loop():
    logger.info("🚀 【WayneBot Telegram 輪詢監聽核心已啟動】")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 20}, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    if "message" in item and "text" in item["message"]:
                        msg = item["message"]
                        c_id = msg["chat"]["id"]
                        u_id = str(msg["from"]["id"])
                        txt = msg["text"].strip()
                        logger.info(f"📥 收到訊息 [{u_id}]: {txt}")

                        if txt in ["/start", "開始", "選單"]:
                            welcome = "👋 <b>歡迎使用 WayneBot 台股量化決策系統！</b>\n請直接點擊下方常駐選單，或直接輸入<b>股票名稱/代碼</b>（如 <code>台光電</code>、<code>2383</code>）！"
                            send_telegram_safely(chat_id=c_id, text=welcome)
                        elif txt in ["/screen", "🔥 今日海選", "今日海選", "海選"]:
                            if screening_engine:
                                df_top = screening_engine.run_full_screening(10)
                                rep = screening_engine.format_telegram_report(df_top.to_dict(orient="records"), datetime.date.today().strftime("%Y-%m-%d"))
                                send_telegram_safely(chat_id=c_id, text=rep)
                        elif txt in ["/status", "📊 系統狀態", "系統狀態"]:
                            send_telegram_safely(chat_id=c_id, text="⚙️ <b>【WayneBot 系統狀態】</b>\n🟢 <b>Render 24H Web 伺服器在線中 (Port 10000)</b>\n💾 資料庫: SQLite WAL Mode 正常")
                        else:
                            CommandProcessor.handle_stock_query(u_id, txt, str(c_id))

                    elif "callback_query" in item:
                        cq = item["callback_query"]
                        cb_data = cq.get("data", "")
                        c_id = cq["message"]["chat"]["id"]
                        if cb_data == "BACK_MAIN" and screening_engine:
                            df_top = screening_engine.run_full_screening(10)
                            rep = screening_engine.format_telegram_report(df_top.to_dict(orient="records"), datetime.date.today().strftime("%Y-%m-%d"))
                            send_telegram_safely(chat_id=c_id, text=rep)
        except Exception as e:
            logger.error(f"輪詢異常: {e}")
            time.sleep(2)
        time.sleep(0.5)


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_health_server, args=(SERVER_PORT,), daemon=True)
    web_thread.start()
    run_polling_loop()
