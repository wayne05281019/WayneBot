# ==============================================================================
# WayneBot 專案核心模組二：即時選股與價位精算引擎 (screening_engine.py)
# 模組定位：CaryBot 四大選股策略、S級籌碼濾網、當沖/隔日沖價位精算、流動性防護
# ==============================================================================

import os
import sqlite3
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np


class ScreeningEngine:
    """WayneBot 量化選股與價位精算引擎"""

    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """取得 SQLite 連線"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def get_latest_trading_date(self) -> Optional[str]:
        """取得資料庫最新交易日期"""
        if not os.path.exists(self.db_path):
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM daily_quotes;")
            res = cursor.fetchone()
            return res[0] if res and res[0] else None

    def fetch_stock_history_df(self, stock_id: str, limit: int = 480) -> pd.DataFrame:
        """讀取單一標的歷史 K 線 DataFrame（依日期正序）"""
        with self._get_connection() as conn:
            query = f"""
            SELECT date, stock_id, stock_name, market, open, high, low, close, 
                   volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
            FROM daily_quotes
            WHERE stock_id = ?
            ORDER BY date DESC
            LIMIT ?;
            """
            df = pd.read_sql_query(query, conn, params=(stock_id, limit))
            if df.empty:
                return df
            return df.iloc[::-1].reset_index(drop=True)

    def load_universe_snapshot(self, min_volume: int = 1000, min_turnover_k: float = 30000.0) -> pd.DataFrame:
        """
        載入最新日全市場快照，並套用流動性防護濾網：
        - 日成交量 >= 1,000 張
        - 日成交額 >= 3,000 萬元 (30,000 千元)
        """
        latest_date = self.get_latest_trading_date()
        if not latest_date:
            return pd.DataFrame()

        with self._get_connection() as conn:
            query = f"""
            SELECT date, stock_id, stock_name, market, open, high, low, close, 
                   volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
            FROM daily_quotes
            WHERE date = ?
              AND volume >= ?
              AND turnover_k >= ?
            ORDER BY turnover_k DESC;
            """
            df = pd.read_sql_query(query, conn, params=(latest_date, min_volume, min_turnover_k))
            return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """計算關鍵技術指標與籌碼特徵"""
        if len(df) < 5:
            return {}

        closes = df['close'].values
        volumes = df['volume'].values
        trust_nets = df['trust_net'].values
        foreign_nets = df['foreign_net'].values

        curr_close = closes[-1]
        curr_vol = volumes[-1]
        curr_pct = df['pct_change'].values[-1]
        avg_p = df['avg_price'].values[-1]

        # 1. 均線計算
        ma5 = np.mean(closes[-5:])
        ma5_prev = np.mean(closes[-6:-1]) if len(closes) >= 6 else ma5
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else ma5
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else ma20
        ma120 = np.mean(closes[-120:]) if len(closes) >= 120 else ma60
        ma480 = np.mean(closes[-480:]) if len(closes) >= 480 else ma120

        # 5MA 向上勾角判斷
        ma5_hook_up = ma5 > ma5_prev

        # 2. 量能指標：Q60R（當日成交量 / 60日均量）
        vol_ma60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else np.mean(volumes)
        q60r = round(curr_vol / vol_ma60, 2) if vol_ma60 > 0 else 1.0

        # 3. 區間高低點
        hi5 = np.max(closes[-5:])
        hi5_prev = np.max(closes[-6:-1]) if len(closes) >= 6 else hi5
        hi120 = np.max(closes[-120:]) if len(closes) >= 120 else hi5
        hi120_prev = np.max(closes[-121:-1]) if len(closes) >= 121 else hi120
        hi480 = np.max(closes[-480:]) if len(closes) >= 480 else hi120
        hi480_prev = np.max(closes[-481:-1]) if len(closes) >= 481 else hi480

        low60 = np.min(closes[-60:]) if len(closes) >= 60 else np.min(closes)
        low20 = np.min(closes[-20:]) if len(closes) >= 20 else np.min(closes)
        high20 = np.max(closes[-20:]) if len(closes) >= 20 else np.max(closes)

        # 4. D20 偏離位置 (0% ~ 100%)
        d20 = round((curr_close - low20) / (high20 - low20) * 100, 1) if high20 > low20 else 50.0

        # 5. 籌碼指標：投信連買天數
        trust_consecutive_days = 0
        for val in reversed(trust_nets):
            if val > 0:
                trust_consecutive_days += 1
            else:
                break

        # S 級籌碼濾網：投信連買 >= 2 天 且 5MA 向上勾角 且 (外資+投信合計買超)
        inst_net_today = foreign_nets[-1] + trust_nets[-1]
        is_s_tier_chip = (trust_consecutive_days >= 2) and ma5_hook_up and (inst_net_today > 0)

        return {
            "curr_close": curr_close,
            "curr_vol": curr_vol,
            "curr_pct": curr_pct,
            "avg_price": avg_p,
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma120": round(ma120, 2),
            "ma480": round(ma480, 2),
            "ma5_hook_up": ma5_hook_up,
            "q60r": q60r,
            "hi5": hi5,
            "hi5_prev": hi5_prev,
            "hi120": hi120,
            "hi120_prev": hi120_prev,
            "hi480": hi480,
            "hi480_prev": hi480_prev,
            "low60": low60,
            "d20": d20,
            "trust_consecutive_days": trust_consecutive_days,
            "is_s_tier_chip": is_s_tier_chip,
            "foreign_net": foreign_nets[-1],
            "trust_net": trust_nets[-1]
        }

    # --------------------------------------------------------------------------
    # CaryBot 四大即時選股策略
    # --------------------------------------------------------------------------
    def evaluate_cary_strategies(self, indicators: Dict[str, Any]) -> List[str]:
        """評估符合之 CaryBot 選股策略"""
        if not indicators:
            return []

        matched = []
        c = indicators["curr_close"]
        pct = indicators["curr_pct"]
        q60r = indicators["q60r"]

        # Select 01: 周帶量突破 (收盤突破前5日高點 + Q60R >= 2.0 + 漲幅 > 1.5%)
        if c >= indicators["hi5_prev"] and q60r >= 2.0 and pct >= 1.5:
            matched.append("Select 01 周帶量突破")

        # Select 02: 突破Hi120 (突破半年新高 + Q60R >= 2.5)
        if c >= indicators["hi120_prev"] and q60r >= 2.5 and pct >= 2.0:
            matched.append("Select 02 突破Hi120")

        # Select 03: 突破Hi480 (突破兩年新高大底 + Q60R >= 3.0)
        if c >= indicators["hi480_prev"] and q60r >= 3.0 and pct >= 2.5:
            matched.append("Select 03 突破Hi480")

        # Select 04: 雙綠脫離 (D20 由低檔轉正脫離 + 脫離60日低點 + 帶量紅K)
        if indicators["d20"] > 10.0 and c > indicators["low60"] * 1.03 and q60r >= 1.5 and pct >= 1.0:
            matched.append("Select 04 雙綠脫離")

        return matched

    # --------------------------------------------------------------------------
    # 當沖動能與隔日沖價位精算
    # --------------------------------------------------------------------------
    def calculate_day_trading_levels(self, close_p: float, avg_p: float) -> Dict[str, float]:
        """
        當沖動能專區價位精算：
        - 建議進場價：收盤價/現價
        - 第一停利 (+3.0%)
        - 第二衝頂 (+6.0%)
        - 均價停損價：跌破當日成交均價或 -2.0%
        """
        entry = close_p
        take_profit_1 = round(entry * 1.03, 2)
        take_profit_2 = round(entry * 1.06, 2)
        stop_loss = round(min(avg_p, entry * 0.98), 2)

        return {
            "entry_price": entry,
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "stop_loss_price": stop_loss
        }

    def calculate_overnight_levels(self, close_p: float) -> Dict[str, Any]:
        """
        隔日沖精選專區價位精算：
        - 動態買進區間：[-1.0%, +0.8%]
        - 明日開高目標：[+3.5%, +4.8%]
        - 強勢衝頂價：+7.0%
        - 保本防守價：-1.5%
        """
        buy_min = round(close_p * 0.99, 2)
        buy_max = round(close_p * 1.008, 2)
        target_open_min = round(close_p * 1.035, 2)
        target_open_max = round(close_p * 1.048, 2)
        surge_top = round(close_p * 1.07, 2)
        defense_price = round(close_p * 0.985, 2)

        return {
            "buy_range": f"{buy_min} ~ {buy_max}",
            "target_open_range": f"{target_open_min} ~ {target_open_max}",
            "surge_top_price": surge_top,
            "defense_price": defense_price,
            "time_protection": "隔日 09:15 前若未達開高目標且量能停滯，強制市價保本平倉"
        }

    # --------------------------------------------------------------------------
    # 全市場智慧掃描與精選匯出
    # --------------------------------------------------------------------------
    def run_full_market_screening(self) -> Dict[str, List[Dict[str, Any]]]:
        """執行全市場量化選股掃描"""
        snapshot_df = self.load_universe_snapshot()
        if snapshot_df.empty:
            return {"cary_picks": [], "day_trading_picks": [], "overnight_picks": []}

        cary_picks = []
        day_trading_picks = []
        overnight_picks = []

        for _, row in snapshot_df.iterrows():
            sid = str(row['stock_id'])
            sname = str(row['stock_name'])

            # 讀取完整歷史以精算指標
            hist_df = self.fetch_stock_history_df(sid, limit=480)
            if len(hist_df) < 20:
                continue

            ind = self.calculate_technical_indicators(hist_df)
            if not ind:
                continue

            matched_strategies = self.evaluate_cary_strategies(ind)
            close_p = ind["curr_close"]
            avg_p = ind["avg_price"]

            # 1. CaryBot 強勢選股收錄
            if matched_strategies:
                cary_picks.append({
                    "stock_id": sid,
                    "stock_name": sname,
                    "close": close_p,
                    "pct_change": ind["curr_pct"],
                    "volume": ind["curr_vol"],
                    "q60r": ind["q60r"],
                    "strategies": matched_strategies,
                    "is_s_tier": ind["is_s_tier_chip"],
                    "trust_net": ind["trust_net"]
                })

            # 2. 當沖動能精選：漲幅 2.5%~7%、Q60R >= 2.0、外資或投信有買盤
            if 2.5 <= ind["curr_pct"] <= 7.0 and ind["q60r"] >= 2.0 and (ind["foreign_net"] > 0 or ind["trust_net"] > 0):
                levels = self.calculate_day_trading_levels(close_p, avg_p)
                day_trading_picks.append({
                    "stock_id": sid,
                    "stock_name": sname,
                    "close": close_p,
                    "pct_change": ind["curr_pct"],
                    "volume": ind["curr_vol"],
                    "levels": levels,
                    "is_s_tier": ind["is_s_tier_chip"]
                })

            # 3. 隔日沖精選：強勢收盤（漲幅 3.5%~8.5%）、帶量且 5MA 勾角、投信佈局
            if 3.5 <= ind["curr_pct"] <= 8.5 and ind["q60r"] >= 1.8 and ind["ma5_hook_up"]:
                ov_levels = self.calculate_overnight_levels(close_p)
                overnight_picks.append({
                    "stock_id": sid,
                    "stock_name": sname,
                    "close": close_p,
                    "pct_change": ind["curr_pct"],
                    "volume": ind["curr_vol"],
                    "levels": ov_levels,
                    "is_s_tier": ind["is_s_tier_chip"],
                    "trust_consecutive_days": ind["trust_consecutive_days"]
                })

        return {
            "cary_picks": cary_picks,
            "day_trading_picks": day_trading_picks[:10],
            "overnight_picks": overnight_picks[:10]
        }


# ==============================================================================
# 獨立沙盒驗收測試區塊
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 啟動 screening_engine.py 模組獨立驗收測試")
    print("=" * 70)

    engine = ScreeningEngine("waynebot_history.db")
    latest_date = engine.get_latest_trading_date()

    if not latest_date:
        print("❌ 錯誤：未找到 waynebot_history.db 資料庫或資料表為空！")
    else:
        print(f"📅 基準交易日: {latest_date}")
        
        # 測試 1：流動性快照載入
        snapshot = engine.load_universe_snapshot()
        print(f"\n【測試 1：流動性過濾快照】")
        print(f"  • 通過流動性門檻 (>=1,000張 & >=3,000萬) 標的數: {len(snapshot)} 檔")
        assert len(snapshot) > 0, "❌ 流動性快照為空！"

        # 測試 2：全市場量化選股掃描
        print(f"\n【測試 2：全市場 CaryBot / 當沖 / 隔日沖 掃描】")
        results = engine.run_full_market_screening()

        cary_picks = results["cary_picks"]
        dt_picks = results["day_trading_picks"]
        ov_picks = results["overnight_picks"]

        print(f"  • CaryBot 觸發標的數 : {len(cary_picks)} 檔")
        print(f"  • 當沖動能精選標的數 : {len(dt_picks)} 檔")
        print(f"  • 隔日沖精選標的數   : {len(ov_picks)} 檔")

        # 展示 CaryBot 選股範例
        if cary_picks:
            print("\n  👉 CaryBot 精選代表展示（前 3 檔）：")
            for p in cary_picks[:3]:
                s_tag = "【🌟 S級籌碼】" if p["is_s_tier"] else ""
                print(f"    - [{p['stock_id']}] {p['stock_name']:<8} | 收盤: {p['close']:>6.2f} ({p['pct_change']:>+5.2f}%) | Q60R: {p['q60r']:>4.1f} | 策略: {', '.join(p['strategies'])} {s_tag}")

        # 展示當沖價位精算範例
        if dt_picks:
            sample_dt = dt_picks[0]
            lv = sample_dt["levels"]
            print(f"\n  👉 當沖動能價位精算展示（以 [{sample_dt['stock_id']}] {sample_dt['stock_name']} 為例）：")
            print(f"    - 進場參考價 : {lv['entry_price']} 元")
            print(f"    - 第一停利(+3%): {lv['take_profit_1']} 元")
            print(f"    - 第二衝頂(+6%): {lv['take_profit_2']} 元")
            print(f"    - 均價防守線 : {lv['stop_loss_price']} 元")

        # 展示隔日沖價位精算範例
        if ov_picks:
            sample_ov = ov_picks[0]
            olv = sample_ov["levels"]
            print(f"\n  👉 隔日沖價位精算展示（以 [{sample_ov['stock_id']}] {sample_ov['stock_name']} 為例）：")
            print(f"    - 今日買進區間   : {olv['buy_range']} 元")
            print(f"    - 明日開高目標   : {olv['target_open_range']} 元")
            print(f"    - 強勢衝頂價     : {olv['surge_top_price']} 元")
            print(f"    - 保本防守價     : {olv['defense_price']} 元")
            print(f"    - 時間保護原則   : {olv['time_protection']}")

        print("\n" + "=" * 70)
        print("🎉 screening_engine.py 沙盒測試驗收完成！")
        print("=" * 70)
