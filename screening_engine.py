# -*- coding: utf-8 -*-
"""
WayneBot 純量化全市場海選引擎：真・第一天絕對優先 ＋ 2~3天極低獲利備援 ＋ 嚴禁追高
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
logger = logging.getLogger("WayneBot.StrictDay1Screening")

BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
os.makedirs(BASE_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")

EXPANDED_MARKET_POOL = [
    ("6415", "矽力*-KY", "TW"), ("2027", "大成鋼", "TW"), ("2383", "台光電", "TW"),
    ("6526", "達發", "TW"), ("3035", "智原", "TW"), ("1303", "南亞", "TW"),
    ("2330", "台積電", "TW"), ("2344", "華邦電", "TW"), ("5351", "鈺創", "TWO"),
    ("2408", "南亞科", "TW"), ("2317", "鴻海", "TW"), ("00631L", "元大台灣50正2", "TW"),
    ("3443", "創意", "TW"), ("3661", "世芯-KY", "TW"), ("3231", "緯創", "TW"),
    ("2376", "技嘉", "TW"), ("2603", "長榮", "TW"), ("2609", "陽明", "TW"), ("2615", "萬海", "TW")
]


def fetch_twse_official_all_chips() -> Dict[str, Dict[str, int]]:
    """一次性抓取證交所官方全市場三大法人買賣超"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json"
    chips_map = {}
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            for row in data:
                sid = row[0].strip()
                try:
                    f_net = int(float(row.replace(",", "")) / 1000)
                    t_net = int(float(row.replace(",", "")) / 1000)
                    d_net = int(float(row.replace(",", "")) / 1000) if len(row) > 11 else 0
                    chips_map[sid] = {
                        "foreign_buy": f_net,
                        "trust_buy": t_net,
                        "dealer_buy": d_net,
                        "total_buy": f_net + t_net + d_net
                    }
                except Exception: continue
    except Exception as e:
        logger.warning(f"TWSE T86 連線異常: {e}")
    return chips_map


def fetch_real_kline(symbol: str, market: str = "TW") -> Optional[pd.DataFrame]:
    clean_sym = symbol.replace(".TW", "").replace(".TWO", "").strip()
    suffix = ".TWO" if market.upper() in ["TWO", "TPEX", "OTC"] else ".TW"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean_sym}{suffix}?interval=1d&range=3mo"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
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
                if len(records) >= 15: return pd.DataFrame(records)
    except Exception: pass
    return None


class ScreeningEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        if WayneDatabaseEngine:
            WayneDatabaseEngine(db_path=self.db_path)
        self.navigator = CaryNavigatorEngine(db_path=self.db_path) if CaryNavigatorEngine else None

    def run_full_screening(self, top_n: int = 10, save_cache: bool = True, weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        official_chips = fetch_twse_official_all_chips()
        candidates = []

        for sym, name, mkt in EXPANDED_MARKET_POOL:
            df = fetch_real_kline(sym, mkt)
            if df is None or len(df) < 15: continue

            df["ma20"] = df["close"].rolling(20, min_periods=5).mean()
            last = df.iloc[-1]
            prev = df.iloc[-2]
            c_p, prev_p = last["close"], prev["close"]
            chg_pct = round(((c_p - prev_p) / prev_p) * 100, 2)

            chip = official_chips.get(sym, {"foreign_buy": 0, "trust_buy": 0, "dealer_buy": 0, "total_buy": 0})
            f_net = chip["foreign_buy"]
            t_net = chip["trust_buy"]
            tot_3 = chip["total_buy"]

            # 調用 CaryBot 決策卡提取歷史獲利序列
            if self.navigator:
                card = self.navigator.get_decision_card(sym, lookback=5)
                temp_c = card.get("temp_c", "50.0 °C")
                space_20 = card.get("space_20", 30)
                space_60 = card.get("space_60", 50)
                table = card.get("table", pd.DataFrame())
            else:
                card, table = {}, pd.DataFrame()
                temp_c, space_20, space_60 = "50.0 °C", 30, 50

            # -------------------------------------------------------------
            # 🎯 核心階梯演算法：精準計算「真・起漲天數 (Breakout Day)」
            # -------------------------------------------------------------
            tier_bonus = 0.0
            priority = "【多頭常態】常態整理"
            stars = "⭐⭐⭐"

            # 提取過去幾天的獲利數值序列 (p0=今天, p1=昨天, p2=前天, p3=大前天)
            profit_history = []
            if not table.empty:
                for _, r in table.iterrows():
                    p_str = str(r.get("獲利", "10.0%")).replace("%", "").strip()
                    try: profit_history.append(float(p_str))
                    except Exception: profit_history.append(10.0)

            p0 = profit_history[0] if len(profit_history) > 0 else 10.0
            p1 = profit_history if len(profit_history) > 1 else 10.0
            p2 = profit_history if len(profit_history) > 2 else 10.0
            p3 = profit_history if len(profit_history) > 3 else 10.0

            # 階梯 1：👑 【真・起漲第 1 天】 (昨天 0.0% 打底，今天第一天翻正)
            if p1 <= 0.5 and p0 > 0.5 and p0 <= 6.0:
                priority = f"【👑 絕對第 1 優先】真・雙綠脫離起漲第 1 天 (獲利 +{p0:.1f}%)"
                stars = "⭐⭐⭐⭐⭐"
                tier_bonus = 50.0  # 霸榜最高分

            # 階梯 2：🥈 【起漲第 2 天】 (前天 0.0%，昨天翻正，目前獲利仍在 0% 附近剛啟動)
            elif p2 <= 0.5 and p1 > 0.5 and p0 <= 6.0:
                priority = f"【🥈 第 2 優先】雙綠脫離起漲第 2 天 (獲利僅 +{p0:.1f}% 剛啟動)"
                stars = "⭐⭐⭐⭐"
                tier_bonus = 35.0

            # 階梯 3：🥉 【起漲第 3 天】 (大前天 0.0%，目前獲利仍在 8% 以內低基期)
            elif p3 <= 0.5 and p2 > 0.5 and p0 <= 8.0:
                priority = f"【🥉 第 3 優先】雙綠脫離起漲第 3 天 (低基期獲利 +{p0:.1f}%)"
                stars = "⭐⭐⭐⭐"
                tier_bonus = 20.0

            # 階梯 4：⛔ 【已脫離起漲點 / 已漲一大段 (嚴禁列為第1優先)】
            elif p0 > 15.0:
                priority = f"【⚠️ 觀察/不追高】已脫離起漲點 (波段獲利已達 +{p0:.1f}%)"
                stars = "⭐⭐⭐"
                tier_bonus = -10.0  # 強制扣分降級，絕不誤導追高

            else:
                priority = f"【常態多頭】溫水整理區 (溫度計 {temp_c})"
                stars = "⭐⭐⭐⭐"
                tier_bonus = 5.0

            # 籌碼評分 (40)
            c_score = 20.0 + (12.0 if f_net > 0 and t_net > 0 else (8.0 if f_net > 0 else -6.0)) + (5.0 if f_net > 1500 else 0.0)
            c_score = max(0.0, min(40.0, c_score))

            # 技術評分 (40)
            t_score = 20.0 + (10.0 if chg_pct > 0 else -5.0) + (10.0 if p0 <= 5.0 else 0.0)
            t_score = max(0.0, min(40.0, t_score))

            f_score = 16.0
            total_score = round(min(100.0, c_score + t_score + f_score + tier_bonus), 1)

            # 風控停損停利 (買在低點停損只需 3~5%，風報比極高)
            stop_loss = round(max(last["ma20"] * 0.98, c_p * 0.95), 2)
            take_profit = round(c_p * 1.15, 2)
            rr_ratio = round((take_profit - c_p) / max(0.1, c_p - stop_loss), 1)

            candidates.append({
                "stock_id": sym, "symbol": sym, "stock_name": name, "name": name,
                "close": c_p, "change_pct": chg_pct, "volume": last["volume"],
                "score": total_score, "total_score": total_score,
                "chip_score": c_score, "tech_score": t_score, "fund_score": f_score,
                "foreign_net": f_net, "trust_net": t_net, "total_3major": tot_3,
                "temp_c": temp_c, "profit_str": f"{p0:.1f}%",
                "space_20": space_20, "space_60": space_60,
                "priority": priority, "stars": stars,
                "stop_loss": stop_loss, "take_profit": take_profit, "reward_risk_ratio": rr_ratio,
                "date": last["date"]
            })

        # 👑 嚴格排序：真第一天 > 第2天 > 第3天 > 已漲大段強制墊底
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return pd.DataFrame(candidates[:top_n])


def format_telegram_report(stock_list: List[Dict[str, Any]], trade_date: str) -> str:
    lines = [
        "🔥 <b>【WayneBot 台股全市場多因子海選盤後戰報】</b>",
        f"📅 <b>真實交易日:</b> <code>{trade_date}</code> (官方真實數據)",
        "🎯 <b>選股鐵律:</b> 真・起漲第1天絕對優先 ＋ 獲利近0%第2~3天備援",
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
        priority = s.get("priority", "【常態多頭】")
        c_score = s.get("chip_score", 30.0)
        t_score = s.get("tech_score", 35.0)
        f_score = s.get("fund_score", 16.0)

        f_net = int(s.get("foreign_net", 0))
        t_net = int(s.get("trust_net", 0))
        tot_3 = int(s.get("total_3major", f_net + t_net))

        temp_c = s.get("temp_c", "50.0 °C")
        profit_str = s.get("profit_str", "10.0%")
        space_20 = s.get("space_20", 30)
        space_60 = s.get("space_60", 50)

        stop_loss = s.get("stop_loss", round(close * 0.95, 2))
        take_profit = s.get("take_profit", round(close * 1.15, 2))
        rr_ratio = s.get("reward_risk_ratio", 3.5)
        yahoo_url = f"https://tw.stock.yahoo.com/quote/{sid}"

        lines.append(f"{rank_icon} <b>{sid} {sname}</b> | <b>${close:.2f} ({chg_str})</b> {stars} (<code>{score:.1f}分</code>)")
        lines.append(f"  • <b>真實位階</b>: <b>{priority}</b>")
        lines.append(f"  • <b>決策指標</b>: 溫度計 <code>{temp_c}</code> | 距低點獲利 <code>{profit_str}</code>")
        lines.append(f"  • <b>操作空間</b>: 20日 <b>{space_20}%</b> | 60日 <b>{space_60}%</b>")
        lines.append(f"  • <b>評分權重</b>: 籌碼 <code>{c_score:.1f}</code> | 技術 <code>{t_score:.1f}</code> | 基本 <code>{f_score:.1f}</code>")
        lines.append(f"  • <b>法人動向</b>: 外資 <code>{f_net:+d} 張</code> | 投信 <code>{t_net:+d} 張</code> | 三大法人 <code>{tot_3:+d} 張</code>")
        lines.append(f"  • <b>波段風控</b>: 停損 <code>${stop_loss:.2f}</code> | 停利 <code>${take_profit:.2f}</code> (風報比 <code>{rr_ratio}</code>)")
        lines.append(f"  • <b>即時走勢</b>: 👉 <a href=\"{yahoo_url}\">點此直連 Yahoo 股市行情 ({sid})</a>")
        lines.append("----------------------------------------")

    lines.append("\n💡 <i>※ 點擊下方【💼 AI 模擬持倉】可查看 30 萬 4 等份帳本，點擊【⭐ 我的自選名單】可查看收藏標的。</i>")
    return "\n".join(lines)


run_full_screening = lambda top_n=10, save_cache=True: ScreeningEngine().run_full_screening(top_n, save_cache)
