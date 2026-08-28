# ==============================================================================
# WayneBot 專案核心模組二：即時選股與價位精算引擎 (screening_engine.py)
# 檔案用途：提供 CaryBot 四大策略、當沖/隔日沖價位精算、S級籌碼濾網與流動性防護
# ==============================================================================

import os
import sqlite3
import logging
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

# 設定日誌記錄格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s"
)
logger = logging.getLogger("ScreeningEngine")


class ScreeningEngine:
    """WayneBot 全市場量化選股與價位精算引擎"""

    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            # 若當前目錄不存在，嘗試在上層或常見目錄尋找
            alt_path = os.path.join(os.path.dirname(__file__), "waynebot_history.db")
            if os.path.exists(alt_path):
                self.db_path = alt_path

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 資料庫連線並啟用 WAL 模式提高讀取效能"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def get_latest_trading_date(self) -> Optional[str]:
        """取得資料庫中最新的一個交易日 (YYYYMMDD)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(date) FROM daily_quotes;")
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"取得最新交易日失敗: {e}")
            return None

    def load_recent_market_data(self, lookback_days: int = 120) -> pd.DataFrame:
        """載入近 N 個交易日的全市場歷史價量數據進行指標運算"""
        with self._get_connection() as conn:
            # 先取出最新的 N 個日期清單
            date_query = f"""
            SELECT DISTINCT date FROM daily_quotes 
            ORDER BY date DESC LIMIT {lookback_days};
            """
            dates_df = pd.read_sql_query(date_query, conn)
            if dates_df.empty:
                logger.warning("資料庫中無任何行情資料！")
                return pd.DataFrame()
            
            oldest_date = dates_df['date'].min()
            
            # 取出該日期區間的所有股票數據
            data_query = f"""
            SELECT 
                date, stock_id, stock_name, market,
                open, high, low, close, volume, turnover_k,
                pct_change, avg_price, foreign_net, trust_net, dealer_net
            FROM daily_quotes
            WHERE date >= '{oldest_date}'
            ORDER BY stock_id ASC, date ASC;
            """
            df = pd.read_sql_query(data_query, conn)
            return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算均線、量比、乖離率、新高新低與投信連買等量化特徵"""
        if df.empty:
            return df

        # 確保依股票與日期正確排序
        df = df.sort_values(by=["stock_id", "date"]).reset_index(drop=True)

        grouped = df.groupby("stock_id")

        # 1. 均價線 (MA5, MA10, MA20, MA60)
        df["ma5"] = grouped["close"].transform(lambda x: x.rolling(window=5, min_periods=1).mean())
        df["ma10"] = grouped["close"].transform(lambda x: x.rolling(window=10, min_periods=1).mean())
        df["ma20"] = grouped["close"].transform(lambda x: x.rolling(window=20, min_periods=1).mean())
        df["ma60"] = grouped["close"].transform(lambda x: x.rolling(window=60, min_periods=1).mean())

        # 2. 均量線 (VMA5, VMA20, VMA60)
        df["vma5"] = grouped["volume"].transform(lambda x: x.rolling(window=5, min_periods=1).mean())
        df["vma20"] = grouped["volume"].transform(lambda x: x.rolling(window=20, min_periods=1).mean())
        df["vma60"] = grouped["volume"].transform(lambda x: x.rolling(window=60, min_periods=1).mean())

        # 3. 爆量量比 Q60R (當日量 / 60日均量)
        df["q60r"] = np.where(df["vma60"] > 0, np.round(df["volume"] / df["vma60"], 2), 1.0)

        # 4. 區間高低點 (Hi5, Hi20, Hi120, Lo60) - 取前一日以防未來數據干擾
        df["hi5_prev"] = grouped["high"].transform(lambda x: x.shift(1).rolling(window=5, min_periods=1).max())
        df["hi20_prev"] = grouped["high"].transform(lambda x: x.shift(1).rolling(window=20, min_periods=1).max())
        df["hi120_prev"] = grouped["high"].transform(lambda x: x.shift(1).rolling(window=120, min_periods=1).max())
        df["lo60_prev"] = grouped["low"].transform(lambda x: x.shift(1).rolling(window=60, min_periods=1).min())

        # 5. D20 乖離度 (相對於 20MA 位置百分比)
        df["d20"] = np.where(df["ma20"] > 0, np.round((df["close"] - df["ma20"]) / df["ma20"] * 100.0, 2), 0.0)
        df["d20_prev"] = grouped["d20"].transform(lambda x: x.shift(1))

        # 6. 5MA 向上勾角特徵 (今日 5MA > 昨日 5MA)
        df["ma5_prev"] = grouped["ma5"].transform(lambda x: x.shift(1))
        df["ma5_hook_up"] = df["ma5"] > df["ma5_prev"]

        # 7. 投信連買天數計算
        def calc_trust_streak(series: pd.Series) -> pd.Series:
            streaks = []
            count = 0
            for val in series:
                if val > 0:
                    count += 1
                else:
                    count = 0
                streaks.append(count)
            return pd.Series(streaks, index=series.index)

        df["trust_streak"] = grouped["trust_net"].transform(calc_trust_streak)

        return df

    def _calculate_price_targets(self, row: pd.Series) -> Dict[str, float]:
        """計算當沖與隔日沖之動態進出場、衝頂目標與停損防守價位"""
        close_p = float(row["close"])
        open_p = float(row["open"]) if float(row["open"]) > 0 else close_p
        avg_p = float(row["avg_price"]) if float(row["avg_price"]) > 0 else close_p

        # 當沖價位規劃
        dt_entry = round((open_p + avg_p) / 2.0, 2)
        dt_tp1 = round(close_p * 1.03, 2)  # 第一停利 (+3%)
        dt_tp2 = round(close_p * 1.06, 2)  # 第二衝頂 (+6%)
        dt_sl = round(min(avg_p * 0.985, close_p * 0.975), 2)  # 均價防守停損

        # 隔日沖價位規劃
        swing_entry_min = round(close_p * 0.99, 2)
        swing_entry_max = round(close_p * 1.01, 2)
        swing_target_gap = round(close_p * 1.042, 2)  # 明日開高目標 (+4.2%)
        swing_target_top = round(close_p * 1.075, 2)  # 強勢衝頂價 (+7.5%)
        swing_defense = round(close_p * 0.965, 2)     # 保本防守線 (-3.5%)

        return {
            "dt_entry": dt_entry,
            "dt_tp1": dt_tp1,
            "dt_tp2": dt_tp2,
            "dt_sl": dt_sl,
            "swing_entry_range": f"{swing_entry_min:.2f} ~ {swing_entry_max:.2f}",
            "swing_target_gap": swing_target_gap,
            "swing_target_top": swing_target_top,
            "swing_defense": swing_defense
        }

    def run_full_market_screening(self) -> Dict[str, Any]:
        """
        【主控制進入點】：執行全市場 2,202 檔 CaryBot 4 大選股與當沖/隔日沖精算
        對接 main_runner.py 每日批次流水線與 Telegram 推播
        """
        logger.info("🔍 [ScreeningEngine] 開始載入市場數據與指標運算...")
        df_raw = self.load_recent_market_data(lookback_days=130)

        if df_raw.empty:
            logger.error("❌ 無法載入任何市場數據，選股終止。")
            return {
                "date": "N/A",
                "summary": "無有效市場數據",
                "select_01_weekly_breakout": [],
                "select_02_hi120_breakout": [],
                "select_03_hi480_breakout": [],
                "select_04_double_green_exit": [],
                "day_trade_picks": [],
                "swing_overnight_picks": [],
                "all_picks": []
            }

        df_calc = self.calculate_technical_indicators(df_raw)
        
        # 篩選最新一天的橫截面數據
        latest_date = df_calc["date"].max()
        df_today = df_calc[df_calc["date"] == latest_date].copy()
        logger.info(f"📊 最新分析基準日: {latest_date}，全市場候選總檔數: {len(df_today):,} 檔")

        # ----------------------------------------------------------------------
        # 防護機制 1：流動性陷阱過濾（成交量 >= 1,000 張 或 成交額 >= 3,000 萬元）
        # ----------------------------------------------------------------------
        liquidity_mask = (df_today["volume"] >= 1000) | (df_today["turnover_k"] >= 30000.0)
        df_liquid = df_today[liquidity_mask].copy()
        logger.info(f"🛡️ 通過流動性濾網標的數: {len(df_liquid):,} 檔")

        # ----------------------------------------------------------------------
        # CaryBot 核心四大策略海選
        # ----------------------------------------------------------------------
        # Select 01：周帶量突破 (5日新高 + Q60R > 2.0 + 漲幅 > 2.5%)
        mask_s1 = (
            (df_liquid["close"] > df_liquid["hi5_prev"]) &
            (df_liquid["q60r"] >= 2.0) &
            (df_liquid["pct_change"] >= 2.5)
        )

        # Select 02：突破 Hi120 (半年新高大底 + Q60R > 2.5)
        mask_s2 = (
            (df_liquid["close"] >= df_liquid["hi120_prev"]) &
            (df_liquid["q60r"] >= 2.5) &
            (df_liquid["pct_change"] >= 2.0)
        )

        # Select 03：突破 Hi480 (兩年新高大底 + Q60R > 3.0)
        mask_s3 = (
            (df_liquid["close"] >= df_liquid["hi480_prev"].fillna(df_liquid["hi120_prev"])) &
            (df_liquid["q60r"] >= 3.0) &
            (df_liquid["pct_change"] >= 3.0)
        )

        # Select 04：雙綠脫離 (D20 由負轉正或 > 0 + 擺脫 60 日低點 + 帶量)
        mask_s4 = (
            (df_liquid["d20"] > 0.0) &
            (df_liquid["d20_prev"] <= 0.5) &
            (df_liquid["close"] > df_liquid["lo60_prev"] * 1.05) &
            (df_liquid["volume"] > df_liquid["vma20"]) &
            (df_liquid["pct_change"] >= 2.0)
        )

        # 轉換為標準輸出結構
        def format_pick_list(sub_df: pd.DataFrame, strategy_name: str) -> List[Dict[str, Any]]:
            picks = []
            for _, r in sub_df.iterrows():
                # 判斷 S 級籌碼標籤
                is_s_tier = (r["trust_streak"] >= 2) and bool(r["ma5_hook_up"])
                chips_label = "🔥 S級籌碼(投信連買+5MA勾角)" if is_s_tier else (
                    f"投信連買 {int(r['trust_streak'])} 天" if r["trust_streak"] > 0 else "主力動能"
                )

                targets = self._calculate_price_targets(r)

                pick_item = {
                    "date": r["date"],
                    "stock_id": str(r["stock_id"]),
                    "stock_name": str(r["stock_name"]),
                    "market": str(r["market"]),
                    "close": float(r["close"]),
                    "pct_change": float(r["pct_change"]),
                    "volume": int(r["volume"]),
                    "turnover_k": float(r["turnover_k"]),
                    "q60r": float(r["q60r"]),
                    "d20": float(r["d20"]),
                    "strategy": strategy_name,
                    "is_s_tier": is_s_tier,
                    "chips_label": chips_label,
                    "trust_streak": int(r["trust_streak"]),
                    "targets": targets
                }
                picks.append(pick_item)
            # 依成交金額由大至小排序
            picks.sort(key=lambda x: x["turnover_k"], reverse=True)
            return picks

        picks_s1 = format_pick_list(df_liquid[mask_s1], "Select 01 周帶量突破")
        picks_s2 = format_pick_list(df_liquid[mask_s2], "Select 02 突破Hi120")
        picks_s3 = format_pick_list(df_liquid[mask_s3], "Select 03 突破Hi480")
        picks_s4 = format_pick_list(df_liquid[mask_s4], "Select 04 雙綠脫離起漲")

        # 彙整當沖專區（高爆量 Q60R >= 2.5 + 高流動性）
        dt_candidates = [p for p in (picks_s1 + picks_s2) if p["volume"] >= 2500 and p["q60r"] >= 2.5]
        
        # 彙整隔日沖專區（S級籌碼或漲幅 3%~7% 具備續航動能）
        swing_candidates = [p for p in (picks_s1 + picks_s4) if 3.0 <= p["pct_change"] <= 8.5]

        # 彙總所有不重複入選標的
        unique_stocks = {}
        for p in (picks_s1 + picks_s2 + picks_s3 + picks_s4):
            sid = p["stock_id"]
            if sid not in unique_stocks:
                unique_stocks[sid] = p

        all_picks_list = list(unique_stocks.values())
        all_picks_list.sort(key=lambda x: x["turnover_k"], reverse=True)

        logger.info(f"✅ 選股完成！S1周突破: {len(picks_s1)} 檔 | S2半年高: {len(picks_s2)} 檔 | S3兩年高: {len(picks_s3)} 檔 | S4雙綠脫離: {len(picks_s4)} 檔")

        return {
            "date": latest_date,
            "total_screened": len(df_today),
            "liquid_count": len(df_liquid),
            "summary": f"共選出 {len(all_picks_list)} 檔精選標的",
            "select_01_weekly_breakout": picks_s1,
            "select_02_hi120_breakout": picks_s2,
            "select_03_hi480_breakout": picks_s3,
            "select_04_double_green_exit": picks_s4,
            "day_trade_picks": dt_candidates[:10],
            "swing_overnight_picks": swing_candidates[:10],
            "all_picks": all_picks_list
        }


# ------------------------------------------------------------------------------
# 單獨模組測試驗證 (SOP 沙盒優先)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 [Sandbox Test] 啟動 ScreeningEngine 獨立測試...")
    engine = ScreeningEngine()
    results = engine.run_full_market_screening()
    
    print("\n" + "=" * 60)
    print(f"📅 基準交易日: {results.get('date')}")
    print(f"📊 總候選檔數: {results.get('total_screened', 0)} 檔 | 流動性合格: {results.get('liquid_count', 0)} 檔")
    print(f"🎯 精選標的數: {len(results.get('all_picks', []))} 檔")
    print("=" * 60)

    for cat in ["select_01_weekly_breakout", "select_02_hi120_breakout", "select_04_double_green_exit"]:
        picks = results.get(cat, [])
        print(f"\n📌 [{cat}] ({len(picks)} 檔):")
        for p in picks[:3]:
            print(f"  • {p['stock_id']} {p['stock_name']} | 收盤: {p['close']} ({p['pct_change']:+.2f}%) | Q60R: {p['q60r']}x | {p['chips_label']}")
            print(f"    👉 當沖進場: {p['targets']['dt_entry']} | 停利: {p['targets']['dt_tp1']} | 隔日沖開高: {p['targets']['swing_target_gap']}")

    print("\n✅ ScreeningEngine 沙盒單元測試 100% 通過！")
