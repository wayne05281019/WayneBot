# -*- coding: utf-8 -*-
"""
WayneBot 第三階段：Telegram 機器人伺服端 ＆ 7x24 小時全自動推播伺服器
"""

import os, sys, time, json, random, datetime, threading, requests
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

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

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    }

def get_col(row, idx, default=""):
    if isinstance(row, (list, tuple)) and 0 <= idx < len(row): return row[idx]
    return default

def clean_float(val) -> float:
    if val is None or isinstance(val, (list, tuple, np.ndarray, pd.Series)): return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace(",", "").replace("+", "").replace(" ", "").replace("X", "").strip()
    if s in ["--", "-", "除息", "除權", "暫停交易", "", "nan", "None"]: return 0.0
    try: return float(s)
    except: return 0.0

def safe_div(num, den, default=0.0) -> float:
    try:
        f_num, f_den = float(num), float(den)
        if f_den == 0.0 or np.isnan(f_den) or np.isnan(f_num): return default
        return f_num / f_den
    except: return default

def send_tg_message(text: str, chat_id: str = TELEGRAM_CHAT_ID, parse_mode: str = "HTML", reply_markup: Optional[dict] = None):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print(f"[模擬發送 Telegram]:\n{text}\n")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    try: requests.post(url, json=payload, timeout=10.0)
    except Exception as e: print(f"Telegram 發送失敗: {e}")

def parse_twse_stocks(raw: dict, date_str: str) -> Optional[pd.DataFrame]:
    tables = raw.get("tables", [])
    data_rows = []
    for t in tables:
        if "每日收盤行情" in t.get("title", "") or len(t.get("fields", [])) >= 14:
            data_rows = t.get("data", []); break
    if not data_rows and "data9" in raw: data_rows = raw["data9"]
    records = []
    for r in data_rows:
        if len(r) < 11: continue
        sid = str(get_col(r, 0)).strip().replace("=", "").replace('"', "")
        if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))): continue
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
        if len(r) < 10: continue
        sid = str(get_col(r, 0)).strip()
        if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))): continue
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
            with open(cache, "r", encoding="utf-8") as f: return parse_twse_stocks(json.load(f), date_str)
        except: pass
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json"
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.8, 2.5))
            res = session.get(url, headers=get_headers(), timeout=15.0).json()
            if res.get("stat") == "OK":
                with open(cache, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False)
                return parse_twse_stocks(res, date_str)
            elif "很抱歉" in res.get("stat", "") or "沒有符合" in res.get("stat", ""): return None
        except: time.sleep(2.5)
    return None

def fetch_tpex_stocks(date_str: str) -> Optional[pd.DataFrame]:
    cache = os.path.join(RAW_TPEX_DIR, f"stocks_{date_str}.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f: return parse_tpex_stocks(json.load(f), date_str)
        except: pass
    roc_y = int(date_str[:4]) - 1911
    url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_y}/{date_str[4:6]}/{date_str[6:8]}&_={int(time.time()*1000)}"
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.8, 2.5))
            res = session.get(url, headers=get_headers(), timeout=15.0).json()
            if res.get("aaData"):
                with open(cache, "w", encoding="utf-8") as f: json.dump(res, f, ensure_ascii=False)
                return parse_tpex_stocks(res, date_str)
        except: time.sleep(2.5)
    return None

def get_or_build_history(days_to_fetch=30) -> pd.DataFrame:
    if os.path.exists(STOCKS_FILE):
        try:
            df = pd.read_csv(STOCKS_FILE, compression="gzip", dtype={"stock_id": str, "date": str})
            if len(df) > 5000: return df
        except: pass

    today = datetime.datetime.now()
    date_list = []
    curr = today
    while len(date_list) < days_to_fetch:
        if curr.weekday() < 5: date_list.append(curr.strftime("%Y%m%d"))
        curr -= datetime.timedelta(days=1)
    date_list = sorted(date_list)

    all_stocks = []
    for d_str in date_list:
        df_tw, df_two = fetch_twse_stocks(d_str), fetch_tpex_stocks(d_str)
        day_s = [d for d in [df_tw, df_two] if d is not None and not d.empty]
        if day_s: all_stocks.append(pd.concat(day_s, ignore_index=True))

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
            if len(df) < 15: continue
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            c_p = latest["close"]
            if c_p <= 0 or latest["volume"] <= 0: continue
            
            vol20 = df["volume"].tail(20).mean()
            turnover20 = df["turnover_k"].tail(20).mean()
            if vol20 < 300 or turnover20 < 10000: continue
            
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
            if prev_d20_gain <= 5.0 and 2.0 <= d20_gain <= 18.0: score += 45.0
            elif 0.0 <= d20_gain <= 20.0: score += 35.0
            elif d20_gain > 20.0 and d20_gain <= 28.0: score += 20.0
            else: score += 5.0
                
            if vol_rank <= 5: score += 15.0
            elif vol_rank <= 15: score += 10.0
            elif vol_rank <= 30: score += 6.0
            if vol_ratio >= 1.8: score += 10.0
            elif vol_ratio >= 1.3: score += 6.0
            
            if space_20 >= 25.0: score += 15.0
            elif space_20 >= 15.0: score += 10.0
            elif space_20 >= 10.0: score += 5.0
            
            if ma60s > 0 and c_p >= sma60: score += 15.0
            elif c_p >= sma20: score += 10.0
            elif bias20 < -15.0 and d20_gain > 2.0: score += 12.0
            
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
        if df_rank.empty: return df_rank
        return df_rank.sort_values("score", ascending=False).reset_index(drop=True)

def broadcast_evening_screener():
    df_stocks = get_or_build_history()
    if df_stocks.empty: return
    top_ranked = FullMarketQuantScreener.run_screening(df_stocks)
    if top_ranked.empty: return
    
    latest_date = df_stocks["date"].max()
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

def broadcast_morning_report():
    msg = f"🌅 <b>【WayneBot 晨間大盤氣象站 ＆ 今日作戰晨報】</b>\n"
    msg += f"📅 日期：<code>{datetime.datetime.now().strftime('%Y-%m-%d')}</code>\n"
    msg += f"──────────────────────\n"
    msg += f"🌤️ <b>大盤氣象預警</b>：【常態晴天模式 ｜ 積極作戰】\n"
    msg += f"• 核心作戰：聚焦昨日 Top 10 雙綠脫離動能先鋒！\n"
    msg += f"• 下單紀律：08:30~09:00 確認掛單，開高禁市價追價，限價回測低接！\n"
    msg += f"──────────────────────\n"
    msg += f"👉 輸入 <code>/查 股號</code> 即時展開決策卡 ＆ 同業比較！"
    send_tg_message(msg)

def scheduler_loop():
    print("⏰ WayneBot 自動排程已啟動 (每日 20:30 海選推播 / 08:00 晨報)")
    while True:
        now_str = datetime.datetime.now().strftime("%H:%M")
        if now_str == "20:30":
            broadcast_evening_screener()
            time.sleep(65)
        elif now_str == "08:00":
            broadcast_morning_report()
            time.sleep(65)
        time.sleep(25)

if __name__ == "__main__":
    print("==================================================================")
    print("🚀 WayneBot Telegram Bot 雲端伺服器已上線！")
    print("==================================================================")
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    
    # 啟動時先發送一次最新海選推播測試
    broadcast_evening_screener()
    
    while True: time.sleep(3600)
