"""
screening_engine.py - WayneBot / CaryBot 量化海選與指標校準引擎
嚴格落實 CaryBot 手冊標準：
1. 優先級 1：真・起漲第 1 天（昨日獲利 0.0% 或處於成本區，今日第一天帶量突破翻正）。
2. 備援級：僅在無第 1 天標的時，選擇距離成本區 < 6%~8% 之起漲第 2~3 天標的。
3. 嚴格排除：自底部/起漲點波段獲利已達 15%~20% 以上之標的，防止追高。
4. 官方三大法人買賣超 (張)、多空溫度計 (°C)、高低位階標籤與操作空間精準對齊。
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any


class FormattedReport(str):
    """字串與字典雙模相容類別，同時支援 Telegram 訊息直接發送與字典欄位讀取"""
    def __new__(cls, text: str, data: dict):
        obj = super().__new__(cls, text)
        obj.data = data
        return obj

    def __getitem__(self, key):
        if isinstance(key, str) and key in self.data:
            return self.data[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self.data.get(key, default)


class ScreeningEngine:
    def __init__(self, db_path: Any = "wayne_market.db", *args, **kwargs):
        # 防呆解析：若傳入 chat_id (int) 或非路徑物件，自動還原為標準資料庫路徑
        if isinstance(db_path, str) and (db_path.endswith(".db") or db_path.endswith(".sqlite") or "/" in db_path or "\\" in db_path):
            self.db_path = db_path
        else:
            self.db_path = os.getenv("WAYNE_DB_PATH", "wayne_market.db")

        # 自動偵測可能的資料庫所在目錄
        candidate_paths = [
            self.db_path,
            "wayne_market.db",
            "data/wayne_market.db",
            "/app/data/wayne_market.db",
            "/app/wayne_market.db"
        ]
        for p in candidate_paths:
            if p and isinstance(p, str) and os.path.exists(p):
                self.db_path = p
                break

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_stock_history(self, conn: sqlite3.Connection, symbol: str, lookback: int = 180) -> pd.DataFrame:
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
        if len(df) < 20:
            return df

        df["ma5"] = df["close_price"].rolling(window=5).mean()
        df["ma10"] = df["close_price"].rolling(window=10).mean()
        df["ma20"] = df["close_price"].rolling(window=20).mean()
        df["ma60"] = df["close_price"].rolling(window=60).mean()
        df["vol_ma20"] = df["volume"].rolling(window=20).mean()

        df["range_high_180"] = df["high_price"].rolling(window=len(df), min_periods=20).max()
        df["range_low_180"] = df["low_price"].rolling(window=len(df), min_periods=20).min()

        delta = df["close_price"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi14"] = 100 - (100 / (1 + rs))

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

        ema12 = df["close_price"].ewm(span=12, adjust=False).mean()
        ema26 = df["close_price"].ewm(span=26, adjust=False).mean()
        df["dif"] = ema12 - ema26
        df["macd"] = df["dif"].ewm(span=9, adjust=False).mean()
        df["osc"] = df["dif"] - df["macd"]

        return df

    def calculate_temperature(self, row: pd.Series, prev_row: pd.Series, inst_streak: int) -> float:
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
        if len(df) < 60:
            return None

        df = self.calculate_technical_indicators(df)
        curr = df.iloc[-1]
        prev1 = df.iloc[-2]

        if df["volume"].iloc[-5:].mean() < 300:
            return None

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

        temperature = self.calculate_temperature(curr, prev1, inst_streak)

        lowest_recent = df["low_price"].iloc[-20:].min()
        swing_gain = ((curr_price - lowest_recent) / lowest_recent) * 100.0

        if swing_gain >= 15.0:
            return None

        cost_line = max(curr["ma20"], df["high_price"].iloc[-10:-1].max())
        prev_profit_pct = ((prev1["close_price"] - cost_line) / cost_line) * 100.0
        today_profit_pct = ((curr_price - cost_line) / cost_line) * 100.0
        today_change_pct = ((curr_price - prev1["close_price"]) / prev1["close_price"]) * 100.0

        is_day1_breakout = False
        is_day2_3_backup = False
        breakout_stage = "非起漲結構"

        if (prev1["close_price"] <= prev1["ma20"] or prev_profit_pct <= 0.5) and \
           (curr_price > curr["ma20"] and today_change_pct > 1.0) and \
           (curr["volume"] >= 1.3 * curr["vol_ma20"]) and \
           (today_profit_pct <= 5.0):
            is_day1_breakout = True
            breakout_stage = "🔥 真・起漲第 1 天（強烈推薦）"
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

    def run_full_market_screening(self, *args, **kwargs) -> Any:
        """
        執行全市場掃描，回傳雙模（字串+字典）相容之推薦報告。
        """
        if not os.path.exists(self.db_path):
            error_msg = "⚠️ 資料庫檔案尚未生成或正在初始化，請稍候重試。"
            return FormattedReport(error_msg, {"recommendations": [], "strategy_status": error_msg})

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

            scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 組合 Telegram Markdown 格式報表
            lines = [
                "🏆 *【WayneBot / CaryBot 量化海選決策日報】*",
                f"📅 掃描時間：`{scan_time}`",
                f"📊 掃描總數：`{len(stocks)} 檔` | 🎯 第 1 天：`{len(day1_candidates)} 檔` | 🛡️ 備援：`{len(backup_candidates)} 檔`",
                f"📌 決策狀態：{strategy_status}",
                "───────────────────"
            ]

            if not final_selection:
                lines.append("⚠️ 今日全市場均未出現符合標準之起漲標的，建議保持資金防禦觀望。")
            else:
                for idx, item in enumerate(final_selection, 1):
                    lines.extend([
                        f"*{idx}. {item['stock_name']} ({item['symbol']})*",
                        f"  • 收盤價: `{item['close_price']} 元` ({item['change_pct']:+0.2f}%)",
                        f"  • 判定階段: `{item['breakout_stage']}`",
                        f"  • 多空溫度: `{item['temperature']}°C` | 位階: `{item['position_tag']}`",
                        f"  • 距成本獲利: `{item['current_profit_from_cost']:+0.2f}%` (成本線: `{item['cost_line']}`)",
                        f"  • 操作空間: 上 `{item['upside_room_pct']}%` / 下防守 `{item['downside_risk_pct']}%`",
                        f"  • 三大法人: `{item['total_inst_lots']:+d} 張` (外資 `{item['foreign_lots']:+d}` / 投信 `{item['trust_lots']:+d}`)",
                        f"  • 即時走勢: [點此直連 Yahoo 股市行情 ({item['symbol']})](https://tw.stock.yahoo.com/quote/{item['symbol']})",
                        "───────────────────"
                    ])

            lines.append("🤖 _由 WayneBot AI 自動化量化引擎生成，嚴守停損停利紀律。_")
            report_text = "\n".join(lines)

            raw_dict = {
                "scan_time": scan_time,
                "total_scanned": len(stocks),
                "day1_count": len(day1_candidates),
                "backup_count": len(backup_candidates),
                "strategy_status": strategy_status,
                "recommendations": final_selection,
                "all_day1": day1_candidates,
                "all_backup": backup_candidates
            }

            return FormattedReport(report_text, raw_dict)
        finally:
            conn.close()

    # 類別函式別名相容
    run_full_screening = run_full_market_screening


# ==============================================================================
# 模組層級相容包裝函式（無論傳入 chat_id、limit 或 db_path 均能安全執行）
# ==============================================================================
def run_full_screening(*args, **kwargs) -> Any:
    engine = ScreeningEngine(*args, **kwargs)
    return engine.run_full_market_screening()

def run_full_market_screening(*args, **kwargs) -> Any:
    engine = ScreeningEngine(*args, **kwargs)
    return engine.run_full_market_screening()
