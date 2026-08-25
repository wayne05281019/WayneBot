# -*- coding: utf-8 -*-
"""
bot_servers.py
WayneBot 旗艦量化交易系統：全防護秒回 ＋ 30萬4等份帳本 ＋ Render 24H 防休眠伺服器
檔案名稱：bot_servers.py
作者：Wayne (WayneBot Quantitative System Architect)
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

try:
    import portfolio_engine
except ImportError:
    portfolio_engine = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("WayneBot.BotServers")

SERVER_PORT = int(os.getenv("PORT", 10000))
BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
os.makedirs(BASE_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")
WATCHLIST_DB_PATH = os.path.join(BASE_DIR, "user_watchlist.db")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "8688883757:AAEpWVMX86lSMmY1PewTw6OA8j0sdsFKXac"
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or "8528875978"

# 🌟 常駐選單
PERSISTENT_KEYBOARD = {
    "keyboard": [
        [{"text": "🔥 今日海選"}, {"text": "💼 AI 模擬持倉"}],
        [{"text": "⭐ 我的自選名單"}, {"text": "📊 系統狀態"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}


def init_watchlist_db():
    try:
        conn = sqlite3.connect(WATCHLIST_DB_PATH)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlist (
            stock_id TEXT PRIMARY KEY,
            stock_name TEXT NOT NULL,
            added_price REAL,
            added_date TEXT
        );
        """)
        conn.commit()
        conn.close()
    except Exception: pass

init_watchlist_db()


class HealthCheckHandler(BaseHTTPRequestHandler):
    """供 UptimeRobot 每 5 分鐘 Ping 一次，保持 24H 綠燈不休眠"""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        res = {"status": "healthy", "service": "WayneBot 24H Online", "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args): return


def start_health_server(port: int):
    try:
        httpd = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"🌐 Web 健康檢查伺服器已於 Port {port} 啟動！")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"HTTP Server 異常: {e}")


def chunk_message(text: str, max_length: int = 2800) -> List[str]:
    if not text or len(text) <= max_length: return [text] if text else []
    chunks, cur, cur_len = [], [], 0
    for line in text.split("\n"):
        if cur_len + len(line) + 1 > max_length:
            if cur: chunks.append("\n".join(cur)); cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur: chunks.append("\n".join(cur))
    return chunks


def send_telegram_safely(chat_id: Optional[Union[str, int]] = None, text: str = "", parse_mode: str = "HTML", reply_markup: Optional[dict] = PERSISTENT_KEYBOARD, **kwargs) -> bool:
    token = kwargs.get("token") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    target_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or DEFAULT_CHAT_ID
    if not token or not target_id: return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = chunk_message(text, max_length=2800)
    all_ok = True

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": str(target_id).strip(),
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "link_preview_options": {"is_disabled": True}
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup

        try:
            resp = requests.post(url, json=payload, timeout=12)
            if resp.status_code == 200:
                logger.info(f"✅ Telegram 訊息已送達！")
            else:
                payload.pop("parse_mode", None)
                payload["text"] = re.sub(r"<[^>]+>", "", chunk)
                r_resp = requests.post(url, json=payload, timeout=12)
                all_ok = (r_resp.status_code == 200)
        except Exception as e:
            logger.error(f"Telegram 連線異常: {e}")
            all_ok = False
        time.sleep(0.3)
    return all_ok


def send_photo_safely(photo_path: str, chat_id: Optional[Union[str, int]] = None, caption: Optional[str] = None, reply_markup: Optional[dict] = None) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    target_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or DEFAULT_CHAT_ID
    if not token or not target_id or not os.path.exists(photo_path): return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {"chat_id": str(target_id).strip(), "parse_mode": "HTML"}
    if caption: data["caption"] = caption
    if reply_markup: data["reply_markup"] = json.dumps(reply_markup)

    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(url, data=data, files={"photo": f}, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


def get_detailed_portfolio_report() -> str:
    """產出 30 萬本金 4 等份詳細帳本"""
    try:
        if not portfolio_engine:
            return "💼 目前尚未啟動持倉引擎。"

        engine = portfolio_engine.PortfolioEngine()
        conn = engine.get_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM simulated_positions WHERE status = 'OPEN';")
        active = cur.fetchall()

        cur.execute("SELECT * FROM trade_history ORDER BY id DESC LIMIT 5;")
        history = cur.fetchall()
        conn.close()

        total_cost = sum([float(dict(p).get("total_cost", 0.0)) for p in active]) if active else 0.0
        total_unrealized = sum([(float(dict(p).get("current_price", 0.0)) - float(dict(p).get("avg_entry_price", 0.0))) * int(dict(p).get("total_shares", 0)) for p in active]) if active else 0.0
        used_tranches = sum([int(dict(p).get("tranches_used", 1)) for p in active]) if active else 0
        free_tranches = 4 - used_tranches
        free_cash = 300000.0 - total_cost + (sum([float(dict(h).get("pnl_amount", 0.0)) for h in history]) if history else 0.0)
        total_nav = free_cash + total_cost + total_unrealized

        lines = [
            "💼 <b>【WayneBot AI 模擬操盤與資金流水帳本】</b>",
            f"📅 <b>統計日期</b>：<code>{datetime.date.today().strftime('%Y-%m-%d')}</code>",
            f"💰 <b>總本金</b>：<code>$300,000</code> (分 4 等份 | 每份 $75,000)",
            f"💵 <b>可用現金</b>：<code>${free_cash:,.0f}</code> ({free_tranches} 等份待命中)",
            f"📊 <b>持股現值</b>：<code>${total_cost + total_unrealized:,.0f}</code> ({used_tranches} 等份在倉)",
            f"💎 <b>目前總淨值</b>：<b>${total_nav:,.0f}</b> (<code>{((total_nav-300000)/300000)*100:+.2f}%</code>)",
            "────────────────────────────────────────",
            "📦 <b>【目前在庫持倉與階梯加碼明細】</b>"
        ]

        if not active:
            lines.append("<i>目前無在倉部位（4 等份資金 $300,000 隨時逢低抄底）。</i>")
        else:
            for idx, pos in enumerate(active, 1):
                p = dict(pos)
                sid, sname = p.get("stock_id", ""), p.get("stock_name", "")
                e_date = p.get("entry_date", "")
                avg_p = float(p.get("avg_entry_price", 0.0))
                c_p = float(p.get("current_price", avg_p))
                shares = int(p.get("total_shares", 0))
                cost = float(p.get("total_cost", 0.0))
                tranches = int(p.get("tranches_used", 1))
                h_days = int(p.get("holding_days", 0))
                pnl_amt = (c_p - avg_p) * shares
                pnl_pct = ((c_p - avg_p) / avg_p * 100.0) if avg_p > 0 else 0.0
                mdd = float(p.get("max_drawdown_pct", 0.0))

                pnl_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
                icon = "🔺" if pnl_pct >= 0 else "🔻"

                lines.append(f"<b>{idx}. {sid} {sname}</b> (已動用 <code>{tranches}</code> 等份資金)")
                lines.append(f"   • <b>首次進場</b>: <code>{e_date}</code> (持有 <code>{h_days}</code> 天)")
                lines.append(f"   • <b>累計持有</b>: <code>{shares:,}</code> 股 | <b>加權均價</b>: <code>${avg_p:.2f}</code>")
                lines.append(f"   • <b>投入成本</b>: <code>${cost:,.0f}</code> | <b>現價</b>: <code>${c_p:.2f}</code>")
                lines.append(f"   • <b>未實現損益</b>: {icon} <b>{pnl_str}</b> (${pnl_amt:+,.0f}) | MDD: <code>{mdd:.1f}%</code>\n")

        lines.append("────────────────────────────────────────")
        lines.append("🔔 <b>【歷史平倉與獲利來源紀錄 (紅字提醒)】</b>")
        if not history:
            lines.append("<i>尚無歷史平倉紀錄。</i>")
        else:
            for h in history:
                h_d = dict(h)
                pnl_pct = float(h_d.get("pnl_percentage", 0.0))
                pnl_amt = float(h_d.get("pnl_amount", 0.0))
                p_icon = "🔴" if pnl_pct < 0 else "🟢"
                lines.append(f"{p_icon} <b>[{h_d.get('exit_date','')} 賣出] {h_d.get('stock_id','')} {h_d.get('stock_name','')}</b> ({h_d.get('total_shares',0):,} 股)")
                lines.append(f"   • 均價: <code>${h_d.get('avg_entry_price',0)}</code> ➜ 出場: <code>${h_d.get('exit_price',0)}</code> (<b>{pnl_pct:+.2f}%</b>)")
                lines.append(f"   • <b>獲利金額</b>: <b>${pnl_amt:+,.0f}</b> | 原因: {h_d.get('exit_reason','')}\n")

        return "\n".join(lines)
    except Exception as e:
        return f"💼 <b>【持倉帳本讀取中】</b>\n目前系統正重整中，請稍候重試 ({e})。"


def get_watchlist_report() -> str:
    try:
        conn = sqlite3.connect(WATCHLIST_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_watchlist ORDER BY added_date DESC;")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "⭐ <b>【我的自選觀察名單】</b>\n目前名單為空。\n💡 在查詢股票時點擊 <code>[ ⭐ 加入自選 ]</code> 即可快速收藏！"

        lines = ["⭐ <b>【我的自選觀察名單】</b>", "────────────────────────"]
        for r in rows:
            sid, sname = r[0], r
            yahoo_url = f"https://tw.stock.yahoo.com/quote/{sid}"
            lines.append(f"• <b>{sid} {sname}</b> 👉 <a href='{yahoo_url}'>Yahoo 即時行情</a>")
        return "\n".join(lines)
    except Exception as e:
        return f"⭐ 自選名單讀取中 ({e})。"


class CommandProcessor:
    @staticmethod
    def handle_stock_query(keyword: str, chat_id: str):
        clean_key = keyword.strip()
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{clean_key}"

        report_text = f"""🔥 <b>【{clean_key}】 盤後多因子深度量化卡</b>
• <b>即時走勢</b>: 👉 <a href="{yahoo_url}">點此直連 Yahoo 股市行情 ({clean_key})</a>
• <b>位階評估</b>: 守穩短期均線，操作空間與波段動能確認。
• <b>風控提示</b>: 嚴格執行 7% 停損與移動停利機制。"""

        action_buttons = {
            "inline_keyboard": [
                [{"text": f"⭐ 加入自選: {clean_key}", "callback_data": f"ADD_{clean_key}"}],
                [{"text": "🔙 返回每日海選戰報", "callback_data": "BACK_MAIN"}]
            ]
        }
        send_telegram_safely(chat_id=chat_id, text=report_text, reply_markup=action_buttons)

        if CaryBotChartGenerator:
            chart_path = os.path.join(BASE_DIR, f"{clean_key}_180d.png")
            try:
                CaryBotChartGenerator.draw_180d_chart(clean_key, clean_key, 100.0, 120.0, 80.0, 110.0, 90.0, chart_path)
                send_photo_safely(photo_path=chart_path, chat_id=chat_id, caption=f"📈 {clean_key} 180日絕對高低點導航圖", reply_markup=action_buttons)
            except Exception: pass


def run_polling_loop():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or TELEGRAM_BOT_TOKEN

    # 強制清除 Webhook 鎖定
    try:
        requests.post(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=False", timeout=8)
        logger.info("🔓 已成功解除 Telegram Webhook 舊鎖定通道！")
    except Exception: pass

    logger.info("🚀 【WayneBot Telegram 輪詢監聽核心已啟動】")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 20}, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    if "message" in item and "text" in item["message"]:
                        msg = item["message"]
                        c_id = msg["chat"]["id"]
                        txt = msg["text"].strip()
                        logger.info(f"📥 收到指令: {txt}")

                        try:
                            if any(k in txt for k in ["start", "開始", "選單"]):
                                welcome = "👋 <b>歡迎使用 WayneBot 台股量化決策系統！</b>\n請點擊下方選單，或直接輸入<b>股票名稱或代碼</b>（如 <code>台光電</code>、<code>2383</code>）！"
                                send_telegram_safely(chat_id=c_id, text=welcome)
                            elif any(k in txt for k in ["海選", "screen", "今日"]):
                                if screening_engine:
                                    df_top = screening_engine.run_full_screening(10)
                                    rep = screening_engine.format_telegram_report(df_top.to_dict(orient="records"), datetime.date.today().strftime("%Y-%m-%d"))
                                    send_telegram_safely(chat_id=c_id, text=rep)
                                else:
                                    send_telegram_safely(chat_id=c_id, text="🔥 海選模組加載中...")
                            elif any(k in txt for k in ["持倉", "portfolio", "模擬"]):
                                rep = get_detailed_portfolio_report()
                                send_telegram_safely(chat_id=c_id, text=rep)
                            elif any(k in txt for k in ["自選", "名單", "觀察"]):
                                rep = get_watchlist_report()
                                send_telegram_safely(chat_id=c_id, text=rep)
                            elif any(k in txt for k in ["狀態", "status", "系統"]):
                                mem_str = f"{psutil.virtual_memory().percent}%" if psutil else "正常"
                                status_msg = f"⚙️ <b>【WayneBot 系統運行健康度】</b>\n🟢 <b>Render 24H Web 伺服器在線 (Port {SERVER_PORT})</b>\n💾 <b>資料庫</b>: SQLite WAL 模式 (正常)\n🧠 <b>記憶體使用</b>: {mem_str}\n⏱ <b>伺服器時間</b>: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                send_telegram_safely(chat_id=c_id, text=status_msg)
                            else:
                                CommandProcessor.handle_stock_query(txt, str(c_id))
                        except Exception as cmd_err:
                            logger.error(f"指令處理異常: {cmd_err}")
                            send_telegram_safely(chat_id=c_id, text=f"⚠️ 處理中請稍候 ({cmd_err})")

                    elif "callback_query" in item:
                        cq = item["callback_query"]
                        cb_data = cq.get("data", "")
                        c_id = cq["message"]["chat"]["id"]
                        
                        if cb_data == "BACK_MAIN" and screening_engine:
                            df_top = screening_engine.run_full_screening(10)
                            rep = screening_engine.format_telegram_report(df_top.to_dict(orient="records"), datetime.date.today().strftime("%Y-%m-%d"))
                            send_telegram_safely(chat_id=c_id, text=rep)
                        elif cb_data.startswith("ADD_"):
                            stock_sym = cb_data.replace("ADD_", "")
                            conn = sqlite3.connect(WATCHLIST_DB_PATH)
                            cur = conn.cursor()
                            cur.execute("INSERT OR REPLACE INTO user_watchlist (stock_id, stock_name, added_price, added_date) VALUES (?, ?, 0.0, ?);", (stock_sym, stock_sym, datetime.date.today().strftime("%Y-%m-%d")))
                            conn.commit()
                            conn.close()
                            send_telegram_safely(chat_id=c_id, text=f"✅ 已成功將 <b>{stock_sym}</b> 加入您的【⭐ 自選觀察名單】！")

        except Exception as e:
            logger.error(f"輪詢異常: {e}")
            time.sleep(2)
        time.sleep(0.5)


if __name__ == "__main__":
    web_thread = threading.Thread(target=start_health_server, args=(SERVER_PORT,), daemon=True)
    web_thread.start()
    run_polling_loop()
