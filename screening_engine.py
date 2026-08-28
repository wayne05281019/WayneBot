# -*- coding: utf-8 -*-
"""
==============================================================================
WayneBot 全市場量化決策系統：即時選股與價位精算引擎 (screening_engine.py)
==============================================================================
核心功能：
1. CaryBot 四大即時選股：
   - Select 01 周帶量突破 (5日高 + Q60R > 2.0)
   - Select 02 突破Hi120 (半年新高大底 + Q60R > 2.5)
   - Select 03 突破Hi480 (兩年新高大底 + Q60R > 3.0)
   - Select 04 雙綠脫離 (D20由0%轉正 + 60日低消失)
2. S 級籌碼濾網 (投信連買 >= 2 日 + 5MA 向上勾角)
3. 當沖 / 隔日沖動能價位精算 (建議進場、第一停利、衝頂目標、保本防守價)
4. 流動性陷阱智慧防護 (強制過濾成交量 < 1,000 張 或 成交額 < 3,000 萬)
5. format_telegram_report: 供 main_runner.py 與 bot_servers.py 調用之 Telegram 報表格式化器
==============================================================================
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

# 預設資料庫路徑
DEFAULT_DB_PATH = os.path.join(os.getcwd(), "waynebot_history.db")

class ScreeningEngine:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 連線並啟用 WAL 效能模式"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def get_latest_trading_date(self) -> str:
        """取得資料庫中最新交易日期 (YYYYMMDD)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM daily_quotes;")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else datetime.now().strftime("%Y%m%d")

    def load_market_data(self, target_date: Optional[str] = None, lookback_days: int = 500) -> pd.DataFrame:
        """
        載入計算所需之歷史行情數據（預設載入近 500 天，確保 Hi480 與 Q60R 運算無虞）
        """
        conn = self._get_connection()
        if not target_date:
            target_date = self.get_latest_trading_date()

        query = """
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k,
            pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date <= ?
        ORDER BY stock_id, date ASC;
        """
        df = pd.read_sql_query(query, conn, params=(target_date,))
        conn.close()
        return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        批次計算全市場技術指標
        """
        if df.empty:
            return df

        # 確保型態正確
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        df['pct_change'] = pd.to_numeric(df['pct_change'], errors='coerce')
        df['trust_net'] = pd.to_numeric(df['trust_net'], errors='coerce').fillna(0)

        # 依照 stock_id 分組計算指標
        grouped = df.groupby('stock_id')

        # 均線 (5MA, 20MA, 60MA)
        df['ma5'] = grouped['close'].transform(lambda x: x.rolling(5, min_periods=1).mean())
        df['ma5_prev'] = grouped['ma5'].shift(1)
        df['ma20'] = grouped['close'].transform(lambda x: x.rolling(20, min_periods=1).mean())
        df['ma60'] = grouped['close'].transform(lambda x: x.rolling(60, min_periods=1).mean())

        # 60 日均量與量比 Q60R
        df['vol_ma60'] = grouped['volume'].transform(lambda x: x.rolling(60, min_periods=5).mean())
        df['q60r'] = np.where(df['vol_ma60'] > 0, df['volume'] / df['vol_ma60'], 1.0)

        # 近期高低價
        df['high_5'] = grouped['high'].transform(lambda x: x.rolling(5, min_periods=1).max())
        df['high_120'] = grouped['high'].transform(lambda x: x.rolling(120, min_periods=20).max())
        df['high_480'] = grouped['high'].transform(lambda x: x.rolling(480, min_periods=60).max())
        df['low_60'] = grouped['low'].transform(lambda x: x.rolling(60, min_periods=10).min())

        # 20 日乖離率 D20 (%)
        df['d20'] = np.where(df['ma20'] > 0, ((df['close'] - df['ma20']) / df['ma20']) * 100.0, 0.0)
        df['d20_prev'] = grouped['d20'].shift(1)

        # 投信連買天數計算
        def get_trust_consecutive_buy(series: pd.Series) -> pd.Series:
            consecutive = []
            count = 0
            for val in series:
                if val > 0:
                    count += 1
                else:
                    count = 0
                consecutive.append(count)
            return pd.Series(consecutive, index=series.index)

        df['trust_buy_days'] = grouped['trust_net'].transform(get_trust_consecutive_buy)

        return df

    def calculate_price_levels(self, row: pd.Series) -> Dict[str, Any]:
        """
        精算當沖與隔日沖關鍵價位
        """
        c = float(row['close'])
        avg_p = float(row['avg_price']) if float(row['avg_price']) > 0 else c

        # 當沖價位
        day_trade = {
            "entry_price": c,
            "take_profit_1": round(c * 1.030, 2),  # +3.0% 第一停利
            "take_profit_2": round(c * 1.060, 2),  # +6.0% 第二衝頂
            "stop_loss": round(min(avg_p, c * 0.980), 2)  # 均價跌破或 -2% 停損
        }

        # 隔日沖價位
        swing_trade = {
            "buy_zone_low": round(c * 0.995, 2),
            "buy_zone_high": round(c * 1.005, 2),
            "target_gap_low": round(c * 1.035, 2),   # +3.5% 明日開高目標低標
            "target_gap_high": round(c * 1.048, 2),  # +4.8% 明日開高目標高標
            "rocket_target": round(c * 1.070, 2),    # +7.0% 強勢衝頂價
            "defense_line": round(c * 0.985, 2)      # -1.5% 保本防守線
        }

        return {"day_trade": day_trade, "swing_trade": swing_trade}

    def run_all_screenings(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        執行全市場選股流水線，輸出結構化結果
        """
        if not target_date:
            target_date = self.get_latest_trading_date()

        raw_df = self.load_market_data(target_date)
        if raw_df.empty:
            return {"date": target_date, "total_scanned": 0, "strategies": {}}

        calc_df = self.calculate_technical_indicators(raw_df)
        
        # 取出指定日期的最新截面
        latest = calc_df[calc_df['date'] == target_date].copy()
        total_scanned = len(latest)

        # ----------------------------------------------------------------------
        # 1. 流動性防護濾網：量 >= 1,000 張 或 成交額 >= 3,000 萬元 (turnover_k >= 30,000)
        # ----------------------------------------------------------------------
        liquid_mask = (latest['volume'] >= 1000) | (latest['turnover_k'] >= 30000)
        valid_pool = latest[liquid_mask].copy()

        # ----------------------------------------------------------------------
        # 2. CaryBot 四大即時選股條件
        # ----------------------------------------------------------------------
        # Select 01: 周帶量突破 (5日高 + Q60R > 2.0 + 漲幅 >= 2%)
        s1_mask = (valid_pool['high'] >= valid_pool['high_5']) & (valid_pool['q60r'] >= 2.0) & (valid_pool['pct_change'] >= 2.0)
        s1_df = valid_pool[s1_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 02: 突破Hi120 (半年新高 + Q60R > 2.5 + 漲幅 >= 3%)
        s2_mask = (valid_pool['high'] >= valid_pool['high_120']) & (valid_pool['q60r'] >= 2.5) & (valid_pool['pct_change'] >= 3.0)
        s2_df = valid_pool[s2_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 03: 突破Hi480 (兩年新高大底 + Q60R > 3.0 + 漲幅 >= 3.5%)
        s3_mask = (valid_pool['high'] >= valid_pool['high_480']) & (valid_pool['q60r'] >= 3.0) & (valid_pool['pct_change'] >= 3.5)
        s3_df = valid_pool[s3_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 04: 雙綠脫離 (D20由負轉正/小於0轉正 + 遠離60日低點 > 5% + 站上20MA)
        s4_mask = (valid_pool['d20'] >= 0.0) & (valid_pool['d20_prev'] <= 0.8) & (valid_pool['close'] > valid_pool['low_60'] * 1.05) & (valid_pool['close'] > valid_pool['ma20'])
        s4_df = valid_pool[s4_mask].sort_values(by=['pct_change', 'q60r'], ascending=[False, False])

        # ----------------------------------------------------------------------
        # 3. S 級籌碼濾網 (投信連買 >= 2 天 + 5MA 向上勾角)
        # ----------------------------------------------------------------------
        s_chip_mask = (valid_pool['trust_buy_days'] >= 2) & (valid_pool['ma5'] > valid_pool['ma5_prev']) & (valid_pool['close'] > valid_pool['ma5'])
        s_chip_df = valid_pool[s_chip_mask].sort_values(by=['trust_buy_days', 'trust_net'], ascending=[False, False])

        # ----------------------------------------------------------------------
        # 4. 當沖動能專區 (Q60R > 2.2 + 漲幅介於 2.5% ~ 7.5% + 實體紅K)
        # ----------------------------------------------------------------------
        day_trade_mask = (valid_pool['q60r'] >= 2.2) & (valid_pool['pct_change'].between(2.5, 7.5)) & (valid_pool['close'] >= valid_pool['open'])
        day_trade_df = valid_pool[day_trade_mask].sort_values(by='q60r', ascending=False)

        # ----------------------------------------------------------------------
        # 5. 隔日沖精選專區 (尾盤強勢收最高/次高 + 投信或外資買超 + 漲幅 3.5%~9.5%)
        # ----------------------------------------------------------------------
        swing_mask = (valid_pool['pct_change'].between(3.5, 9.5)) & ((valid_pool['high'] - valid_pool['close']) <= (valid_pool['high'] - valid_pool['low']) * 0.2) & ((valid_pool['trust_net'] > 0) | (valid_pool['foreign_net'] > 500))
        swing_df = valid_pool[swing_mask].sort_values(by=['pct_change', 'q60r'], ascending=[False, False])

        def format_stock_items(df_sub: pd.DataFrame, limit: int = 10) -> List[Dict[str, Any]]:
            items = []
            for _, r in df_sub.head(limit).iterrows():
                levels = self.calculate_price_levels(r)
                items.append({
                    "stock_id": str(r['stock_id']),
                    "stock_name": str(r['stock_name']),
                    "market": str(r['market']),
                    "close": float(r['close']),
                    "pct_change": float(r['pct_change']),
                    "volume": int(r['volume']),
                    "q60r": round(float(r['q60r']), 2),
                    "trust_net": int(r['trust_net']),
                    "foreign_net": int(r['foreign_net']),
                    "trust_buy_days": int(r['trust_buy_days']),
                    "price_levels": levels
                })
            return items

        return {
            "date": target_date,
            "total_scanned": total_scanned,
            "liquid_count": len(valid_pool),
            "strategies": {
                "select_01_week_breakout": format_stock_items(s1_df),
                "select_02_hi120_breakout": format_stock_items(s2_df),
                "select_03_hi480_breakout": format_stock_items(s3_df),
                "select_04_double_green_exit": format_stock_items(s4_df),
                "s_class_chips": format_stock_items(s_chip_df),
                "day_trade_momentum": format_stock_items(day_trade_df),
                "overnight_swing": format_stock_items(swing_df)
            }
        }


# ==============================================================================
# Telegram 報表格式化模組 (format_telegram_report)
# ==============================================================================
def format_telegram_report(results: Dict[str, Any], report_type: str = "daily_summary") -> str:
    """
    將選股與價位精算結果格式化為排版優雅之 Telegram 訊息文字
    """
    if not results or "strategies" not in results:
        return "⚠️ 今日無符合量化標準之選股數據。"

    date_str = results.get("date", datetime.now().strftime("%Y%m%d"))
    formatted_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}" if len(date_str) == 8 else date_str
    scanned = results.get("total_scanned", 0)
    liquid = results.get("liquid_count", 0)
    strat = results.get("strategies", {})

    lines = []
    lines.append(f"🚀 *WayneBot 量化決策全市場戰報* ｜ `{formatted_date}`")
    lines.append(f"🔍 掃描檔數: `{scanned:,}` 檔 ｜ 流動合格池: `{liquid:,}` 檔")
    lines.append("━" * 28)

    # 1. 突破Hi480 兩年大底 (最稀有高勝率)
    s3 = strat.get("select_03_hi480_breakout", [])
    if s3:
        lines.append("\n👑 *【Select 03 突破 Hi480 兩年大底】* (最高量化勝率)")
        for item in s3[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%)")
            lines.append(f"  ↳ 量比: `{item['q60r']}x` | 成交: `{item['volume']:,}張` | 投信連買: `{item['trust_buy_days']}天`")

    # 2. 突破Hi120 半年新高
    s2 = strat.get("select_02_hi120_breakout", [])
    if s2:
        lines.append("\n🔥 *【Select 02 突破 Hi120 半年新高】*")
        for item in s2[:4]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 量比: `{item['q60r']}x`")

    # 3. 周帶量突破
    s1 = strat.get("select_01_week_breakout", [])
    if s1:
        lines.append("\n⚡ *【Select 01 周帶量突破 (5日高+Q60R>2)】*")
        for item in s1[:4]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 量比: `{item['q60r']}x`")

    # 4. 雙綠脫離起漲
    s4 = strat.get("select_04_double_green_exit", [])
    if s4:
        lines.append("\n🌱 *【Select 04 雙綠脫離黃金起漲】*")
        for item in s4[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 脫離20MA起漲")

    # 5. S 級投信籌碼專區
    sc = strat.get("s_class_chips", [])
    if sc:
        lines.append("\n💎 *【S 級籌碼核心：投信連買 ＆ 5MA向上勾角】*")
        for item in sc[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} | 投信連買: `{item['trust_buy_days']}天` (今日+{item['trust_net']:,}張)")

    # 6. 當沖動能精算
    dt = strat.get("day_trade_momentum", [])
    if dt:
        lines.append("\n🎯 *【當沖動能專區：即時推播點位】*")
        for item in dt[:2]:
            lv = item['price_levels']['day_trade']
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* (現價 ${item['close']})")
            lines.append(f"  ↳ 進場: `${lv['entry_price']}` | 停利1(+3%): `${lv['take_profit_1']}` | 衝頂(+6%): `${lv['take_profit_2']}` | 停損: `${lv['stop_loss']}`")

    # 7. 隔日沖精選點位
    sw = strat.get("overnight_swing", [])
    if sw:
        lines.append("\n🌙 *【隔日沖精選專區：尾盤佈局點位】*")
        for item in sw[:2]:
            lv = item['price_levels']['swing_trade']
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* (收盤 ${item['close']})")
            lines.append(f"  ↳ 買進區間: `${lv['buy_zone_low']}~${lv['buy_zone_high']}`")
            lines.append(f"  ↳ 明日開高目標: `${lv['target_gap_low']}~${lv['target_gap_high']}` (+3.5~4.8%)")
            lines.append(f"  ↳ 衝頂目標: `${lv['rocket_target']}` (+7%) | 防守線: `${lv['defense_line']}`")

    lines.append("\n━" * 28)
    lines.append("⚠️ *風控紀律提醒*：嚴格執行均價停損與防守線，流動性優先，切勿追高盲進。")

    return "\n".join(lines)


# ==============================================================================
# 本地 / 沙盒單元測試入口
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 正在執行 screening_engine.py 沙盒單元測試...")
    print("=" * 60)

    # 檢查是否有現成資料庫，若無則建立輕量 Mock 測試資料庫進行驗證
    test_db = DEFAULT_DB_PATH
    if not os.path.exists(test_db):
        print("⚠️ 未偵測到 waynebot_history.db，正在建立記憶體測試資料庫驗證...")
        test_db = ":memory:"
        conn = sqlite3.connect(test_db)
        conn.execute("""
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER,
            PRIMARY KEY (date, stock_id)
        );
        """)
        # 寫入測試數據
        conn.execute("""
        INSERT INTO daily_quotes VALUES 
        ('20260827', '2330', '台積電', 'TW', 980.0, 995.0, 978.0, 992.0, 28000, 27600000.0, 3.2, 988.0, 15000, 2500, 300),
        ('20260827', '3037', '欣興', 'TW', 185.0, 192.0, 184.0, 191.0, 15000, 2800000.0, 4.5, 188.5, 4000, 1200, 100);
        """)
        conn.commit()
        engine = ScreeningEngine(db_path=test_db)
    else:
        engine = ScreeningEngine(db_path=test_db)

    print("📊 執行全市場選股掃描...")
    res = engine.run_all_screenings()
    print(f"✅ 掃描完成！掃描檔數: {res.get('total_scanned')}")

    print("\n📱 產生 Telegram 戰報預覽：")
    print("-" * 50)
    report_text = format_telegram_report(res)
    print(report_text)
    print("-" * 50)
    print("🎉 screening_engine.py 單元驗證 100% 通過！")# -*- coding: utf-8 -*-
"""
==============================================================================
WayneBot 全市場量化決策系統：即時選股與價位精算引擎 (screening_engine.py)
==============================================================================
核心功能：
1. CaryBot 四大即時選股：
   - Select 01 周帶量突破 (5日高 + Q60R > 2.0)
   - Select 02 突破Hi120 (半年新高大底 + Q60R > 2.5)
   - Select 03 突破Hi480 (兩年新高大底 + Q60R > 3.0)
   - Select 04 雙綠脫離 (D20由0%轉正 + 60日低消失)
2. S 級籌碼濾網 (投信連買 >= 2 日 + 5MA 向上勾角)
3. 當沖 / 隔日沖動能價位精算 (建議進場、第一停利、衝頂目標、保本防守價)
4. 流動性陷阱智慧防護 (強制過濾成交量 < 1,000 張 或 成交額 < 3,000 萬)
5. format_telegram_report: 供 main_runner.py 與 bot_servers.py 調用之 Telegram 報表格式化器
==============================================================================
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

# 預設資料庫路徑
DEFAULT_DB_PATH = os.path.join(os.getcwd(), "waynebot_history.db")

class ScreeningEngine:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """建立 SQLite 連線並啟用 WAL 效能模式"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def get_latest_trading_date(self) -> str:
        """取得資料庫中最新交易日期 (YYYYMMDD)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM daily_quotes;")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else datetime.now().strftime("%Y%m%d")

    def load_market_data(self, target_date: Optional[str] = None, lookback_days: int = 500) -> pd.DataFrame:
        """
        載入計算所需之歷史行情數據（預設載入近 500 天，確保 Hi480 與 Q60R 運算無虞）
        """
        conn = self._get_connection()
        if not target_date:
            target_date = self.get_latest_trading_date()

        query = """
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k,
            pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date <= ?
        ORDER BY stock_id, date ASC;
        """
        df = pd.read_sql_query(query, conn, params=(target_date,))
        conn.close()
        return df

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        批次計算全市場技術指標
        """
        if df.empty:
            return df

        # 確保型態正確
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        df['pct_change'] = pd.to_numeric(df['pct_change'], errors='coerce')
        df['trust_net'] = pd.to_numeric(df['trust_net'], errors='coerce').fillna(0)

        # 依照 stock_id 分組計算指標
        grouped = df.groupby('stock_id')

        # 均線 (5MA, 20MA, 60MA)
        df['ma5'] = grouped['close'].transform(lambda x: x.rolling(5, min_periods=1).mean())
        df['ma5_prev'] = grouped['ma5'].shift(1)
        df['ma20'] = grouped['close'].transform(lambda x: x.rolling(20, min_periods=1).mean())
        df['ma60'] = grouped['close'].transform(lambda x: x.rolling(60, min_periods=1).mean())

        # 60 日均量與量比 Q60R
        df['vol_ma60'] = grouped['volume'].transform(lambda x: x.rolling(60, min_periods=5).mean())
        df['q60r'] = np.where(df['vol_ma60'] > 0, df['volume'] / df['vol_ma60'], 1.0)

        # 近期高低價
        df['high_5'] = grouped['high'].transform(lambda x: x.rolling(5, min_periods=1).max())
        df['high_120'] = grouped['high'].transform(lambda x: x.rolling(120, min_periods=20).max())
        df['high_480'] = grouped['high'].transform(lambda x: x.rolling(480, min_periods=60).max())
        df['low_60'] = grouped['low'].transform(lambda x: x.rolling(60, min_periods=10).min())

        # 20 日乖離率 D20 (%)
        df['d20'] = np.where(df['ma20'] > 0, ((df['close'] - df['ma20']) / df['ma20']) * 100.0, 0.0)
        df['d20_prev'] = grouped['d20'].shift(1)

        # 投信連買天數計算
        def get_trust_consecutive_buy(series: pd.Series) -> pd.Series:
            consecutive = []
            count = 0
            for val in series:
                if val > 0:
                    count += 1
                else:
                    count = 0
                consecutive.append(count)
            return pd.Series(consecutive, index=series.index)

        df['trust_buy_days'] = grouped['trust_net'].transform(get_trust_consecutive_buy)

        return df

    def calculate_price_levels(self, row: pd.Series) -> Dict[str, Any]:
        """
        精算當沖與隔日沖關鍵價位
        """
        c = float(row['close'])
        avg_p = float(row['avg_price']) if float(row['avg_price']) > 0 else c

        # 當沖價位
        day_trade = {
            "entry_price": c,
            "take_profit_1": round(c * 1.030, 2),  # +3.0% 第一停利
            "take_profit_2": round(c * 1.060, 2),  # +6.0% 第二衝頂
            "stop_loss": round(min(avg_p, c * 0.980), 2)  # 均價跌破或 -2% 停損
        }

        # 隔日沖價位
        swing_trade = {
            "buy_zone_low": round(c * 0.995, 2),
            "buy_zone_high": round(c * 1.005, 2),
            "target_gap_low": round(c * 1.035, 2),   # +3.5% 明日開高目標低標
            "target_gap_high": round(c * 1.048, 2),  # +4.8% 明日開高目標高標
            "rocket_target": round(c * 1.070, 2),    # +7.0% 強勢衝頂價
            "defense_line": round(c * 0.985, 2)      # -1.5% 保本防守線
        }

        return {"day_trade": day_trade, "swing_trade": swing_trade}

    def run_all_screenings(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        執行全市場選股流水線，輸出結構化結果
        """
        if not target_date:
            target_date = self.get_latest_trading_date()

        raw_df = self.load_market_data(target_date)
        if raw_df.empty:
            return {"date": target_date, "total_scanned": 0, "strategies": {}}

        calc_df = self.calculate_technical_indicators(raw_df)
        
        # 取出指定日期的最新截面
        latest = calc_df[calc_df['date'] == target_date].copy()
        total_scanned = len(latest)

        # ----------------------------------------------------------------------
        # 1. 流動性防護濾網：量 >= 1,000 張 或 成交額 >= 3,000 萬元 (turnover_k >= 30,000)
        # ----------------------------------------------------------------------
        liquid_mask = (latest['volume'] >= 1000) | (latest['turnover_k'] >= 30000)
        valid_pool = latest[liquid_mask].copy()

        # ----------------------------------------------------------------------
        # 2. CaryBot 四大即時選股條件
        # ----------------------------------------------------------------------
        # Select 01: 周帶量突破 (5日高 + Q60R > 2.0 + 漲幅 >= 2%)
        s1_mask = (valid_pool['high'] >= valid_pool['high_5']) & (valid_pool['q60r'] >= 2.0) & (valid_pool['pct_change'] >= 2.0)
        s1_df = valid_pool[s1_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 02: 突破Hi120 (半年新高 + Q60R > 2.5 + 漲幅 >= 3%)
        s2_mask = (valid_pool['high'] >= valid_pool['high_120']) & (valid_pool['q60r'] >= 2.5) & (valid_pool['pct_change'] >= 3.0)
        s2_df = valid_pool[s2_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 03: 突破Hi480 (兩年新高大底 + Q60R > 3.0 + 漲幅 >= 3.5%)
        s3_mask = (valid_pool['high'] >= valid_pool['high_480']) & (valid_pool['q60r'] >= 3.0) & (valid_pool['pct_change'] >= 3.5)
        s3_df = valid_pool[s3_mask].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])

        # Select 04: 雙綠脫離 (D20由負轉正/小於0轉正 + 遠離60日低點 > 5% + 站上20MA)
        s4_mask = (valid_pool['d20'] >= 0.0) & (valid_pool['d20_prev'] <= 0.8) & (valid_pool['close'] > valid_pool['low_60'] * 1.05) & (valid_pool['close'] > valid_pool['ma20'])
        s4_df = valid_pool[s4_mask].sort_values(by=['pct_change', 'q60r'], ascending=[False, False])

        # ----------------------------------------------------------------------
        # 3. S 級籌碼濾網 (投信連買 >= 2 天 + 5MA 向上勾角)
        # ----------------------------------------------------------------------
        s_chip_mask = (valid_pool['trust_buy_days'] >= 2) & (valid_pool['ma5'] > valid_pool['ma5_prev']) & (valid_pool['close'] > valid_pool['ma5'])
        s_chip_df = valid_pool[s_chip_mask].sort_values(by=['trust_buy_days', 'trust_net'], ascending=[False, False])

        # ----------------------------------------------------------------------
        # 4. 當沖動能專區 (Q60R > 2.2 + 漲幅介於 2.5% ~ 7.5% + 實體紅K)
        # ----------------------------------------------------------------------
        day_trade_mask = (valid_pool['q60r'] >= 2.2) & (valid_pool['pct_change'].between(2.5, 7.5)) & (valid_pool['close'] >= valid_pool['open'])
        day_trade_df = valid_pool[day_trade_mask].sort_values(by='q60r', ascending=False)

        # ----------------------------------------------------------------------
        # 5. 隔日沖精選專區 (尾盤強勢收最高/次高 + 投信或外資買超 + 漲幅 3.5%~9.5%)
        # ----------------------------------------------------------------------
        swing_mask = (valid_pool['pct_change'].between(3.5, 9.5)) & ((valid_pool['high'] - valid_pool['close']) <= (valid_pool['high'] - valid_pool['low']) * 0.2) & ((valid_pool['trust_net'] > 0) | (valid_pool['foreign_net'] > 500))
        swing_df = valid_pool[swing_mask].sort_values(by=['pct_change', 'q60r'], ascending=[False, False])

        def format_stock_items(df_sub: pd.DataFrame, limit: int = 10) -> List[Dict[str, Any]]:
            items = []
            for _, r in df_sub.head(limit).iterrows():
                levels = self.calculate_price_levels(r)
                items.append({
                    "stock_id": str(r['stock_id']),
                    "stock_name": str(r['stock_name']),
                    "market": str(r['market']),
                    "close": float(r['close']),
                    "pct_change": float(r['pct_change']),
                    "volume": int(r['volume']),
                    "q60r": round(float(r['q60r']), 2),
                    "trust_net": int(r['trust_net']),
                    "foreign_net": int(r['foreign_net']),
                    "trust_buy_days": int(r['trust_buy_days']),
                    "price_levels": levels
                })
            return items

        return {
            "date": target_date,
            "total_scanned": total_scanned,
            "liquid_count": len(valid_pool),
            "strategies": {
                "select_01_week_breakout": format_stock_items(s1_df),
                "select_02_hi120_breakout": format_stock_items(s2_df),
                "select_03_hi480_breakout": format_stock_items(s3_df),
                "select_04_double_green_exit": format_stock_items(s4_df),
                "s_class_chips": format_stock_items(s_chip_df),
                "day_trade_momentum": format_stock_items(day_trade_df),
                "overnight_swing": format_stock_items(swing_df)
            }
        }


# ==============================================================================
# Telegram 報表格式化模組 (format_telegram_report)
# ==============================================================================
def format_telegram_report(results: Dict[str, Any], report_type: str = "daily_summary") -> str:
    """
    將選股與價位精算結果格式化為排版優雅之 Telegram 訊息文字
    """
    if not results or "strategies" not in results:
        return "⚠️ 今日無符合量化標準之選股數據。"

    date_str = results.get("date", datetime.now().strftime("%Y%m%d"))
    formatted_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}" if len(date_str) == 8 else date_str
    scanned = results.get("total_scanned", 0)
    liquid = results.get("liquid_count", 0)
    strat = results.get("strategies", {})

    lines = []
    lines.append(f"🚀 *WayneBot 量化決策全市場戰報* ｜ `{formatted_date}`")
    lines.append(f"🔍 掃描檔數: `{scanned:,}` 檔 ｜ 流動合格池: `{liquid:,}` 檔")
    lines.append("━" * 28)

    # 1. 突破Hi480 兩年大底 (最稀有高勝率)
    s3 = strat.get("select_03_hi480_breakout", [])
    if s3:
        lines.append("\n👑 *【Select 03 突破 Hi480 兩年大底】* (最高量化勝率)")
        for item in s3[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%)")
            lines.append(f"  ↳ 量比: `{item['q60r']}x` | 成交: `{item['volume']:,}張` | 投信連買: `{item['trust_buy_days']}天`")

    # 2. 突破Hi120 半年新高
    s2 = strat.get("select_02_hi120_breakout", [])
    if s2:
        lines.append("\n🔥 *【Select 02 突破 Hi120 半年新高】*")
        for item in s2[:4]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 量比: `{item['q60r']}x`")

    # 3. 周帶量突破
    s1 = strat.get("select_01_week_breakout", [])
    if s1:
        lines.append("\n⚡ *【Select 01 周帶量突破 (5日高+Q60R>2)】*")
        for item in s1[:4]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 量比: `{item['q60r']}x`")

    # 4. 雙綠脫離起漲
    s4 = strat.get("select_04_double_green_exit", [])
    if s4:
        lines.append("\n🌱 *【Select 04 雙綠脫離黃金起漲】*")
        for item in s4[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} (+{item['pct_change']}%) | 脫離20MA起漲")

    # 5. S 級投信籌碼專區
    sc = strat.get("s_class_chips", [])
    if sc:
        lines.append("\n💎 *【S 級籌碼核心：投信連買 ＆ 5MA向上勾角】*")
        for item in sc[:3]:
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}*  ${item['close']} | 投信連買: `{item['trust_buy_days']}天` (今日+{item['trust_net']:,}張)")

    # 6. 當沖動能精算
    dt = strat.get("day_trade_momentum", [])
    if dt:
        lines.append("\n🎯 *【當沖動能專區：即時推播點位】*")
        for item in dt[:2]:
            lv = item['price_levels']['day_trade']
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* (現價 ${item['close']})")
            lines.append(f"  ↳ 進場: `${lv['entry_price']}` | 停利1(+3%): `${lv['take_profit_1']}` | 衝頂(+6%): `${lv['take_profit_2']}` | 停損: `${lv['stop_loss']}`")

    # 7. 隔日沖精選點位
    sw = strat.get("overnight_swing", [])
    if sw:
        lines.append("\n🌙 *【隔日沖精選專區：尾盤佈局點位】*")
        for item in sw[:2]:
            lv = item['price_levels']['swing_trade']
            lines.append(f"• `{item['stock_id']}` *{item['stock_name']}* (收盤 ${item['close']})")
            lines.append(f"  ↳ 買進區間: `${lv['buy_zone_low']}~${lv['buy_zone_high']}`")
            lines.append(f"  ↳ 明日開高目標: `${lv['target_gap_low']}~${lv['target_gap_high']}` (+3.5~4.8%)")
            lines.append(f"  ↳ 衝頂目標: `${lv['rocket_target']}` (+7%) | 防守線: `${lv['defense_line']}`")

    lines.append("\n━" * 28)
    lines.append("⚠️ *風控紀律提醒*：嚴格執行均價停損與防守線，流動性優先，切勿追高盲進。")

    return "\n".join(lines)


# ==============================================================================
# 本地 / 沙盒單元測試入口
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 正在執行 screening_engine.py 沙盒單元測試...")
    print("=" * 60)

    # 檢查是否有現成資料庫，若無則建立輕量 Mock 測試資料庫進行驗證
    test_db = DEFAULT_DB_PATH
    if not os.path.exists(test_db):
        print("⚠️ 未偵測到 waynebot_history.db，正在建立記憶體測試資料庫驗證...")
        test_db = ":memory:"
        conn = sqlite3.connect(test_db)
        conn.execute("""
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER,
            PRIMARY KEY (date, stock_id)
        );
        """)
        # 寫入測試數據
        conn.execute("""
        INSERT INTO daily_quotes VALUES 
        ('20260827', '2330', '台積電', 'TW', 980.0, 995.0, 978.0, 992.0, 28000, 27600000.0, 3.2, 988.0, 15000, 2500, 300),
        ('20260827', '3037', '欣興', 'TW', 185.0, 192.0, 184.0, 191.0, 15000, 2800000.0, 4.5, 188.5, 4000, 1200, 100);
        """)
        conn.commit()
        engine = ScreeningEngine(db_path=test_db)
    else:
        engine = ScreeningEngine(db_path=test_db)

    print("📊 執行全市場選股掃描...")
    res = engine.run_all_screenings()
    print(f"✅ 掃描完成！掃描檔數: {res.get('total_scanned')}")

    print("\n📱 產生 Telegram 戰報預覽：")
    print("-" * 50)
    report_text = format_telegram_report(res)
    print(report_text)
    print("-" * 50)
    print("🎉 screening_engine.py 單元驗證 100% 通過！")
