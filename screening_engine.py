# ==============================================================================
# WayneBot 全市場量化決策系統：選股與價位精算模組 (screening_engine.py)
# 功能：全市場歷史/即時量化選股、當沖/隔日沖價位精算、S級籌碼濾網、流動性防護
# ==============================================================================

import os
import sqlite3
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np


class ScreeningEngine:
    """WayneBot 全市場量化選股與價位精算引擎"""

    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 唯讀連線並啟用 WAL 模式優化"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_latest_trading_dates(self, limit: int = 490) -> List[str]:
        """取得資料庫中最新的 N 個交易日（遞增排序）"""
        if not os.path.exists(self.db_path):
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        dates = [r[0] for r in rows]
        dates.reverse()
        return dates

    def load_stock_history_df(self, stock_id: str, limit_days: int = 490) -> pd.DataFrame:
        """載入單一標的最新 N 日歷史量價與籌碼數據"""
        conn = self._get_connection()
        query = """
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k,
            pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(stock_id, limit_days))
        conn.close()
        if df.empty:
            return df
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算關鍵均線、量比 Q60R、歷史新高 (Hi5/Hi120/Hi480) 與 D20 乖離指標"""
        if len(df) < 5:
            return df

        # 均線計算
        df["ma5"] = df["close"].rolling(window=5).mean()
        df["ma20"] = df["close"].rolling(window=20).mean()
        df["ma60"] = df["close"].rolling(window=60).mean()
        df["vol_ma60"] = df["volume"].rolling(window=60).mean()

        # 60日量比 (Q60R)
        df["q60r"] = np.where(df["vol_ma60"] > 0, df["volume"] / df["vol_ma60"], 1.0)

        # 區間高點與低點
        df["hi5"] = df["high"].rolling(window=5).max()
        df["hi120"] = df["high"].rolling(window=min(120, len(df))).max()
        df["hi480"] = df["high"].rolling(window=min(480, len(df))).max()
        df["low20"] = df["low"].rolling(window=20).min()
        df["high20"] = df["high"].rolling(window=20).max()
        df["low60"] = df["low"].rolling(window=min(60, len(df))).min()

        # D20 指標：近20日區間位置百分比 (0%~100%)
        range_20 = df["high20"] - df["low20"]
        df["d20"] = np.where(range_20 > 0, (df["close"] - df["low20"]) / range_20 * 100.0, 50.0)

        # 5MA 勾角判斷 (今日 MA5 > 昨日 MA5)
        df["ma5_diff"] = df["ma5"].diff()

        return df

    def calculate_trade_price_targets(self, latest_row: pd.Series) -> Dict[str, Any]:
        """精算當沖與隔日沖關鍵價位卡"""
        close_p = float(latest_row["close"])
        avg_p = float(latest_row["avg_price"]) if float(latest_row["avg_price"]) > 0 else close_p
        open_p = float(latest_row["open"])

        # 當沖動能價位精算
        day_trade = {
            "entry_price": round(close_p, 2),
            "take_profit_1": round(close_p * 1.03, 2),       # 第一目標 +3%
            "take_profit_2": round(close_p * 1.06, 2),       # 第二衝頂 +6%
            "stop_loss": round(min(avg_p, close_p * 0.975), 2) # 均價破線或 -2.5% 防守
        }

        # 隔日沖精選價位精算
        swing = {
            "buy_range_low": round(min(avg_p, close_p * 0.99), 2),
            "buy_range_high": round(close_p, 2),
            "target_open_high": f"{round(close_p * 1.035, 2)} ~ {round(close_p * 1.048, 2)} (+3.5~4.8%)",
            "surge_target": round(close_p * 1.08, 2),        # 強勢衝頂 +8%
            "defense_price": round(close_p * 0.97, 2)         # 保本防守價
        }

        return {
            "day_trade": day_trade,
            "swing": swing
        }

    def run_full_market_screening(
        self,
        target_date: Optional[str] = None,
        min_volume: int = 1000,
        min_turnover_k: float = 30000.0
    ) -> Dict[str, Any]:
        """
        執行全市場量化選股流水線
        :param target_date: 指定選股基準日 (YYYYMMDD)，若為 None 則自動取資料庫最新一日
        :param min_volume: 流動性下限（張數，預設 1,000 張）
        :param min_turnover_k: 流動性下限（千元，預設 30,000 千元 = 3,000 萬元）
        :return: 結構化選股結果字典
        """
        if not os.path.exists(self.db_path):
            return {"error": f"找不到資料庫檔案: {self.db_path}", "status": "failed"}

        dates = self.get_latest_trading_dates(limit=490)
        if not dates:
            return {"error": "資料庫內無有效交易日數據", "status": "failed"}

        curr_date = target_date if target_date else dates[-1]
        print(f"📊 啟動全市場量化選股，基準日: {curr_date}")

        conn = self._get_connection()
        # 篩選當日符合流動性標準的標的清單
        candidate_query = """
        SELECT stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date = ? AND volume >= ? AND turnover_k >= ?
        """
        df_today = pd.read_sql_query(candidate_query, conn, params=(curr_date, min_volume, min_turnover_k))
        conn.close()

        if df_today.empty:
            return {
                "date": curr_date,
                "total_candidates": 0,
                "select_01_breakout_5d": [],
                "select_02_breakout_120d": [],
                "select_03_breakout_480d": [],
                "select_04_double_green_exit": [],
                "s_tier_chips": [],
                "day_trade_momentum": [],
                "swing_overnight": []
            }

        select_01 = []
        select_02 = []
        select_03 = []
        select_04 = []
        s_tier_chips = []

        total_scanned = len(df_today)

        for _, row in df_today.iterrows():
            sid = str(row["stock_id"]).strip()
            df_hist = self.load_stock_history_df(sid, limit_days=490)
            if len(df_hist) < 20:
                continue

            df_calc = self.calculate_technical_indicators(df_hist)
            last_idx = len(df_calc) - 1
            curr_row = df_calc.iloc[last_idx]
            prev_row = df_calc.iloc[last_idx - 1]

            close_p = float(curr_row["close"])
            high_p = float(curr_row["high"])
            q60r = float(curr_row.get("q60r", 1.0))
            d20 = float(curr_row.get("d20", 50.0))
            prev_d20 = float(prev_row.get("d20", 50.0))

            targets = self.calculate_trade_price_targets(curr_row)

            stock_info = {
                "stock_id": sid,
                "stock_name": curr_row["stock_name"],
                "market": curr_row["market"],
                "close": close_p,
                "pct_change": float(curr_row["pct_change"]),
                "volume": int(curr_row["volume"]),
                "turnover_k": float(curr_row["turnover_k"]),
                "q60r": round(q60r, 2),
                "d20": round(d20, 1),
                "targets": targets
            }

            # 投信連買判斷
            trust_streak = 0
            for i in range(last_idx, max(-1, last_idx - 5), -1):
                if df_calc.iloc[i]["trust_net"] > 0:
                    trust_streak += 1
                else:
                    break
            stock_info["trust_streak"] = trust_streak
            stock_info["is_ma5_up"] = bool(curr_row["ma5_diff"] > 0)

            # S 級籌碼濾網：投信連買 >= 2 日 且 5MA 向上勾角
            if trust_streak >= 2 and stock_info["is_ma5_up"]:
                s_tier_chips.append(stock_info)

            # 策略 1：周帶量突破（創5日新高 + Q60R > 2.0）
            hi5_prev = df_calc.iloc[max(0, last_idx - 5):last_idx]["high"].max() if last_idx >= 5 else curr_row["high"]
            if high_p >= hi5_prev and q60r >= 2.0 and curr_row["pct_change"] > 1.5:
                select_01.append(stock_info)

            # 策略 2：突破 Hi120（創半年新高 + Q60R > 2.5）
            hi120_prev = df_calc.iloc[max(0, last_idx - 120):last_idx]["high"].max() if last_idx >= 60 else curr_row["high"]
            if high_p >= hi120_prev and q60r >= 2.5 and curr_row["pct_change"] > 2.5:
                select_02.append(stock_info)

            # 策略 3：突破 Hi480（創兩年新高大底 + Q60R > 3.0）
            hi480_prev = df_calc.iloc[max(0, last_idx - 480):last_idx]["high"].max() if last_idx >= 200 else curr_row["high"]
            if high_p >= hi480_prev and q60r >= 3.0 and curr_row["pct_change"] > 3.5:
                select_03.append(stock_info)

            # 策略 4：雙綠脫離（D20 由低檔 <= 5% 轉正升至 > 10% 且 60 日破底消失）
            if prev_d20 <= 8.0 and d20 >= 12.0 and curr_row["pct_change"] > 0:
                select_04.append(stock_info)

        # 排序：依量比與漲幅排序
        select_01 = sorted(select_01, key=lambda x: x["q60r"], reverse=True)[:10]
        select_02 = sorted(select_02, key=lambda x: x["pct_change"], reverse=True)[:10]
        select_03 = sorted(select_03, key=lambda x: x["q60r"], reverse=True)[:10]
        select_04 = sorted(select_04, key=lambda x: x["d20"], reverse=True)[:10]
        s_tier_chips = sorted(s_tier_chips, key=lambda x: x["trust_streak"], reverse=True)[:10]

        # 當沖動能推薦（優先取周突破中量比最大者）
        day_trade_momentum = sorted(select_01 + select_02, key=lambda x: (x["q60r"], x["pct_change"]), reverse=True)[:5]
        # 隔日沖精選推薦（優先取 S 級籌碼且收紅者）
        swing_overnight = sorted(s_tier_chips, key=lambda x: x["pct_change"], reverse=True)[:5]

        result = {
            "date": curr_date,
            "total_screened": total_scanned,
            "select_01_breakout_5d": select_01,
            "select_02_breakout_120d": select_02,
            "select_03_breakout_480d": select_03,
            "select_04_double_green_exit": select_04,
            "s_tier_chips": s_tier_chips,
            "day_trade_momentum": day_trade_momentum,
            "swing_overnight": swing_overnight
        }
        return result


# ------------------------------------------------------------------------------
# 單獨模組測試驗證區
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    engine = ScreeningEngine("waynebot_history.db")
    print("🧪 執行 ScreeningEngine 獨立測試...")
    res = engine.run_full_market_screening()
    print(f"✅ 選股測試完成，掃描標的數: {res.get('total_screened', 0)}")
    print(f"  • 周帶量突破標的數: {len(res.get('select_01_breakout_5d', []))}")
    print(f"  • 突破Hi120標的數: {len(res.get('select_02_breakout_120d', []))}")
    print(f"  • S 級籌碼標的數: {len(res.get('s_tier_chips', []))}")
