"""
screening_engine.py - WayneBot / CaryBot 量化海選與指標校準引擎
嚴格落實 CaryBot 手冊標準：
1. 優先級 1：真・起漲第 1 天（昨日獲利 0.0% 或處於成本區，今日第一天帶量突破翻正）。
2. 備援級：僅在無第 1 天標的時，選擇距離成本區 < 6%~8% 之起漲第 2~3 天標的。
3. 嚴格排除：自底部/起漲點波段獲利已達 15%~20% 以上之標的，防止追高。
4. 官方三大法人買賣超 (張)、多空溫度計 (°C)、高低位階標籤與操作空間精準對齊。
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any


class ScreeningEngine:
    def __init__(self, db_path: str = "wayne_market.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_stock_history(self, conn: sqlite3.Connection, symbol: str, lookback: int = 180) -> pd.DataFrame:
        """
        讀取指定個股最新 180 個交易日歷史日 K 線與籌碼資料。
        """
        query = """
            SELECT 
                trade_date, open_price, high_price, low_price, close_price, volume,
                foreign_buy_sell, trust_buy_sell, dealer_buy_sell
            FROM daily_quotes
            WHERE symbol = ?
            ORDER BY trade_date ASC
        """
        df = pd.read_sql_query(query, conn, params=(symbol,))
        if df.empty:
            return df
        if len(df) > lookback:
            df = df.iloc[-lookback:].copy().reset_index(drop=True)
        return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算均線、成交量均線、RSI、KD、MACD 與 180 日高低價。
        """
        if len(df) < 20:
            return df

        # 均線計算
        df["ma5"] = df["close_price"].rolling(window=5).mean()
        df["ma10"] = df["close_price"].rolling(window=10).mean()
        df["ma20"] = df["close_price"].rolling(window=20).mean()
        df["ma60"] = df["close_price"].rolling(window=60).mean()
        df["vol_ma20"] = df["volume"].rolling(window=20).mean()

        # 180 日區間高低點
        df["range_high_180"] = df["high_price"].rolling(window=len(df), min_periods=20).max()
        df["range_low_180"] = df["low_price"].rolling(window=len(df), min_periods=20).min()

        # RSI (14)
        delta = df["close_price"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi14"] = 100 - (100 / (1 + rs))

        # KD (9, 3, 3)
        low9 = df["low_price"].rolling(window=9).min()
        high9 = df["high_price"].rolling(window=9).max()
        rsv = ((df["close_price"] - low9) / (high9 - low9 + 1e-9)) * 100
        
        k_list = [50.0]
        d_list = [50.0]
        for val in rsv.fillna(50.0):
            k = (2 / 3) * k_list[-1] + (1 / 3) * val
            d = (2 / 3) * d_list[-1] + (1 / 3) * k
            k_list.append(k)
            d_list.append(d)
        df["k9"] = k_list[1:]
        df["d9"] = d_list[1:]

        # MACD (12, 26, 9)
        ema12 = df["close_price"].ewm(span=12, adjust=False).mean()
        ema26 = df["close_price"].ewm(span=26, adjust=False).mean()
        df["dif"] = ema12 - ema26
        df["macd"] = df["dif"].ewm(span=9, adjust=False).mean()
        df["osc"] = df["dif"] - df["macd"]

        return df

    def calculate_temperature(self, row: pd.Series, prev_row: pd.Series, inst_streak: int) -> float:
        """
        計算 CaryBot 多空溫度計 (°C)：
        - 基礎體溫：50°C
        - 均線多頭排列：+15°C
        - 帶量紅 K（成交量 > 1.5 倍 20MA 且收紅）：+12°C
        - KD 黃金交叉或強勢向上：+8°C
        - MACD 柱狀體翻正擴大：+10°C
        - 投信/外資連買：每多 1 日 +2.5°C（上限 +15°C）
        - 均線空頭排列或跌破 20MA：-20°C
        溫度範圍限制於 0.0°C ~ 100.0°C。
        """
        temp = 50.0

        if row["close_price"] > row["ma20"] > row["ma60"]:
            temp += 15.0
        elif row["close_price"] < row["ma20"]:
            temp -= 20.0

        if row["volume"] >= 1.5 * row["vol_ma20"] and row["close_price"] > row["open_price"]:
            temp += 12.0

        if row["k9"] > row["d9"] and prev_row["k9"] <= prev_row["d9"]:
            temp += 10.0
        elif row["k9"] > 50.0 and row["k9"] > row["d9"]:
            temp += 5.0

        if row["osc"] > 0 and row["osc"] > prev_row["osc"]:
            temp += 8.0
        elif row["osc"] < 0:
            temp -= 10.0

        temp += min(inst_streak * 2.5, 15.0)
        return round(float(np.clip(temp, 0.0, 100.0)), 1)

    def analyze_stock(self, symbol: str, stock_name: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        校準分析單一檔股票是否符合 CaryBot 決策卡標準與起漲判定。
        """
        if len(df) < 60:
            return None

        df = self.calculate_technical_indicators(df)
        curr = df.iloc[-1]
        prev1 = df.iloc[-2]

        # 1. 基礎量能與流動性過濾（近 5 日均量需大於 300 張）
        if df["volume"].iloc[-5:].mean() < 300:
            return None

        # 2. 180 日位階與操作空間
        low_180 = curr["range_low_180"]
        high_180 = curr["range_high_180"]
        curr_price = curr["close_price"]

        position_ratio = 50.0 if high_180 == low_180 else ((curr_price - low_180) / (high_180 - low_180)) * 100.0

        if position_ratio <= 35.0:
            position_tag = "低位階（築底/起漲區）"
        elif position_ratio <= 70.0:
            position_tag = "中位階（主升/整理區）"
        else:
            position_tag = "高位階（過熱警戒區）"

        upside_room = round(((high_180 - curr_price) / curr_price) * 100.0, 2)
        downside_risk = round(((curr_price - low_180) / curr_price) * 100.0, 2)

        # 3. 法人連續買賣超與當日張數（以千股換算為張）
        foreign_lots = int(curr["foreign_buy_sell"] / 1000)
        trust_lots = int(curr["trust_buy_sell"] / 1000)
        dealer_lots = int(curr["dealer_buy_sell"] / 1000)
        total_inst_lots = foreign_lots + trust_lots + dealer_lots

        inst_streak = 0
        for i in range(len(df) - 1, -1, -1):
            day_inst = (df["foreign_buy_sell"].iloc[i] + df["trust_buy_sell"].iloc[i]) / 1000
            if day_inst > 0:
                inst_streak += 1
            else:
                break

        # 4. 多空溫度計
        temperature = self.calculate_temperature(curr, prev1, inst_streak)

        # 5. 波段累積漲幅（防追高機制：自 20 日最低點或平台起算累積漲幅）
        lowest_recent = df["low_price"].iloc[-20:].min()
        swing_gain = ((curr_price - lowest_recent) / lowest_recent) * 100.0

        # 【核心校準規則】：波段獲利已達 15%~20% 以上者，一律嚴格排除！
        if swing_gain >= 15.0:
            return None

        # 6. 起漲天數判定 (Day 1 / Day 2 / Day 3)
        cost_line = max(curr["ma20"], df["high_price"].iloc[-10:-1].max())
        prev_profit_pct = ((prev1["close_price"] - cost_line) / cost_line) * 100.0
        today_profit_pct = ((curr_price - cost_line) / cost_line) * 100.0
        today_change_pct = ((curr_price - prev1["close_price"]) / prev1["close_price"]) * 100.0

        is_day1_breakout = False
        is_day2_3_backup = False
        breakout_stage = "非起漲結構"

        # 條件 1：真・起漲第 1 天（昨日獲利 <= 0.5% 或未突破，今日第一天帶量突破翻正）
        if (prev1["close_price"] <= prev1["ma20"] or prev_profit_pct <= 0.5) and \
           (curr_price > curr["ma20"] and today_change_pct > 1.0) and \
           (curr["volume"] >= 1.3 * curr["vol_ma20"]) and \
           (today_profit_pct <= 5.0):
            is_day1_breakout = True
            breakout_stage = "🔥 真・起漲第 1 天（強烈推薦）"

        # 條件 2：起漲第 2~3 天備援（獲利仍在 < 6%~8% 之內，且均線支撐完好）
        elif (prev_profit_pct > 0.0) and (today_profit_pct <= 7.5) and \
             (curr_price > curr["ma20"]) and (temperature >= 55.0):
            is_day2_3_backup = True
            breakout_stage = "⚡ 起漲第 2~3 天（貼近成本備援）"

        if not (is_day1_breakout or is_day2_3_backup):
            return None

        return {
            "symbol": symbol,
            "stock_name": stock_name,
            "close_price": curr_price,
            "change_pct": round(today_change_pct, 2),
            "volume_lots": int(curr["volume"]),
            "vol_ratio": round(float(curr["volume"] / (curr["vol_ma20"] + 1e-9)), 2),
            "temperature": temperature,
            "position_ratio": round(position_ratio, 1),
            "position_tag": position_tag,
            "upside_room_pct": upside_room,
            "downside_risk_pct": downside_risk,
            "foreign_lots": foreign_lots,
            "trust_lots": trust_lots,
            "dealer_lots": dealer_lots,
            "total_inst_lots": total_inst_lots,
            "inst_streak_days": inst_streak,
            "is_day1": is_day1_breakout,
            "is_backup": is_day2_3_backup,
            "breakout_stage": breakout_stage,
            "cost_line": round(cost_line, 2),
            "current_profit_from_cost": round(today_profit_pct, 2),
            "swing_gain": round(swing_gain, 2)
        }

    def run_full_market_screening(self) -> Dict[str, Any]:
        """
        執行全市場掃描，回傳排序後的推薦清單與備援標的。
        """
        conn = self._get_connection()
        try:
            meta_query = "SELECT symbol, stock_name FROM stock_metadata WHERE is_active = 1"
            cursor = conn.execute(meta_query)
            stocks = cursor.fetchall()
            
            day1_candidates: List[Dict[str, Any]] = []
            backup_candidates: List[Dict[str, Any]] = []

            for row in stocks:
                sym = row["symbol"]
                name = row["stock_name"]
                df = self.fetch_stock_history(conn, sym, lookback=180)
                if df.empty:
                    continue

                analysis = self.analyze_stock(sym, name, df)
                if analysis:
                    if analysis["is_day1"]:
                        day1_candidates.append(analysis)
                    elif analysis["is_backup"]:
                        backup_candidates.append(analysis)

            # 排序標準
            day1_candidates.sort(
                key=lambda x: (x["temperature"], x["total_inst_lots"], x["upside_room_pct"]),
                reverse=True
            )
            backup_candidates.sort(
                key=lambda x: (-x["current_profit_from_cost"], x["temperature"], x["total_inst_lots"]),
                reverse=True
            )

            if len(day1_candidates) > 0:
                final_selection = day1_candidates[:5]
                strategy_status = "🎯 今日以【真・起漲第 1 天】標的為絕對首選推薦"
            else:
                final_selection = backup_candidates[:5]
                strategy_status = "🛡️ 當日無符合第 1 天起漲股，啟用【起漲第 2~3 天貼近成本】備援推薦"

            return {
                "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_scanned": len(stocks),
                "day1_count": len(day1_candidates),
                "backup_count": len(backup_candidates),
                "strategy_status": strategy_status,
                "recommendations": final_selection,
                "all_day1": day1_candidates,
                "all_backup": backup_candidates
            }
        finally:
            conn.close()
