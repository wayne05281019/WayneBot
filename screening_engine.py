# ==============================================================================
# WayneBot 全市場量化決策系統：模組二 - 即時選股與價位精算引擎
# 檔案路徑：screening_engine.py
# 核心功能：四大 CaryBot 選股策略、當沖/隔日沖價位精算、S級籌碼濾網、Telegram 報告排版
# ==============================================================================

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

class ScreeningEngine:
    """
    量化選股與即時決策運算核心
    """
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self._ensure_config_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_config_table(self):
        """確保動態參數配置表存在（Auto-Tuning 支援）"""
        if not os.path.exists(self.db_path):
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_config (
            param_key TEXT PRIMARY KEY,
            param_value REAL,
            description TEXT
        );
        """)
        # 預設參數設定
        default_configs = [
            ("min_volume_sheets", 1000.0, "最低成交量門檻(張)"),
            ("min_turnover_k", 30000.0, "最低成交金額門檻(千元=3000萬)"),
            ("q60r_select01", 2.0, "Select01 爆量比門檻"),
            ("q60r_select02", 2.5, "Select02 爆量比門檻"),
            ("q60r_select03", 3.0, "Select03 爆量比門檻"),
            ("day_trade_tp1_pct", 3.0, "當沖第一停利百分比"),
            ("day_trade_tp2_pct", 6.0, "當沖第二衝頂百分比"),
            ("swing_target_min_pct", 3.5, "隔日沖開高目標下限百分比"),
            ("swing_target_max_pct", 4.8, "隔日沖開高目標上限百分比")
        ]
        for key, val, desc in default_configs:
            cursor.execute("""
            INSERT OR IGNORE INTO strategy_config (param_key, param_value, description)
            VALUES (?, ?, ?);
            """, (key, val, desc))
        conn.commit()
        conn.close()

    def get_param(self, param_key: str, default_val: float) -> float:
        """讀取動態參數"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT param_value FROM strategy_config WHERE param_key = ?", (param_key,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return float(row["param_value"])
        except Exception:
            pass
        return default_val

    def get_latest_date(self) -> Optional[str]:
        """取得資料庫中最新交易日"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) as max_date FROM daily_quotes;")
            row = cursor.fetchone()
            conn.close()
            if row and row["max_date"]:
                return str(row["max_date"])
        except Exception:
            pass
        return None

    def load_stock_history(self, stock_id: str, limit_days: int = 500) -> pd.DataFrame:
        """載入單一個股歷史數據並按日期升序排列"""
        conn = self._get_connection()
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, 
               volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?;
        """
        df = pd.read_sql_query(query, conn, params=(stock_id, limit_days))
        conn.close()
        if df.empty:
            return df
        return df.sort_values("date").reset_index(drop=True)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算均線、量比、高低點與技術結構指標"""
        if len(df) < 5:
            return df

        # 均線
        df["ma5"] = df["close"].rolling(window=5).mean()
        df["ma20"] = df["close"].rolling(window=20).mean()
        df["ma60"] = df["close"].rolling(window=60).mean()
        df["ma120"] = df["close"].rolling(window=120).mean()
        df["ma240"] = df["close"].rolling(window=240).mean()
        df["ma480"] = df["close"].rolling(window=480).mean()

        # 5MA 勾角斜率 (當日 MA5 - 前日 MA5)
        df["ma5_slope"] = df["ma5"].diff()

        # 60日均量與量比 Q60R
        df["vol_ma60"] = df["volume"].rolling(window=60).mean()
        df["q60r"] = np.where(df["vol_ma60"] > 0, df["volume"] / df["vol_ma60"], 0.0)

        # N 日高低點（不含當日，用於判斷突破）
        df["hi5_prev"] = df["high"].shift(1).rolling(window=5).max()
        df["hi120_prev"] = df["high"].shift(1).rolling(window=120).max()
        df["hi480_prev"] = df["high"].shift(1).rolling(window=min(len(df)-1, 480)).max()
        df["low60_prev"] = df["low"].shift(1).rolling(window=60).min()
        df["low20_prev"] = df["low"].shift(1).rolling(window=20).min()

        # 20 日偏離度 D20 = (收盤價 - 20日最低) / (20日最高 - 20日最低)
        hi20 = df["high"].rolling(window=20).max()
        low20 = df["low"].rolling(window=20).min()
        rng20 = hi20 - low20
        df["d20"] = np.where(rng20 > 0, (df["close"] - low20) / rng20 * 100.0, 50.0)
        df["d20_prev"] = df["d20"].shift(1)

        # 投信連買天數計算
        trust_buy = (df["trust_net"] > 0).astype(int)
        df["trust_consecutive_days"] = trust_buy.groupby((~trust_buy.astype(bool)).cumsum()).cumsum()

        return df

    def run_all_screenings(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        執行全市場標的篩選
        """
        if not target_date:
            target_date = self.get_latest_date()
        if not target_date:
            return {"date": "", "total_scanned": 0, "strategies": {}}

        min_vol = self.get_param("min_volume_sheets", 1000.0)
        min_turnover = self.get_param("min_turnover_k", 30000.0)
        q60r_th1 = self.get_param("q60r_select01", 2.0)
        q60r_th2 = self.get_param("q60r_select02", 2.5)
        q60r_th3 = self.get_param("q60r_select03", 3.0)

        conn = self._get_connection()
        # 取得目標日有交易且符合流動性防護閥之標的
        query = """
        SELECT DISTINCT stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, trust_net, foreign_net
        FROM daily_quotes
        WHERE date = ? AND (volume >= ? OR turnover_k >= ?);
        """
        candidate_df = pd.read_sql_query(query, conn, params=(target_date, min_vol, min_turnover))
        conn.close()

        results = {
            "date": target_date,
            "total_scanned": len(candidate_df),
            "select_01_weekly_breakout": [],
            "select_02_break_hi120": [],
            "select_03_break_hi480": [],
            "select_04_green_exit": [],
            "day_trade_picks": [],
            "swing_trade_picks": []
        }

        if candidate_df.empty:
            return results

        # 逐檔技術線型運算
        for _, row in candidate_df.iterrows():
            sid = str(row["stock_id"])
            sname = str(row["stock_name"])
            
            hist = self.load_stock_history(sid, limit_days=500)
            if len(hist) < 20:
                continue

            hist = self.calculate_indicators(hist)
            curr = hist.iloc[-1]
            if str(curr["date"]) != target_date:
                continue

            close_p = float(curr["close"])
            open_p = float(curr["open"])
            high_p = float(curr["high"])
            low_p = float(curr["low"])
            vol = int(curr["volume"])
            turnover_k = float(curr["turnover_k"])
            pct_chg = float(curr["pct_change"])
            q60r = float(curr["q60r"])
            avg_p = float(curr["avg_price"]) if curr["avg_price"] > 0 else close_p
            trust_n = int(curr["trust_net"])
            foreign_n = int(curr["foreign_net"])
            trust_streak = int(curr["trust_consecutive_days"])
            ma5_slope = float(curr["ma5_slope"]) if pd.notna(curr["ma5_slope"]) else 0.0

            # S級籌碼標籤：投信連買 >= 2天 或 單日投信買超>500張，且 5MA 向上勾角
            is_s_chip = (trust_streak >= 2 or trust_n >= 500) and (ma5_slope > 0)

            # 價位精算模型
            # 當沖價位
            dt_entry = close_p
            dt_tp1 = round(close_p * 1.03, 2)
            dt_tp2 = round(close_p * 1.06, 2)
            dt_sl = round(avg_p * 0.985 if avg_p > 0 else close_p * 0.98, 2)

            # 隔日沖價位
            sw_buy_low = round(close_p * 0.99, 2)
            sw_buy_high = round(close_p * 1.005, 2)
            sw_target_low = round(close_p * 1.035, 2)
            sw_target_high = round(close_p * 1.048, 2)
            sw_surge = round(close_p * 1.07, 2)
            sw_defend = round(float(curr["ma5"]) if pd.notna(curr["ma5"]) and curr["ma5"] > 0 else close_p * 0.97, 2)

            stock_summary = {
                "stock_id": sid,
                "stock_name": sname,
                "market": str(curr["market"]),
                "close": close_p,
                "pct_change": pct_chg,
                "volume": vol,
                "turnover_k": turnover_k,
                "q60r": round(q60r, 2),
                "is_s_chip": is_s_chip,
                "trust_streak": trust_streak,
                "trust_net": trust_n,
                "foreign_net": foreign_n,
                "day_trade": {
                    "entry": dt_entry,
                    "tp1": dt_tp1,
                    "tp2": dt_tp2,
                    "sl": dt_sl
                },
                "swing_trade": {
                    "buy_range": f"{sw_buy_low} ~ {sw_buy_high}",
                    "target_range": f"{sw_target_low} ~ {sw_target_high}",
                    "surge_target": sw_surge,
                    "defend_price": sw_defend
                }
            }

            # ------------------------------------------------------------------
            # 策略 1: Select 01 周帶量突破 (5日高 + Q60R > 2.0 + 站上5MA)
            # ------------------------------------------------------------------
            if pd.notna(curr["hi5_prev"]) and close_p >= curr["hi5_prev"] and q60r >= q60r_th1 and close_p > curr["ma5"]:
                results["select_01_weekly_breakout"].append(stock_summary)

            # ------------------------------------------------------------------
            # 策略 2: Select 02 突破Hi120 (半年新高 + Q60R > 2.5)
            # ------------------------------------------------------------------
            if pd.notna(curr["hi120_prev"]) and high_p >= curr["hi120_prev"] and q60r >= q60r_th2:
                results["select_02_break_hi120"].append(stock_summary)

            # ------------------------------------------------------------------
            # 策略 3: Select 03 突破Hi480 (兩年新高大底 + Q60R > 3.0)
            # ------------------------------------------------------------------
            if pd.notna(curr["hi480_prev"]) and high_p >= curr["hi480_prev"] and q60r >= q60r_th3:
                results["select_03_break_hi480"].append(stock_summary)

            # ------------------------------------------------------------------
            # 策略 4: Select 04 雙綠脫離 (D20由低檔轉正脫離 + 60日低點守穩)
            # ------------------------------------------------------------------
            if pd.notna(curr["d20_prev"]) and curr["d20_prev"] <= 15.0 and curr["d20"] > 20.0 and close_p > curr["ma20"]:
                results["select_04_green_exit"].append(stock_summary)

            # 當沖精選（強勢紅K + 爆量Q60R>2.0 + 漲幅介於 2.5%~7.5%）
            if 2.5 <= pct_chg <= 7.5 and q60r >= 2.0 and close_p > open_p:
                results["day_trade_picks"].append(stock_summary)

            # 隔日沖精選（尾盤維持強勢 + S級籌碼或量價健康 + 漲幅介於 3.0%~8.5%）
            if 3.0 <= pct_chg <= 8.5 and (is_s_chip or q60r >= 1.8) and close_p >= (high_p * 0.985):
                results["swing_trade_picks"].append(stock_summary)

        # 排序（以 Q60R 與 漲幅 綜合排序）
        for k in ["select_01_weekly_breakout", "select_02_break_hi120", "select_03_break_hi480", 
                  "select_04_green_exit", "day_trade_picks", "swing_trade_picks"]:
            results[k].sort(key=lambda x: (x["is_s_chip"], x["q60r"]), reverse=True)

        return results

# ------------------------------------------------------------------------------
# Telegram 推播訊息排版核心函式（main_runner 與 bot_servers 必備）
# ------------------------------------------------------------------------------
def format_telegram_report(res: Dict[str, Any], max_items_per_section: int = 5) -> str:
    """
    將量化選股與價位精算結果格式化為高可讀性之 Telegram Markdown 報告
    """
    target_date = res.get("date", datetime.now().strftime("%Y%m%d"))
    total_scanned = res.get("total_scanned", 0)

    lines = []
    lines.append(f"📊 *WayneBot 台股量化決策日報* ｜ `{target_date}`")
    lines.append(f"🔍 全市場有效流動性掃描：`{total_scanned}` 檔\n")

    # 1. Select 01 周帶量突破
    s1 = res.get("select_01_weekly_breakout", [])
    lines.append(f"⚡ *【Select 01 周帶量突破】*（共 {len(s1)} 檔）")
    if not s1:
        lines.append("  _今日暫無符合標的_")
    else:
        for item in s1[:max_items_per_section]:
            chip_tag = " ⭐[S級籌碼]" if item["is_s_chip"] else ""
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*{chip_tag}")
            lines.append(f"  現價: `{item['close']}` ({item['pct_change']:+.2f}%) ｜ 量比 Q60R: `{item['q60r']}x` ｜ 成交: `{item['volume']}張`")
    lines.append("")

    # 2. Select 02 半年新高突破
    s2 = res.get("select_02_break_hi120", [])
    lines.append(f"🎯 *【Select 02 突破半年新高 Hi120】*（共 {len(s2)} 檔）")
    if not s2:
        lines.append("  _今日暫無符合標的_")
    else:
        for item in s2[:max_items_per_section]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* ｜ 現價: `{item['close']}` ({item['pct_change']:+.2f}%) ｜ Q60R: `{item['q60r']}x`")
    lines.append("")

    # 3. Select 03 兩年新高大底突破
    s3 = res.get("select_03_break_hi480", [])
    lines.append(f"👑 *【Select 03 突破兩年大底 Hi480】*（共 {len(s3)} 檔）")
    if not s3:
        lines.append("  _今日暫無符合標的_")
    else:
        for item in s3[:max_items_per_section]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* ｜ 現價: `{item['close']}` ({item['pct_change']:+.2f}%) ｜ Q60R: `{item['q60r']}x`")
    lines.append("")

    # 4. 當沖動能與隔日沖決策卡 (精選前 2 檔)
    day_picks = res.get("day_trade_picks", [])
    swing_picks = res.get("swing_trade_picks", [])

    if day_picks:
        lines.append("🚀 *【當沖動能專區·價位精算卡】*")
        for item in day_picks[:2]:
            dt = item["day_trade"]
            lines.append(f"📌 `{item['stock_id']}` *{item['stock_name']}* (收盤: `{item['close']}`)")
            lines.append(f"  └ 建議進場: `{dt['entry']}` ｜ 第1停利(+3%): `{dt['tp1']}` ｜ 衝頂(+6%): `{dt['tp2']}` ｜ 均價防守: `{dt['sl']}`")
        lines.append("")

    if swing_picks:
        lines.append("🌙 *【隔日沖精選·尾盤布局規劃】*")
        for item in swing_picks[:2]:
            sw = item["swing_trade"]
            lines.append(f"📌 `{item['stock_id']}` *{item['stock_name']}* (收盤: `{item['close']}`)")
            lines.append(f"  └ 今日買進區間: `{sw['buy_range']}`")
            lines.append(f"  └ 明日開高目標: `{sw['target_range']}` ｜ 衝頂價: `{sw['surge_target']}` ｜ 保本防守: `{sw['defend_price']}`")
        lines.append("")

    lines.append("⚠️ _風險提醒：本量化報告僅供策略參考，操作請嚴格執行移動防守與停損紀律。_")
    return "\n".join(lines)


# ------------------------------------------------------------------------------
# 單元沙盒驗證入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 正在進行 screening_engine.py 獨立沙盒測試...")
    print("=" * 60)
    
    engine = ScreeningEngine("waynebot_history.db")
    latest_d = engine.get_latest_date()
    print(f"📅 最新交易日: {latest_d}")

    if latest_d:
        report_data = engine.run_all_screenings(latest_d)
        print(f"✅ 篩選完成！掃描標的數: {report_data['total_scanned']}")
        print(f"   • 周帶量突破: {len(report_data['select_01_weekly_breakout'])} 檔")
        print(f"   • 突破 Hi120: {len(report_data['select_02_break_hi120'])} 檔")
        print(f"   • 突破 Hi480: {len(report_data['select_03_break_hi480'])} 檔")
        print(f"   • 雙綠脫離: {len(report_data['select_04_green_exit'])} 檔")
        print(f"   • 當沖動能: {len(report_data['day_trade_picks'])} 檔")
        print(f"   • 隔日沖精選: {len(report_data['swing_trade_picks'])} 檔")
        
        # 測試 format_telegram_report 格式化輸出
        msg = format_telegram_report(report_data)
        print("\n" + "-" * 40 + " Telegram 排版預覽 " + "-" * 40)
        print(msg[:500] + "\n... (以下略)")
        print("-" * 90)
        print("🎉 screening_engine.py 沙盒驗證通過！")
    else:
        print("⚠️ 未找到資料庫檔案，請先確認 waynebot_history.db 是否存在。")
