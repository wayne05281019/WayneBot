# ==============================================================================
# WayneBot 全市場量化決策系統：核心選股與價位精算引擎 (screening_engine.py)
# 核心功能：CaryBot 四大選股策略、S級籌碼濾網、當沖/隔日沖動能精算、流動性防護
# ==============================================================================

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s"
)
logger = logging.getLogger("ScreeningEngine")


class ScreeningEngine:
    def __init__(self, db_path: str = "waynebot_history.db"):
        """
        初始化選股引擎
        :param db_path: SQLite 資料庫路徑
        """
        self.db_path = db_path
        # 流動性防護門檻
        self.min_volume_sheets = 1000       # 每日最低成交量 1,000 張
        self.min_turnover_k = 30000.0       # 每日最低成交額 3,000 萬元 (30,000 千元)

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 唯讀或快速連線"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def get_latest_trading_date(self) -> Optional[str]:
        """從資料庫獲取最新交易日期 (YYYYMMDD)"""
        if not os.path.exists(self.db_path):
            logger.error(f"資料庫檔案不存在: {self.db_path}")
            return None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM daily_quotes;")
            row = cursor.fetchone()
            conn.close()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"獲取最新交易日失敗: {e}")
            return None

    def _calculate_price_targets(self, close_p: float, avg_p: float) -> Dict[str, Any]:
        """
        當沖與隔日沖動能價位精算
        :param close_p: 當日收盤價
        :param avg_p: 當日成交均價
        :return: 包含進場、停利、衝頂、防守線的字典
        """
        base_p = close_p if close_p > 0 else 1.0
        avg_base = avg_p if avg_p > 0 else base_p

        # 當沖動能指標
        day_trade = {
            "entry_price": round(base_p, 2),
            "take_profit_1": round(base_p * 1.03, 2),       # 第一停利 (+3%)
            "take_profit_2": round(base_p * 1.06, 2),       # 第二衝頂 (+6%)
            "stop_loss": round(avg_base, 2)                 # 均價停損價
        }

        # 隔日沖精選指標
        overnight_swing = {
            "buy_range_low": round(base_p * 0.99, 2),       # 買進區間下緣
            "buy_range_high": round(base_p * 1.005, 2),     # 買進區間上緣
            "target_open_min": round(base_p * 1.035, 2),    # 明日開高目標下緣 (+3.5%)
            "target_open_max": round(base_p * 1.048, 2),    # 明日開高目標上緣 (+4.8%)
            "target_surge": round(base_p * 1.085, 2),       # 強勢衝頂價 (+8.5%)
            "defense_price": round(avg_base * 0.99, 2)      # 保本防守價
        }

        return {
            "day_trade": day_trade,
            "overnight_swing": overnight_swing
        }

    def run_full_market_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        【主控制流水線進入點】執行全市場量化選股掃描
        :param target_date: 指定掃描日期 (YYYYMMDD)，若無則自動取資料庫最新日期
        :return: 包含各策略清單與統計之完整字典
        """
        if not os.path.exists(self.db_path):
            logger.error(f"❌ 選股失敗：找不到歷史資料庫 {self.db_path}")
            return {
                "status": "error",
                "message": f"Database not found: {self.db_path}",
                "date": None,
                "total_scanned": 0,
                "results": {}
            }

        conn = self._get_connection()

        # 確認目標日期
        if not target_date:
            target_date = self.get_latest_trading_date()
        
        if not target_date:
            logger.error("❌ 無法確定有效交易日期")
            conn.close()
            return {"status": "error", "message": "No valid trading date found"}

        logger.info(f"🔍 開始執行全市場量化選股掃描 (基準日: {target_date})...")

        # 1. 取得近 480 交易日之歷史行情數據
        query = """
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k, pct_change, avg_price,
            foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date <= ?
        ORDER BY stock_id, date ASC;
        """
        df = pd.read_sql_query(query, conn, params=(target_date,))
        conn.close()

        if df.empty:
            logger.warning(f"⚠️ 日期 {target_date} 無任何行情數據")
            return {
                "status": "empty",
                "date": target_date,
                "total_scanned": 0,
                "select_01_weekly_breakout": [],
                "select_02_hi120_breakout": [],
                "select_03_hi480_breakout": [],
                "select_04_double_green_breakout": [],
                "s_tier_picks": [],
                "day_trade_momentum": [],
                "overnight_swing": []
            }

        # 2. 分組計算技術與量能指標
        grouped = df.groupby("stock_id")
        total_stocks = len(grouped)

        # 策略清單容器
        select_01_list = []  # Select 01 周帶量突破
        select_02_list = []  # Select 02 突破Hi120
        select_03_list = []  # Select 03 突破Hi480
        select_04_list = []  # Select 04 雙綠脫離
        s_tier_list = []     # S 級最高勝率標的
        day_trade_list = []  # 當沖動能名單
        swing_list = []      # 隔日沖精選名單

        for stock_id, group in grouped:
            if len(group) < 5:
                continue

            # 最新一筆資料（當日）
            latest = group.iloc[-1]
            if str(latest["date"]) != str(target_date):
                continue

            # 【防護機制 1】：流動性過濾（排除成交量 < 1000 張 且 成交金額 < 3000 萬之冷門股）
            vol = float(latest["volume"])
            turnover_k = float(latest["turnover_k"])
            if vol < self.min_volume_sheets and turnover_k < self.min_turnover_k:
                continue

            close_p = float(latest["close"])
            open_p = float(latest["open"])
            high_p = float(latest["high"])
            low_p = float(latest["low"])
            avg_p = float(latest["avg_price"])
            pct_chg = float(latest["pct_change"])
            trust_net = int(latest["trust_net"])
            foreign_net = int(latest["foreign_net"])
            stock_name = str(latest["stock_name"])
            market = str(latest["market"])

            if close_p <= 0:
                continue

            # 計算 60MA 量比 (Q60R)
            vol_series = group["volume"].values
            vol_ma60 = np.mean(vol_series[-60:]) if len(vol_series) >= 60 else np.mean(vol_series)
            q60r = round(vol / vol_ma60, 2) if vol_ma60 > 0 else 1.0

            # 計算 5MA 及趨勢
            close_series = group["close"].values
            ma5 = np.mean(close_series[-5:]) if len(close_series) >= 5 else close_p
            ma5_prev = np.mean(close_series[-6:-1]) if len(close_series) >= 6 else ma5
            is_ma5_up = (ma5 > ma5_prev) and (close_p >= ma5)

            # 計算投信連買天數
            trust_series = group["trust_net"].values
            trust_consecutive_days = 0
            for t_val in reversed(trust_series):
                if t_val > 0:
                    trust_consecutive_days += 1
                else:
                    break

            # S 級籌碼認定：投信連買 >= 2 天 或 投信當日大買 + 5MA 向上勾角
            is_s_tier = (trust_consecutive_days >= 2 or (trust_net >= 300 and is_ma5_up))

            # 歷史高低點計算
            high_series = group["high"].values
            low_series = group["low"].values

            # 過去 5 日高點（不含今日）
            hi5_prev = np.max(high_series[-6:-1]) if len(high_series) >= 6 else high_series[0]
            # 過去 120 日高點（不含今日）
            hi120_prev = np.max(high_series[-121:-1]) if len(high_series) >= 121 else np.max(high_series[:-1])
            # 過去 480 日高點（不含今日）
            hi480_prev = np.max(high_series[-481:-1]) if len(high_series) >= 481 else np.max(high_series[:-1])

            # 20日最低價與 60日最低價
            low20 = np.min(low_series[-20:]) if len(low_series) >= 20 else np.min(low_series)
            low60 = np.min(low_series[-60:]) if len(low_series) >= 60 else np.min(low_series)
            d20_pct = round(((close_p - low20) / low20 * 100.0), 2) if low20 > 0 else 0.0

            # 價位精算
            targets = self._calculate_price_targets(close_p, avg_p)

            item_info = {
                "stock_id": stock_id,
                "stock_name": stock_name,
                "market": market,
                "close": close_p,
                "pct_change": pct_chg,
                "volume": int(vol),
                "turnover_k": turnover_k,
                "avg_price": avg_p,
                "q60r": q60r,
                "trust_net": trust_net,
                "foreign_net": foreign_net,
                "trust_consecutive_days": trust_consecutive_days,
                "is_s_tier": is_s_tier,
                "targets": targets
            }

            # ------------------------------------------------------------------
            # 策略判斷 1：Select 01 周帶量突破 (5日高 + Q60R > 2.0 + 實質漲幅)
            # ------------------------------------------------------------------
            if (close_p >= hi5_prev) and (q60r >= 2.0) and (pct_chg >= 2.0):
                select_01_list.append(item_info)

            # ------------------------------------------------------------------
            # 策略判斷 2：Select 02 突破Hi120 (半年新高 + Q60R > 2.5)
            # ------------------------------------------------------------------
            if (close_p >= hi120_prev) and (q60r >= 2.5) and (pct_chg >= 2.5):
                select_02_list.append(item_info)

            # ------------------------------------------------------------------
            # 策略判斷 3：Select 03 突破Hi480 (兩年新高大底 + Q60R > 3.0)
            # ------------------------------------------------------------------
            if (close_p >= hi480_prev) and (q60r >= 3.0) and (pct_chg >= 3.0):
                select_03_list.append(item_info)

            # ------------------------------------------------------------------
            # 策略判斷 4：Select 04 雙綠脫離 (D20由底部剛轉正脫離 0.5%~12% 且 脫離60低)
            # ------------------------------------------------------------------
            if (0.5 <= d20_pct <= 12.0) and (close_p > low60 * 1.03) and (pct_chg > 0):
                select_04_list.append(item_info)

            # S 級清單
            if is_s_tier and (pct_chg > 1.5):
                s_tier_list.append(item_info)

            # 當沖動能名單（帶量 + 振幅波動強）
            if (q60r >= 1.8) and (pct_chg >= 3.0):
                day_trade_list.append(item_info)

            # 隔日沖精選名單（尾盤強勢 + 投信或外資同買）
            if (pct_chg >= 3.5) and (trust_net > 0 or foreign_net > 0) and (close_p >= high_p * 0.985):
                swing_list.append(item_info)

        # 排序：優先以量比 Q60R 與 漲幅 排序
        select_01_list.sort(key=lambda x: x["q60r"], reverse=True)
        select_02_list.sort(key=lambda x: x["q60r"], reverse=True)
        select_03_list.sort(key=lambda x: x["q60r"], reverse=True)
        select_04_list.sort(key=lambda x: x["pct_change"], reverse=True)
        s_tier_list.sort(key=lambda x: x["trust_consecutive_days"], reverse=True)
        day_trade_list.sort(key=lambda x: x["q60r"], reverse=True)
        swing_list.sort(key=lambda x: x["pct_change"], reverse=True)

        logger.info(f"✅ 選股完成！掃描標的: {total_stocks} 檔 | "
                    f"周突破: {len(select_01_list)} | Hi120: {len(select_02_list)} | "
                    f"Hi480: {len(select_03_list)} | 雙綠脫離: {len(select_04_list)} | "
                    f"S級標的: {len(s_tier_list)}")

        return {
            "status": "success",
            "date": target_date,
            "total_scanned": total_stocks,
            "select_01_weekly_breakout": select_01_list,
            "select_02_hi120_breakout": select_02_list,
            "select_03_hi480_breakout": select_03_list,
            "select_04_double_green_breakout": select_04_list,
            "s_tier_picks": s_tier_list,
            "day_trade_momentum": day_trade_list,
            "overnight_swing": swing_list,
            "summary": {
                "select_01_count": len(select_01_list),
                "select_02_count": len(select_02_list),
                "select_03_count": len(select_03_list),
                "select_04_count": len(select_04_list),
                "s_tier_count": len(s_tier_list),
                "day_trade_count": len(day_trade_list),
                "overnight_swing_count": len(swing_list)
            }
        }


# ==============================================================================
# 單獨測試進入點 (方便沙盒與本機獨立驗證)
# ==============================================================================
if __name__ == "__main__":
    engine = ScreeningEngine("waynebot_history.db")
    res = engine.run_full_market_screening()
    print("\n" + "=" * 60)
    print(f"📊 WayneBot 選股引擎測試結果 [基準日: {res.get('date')}]")
    print("=" * 60)
    summary = res.get("summary", {})
    for k, v in summary.items():
        print(f"  • {k:<25}: {v:>4} 檔")

    if res.get("select_01_weekly_breakout"):
        top1 = res["select_01_weekly_breakout"][0]
        print(f"\n🔥 周帶量突破首選範例: [{top1['stock_id']}] {top1['stock_name']} | 收盤: {top1['close']} (+{top1['pct_change']}%) | 量比: {top1['q60r']}x")
        print(f"   👉 當沖建議: 進場 {top1['targets']['day_trade']['entry_price']} | 停利1 {top1['targets']['day_trade']['take_profit_1']} | 衝頂 {top1['targets']['day_trade']['take_profit_2']}")
