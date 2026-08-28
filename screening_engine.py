# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組二 - 即時選股與價位精算引擎
# 檔案名稱：screening_engine.py
# 核心功能：CaryBot四大策略、當沖/隔日沖價位精算、S級籌碼濾網、Telegram報表產生
# ==============================================================================

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd


class ScreeningEngine:
    """
    WayneBot 量化選股與價位精算核心引擎
    """
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"❌ 找不到資料庫檔案：{self.db_path}，請先確認資料庫已建立。")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def load_market_data(self, lookback_days: int = 500) -> pd.DataFrame:
        """
        載入全市場歷史日K線與籌碼數據
        """
        conn = self._get_connection()
        query = f"""
        SELECT 
            date, stock_id, stock_name, market,
            open, high, low, close, volume, turnover_k,
            pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date >= (
            SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT {lookback_days}
        )
        ORDER BY stock_id, date ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

    def compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算均線、量比 Q60R、高低點突破與投信籌碼指標
        """
        df = df.copy()
        
        # 依個股分組計算
        grouped = df.groupby('stock_id')

        # 均線計算
        df['ma5'] = grouped['close'].transform(lambda x: x.rolling(5, min_periods=1).mean())
        df['ma20'] = grouped['close'].transform(lambda x: x.rolling(20, min_periods=1).mean())
        df['ma60'] = grouped['close'].transform(lambda x: x.rolling(60, min_periods=1).mean())
        df['ma120'] = grouped['close'].transform(lambda x: x.rolling(120, min_periods=1).mean())
        df['ma480'] = grouped['close'].transform(lambda x: x.rolling(480, min_periods=1).mean())

        # 均量與量比 Q60R (當日量 / 60日均量)
        df['vol_ma5'] = grouped['volume'].transform(lambda x: x.rolling(5, min_periods=1).mean())
        df['vol_ma60'] = grouped['volume'].transform(lambda x: x.rolling(60, min_periods=1).mean())
        df['q60r'] = np.where(df['vol_ma60'] > 0, df['volume'] / df['vol_ma60'], 1.0)

        # 5MA 向上勾角判定 (今日 5MA > 昨日 5MA)
        df['ma5_prev'] = grouped['ma5'].shift(1)
        df['ma5_slope_up'] = df['ma5'] > df['ma5_prev']

        # 歷史新高與新低（滾動極值）
        df['hi5_prev'] = grouped['high'].transform(lambda x: x.shift(1).rolling(5, min_periods=1).max())
        df['hi120_prev'] = grouped['high'].transform(lambda x: x.shift(1).rolling(120, min_periods=1).max())
        df['hi480_prev'] = grouped['high'].transform(lambda x: x.shift(1).rolling(480, min_periods=1).max())
        
        df['low20_prev'] = grouped['low'].transform(lambda x: x.shift(1).rolling(20, min_periods=1).min())
        df['low60_prev'] = grouped['low'].transform(lambda x: x.shift(1).rolling(60, min_periods=1).min())

        # D20 乖離率與偏離度 (與 20 日低點距離)
        df['d20'] = np.where(
            df['low20_prev'] > 0, 
            ((df['close'] - df['low20_prev']) / df['low20_prev']) * 100.0, 
            0.0
        )
        df['d20_prev'] = grouped['d20'].shift(1)

        # 投信連買天數
        def calc_trust_streak(series):
            streak = []
            cur = 0
            for val in series:
                if val > 0:
                    cur += 1
                else:
                    cur = 0
                streak.append(cur)
            return pd.Series(streak, index=series.index)

        df['trust_streak'] = grouped['trust_net'].transform(calc_trust_streak)

        return df

    def filter_liquidity(self, df_latest: pd.DataFrame) -> pd.DataFrame:
        """
        流動性防護網：強制過濾日成交量 < 1,000 張 且 日成交額 < 3,000 萬元的冷門股
        """
        # 成交量 >= 1000 張 或 成交額 >= 30,000 千元 (3000萬)
        cond_liq = (df_latest['volume'] >= 1000) | (df_latest['turnover_k'] >= 30000)
        return df_latest[cond_liq].copy()

    def run_all_screens(self) -> Dict[str, Any]:
        """
        執行全市場四大策略、當沖、隔日沖與 S 級標的篩選
        """
        raw_df = self.load_market_data(lookback_days=500)
        if raw_df.empty:
            return {"date": datetime.now().strftime("%Y%m%d"), "strategies": {}}

        df_calc = self.compute_technical_indicators(raw_df)
        
        # 取得最新交易日資料
        latest_date = df_calc['date'].max()
        df_today = df_calc[df_calc['date'] == latest_date].copy()
        
        # 實施流動性過濾
        df_pool = self.filter_liquidity(df_today)

        results = {
            "date": latest_date,
            "total_scanned": len(df_today),
            "liquid_pool": len(df_pool),
            "strategies": {}
        }

        # ----------------------------------------------------------------------
        # Strategy 01: 周帶量突破 (5日高 + Q60R > 2.0)
        # ----------------------------------------------------------------------
        c1 = (df_pool['close'] > df_pool['hi5_prev']) & (df_pool['q60r'] >= 2.0) & (df_pool['pct_change'] > 0)
        s1_df = df_pool[c1].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])
        results["strategies"]["select_01"] = self._format_items(s1_df, "Select 01 周帶量突破")

        # ----------------------------------------------------------------------
        # Strategy 02: 突破Hi120 半年新高 (半年新高 + Q60R > 2.5)
        # ----------------------------------------------------------------------
        c2 = (df_pool['close'] >= df_pool['hi120_prev']) & (df_pool['q60r'] >= 2.5) & (df_pool['pct_change'] > 1.5)
        s2_df = df_pool[c2].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])
        results["strategies"]["select_02"] = self._format_items(s2_df, "Select 02 突破Hi120 (半年新高)")

        # ----------------------------------------------------------------------
        # Strategy 03: 突破Hi480 兩年新高大底 (兩年新高 + Q60R > 3.0)
        # ----------------------------------------------------------------------
        c3 = (df_pool['close'] >= df_pool['hi480_prev']) & (df_pool['q60r'] >= 3.0) & (df_pool['pct_change'] > 2.0)
        s3_df = df_pool[c3].sort_values(by=['q60r', 'pct_change'], ascending=[False, False])
        results["strategies"]["select_03"] = self._format_items(s3_df, "Select 03 突破Hi480 (兩年新高大底)")

        # ----------------------------------------------------------------------
        # Strategy 04: 雙綠脫離 (D20由0%轉正 + 遠離60日低點)
        # ----------------------------------------------------------------------
        c4 = (df_pool['d20'] > 0) & (df_pool['d20_prev'] <= 0.5) & (df_pool['close'] > df_pool['low60_prev'] * 1.05) & (df_pool['ma5_slope_up'])
        s4_df = df_pool[c4].sort_values(by=['pct_change', 'volume'], ascending=[False, False])
        results["strategies"]["select_04"] = self._format_items(s4_df, "Select 04 雙綠脫離結構")

        # ----------------------------------------------------------------------
        # 專區一：當沖動能專區 (Q60R > 2.2, 漲幅 3.5%~8.5%, 具備拉抬空間)
        # ----------------------------------------------------------------------
        c_dt = (df_pool['q60r'] >= 2.2) & (df_pool['pct_change'].between(3.5, 8.5)) & (df_pool['ma5_slope_up'])
        dt_df = df_pool[c_dt].sort_values(by=['q60r'], ascending=False).head(5)
        results["strategies"]["day_trade"] = self._format_price_calc(dt_df, mode="day_trade")

        # ----------------------------------------------------------------------
        # 專區二：隔日沖精選專區 (投信連買/強勢收高, 漲幅 4.0%~9.8%)
        # ----------------------------------------------------------------------
        c_on = (df_pool['pct_change'].between(4.0, 9.9)) & (df_pool['q60r'] >= 1.8) & (df_pool['close'] >= df_pool['high'] * 0.985)
        on_df = df_pool[c_on].sort_values(by=['trust_streak', 'turnover_k'], ascending=[False, False]).head(5)
        results["strategies"]["overnight"] = self._format_price_calc(on_df, mode="overnight")

        return results

    def _format_items(self, df_sub: pd.DataFrame, strategy_name: str) -> List[Dict[str, Any]]:
        items = []
        for _, row in df_sub.head(10).iterrows():
            # S 級標籤判斷：投信連買 >= 2 天 且 5MA 向上
            is_s_tier = bool(row['trust_streak'] >= 2 and row['ma5_slope_up'])
            items.append({
                "stock_id": str(row['stock_id']),
                "stock_name": str(row['stock_name']),
                "close": float(row['close']),
                "pct_change": float(row['pct_change']),
                "volume": int(row['volume']),
                "q60r": round(float(row['q60r']), 2),
                "trust_streak": int(row['trust_streak']),
                "is_s_tier": is_s_tier
            })
        return items

    def _format_price_calc(self, df_sub: pd.DataFrame, mode: str) -> List[Dict[str, Any]]:
        items = []
        for _, row in df_sub.iterrows():
            c = float(row['close'])
            avg_p = float(row['avg_price']) if row['avg_price'] > 0 else c
            is_s_tier = bool(row['trust_streak'] >= 2 and row['ma5_slope_up'])

            if mode == "day_trade":
                # 當沖精算：進場價、第一停利(+3%)、第二衝頂(+6%)、均價停損價
                items.append({
                    "stock_id": str(row['stock_id']),
                    "stock_name": str(row['stock_name']),
                    "close": c,
                    "pct_change": float(row['pct_change']),
                    "q60r": round(float(row['q60r']), 2),
                    "entry_price": round(c, 2),
                    "tp1_price": round(c * 1.03, 2),
                    "tp2_price": round(c * 1.06, 2),
                    "sl_price": round(min(avg_p, c * 0.98), 2),
                    "is_s_tier": is_s_tier
                })
            elif mode == "overnight":
                # 隔日沖精算：買進區間、明日開高目標(+3.5~4.8%)、強勢衝頂(+8%)、保本防守價(-1.8%)
                buy_low = round(c * 0.99, 2)
                buy_high = round(c, 2)
                items.append({
                    "stock_id": str(row['stock_id']),
                    "stock_name": str(row['stock_name']),
                    "close": c,
                    "pct_change": float(row['pct_change']),
                    "buy_range": f"{buy_low} ~ {buy_high}",
                    "target_open": f"{round(c * 1.035, 2)} ~ {round(c * 1.048, 2)}",
                    "surge_target": round(c * 1.08, 2),
                    "defense_price": round(c * 0.982, 2),
                    "trust_streak": int(row['trust_streak']),
                    "is_s_tier": is_s_tier
                })
        return items


def format_telegram_report(results: Dict[str, Any]) -> str:
    """
    將量化選股與價位精算結果格式化為 Telegram 專用 Markdown 報表
    """
    date_str = results.get("date", datetime.now().strftime("%Y%m%d"))
    total_scanned = results.get("total_scanned", 0)
    liquid_pool = results.get("liquid_pool", 0)
    strategies = results.get("strategies", {})

    lines = []
    lines.append(f"⚡ *【WayneBot 全市場量化決策日報】*")
    lines.append(f"📅 交易日期：`{date_str}` | 掃描：`{total_scanned}` 檔 | 高流動池：`{liquid_pool}` 檔\n")

    # 1. CaryBot 四大策略
    strat_map = [
        ("select_01", "🚀 Select 01 周帶量突破 (5日高+Q60R>2.0)"),
        ("select_02", "🔥 Select 02 突破Hi120 (半年新高)"),
        ("select_03", "👑 Select 03 突破Hi480 (兩年大底)"),
        ("select_04", "🌱 Select 04 雙綠脫離結構")
    ]

    for key, title in strat_map:
        items = strategies.get(key, [])
        lines.append(f"*{title}* `({len(items)} 檔)`")
        if not items:
            lines.append("  _無符合條件標的_")
        else:
            for it in items:
                s_tag = " ⭐[S級]" if it.get("is_s_tier") else ""
                t_streak = f" 投信連{it['trust_streak']}買" if it.get("trust_streak", 0) > 0 else ""
                lines.append(
                    f"• `{it['stock_id']}` *{it['stock_name']}*{s_tag} "
                    f"收 `{it['close']}` ({it['pct_change']:+.2f}%) | "
                    f"量比 `{it['q60r']}x` | 量 `{it['volume']}張`{t_streak}"
                )
        lines.append("")

    # 2. 當沖動能精算
    dt_items = strategies.get("day_trade", [])
    lines.append(f"🎯 *【當沖動能價位精算專區】* `({len(dt_items)} 檔)`")
    if not dt_items:
        lines.append("  _今日無高度建議之當沖動能標的_")
    else:
        for it in dt_items:
            s_tag = " ⭐[S級]" if it.get("is_s_tier") else ""
            lines.append(f"• `{it['stock_id']}` *{it['stock_name']}*{s_tag} (現價 `{it['close']}`)")
            lines.append(f"  └ 建議進場: `{it['entry_price']}` | 停利①(+3%): `{it['tp1_price']}` | 衝頂②(+6%): `{it['tp2_price']}` | 停損: `{it['sl_price']}`")
    lines.append("")

    # 3. 隔日沖精選專區
    on_items = strategies.get("overnight", [])
    lines.append(f"🌙 *【尾盤隔日沖精選專區】* `({len(on_items)} 檔)`")
    if not on_items:
        lines.append("  _今日無符合標準之隔日沖標的_")
    else:
        for it in on_items:
            s_tag = " ⭐[S級]" if it.get("is_s_tier") else ""
            t_streak = f" (投信連{it['trust_streak']}買)" if it.get("trust_streak", 0) > 0 else ""
            lines.append(f"• `{it['stock_id']}` *{it['stock_name']}*{s_tag}{t_streak}")
            lines.append(f"  └ 買進區間: `{it['buy_range']}` | 明日開高目標: `{it['target_open']}` | 衝頂: `{it['surge_target']}` | 防守: `{it['defense_price']}`")
    lines.append("")

    lines.append("💡 *風控提醒*：嚴守流動性防護與紀律防守線；破位請果斷停損。")
    return "\n".join(lines)


# ------------------------------------------------------------------------------
# 單獨測試入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("🔍 正在進行 screening_engine.py 獨立單元測試...")
    engine = ScreeningEngine(db_path="waynebot_history.db")
    try:
        report_data = engine.run_all_screens()
        text_report = format_telegram_report(report_data)
        print("✅ 選股引擎執行成功！報表預覽：\n")
        print(text_report)
    except FileNotFoundError as e:
        print(f"⚠️ 測試提示：{e}")
        print("💡 請確認本地或工作區已具備 waynebot_history.db 後即可完整產出報表。")
