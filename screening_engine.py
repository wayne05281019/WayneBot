# ==============================================================================
# WayneBot 全市場量化決策系統：選股與價位精算引擎 (screening_engine.py)
# ==============================================================================

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

# 設定日誌記錄
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s"
)
logger = logging.getLogger("ScreeningEngine")


class ScreeningEngine:
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self.config = self._load_strategy_config()

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 連線並啟用 WAL 模式提高讀取效率"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _load_strategy_config(self) -> Dict[str, float]:
        """從資料庫 strategy_config 表讀取動態參數，若無則採用標準設定"""
        default_config = {
            "min_volume_sheets": 1000.0,    # 最低成交量 (張)
            "min_turnover_k": 30000.0,      # 最低成交額 (千元，即 3,000 萬)
            "q60r_select01": 2.0,           # Select 01 量比門檻
            "q60r_select02": 2.5,           # Select 02 量比門檻
            "q60r_select03": 3.0,           # Select 03 量比門檻
            "day_trade_tp1_pct": 3.0,       # 當沖第一停利 %
            "day_trade_tp2_pct": 6.0,       # 當沖第二衝頂 %
            "swing_target_min_pct": 3.5,    # 隔日沖開高低標 %
            "swing_target_max_pct": 4.8,    # 隔日沖開高高標 %
        }
        if not os.path.exists(self.db_path):
            return default_config

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_config (
                    param_key TEXT PRIMARY KEY,
                    param_value REAL,
                    updated_at TEXT
                );
            """)
            cursor.execute("SELECT param_key, param_value FROM strategy_config;")
            rows = cursor.fetchall()
            conn.close()

            for k, v in rows:
                if k in default_config:
                    default_config[k] = float(v)
        except Exception as e:
            logger.warning(f"載入 strategy_config 失敗，採用預設參數: {e}")

        return default_config

    def _get_latest_dates(self, conn: sqlite3.Connection, limit: int = 130) -> List[str]:
        """取得資料庫中最新 N 個交易日列表 (升冪排序)"""
        df_dates = pd.read_sql_query(
            f"SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT {limit};",
            conn
        )
        if df_dates.empty:
            return []
        return sorted(df_dates["date"].tolist())

    def _calculate_indicators(self, df_stock: pd.DataFrame) -> pd.DataFrame:
        """針對單一標的計算技術指標與統計特徵"""
        df = df_stock.sort_values("date").copy()
        
        # 均線
        df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
        df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()
        df["ma60"] = df["close"].rolling(window=60, min_periods=1).mean()
        df["ma120"] = df["close"].rolling(window=120, min_periods=1).mean()

        # 量均線與 60 日量比 (Q60R)
        df["vma60"] = df["volume"].rolling(window=60, min_periods=1).mean()
        df["q60r"] = np.where(df["vma60"] > 0, df["volume"] / df["vma60"], 1.0)

        # 區間極值 (排除當日以前的 rolling max)
        df["hi5_prev"] = df["high"].shift(1).rolling(window=5, min_periods=1).max()
        df["hi120_prev"] = df["high"].shift(1).rolling(window=120, min_periods=1).max()
        df["hi480_prev"] = df["high"].shift(1).rolling(window=480, min_periods=1).max()
        df["low60_prev"] = df["low"].shift(1).rolling(window=60, min_periods=1).min()

        # D20 乖離率 (%)
        df["d20"] = np.where(df["ma20"] > 0, ((df["close"] - df["ma20"]) / df["ma20"]) * 100.0, 0.0)
        df["d20_prev"] = df["d20"].shift(1)

        # 5MA 勾角判斷 (今日 5MA > 昨日 5MA)
        df["ma5_prev"] = df["ma5"].shift(1)
        df["ma5_hook_up"] = (df["ma5"] > df["ma5_prev"])

        # 投信連買計數
        df["trust_buy_streak"] = (df["trust_net"] > 0).astype(int)
        # 計算最近連續正買超天數
        trust_streaks = []
        streak = 0
        for val in df["trust_net"]:
            if val > 0:
                streak += 1
            else:
                streak = 0
            trust_streaks.append(streak)
        df["trust_streak"] = trust_streaks

        return df

    def _calc_day_trade_targets(self, row: pd.Series) -> Dict[str, float]:
        """計算當沖精算價位"""
        close_p = float(row["close"])
        avg_p = float(row["avg_price"]) if row["avg_price"] > 0 else close_p
        tp1_pct = self.config["day_trade_tp1_pct"]
        tp2_pct = self.config["day_trade_tp2_pct"]

        return {
            "entry_price": close_p,
            "take_profit_1": round(close_p * (1.0 + tp1_pct / 100.0), 2),
            "take_profit_2": round(close_p * (1.0 + tp2_pct / 100.0), 2),
            "stop_loss_price": round(min(avg_p, close_p * 0.98), 2)
        }

    def _calc_overnight_targets(self, row: pd.Series) -> Dict[str, Any]:
        """計算隔日沖精算價位"""
        close_p = float(row["close"])
        t_min_pct = self.config["swing_target_min_pct"]
        t_max_pct = self.config["swing_target_max_pct"]

        return {
            "buy_zone": f"{round(close_p * 0.995, 2)} ~ {round(close_p * 1.005, 2)}",
            "target_open_range": f"{round(close_p * (1.0 + t_min_pct / 100.0), 2)} ~ {round(close_p * (1.0 + t_max_pct / 100.0), 2)}",
            "strong_target": round(close_p * 1.07, 2),
            "defense_price": round(close_p * 0.985, 2)
        }

    def run_full_market_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        【主排程調用入口】：執行全市場多策略選股掃描
        回傳結構相容 main_runner.py、Telegram Bot 與自選監控模組
        """
        logger.info("🔍 開始執行 WayneBot 全市場量化選股掃描...")
        if not os.path.exists(self.db_path):
            logger.error(f"❌ 找不到歷史資料庫: {self.db_path}")
            return {
                "date": target_date or "",
                "total_scanned": 0,
                "select_01_weekly": [],
                "select_02_hi120": [],
                "select_03_hi480": [],
                "select_04_double_green": [],
                "day_trade": [],
                "overnight_swing": [],
                "s_tier_chips": []
            }

        conn = self._get_connection()
        dates = self._get_latest_dates(conn, limit=130)

        if not dates:
            logger.error("❌ 資料庫中無有效交易日數據！")
            conn.close()
            return {"date": "", "total_scanned": 0}

        latest_date = target_date if (target_date and target_date in dates) else dates[-1]
        logger.info(f"📊 選定掃描基準交易日: {latest_date} (歷史視窗: {dates[0]} ~ {dates[-1]})")

        # 讀取所需歷史區間的全部報價
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date >= '{dates[0]}' AND date <= '{latest_date}'
        ORDER BY stock_id, date ASC;
        """
        df_all = pd.read_sql_query(query, conn)
        conn.close()

        if df_all.empty:
            logger.warning("⚠️ 查無任何交易記錄！")
            return {"date": latest_date, "total_scanned": 0}

        # 儲存篩選結果清單
        res_select_01 = []
        res_select_02 = []
        res_select_03 = []
        res_select_04 = []
        res_day_trade = []
        res_overnight = []
        res_s_tier = []

        grouped = df_all.groupby("stock_id")
        scanned_count = 0

        min_vol = self.config["min_volume_sheets"]
        min_to_k = self.config["min_turnover_k"]

        for stock_id, df_stock in grouped:
            # 確保最新日有資料且有一定長度
            if df_stock.iloc[-1]["date"] != latest_date or len(df_stock) < 10:
                continue

            scanned_count += 1
            df_ind = self._calculate_indicators(df_stock)
            curr = df_ind.iloc[-1]

            # ------------------------------------------------------------------
            # 1. 流動性過濾 (日量 >= 1000 張 或 日成交額 >= 3,000 萬)
            # ------------------------------------------------------------------
            is_liquid = (curr["volume"] >= min_vol) or (curr["turnover_k"] >= min_to_k)
            if not is_liquid:
                continue

            item_info = {
                "stock_id": str(curr["stock_id"]),
                "stock_name": str(curr["stock_name"]),
                "market": str(curr["market"]),
                "close": float(curr["close"]),
                "pct_change": float(curr["pct_change"]),
                "volume": int(curr["volume"]),
                "turnover_k": float(curr["turnover_k"]),
                "q60r": round(float(curr["q60r"]), 2),
                "d20": round(float(curr["d20"]), 2),
                "trust_net": int(curr["trust_net"]),
                "foreign_net": int(curr["foreign_net"]),
                "trust_streak": int(curr["trust_streak"]),
            }

            # ------------------------------------------------------------------
            # 2. CaryBot 四大策略篩選
            # ------------------------------------------------------------------
            # Select 01: 周帶量突破 (收盤 > 前5日最高 且 Q60R > 2.0 且 漲幅 > 1.5%)
            if (curr["close"] > curr["hi5_prev"]) and (curr["q60r"] >= self.config["q60r_select01"]) and (curr["pct_change"] > 1.5):
                res_select_01.append(item_info)

            # Select 02: 突破Hi120 (半年新高 且 Q60R > 2.5)
            if (curr["close"] >= curr["hi120_prev"]) and (curr["q60r"] >= self.config["q60r_select02"]) and (curr["pct_change"] > 2.0):
                res_select_02.append(item_info)

            # Select 03: 突破Hi480 (兩年新高大底 且 Q60R > 3.0)
            if (curr["hi480_prev"] > 0) and (curr["close"] >= curr["hi480_prev"]) and (curr["q60r"] >= self.config["q60r_select03"]):
                res_select_03.append(item_info)

            # Select 04: 雙綠脫離 (D20 由負轉正 或 脫離近60日低點 且 收紅)
            if (curr["d20_prev"] <= 0 and curr["d20"] > 0) and (curr["pct_change"] > 0):
                res_select_04.append(item_info)

            # ------------------------------------------------------------------
            # 3. S 級籌碼專區 (投信連買 >= 2 天 + 5MA 向上勾角)
            # ------------------------------------------------------------------
            if (curr["trust_streak"] >= 2) and (curr["ma5_hook_up"]):
                s_item = dict(item_info)
                s_item["reason"] = f"投信連買 {curr['trust_streak']} 天 + 5MA 向上翻揚"
                res_s_tier.append(s_item)

            # ------------------------------------------------------------------
            # 4. 當沖動能專區 (漲幅 2.5%~7.5%、量比 > 1.8、附帶精算價位)
            # ------------------------------------------------------------------
            if (2.5 <= curr["pct_change"] <= 7.5) and (curr["q60r"] >= 1.8):
                dt_item = dict(item_info)
                dt_item.update(self._calc_day_trade_targets(curr))
                res_day_trade.append(dt_item)

            # ------------------------------------------------------------------
            # 5. 隔日沖精選專區 (收盤接近最高、量增紅棒、附帶買進與次日開高區間)
            # ------------------------------------------------------------------
            is_near_high = (curr["high"] > 0) and ((curr["close"] / curr["high"]) >= 0.985)
            if is_near_high and (curr["pct_change"] >= 3.0) and (curr["q60r"] >= 1.5):
                sw_item = dict(item_info)
                sw_item.update(self._calc_overnight_targets(curr))
                res_overnight.append(sw_item)

        # 排序：依量比 (Q60R) 與漲幅降冪排列
        res_select_01.sort(key=lambda x: (x["q60r"], x["pct_change"]), reverse=True)
        res_select_02.sort(key=lambda x: (x["q60r"], x["pct_change"]), reverse=True)
        res_select_03.sort(key=lambda x: (x["q60r"], x["pct_change"]), reverse=True)
        res_select_04.sort(key=lambda x: (x["pct_change"], x["q60r"]), reverse=True)
        res_day_trade.sort(key=lambda x: x["q60r"], reverse=True)
        res_overnight.sort(key=lambda x: x["pct_change"], reverse=True)
        res_s_tier.sort(key=lambda x: (x["trust_streak"], x["turnover_k"]), reverse=True)

        logger.info(f"✅ 選股掃描完成！掃描檔數: {scanned_count} 檔")
        logger.info(f"   • Select 01 周帶量突破 : {len(res_select_01)} 檔")
        logger.info(f"   • Select 02 突破Hi120   : {len(res_select_02)} 檔")
        logger.info(f"   • Select 03 突破Hi480   : {len(res_select_03)} 檔")
        logger.info(f"   • Select 04 雙綠脫離   : {len(res_select_04)} 檔")
        logger.info(f"   • S 級籌碼強勢標的     : {len(res_s_tier)} 檔")
        logger.info(f"   • 當沖精選候選池       : {len(res_day_trade)} 檔")
        logger.info(f"   • 隔日沖精選候選池     : {len(res_overnight)} 檔")

        return {
            "date": latest_date,
            "total_scanned": scanned_count,
            "select_01_weekly": res_select_01,
            "select_02_hi120": res_select_02,
            "select_03_hi480": res_select_03,
            "select_04_double_green": res_select_04,
            "day_trade": res_day_trade,
            "overnight_swing": res_overnight,
            "s_tier_chips": res_s_tier
        }


# ------------------------------------------------------------------------------
# 單獨模組測試入口 (可直接 python screening_engine.py 進行沙盒驗證)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    engine = ScreeningEngine(db_path="waynebot_history.db")
    results = engine.run_full_market_screening()
    print("\n" + "=" * 60)
    print(f"📊 WayneBot 模組單獨測試報告 ({results.get('date', 'N/A')})")
    print("=" * 60)
    print(f"總掃描標的數: {results.get('total_scanned', 0)} 檔")
    for category in ["select_01_weekly", "select_02_hi120", "s_tier_chips", "day_trade", "overnight_swing"]:
        items = results.get(category, [])
        print(f"\n【{category}】命中 {len(items)} 檔 (前 3 檔範例):")
        for it in items[:3]:
            print(f"  • [{it['stock_id']}] {it['stock_name']} | 收盤: {it['close']} ({it['pct_change']:+.2f}%) | 量比: {it['q60r']}x | 投信: {it['trust_net']}張")
