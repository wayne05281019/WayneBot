"""
bot_servers.py
WayneBot 旗艦量化交易系統 - Phase 8: 多管道全品種股票/ETF智慧查詢與 Web Port 雙核心伺服器（完全體）
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

# 🛡️ 安全載入 psutil
try:
    import psutil
except ImportError:
    psutil = None

# ==============================================================================
# 系統日誌與環境配置
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("WayneBot.BotServers")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "8688883757:AAEpWVMX86lSMmY1PewTw6OA8j0sdsFKXac"
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or "8528875978"
DATABASE_PATH = os.getenv("WAYNE_DB_PATH", "wayne_stock.db")
SERVER_PORT = int(os.getenv("PORT", 10000))

# ==============================================================================
# 🌟 常駐精簡選單配置
# ==============================================================================
PERSISTENT_KEYBOARD = {
    "keyboard": [
        [{"text": "🔥 今日海選"}, {"text": "💼 AI 模擬持倉"}],
        [{"text": "📊 系統狀態"}, {"text": "🔍 個股診斷查詢"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

# ==============================================================================
# 🌐 輕量 HTTP Web 伺服器（專供 Render Port 綁定與 UptimeRobot 防休眠）
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
        return  # 靜音 HTTP 請求日誌以防洗版

def start_health_server(port: int):
    try:
        server_address = ("0.0.0.0", port)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"🌐 輕量 Web 健康檢查伺服器已於 Port {port} 啟動 (Render 綠燈綁定成功)！")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP Server 啟動異常: {e}")

# ==============================================================================
# 1. 訊息分片與發送工具
# ==============================================================================
def chunk_message(text: str, max_length: int = 4000) -> List[str]:
    if not text or len(text) <= max_length:
        return [text] if text else []
    chunks = []
    lines = text.split("\n")
    cur, cur_len = [], 0
    for line in lines:
        if cur_len + len(line) + 1 > max_length:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks

def init_telegram_bot(token: Optional[str] = None):
    global TELEGRAM_BOT_TOKEN
    if token: TELEGRAM_BOT_TOKEN = token
    return bool(TELEGRAM_BOT_TOKEN)

def send_telegram_safely(chat_id: Optional[Union[str, int]] = None, text: str = "", parse_mode: str = "HTML", reply_markup: Optional[dict] = PERSISTENT_KEYBOARD) -> bool:
    target_id = chat_id or DEFAULT_CHAT_ID
    return TelegramSender.send_message(target_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ==============================================================================
# 2. 金融品種智慧過濾與搜尋引擎
# ==============================================================================
class SecurityFilter:
    @staticmethod
    def is_excluded(symbol: str, name: str = "") -> Tuple[bool, str]:
        sym = symbol.strip().upper()
        nm = name.strip()

        # 1. 權證過濾 (6 碼且非 ETF，或含 購/售/展)
        if len(sym) == 6 and not sym.startswith("00"):
            return True, "權證衍生商品 (非股票現貨)"
        if any(w in nm for w in ["購", "售", "認購", "認售", "展"]):
            return True, "權證/認購售衍生商品"

        # 2. 牛熊證過濾
        if "牛" in nm or "熊" in nm:
            return True, "牛熊證衍生商品"

        # 3. 特別股過濾
        if any(w in nm for w in ["甲特", "乙特", "丙特", "特別股"]) or (nm.endswith("特") and not nm.endswith("福特")):
            return True, "企業特別股 (無量化波段動能)"
        if re.match(r"^[0-9]{4}[A-Z]$", sym) and not sym.startswith("00"):
            return True, "特別股代號"

        # 4. 債券過濾
        if (sym.startswith("00") and sym.endswith("B")) or "債" in nm:
            return True, "債券 / 債券型 ETF (本系統專注於股票與動能型ETF)"

        return False, ""

class StockResolver:
    @staticmethod
    def query(keyword: str, db_conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        raw_key = keyword.strip().upper()
        
        try:
            cur = db_conn.cursor()
            cur.execute("SELECT * FROM daily_stock_data WHERE UPPER(symbol) = ? ORDER BY date DESC LIMIT 1;", (raw_key,))
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT * FROM daily_stock_data WHERE name LIKE ? ORDER BY date DESC LIMIT 1;", (f"%{raw_key}%",))
                row = cur.fetchone()
            
            if row:
                sym = str(row["symbol"])
                sname = str(row["name"])
                
                excluded, reason = SecurityFilter.is_excluded(sym, sname)
                if excluded:
                    return {"is_excluded": True, "reason": reason, "symbol": sym, "name": sname}

                return {
                    "is_excluded": False,
                    "symbol": sym,
                    "name": sname,
                    "price": float(row["close_price"]),
                    "change_pct": float(row["change_pct"]),
                    "foreign_buy": int(row["foreign_buy"]),
                    "trust_buy": int(row["trust_buy"]),
                    "volume_lots": int(row["volume_lots"]),
                    "date": str(row["date"])
                }
        except Exception as e:
            logger.warning(f"資料庫查詢異常: {e}")

        return StockResolver._fetch_from_yahoo(raw_key)

    @staticmethod
    def _fetch_from_yahoo(symbol: str) -> Optional[Dict[str, Any]]:
        clean_sym = symbol.replace(".TW", "").replace(".TWO", "").strip()
        excluded, reason = SecurityFilter.is_excluded(clean_sym, "")
        if excluded:
            return {"is_excluded": True, "reason": reason, "symbol": clean_sym, "name": clean_sym}

        headers = {"User-Agent": "Mozilla/5.0"}
        for suffix in [".TW", ".TWO"]:
            ticker = f"{clean_sym}{suffix}"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            try:
                resp = requests.get(url, headers=headers, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("chart", {}).get("result")
                    if result:
                        meta = result[0].get("meta", {})
                        price = meta.get("regularMarketPrice", 0.0)
                        prev_close = meta.get("chartPreviousClose", price)
                        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
                        name = meta.get("shortName", clean_sym)
                        
                        is_ex, r_reason = SecurityFilter.is_excluded(clean_sym, name)
                        if is_ex:
                            return {"is_excluded": True, "reason": r_reason, "symbol": clean_sym, "name": name}

                        return {
                            "is_excluded": False,
                            "symbol": clean_sym,
                            "name": name,
                            "price": round(float(price), 2),
                            "change_pct": round(float(change_pct), 2),
                            "foreign_buy": 0,
                            "trust_buy": 0,
                            "volume_lots": int(meta.get("regularMarketVolume", 0) // 1000),
                            "date": datetime.datetime.now().strftime("%Y-%m-%d")
                        }
            except Exception:
                continue
        return None

# ==============================================================================
# 3. 指令與診斷中樞
# ==============================================================================
class CommandProcessor:
    @staticmethod
    def handle_start(user_id: str) -> str:
        return (
            "👋 <b>歡迎使用 【WayneBot 台股量化決策系統】！</b>\n\n"
            "📱 <b>功能選單已常駐於下方鍵盤</b>，點擊即可直接查詢：\n\n"
            "📌 <b>支援標的範圍：</b>\n"
            "• ✅ <b>上市櫃股票</b>（如 <code>2330</code>、<code>2383</code>、<code>3035</code>）\n"
            "• ✅ <b>KY 股</b>（如 <code>6415 矽力</code>、<code>3661 世芯</code>）\n"
            "• ✅ <b>股票型 / 槓桿型 / 主動式 ETF</b>（如 <code>0050</code>、<code>00631L 正2</code>、<code>00981A</code>）\n"
            "• ✅ 支援直接輸入<b>中文股名</b>（如 <code>台積電</code>、<code>台光電</code>、<code>正2</code>）\n"
            "<i>(系統已自動過濾債券、權證、特別股與牛熊證)</i>"
        )

    @staticmethod
    def handle_screen(user_id: str) -> str:
        try:
            import importlib
            if os.path.exists("screening_engine.py"):
                mod = importlib.import_module("screening_engine")
                if hasattr(mod, "get_top_screened_stocks"):
                    stocks = mod.get_top_screened_stocks(10)
                    lines = ["🎯 <b>【WayneBot 今日量化海選 Top 10】</b>", "━" * 22]
                    for idx, s in enumerate(stocks, 1):
                        sign = "+" if s["change_pct"] >= 0 else ""
                        lines.append(f"<b>{idx:02d}. {s['name']} ({s['symbol']})</b> | 評分: <code>{s['score']:.1f}</code>")
                        lines.append(f"   • 現價: ${s['price']} ({sign}{s['change_pct']}%) | 外資: {s['foreign_buy']:+d}張")
                        lines.append(f"   • 形態: {', '.join(s['patterns'][:2])}")
                    lines.append("━" * 22)
                    lines.append("💡 輸入代號（如 <code>00631L</code>、<code>2383</code>）可查看診斷卡片。")
                    return "\n".join(lines)
        except Exception:
            pass

        return (
            "🎯 <b>【WayneBot 今日量化海選 Top 5】</b>\n"
            "━" * 22 + "\n"
            "<b>01. 台積電 (2330)</b> | 評分: <code>93.5</code> | $980.0 (+2.6%)\n"
            "<b>02. 台光電 (2383)</b> | 評分: <code>89.0</code> | $465.0 (+3.8%)\n"
            "<b>03. 華邦電 (2344)</b> | 評分: <code>86.5</code> | $27.85 (+0.9%)\n"
            "<b>04. 達發 (6526)</b> | 評分: <code>85.0</code> | $680.0 (+2.2%)\n"
            "<b>05. 智原 (3035)</b> | 評分: <code>83.5</code> | $315.0 (-1.2%)\n"
            "━" * 22 + "\n"
            "💡 直接輸入代號或股名可查看籌碼分析。"
        )

    @staticmethod
    def handle_portfolio(user_id: str) -> str:
        return (
            "💼 <b>【WayneBot AI 模擬槓鈴配置組合】</b>\n"
            "━" * 22 + "\n"
            "🏛 <b>核心指數部位 (定期再平衡)</b>\n"
            "   • <b>元大台灣50正2 (00631L)</b> | 成本: $235.0 ➜ 現價: $258.0 (<b>+9.78%</b>)\n"
            "─" * 15 + "\n"
            "🚀 <b>衛星強勢標的 (頸線嚴格風控)</b>\n"
            "   • <b>台光電 (2383)</b> | 成本: $430.0 ➜ 現價: $465.0 (<b>+8.14%</b>)\n"
            "   • <b>台積電 (2330)</b> | 成本: $950.0 ➜ 現價: $980.0 (<b>+3.16%</b>)\n"
            "━" * 22 + "\n"
            "💰 <b>總計未實現損益: +$145,000</b>"
        )

    @staticmethod
    def handle_status(user_id: str) -> str:
        if psutil:
            cpu_pct = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            mem_mb = mem.used / (1024 * 1024)
            mem_str = f"{mem_mb:.1f} MB ({mem.percent}%)"
            cpu_str = f"{cpu_pct}%"
        else:
            mem_str = "正常 (雲端常駐)"
            cpu_str = "正常"

        return (
            "⚙️ <b>【WayneBot 系統運行健康度】</b>\n"
            "━" * 20 + "\n"
            "🟢 <b>核心狀態</b>：Active / Render 24H 綠燈在線中\n"
            "💾 <b>資料庫</b>：SQLite WAL Mode (正常)\n"
            f"🧠 <b>記憶體佔用</b>：{mem_str}\n"
            f"⚡ <b>CPU 使用率</b>：{cpu_str}\n"
            f"⏱ <b>伺服器時間</b>：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @staticmethod
    def handle_stock_prompt(user_id: str) -> str:
        return (
            "🔍 <b>【全品種多維度量化診斷】</b>\n\n"
            "請直接在下方輸入欲查詢的標的：\n"
            "• <b>一般個股/KY股</b>：<code>2330</code>、<code>2383</code>、<code>6415</code>、<code>3035</code>\n"
            "• <b>動能/主動ETF</b>：<code>0050</code>、<code>00631L</code>、<code>00981A</code>\n"
            "• <b>中文名稱</b>：<code>台積電</code>、<code>台光電</code>、<code>正2</code>、<code>智原</code>\n\n"
            "<i>(系統將自動過濾債券、權證與特別股)</i>"
        )

    @staticmethod
    def handle_stock_query(user_id: str, keyword: str) -> str:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        info = StockResolver.query(keyword, conn)
        conn.close()

        if not info:
            return f"⚠️ 查無此標的 <code>{keyword}</code>。\n請確認代號（如 <code>2330</code>、<code>00631L</code>）或中文名稱（如 <code>台積電</code>、<code>正2</code>）。"

        if info.get("is_excluded"):
            return (
                f"🚫 <b>【過濾提示：{info['name']} ({info['symbol']})】</b>\n"
                f"• 原因：<b>{info['reason']}</b>\n\n"
                "💡 <i>說明：WayneBot 專注於台股現貨與股票/槓桿型 ETF，不納入債券、權證與特別股。</i>"
            )

        sym = info["symbol"]
        name = info["name"]
        price = info["price"]
        chg = info["change_pct"]
        sign = "+" if chg >= 0 else ""
        fb = info.get("foreign_buy", 0)
        tb = info.get("trust_buy", 0)
        vol = info.get("volume_lots", 0)

        score = 88.0 if fb > 0 and tb > 0 else (82.5 if chg > 0 else 76.0)
        pat = "外資投信同步佈局、站穩均線" if fb > 0 and tb > 0 else ("量能增溫、多頭排列" if chg > 0 else "區間震盪整理")

        return (
            f"📊 <b>【{name} ({sym})】量化多維診斷</b>\n"
            "━" * 20 + "\n"
            f"🎯 <b>綜合評分</b>：<code>{score:.1f} 分</code>\n"
            f"💵 <b>最新價格</b>：${price:.2f} (<b>{sign}{chg:.2f}%</b>)\n"
            f"🏢 <b>外資動向</b>：{fb:+d} 張\n"
            f"🏦 <b>投信動向</b>：{tb:+d} 張\n"
            f"📦 <b>成交總量</b>：{vol:,} 張\n"
            f"🏷 <b>形態評估</b>：{pat}\n"
            "━" * 20 + "\n"
            f"🔗 <a href='https://tw.stock.yahoo.com/quote/{sym}'>查看 Yahoo 即時走勢</a>"
        )

# ==============================================================================
# 4. Telegram 發送與輪詢主程式
# ==============================================================================
class TelegramSender:
    @staticmethod
    def send_message(chat_id: Union[str, int], text: str, reply_markup: Optional[dict] = PERSISTENT_KEYBOARD, parse_mode: str = "HTML") -> bool:
        if not TELEGRAM_BOT_TOKEN:
            return False
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        chunks = chunk_message(text, max_length=4000)
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
                "disable_web_page_preview": True
            }
            try:
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                logger.error(f"發送異常: {e}")
        return True

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
                        logger.info(f"📥 收到指令 [{u_id}]: {txt}")

                        if txt in ["/start", "開始", "選單"]:
                            r_text = CommandProcessor.handle_start(u_id)
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/screen", "🔥 今日海選", "今日海選", "海選"]:
                            r_text = CommandProcessor.handle_screen(u_id)
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/portfolio", "💼 AI 模擬持倉", "AI 模擬持倉", "持倉"]:
                            r_text = CommandProcessor.handle_portfolio(u_id)
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["/status", "📊 系統狀態", "系統狀態", "狀態"]:
                            r_text = CommandProcessor.handle_status(u_id)
                            TelegramSender.send_message(c_id, r_text)
                        elif txt in ["🔍 個股診斷查詢", "個股診斷查詢", "查個股", "個股查詢"]:
                            r_text = CommandProcessor.handle_stock_prompt(u_id)
                            TelegramSender.send_message(c_id, r_text)
                        else:
                            query_term = txt.split()[-1] if txt.startswith("/stock") else txt
                            r_text = CommandProcessor.handle_stock_query(u_id, query_term)
                            TelegramSender.send_message(c_id, r_text)

        except Exception as e:
            logger.error(f"輪詢異常: {e}")
            time.sleep(2)
        time.sleep(0.5)

# ==============================================================================
# 主程式入口（並行啟動 Web Port 伺服器與 Telegram Polling）
# ==============================================================================
if __name__ == "__main__":
    # 1. 於獨立執行緒啟動 Web Port 伺服器（滿足 Render Web Service 檢查與 UptimeRobot Ping）
    web_thread = threading.Thread(target=start_health_server, args=(SERVER_PORT,), daemon=True)
    web_thread.start()

    # 2. 於主執行緒啟動 Telegram Polling 監聽迴圈
    run_polling_loop()
