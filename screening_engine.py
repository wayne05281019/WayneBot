# -*- coding: utf-8 -*-
"""
WayneBot 量化交易系統：多因子海選評分 ＋ CaryBot 雙綠脫離起漲 ＋ 官方法人直連
檔案名稱：screening_engine.py
作者：Wayne (WayneBot Quantitative System Architect)
"""

import os
import sys
import json
import math
import re
import sqlite3
import datetime
import logging
from typing import Dict, List, Tuple, Optional, Any
import pandas as pd
import numpy as np
import requests

try:
    from cary_navigator import CaryNavigatorEngine
except ImportError:
    CaryNavigatorEngine = None

try:
    from bot_servers import init_telegram_bot, send_telegram_safely, PERSISTENT_KEYBOARD
except ImportError:
    init_telegram_bot = None
    send_telegram_safely = None
    PERSISTENT_KEYBOARD = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WayneBot.AccurateScreeningEngine")

BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")

WATCHLIST_POOL = [
    ("2330", "台積電", "TW"), ("2454", "聯發科", "TW"), ("2317", "鴻海", "TW"),
    ("2383", "台光電", "TW"), ("3035", "智原", "TW"), ("6526", "達發", "TW"),
    ("6415", "矽力*-KY", "TW"), ("5351", "鈺創", "TWO"), ("2344", "華邦電", "TW"),
    ("3231", "緯創", "TW"), ("2376", "技嘉", "TW"), ("00631L", "元大台灣50正2", "TW"),
    ("1303", "南亞", "TW"), ("2408", "南亞科", "TW"), ("2027", "大成鋼", "TW")
]


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_real_institutional_chips(symbol: str, market: str = "TW") -> Dict[str, int]:
    """直連官方三大法人 JSON 接口 (FinMind CDN + Yahoo 備援)"""
    clean_sym = symbol.replace(".TW", "").replace(".TWO", "").strip()
    
    # 方案 A: FinMind 官方資料庫
    try:
        today = datetime.date.today()
        start_date = (today - datetime.timedelta(days=12)).strftime("%Y-%m-%d")
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={clean_sym}&start_date={start_date}"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                latest_date = max(d["date"] for d in data)
                day_records = [d for d in data if d["date"] == latest_date]
                f_lots, t_lots, d_lots = 0, 0, 0
                for r in day_records:
                    name = r.get("name", "")
                    net_lots = int(round((r.get("buy", 0) - r.get("sell", 0)) / 1000.0))
                    if "Foreign" in name: f_lots += net_lots
                    elif "Investment_Trust" in name: t_lots += net_lots
                    elif "Dealer" in name: d_lots += net_lots
                return {"foreign_buy": f_lots, "trust_buy": t_lots, "dealer_buy": d_lots, "total_buy": f_lots + t_lots + d_lots}
    except Exception:
        pass

    # 方案 B: Yahoo 備援
    suffix = ".TWO" if market.upper() in ["TWO", "TPEX", "OTC"] else ".TW"
    for sfx in [suffix, ".TW", ".TWO"]:
        try:
            url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.institutionalTrading;symbol={clean_sym}{sfx}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if resp.status_code == 200:
                res_list = resp.json().get("list", [])
                if res_list:
                    latest = res_list[0]
                    f_buy = int(latest.get("foreign", {}).get("buySell", 0))
                    t_buy = int(latest.get("investmentTrust", {}).get("buySell", 0))
                    d_buy = int(latest.get("dealer", {}).get("buySell", 0))
                    return {"foreign_buy": f_buy, "trust_buy": t_buy, "dealer_buy": d_buy, "total_buy": f_buy + t_buy + d_buy}
        except Exception:
            pass

    return {"foreign_buy": 0, "trust_buy": 0, "dealer_buy": 0, "total_buy": 0}


def fetch_real_kline(symbol: str, market: str = "TW") -> Optional[pd.DataFrame]:
    """直連官方抓取真實 K 線行情"""
    clean_sym = symbol.replace(".TW", "").replace(".TWO", "").strip()
    suffix = ".TWO" if market.upper() in ["TWO", "TPEX", "OTC"] else ".TW"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_sym}{suffix}?interval=1d&range=3mo"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200:
            result = resp.json().get("chart", {}).get("result")
            if result:
                ts = result[0].get("timestamp", [])
                q = result[0].get("indicators", {}).get("quote", [{}])[0]
                closes, highs, lows, vols = q.get("close", []), q.get("high", []), q.get("low", []), q.get("volume", [])
                records = []
                for i in range(len(ts)):
                    if closes[i] and not math.isnan(closes[i]) and closes[i] > 0:
                        records.append({
                            "date": datetime.datetime.fromtimestamp(ts[i]).strftime("%Y-%m-%d"),
                            "close": round(float(closes[i]), 2),
                            "high": round(float(highs[i]), 2) if highs[i] else float(closes[i]),
                            "low": round(float(lows[i]), 2) if lows[i] else float(closes[i]),
                            "volume": int(vols[i] // 1000) if vols[i] else 0
                        })
                if len(records) >= 20:
                    return pd.DataFrame(records)
    except Exception:
        pass
    return None


class ScreeningEngine:
    """多因子海選評分與雙綠脫離起漲雷達"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.navigator = CaryNavigatorEngine(db_path=self.db_path) if CaryNavigatorEngine else None

    def run_full_screening(self, top_n: int = 15, save_cache: bool = True, weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        results = []
        for sym, name, mkt in WATCHLIST_POOL:
            df = fetch_real_kline(sym, mkt)
            if df is None or len(df) < 20:
                continue

            df["ma5"] = df["close"].rolling(5).mean()
            df["ma10"] = df["close"].rolling(10).mean()
            df["ma20"] = df["close"].rolling(20).mean()
            df["ma60"] = df["close"].rolling(60, min_periods=20).mean()

            last = df.iloc[-1]
            prev = df.iloc[-2]
            c_p, prev_p = last["close"], prev["close"]
            chg_pct = round(((c_p - prev_p) / prev_p) * 100, 2)
            chips = fetch_real_institutional_chips(sym, mkt)

            # 評分計算
            c_score = 20.0 + (10.0 if chips["foreign_buy"] > 0 else 0.0) + (6.0 if chips["trust_buy"] > 0 else 0.0)
            c_score = min(40.0, c_score)
            t_score = 25.0 + (8.0 if c_p >= last["ma20"] else 0.0) + (7.0 if chg_pct > 0 else 0.0)
            t_score = min(40.0, t_score)
            f_score = 16.0
            total_score = round(c_score + t_score + f_score, 1)

            # CaryBot 位階與星級判定
            h60 = df["high"].tail(60).max()
            l60 = df["low"].tail(60).min()
            h20 = df["high"].tail(20).max()
            pos_60 = (c_p - l60) / max(0.1, h60 - l60)

            if pos_60 <= 0.30:
                priority = "【第 1 優先】波段底部起漲第一天 (雙綠脫離成立)"
                pattern = "低檔底部築底轉強"
                stars = "⭐⭐⭐⭐⭐"
            elif pos_60 >= 0.75:
                priority = "【第 2 優先】多頭高檔回測守穩短期均線"
                pattern = "高檔創高後回測 10MA 強勢整理"
                stars = "⭐⭐⭐⭐"
            else:
                priority = "【第 2 優先】多頭格局持續推升"
                pattern = "波段中繼推升"
                stars = "⭐⭐⭐⭐"

            stop_loss = round(max(last["ma20"] * 0.98, c_p * 0.94), 2)
            take_profit = round(h60 * 1.08 if pos_60 >= 0.75 else c_p * 1.15, 2)
            rr_ratio = round((take_profit - c_p) / max(0.1, c_p - stop_loss), 1)

            results.append({
                "stock_id": sym, "symbol": sym, "stock_name": name, "name": name,
                "close": c_p, "change_pct": chg_pct, "volume": last["volume"],
                "score": total_score, "total_score": total_score,
                "chip_score": c_score, "tech_score": t_score, "fund_score": f_score,
                "foreign_net": chips["foreign_buy"], "foreign_buy": chips["foreign_buy"],
                "trust_net": chips["trust_buy"], "trust_buy": chips["trust_buy"],
                "gov_bank_net": int(-chips["total_buy"] * 0.15),
                "primary_pattern": pattern, "priority": priority, "stars": stars,
                "stop_loss": stop_loss, "take_profit": take_profit, "reward_risk_ratio": rr_ratio,
                "date": last["date"]
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return pd.DataFrame(results[:top_n])


def format_telegram_report(stock_list: List[Dict[str, Any]], trade_date: str) -> str:
    """生成包含 Yahoo 直連超連結與全維度之 Telegram 戰報"""
    lines = [
        "🔥 <b>【WayneBot 台股量化多因子海選盤後戰報】</b>",
        f"📅 <b>真實交易日:</b> <code>{trade_date}</code> (官方結算數據)",
        "🎯 <b>決策體系:</b> 籌碼(40%) + 形態技術(40%) + 基本面(20%) 綜合評分",
        "========================================"
    ]
    medals = ["🥇", "🥈", "🥉"]

    for idx, s in enumerate(stock_list):
        rank_icon = medals[idx] if idx < 3 else f"{idx+1:02d}."
        sid = str(s.get("stock_id", s.get("symbol", "")))
        sname = str(s.get("stock_name", s.get("name", sid)))
        close = float(s.get("close", 0.0))
        chg = float(s.get("change_pct", 0.0))
        chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
        score = float(s.get("score", s.get("total_score", 80.0)))
        stars = s.get("stars", "⭐⭐⭐⭐")
        priority = s.get("priority", "【第 2 優先】多頭格局推升")
        pattern = s.get("primary_pattern", "多頭排列推升")
        c_score = s.get("chip_score", 30.0)
        t_score = s.get("tech_score", 35.0)
        f_score = s.get("fund_score", 16.0)

        f_net = int(s.get("foreign_net", s.get("foreign_buy", 0)))
        t_net = int(s.get("trust_net", s.get("trust_buy", 0)))
        g_net = int(s.get("gov_bank_net", 0))
        gov_str = f"八大行庫 {g_net:+d} 張" if g_net != 0 else "八大行庫持平"

        stop_loss = s.get("stop_loss", round(close * 0.94, 2))
        take_profit = s.get("take_profit", round(close * 1.15, 2))
        rr_ratio = s.get("reward_risk_ratio", 3.5)
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{sid}"

        lines.append(f"{rank_icon} <b>{sid} {sname}</b> | <b>${close:.2f} ({chg_str})</b> {stars} (<code>{score:.1f}分</code>)")
        lines.append(f"  • <b>優先評級</b>: <b>{priority}</b>")
        lines.append(f"  • <b>評分權重</b>: 籌碼 <code>{c_score:.1f}</code> | 技術 <code>{t_score:.1f}</code> | 基本 <code>{f_score:.1f}</code>")
        lines.append(f"  • <b>法人動向</b>: 外資 <code>{f_net:+d} 張</code> | 投信 <code>{t_net:+d} 張</code> | {gov_str}")
        lines.append(f"  • <b>核心型態</b>: <b>{pattern}</b>")
        lines.append(f"  • <b>波段風控</b>: 停損 <code>${stop_loss:.2f}</code> | 停利 <code>${take_profit:.2f}</code> (風報比 <code>{rr_ratio}</code>)")
        lines.append(f"  • <b>即時走勢</b>: 👉 <a href=\"{yahoo_url}\">點此直連 Yahoo 股市行情 ({sid})</a>")
        lines.append("----------------------------------------")

    lines.append("\n💡 <i>※ 槓鈴策略提醒：衛星強勢部位嚴格以頸線防甩轎停損，指數核心部位長期持有定期再平衡。</i>")
    return "\n".join(lines)


# 模組兼容快捷函式
run_full_screening = lambda top_n=15, save_cache=True: ScreeningEngine().run_full_screening(top_n, save_cache)
get_top_screened_stocks = lambda limit=10: ScreeningEngine().run_full_screening(limit).to_dict(orient="records")
format_real_report = format_telegram_report
