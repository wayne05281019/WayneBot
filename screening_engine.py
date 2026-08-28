# ==============================================================================
# WayneBot 全市場量化決策系統升級：核心模組二 - 即時選股與價位精算引擎
# 檔案名稱：screening_engine.py
# 核心功能：
#   1. CaryBot 四大即時選股 (周帶量突破 / 突破Hi120 / 突破Hi480 / 雙綠脫離)
#   2. S 級籌碼濾網 (投信連買 + 5MA 向上勾角)
#   3. 四大盲點防護 (中小型股流動性陷阱、當沖/隔日沖動態區間精算、大盤多空風控)
#   4. 當沖動能與隔日沖價位精算卡 (進場區間、停利目標、均價防守線、09:15 時間保護)
# ==============================================================================

import os
import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

# ------------------------------------------------------------------------------
# 1. 技術指標與量化特徵計算模組
# ------------------------------------------------------------------------------
def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    計算全套技術指標與籌碼特徵：
    - 移動平均線：5MA, 10MA, 20MA, 60MA, 120MA, 240MA, 480MA
    - 均線斜率與勾角：5MA 向上勾角判定 (ma5_hook_up)
    - 60日均量比 (Q60R)：當日成交量 / 60日平均成交量
    - 歷史新高與位階：前5日高點 (Hi5)、前120日高點 (Hi120)、前480日高點 (Hi480)
    - 底部與位階指標 (D20)：(Close - Low20) / (High20 - Low20) * 100
    - 投信連續買超天數 (trust_consecutive_days)
    """
    if df is None or len(df) < 5:
        return df

    df = df.sort_values("date").reset_index(drop=True).copy()

    # 確保數值型別正確
    num_cols = ["open", "high", "low", "close", "volume", "turnover_k", "foreign_net", "trust_net", "dealer_net"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # 1. 均線系列
    df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean().round(2)
    df["ma10"] = df["close"].rolling(window=10, min_periods=1).mean().round(2)
    df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean().round(2)
    df["ma60"] = df["close"].rolling(window=60, min_periods=1).mean().round(2)
    df["ma120"] = df["close"].rolling(window=120, min_periods=1).mean().round(2)
    df["ma240"] = df["close"].rolling(window=240, min_periods=1).mean().round(2)
    df["ma480"] = df["close"].rolling(window=480, min_periods=1).mean().round(2)

    # 2. 5MA 向上勾角 (今日5MA > 昨日5MA 且 今日收盤 > 5MA)
    df["ma5_diff"] = df["ma5"].diff().fillna(0.0)
    df["ma5_hook_up"] = (df["ma5_diff"] > 0) & (df["close"] >= df["ma5"])

    # 3. 60日成交量均線與 Q60R 量比
    df["vol_ma60"] = df["volume"].rolling(window=60, min_periods=5).mean().fillna(df["volume"])
    df["q60r"] = np.where(df["vol_ma60"] > 0, (df["volume"] / df["vol_ma60"]).round(2), 1.0)

    # 4. 歷史高點統計 (排除當日，取前 N 日最高)
    df["hi5_prev"] = df["high"].shift(1).rolling(window=5, min_periods=1).max().fillna(df["high"])
    df["hi120_prev"] = df["high"].shift(1).rolling(window=120, min_periods=10).max().fillna(df["high"])
    df["hi480_prev"] = df["high"].shift(1).rolling(window=480, min_periods=30).max().fillna(df["high"])

    # 5. 20日與60日最低點 (排除當日)
    df["lo20_prev"] = df["low"].shift(1).rolling(window=20, min_periods=5).min().fillna(df["low"])
    df["lo60_prev"] = df["low"].shift(1).rolling(window=60, min_periods=10).min().fillna(df["low"])

    # 6. D20 底部脫離位階 (0%~100%)
    hi20_full = df["high"].rolling(window=20, min_periods=1).max()
    lo20_full = df["low"].rolling(window=20, min_periods=1).min()
    diff20 = hi20_full - lo20_full
    df["d20"] = np.where(diff20 > 0, ((df["close"] - lo20_full) / diff20 * 100.0).round(2), 50.0)
    df["d20_prev"] = df["d20"].shift(1).fillna(50.0)

    # 7. 投信連買天數計算
    trust_buy = (df["trust_net"] > 0).astype(int)
    consecutive_trust = []
    curr_count = 0
    for val in trust_buy:
        if val == 1:
            curr_count += 1
        else:
            curr_count = 0
        consecutive_trust.append(curr_count)
    df["trust_consecutive_days"] = consecutive_trust

    return df

# ------------------------------------------------------------------------------
# 2. 選股引擎核心類別 (ScreeningEngine)
# ------------------------------------------------------------------------------
class ScreeningEngine:
    """
    量化選股與即時決策核心引擎
    """
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path

    def check_liquidity(self, row: pd.Series, min_vol: int = 1000, min_turnover_k: float = 30000.0) -> bool:
        """
        盲點防護一：中小型股流動性陷阱過濾
        - 日成交量 >= 1,000 張
        - 日成交金額 >= 3,000 萬元 (turnover_k >= 30,000 千元)
        """
        vol = float(row.get("volume", 0))
        turnover_k = float(row.get("turnover_k", 0))
        return (vol >= min_vol) and (turnover_k >= min_turnover_k)

    def evaluate_carybot_strategies(self, df: pd.DataFrame) -> Dict[str, bool]:
        """
        評估 CaryBot 四大即時選股策略與 S 級籌碼濾網：
        1. Select 01 周帶量突破：收盤價突破前5日高點 (或創5日收盤新高) 且 Q60R 量比 >= 2.0
        2. Select 02 突破Hi120：收盤價突破前半年 (120日) 新高 且 Q60R 量比 >= 2.5
        3. Select 03 突破Hi480：收盤價突破前兩年 (480日) 大底新高 且 Q60R 量比 >= 3.0
        4. Select 04 雙綠脫離：D20 由低檔 (<20%) 向上脫離 且 收盤價脫離 60 日新低區
        5. S 級籌碼濾網：投信連買 >= 2 天 (或單日大買) 且 5MA 向上勾角 (ma5_hook_up)
        """
        if df is None or len(df) < 5:
            return {
                "select_01_break_week": False,
                "select_02_break_hi120": False,
                "select_03_break_hi480": False,
                "select_04_dual_green": False,
                "s_grade_chip": False,
                "passed_liquidity": False
            }

        latest = df.iloc[-1]
        close = float(latest["close"])
        high = float(latest["high"])
        q60r = float(latest["q60r"])
        
        hi5_p = float(latest["hi5_prev"])
        hi120_p = float(latest["hi120_prev"])
        hi480_p = float(latest["hi480_prev"])
        lo60_p = float(latest["lo60_prev"])
        d20 = float(latest["d20"])
        d20_p = float(latest["d20_prev"])
        
        trust_days = int(latest["trust_consecutive_days"])
        ma5_hook = bool(latest["ma5_hook_up"])
        passed_liq = self.check_liquidity(latest)

        # 1. Select 01 周帶量突破：收盤突破前5日高點 (或盤中過高且站穩5MA) 且 Q60R >= 2.0
        break_5d = (close >= hi5_p * 0.998) or (high >= hi5_p and close >= latest["ma5"])
        select_01 = bool(break_5d and (q60r >= 2.0))

        # 2. Select 02 突破Hi120：半年新高突破 且 Q60R >= 2.5
        break_120d = (close >= hi120_p * 0.998) or (high >= hi120_p and close >= latest["ma20"])
        select_02 = bool(break_120d and (q60r >= 2.5))

        # 3. Select 03 突破Hi480：兩年大底新高突破 且 Q60R >= 3.0
        break_480d = (close >= hi480_p * 0.998) or (high >= hi480_p and close >= latest["ma60"])
        select_03 = bool(break_480d and (q60r >= 3.0))

        # 4. Select 04 雙綠脫離：D20 低檔 (<20%) 向上脫離 且 收盤高於近60日低點 3% 以上
        dual_green = (d20_p <= 20.0 and d20 > d20_p) and (close >= lo60_p * 1.03)
        select_04 = bool(dual_green and (q60r >= 1.2))

        # 5. S 級籌碼濾網：投信連買 >= 2 天 且 5MA 向上勾角
        s_chip = bool((trust_days >= 2 or int(latest.get("trust_net", 0)) >= 500) and ma5_hook)

        return {
            "select_01_break_week": select_01,
            "select_02_break_hi120": select_02,
            "select_03_break_hi480": select_03,
            "select_04_dual_green": select_04,
            "s_grade_chip": s_chip,
            "passed_liquidity": passed_liq
        }

    # --------------------------------------------------------------------------
    # 3. 當沖動能專區價位精算 (Day Trading Card)
    # --------------------------------------------------------------------------
    def calculate_day_trading_plan(self, row: pd.Series) -> Dict[str, Any]:
        """
        當沖動能專區即時價位精算：
        - 建議進場價 (entry_price)：當前收盤價
        - 第一停利 (+3.0%)：快速停利點
        - 第二衝頂 (+6.0%)：波段衝頂點
        - 均價停損價 (sl_price)：以當日均價 (avg_price) 或 -2.0% 設防
        - 時間防護：09:15 時間保護機制
        """
        close = float(row.get("close", 0.0))
        avg_price = float(row.get("avg_price", close))
        if avg_price <= 0:
            avg_price = close

        entry_price = close
        tp1_price = round(entry_price * 1.03, 2)
        tp2_price = round(entry_price * 1.06, 2)
        
        sl_rule_price = round(entry_price * 0.98, 2)
        sl_price = max(round(avg_price * 0.995, 2), sl_rule_price)
        if sl_price >= entry_price:
            sl_price = round(entry_price * 0.985, 2)

        return {
            "stock_id": str(row.get("stock_id", "")),
            "stock_name": str(row.get("stock_name", "")),
            "entry_price": entry_price,
            "tp1_target": tp1_price,
            "tp2_target": tp2_price,
            "stop_loss": sl_price,
            "avg_price": round(avg_price, 2),
            "time_protection": "09:15 前量能未放大或未觸及 +1.5% 則市價獲利/保本平倉"
        }

    # --------------------------------------------------------------------------
    # 4. 隔日沖精選專區價位精算 (Overnight Momentum Card)
    # --------------------------------------------------------------------------
    def calculate_overnight_plan(self, row: pd.Series) -> Dict[str, Any]:
        """
        隔日沖精選專區尾盤價位精算：
        - 今日買進區間 (buy_zone)：[收盤價 * 0.995, 收盤價 * 1.005] (防範固定價位未成交)
        - 明日開高目標 (+3.5% ~ +4.8%)：早盤開高獲利了結區
        - 強勢衝頂價 (+8.0%)：開盤跳空強攻之衝頂價
        - 保本防守價 (defense_price)：跌破買進均價或 5MA 立即保本退場
        """
        close = float(row.get("close", 0.0))
        ma5 = float(row.get("ma5", close))

        buy_zone_low = round(close * 0.995, 2)
        buy_zone_high = round(close * 1.005, 2)
        target_open_low = round(close * 1.035, 2)
        target_open_high = round(close * 1.048, 2)
        target_top = round(close * 1.08, 2)
        defense_price = round(min(close * 0.985, ma5), 2)

        return {
            "stock_id": str(row.get("stock_id", "")),
            "stock_name": str(row.get("stock_name", "")),
            "close_price": close,
            "buy_zone": f"{buy_zone_low:.2f} ~ {buy_zone_high:.2f}",
            "target_open_zone": f"{target_open_low:.2f} ~ {target_open_high:.2f} (+3.5%~+4.8%)",
            "target_top": target_top,
            "defense_price": defense_price,
            "execution_note": "尾盤 13:20~13:25 於買進區間分批佈局；次日 09:05 前開高分批停利"
        }

    # --------------------------------------------------------------------------
    # 5. 全市場快速掃描 (Market Screener)
    # --------------------------------------------------------------------------
    def scan_market(self, target_date: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        對歷史資料庫進行全市場量化選股掃描
        """
        if not os.path.exists(self.db_path):
            return {}

        conn = sqlite3.connect(self.db_path)
        if not target_date:
            cur = conn.cursor()
            cur.execute("SELECT MAX(date) FROM daily_quotes;")
            res = cur.fetchone()
            target_date = res[0] if res else None

        if not target_date:
            conn.close()
            return {}

        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id IN (
            SELECT DISTINCT stock_id FROM daily_quotes WHERE date = '{target_date}'
        )
        ORDER BY stock_id, date ASC;
        """
        df_all = pd.read_sql_query(query, conn)
        conn.close()

        if df_all.empty:
            return {}

        results = {
            "select_01_break_week": [],
            "select_02_break_hi120": [],
            "select_03_break_hi480": [],
            "select_04_dual_green": [],
            "s_grade_chip": [],
            "day_trading_picks": [],
            "overnight_picks": []
        }

        for sid, group in df_all.groupby("stock_id"):
            if len(group) < 5:
                continue
            df_ind = calculate_technical_indicators(group)
            latest = df_ind.iloc[-1]

            if latest["date"] != target_date:
                continue

            triggers = self.evaluate_carybot_strategies(df_ind)
            if not triggers["passed_liquidity"]:
                continue

            stock_info = {
                "stock_id": sid,
                "stock_name": latest["stock_name"],
                "market": latest["market"],
                "close": latest["close"],
                "pct_change": latest["pct_change"],
                "volume": int(latest["volume"]),
                "turnover_k": latest["turnover_k"],
                "q60r": latest["q60r"],
                "trust_days": int(latest["trust_consecutive_days"])
            }

            if triggers["select_01_break_week"]:
                results["select_01_break_week"].append(stock_info)
            if triggers["select_02_break_hi120"]:
                results["select_02_break_hi120"].append(stock_info)
            if triggers["select_03_break_hi480"]:
                results["select_03_break_hi480"].append(stock_info)
            if triggers["select_04_dual_green"]:
                results["select_04_dual_green"].append(stock_info)
            if triggers["s_grade_chip"]:
                results["s_grade_chip"].append(stock_info)

            # 當沖動能候選
            if (triggers["select_01_break_week"] or latest["q60r"] >= 2.2) and (1.5 <= latest["pct_change"] <= 6.5):
                dt_plan = self.calculate_day_trading_plan(latest)
                results["day_trading_picks"].append({**stock_info, **dt_plan})

            # 隔日沖候選
            if triggers["s_grade_chip"] and latest["pct_change"] >= 3.0:
                on_plan = self.calculate_overnight_plan(latest)
                results["overnight_picks"].append({**stock_info, **on_plan})

        return results

# ------------------------------------------------------------------------------
# 6. 沙盒獨立全功能自我驗證測試 (Self-Test Harness)
# ------------------------------------------------------------------------------
def run_sandbox_tests():
    print("=" * 70)
    print("🧪 啟動 screening_engine.py 沙盒全功能驗證")
    print("=" * 70)

    # 模擬 500 天真實連續行情數據 (以台積電 2330 為範本)
    days = 500
    dates = pd.date_range(end="2026-08-28", periods=days, freq="B").strftime("%Y%m%d").tolist()
    
    base_price = 1000.0
    prices = [base_price]
    for i in range(1, days):
        prices.append(prices[-1] * (1 + 0.0018))

    df_mock = pd.DataFrame({
        "date": dates,
        "stock_id": "2330",
        "stock_name": "台積電",
        "market": "TW",
        "open": [p * 0.995 for p in prices],
        "high": [p * 1.008 for p in prices],
        "low": [p * 0.992 for p in prices],
        "close": prices,
        "volume": [1500] * (days - 1) + [4000],  # 今日爆量 (Q60R > 2.0)
        "turnover_k": [1500 * p for p in prices],
        "pct_change": [0.18] * (days - 1) + [2.8],
        "avg_price": prices,
        "foreign_net": [500] * days,
        "trust_net": [300] * days,               # 投信連買
        "dealer_net": [50] * days
    })

    # 微調最後 6 日行情以精確驗證突破與勾角
    df_mock.loc[days-6:days-2, "high"] = [2405.0, 2408.0, 2410.0, 2400.0, 2402.0]
    df_mock.loc[days-6:days-2, "close"] = [2395.0, 2400.0, 2405.0, 2395.0, 2400.0]
    
    # 當日強勢突破
    df_mock.loc[days-1, "open"] = 2405.0
    df_mock.loc[days-1, "high"] = 2425.0
    df_mock.loc[days-1, "low"] = 2400.0
    df_mock.loc[days-1, "close"] = 2420.0
    df_mock.loc[days-1, "avg_price"] = 2412.0
    df_mock.loc[days-1, "volume"] = 4000
    df_mock.loc[days-1, "turnover_k"] = 4000 * 2412

    # 1. 測試技術指標計算
    print("\n【測試 1：技術指標計算檢驗 (台積電模擬)】")
    df_ind = calculate_technical_indicators(df_mock)
    latest = df_ind.iloc[-1]
    print(f"  • 收盤價: {latest['close']} | 5MA: {latest['ma5']} | 60MA: {latest['ma60']}")
    print(f"  • Q60R 量比: {latest['q60r']} (預期 > 2.0)")
    print(f"  • 投信連買天數: {latest['trust_consecutive_days']} 天 | 5MA 向上勾角: {latest['ma5_hook_up']}")
    
    assert latest["q60r"] >= 2.0, "❌ Q60R 計算錯誤"
    assert latest["ma5_hook_up"] == True, "❌ 5MA 向上勾角判定錯誤"
    assert latest["trust_consecutive_days"] >= 3, "❌ 投信連買計算錯誤"
    print("  👉 測試 1 通過 ✅")

    # 2. 測試策略評估
    print("\n【測試 2：CaryBot 四大選股與流動性防護驗證】")
    engine = ScreeningEngine()
    triggers = engine.evaluate_carybot_strategies(df_ind)
    print(f"  • 台積電觸發策略: {triggers}")
    
    assert triggers["passed_liquidity"] == True, "❌ 流動性防護判定錯誤"
    assert triggers["select_01_break_week"] == True, "❌ 未成功觸發周帶量突破"
    assert triggers["s_grade_chip"] == True, "❌ 未成功觸發 S 級籌碼濾網"
    print("  👉 測試 2 通過 ✅")

    # 3. 測試當沖動能價位精算
    print("\n【測試 3：當沖動能專區價位精算卡驗收】")
    dt_card = engine.calculate_day_trading_plan(latest)
    print(f"  • 進場價: {dt_card['entry_price']} | 均價: {dt_card['avg_price']}")
    print(f"  • 第一停利 (+3%): {dt_card['tp1_target']} | 第二衝頂 (+6%): {dt_card['tp2_target']}")
    print(f"  • 均價停損價: {dt_card['stop_loss']}")
    print(f"  • 時間保護: {dt_card['time_protection']}")
    
    assert dt_card["tp1_target"] > dt_card["entry_price"], "❌ 停利價計算異常"
    assert dt_card["stop_loss"] < dt_card["entry_price"], "❌ 停損價計算異常"
    print("  👉 測試 3 通過 ✅")

    # 4. 測試隔日沖尾盤精算
    print("\n【測試 4：隔日沖精選專區價位精算卡驗收】")
    on_card = engine.calculate_overnight_plan(latest)
    print(f"  • 今日買進區間: {on_card['buy_zone']}")
    print(f"  • 明日開高目標: {on_card['target_open_zone']}")
    print(f"  • 強勢衝頂價: {on_card['target_top']} | 保本防守價: {on_card['defense_price']}")
    
    assert on_card["target_top"] > latest["close"], "❌ 隔日沖衝頂價異常"
    assert on_card["defense_price"] < latest["close"], "❌ 隔日沖防守價異常"
    print("  👉 測試 4 通過 ✅")

    print("\n" + "=" * 70)
    print("🎉 screening_engine.py 沙盒測試 100% 全部通過！可安心整合與替換。")
    print("=" * 70)

if __name__ == "__main__":
    run_sandbox_tests()
