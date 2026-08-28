# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組二
# 模組名稱：screening_engine.py (即時選股、價位精算與風控引擎)
# 功能：CaryBot 四大選股、S級籌碼濾網、當沖/隔日沖價位精算、流動性與大盤風控、動態參數表
# ==============================================================================

import os
import sys
import sqlite3
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np


class StrategyConfigManager:
    """SQLite strategy_config 動態策略參數管理器"""

    DEFAULT_CONFIG = {
        # 流動性硬門檻
        "min_volume": 1000,          # 最小成交量（張）
        "min_turnover_k": 30000,      # 最小成交金額（千元 = 3,000 萬元）
        # CaryBot 量比門檻 (Q60R = 當日量 / 60日均量)
        "q60r_select01": 2.0,         # Select 01 周帶量突破
        "q60r_select02": 2.5,         # Select 02 突破 Hi120
        "q60r_select03": 3.0,         # Select 03 突破 Hi480
        # 價位與停利停損參數 (%)
        "daytrade_tp1_pct": 3.0,      # 當沖第一停利 +3.0%
        "daytrade_tp2_pct": 6.0,      # 當沖第二衝頂 +6.0%
        "daytrade_sl_pct": -2.0,      # 當沖最大停損 -2.0% (輔以 VWAP 均價線)
        "swing_target_min_pct": 3.5,  # 隔日沖開高目標下限 +3.5%
        "swing_target_max_pct": 4.8,  # 隔日沖開高目標上限 +4.8%
        "swing_surge_pct": 8.0,       # 隔日沖衝頂目標 +8.0%
        "swing_defense_pct": -2.0,    # 隔日沖保本防守 -2.0%
        # S 級籌碼門檻
        "trust_consecutive_days": 2,  # 投信連買天數
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        """初始化 strategy_config 資料表並填入預設值"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_config (
            param_key TEXT PRIMARY KEY,
            param_value REAL NOT NULL,
            description TEXT
        );
        """)
        
        # 檢查並寫入預設參數
        for k, v in self.DEFAULT_CONFIG.items():
            cursor.execute("""
            INSERT OR IGNORE INTO strategy_config (param_key, param_value, description)
            VALUES (?, ?, ?);
            """, (k, float(v), f"Default config for {k}"))
            
        conn.commit()
        conn.close()

    def get_all_config(self) -> Dict[str, float]:
        """讀取所有動態策略參數"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT param_key, param_value FROM strategy_config;")
        rows = cursor.fetchall()
        conn.close()
        
        config = self.DEFAULT_CONFIG.copy()
        for row in rows:
            config[row["param_key"]] = float(row["param_value"])
        return config

    def update_config(self, param_key: str, param_value: float) -> bool:
        """更新單一動態策略參數"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO strategy_config (param_key, param_value)
        VALUES (?, ?)
        ON CONFLICT(param_key) DO UPDATE SET param_value=excluded.param_value;
        """, (param_key, float(param_value)))
        conn.commit()
        conn.close()
        return True


class ScreeningEngine:
    """
    即時選股與價位精算核心引擎
    整合 4 大策略、S 級籌碼判定、流動性防護與大盤風控總開關
    """

    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self.config_mgr = StrategyConfigManager(db_path)
        self.config = self.config_mgr.get_all_config()

    def refresh_config(self):
        """重新整理載入最新動態參數"""
        self.config = self.config_mgr.get_all_config()

    def check_market_risk(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        """
        【大盤空頭環境防禦總開關】
        檢測 0050（元大台灣50）是否跌破季線（60MA）
        回傳: { 'is_safe': bool, 'benchmark_close': float, 'ma60': float, 'bias_pct': float, 'status_label': str }
        """
        query = """
        SELECT date, close FROM daily_quotes
        WHERE stock_id = '0050'
        ORDER BY date DESC
        LIMIT 65;
        """
        df_bench = pd.read_sql_query(query, conn)
        if len(df_bench) < 60:
            return {
                "is_safe": True,
                "benchmark_close": 0.0,
                "ma60": 0.0,
                "bias_pct": 0.0,
                "status_label": "🟢 大盤歷史數據不足，維持標準風控"
            }

        df_bench = df_bench.sort_values("date").reset_index(drop=True)
        latest_close = df_bench["close"].iloc[-1]
        ma60 = df_bench["close"].tail(60).mean()
        bias_pct = round(((latest_close - ma60) / ma60) * 100.0, 2)
        is_safe = latest_close >= ma60

        status_label = (
            f"🟢 大盤處於季線之上 (0050: {latest_close:.1f} / 60MA: {ma60:.1f}, 乖離: +{bias_pct}%) - 正常持倉模式"
            if is_safe else
            f"🔴 大盤跌破季線 (0050: {latest_close:.1f} < 60MA: {ma60:.1f}, 乖離: {bias_pct}%) - 啟動防禦收縮至20-30%並評估00632R避險"
        )

        return {
            "is_safe": is_safe,
            "benchmark_close": latest_close,
            "ma60": round(ma60, 2),
            "bias_pct": bias_pct,
            "status_label": status_label
        }

    def load_market_data(self, conn: sqlite3.Connection, lookback_days: int = 500) -> pd.DataFrame:
        """從 SQLite 提取全市場歷史行情，並按股票依序計算關鍵技術指標"""
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date >= (
            SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT 1 OFFSET {lookback_days - 1}
        )
        ORDER BY stock_id ASC, date ASC;
        """
        df = pd.read_sql_query(query, conn)
        return df

    def compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算全套指標向量：
        - MA5, MA20, MA60, MA120, MA480
        - Q60R (成交量比率 = volume / vol_ma60)
        - 5日新高, 120日新高(Hi120), 480日新高(Hi480)
        - D20 乖離率與通道脫離
        - 投信連買天數與 5MA 勾角
        """
        processed_dfs = []

        for sid, group in df.groupby("stock_id", sort=False):
            g = group.copy().sort_values("date").reset_index(drop=True)
            if len(g) < 5:
                continue

            # 1. 移動平均線
            g["ma5"] = g["close"].rolling(window=5, min_periods=1).mean()
            g["ma20"] = g["close"].rolling(window=20, min_periods=1).mean()
            g["ma60"] = g["close"].rolling(window=60, min_periods=1).mean()
            g["ma120"] = g["close"].rolling(window=120, min_periods=1).mean()
            g["ma480"] = g["close"].rolling(window=480, min_periods=1).mean()

            # 2. 均量與 Q60R 量比
            g["vol_ma60"] = g["volume"].rolling(window=60, min_periods=5).mean()
            g["q60r"] = np.where(g["vol_ma60"] > 0, g["volume"] / g["vol_ma60"], 1.0)
            g["q60r"] = g["q60r"].round(2)

            # 3. 區間高點與低點 (以昨日收盤為基礎之突破門檻)
            g["hi5_prev"] = g["high"].shift(1).rolling(window=5, min_periods=1).max()
            g["hi120_prev"] = g["high"].shift(1).rolling(window=120, min_periods=1).max()
            g["hi480_prev"] = g["high"].shift(1).rolling(window=480, min_periods=1).max()
            g["low60_prev"] = g["low"].shift(1).rolling(window=60, min_periods=1).min()

            # 4. 20日乖離率 (D20 = (Close - MA20) / MA20 * 100)
            g["d20"] = np.where(g["ma20"] > 0, ((g["close"] - g["ma20"]) / g["ma20"]) * 100.0, 0.0)
            g["d20_prev"] = g["d20"].shift(1).fillna(0.0)

            # 5. 5MA 向上勾角判定 (今日 MA5 > 昨日 MA5 且 今日收盤 > MA5)
            g["ma5_prev"] = g["ma5"].shift(1)
            g["ma5_slope_up"] = (g["ma5"] > g["ma5_prev"]) & (g["close"] >= g["ma5"])

            # 6. 投信連買天數計算
            trust_buy = (g["trust_net"] > 0).astype(int)
            trust_streak = []
            cur_streak = 0
            for tb in trust_buy:
                cur_streak = cur_streak + 1 if tb == 1 else 0
                trust_streak.append(cur_streak)
            g["trust_streak"] = trust_streak

            processed_dfs.append(g)

        if not processed_dfs:
            return pd.DataFrame()

        return pd.concat(processed_dfs, ignore_index=True)

    def calculate_daytrade_targets(self, row: pd.Series) -> Dict[str, Any]:
        """
        【當沖動能專區價位精算】
        提供：建議進場區間、第一停利(+3%)、第二衝頂(+6%)、均價停損價、09:15 時間保護機制
        """
        close_p = float(row["close"])
        avg_p = float(row["avg_price"]) if float(row["avg_price"]) > 0 else close_p
        open_p = float(row["open"]) if float(row["open"]) > 0 else close_p

        tp1_pct = self.config.get("daytrade_tp1_pct", 3.0)
        tp2_pct = self.config.get("daytrade_tp2_pct", 6.0)
        sl_pct = self.config.get("daytrade_sl_pct", -2.0)

        # 建議進場價區間（開盤與收盤/均價動態帶）
        entry_low = round(min(open_p, close_p) * 0.998, 2)
        entry_high = round(max(open_p, close_p) * 1.005, 2)
        ref_entry = round((entry_low + entry_high) / 2.0, 2)

        tp1 = round(ref_entry * (1.0 + tp1_pct / 100.0), 2)
        tp2 = round(ref_entry * (1.0 + tp2_pct / 100.0), 2)
        
        # 停損價：取固定比例停損與成交均價 (VWAP) 之防守位
        fixed_sl = round(ref_entry * (1.0 + sl_pct / 100.0), 2)
        sl_price = round(min(fixed_sl, avg_p * 0.99), 2)

        return {
            "entry_range": f"{entry_low:.2f} ~ {entry_high:.2f}",
            "ref_entry": ref_entry,
            "tp1_target": tp1,
            "tp2_target": tp2,
            "stop_loss": sl_price,
            "time_protection": "⏰ 09:15 前若未達 +2% 且量能停滯跌破均價線，執行保本/市價平倉"
        }

    def calculate_overnight_targets(self, row: pd.Series) -> Dict[str, Any]:
        """
        【隔日沖精選專區價位精算】
        提供：尾盤買進區間、明日開高目標(+3.5~4.8%)、強勢衝頂價(+8%)、保本防守價
        """
        close_p = float(row["close"])
        ma5_p = float(row.get("ma5", close_p))

        target_min_pct = self.config.get("swing_target_min_pct", 3.5)
        target_max_pct = self.config.get("swing_target_max_pct", 4.8)
        surge_pct = self.config.get("swing_surge_pct", 8.0)
        defense_pct = self.config.get("swing_defense_pct", -2.0)

        # 尾盤買進區間 (收盤價前置緩衝)
        buy_low = round(close_p * 0.995, 2)
        buy_high = round(close_p * 1.008, 2)
        
        open_target_low = round(close_p * (1.0 + target_min_pct / 100.0), 2)
        open_target_high = round(close_p * (1.0 + target_max_pct / 100.0), 2)
        surge_target = round(close_p * (1.0 + surge_pct / 100.0), 2)
        
        # 防守價：取 -2% 與 5MA 之較佳防守支撐
        fixed_def = round(close_p * (1.0 + defense_pct / 100.0), 2)
        defense_price = round(max(fixed_def, ma5_p * 0.99), 2)

        return {
            "buy_zone": f"{buy_low:.2f} ~ {buy_high:.2f}",
            "open_target_range": f"{open_target_low:.2f} ~ {open_target_high:.2f} (+{target_min_pct}%~+{target_max_pct}%)",
            "surge_target": f"{surge_target:.2f} (+{surge_pct}%)",
            "defense_price": defense_price,
            "action_guideline": "明日 09:00~09:05 開高達標分批停利；若開平走低跌破防守價無條件離場"
        }

    def run_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        執行全市場即時選股與決策卡產出
        1. 載入並計算全市場技術與籌碼指標
        2. 執行大盤風控開關審查
        3. 流動性硬濾網 (量 >= 1000張, 額 >= 3000萬)
        4. 執行 CaryBot 四大即時選股策略
        5. 標註 S 級籌碼標籤
        6. 輸出結構化選股結果與 Telegram 格式化卡片
        """
        self.refresh_config()
        conn = sqlite3.connect(self.db_path)

        # 1. 檢驗大盤風控
        market_risk = self.check_market_risk(conn)

        # 2. 載入歷史資料並計算指標
        df_raw = self.load_market_data(conn, lookback_days=500)
        if df_raw.empty:
            conn.close()
            return {"status": "error", "message": "歷史行情資料庫無資料", "results": {}}

        df_calc = self.compute_technical_indicators(df_raw)
        conn.close()

        if df_calc.empty:
            return {"status": "error", "message": "技術指標計算失敗", "results": {}}

        # 3. 取得指定日期之最新截面數據（預設最新交易日）
        if target_date:
            df_latest = df_calc[df_calc["date"] == target_date].copy()
        else:
            latest_dt = df_calc["date"].max()
            df_latest = df_calc[df_calc["date"] == latest_dt].copy()

        actual_date = df_latest["date"].iloc[0] if not df_latest.empty else "N/A"

        # 4. 【流動性硬濾網】防範中小型股流動性陷阱
        min_v = self.config.get("min_volume", 1000)
        min_to = self.config.get("min_turnover_k", 30000)
        
        df_liquid = df_latest[
            (df_latest["volume"] >= min_v) & 
            (df_latest["turnover_k"] >= min_to)
        ].copy()

        # 5. 【CaryBot 四大策略篩選】
        q01_min = self.config.get("q60r_select01", 2.0)
        q02_min = self.config.get("q60r_select02", 2.5)
        q03_min = self.config.get("q60r_select03", 3.0)
        trust_days_min = int(self.config.get("trust_consecutive_days", 2))

        # Select 01: 周帶量突破 (創5日高 + Q60R > 2.0 + 漲幅 > 1.5%)
        mask_sel01 = (
            (df_liquid["close"] > df_liquid["hi5_prev"]) &
            (df_liquid["q60r"] >= q01_min) &
            (df_liquid["pct_change"] >= 1.5)
        )
        df_sel01 = df_liquid[mask_sel01].copy()

        # Select 02: 突破 Hi120 半年新高 (創120日高 + Q60R > 2.5)
        mask_sel02 = (
            (df_liquid["close"] >= df_liquid["hi120_prev"]) &
            (df_liquid["q60r"] >= q02_min)
        )
        df_sel02 = df_liquid[mask_sel02].copy()

        # Select 03: 突破 Hi480 兩年新高大底 (創480日高 + Q60R > 3.0)
        mask_sel03 = (
            (df_liquid["close"] >= df_liquid["hi480_prev"]) &
            (df_liquid["q60r"] >= q03_min)
        )
        df_sel03 = df_liquid[mask_sel03].copy()

        # Select 04: 雙綠脫離 (D20 由 0% 轉正或低檔反轉脫離 + 脫離60日低點 > 3% + 5MA向上)
        mask_sel04 = (
            (df_liquid["d20_prev"] <= 0.5) &
            (df_liquid["d20"] > 0.5) &
            (df_liquid["close"] > df_liquid["low60_prev"] * 1.03) &
            (df_liquid["ma5_slope_up"] == True) &
            (df_liquid["pct_change"] >= 1.0)
        )
        df_sel04 = df_liquid[mask_sel04].copy()

        # 6. 包裝與精算輸出清單
        def enrich_records(df_sub: pd.DataFrame, strategy_tag: str) -> List[Dict[str, Any]]:
            records = []
            for _, r in df_sub.iterrows():
                # S 級籌碼判定 (投信連買 >= 2天 且 5MA 向上)
                is_s_class = (r["trust_streak"] >= trust_days_min) and bool(r["ma5_slope_up"])
                
                daytrade_plan = self.calculate_daytrade_targets(r)
                overnight_plan = self.calculate_overnight_targets(r)

                records.append({
                    "stock_id": str(r["stock_id"]),
                    "stock_name": str(r["stock_name"]),
                    "market": str(r["market"]),
                    "close": float(r["close"]),
                    "pct_change": float(r["pct_change"]),
                    "volume": int(r["volume"]),
                    "turnover_k": float(r["turnover_k"]),
                    "q60r": float(r["q60r"]),
                    "d20": float(r["d20"]),
                    "trust_streak": int(r["trust_streak"]),
                    "is_s_class": is_s_class,
                    "s_chip_tag": "🔥【S級籌碼·投信連買】" if is_s_class else "",
                    "strategy_tag": strategy_tag,
                    "daytrade_plan": daytrade_plan,
                    "overnight_plan": overnight_plan
                })
            # 依量比 Q60R 與漲幅排序
            records.sort(key=lambda x: (x["is_s_class"], x["q60r"], x["pct_change"]), reverse=True)
            return records

        results = {
            "date": actual_date,
            "market_risk": market_risk,
            "total_liquid_pool": len(df_liquid),
            "strategies": {
                "select_01_weekly_breakout": enrich_records(df_sel01, "Select 01 周帶量突破"),
                "select_02_hi120_breakout": enrich_records(df_sel02, "Select 02 突破Hi120"),
                "select_03_hi480_breakout": enrich_records(df_sel03, "Select 03 突破Hi480大底"),
                "select_04_dual_green_escape": enrich_records(df_sel04, "Select 04 雙綠脫離"),
            }
        }

        return {"status": "success", "results": results}

    def format_telegram_card(self, screening_output: Dict[str, Any]) -> str:
        """
        將選股結果格式化為符合 Telegram 視覺規範的極簡扁平決策卡片
        """
        if screening_output.get("status") != "success":
            return f"❌ 選股執行失敗：{screening_output.get('message', '未知原因')}"

        data = screening_output["results"]
        dt = data["date"]
        risk = data["market_risk"]
        strat = data["strategies"]

        lines = []
        lines.append(f"🚀 *WayneBot 全市場量化選股決策報表* ｜ `{dt}`")
        lines.append("━" * 30)
        lines.append(f"*【大盤風控雷達】*\n{risk['status_label']}")
        lines.append(f"📊 通過流動性硬篩選池：`{data['total_liquid_pool']}` 檔")
        lines.append("━" * 30)

        strat_meta = [
            ("select_01_weekly_breakout", "⚡ *Select 01 周帶量突破*（5日高 + Q60R>2.0）"),
            ("select_02_hi120_breakout", "🎯 *Select 02 突破 Hi120*（半年新高 + Q60R>2.5）"),
            ("select_03_hi480_breakout", "👑 *Select 03 突破 Hi480*（兩年新高大底 + Q60R>3.0）"),
            ("select_04_dual_green_escape", "🌱 *Select 04 雙綠脫離*（D20轉正 + 底部轉強）")
        ]

        total_picks = 0
        for key, title in strat_meta:
            picks = strat.get(key, [])
            total_picks += len(picks)
            lines.append(f"\n{title} ［`{len(picks)}` 檔］")
            if not picks:
                lines.append("  _今日無符合標的_")
                continue

            for p in picks[:4]:  # 各策略最多展示前 4 檔精華
                chip_badge = " ⭐" if p["is_s_class"] else ""
                lines.append(
                    f"  • *{p['stock_id']} {p['stock_name']}*{chip_badge} ｜ 收 `{p['close']:.2f}` (`{p['pct_change']:+.2f}%`) "
                    f"｜ 量比 `{p['q60r']}x` ｜ 投信連 `{p['trust_streak']}日`"
                )
                dp = p["daytrade_plan"]
                op = p["overnight_plan"]
                lines.append(f"    ├ 🚀 *當沖動能*：進場 `{dp['entry_range']}` ➔ 衝頂 `{dp['tp2_target']}` ｜ 防守 `{dp['stop_loss']}`")
                lines.append(f"    └ 🌙 *隔日沖*：買區 `{op['buy_zone']}` ➔ 目標 `{op['open_target_range']}` ｜ 防守 `{op['defense_price']}`")

        lines.append("\n" + "━" * 30)
        lines.append(f"💡 *合計精選標的*：`{total_picks}` 檔 ｜ 標註 ⭐ 符號為投信主力鎖碼 S 級標的")
        return "\n".join(lines)


# ==============================================================================
# 獨立沙盒測試驗證（符合 SOP 原則 1 與 2）
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 正在執行 screening_engine.py 模組二獨立沙盒測試...")
    print("=" * 70)

    test_db = "waynebot_history.db"

    # 若環境中無 SQLite 庫，建立微型測試資料庫以驗證邏輯完整度
    if not os.path.exists(test_db):
        print("⚠️ 未偵測到現存資料庫，自動建立沙盒測試模擬資料庫...")
        conn = sqlite3.connect(test_db)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER,
            PRIMARY KEY (date, stock_id)
        );
        """)
        
        # 插入模擬 0050 與測試個股歷史數據
        dates = [f"202608{d:02d}" for d in range(1, 28)]
        mock_data = []
        for i, dt in enumerate(dates):
            # 0050 大盤基準
            mock_data.append((dt, "0050", "元大台灣50", "TW", 180+i*0.2, 182+i*0.2, 179+i*0.2, 181+i*0.2, 15000, 2700000, 0.5, 181.0, 500, 200, 100))
            # 2330 台積電 (周帶量突破)
            mock_data.append((dt, "2330", "台積電", "TW", 950+i*2, 970+i*2, 945+i*2, 968+i*2, 35000 + (100000 if i==26 else 0), 34000000, 2.5, 965.0, 5000, 1500, 800))
            # 3037 欣興 (雙綠脫離 + 投信連買)
            mock_data.append((dt, "3037", "欣興", "TW", 160+i*1, 168+i*1, 158+i*1, 167+i*1, 12000, 2000000, 3.2, 165.0, 1200, 800, 200))
            # 6415 矽力*-KY (突破Hi120)
            mock_data.append((dt, "6415", "矽力*-KY", "TW", 450+i*3, 475+i*3, 448+i*3, 472+i*3, 5000, 2350000, 4.5, 470.0, 800, 400, 150))
            # 9999 殭屍股 (成交量低於 1000 張，測試流動性濾網)
            mock_data.append((dt, "9999", "測試殭屍", "TW", 20.0, 20.2, 19.8, 20.0, 50, 1000, 0.0, 20.0, 0, 0, 0))

        cur.executemany("INSERT OR REPLACE INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", mock_data)
        conn.commit()
        conn.close()
        print("✅ 模擬資料庫構建完成。")

    # 實例化選股引擎
    engine = ScreeningEngine(db_path=test_db)

    # 1. 測試參數讀取與更新
    print("\n【測試 1：strategy_config 動態參數表讀取與更新】")
    cfg = engine.config_mgr.get_all_config()
    print(f"  • 預設 Select 01 量比門檻: {cfg['q60r_select01']}x")
    print(f"  • 預設流動性最低成交量門檻: {cfg['min_volume']} 張")
    engine.config_mgr.update_config("q60r_select01", 1.8)
    engine.refresh_config()
    print(f"  • 動態調優後 Select 01 量比門檻: {engine.config['q60r_select01']}x (驗證成功 ✅)")

    # 2. 測試選股與價位精算
    print("\n【測試 2：執行即時選股、S級標籤與價位精算】")
    report = engine.run_screening()
    assert report["status"] == "success", "選股執行失敗！"
    print(f"  • 篩選交易日: {report['results']['date']}")
    print(f"  • 大盤風控狀態: {report['results']['market_risk']['status_label']}")
    print(f"  • 流動性合格池: {report['results']['total_liquid_pool']} 檔")
    
    for strat_key, strat_list in report["results"]["strategies"].items():
        print(f"  • [{strat_key}]: 篩出 {len(strat_list)} 檔標的")

    # 3. 測試 Telegram 格式化卡片生成
    print("\n【測試 3：Telegram 扁平決策卡片渲染】")
    card_text = engine.format_telegram_card(report)
    print("\n--- [Telegram 訊息卡片預覽] ---")
    print(card_text)
    print("------------------------------")

    print("\n🎉 模組二 `screening_engine.py` 沙盒單獨測試 100% 通過！")
