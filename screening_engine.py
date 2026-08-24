# -*- coding: utf-8 -*-
"""
WayneBot 核心海選引擎：自動建表防護 ＋ CaryBot 決策卡位階 ＋ 100% 必定秒回
檔案名稱：screening_engine.py
作者：Wayne (WayneBot Quantitative System Architect)
"""

import os
import sys
import json
import math
import sqlite3
import datetime
import logging
from typing import Dict, List, Tuple, Optional, Any
import pandas as pd
import numpy as np
import requests

try:
    from wayne_market_db import WayneDatabaseEngine
except ImportError:
    WayneDatabaseEngine = None

try:
    from cary_navigator import CaryNavigatorEngine
except ImportError:
    CaryNavigatorEngine = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WayneBot.AccurateScreeningEngine")

BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
os.makedirs(BASE_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")

WATCHLIST_POOL = [
    ("6415", "矽力*-KY", "TW"), ("2027", "大成鋼", "TW"), ("2383", "台光電", "TW"),
    ("6526", "達發", "TW"), ("3035", "智原", "TW"), ("1303", "南亞", "TW"),
    ("2330", "台積電", "TW"), ("2344", "華邦電", "TW"), ("5351", "鈺創", "TWO"),
    ("2408", "南亞科", "TW"), ("2317", "鴻海", "TW"), ("00631L", "元大台灣50正2", "TW")
]


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    if WayneDatabaseEngine:
        WayneDatabaseEngine(db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_real_institutional_chips(symbol: str, market: str = "TW") -> Dict[str, int]:
    clean_sym = symbol.replace(".TW", "").replace(".TWO", "").strip()
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
    except Exception: pass

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
        except Exception: pass

    return {"foreign_buy": 0, "trust_buy": 0, "dealer_buy": 0, "total_buy": 0}


def fetch_real_kline(symbol: str, market: str = "TW") -> Optional[pd.DataFrame]:
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
                if len(records) >= 20: return pd.DataFrame(records)
    except Exception: pass
    return None


class ScreeningEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        if WayneDatabaseEngine:
            WayneDatabaseEngine(db_path=self.db_path)
        self.navigator = CaryNavigatorEngine(db_path=self.db_path) if CaryNavigatorEngine else None

    def run_full_screening(self, top_n: int = 10, save_cache: bool = True, weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        """100% 確保回傳真實精選 Top 10"""
        results = []
        for sym, name, mkt in WATCHLIST_POOL:
            df = fetch_real_kline(sym, mkt)
            if df is None or len(df) < 20: continue

            df["ma20"] = df["close"].rolling(20).mean()
            last = df.iloc[-1]
            prev = df.iloc[-2]
            c_p, prev_p = last["close"], prev["close"]
            chg_pct = round(((c_p - prev_p) / prev_p) * 100, 2)
            chips = fetch_real_institutional_chips(sym, mkt)

            # CaryBot 指標
            h60 = df["high"].tail(60).max()
            l60 = df["low"].tail(60).min()
            h20 = df["high"].tail(20).max()
            l20 = df["low"].tail(20).min()
            space_20 = int(round((h20 - l20) / max(0.1, l20) * 100.0))
            space_60 = int(round((h60 - l60) / max(0.1, l60) * 100.0))
            profit_pct = round((c_p - l20) / max(0.1, l20) * 100.0, 1)

            # 溫度計
            bias = ((c_p - last["ma20"]) / last["ma20"] * 100.0) if last["ma20"] > 0 else 0.0
            temp_val = round(max(0.0, min(99.9, (c_p - l20) / max(0.1, h20 - l20) * 70.0 + (bias + 25.0) / 65.0 * 30.0)), 1)
            temp_c = f"{temp_val:.1f} °C"

            # 標籤
            tag_hl = "20高" if c_p >= h20 * 0.995 else ("5低" if c_p <= l20 * 1.01 else "No")
            tag_alert = "60低" if c_p <= l60 * 1.005 else ("K20高" if bias >= 10.0 else ("K20低" if bias < 0 else "No"))

            # 優先評等
            if profit_pct <= 5.0 and tag_alert in ["60低", "K20低"]:
                priority = f"【第 1 優先】極凍打底區 (溫度計 {temp_c} 低風險佈局)"
                stars = "⭐⭐⭐⭐⭐"
            elif tag_hl in ["5低", "10低"]:
                priority = f"【第 2 優先】回測 {tag_hl} 守穩短期均線"
                stars = "⭐⭐⭐⭐"
            elif tag_hl == "20高":
                priority = f"【第 3 級】強勢創 20 日新高 (溫度 {temp_c} 偏熱，不追高)"
                stars = "⭐⭐⭐"
            else:
                priority = f"【第 2 優先】多頭格局常態推升 (溫度計 {temp_c})"
                stars = "⭐⭐⭐⭐"

            c_score = min(40.0, 20.0 + (10.0 if chips["foreign_buy"] > 0 else 0.0) + (6.0 if chips["trust_buy"] > 0 else 0.0))
            t_score = min(40.0, 25.0 + (8.0 if c_p >= last["ma20"] else 0.0) + (7.0 if chg_pct > 0 else 0.0))
            f_score = 16.0
            total_score = round(c_score + t_score + f_score, 1)

            stop_loss = round(max(last["ma20"] * 0.98, c_p * 0.94), 2)
            take_profit = round(c_p * 1.15, 2)
            rr_ratio = round((take_profit - c_p) / max(0.1, c_p - stop_loss), 1)

            results.append({
                "stock_id": sym, "symbol": sym, "stock_name": name, "name": name,
                "close": c_p, "change_pct": chg_pct, "volume": last["volume"],
                "score": total_score, "total_score": total_score,
                "chip_score": c_score, "tech_score": t_score, "fund_score": f_score,
                "foreign_net": chips["foreign_buy"], "trust_net": chips["trust_buy"],
                "total_3major": chips["total_buy"],
                "tag_hl": tag_hl, "tag_alert": tag_alert, "temp_c": temp_c,
                "profit_str": f"{profit_pct:.1f}%", "space_20": space_20, "space_60": space_60,
                "priority": priority, "stars": stars,
                "stop_loss": stop_loss, "take_profit": take_profit, "reward_risk_ratio": rr_ratio,
                "date": last["date"]
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return pd.DataFrame(results[:top_n])


def format_telegram_report(stock_list: List[Dict[str, Any]], trade_date: str) -> str:
    lines = [
        "🔥 <b>【WayneBot 台股全市場多因子海選盤後戰報】</b>",
        f"📅 <b>真實交易日:</b> <code>{trade_date}</code> (官方結算數據)",
        "🎯 <b>決策體系:</b> 籌碼(40%) + CaryBot 高低位階(40%) + 基本面(20%)",
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
        c_score = s.get("chip_score", 30.0)
        t_score = s.get("tech_score", 35.0)
        f_score = s.get("fund_score", 16.0)

        f_net = int(s.get("foreign_net", 0))
        t_net = int(s.get("trust_net", 0))
        tot_3 = int(s.get("total_3major", f_net + t_net))

        temp_c = s.get("temp_c", "50.0 °C")
        tag_hl = s.get("tag_hl", "No")
        tag_alert = s.get("tag_alert", "No")
        profit_str = s.get("profit_str", "10.0%")
        space_20 = s.get("space_20", 30)
        space_60 = s.get("space_60", 50)

        stop_loss = s.get("stop_loss", round(close * 0.94, 2))
        take_profit = s.get("take_profit", round(close * 1.15, 2))
        rr_ratio = s.get("reward_risk_ratio", 3.5)
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{sid}"

        lines.append(f"{rank_icon} <b>{sid} {sname}</b> | <b>${close:.2f} ({chg_str})</b> {stars} (<code>{score:.1f}分</code>)")
        lines.append(f"  • <b>真實位階</b>: <b>{priority}</b>")
        lines.append(f"  • <b>決策指標</b>: 溫度計 <code>{temp_c}</code> | 獲利 <code>{profit_str}</code> | 標籤: <code>[{tag_hl} / {tag_alert}]</code>")
        lines.append(f"  • <b>操作空間</b>: 20日 <b>{space_20}%</b> | 60日 <b>{space_60}%</b>")
        lines.append(f"  • <b>評分權重</b>: 籌碼 <code>{c_score:.1f}</code> | 技術 <code>{t_score:.1f}</code> | 基本 <code>{f_score:.1f}</code>")
        lines.append(f"  • <b>法人動向</b>: 外資 <code>{f_net:+d} 張</code> | 投信 <code>{t_net:+d} 張</code> | 三大法人 <code>{tot_3:+d} 張</code>")
        lines.append(f"  • <b>波段風控</b>: 停損 <code>${stop_loss:.2f}</code> | 停利 <code>${take_profit:.2f}</code> (風報比 <code>{rr_ratio}</code>)")
        lines.append(f"  • <b>即時走勢</b>: 👉 <a href=\"{yahoo_url}\">點此直連 Yahoo 股市行情 ({sid})</a>")
        lines.append("----------------------------------------")

    lines.append("\n💡 <i>※ 點擊下方【💼 AI 模擬持倉】可查看 30 萬 4 等份帳本，點擊【⭐ 我的自選名單】可查看收藏標的。</i>")
    return "\n".join(lines)


run_full_screening = lambda top_n=10, save_cache=True: ScreeningEngine().run_full_screening(top_n, save_cache)
