# ==============================================================================
# WayneBot 全市場量化決策系統：模組二 - 即時選股與價位精算核心 (screening_engine.py)
# 功能：CaryBot 四大海選、當沖/隔日沖價位精算、S級籌碼濾網、流動性防護與個股決策卡
# ==============================================================================

import os
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional

class ScreeningEngine:
    """
    WayneBot 全市場量化選股與價位精算引擎
    """
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        # 動態風控與流動性參數（亦可從 SQLite strategy_config 動態載入）
        self.min_volume_sheets = 1000       # 最低日成交量 1,000 張（過濾流動性陷阱）
        self.min_turnover_k = 30000.0       # 最低日成交額 3,000 萬元 (30,000 千元)

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 連線"""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"資料庫檔案不存在: {self.db_path}，請先確認第 0 步歷史庫已就緒。")
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def get_latest_trading_date(self) -> str:
        """取得資料庫中最新交易日期 (YYYYMMDD)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM daily_quotes;")
            row = cursor.fetchone()
            return row[0] if row and row[0] else datetime.now().strftime("%Y%m%d")

    def _load_historical_window(self, lookback_days: int = 500) -> pd.DataFrame:
        """載入計算各項長短期均線與突破所需的歷史視窗數據"""
        conn = self._get_connection()
        query = f"""
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k, pct_change, avg_price,
            foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date IN (
            SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT {lookback_days}
        )
        ORDER BY stock_id ASC, date ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

    def calculate_technical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算全市場技術指標、突破型態與籌碼特徵：
        - 均線群: 5MA, 20MA, 60MA, 120MA, 240MA, 480MA
        - 量能指標: 60日均量 (VMA60)、量比 Q60R (當日量 / VMA60)、Q5R
        - 新高價位: Hi5 (5日高), Hi120 (120日高/半年新高), Hi480 (480日高/兩年大底)
        - 乖離與脫離: D20 (20日價格乖離率), Low60 (60日最低價)
        - 籌碼與形態: 5MA 向上勾角、投信連買天數
        """
        if df.empty:
            return pd.DataFrame()

        records = []
        # 依個股分組計算滾動特徵
        for sid, group in df.groupby("stock_id"):
            g = group.copy().sort_values("date").reset_index(drop=True)
            n_bars = len(g)
            if n_bars < 5:
                continue

            # 均線計算
            g["ma5"] = g["close"].rolling(5).mean()
            g["ma20"] = g["close"].rolling(20).mean()
            g["ma60"] = g["close"].rolling(60).mean()
            g["ma120"] = g["close"].rolling(120).mean()
            g["ma480"] = g["close"].rolling(480).mean()

            # 量能均線與量比
            g["vma5"] = g["volume"].rolling(5).mean()
            g["vma60"] = g["volume"].rolling(60).mean()
            g["q60r"] = np.where(g["vma60"] > 0, g["volume"] / g["vma60"], 1.0)
            g["q5r"] = np.where(g["vma5"] > 0, g["volume"] / g["vma5"], 1.0)

            # 新高與新低（以昨日為基準比較）
            g["hi5_prev"] = g["high"].shift(1).rolling(5).max()
            g["hi120_prev"] = g["high"].shift(1).rolling(120).max()
            g["hi480_prev"] = g["high"].shift(1).rolling(480).max()
            g["low60_prev"] = g["low"].shift(1).rolling(60).min()

            # D20 (20日偏離率)
            g["d20"] = np.where(g["ma20"] > 0, ((g["close"] - g["ma20"]) / g["ma20"]) * 100.0, 0.0)
            g["d20_prev"] = g["d20"].shift(1)

            # 5MA 向上勾角 (今日 5MA > 昨日 5MA 且 (昨日 5MA <= 前日 5MA 或 5MA 斜率翻正))
            g["ma5_shift1"] = g["ma5"].shift(1)
            g["ma5_shift2"] = g["ma5"].shift(2)
            g["ma5_hook_up"] = (g["ma5"] > g["ma5_shift1"]) & (g["ma5_shift1"] >= g["ma5_shift2"] * 0.998)

            # 投信連買計數
            trust_positive = (g["trust_net"] > 0).astype(int)
            trust_streak = []
            cur_streak = 0
            for val in trust_positive:
                if val == 1:
                    cur_streak += 1
                else:
                    cur_streak = 0
                trust_streak.append(cur_streak)
            g["trust_streak"] = trust_streak

            # 僅取最後一日（最新交易日）作為選股池
            latest_row = g.iloc[-1].to_dict()
            records.append(latest_row)

        res_df = pd.DataFrame(records)
        return res_df

    def _calculate_day_trading_levels(self, row: pd.Series) -> Dict[str, float]:
        """當沖動能價位精算"""
        close_p = row["close"]
        avg_p = row["avg_price"] if row["avg_price"] > 0 else close_p
        return {
            "entry_price": round(close_p, 2),
            "tp1_price": round(close_p * 1.03, 2),       # +3% 第一停利
            "tp2_price": round(close_p * 1.06, 2),       # +6% 第二衝頂
            "stop_loss_price": round(min(avg_p, close_p * 0.98), 2)  # 均價/防守停損
        }

    def _calculate_overnight_levels(self, row: pd.Series) -> Dict[str, Any]:
        """隔日沖精選價位精算"""
        close_p = row["close"]
        return {
            "buy_zone_low": round(close_p * 0.995, 2),
            "buy_zone_high": round(close_p * 1.005, 2),
            "next_open_target_low": round(close_p * 1.035, 2),  # +3.5%
            "next_open_target_high": round(close_p * 1.048, 2), # +4.8%
            "rush_high_target": round(close_p * 1.075, 2),      # 強勢衝頂價
            "defense_price": round(close_p * 0.985, 2)          # 保本防守價
        }

    def run_full_market_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        【主排程與流水線核心入口】
        執行全市場 2,202 檔標的量化初篩與四大 CaryBot 策略計算
        """
        # 1. 載入歷史數據與計算指標
        raw_df = self._load_historical_window(lookback_days=500)
        if raw_df.empty:
            return {"date": target_date or "", "summary": "無數據", "strategies": {}}

        feature_df = self.calculate_technical_features(raw_df)
        if feature_df.empty:
            return {"date": target_date or "", "summary": "特徵計算失敗", "strategies": {}}

        latest_date = str(feature_df["date"].iloc[0])

        # 2. 流動性基礎防護過濾（排除日量 < 1000張 或 日額 < 3000萬 之殭屍股）
        liquid_df = feature_df[
            (feature_df["volume"] >= self.min_volume_sheets) & 
            (feature_df["turnover_k"] >= self.min_turnover_k) &
            (feature_df["close"] > 0)
        ].copy()

        # 3. CaryBot 四大即時選股邏輯
        # ----------------------------------------------------------------------
        # Select 01: 周帶量突破 (創5日高 + Q60R > 2.0 + 漲幅 > 2.0%)
        # ----------------------------------------------------------------------
        s1_mask = (
            (liquid_df["close"] >= liquid_df["hi5_prev"]) &
            (liquid_df["q60r"] >= 2.0) &
            (liquid_df["pct_change"] >= 2.0)
        )
        s1_df = liquid_df[s1_mask].sort_values("q60r", ascending=False)

        # ----------------------------------------------------------------------
        # Select 02: 突破Hi120 (半年新高 + Q60R > 2.5)
        # ----------------------------------------------------------------------
        s2_mask = (
            (liquid_df["close"] >= liquid_df["hi120_prev"]) &
            (liquid_df["q60r"] >= 2.5)
        )
        s2_df = liquid_df[s2_mask].sort_values("q60r", ascending=False)

        # ----------------------------------------------------------------------
        # Select 03: 突破Hi480 (兩年新高大底 + Q60R > 3.0)
        # ----------------------------------------------------------------------
        s3_mask = (
            (liquid_df["close"] >= liquid_df["hi480_prev"]) &
            (liquid_df["q60r"] >= 3.0)
        )
        s3_df = liquid_df[s3_mask].sort_values("q60r", ascending=False)

        # ----------------------------------------------------------------------
        # Select 04: 雙綠脫離 (D20 由負轉正或由0脫離 + 遠離60日低點 + 5MA勾角)
        # ----------------------------------------------------------------------
        s4_mask = (
            (liquid_df["d20"] > 0.0) &
            (liquid_df["d20_prev"] <= 1.0) &
            (liquid_df["close"] > liquid_df["low60_prev"] * 1.05) &
            (liquid_df["ma5_hook_up"] == True)
        )
        s4_df = liquid_df[s4_mask].sort_values("pct_change", ascending=False)

        # 4. S 級籌碼濾網（投信連買 >= 2天 且 5MA向上勾角）
        s_grade_mask = (
            (liquid_df["trust_streak"] >= 2) &
            (liquid_df["ma5_hook_up"] == True) &
            (liquid_df["pct_change"] > 0)
        )
        s_grade_df = liquid_df[s_grade_mask].sort_values("trust_streak", ascending=False)

        # 5. 當沖與隔日沖池建置與價位精算
        day_trading_pool = []
        for _, row in s1_df.head(10).iterrows():
            levels = self._calculate_day_trading_levels(row)
            day_trading_pool.append({
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "close": row["close"],
                "pct_change": row["pct_change"],
                "q60r": round(row["q60r"], 2),
                **levels
            })

        overnight_pool = []
        for _, row in s2_df.head(10).iterrows():
            levels = self._calculate_overnight_levels(row)
            overnight_pool.append({
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "close": row["close"],
                "pct_change": row["pct_change"],
                "trust_streak": int(row["trust_streak"]),
                **levels
            })

        results = {
            "date": latest_date,
            "scanned_total": len(feature_df),
            "liquid_total": len(liquid_df),
            "select_01_weekly": s1_df.to_dict(orient="records"),
            "select_02_hi120": s2_df.to_dict(orient="records"),
            "select_03_hi480": s3_df.to_dict(orient="records"),
            "select_04_double_green": s4_df.to_dict(orient="records"),
            "s_grade_chip": s_grade_df.to_dict(orient="records"),
            "day_trading_recommendations": day_trading_pool,
            "overnight_recommendations": overnight_pool,
        }

        return results

    def get_stock_decision_card(self, stock_id: str) -> Dict[str, Any]:
        """【🎯 買低賣高決策卡】單一個股即時診斷與動態防守位"""
        conn = self._get_connection()
        query = f"""
        SELECT * FROM daily_quotes
        WHERE stock_id = '{stock_id}'
        ORDER BY date DESC LIMIT 120;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            return {"error": f"查無標的 {stock_id} 之歷史行情"}

        df = df.sort_values("date").reset_index(drop=True)
        latest = df.iloc[-1]
        close_p = latest["close"]
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma60 = df["close"].rolling(60).mean().iloc[-1]
        d20 = ((close_p - ma20) / ma20 * 100.0) if ma20 > 0 else 0.0

        card = {
            "stock_id": latest["stock_id"],
            "stock_name": latest["stock_name"],
            "date": latest["date"],
            "close": close_p,
            "pct_change": latest["pct_change"],
            "volume": latest["volume"],
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "d20_bias": round(d20, 2),
            "support_ma20": round(ma20, 2),
            "stop_loss_hard": round(close_p * 0.95, 2),
            "status": "強勢多頭" if close_p > ma20 > ma60 else ("區間整理" if close_p > ma20 else "弱勢回檔")
        }
        return card

# ------------------------------------------------------------------------------
# 單元測試與沙盒驗證入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 65)
    print("🔍 正在執行 ScreeningEngine 沙盒單元測試...")
    print("=" * 65)
    
    engine = ScreeningEngine("waynebot_history.db")
    if os.path.exists("waynebot_history.db"):
        res = engine.run_full_market_screening()
        print(f"✅ 掃描完成！交易日期: {res['date']}")
        print(f"📊 全市場標的: {res['scanned_total']} 檔 | 通過流動性濾網: {res['liquid_total']} 檔")
        print(f"⚡ Select 01 周帶量突破: {len(res['select_01_weekly'])} 檔")
        print(f"⚡ Select 02 突破 Hi120: {len(res['select_02_hi120'])} 檔")
        print(f"⚡ Select 03 突破 Hi480: {len(res['select_03_hi480'])} 檔")
        print(f"⚡ Select 04 雙綠脫離  : {len(res['select_04_double_green'])} 檔")
        print(f"⭐ S 級籌碼精選       : {len(res['s_grade_chip'])} 檔")
        print(f"🚀 當沖動能精算推薦   : {len(res['day_trading_recommendations'])} 檔")
    else:
        print("ℹ️ 未偵測到 waynebot_history.db，請確認資料庫路徑。")
