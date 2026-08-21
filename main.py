# -*- coding: utf-8 -*-
"""
WayneBot 第三階段 (Phase 3)：Telegram 機器人伺服端 (Render Web 0.01秒極速綁定 + Phase 1 資料庫整合版)
"""

import os
import sys
import time
import json
import random
import datetime
import threading
import traceback
import requests
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler

# 引入 Phase 1 資料庫模組
import wayne_db

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8688883757:AAEpWVMX86lSMmY1PewTw60A8j0sdsFKXac")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8528875978")

BASE_DIR = "waynebot_data"
RAW_TWSE_DIR = os.path.join(BASE_DIR, "raw_twse")
RAW_TPEX_DIR = os.path.join(BASE_DIR, "raw_tpex")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(RAW_TWSE_DIR, exist_ok=True)
os.makedirs(RAW_TPEX_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

STOCKS_FILE = os.path.join(EXPORT_DIR, "history_stocks.csv.gz")
CHIPS_FILE = os.path.join(EXPORT_DIR, "history_chips.csv.gz")

session = requests.Session()
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
]

# ==========================================
# 0. Render Web 端口即時監聽服務 (0.01秒秒通 Render 檢查)
# ==========================================
class SimpleHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("WayneBot 7x24h Daemon is Running Online!".encode("utf-8"))
    
    def log_message(self, format, *args):
        return

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    }

def get_col(row, idx, default=""):
    if isinstance(row, (list, tuple)) and 0 <= idx < len(row): 
        return row[idx]
    return default

def clean_float(val) -> float:
    if val is None or isinstance(val, (list, tuple, np.ndarray, pd.Series)): 
        return 0.0
    if isinstance(val, (int, float)): 
        return float(val)
    s = str(val).replace(",", "").replace("+", "").replace(" ", "").replace("X", "").strip()
    if s in ["--", "-", "除息", "除權", "暫停交易", "", "nan", "None"]: 
        return 0.0
    try: 
        return float(s)
    except: 
        return 0.0

def safe_div(num, den, default=0.0) -> float:
    try:
        f_num, f_den = float(num), float(den)
        if f_den == 0.0 or np.isnan(f_den) or np.isnan(f_num): 
            return default
        return f_num / f_den
    except: 
        return default

def send_tg_message(text: str, chat_id: str = TELEGRAM_CHAT_ID, parse_mode: str = "HTML", reply_markup: Optional[dict] = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup: 
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        res = requests.post(url, json=payload, timeout=10.0)
        print(f"Telegram 推播狀態: {res.status_code}")
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")
        wayne_db.log_system_error(
            module_name="main.send_tg_message",
            error_message=str(e),
            stack_trace=traceback.format_exc()
        )

def parse_twse_stocks(raw: dict, date_str: str) -> Optional[pd.DataFrame]:
    tables = raw.get("tables", [])
    data_rows = []
    for t in tables:
        if "每日收盤行情" in t.get("title", "") or len(t.get("fields", [])) >= 14:
            data_rows = t.get("data", [])
            break
    if not data_rows and "data9" in raw: 
        data_rows = raw["data9"]
    records = []
    for r in data_rows:
        if len(r) < 11: 
            continue
        sid = str(get_col(r, 0)).strip().replace("=", "").replace('"', "")
        if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))): 
            continue
        sname = str(get_col(r, 1)).strip()
        vol_shares = clean_float(get_col(r, 2))
        turnover_k = clean_float(get_col(r, 4)) / 1000.0
        open_p, high_p, low_p, close_p = clean_float(get_col(r, 5)), clean_float(get_col(r, 6)), clean_float(get_col(r, 7)), clean_float(get_col(r, 8))
        sign, diff = str(get_col(r, 9)), clean_float(get_col(r, 10))
        prev_close = close_p - diff if "+" in sign or "▲" in sign or "red" in sign else (close_p + diff if "-" in sign or "▼" in sign or "green" in sign else close_p)
        pct_change = safe_div(close_p - prev_close, prev_close) * 100.0
        records.append({
            "date": date_str, "stock_id": sid, "stock_name": sname, "market": "TW",
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": int(round(vol_shares / 1000.0)), "turnover_k": turnover_k,
            "pct_change": round(pct_change, 2), "avg_price": round(safe_div(turnover_k * 1000.0, vol_shares, default=close_p), 2)
        })
    return pd.DataFrame(records) if records else None

def parse_tpex_stocks(raw: dict, date_str: str) -> Optional[pd.DataFrame]:
    records = []
    for r in raw.get("aaData", []):
        if len(r) < 10: 
            continue
        sid = str(get_col(r, 0)).strip()
        if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))): 
            continue
        sname = str(get_col(r, 1)).strip()
        close_p, diff, open_p, high_p, low_p = clean_float(get_col(r, 2)), clean_float(get_col(r, 3)), clean_float(get_col(r, 4)), clean_float(get_col(r, 5)), clean_float(get_col(r, 6))
        vol_shares, turnover_k = clean_float(get_col(r, 7)), clean_float(get_col(r, 8)) / 1000.0
        prev_close = close_p - diff if close_p > 0 else close_p
        pct_change = safe_div(close_p - prev_close, prev_close) * 100.0
        records.append({
            "date": date_str, "stock_id": sid, "stock_name": sname, "market": "TWO",
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": int(round(vol_shares / 1000.0)), "turnover_k": turnover_k,
            "pct_change": round(pct_change, 2), "avg_price": round(safe_div(turnover_k * 1000.0, vol_shares, default=close_p), 2)
        })
    return pd.DataFrame(records) if records else None

def fetch_twse_stocks(date_str: str) -> Optional[pd.DataFrame]:
    cache = os.path.join(RAW_TWSE_DIR, f"stocks_{date_str}.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f: 
                return parse_twse_stocks(json.load(f), date_str)
        except: 
            pass
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json"
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.8, 2.5))
            res = session.get(url, headers=get_headers(), timeout=15.0).json()
            if res.get("stat") == "OK":
                with open(cache, "w", encoding="utf-8") as f: 
                    json.dump(res, f, ensure_ascii=False)
                return parse_twse_stocks(res, date_str)
            elif "很抱歉" in res.get("stat", "") or "沒有符合" in res.get("stat", ""): 
                return None
        except Exception as e: 
            time.sleep(2.5)
    return None

def fetch_tpex_stocks(date_str: str) -> Optional[pd.DataFrame]:
    cache = os.path.join(RAW_TPEX_DIR, f"stocks_{date_str}.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f: 
                return parse_tpex_stocks(json.load(f), date_str)
        except: 
            pass
    roc_y = int(date_str[:4]) - 1911
    url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_y}/{date_str[4:6]}/{date_str[6:8]}&_={int(time.time()*1000)}"
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.8, 2.5))
            res = session.get(url, headers=get_headers(), timeout=15.0).json()
            if res.get("aaData"):
                with open(cache, "w", encoding="utf-8") as f: 
                    json.dump(res, f, ensure_ascii=False)
                return parse_tpex_stocks(res, date_str)
        except Exception as e: 
            time.sleep(2.5)
    return None

def get_or_build_history(days_to_fetch=30) -> pd.DataFrame:
    if os.path.exists(STOCKS_FILE):
        try:
            df = pd.read_csv(STOCKS_FILE, compression="gzip", dtype={"stock_id": str, "date": str})
            if len(df) > 5000: 
                return df
        except: 
            pass

    today = datetime.datetime.now()
    date_list = []
    curr = today
    while len(date_list) < days_to_fetch:
        if curr.weekday() < 5: 
            date_list.append(curr.strftime("%Y%m%d"))
        curr -= datetime.timedelta(days=1)
    date_list = sorted(date_list)

    all_stocks = []
    for d_str in date_list:
        df_tw, df_two = fetch_twse_stocks(d_str), fetch_tpex_stocks(d_str)
        day_s = [d for d in [df_tw, df_two] if d is not None and not d.empty]
        if day_s: 
            all_stocks.append(pd.concat(day_s, ignore_index=True))

    if all_stocks:
        df_total = pd.concat(all_stocks, ignore_index=True)
        df_total.to_csv(STOCKS_FILE, index=False, compression="gzip")
        return df_total
    return pd.DataFrame()

class FullMarketQuantScreener:
    @staticmethod
    def run_screening(df_stocks: pd.DataFrame) -> pd.DataFrame:
        candidates = []
        for sid, group in df_stocks.groupby("stock_id"):
            df = group.sort_values("date").copy()
            if len(df) < 15: 
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            c_p = latest["close"]
            if c_p <= 0 or latest["volume"] <= 0: 
                continue
            
            vol20 = df["volume"].tail(20).mean()
            turnover20 = df["turnover_k"].tail(20).mean()
            if vol20 < 300 or turnover20 < 10000: 
                continue
            
            h20, l20 = df["high"].tail(20).max(), df["low"].tail(20).min()
            d20_gain = safe_div(c_p - l20, l20) * 100.0
            prev_d20_gain = safe_div(prev["close"] - l20, l20) * 100.0
            space_20 = safe_div(h20 - l20, l20) * 100.0
            
            sma20 = df["close"].tail(20).mean()
            sma60 = df["close"].tail(60).mean() if len(df) >= 60 else sma20
            bias20 = safe_div(c_p - sma20, sma20) * 100.0
            vol5 = df["volume"].tail(5).mean()
            vol_ratio = safe_div(latest["volume"], vol5, default=1.0)
            vol_rank = int((df["volume"].tail(120) > latest["volume"]).sum() + 1)
            ma60s = safe_div(sma60 - df["close"].tail(60).iloc[0], 60) if len(df) >= 60 else 0.0
            
            score = 0.0
            if prev_d20_gain <= 5.0 and 2.0 <= d20_gain <= 18.0: 
                score += 45.0
            elif 0.0 <= d20_gain <= 20.0: 
                score += 35.0
            elif d20_gain > 20.0 and d20_gain <= 28.0: 
                score += 20.0
            else: 
                score += 5.0
                
            if vol_rank <= 5: 
                score += 15.0
            elif vol_rank <= 15: 
                score += 10.0
            elif vol_rank <= 30: 
                score += 6.0
            if vol_ratio >= 1.8: 
                score += 10.0
            elif vol_ratio >= 1.3: 
                score += 6.0
            
            if space_20 >= 25.0: 
                score += 15.0
            elif space_20 >= 15.0: 
                score += 10.0
            elif space_20 >= 10.0: 
                score += 5.0
            
            if ma60s > 0 and c_p >= sma60: 
                score += 15.0
            elif c_p >= sma20: 
                score += 10.0
            elif bias20 < -15.0 and d20_gain > 2.0: 
                score += 12.0
            
            grade = "💎 A級 (動能先鋒)" if score >= 80 else ("⚡ B級 (波段觀察)" if score >= 65 else "一般")
            
            if score >= 60:
                candidates.append({
                    "stock_id": sid, "stock_name": latest["stock_name"], "market": latest["market"],
                    "close": c_p, "pct_change": latest["pct_change"],
                    "d20_gain": f"{d20_gain:.1f}%", "space_20": f"{space_20:.0f}%",
                    "vol_rank": f"第 {vol_rank} 名", "vol_ratio": f"{vol_ratio:.1f}x",
                    "bias20": f"{bias20:+.2f}%", "ma60s": round(ma60s, 2),
                    "score": round(score, 1), "grade": grade, "raw_df": df
                })

        df_rank = pd.DataFrame(candidates)
        if df_rank.empty: 
            return df_rank
        return df_rank.sort_values("score", ascending=False).reset_index(drop=True)

def broadcast_evening_screener():
    print("📢 正在執行每日 20:30 晚間海選推播任務 ...")
    try:
        df_stocks = get_or_build_history()
        if df_stocks.empty: 
            return
        top_ranked = FullMarketQuantScreener.run_screening(df_stocks)
        if top_ranked.empty: 
            return
        
        latest_date = df_stocks["date"].max()
        
        # 將今日精選海選數據快取至 Phase 1 資料庫 (cached_data)
        cached_summary = []
        for _, row in top_ranked.head(10).iterrows():
            cached_summary.append({
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "close": row["close"],
                "score": row["score"],
                "grade": row["grade"],
                "d20_gain": row["d20_gain"],
                "space_20": row["space_20"]
            })
        wayne_db.set_cached_data(
            chapter_id=f"SCREENER_TOP10_{latest_date}",
            title=f"{latest_date} 每日精選海選戰報",
            content=cached_summary,
            is_valid=1
        )

        msg = f"🏆 <b>【WayneBot 股市量化導航 ｜ 每日精選 Top 10 海選戰報】</b>\n"
        msg += f"📅 運算基準日：<code>{latest_date}</code>\n"
        msg += f"──────────────────────\n"
        
        inline_buttons = []
        for idx, row in top_ranked.head(10).iterrows():
            sid, sname = row["stock_id"], row["stock_name"]
            yahoo_chart = f"https://tw.stock.yahoo.com/quote/{sid}.TW"
            msg += f"<b>{idx+1}. <a href='{yahoo_chart}'>{sname}</a> ({sid})</b> ｜ <b>{row['close']}元</b> ({row['pct_change']:+.2f}%)\n"
            msg += f"   • {row['grade']} ｜ 評分: <b>{row['score']}</b>\n"
            msg += f"   • D20基底: <code>{row['d20_gain']}</code> ｜ 空間: <code>{row['space_20']}</code> ｜ 量能: <code>{row['vol_rank']}</code>\n\n"
            if idx < 4:
                inline_buttons.append([{"text": f"📊 展開 {sname} ({sid}) 決策卡", "callback_data": f"card_{sid}"}])
                
        msg += f"──────────────────────\n"
        msg += f"💡 <b>操盤提醒</b>：首筆 50% 試單，開高跳空 &gt; 2.5% 禁追，嚴守防守線！"
        reply_markup = {"inline_keyboard": inline_buttons}
        send_tg_message(msg, reply_markup=reply_markup)
    except Exception as e:
        print(f"海選推播異常: {e}")
        wayne_db.log_system_error(
            module_name="main.broadcast_evening_screener",
            error_message=str(e),
            stack_trace=traceback.format_exc()
        )

def scheduler_loop():
    print("⏰ WayneBot 自動排程已啟動 (每日 20:30 海選推播 / 08:00 晨報)")
    # 伺服器啟動時，先發送一次最新海選戰報至 Telegram
    broadcast_evening_screener()
    while True:
        now_str = datetime.datetime.now().strftime("%H:%M")
        if now_str == "20:30":
            broadcast_evening_screener()
            time.sleep(65)
        time.sleep(25)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"🚀 WayneBot Web Port {port} 正在以 0.01 秒極速綁定 ...")
    
    # 1. 系統啟動時初始化 Phase 1 SQLite 資料庫 (5 張表 + WAL 模式)
    try:
        wayne_db.init_database()
        print("✅ Phase 1 資料庫已成功初始化 (WAL 模式啟動)")
    except Exception as e:
        print(f"⚠️ 資料庫初始化提示: {e}")
    
    # 2. 在背景啟動 Telegram 排程與推播任務
    t_sched = threading.Thread(target=scheduler_loop, daemon=True)
    t_sched.start()
    
    # 3. 主執行緒直接監聽 Render 端口 (Render 檢測瞬間 100% 通過)
    server = HTTPServer(("0.0.0.0", port), SimpleHealthCheckHandler)
    print(f"✅ WayneBot 伺服器已正式上線！監聽 Port: {port}")
    server.serve_forever()
