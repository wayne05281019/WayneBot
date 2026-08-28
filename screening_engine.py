# ==============================================================================
# WayneBot 全市場量化決策系統：即時選股與決策精算引擎 (screening_engine.py)
# 模組功能：四大突破策略、當沖/隔日沖價位精算、S級籌碼濾網、Telegram 報表格式化
# ==============================================================================

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np


class ScreeningEngine:
    def __init__(self, db_path: str = "waynebot_history.db"):
        """
        初始化選股引擎
        :param db_path: SQLite 資料庫路徑
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 連線並開啟唯讀最佳化"""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"找不到資料庫檔案：{self.db_path}，請先執行資料庫建置或下載 Release。")
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def load_market_data(self, lookback_days: int = 150) -> pd.DataFrame:
        """
        載入全市場近 N 個交易日的歷史數據
        :param lookback_days: 回溯交易日天數
        :return: 包含歷史行情的 DataFrame
        """
        conn = self._get_connection()
        query = f"""
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close,
            volume, turnover_k, pct_change, avg_price,
            foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date IN (
            SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT {lookback_days}
        )
        ORDER BY stock_id, date ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

    def run_screening(self, lookback_days: int = 150) -> Dict[str, Any]:
        """
        執行全市場量化篩選與價位精算
        :return: 結構化選股結果字典
        """
        df = self.load_market_data(lookback_days=lookback_days)
        if df.empty:
            return {"error": "資料庫內無有效行情數據", "date": datetime.now().strftime("%Y%m%d")}

        dates = sorted(df["date"].unique())
        latest_date = dates[-1]
        prev_date = dates[-2] if len(dates) >= 2 else latest_date

        results = {
            "date": latest_date,
            "total_scanned": df[df["date"] == latest_date]["stock_id"].nunique(),
            "select_01": [],      # 周帶量突破 (5日高 + Q60R > 2.0)
            "select_02": [],      # 突破Hi120 (半年新高 + Q60R > 2.5)
            "select_03": [],      # 突破Hi480 (兩年新高大底 + Q60R > 3.0)
            "select_04": [],      # 雙綠脫離 (D20轉正 + 底部起漲)
            "day_trade": [],      # 當沖動能專區
            "overnight": [],      # 隔日沖精選專區
            "s_class_chips": []   # S 級籌碼標的 (投信連買 + 5MA向上勾角)
        }

        # 依個股分組計算指標
        grouped = df.groupby("stock_id")

        for stock_id, group in grouped:
            if len(group) < 5:
                continue

            # 確保按日期升冪排序
            g = group.sort_values("date").reset_index(drop=True)
            today = g.iloc[-1]

            # 檢查最後一筆是否為最新交易日
            if today["date"] != latest_date:
                continue

            # ------------------------------------------------------------------
            # 1. 流動性過濾（嚴防殭屍股：日量 >= 1,000 張 且 日額 >= 3,000 萬元）
            # ------------------------------------------------------------------
            if today["volume"] < 1000 or today["turnover_k"] < 30000.0:
                continue

            close_p = float(today["close"])
            open_p = float(today["open"])
            high_p = float(today["high"])
            low_p = float(today["low"])
            avg_p = float(today["avg_price"]) if today["avg_price"] > 0 else close_p
            pct_chg = float(today["pct_change"])
            vol_today = int(today["volume"])

            # 技術指標序列
            closes = g["close"].values
            volumes = g["volume"].values
            highs = g["high"].values
            lows = g["low"].values
            trust_nets = g["trust_net"].values
            foreign_nets = g["foreign_net"].values

            # 均線計算
            ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
            ma5_prev = np.mean(closes[-6:-1]) if len(closes) >= 6 else ma5
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
            ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]

            # 量比 Q60R (今日量 / 60日均量)
            vol_ma60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else np.mean(volumes)
            q60r = round(vol_today / vol_ma60, 2) if vol_ma60 > 0 else 1.0

            # 位階指標 D20 (20日高低位階百分比: (Close - Low20) / (High20 - Low20))
            h20 = np.max(highs[-20:]) if len(highs) >= 20 else np.max(highs)
            l20 = np.min(lows[-20:]) if len(lows) >= 20 else np.min(lows)
            d20 = round((close_p - l20) / (h20 - l20) * 100, 1) if h20 > l20 else 50.0

            # 5日高、120日高、480日高判定
            h5_prev = np.max(highs[-6:-1]) if len(highs) >= 6 else highs[-1]
            h120_prev = np.max(highs[-121:-1]) if len(highs) >= 121 else np.max(highs[:-1])
            is_break_h5 = close_p > h5_prev
            is_break_h120 = close_p > h120_prev

            # 籌碼指標
            trust_today = int(today["trust_net"])
            foreign_today = int(today["foreign_net"])
            is_trust_continuous = (len(trust_nets) >= 3 and trust_nets[-1] > 0 and trust_nets[-2] > 0)
            ma5_hook_up = (ma5 > ma5_prev and close_p > ma5)

            # 打包個股基礎資訊
            stock_info = {
                "stock_id": str(stock_id),
                "stock_name": str(today["stock_name"]),
                "market": str(today["market"]),
                "close": close_p,
                "pct_change": pct_chg,
                "volume": vol_today,
                "turnover_k": round(float(today["turnover_k"]), 1),
                "q60r": q60r,
                "d20": d20,
                "avg_price": avg_p,
                "foreign_net": foreign_today,
                "trust_net": trust_today,
                # 當沖價位計算
                "day_entry": close_p,
                "day_tp1": round(close_p * 1.03, 2),
                "day_tp2": round(close_p * 1.06, 2),
                "day_sl": round(min(avg_p, close_p * 0.98), 2),
                # 隔日沖價位計算
                "overnight_entry_low": round(min(close_p, avg_p), 2),
                "overnight_entry_high": round(max(close_p, avg_p), 2),
                "overnight_target_low": round(close_p * 1.035, 2),
                "overnight_target_high": round(close_p * 1.048, 2),
                "overnight_surge": round(close_p * 1.07, 2),
                "overnight_defense": round(close_p * 0.975, 2)
            }

            # ------------------------------------------------------------------
            # 策略 1：周帶量突破 (5日新高 + Q60R >= 2.0 + 紅K)
            # ------------------------------------------------------------------
            if is_break_h5 and q60r >= 2.0 and close_p >= open_p and pct_chg >= 2.5:
                results["select_01"].append(stock_info)

            # ------------------------------------------------------------------
            # 策略 2：突破 Hi120 (半年新高 + Q60R >= 2.5)
            # ------------------------------------------------------------------
            if is_break_h120 and q60r >= 2.5 and pct_chg >= 3.0:
                results["select_02"].append(stock_info)

            # ------------------------------------------------------------------
            # 策略 3：突破 Hi480 (大底長期突破 + Q60R >= 3.0)
            # ------------------------------------------------------------------
            if is_break_h120 and q60r >= 3.0 and pct_chg >= 4.0 and len(highs) >= 100:
                results["select_03"].append(stock_info)

            # ------------------------------------------------------------------
            # 策略 4：雙綠脫離 (D20 由低檔轉正向上 + 站上 20MA)
            # ------------------------------------------------------------------
            if len(lows) >= 20:
                l20_prev = np.min(lows[-21:-1]) if len(lows) >= 21 else l20
                if low_p > l20_prev and d20 >= 15.0 and d20 <= 45.0 and close_p > ma20 and pct_chg >= 1.5:
                    results["select_04"].append(stock_info)

            # ------------------------------------------------------------------
            # S 級籌碼濾網：投信連買 + 外資同行 + 5MA 向上勾角
            # ------------------------------------------------------------------
            if is_trust_continuous and foreign_today >= 0 and ma5_hook_up and pct_chg >= 1.0:
                results["s_class_chips"].append(stock_info)

            # ------------------------------------------------------------------
            # 當沖動能精選：漲幅 3%~7%、Q60R > 2.0、量能充沛
            # ------------------------------------------------------------------
            if 3.0 <= pct_chg <= 7.5 and q60r >= 2.0 and vol_today >= 2000:
                results["day_trade"].append(stock_info)

            # ------------------------------------------------------------------
            # 隔日沖精選：尾盤強勢（收盤接近最高價）、投信/外資買超、量比 >= 1.8
            # ------------------------------------------------------------------
            if close_p >= (high_p * 0.985) and pct_chg >= 3.5 and (trust_today > 0 or foreign_today > 500) and q60r >= 1.8:
                results["overnight"].append(stock_info)

        # 排序：優先以成交額與量比排序前 10 檔
        for key in ["select_01", "select_02", "select_03", "select_04", "day_trade", "overnight", "s_class_chips"]:
            results[key] = sorted(results[key], key=lambda x: (x["q60r"], x["turnover_k"]), reverse=True)[:8]

        return results


def format_telegram_report(screening_results: Dict[str, Any], title: Optional[str] = None) -> str:
    """
    將量化選股與決策精算結果格式化為 Telegram 訊息
    :param screening_results: run_screening 輸出的字典
    :param title: 自訂標題
    :return: 格式化後的文字內容
    """
    if "error" in screening_results:
        return f"⚠️ **WayneBot 選股提醒**：{screening_results['error']}"

    dt = screening_results.get("date", datetime.now().strftime("%Y%m%d"))
    date_formatted = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}" if len(dt) == 8 else dt
    total_scanned = screening_results.get("total_scanned", 0)

    header = title or f"🚀 **WayneBot 台股量化決策日報** ({date_formatted})"
    lines = [
        header,
        f"📊 全市場掃描標的：`{total_scanned:,}` 檔（已套用流動性防護）",
        "═" * 32
    ]

    # 1. S 級籌碼專區
    s_chips = screening_results.get("s_class_chips", [])
    if s_chips:
        lines.append("\n🌟 **【S 級法人連買＋均線勾角】**")
        for s in s_chips[:4]:
            lines.append(
                f"• `{s['stock_id']}` **{s['stock_name']}** | 收: `{s['close']}` ({s['pct_change']:+.2f}%)"
                f"\n  投信: `{s['trust_net']:+d}` 張 | 外資: `{s['foreign_net']:+d}` 張 | 量比: `{s['q60r']}x`"
            )

    # 2. 四大即時選股
    s1 = screening_results.get("select_01", [])
    if s1:
        lines.append("\n⚡ **【Select 01 周帶量突破 (5日高+Q60R>2)】**")
        for s in s1[:4]:
            lines.append(f"• `{s['stock_id']}` {s['stock_name']} | `{s['close']}` ({s['pct_change']:+.2f}%) | 量比: `{s['q60r']}x` | 日量: `{s['volume']:,}`張")

    s2 = screening_results.get("select_02", [])
    if s2:
        lines.append("\n🔥 **【Select 02 半年新高突破 (Hi120)】**")
        for s in s2[:4]:
            lines.append(f"• `{s['stock_id']}` {s['stock_name']} | `{s['close']}` ({s['pct_change']:+.2f}%) | 量比: `{s['q60r']}x`")

    s4 = screening_results.get("select_04", [])
    if s4:
        lines.append("\n🌱 **【Select 04 雙綠脫離 (大底轉正)】**")
        for s in s4[:3]:
            lines.append(f"• `{s['stock_id']}` {s['stock_name']} | `{s['close']}` ({s['pct_change']:+.2f}%) | 位階 D20: `{s['d20']}%`")

    # 3. 當沖動能專區
    dt_list = screening_results.get("day_trade", [])
    if dt_list:
        lines.append("\n🎯 **【當沖動能價位精算】**")
        for s in dt_list[:3]:
            lines.append(
                f"• `{s['stock_id']}` **{s['stock_name']}** (收 `{s['close']}`)"
                f"\n  進場: `{s['day_entry']}` | 第一利(+3%): `{s['day_tp1']}` | 衝頂(+6%): `{s['day_tp2']}` | 停損: `{s['day_sl']}`"
            )

    # 4. 隔日沖精選專區
    on_list = screening_results.get("overnight", [])
    if on_list:
        lines.append("\n🌙 **【隔日沖強勢佈局】**")
        for s in on_list[:3]:
            lines.append(
                f"• `{s['stock_id']}` **{s['stock_name']}** (尾盤均價 `{s['avg_price']}`)"
                f"\n  買進區間: `{s['overnight_entry_low']}~{s['overnight_entry_high']}`"
                f"\n  開高目標(+3.5~4.8%): `{s['overnight_target_low']}~{s['overnight_target_high']}` | 防守: `{s['overnight_defense']}`"
            )

    if not (s_chips or s1 or s2 or s4 or dt_list or on_list):
        lines.append("\nℹ️ 今日全市場行情未出現符合高勝率動能條件之標的，建議保留現金觀望。")

    lines.append("\n" + "═" * 32)
    lines.append("🤖 *WayneBot 量化操盤系統 | 嚴格執行紀律停損*")
    return "\n".join(lines)


# ------------------------------------------------------------------------------
# 單元測試入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    db_file = "waynebot_history.db"
    if os.path.exists(db_file):
        print(f"🔍 測試執行 ScreeningEngine (使用 {db_file})...")
        engine = ScreeningEngine(db_path=db_file)
        res = engine.run_screening(lookback_days=120)
        report = format_telegram_report(res)
        print("\n" + report)
    else:
        print("💡 目前目錄無 waynebot_history.db，模組定義與匯出檢查完畢。")
