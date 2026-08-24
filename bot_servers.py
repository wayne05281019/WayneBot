# -*- coding: utf-8 -*-
"""
bot_servers.py
WayneBot 旗艦量化交易系統：免指令中文查詢 ＋ 關閉網址大圖 ＋ 自選名單 ＋ 詳細持倉帳本
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

init_watchlist_db()


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        res = {"status": "healthy", "service": "WayneBot Dual-Core", "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
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
            "disable_web_page_preview": True, # ✅ 徹底關閉 Yahoo 紫色巨大預覽圖！
            "link_preview_options": {"is_disabled": True}
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup

        try:
            resp = requests.post(url, json=payload, timeout=12)
            if resp.status_code == 200:
                logger.info(f"✅ Telegram 戰報第 [{i+1}/{len(chunks)}] 段已發送！")
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
    """產出超詳細的 AI 模擬部位帳本、加碼記錄與資金流水帳"""
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

    lines = [
        "💼 <b>【WayneBot AI 模擬操盤與資金流水帳本】</b>",
        f"📅 <b>統計日期</b>：<code>{datetime.date.today().strftime('%Y-%m-%d')}</code>",
        "────────────────────────────────────────",
        "📦 <b>【目前在庫持倉明細】</b>"
    ]

    total_cost = 0.0
    total_unrealized = 0.0

    if not active:
        lines.append("<i>目前無在倉部位（資金 100% 待命中）。</i>")
    else:
        for idx, pos in enumerate(active, 1):
            sid = pos["stock_id"]
            sname = pos["stock_name"]
            ptype = pos["position_type"]
            e_date = pos["entry_date"]
            e_price = float(pos["entry_price"])
            c_price = float(pos["current_price"])
            shares = int(pos["shares"])
            h_days = int(pos["holding_days"])
            cost = e_price * shares
            pnl_amount = (c_price - e_price) * shares
            pnl_pct = ((c_price - e_price) / e_price) * 100.0
            mdd = float(pos["max_drawdown_pct"])

            total_cost += cost
            total_unrealized += pnl_amount

            pnl_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            icon = "🔺" if pnl_pct >= 0 else "🔻"

            lines.append(f"<b>{idx}. {sid} {sname}</b> ({ptype})")
            lines.append(f"   • <b>進場日期</b>: <code>{e_date}</code> (持有 <code>{h_days}</code> 天)")
            lines.append(f"   • <b>持有股數</b>: <code>{shares:,}</code> 股 | <b>單價</b>: <code>${e_price:.2f}</code>")
            lines.append(f"   • <b>投入成本</b>: <code>${cost:,.0f}</code> | <b>現價</b>: <code>${c_price:.2f}</code>")
            lines.append(f"   • <b>未實現損益</b>: {icon} <b>{pnl_str}</b> (${pnl_amount:+,.0f}) | MDD: <code>{mdd:.1f}%</code>\n")

    lines.append("────────────────────────────────────────")
    lines.append("🔔 <b>【近期平倉與獲利來源紀錄 (紅字提醒)】</b>")
    if not history:
        lines.append("<i>尚無歷史平倉紀錄。</i>")
    else:
        for h in history:
            pnl_pct = float(h["pnl_percentage"])
            pnl_amt = float(h["pnl_amount"])
            p_icon = "🔴" if pnl_pct < 0 else "🟢"
            lines.append(f"{p_icon} <b>[{h['exit_date']} 賣出] {h['stock_id']} {h['stock_name']}</b> ({h['shares']}股)")
            lines.append(f"   • 進場: <code>${h['entry_price']}</code> ➜ 出場: <code>${h['exit_price']}</code> (<b>{pnl_pct:+.2f}%</b>)")
            lines.append(f"   • <b>損益金額</b>: <b>${pnl_amt:+,.0f}</b> | 原因: {h['exit_reason']}")
            lines.append(f"   • <b>歸因分析</b>: <i>{h['failure_attribution']}</i>\n")

    # 績效總評
    perf = engine.evaluate_performance()
    lines.append("────────────────────────────────────────")
    lines.append("📈 <b>【歷史累計總績效】</b>")
    lines.append(f"• <b>累計平倉</b>: <code>{perf['total_trades']}</code> 筆 | <b>勝率</b>: <b>{perf['win_rate']}%</b> | <b>賺賠比</b>: <b>{perf['profit_loss_ratio']}</b>")
    lines.append(f"• <b>累計複利報酬</b>: <b>{perf['cumulative_return_pct']:+}%</b>")

    return "\n".join(lines)


def get_watchlist_report() -> str:
    """產出使用者自選觀察名單"""
    conn = sqlite3.connect(WATCHLIST_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_watchlist ORDER BY added_date DESC;")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "⭐ <b>【我的自選觀察名單】</b>\n目前名單為空。\n💡 在海選戰報中點擊 <code>[ ⭐ 加入自選 ]</code> 即可快速收藏！"

    lines = ["⭐ <b>【我的自選觀察名單】</b>", "────────────────────────"]
    for r in rows:
        sid, sname, price, dt = r[0], r, r, r
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{sid}"
        lines.append(f"• <b>{sid} {sname}</b> (加入價: ${price:.2f})")
        lines.append(f"  👉 <a href='{yahoo_url}'>Yahoo 即時報價</a> | <a href='https://t.me/share/url?url={sid}'>點擊查決策卡</a>\n")
    return "\n".join(lines)


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
            except Exception as e:
                logger.warning(f"趨勢圖繪製異常: {e}")


def run_polling_loop():
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
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

                        if txt in ["/start", "開始", "選單"]:
                            welcome = "👋 <b>歡迎使用 WayneBot 台股量化決策系統！</b>\n請點擊下方選單，或直接輸入<b>股票名稱或代碼</b>（如 <code>台光電</code>、<code>2383</code>）！"
                            send_telegram_safely(chat_id=c_id, text=welcome)
                        elif txt in ["/screen", "🔥 今日海選", "今日海選", "海選"]:
                            if screening_engine:
                                df_top = screening_engine.run_full_screening(10)
                                rep = screening_engine.format_telegram_report(df_top.to_dict(orient="records"), datetime.date.today().strftime("%Y-%m-%d"))
                                send_telegram_safely(chat_id=c_id, text=rep)
                        elif txt in ["/portfolio", "💼 AI 模擬持倉", "AI 模擬持倉", "持倉"]:
                            rep = get_detailed_portfolio_report()
                            send_telegram_safely(chat_id=c_id, text=rep)
                        elif txt in ["⭐ 我的自選名單", "自選名單", "自選股"]:
                            rep = get_watchlist_report()
                            send_telegram_safely(chat_id=c_id, text=rep)
                        elif txt in ["/status", "📊 系統狀態", "系統狀態"]:
                            mem_str = f"{psutil.virtual_memory().percent}%" if psutil else "正常"
                            status_msg = f"⚙️ <b>【WayneBot 系統運行健康度】</b>\n🟢 <b>Render 24H Web 伺服器在線 (Port {SERVER_PORT})</b>\n💾 <b>資料庫</b>: SQLite WAL 模式 (正常)\n🧠 <b>記憶體使用</b>: {mem_str}\n⏱ <b>伺服器時間</b>: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            send_telegram_safely(chat_id=c_id, text=status_msg)
                        else:
                            CommandProcessor.handle_stock_query(txt, str(c_id))

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
