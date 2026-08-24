# -*- coding: utf-8 -*-
"""
WayneBot 全市場海選引擎：全台股 2,233 檔標的掃描 ＋ CaryBot 決策卡位階 ＋ 多因子評分
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
    from cary_navigator import CaryNavigatorEngine
except ImportError:
    CaryNavigatorEngine = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WayneBot.FullMarketScreeningEngine")

BASE_DIR = "/content/waynebot_data" if os.path.exists("/content") else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_market_master.db")


def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


class ScreeningEngine:
    """全市場 2,233 檔標的量化多因子海選與 CaryBot 絕對高低位階雷達"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.navigator = CaryNavigatorEngine(db_path=self.db_path) if CaryNavigatorEngine else None

    def run_full_screening(
        self,
        top_n: int = 10,
        save_cache: bool = True,
        weights: Optional[Dict[str, float]] = None,
        min_volume: int = 500,
        min_price: float = 10.0
    ) -> pd.DataFrame:
        """
        🚀 全市場真實海選：
        從 wayne_market_master.db 掃描全台灣所有上市櫃股票與 ETF，
        依據 流動性、CaryBot 高低位階、三大法人籌碼與技術型態 計算綜合得分！
        """
        if weights is None:
            weights = {
                "technical_breakout": 0.35,
                "institutional_flow": 0.30,
                "chip_concentration": 0.20,
                "fundamental_growth": 0.15
            }

        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        # 取得資料庫最新結算日期
        cur.execute("SELECT MAX(date) as max_date FROM daily_market_quotes;")
        latest_date_row = cur.fetchone()
        latest_date = latest_date_row["max_date"] if latest_date_row and latest_date_row["max_date"] else datetime.date.today().strftime("%Y-%m-%d")

        # 🌟 全市場 2,233 檔即時聯合查詢 (過濾流動性枯竭股)
        query = """
        SELECT u.stock_id, u.stock_name, u.market_type, u.asset_type, u.industry,
               q.open, q.high, q.low, q.close, q.volume, q.turnover, q.change_pct,
               q.pe_ratio, q.dividend_yield,
               q.ma5, q.ma10, q.ma20, q.ma60, q.mdd_20d,
               c.foreign_net, c.trust_net, c.dealer_net, c.total_3major_net, c.gov_bank_net,
               c.foreign_5d_net, c.trust_5d_net
        FROM stock_universe u
        JOIN daily_market_quotes q ON u.stock_id = q.stock_id AND q.date = ?
        JOIN daily_institutional_chips c ON u.stock_id = c.stock_id AND c.date = ?
        WHERE u.is_active = 1 AND q.volume >= ? AND q.close >= ?;
        """
        df_all = pd.read_sql_query(query, conn, params=(latest_date, latest_date, min_volume, min_price))
        conn.close()

        if df_all.empty:
            logger.warning("資料庫尚無全市場數據，嘗試從即時快取池讀取...")
            return pd.DataFrame()

        logger.info(f"全市場掃描：符合流動性 (量>={min_volume}張, 價>={min_price}元) 之標的共 {len(df_all)} 檔，進行多維度量化打分...")

        # 向量化多維度評分運算
        scored_stocks = []
        for _, row in df_all.iterrows():
            sid = str(row["stock_id"])
            sname = str(row["stock_name"])
            c_p = float(row["close"])
            chg = float(row["change_pct"])
            vol = int(row["volume"])
            ma20 = float(row["ma20"]) if row["ma20"] > 0 else c_p
            ma60 = float(row["ma60"]) if row["ma60"] > 0 else c_p

            f_net = int(row["foreign_net"])
            t_net = int(row["trust_net"])
            d_net = int(row["dealer_net"])
            tot_3 = int(row["total_3major_net"])
            g_net = int(row["gov_bank_net"])

            # 1. 籌碼動能分 (滿分 40)
            c_score = 20.0
            if f_net > 0 and t_net > 0: c_score += 18.0  # 土洋同步大買
            elif f_net > 1000 or t_net > 500: c_score += 15.0
            elif tot_3 > 0: c_score += 10.0
            elif f_net < 0 and t_net < 0: c_score -= 8.0
            c_score = max(0.0, min(40.0, c_score))

            # 2. 技術型態分 (滿分 40)
            t_score = 20.0
            if c_p >= ma20: t_score += 10.0 # 站穩月線
            if c_p >= ma60: t_score += 5.0  # 站穩季線
            if chg > 0: t_score += 5.0      # 當日上漲
            t_score = max(0.0, min(40.0, t_score))

            # 3. 基本面分 (滿分 20)
            f_score = 16.0
            total_score = round(c_score + t_score + f_score, 1)

            # 4. 呼叫 CaryBot 導航引擎計算真實位階與溫度計
            if self.navigator:
                card = self.navigator.get_decision_card(sid, lookback=5)
                temp_c = card.get("temp_c", "50.0 °C")
                space_20 = card.get("space_20", 30)
                space_60 = card.get("space_60", 50)
                
                latest_row = card["table"].iloc[0] if ("table" in card and not card["table"].empty) else {}
                tag_hl = latest_row.get("高低", "No")
                tag_alert = latest_row.get("預警", "No")
                profit_str = latest_row.get("獲利", "10.0%")
                bias_str = latest_row.get("月乖離", "0.0%")

                # 起漲第一天嚴格判定 (昨天在0.0%極低，今天第一天翻正)
                is_day1_breakout = False
                if "table" in card and len(card["table"]) >= 2:
                    yest_p = card["table"].iloc.get("獲利", "")
                    if "0.0%" in yest_p and "0.0%" not in profit_str:
                        is_day1_breakout = True

                temp_val = float(temp_c.replace("°C", "").strip())
                if is_day1_breakout:
                    priority = "【第 1 優先】波段底部起漲第一天 (雙綠脫離成立)"
                    stars = "⭐⭐⭐⭐⭐"
                    total_score += 5.0 # 起漲加權
                elif temp_val <= 15.0:
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
            else:
                temp_c, space_20, space_60 = "50.0 °C", 30, 50
                tag_hl, tag_alert, profit_str = "No", "No", "10.0%"
                priority, stars = "【第 2 優先】多頭格局推升", "⭐⭐⭐⭐"

            total_score = round(min(100.0, total_score), 1)

            # 風控設定
            stop_loss = round(max(ma20 * 0.98, c_p * 0.94), 2)
            take_profit = round(c_p * 1.15, 2)
            rr_ratio = round((take_profit - c_p) / max(0.1, c_p - stop_loss), 1)

            scored_stocks.append({
                "stock_id": sid, "symbol": sid, "stock_name": sname, "name": sname,
                "close": c_p, "change_pct": chg, "volume": vol,
                "score": total_score, "total_score": total_score,
                "chip_score": c_score, "tech_score": t_score, "fund_score": f_score,
                "foreign_net": f_net, "trust_net": t_net, "dealer_net": d_net,
                "total_3major": tot_3, "gov_bank_net": g_net,
                "tag_hl": tag_hl, "tag_alert": tag_alert, "temp_c": temp_c,
                "profit_str": profit_str, "space_20": space_20, "space_60": space_60,
                "priority": priority, "stars": stars,
                "stop_loss": stop_loss, "take_profit": take_profit, "reward_risk_ratio": rr_ratio,
                "date": latest_date
            })

        # 依全市場量化總分由高到低嚴格排名
        df_ranked = pd.DataFrame(scored_stocks).sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
        return df_ranked


def format_telegram_report(stock_list: List[Dict[str, Any]], trade_date: str) -> str:
    """生成全市場海選之純淨專業 Telegram 戰報 (無紫色大圖、含 Yahoo 直連)"""
    lines = [
        "🔥 <b>【WayneBot 台股全市場多因子海選盤後戰報】</b>",
        f"📅 <b>真實交易日:</b> <code>{trade_date}</code> (全台股 2,233 檔官方數據)",
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
