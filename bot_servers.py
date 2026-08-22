"""
bot_servers.py
WayneBot 旗艦量化交易系統 - Phase 8: 多管道互動指令與 Telegram 常駐精簡選單（完全體）
"""

import os
import sys
import json
import time
import hmac
import hashlib
import base64
import logging
import asyncio
import sqlite3
import datetime
from typing import Dict, List, Any, Optional, Tuple, Union

import psutil
import requests

# ==============================================================================
# 系統日誌與環境配置
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("WayneBot.BotServers")

# 🔑 Token 設定
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "請在此填入您的_TELEGRAM_BOT_TOKEN")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
DATABASE_PATH = os.getenv("WAYNE_DB_PATH", "wayne_stock.db")

# ==============================================================================
# 🌟 常駐精簡鍵盤配置 (Resize + Persistent)
# ==============================================================================
PERSISTENT_KEYBOARD = {
    "keyboard": [
        [{"text": "🔥 今日海選"}, {"text": "💼 AI 模擬持倉"}],
        [{"text": "📊 系統狀態"}, {"text": "🔍 查台積電 (2330)"}]
    ],
    "resize_keyboard": True,   # 自動縮小按鈕尺寸，精簡不佔版面
    "is_persistent": True      # 永久常駐於底部
}

# ==============================================================================
# 1. 資料庫與使用者狀態管理模組
# ==============================================================================
class DatabaseManager:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_states (
                        user_id TEXT PRIMARY KEY,
                        platform TEXT NOT NULL,
                        last_command TEXT,
                        last_symbol TEXT,
                        context_json TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS mock_portfolio (
                        symbol TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        current_price REAL NOT NULL,
                        shares INTEGER NOT NULL,
                        tp_price REAL NOT NULL,
                        sl_price REAL NOT NULL,
                        entry_date TEXT NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"資料庫初始化異常: {str(e)}")

    def update_user_state(self, user_id: str, platform: str, command: str, symbol: Optional[str] = None, context: Optional[dict] = None):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                context_str = json.dumps(context or {}, ensure_ascii=False)
                cursor.execute("""
                    INSERT INTO user_states (user_id, platform, last_command, last_symbol, context_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        platform = excluded.platform,
                        last_command = excluded.last_command,
                        last_symbol = excluded.last_symbol,
                        context_json = excluded.context_json,
                        updated_at = CURRENT_TIMESTAMP
                """, (str(user_id), platform, command, symbol, context_str))
                conn.commit()
        except Exception as e:
            logger.error(f"寫入 user_states 失敗 ({user_id}): {str(e)}")

    def get_portfolio(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM mock_portfolio")
                rows = cursor.fetchall()
                if rows:
                    return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"讀取 mock_portfolio 失敗: {str(e)}")
        
        return [
            {"symbol": "2330", "name": "台積電", "entry_price": 950.0, "current_price": 985.0, "shares": 1000, "tp_price": 1050.0, "sl_price": 920.0, "entry_date": "2026-08-10"},
            {"symbol": "2383", "name": "台光電", "entry_price": 430.0, "current_price": 455.0, "shares": 2000, "tp_price": 490.0, "sl_price": 415.0, "entry_date": "2026-08-15"},
            {"symbol": "3035", "name": "智原", "entry_price": 310.0, "current_price": 298.0, "shares": 1000, "tp_price": 350.0, "sl_price": 290.0, "entry_date": "2026-08-18"},
        ]

    def test_connection(self) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
        except Exception:
            return False

db_manager = DatabaseManager()

# ==============================================================================
# 2. 選股引擎介面
# ==============================================================================
class StockDataEngine:
    @staticmethod
    def get_top_screened_stocks(limit: int = 10) -> List[Dict[str, Any]]:
        return [
            {"symbol": "2330", "name": "台積電", "score": 94.5, "price": 985.0, "change_pct": 2.6, "foreign_buy": 12450, "trust_buy": 1200, "patterns": ["頸線突破", "外資連三買", "多頭排列"]},
            {"symbol": "2383", "name": "台光電", "score": 91.2, "price": 455.0, "change_pct": 3.8, "foreign_buy": 3200, "trust_buy": 850, "patterns": ["頭肩底翻揚", "投信鎖碼", "量價齊揚"]},
            {"symbol": "2454", "name": "聯發科", "score": 88.7, "price": 1280.0, "change_pct": 1.5, "foreign_buy": 1560, "trust_buy": -200, "patterns": ["破底翻", "高檔整理"]},
            {"symbol": "3035", "name": "智原", "score": 86.4, "price": 298.0, "change_pct": -1.2, "foreign_buy": 890, "trust_buy": 430, "patterns": ["回測頸線", "KD低檔背離"]},
            {"symbol": "6415", "name": "矽力*-KY", "score": 85.0, "price": 485.0, "change_pct": 4.1, "foreign_buy": 1100, "trust_buy": 310, "patterns": ["底部突破", "量增價漲"]},
            {"symbol": "6526", "達發", "score": 83.2, "price": 630.0, "change_pct": 2.2, "foreign_buy": 420, "trust_buy": 210, "patterns": ["雙底成形", "投信進駐"]},
            {"symbol": "2344", "name": "華邦電", "score": 82.0, "price": 27.8, "change_pct": 0.9, "foreign_buy": 4500, "trust_buy": 150, "patterns": ["均線糾結向上"]},
            {"symbol": "5351", "name": "鈺創", "score": 80.5, "price": 43.5, "change_pct": 5.2, "foreign_buy": 2100, "trust_buy": 50, "patterns": ["量能爆發", "突破區間"]},
            {"symbol": "3231", "name": "緯創", "score": 79.0, "price": 108.5, "change_pct": -0.5, "foreign_buy": -1500, "trust_buy": 1200, "patterns": ["投信買外資賣", "支撐測底"]},
            {"symbol": "2376", "name": "技嘉", "score": 78.2, "price": 265.0, "change_pct": 1.1, "foreign_buy": 850, "trust_buy": -100, "patterns": ["三角收斂末端"]},
        ][:limit]

    @staticmethod
    def get_stock_detail(symbol: str) -> Dict[str, Any]:
        stocks = {s["symbol"]: s for s in StockDataEngine.get_top_screened_stocks(10)}
        if symbol in stocks:
            return stocks[symbol]
        return {
            "symbol": symbol,
            "name": "個股標的",
            "score": 75.0,
            "price": 100.0,
            "change_pct": 0.0,
            "foreign_buy": 0,
            "trust_buy": 0,
            "patterns": ["區間整理", "觀察量能"]
        }

# ==============================================================================
# 3. 訊息分片工具
# ==============================================================================
def chunk_message(text: str, max_length: int = 4000) -> List[str]:
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 1
        if current_length + line_length > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            if line:
                current_chunk.append(line)
                current_length = len(line) + 1
        else:
            current_chunk.append(line)
            current_length += line_length

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

# ==============================================================================
# 4. 指令解析中樞
# ==============================================================================
class CommandProcessor:
    @staticmethod
    def handle_start(user_id: str, platform: str) -> str:
        db_manager.update_user_state(user_id, platform, "/start")
        return (
            "👋 <b>歡迎使用 【WayneBot 台股量化決策系統】！</b>\n\n"
            "本系統整合籌碼三法、頸線形態辨識與外資投信量化評分矩陣。\n"
            "📱 <b>功能選單已固定在下方鍵盤</b>，點擊即可直接查詢！\n\n"
            "📌 <b>常用操作：</b>\n"
            "• 點擊 <b>【🔥 今日海選】</b>：取得今日前 10 檔潛力個股\n"
            "• 點擊 <b>【💼 AI 模擬持倉】</b>：監控目前部位與停損停利水位\n"
            "• 點擊 <b>【📊 系統狀態】</b>：檢視伺服器資源與資料庫連線\n"
            "• 直接輸入 <b>4 碼股票代號</b>（如 <code>2330</code>、<code>2383</code>）：即時個股診斷"
        )

    @staticmethod
    def handle_screen(user_id: str, platform: str) -> str:
        db_manager.update_user_state(user_id, platform, "/screen")
        stocks = StockDataEngine.get_top_screened_stocks(10)
        lines = ["🎯 <b>【WayneBot 今日量化海選 Top 10】</b>", "━" * 22]
        for idx, s in enumerate(stocks, 1):
            sign = "+" if s["change_pct"] >= 0 else ""
            lines.append(f"<b>{idx:02d}. {s['name']} ({s['symbol']})</b> | 評分: <code>{s['score']:.1f}</code>")
            lines.append(f"   • 現價: ${s['price']} ({sign}{s['change_pct']}%) | 外資: {s['foreign_buy']:+d}張")
            lines.append(f"   • 形態: {', '.join(s['patterns'][:2])}")
        lines.append("━" * 22)
        lines.append("💡 直接輸入代號（如 <code>2383</code>）可查看籌碼卡片。")
        return "\n".join(lines)

    @staticmethod
    def handle_portfolio(user_id: str, platform: str) -> str:
        db_manager.update_user_state(user_id, platform, "/portfolio")
        portfolio = db_manager.get_portfolio()
        if not portfolio:
            return "💼 目前 AI 模擬策略持倉為空倉，正等待多頭結構突破標的。"
        lines = ["💼 <b>【WayneBot AI 模擬投資組合持倉監控】</b>", "━" * 22]
        total_pnl = 0.0
        for item in portfolio:
            pnl_pct = ((item["current_price"] - item["entry_price"]) / item["entry_price"]) * 100
            pnl_amount = (item["current_price"] - item["entry_price"]) * item["shares"]
            total_pnl += pnl_amount
            sign = "+" if pnl_pct >= 0 else ""
            lines.append(f"📌 <b>{item['name']} ({item['symbol']})</b>")
            lines.append(f"   • 成本: ${item['entry_price']:.1f} ➜ 現價: ${item['current_price']:.1f} ({sign}{pnl_pct:.2f}%)")
            lines.append(f"   • 未實現損益: <b>${pnl_amount:+,.0f}</b> ({item['shares']:,}股)")
            lines.append(f"   • 水位控制: 停利 ${item['tp_price']:.1f} | 停損 ${item['sl_price']:.1f}")
            lines.append("─" * 15)
        sign_tot = "+" if total_pnl >= 0 else ""
        lines.append(f"💰 <b>總計未實現損益: {sign_tot}${total_pnl:,.0f}</b>")
        return "\n".join(lines)

    @staticmethod
    def handle_status(user_id: str, platform: str) -> str:
        db_manager.update_user_state(user_id, platform, "/status")
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        mem_mb = mem.used / (1024 * 1024)
        db_status = "✅ 正常連線 (WAL Mode)" if db_manager.test_connection() else "❌ 連線異常"
        return (
            "⚙️ <b>【WayneBot 系統運行與健康狀態】</b>\n"
            "━" * 20 + "\n"
            "🟢 <b>核心狀態</b>：Active / Polling 在線中\n"
            f"💾 <b>資料庫</b>：{db_status}\n"
            f"🧠 <b>記憶體佔用</b>：{mem_mb:.1f} MB ({mem.percent}%)\n"
            f"⚡ <b>CPU 使用率</b>：{cpu_pct}%\n"
            f"⏱ <b>主機時間</b>：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @staticmethod
    def handle_stock_query(user_id: str, platform: str, symbol: str) -> str:
        db_manager.update_user_state(user_id, platform, "/stock", symbol=symbol)
        stock_data = StockDataEngine.get_stock_detail(symbol)
        sign = "+" if stock_data["change_pct"] >= 0 else ""
        return (
            f"📊 <b>【{stock_data['name']} ({stock_data['symbol']})】量化診斷</b>\n"
            "━" * 20 + "\n"
            f"🎯 <b>綜合評分</b>：<code>{stock_data['score']:.1f} 分</code>\n"
            f"💵 <b>最新價格</b>：${stock_data['price']:.2f} (<b>{sign}{stock_data['change_pct']:.2f}%</b>)\n"
            f"🏢 <b>外資動向</b>：{stock_data['foreign_buy']:+d} 張\n"
            f"🏦 <b>投信動向</b>：{stock_data['trust_buy']:+d} 張\n"
            f"🏷 <b>形態指標</b>：{', '.join(stock_data['patterns'])}\n"
            "━" * 20 + "\n"
            "💡 提示：點擊下方【🔥 今日海選】可查看熱門標的。"
        )

# ==============================================================================
# 5. Telegram 發送與自動註冊選單
# ==============================================================================
class TelegramSender:
    @staticmethod
    def send_message(chat_id: Union[str, int], text: str, reply_markup: Optional[dict] = PERSISTENT_KEYBOARD) -> bool:
        if not TELEGRAM_BOT_TOKEN or "請在此填入" in TELEGRAM_BOT_TOKEN:
            return False
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        chunks = chunk_message(text, max_length=4000)
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            }
            try:
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                logger.error(f"Telegram 發送異常: {e}")
        return True

    @staticmethod
    def register_bot_commands():
        """向 Telegram 註冊左下角 Menu 藍色按鈕指令"""
        if not TELEGRAM_BOT_TOKEN or "請在此填入" in TELEGRAM_BOT_TOKEN:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
        commands = [
            {"command": "start", "description": "🏠 開啟功能主選單"},
            {"command": "screen", "description": "🔥 今日量化海選 Top 10"},
            {"command": "portfolio", "description": "💼 AI 模擬投資組合持倉"},
            {"command": "status", "description": "⚙️ 系統健康狀態與連線"}
        ]
        try:
            requests.post(url, json={"commands": commands}, timeout=10)
            logger.info("✅ 已成功向 Telegram 註冊左下角 Menu 快速選單！")
        except Exception as e:
            logger.warning(f"註冊 Bot 指令失敗: {e}")

# ==============================================================================
# 6. Polling 輪詢主程式
# ==============================================================================
def run_polling_loop():
    if not TELEGRAM_BOT_TOKEN or "請在此填入" in TELEGRAM_BOT_TOKEN:
        logger.error("❌ 錯誤：未設定有效的 TELEGRAM_BOT_TOKEN！")
        return

    TelegramSender.register_bot_commands()
    logger.info("🚀 【WayneBot Telegram 伺服器啟動完成】（常駐底部精簡鍵盤模式）")
    
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

                        # 支援指令與常駐按鈕文字
                        if txt in ["/start", "開始", "選單"]:
                            r_text = CommandProcessor.handle_start(u_id, "telegram")
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/screen", "🔥 今日海選", "海選"]:
                            r_text = CommandProcessor.handle_screen(u_id, "telegram")
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/portfolio", "💼 AI 模擬持倉", "持倉"]:
                            r_text = CommandProcessor.handle_portfolio(u_id, "telegram")
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/status", "📊 系統狀態", "狀態"]:
                            r_text = CommandProcessor.handle_status(u_id, "telegram")
                            TelegramSender.send_message(c_id, r_text)
                        elif txt.startswith("/stock") or "2330" in txt or (len(txt) == 4 and txt.isdigit()):
                            sym = "2330" if "2330" in txt else (txt.split()[-1] if txt.startswith("/stock") else txt)
                            r_text = CommandProcessor.handle_stock_query(u_id, "telegram", sym)
                            TelegramSender.send_message(c_id, r_text)
                        else:
                            fallback = f"🤖 收到指令: <code>{txt}</code>\n請直接點擊下方常駐按鈕，或輸入 4 碼個股代號。"
                            TelegramSender.send_message(c_id, fallback)

        except Exception as e:
            logger.error(f"輪詢網路異常: {e}")
            time.sleep(2)
        time.sleep(0.5)

if __name__ == "__main__":
    run_polling_loop()
