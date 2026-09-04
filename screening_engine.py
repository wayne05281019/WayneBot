# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組二 - 即時選股與價位精算核心
# 檔案路徑：screening_engine.py
# 核心功能：
#   1. 海選：周帶量、站上季線、止跌（不再列雙綠／半年高／兩年高；同條件整檔不推）
#   2. 當沖動能專區（進場價、+3%第一停利、+6%衝頂、均價停損）
#   3. 隔日沖精選專區（買進區間、明日+3.5~4.8%開高目標、衝頂價、保本防守價）
#   4. S 級籌碼濾網（投信連買 + 5MA向上勾角）
#   5. 中小型股流動性雙防護（日量 >= 1,000張 且 日額 >= 3,000萬）
# ==============================================================================

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np


try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"


class ScreeningEngine:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_db_path()

    def _get_connection(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def get_latest_trading_date(self) -> str:
        """海選基準日：庫裡最後完整收盤日（跳週末；假日／颱風停市無齊庫則往前）。"""
        try:
            from trading_calendar import resolve_screen_as_of

            resolved = resolve_screen_as_of(self.db_path)
            if resolved:
                return resolved
        except Exception:
            pass
        try:
            from import_health import latest_complete_quote_date

            complete = latest_complete_quote_date(self.db_path)
            if complete:
                return complete
        except Exception:
            pass
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT replace(date,'-','') FROM daily_quotes
                GROUP BY replace(date,'-','')
                ORDER BY replace(date,'-','') DESC
                LIMIT 15
                """
            )
            from trading_calendar import is_trading_weekday

            for (raw,) in cursor.fetchall():
                d = str(raw or "").replace("-", "")[:8]
                if d and is_trading_weekday(d):
                    return d
            cursor.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes;")
            row = cursor.fetchone()
            return row[0] if row and row[0] else datetime.now().strftime("%Y%m%d")

    def load_market_data(self, target_date: Optional[str] = None, min_volume: int = 1000, min_turnover_k: float = 30000.0) -> Dict[str, pd.DataFrame]:
        """
        載入全市場數據並執行「流動性第一層過濾」：
        - 門檻：當日成交量 >= 1,000 張 且 成交金額 >= 3,000 萬元 (turnover_k >= 30,000)
        - 僅對通過流動性之標的載入回溯 120~480 日歷史 K 線，確保毫秒級運算效能
        """
        conn = self._get_connection()
        if not target_date:
            target_date = self.get_latest_trading_date()

        query_candidates = """
        SELECT stock_id, stock_name, market, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE date = ?
          AND volume >= ?
          AND turnover_k >= ?
          AND close > 0;
        """
        df_candidates = pd.read_sql_query(
            query_candidates, conn, params=(target_date, min_volume, min_turnover_k)
        )
        valid_sids = df_candidates['stock_id'].tolist()

        if not valid_sids:
            conn.close()
            return {}

        floor_row = conn.execute(
            """
            SELECT MIN(d) FROM (
                SELECT DISTINCT date AS d FROM daily_quotes
                WHERE date <= ?
                ORDER BY date DESC
                LIMIT 500
            )
            """,
            (target_date,),
        ).fetchone()
        date_floor = floor_row[0] if floor_row and floor_row[0] else None

        placeholders = ",".join("?" * len(valid_sids))
        query_history = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id IN ({placeholders})
          AND date <= ?
          {"AND date >= ?" if date_floor else ""}
        ORDER BY stock_id, date ASC;
        """
        params = list(valid_sids) + [target_date]
        if date_floor:
            params.append(date_floor)
        df_all = pd.read_sql_query(query_history, conn, params=params)
        conn.close()

        # 依 stock_id 分組
        stock_dfs = {sid: group.reset_index(drop=True) for sid, group in df_all.groupby('stock_id')}
        return stock_dfs

    def calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """計算單一標的之關鍵量化與均線指標"""
        if len(df) < 5:
            return {}

        close_series = df['close']
        high_series = df['high']
        low_series = df['low']
        vol_series = df['volume']
        trust_series = df['trust_net']

        # 均線計算（同一條 rolling 只算一次）
        ma5_s = close_series.rolling(5).mean()
        ma5 = ma5_s.iloc[-1]
        ma5_prev = ma5_s.iloc[-2] if len(df) >= 6 else ma5
        ma20 = close_series.rolling(20).mean().iloc[-1] if len(df) >= 20 else ma5
        ma60_s = close_series.rolling(60, min_periods=20).mean()
        ma60 = ma60_s.iloc[-1] if len(df) >= 20 else ma20
        ma60_prev = ma60_s.iloc[-2] if len(df) >= 21 else ma60
        
        # 量能指標 Q60R (當日量 / 60日均量)
        vol_ma60 = vol_series.rolling(60).mean().iloc[-1] if len(df) >= 60 else vol_series.mean()
        latest_vol = vol_series.iloc[-1]
        q60r = round(latest_vol / vol_ma60, 2) if vol_ma60 > 0 else 1.0

        # 歷史高低點
        # Hi5: 前 5 日最高價（不含今日）
        hi5 = high_series.iloc[-6:-1].max() if len(df) >= 6 else high_series.iloc[:-1].max()
        # Hi120: 前 120 日最高價
        hi120 = high_series.iloc[-121:-1].max() if len(df) >= 121 else high_series.iloc[:-1].max()
        # Hi480: 前 480 日最高價（兩年大底）
        hi480 = high_series.iloc[-481:-1].max() if len(df) >= 481 else high_series.iloc[:-1].max()

        close_win20 = close_series.iloc[-20:] if len(close_series) >= 20 else close_series
        hi20_close = float(close_win20.max()) if len(close_win20) else 0.0

        # 20日與60日最低點
        low20 = low_series.iloc[-21:-1].min() if len(df) >= 21 else low_series.iloc[:-1].min()
        low60 = low_series.iloc[-61:-1].min() if len(df) >= 61 else low_series.iloc[:-1].min()

        # D20: 距離 20 日低點幅度 (%)
        latest_close = close_series.iloc[-1]
        latest_open = df['open'].iloc[-1]
        latest_high = df['high'].iloc[-1]
        latest_low = df['low'].iloc[-1]
        latest_avg = df['avg_price'].iloc[-1]
        pct_change = df['pct_change'].iloc[-1]
        turnover_k = df['turnover_k'].iloc[-1]

        d20 = round((latest_close - low20) / low20 * 100.0, 2) if (low20 and low20 > 0) else 0.0
        dist_h20 = round((latest_close - hi20_close) / hi20_close * 100.0, 2) if hi20_close else 0.0
        chase_warning = bool(hi20_close > 0 and latest_close >= hi20_close * 0.985)
        try:
            from decision_card_signals import TEMP_ATH_WATCH, compute_card_temperature

            h20_w = float(high_series.tail(20).max()) if len(high_series) else 0.0
            l20_w = float(low_series.tail(20).min()) if len(low_series) else 0.0
            h60_w = float(high_series.tail(60).max()) if len(high_series) else 0.0
            l60_w = float(low_series.tail(60).min()) if len(low_series) else 0.0
            bias_m = ((float(latest_close) - float(ma20)) / float(ma20) * 100.0) if ma20 else 0.0
            temp_n = compute_card_temperature(
                float(latest_close), h20_w, l20_w, bias_m, high60=h60_w, low60=l60_w
            )
            near_ath = bool(
                (hi120 and float(latest_close) >= float(hi120) * 0.998)
                or (hi480 and float(latest_close) >= float(hi480) * 0.998)
            )
            if near_ath and temp_n >= TEMP_ATH_WATCH:
                chase_warning = True
        except Exception:
            pass
        prev_close = close_series.iloc[-2] if len(df) >= 2 else latest_close
        prev_d20 = round((prev_close - low20) / low20 * 100.0, 2) if (low20 and low20 > 0) else 0.0

        # 5MA 向上勾角判定
        ma5_hook_up = bool(ma5 > ma5_prev and latest_close > ma5)

        # 投信連買判定（近 2 日投信淨買超 > 0）
        trust_consecutive_buy = False
        if len(trust_series) >= 2:
            trust_consecutive_buy = bool(trust_series.iloc[-1] > 0 and trust_series.iloc[-2] > 0)

        # S 級標籤（投信連買 + 5MA向上勾角）
        is_s_tier = bool(trust_consecutive_buy and ma5_hook_up)

        return {
            "stock_id": df['stock_id'].iloc[-1],
            "stock_name": df['stock_name'].iloc[-1],
            "market": df['market'].iloc[-1],
            "close": latest_close,
            "open": latest_open,
            "high": latest_high,
            "low": latest_low,
            "volume": int(latest_vol),
            "turnover_k": turnover_k,
            "avg_price": latest_avg if latest_avg > 0 else latest_close,
            "pct_change": pct_change,
            "q60r": q60r,
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(float(ma60), 2) if pd.notna(ma60) else 0.0,
            "ma60_prev": round(float(ma60_prev), 2) if pd.notna(ma60_prev) else 0.0,
            "hi5": hi5,
            "hi20_close": hi20_close,
            "dist_h20": dist_h20,
            "chase_warning": chase_warning,
            "hi120": hi120,
            "hi480": hi480,
            "low20": low20,
            "low60": low60,
            "d20": d20,
            "prev_d20": prev_d20,
            "ma5_hook_up": ma5_hook_up,
            "trust_consecutive_buy": trust_consecutive_buy,
            "is_s_tier": is_s_tier,
            "prev_close": prev_close,
            "foreign_net": int(df['foreign_net'].iloc[-1]),
            "trust_net": int(df['trust_net'].iloc[-1]),
            "dealer_net": int(df['dealer_net'].iloc[-1]),
        }


    def execute_all_strategies(self, stock_dfs: Dict[str, pd.DataFrame]) -> Dict[str, List[Dict[str, Any]]]:
        """對所有通過流動性檢驗的標的執行 CaryBot 四大選股與動能定價"""
        res_sel_01 = []
        res_sel_02 = []
        res_sel_03 = []
        res_day_trade = []
        res_overnight = []
        res_leave_zero = []
        res_golden_buy = []
        res_half_year_high = []

        for sid, df in stock_dfs.items():
            info = self.calculate_indicators(df)
            if not info:
                continue
            if _is_half_year_high_break(info):
                enriched = _enrich_decision_fields(df, info)
                enriched["pattern"] = _pattern_tag(enriched)
                if not _is_downtrend_no_touch(enriched):
                    res_half_year_high.append(enriched)
                continue
            if _skip_long_term_high_push(info):
                continue
            info = _enrich_decision_fields(df, info)
            info["pattern"] = _pattern_tag(info)
            layout_ok = not _is_downtrend_no_touch(info)

            c = info["close"]
            o = info["open"]
            pct = info["pct_change"]
            q = info["q60r"]
            hi5 = info["hi5"]
            hi120 = info["hi120"]
            hi480 = info["hi480"]
            d20 = info["d20"]
            prev_d20 = info["prev_d20"]
            ma5_hook = info["ma5_hook_up"]
            avg_p = _avg_price_for_safety(info)
            prev_close = info.get("prev_close") or c

            # ------------------------------------------------------------------
            # CaryBot Select 01: 周帶量突破 (5日高 + Q60R > 2.0)
            # ------------------------------------------------------------------
            if layout_ok and hi5 and c >= hi5 and q >= 2.0 and pct > 0.5:
                res_sel_01.append(info)

            # Select 02: 站上季線（昨收在季線下、今日站上）。不是追半年高。
            ma60 = info.get("ma60") or 0
            ma60_prev = info.get("ma60_prev") or ma60
            on_ma60 = False
            if (
                layout_ok
                and ma60 > 0
                and prev_close < ma60_prev
                and c >= ma60
                and pct > 0
                and q >= 1.0
            ):
                res_sel_02.append(info)
                on_ma60 = True

            # Select 03: 止跌＝月低附近有人接、量沒死。不用季低，避免跌很久才彈。
            if (
                layout_ok
                and not on_ma60
                and not info.get("chase_warning")
                and pct > 0
                and q >= 1.0
                and info.get("low20")
                and c <= float(info["low20"]) * 1.06
                and (ma5_hook or c >= o)
            ):
                res_sel_03.append(info)

            # 黃金買點：60低 + 獲利≈0 + 月乖離超跌（決策卡同一套欄位；可收下坡末端）。
            if _golden_buy_ok(info):
                golden = dict(info)
                golden["golden_buy"] = True
                res_golden_buy.append(golden)

            # 起漲＝高低卡「獲利」格剛離開 0（近 60 曆日收盤低，跟決策卡同一條）。
            # 量熱或昨收高低格還在 20 低，才算有人接；明顯空頭／月線下整理不進桶。
            if len(df) >= 5:
                from decision_card_signals import calc_volume_rank

                vols = df["volume"].to_numpy(dtype=float)
                closes = df["close"].to_numpy(dtype=float)
                turns = (
                    df["turnover_k"].to_numpy(dtype=float)
                    if "turnover_k" in df.columns
                    else None
                )
                window_n = min(120, len(vols))
                rank = calc_volume_rank(
                    vols[-window_n:],
                    120,
                    closes=closes[-window_n:],
                    turnovers=turns[-window_n:] if turns is not None else None,
                )
                leave_l20 = prev_d20 <= 2.0 and d20 >= 2.0
                vol_hot = leave_l20 or rank <= 20 or q >= 2.0
                close_s = df["close"].astype(float)
                l20c = close_s.rolling(20, min_periods=5).min()
                yest_l20 = float(l20c.iloc[-2]) if len(l20c) >= 2 else 0.0
                yest_hl_low = bool(yest_l20 > 0 and float(info["prev_close"]) <= yest_l20 * 1.002)
                sid_s = str(info.get("stock_id") or "")
                if (
                    layout_ok
                    and _leave_zero_profit_ok(df, info)
                    and (vol_hot or yest_hl_low)
                    and _leave_zero_trend_ok(info)
                    and len(sid_s) == 4
                    and sid_s.isdigit()
                ):
                    item = dict(info)
                    item["profit"] = float(info.get("profit_pct") or 0)
                    item["vol_rank_120"] = rank
                    item["leave_l20"] = leave_l20 or yest_hl_low
                    res_leave_zero.append(item)

            # ------------------------------------------------------------------
            # 當沖動能專區：量能放大 (Q60R >= 2.0)、5MA 向上、振幅 2.0%~8.0%
            # ------------------------------------------------------------------
            if q >= 2.0 and ma5_hook and 2.0 <= pct <= 8.5:
                day_trade_item = dict(info)
                day_trade_item["entry_price"] = c
                day_trade_item["target_1"] = round(c * 1.03, 2)   # +3% 第一停利
                day_trade_item["target_2"] = round(c * 1.06, 2)   # +6% 第二衝頂
                day_trade_item["stop_loss"] = round(avg_p, 2)     # 均價停損
                res_day_trade.append(day_trade_item)

            # ------------------------------------------------------------------
            # 隔日沖精選專區：尾盤強勢實體紅K (收盤>開盤1.8%)、量比 Q60R >= 1.8
            # ------------------------------------------------------------------
            if q >= 1.8 and c >= o * 1.018 and c > info["ma20"] and pct >= 2.5:
                overnight_item = dict(info)
                overnight_item["buy_range"] = f"{round(c * 0.992, 2)} ~ {c}"
                overnight_item["target_gap"] = f"{round(c * 1.035, 2)} ~ {round(c * 1.048, 2)}" # +3.5%~+4.8%
                overnight_item["target_max"] = round(c * 1.07, 2) # +7% 衝頂價
                overnight_item["defense_price"] = round(min(o, avg_p), 2) # 保本防守價
                res_overnight.append(overnight_item)

        # 排序：少追（貼20日收盤高）排後面；S級與量比仍優先
        sort_key = lambda x: (
            0 if x.get("chase_warning") else 1,
            1 if x.get("is_s_tier", False) else 0,
            x.get("q60r", 0.0),
        )
        res_sel_01.sort(key=sort_key, reverse=True)
        res_sel_02.sort(key=sort_key, reverse=True)
        res_sel_03.sort(key=sort_key, reverse=True)
        res_day_trade.sort(key=sort_key, reverse=True)
        res_overnight.sort(key=sort_key, reverse=True)
        res_leave_zero.sort(
            key=lambda x: (
                1 if x.get("chase_warning") else 0,
                0 if x.get("leave_l20") else 1,
                int(x.get("vol_rank_120") or 99),
                -(x.get("q60r") or 0),
            )
        )

        res_golden_buy.sort(
            key=lambda x: (
                1 if x.get("chase_warning") else 0,
                float(x.get("bias_monthly") or 0),
                abs(float(x.get("profit_pct") or 0)),
            )
        )
        res_half_year_high.sort(key=sort_key, reverse=True)

        return {
            "select_01": res_sel_01,
            "select_02": res_sel_02,
            "select_03": res_sel_03,
            "half_year_high": res_half_year_high,
            "leave_zero": res_leave_zero,
            "golden_buy": res_golden_buy,
            "day_trade": res_day_trade,
            "overnight": res_overnight
        }

    @staticmethod
    def _row_for_bot(item: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(item)
        out["code"] = str(item.get("stock_id") or "")
        out["name"] = item.get("stock_name") or ""
        out["score"] = int(round(float(item.get("q60r") or 0) * 10))
        return out

    def _enrich_session_trade_rows(
        self, session_rows: List[Dict[str, Any]], target_date: str
    ) -> List[Dict[str, Any]]:
        """把 screen_sessions 桶資料補上昨收行情，供當沖／隔日沖盤中複核。"""
        if not session_rows:
            return []
        codes = [str(r.get("stock_id") or "").strip() for r in session_rows]
        codes = [c for c in codes if c]
        if not codes:
            return []
        conn = self._get_connection()
        placeholders = ",".join("?" * len(codes))
        df = pd.read_sql_query(
            f"""
            SELECT stock_id, stock_name, close, volume, turnover_k, pct_change,
                   foreign_net, trust_net, dealer_net, avg_price
            FROM daily_quotes
            WHERE date = ? AND stock_id IN ({placeholders})
            """,
            conn,
            params=[target_date] + codes,
        )
        conn.close()
        by_id = {str(r["stock_id"]): r.to_dict() for _, r in df.iterrows()}
        out: List[Dict[str, Any]] = []
        for sr in session_rows:
            sid = str(sr.get("stock_id") or "").strip()
            if not sid:
                continue
            q = by_id.get(sid) or {}
            item: Dict[str, Any] = {
                "stock_id": sid,
                "stock_name": sr.get("stock_name") or q.get("stock_name") or "",
                "close": sr.get("pick_close") if sr.get("pick_close") is not None else q.get("close"),
                "hi20_close": sr.get("hi20_close"),
                "entry_price": sr.get("entry_price"),
                "defense_price": sr.get("defense_price"),
                "chase_warning": bool(sr.get("chase_warning")),
            }
            for key in (
                "volume",
                "turnover_k",
                "pct_change",
                "foreign_net",
                "trust_net",
                "dealer_net",
                "avg_price",
            ):
                if q.get(key) is not None:
                    item[key] = q[key]
            out.append(item)
        return out

    def _screen_trade_bucket_from_cache(
        self, bucket_key: str, target_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from screen_sessions import load_bucket_rows

        target_date = target_date or self.get_latest_trading_date()
        rows = load_bucket_rows(self.db_path, bucket_key, target_date)
        if not rows:
            rows = load_bucket_rows(self.db_path, bucket_key, "")
        if not rows:
            return []
        enriched = self._enrich_session_trade_rows(rows, target_date)
        return [self._row_for_bot(x) for x in enriched]

    def screen_daytrade(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """主選單當沖：只讀海選快取 + 盤中 MIS 複核，不跑全市場掃描。"""
        target_date = target_date or self.get_latest_trading_date()
        return self._screen_trade_bucket_from_cache("day_trade", target_date)

    def screen_overnight(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """主選單隔日沖：只讀海選快取 + 盤中 MIS 複核，不跑全市場掃描。"""
        target_date = target_date or self.get_latest_trading_date()
        return self._screen_trade_bucket_from_cache("overnight", target_date)

    def run_full_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        return execute_full_screening(self.db_path, target_date)


def _is_half_year_high_break(info: Dict[str, Any]) -> bool:
    """收盤創約 120 交易日新高（半年高）且帶量。"""
    try:
        c = float(info.get("close") or 0)
        hi120 = float(info.get("hi120") or 0)
        q = float(info.get("q60r") or 0)
        pct = float(info.get("pct_change") or 0)
    except (TypeError, ValueError):
        return False
    return hi120 > 0 and c >= hi120 and q >= 2.5 and pct >= 3.0


def _skip_long_term_high_push(info: Dict[str, Any]) -> bool:
    """兩年高整檔不進其他海選桶（半年高改獨立分類）。"""
    try:
        c = float(info.get("close") or 0)
        hi480 = float(info.get("hi480") or 0)
        q = float(info.get("q60r") or 0)
        pct = float(info.get("pct_change") or 0)
    except (TypeError, ValueError):
        return False
    break480 = hi480 > 0 and c >= hi480
    return bool(break480 and q >= 3.0 and pct >= 4.0)


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _regime_label(item: Dict[str, Any]) -> str:
    """海選旁的格局標籤（依收盤相對月／季線與月低）。"""
    try:
        c = float(item.get("close") or 0)
        ma20 = float(item.get("ma20") or 0)
        ma60 = float(item.get("ma60") or 0)
        low20 = float(item.get("low20") or 0)
        d20 = float(item.get("d20") or 0)
    except (TypeError, ValueError):
        return "整理格局"
    if low20 and c > 0 and c <= low20 * 1.008:
        return "弱勢破底"
    if d20 <= 1.2:
        return "貼近月低"
    if ma20 and ma60 and c >= ma20 and ma20 >= ma60:
        return "多頭排列"
    if ma20 and ma60 and c <= ma20 and ma20 <= ma60:
        return "空頭排列"
    if ma20 and c >= ma20:
        return "站上月線"
    if ma20 and c < ma20:
        return "月線下整理"
    return "整理格局"


def _cal60_low_close(df: pd.DataFrame, idx: int = -1) -> float:
    """與決策卡同一條：該日往前 60 曆日收盤最低。"""
    from decision_card_signals import cal60_low_close_at

    return cal60_low_close_at(df, idx)


def _enrich_decision_fields(df: pd.DataFrame, info: Dict[str, Any]) -> Dict[str, Any]:
    """對齊高低決策卡：獲利、月乖離、60低（邏輯層，不動出圖色票）。"""
    from decision_card_signals import cal60_low_close_at, profit_floor_at, profit_pct_cal60_series

    out = dict(info)
    close_s = df["close"].astype(float)
    c = float(out.get("close") or 0)
    l60 = float(close_s.rolling(60, min_periods=20).min().iloc[-1] or 0)
    profits = profit_pct_cal60_series(df)
    cal60 = cal60_low_close_at(df)
    floor = profit_floor_at(df)
    ma20 = float(out.get("ma20") or 0)
    out["low_60_close"] = round(l60, 4) if l60 else 0.0
    out["cal60_low"] = round(cal60, 4) if cal60 else 0.0
    out["profit_floor"] = round(floor, 4) if floor else 0.0
    out["profit_pct"] = round(float(profits.iloc[-1]), 1) if len(profits) else 0.0
    out["bias_monthly"] = round((c - ma20) / ma20 * 100.0, 1) if ma20 > 0 else 0.0
    out["at_60_low"] = bool(l60 > 0 and c <= l60 * 1.005)
    return out


def _pattern_tag(info: Dict[str, Any]) -> str:
    """型態三分：上坡／箱型／下坡（下坡不碰）。"""
    regime = _regime_label(info)
    try:
        c = float(info.get("close") or 0)
        ma20 = float(info.get("ma20") or 0)
        ma60 = float(info.get("ma60") or 0)
        ma60_prev = float(info.get("ma60_prev") or ma60)
        d20 = float(info.get("d20") or 0)
        ma5_hook = bool(info.get("ma5_hook_up"))
    except (TypeError, ValueError):
        return "箱型"
    if regime in ("空頭排列", "弱勢破底", "月線下整理"):
        return "下坡"
    if ma60 > 0 and ma20 > 0 and c < ma20 and ma20 < ma60 and ma60 <= ma60_prev * 1.001:
        return "下坡"
    if ma20 > 0 and c < ma20 * 0.985 and d20 <= 2.5:
        return "下坡"
    if (
        ma20 > 0
        and ma60 > 0
        and c >= ma20
        and ma20 >= ma60
        and (ma5_hook or c >= ma20 * 1.008)
    ):
        return "上坡"
    if regime in ("多頭排列", "站上月線") and ma5_hook:
        return "上坡"
    return "箱型"


def _is_downtrend_no_touch(info: Dict[str, Any]) -> bool:
    return _pattern_tag(info) == "下坡"


def _golden_buy_ok(info: Dict[str, Any]) -> bool:
    """黃金買點：60低 + 獲利≈0 + 月乖離 < -10%（可在下坡末端，專桶收）。"""
    if not info.get("at_60_low"):
        return False
    try:
        profit = float(info.get("profit_pct") if info.get("profit_pct") is not None else 99)
        bias = float(info.get("bias_monthly") if info.get("bias_monthly") is not None else 0)
    except (TypeError, ValueError):
        return False
    if not (-1.5 <= profit <= 2.5):
        return False
    if bias >= -10.0:
        return False
    sid = str(info.get("stock_id") or "")
    return len(sid) == 4 and sid.isdigit()


def _yesterday_profit_pct(df: pd.DataFrame) -> float:
    """昨收獲利%，對齊決策卡前一列（60 曆日低）。"""
    from decision_card_signals import profit_pct_cal60_series

    if len(df) < 2:
        return 99.0
    profits = profit_pct_cal60_series(df)
    return float(profits.iloc[-2])


def _leave_zero_profit_ok(df: pd.DataFrame, info: Dict[str, Any]) -> bool:
    """起漲獲利條件：decision_card_signals.leave_zero_screen_ok（卡片實綠／雙綠脫離）。"""
    from decision_card_signals import card_alerts_for_df, leave_zero_screen_ok

    try:
        pt = float(info.get("profit_pct") if info.get("profit_pct") is not None else 99)
        py = _yesterday_profit_pct(df)
    except (TypeError, ValueError):
        return False
    ya, ta = card_alerts_for_df(df)
    ok, _reason = leave_zero_screen_ok(py, pt, yest_alert=ya, today_alert=ta)
    return ok


def _leave_zero_trend_ok(info: Dict[str, Any]) -> bool:
    """起漲桶：獲利剛離零之外，排除明顯趨勢向下；保留多頭或站上月／季線向上。"""
    if _is_downtrend_no_touch(info):
        return False
    regime = _regime_label(info)
    if regime in ("空頭排列", "弱勢破底", "月線下整理"):
        return False
    try:
        c = float(info.get("close") or 0)
        ma20 = float(info.get("ma20") or 0)
        ma60 = float(info.get("ma60") or 0)
    except (TypeError, ValueError):
        return False
    if regime in ("多頭排列", "站上月線"):
        return True
    if ma20 > 0 and c >= ma20:
        return True
    if ma60 > 0 and ma20 >= ma60 and c >= ma60:
        return True
    return False


def _pct_str(pct) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return ""
    return f"+{p:.2f}%" if p > 0 else f"{p:.2f}%"


def _avg_price_for_safety(item: Dict[str, Any]) -> float:
    """停損／防守價用均價；庫裡若誤存成交股數則改算 turnover÷volume。"""
    try:
        avg_p = float(item.get("avg_price") or 0)
    except (TypeError, ValueError):
        avg_p = 0.0
    try:
        close = float(item.get("close") or 0)
    except (TypeError, ValueError):
        close = 0.0
    try:
        vol_lots = int(item.get("volume") or 0)
    except (TypeError, ValueError):
        vol_lots = 0
    try:
        turnover_k = float(item.get("turnover_k") or 0)
    except (TypeError, ValueError):
        turnover_k = 0.0
    computed = round(turnover_k / vol_lots, 2) if vol_lots > 0 and turnover_k > 0 else close
    if avg_p <= 0:
        return computed
    shares = vol_lots * 1000
    if shares > 0 and abs(avg_p - shares) <= max(1.0, shares * 0.001):
        return computed
    try:
        low = float(item.get("low") or close or 0)
        high = float(item.get("high") or close or 0)
    except (TypeError, ValueError):
        low, high = close, close
    band_lo = min(low, close) * 0.5 if min(low, close) > 0 else 0.0
    band_hi = max(high, close) * 2.0 if max(high, close) > 0 else avg_p
    if band_lo > 0 and (avg_p < band_lo or avg_p > band_hi):
        return computed
    return avg_p


def _px_str(close) -> str:
    if close is None or close == "":
        return "—"
    try:
        v = float(close)
    except (TypeError, ValueError):
        return html_escape(close)
    if v >= 100:
        s = f"{v:.1f}".rstrip("0").rstrip(".")
    else:
        s = f"{v:.2f}"
    return html_escape(s)


def _hot(text: str) -> str:
    """Telegram HTML 不能指定紅色；該注意的數字／標籤用粗體當視覺錨點。"""
    return f"<b>{html_escape(text)}</b>"


def _pct_html(pct) -> str:
    s = _pct_str(pct)
    return _hot(s) if s else "—"


def _q_html(q) -> str:
    if q is None or q == "":
        return "—"
    try:
        v = float(q)
        shown = f"{v:.2f}×"
        return _hot(shown) if v >= 2 else html_escape(shown)
    except (TypeError, ValueError):
        return html_escape(str(q))


def _chip_plain(item: Dict[str, Any]) -> str:
    def _n(key: str) -> str:
        try:
            v = int(item.get(key) or 0)
        except (TypeError, ValueError):
            return "0"
        return f"{v:+,}"

    return f"外資{_n('foreign_net')}張　投信{_n('trust_net')}張　自營{_n('dealer_net')}張"


def _chip_html(item: Dict[str, Any]) -> str:
    return html_escape(_chip_plain(item))


def _safety_plan_plain(item: Dict[str, Any]) -> List[str]:
    """當沖／隔日沖：保險進多少、出多少、守哪裡。"""
    lines: List[str] = []
    if item.get("target_1") is not None or item.get("entry_price") is not None:
        entry = _px_str(item.get("entry_price") if item.get("entry_price") is not None else item.get("close"))
        lines.append(f"保險進場　≤ {entry}（量能放大當日收盤；不要追更高）")
        lines.append(f"第一停利　{_px_str(item.get('target_1'))}（+3%，先出一部分鎖利）")
        lines.append(f"衝頂停利　{_px_str(item.get('target_2'))}（+6%，剩下再衝；沖不到就不要硬等）")
        lines.append(f"保險停損　{_px_str(item.get('stop_loss'))}（當日均價；跌破先走，不要硬扛）")
    elif item.get("buy_range") is not None:
        lines.append(f"保險買進　尾盤 {item.get('buy_range')}（昨收附近，不要摸高）")
        lines.append(f"明早開高　{item.get('target_gap')}（+3.5%～+4.8% 目標）")
        lines.append(f"衝頂　　　{_px_str(item.get('target_max'))}（+7%）")
        lines.append(f"保險防守　{_px_str(item.get('defense_price'))}（開盤與均價較低者；跌破先走）")
    return lines


def _safety_plan_html(item: Dict[str, Any]) -> List[str]:
    out = []
    for line in _safety_plan_plain(item):
        if "　" in line:
            label, rest = line.split("　", 1)
            out.append(f"{html_escape(label)}　{_hot(rest)}")
        else:
            out.append(_hot(line))
    return out


def _stock_card_html(item: Dict[str, Any], idx: int, *, show_line_link: bool = True) -> str:
    from tg_layout import html_qty_tight

    sid = str(item.get("stock_id") or item.get("code") or "")
    sname = str(item.get("stock_name") or item.get("name") or "")
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(sid, sname)
    except Exception:
        title = f"{html_escape(sid)} {html_escape(sname)}"
    regime = html_escape(_regime_label(item))
    close_s = _px_str(item.get("close"))
    vol = int(item.get("volume") or 0)
    notices: List[str] = []
    if item.get("both_sessions"):
        notices.append(_hot("雙時段"))
    if item.get("chase_warning"):
        notices.append(_hot("少追"))
    if item.get("is_s_tier"):
        notices.append(_hot("S級"))
    if item.get("leave_l20"):
        notices.append(_hot("20低脫離"))
    if item.get("revenue_hot"):
        notices.append(_hot("營收轉強"))
    if item.get("golden_buy"):
        notices.append(_hot("黃金買點"))
    if item.get("at_60_low") and not item.get("golden_buy"):
        notices.append(_hot("60低"))
    if item.get("sector_inflow"):
        notices.append(_hot(str(item.get("sector_flow_label") or "輪動進")))
    elif item.get("sector_outflow"):
        notices.append(html_escape(str(item.get("sector_flow_label") or "輪動出")))
    if item.get("us_peer_headwind"):
        notices.append(_hot("費半逆風"))
    if item.get("us_risk_off"):
        notices.append(_hot("隔夜逆風"))
    elif item.get("us_caution"):
        notices.append(html_escape("隔夜偏空"))
    to_k = item.get("turnover_k")
    try:
        to_s = f"{float(to_k) / 1000.0:.1f}億" if to_k is not None else ""
    except (TypeError, ValueError):
        to_s = ""
    body = [
        f"<b>{idx}.</b> {title}"
        + (f"　{_line_stock_html_link(sid)}" if sid and show_line_link else ""),
    ]
    live = item.get("live")
    if live:
        try:
            from trade_live import format_trade_live_line

            live_line = format_trade_live_line(live)
            if live_line:
                body.append(live_line)
        except Exception:
            pass
    body.extend([
        f"格局　{regime}",
        f"收盤　{close_s}　漲跌　{_pct_html(item.get('pct_change'))}",
        f"量　{html_qty_tight(vol, signed=False)}　量比　{_q_html(item.get('q60r'))}",
    ])
    if to_s:
        body.append(f"額　<code>{html_escape(to_s)}</code>")
    body.extend([
        f"均線　月{_px_str(item.get('ma20'))}　季{_px_str(item.get('ma60'))}",
        f"法人　{_chip_html(item)}",
    ])
    pat = str(item.get("pattern") or "")
    if pat:
        body.append(f"型態　{html_escape(pat)}")
    if item.get("golden_buy"):
        body.append(
            f"獲利　{html_escape(item.get('profit_pct'))}%　"
            f"月乖離　{html_escape(item.get('bias_monthly'))}%"
        )
    if notices:
        body.append("注意　" + "　".join(notices))
    if item.get("profit") is not None:
        body.append(f"獲利　{html_escape(item.get('profit'))}%（近60曆日低點上來）")
    rank_val = None
    if live and live.get("vol_rank_120") is not None:
        rank_val = int(live["vol_rank_120"])
    elif item.get("vol_rank_120"):
        rank_val = int(item["vol_rank_120"])
    if rank_val is not None:
        rank_s = f"第{rank_val}名"
        if live and live.get("vol_rank_120") is not None:
            rank_s = f"第{rank_val}名（盤中即時）"
        body.append("120量　" + (_hot(rank_s) if rank_val <= 20 else html_escape(rank_s)))
    plan = _safety_plan_html(item)
    if plan:
        body.extend(plan)
    return f"<blockquote>{chr(10).join(body)}</blockquote>"


def _compact_line(item: Dict[str, Any]) -> str:
    from tg_layout import html_qty

    sid = str(item.get("stock_id") or item.get("code") or "")
    sname = str(item.get("stock_name") or item.get("name") or "")
    q = item.get("q60r")
    q_s = ""
    try:
        q_s = f"{float(q):.2f}×" if q is not None and q != "" else ""
    except (TypeError, ValueError):
        q_s = str(q or "")
    pct = _pct_html(item.get("pct_change"))
    hot = "　".join(
        t
        for t, on in (
            (_hot("雙時段"), item.get("both_sessions")),
            (_hot("少追"), item.get("chase_warning")),
            (_hot("S級"), item.get("is_s_tier")),
            (_hot("20低脫離"), item.get("leave_l20")),
            (_hot("營收轉強"), item.get("revenue_hot")),
            (_hot(str(item.get("sector_flow_label") or "輪動進")), item.get("sector_inflow")),
            (_hot("費半逆風"), item.get("us_peer_headwind")),
            (_hot("隔夜逆風"), item.get("us_risk_off")),
        )
        if on
    )
    extra = f"　{hot}" if hot else ""
    plan = ""
    if item.get("target_1") is not None or item.get("entry_price") is not None:
        plan = (
            f"　保險進≤{_px_str(item.get('entry_price') if item.get('entry_price') is not None else item.get('close'))}"
            f"　停利{_px_str(item.get('target_1'))}/{_px_str(item.get('target_2'))}"
            f"　停損均價{_px_str(item.get('stop_loss'))}"
        )
    elif item.get("buy_range") is not None:
        plan = (
            f"　買{html_escape(item.get('buy_range'))}"
            f"　開高{html_escape(item.get('target_gap'))}"
            f"　守{_px_str(item.get('defense_price'))}"
        )
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(sid, sname)
    except Exception:
        title = f"{html_escape(sid)} {html_escape(sname)}"
    from tg_layout import html_price, join_sections, kv_html, section

    rows = [
        kv_html("型態", html_escape(_regime_label(item))),
        kv_html("收盤", f"{html_price(item.get('close'))}　{pct}"),
        kv_html("成交量", html_qty(item.get("volume"), signed=False)),
    ]
    if q_s:
        rows.append(kv_html("60量比", html_escape(q_s)))
    if extra:
        rows.append(kv_html("標記", extra.strip()))
    body = section(*rows)
    if plan:
        body = join_sections(body, plan.strip())
    return f"{title}\n{body}"


# 06:30 海選推播只推佈局桶；當沖／隔日沖改主選單單獨查。
SCREEN_PUSH_SPECS = (
    ("leave_zero", "🌱", "起漲", "高低卡獲利實綠／雙綠脫離（今≤5%；排除明顯空頭）", 8, True),
    ("golden_buy", "✨", "黃金買點", "60低＋獲利≈0＋月乖離<-10%（排除下坡）", 8, True),
    ("revenue_cross", "📈", "優先看", "營收轉強 × 量價突破", 8, False),
    ("select_01", "🔥", "周帶量", "突破5日高＋60日量比≥2", 8, True),
    ("half_year_high", "📊", "半年高", "收盤創120日新高且量比≥2.5", 8, True),
    ("select_02", "🏆", "站上季線", "昨收在季線下、今日站上季線", 8, True),
    ("select_03", "💎", "止跌", "月低附近有人接、量比≥1、今日翻紅", 8, True),
)

LINE_TRADE_POINTER = (
    "＝＝短線（不在晨間海選）＝＝\n"
    "當沖、隔日沖名單改在 Telegram 主選單按「當沖」或「隔日沖」查看（同樣是昨收掃描，含保險進／停利／停損）。"
)


def format_screening_payload(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
) -> List[Dict[str, Any]]:
    """每個分類一則訊息；標題由左邊小動圖 + 分類名的貼紙呈現。"""
    payload: List[Dict[str, Any]] = []
    specs = list(SCREEN_PUSH_SPECS)
    first = True
    for key, emoji, label, subtitle, cap, skip_empty in specs:
        items = results.get(key) or []
        if skip_empty and not items:
            continue
        head = f"＝＝{html_escape(label)}｜{html_escape(subtitle)}＝＝"
        if first:
            from trading_calendar import format_trading_date_zh
            from tg_layout import headline_lines

            as_of_label = format_trading_date_zh(target_date)
            head = headline_lines(
                "<b>WayneBot 海選</b>",
                f"昨收　{html_escape(as_of_label)}",
                head,
                f"共 {len(items)} 檔",
            )
            first = False
        else:
            head = f"{head}　共 {len(items)} 檔"
        part: Dict[str, Any] = {
            "mark_key": key,
            "line_pack_id": key,
            "mark_label": f"{label} · {len(items)}檔",
            "mark_hint": subtitle,
        }
        if not items:
            part["html"] = head + "\n<i>今日無符合條件標的</i>"
            payload.append(part)
            continue
        cards = [_stock_card_html(it, n + 1, show_line_link=False) for n, it in enumerate(items)]
        part["html"] = head + "\n" + "\n".join(cards)
        payload.append(part)

    if not payload:
        from trading_calendar import format_trading_date_zh

        payload.append(
            {
                "html": (
                    f"<b>WayneBot 海選</b>　昨收 {html_escape(format_trading_date_zh(target_date))}\n"
                    "<i>今日無符合條件標的</i>"
                )
            }
        )
    return payload


def format_screening_sections(results: Dict[str, List[Dict[str, Any]]], target_date: str) -> List[str]:
    return [p["html"] for p in format_screening_payload(results, target_date)]


SHARE_SEP = "────────────────"


def _line_stock_html_link(stock_id: str) -> str:
    from config import get_public_base_url

    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    url = f"{get_public_base_url()}/line/stock/{sid}"
    return f'<a href="{html_escape(url)}">開 LINE・傳這檔</a>'


def _date_slash(target_date: str) -> str:
    d = str(target_date or "").replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}/{d[4:6]}/{d[6:]}"
    return str(target_date or "")


def _yahoo_web(sid: str, db_path: Optional[str] = None) -> str:
    sid = str(sid or "").strip()
    if not sid:
        return ""
    try:
        from stock_links import yahoo_urls

        web, _mobile = yahoo_urls(sid, db_path)
        return web
    except Exception:
        return f"https://tw.stock.yahoo.com/quote/{sid}.TW"


def split_line_share_chunks(text: str, limit: int = 3500) -> List[str]:
    """超過約 3500 字就在區隔線切開，每則標好轉寄稿 1/2。"""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p for p in text.split("\n" + SHARE_SEP + "\n") if p.strip()]
    packed: List[str] = []
    buf: List[str] = []
    size = 0
    for p in parts:
        extra = len(p) + (0 if not buf else len("\n" + SHARE_SEP + "\n"))
        if buf and size + extra > limit:
            packed.append(("\n" + SHARE_SEP + "\n").join(buf))
            buf = [p]
            size = len(p)
        else:
            buf.append(p)
            size += extra
    if buf:
        packed.append(("\n" + SHARE_SEP + "\n").join(buf))
    hard: List[str] = []
    for block in packed:
        if len(block) <= limit:
            hard.append(block)
            continue
        for i in range(0, len(block), limit):
            hard.append(block[i : i + limit])
    n = len(hard)
    out: List[str] = []
    for i, body in enumerate(hard, 1):
        if body.startswith("轉寄稿"):
            out.append(body)
            continue
        if n == 1:
            head = "轉寄稿　長按這一則 → 分享到 LINE"
        else:
            head = f"轉寄稿 {i}/{n}　長按這一則 → 分享到 LINE"
        out.append(head + "\n" + body)
    return out


def _share_notices_plain(item: Dict[str, Any]) -> List[str]:
    bits: List[str] = []
    if item.get("both_sessions"):
        bits.append("雙時段")
    if item.get("chase_warning"):
        bits.append("少追")
    if item.get("is_s_tier"):
        bits.append("S級")
    if item.get("leave_l20"):
        bits.append("20低脫離")
    if item.get("revenue_hot"):
        bits.append("營收轉強")
    if item.get("golden_buy"):
        bits.append("黃金買點")
    if item.get("at_60_low"):
        bits.append("60低")
    if item.get("sector_inflow"):
        bits.append(str(item.get("sector_flow_label") or "輪動進"))
    elif item.get("sector_outflow"):
        bits.append(str(item.get("sector_flow_label") or "輪動出"))
    if item.get("us_peer_headwind"):
        bits.append("費半逆風")
    if item.get("us_risk_off"):
        bits.append("隔夜逆風")
    elif item.get("us_caution"):
        bits.append("隔夜偏空")
    return bits


def _share_stock_block(it: Dict[str, Any], idx: int, db_path: Optional[str] = None) -> str:
    from line_share_format import format_line_stock_block

    return format_line_stock_block(it, idx, db_path)


LINE_STOCK_BUCKETS = (
    ("leave_zero", "起漲"),
    ("golden_buy", "黃金買點"),
    ("revenue_cross", "優先看"),
    ("select_01", "周帶量"),
    ("half_year_high", "半年高"),
    ("select_02", "站上季線"),
    ("select_03", "止跌"),
    ("day_trade", "當沖"),
    ("overnight", "隔日沖"),
)


def format_stock_line_share_text(
    item: Dict[str, Any],
    target_date: str,
    db_path: Optional[str] = None,
    bucket_label: str = "",
) -> str:
    sid = str(item.get("stock_id") or item.get("code") or "").strip()
    sname = str(item.get("stock_name") or item.get("name") or "").strip()
    tag = f"【{bucket_label}】" if bucket_label else ""
    return "\n".join(
        [
            f"WayneBot 海選　{_date_slash(target_date)}",
            f"{tag}{sid} {sname}".strip(),
            SHARE_SEP,
            _share_stock_block(item, 1, db_path),
        ]
    )


def build_line_stock_bodies(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    db_path: Optional[str] = None,
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, label in LINE_STOCK_BUCKETS:
        for it in results.get(key) or []:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if not sid:
                continue
            out[sid] = format_stock_line_share_text(it, target_date, db_path, bucket_label=label)
    return out


LINE_BUCKET_TITLES = {
    "leave_zero": "起漲",
    "golden_buy": "黃金買點",
    "revenue_cross": "優先看",
    "select_01": "周帶量",
    "half_year_high": "半年高",
    "select_02": "站上季線",
    "select_03": "止跌",
    "day_trade": "當沖",
    "overnight": "隔日沖",
}


def format_bucket_line_share_text(
    results: Dict[str, List[Dict[str, Any]]],
    bucket_key: str,
    target_date: str,
    db_path: Optional[str] = None,
) -> str:
    from line_share_format import format_line_bucket_body

    items = results.get(bucket_key) or []
    block = format_line_bucket_body(items, bucket_key, db_path)
    if not block:
        return ""
    return f"WayneBot 海選　{_date_slash(target_date)}\n{block}"


def build_line_bucket_packs(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, str]]:
    """每個海選分類一則 LINE 稿（整區一次轉）。"""
    packs: List[Dict[str, str]] = []
    keys = [k for k, *_ in SCREEN_PUSH_SPECS] + ["day_trade", "overnight"]
    for key in keys:
        items = results.get(key) or []
        if not items:
            continue
        text = format_bucket_line_share_text(results, key, target_date, db_path)
        if not text:
            continue
        label = LINE_BUCKET_TITLES.get(key) or key
        packs.append(
            {
                "id": key,
                "label": f"開 LINE・{label}",
                "title": f"傳 {label} 到 LINE",
                "text": text,
            }
        )
    return packs


def _share_bucket_block(
    results: Dict[str, List[Dict[str, Any]]],
    key: str,
    title: str,
    db_path: Optional[str] = None,
) -> str:
    from line_share_format import format_line_bucket_body, line_bucket_header

    items = results.get(key) or []
    us_regime = results.get("_us_regime") if isinstance(results, dict) else ""
    if not items:
        if key in ("day_trade", "overnight") and us_regime == "risk_off":
            return f"{line_bucket_header(key, 0)}\n隔夜逆風：當沖／隔日沖今日不列"
        return ""
    dict_items = [it for it in items if isinstance(it, dict)]
    if not dict_items:
        return ""
    return format_line_bucket_body(dict_items, key, db_path)


def format_line_share_packs(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    us_plain: str = "",
    session_plain: str = "",
    db_path: Optional[str] = None,
    us_snap: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """三段 LINE：夜盤、起漲／佈局、短線說明（當沖改主選單查）。"""
    from line_hop import LINE_PACKS

    specs_layout = [
        ("leave_zero", "起漲　高低卡獲利剛離零"),
        ("golden_buy", "黃金買點　60低超跌"),
        ("revenue_cross", "優先看　營收轉強×量價"),
        ("select_01", "周帶量　短線轉強"),
        ("select_02", "站上季線　中線轉強第一天"),
        ("select_03", "止跌　月低有人接"),
    ]
    head = "\n".join(
        [
            f"WayneBot 海選　{_date_slash(target_date)}",
            session_plain or "昨收名單。量化輔助，不是立即下單。",
        ]
    )
    night = ""
    if us_snap is not None:
        try:
            from us_overnight import format_night_plain

            night = format_night_plain(us_snap)
        except Exception:
            night = ""
    if not night and us_plain:
        night = "＝＝夜盤判斷＝＝\n" + us_plain
    if not night:
        night = "＝＝夜盤判斷＝＝\n這次沒接到美股數字"

    both_bits = []
    seen_both = set()
    try:
        from screen_sessions import BUCKETS as _SCREEN_BUCKETS
    except Exception:
        _SCREEN_BUCKETS = (
            "leave_zero", "golden_buy", "revenue_cross", "select_01", "select_02",
            "select_03", "day_trade", "overnight",
        )
    for key in _SCREEN_BUCKETS:
        for it in results.get(key) or []:
            if not isinstance(it, dict):
                continue
            if not it.get("both_sessions"):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid or sid in seen_both:
                continue
            seen_both.add(sid)
            name = str(it.get("stock_name") or it.get("name") or "")
            from line_share_format import line_stock_headline

            both_bits.append(line_stock_headline(len(both_bits) + 1, sid, name, db_path))
    both = ""
    if both_bits:
        both = "＝＝雙時段＝＝　晚間台股＋今早都在\n" + "\n".join(both_bits)

    layout_parts = [_share_bucket_block(results, k, t, db_path) for k, t in specs_layout]
    layout_parts = [p for p in layout_parts if p]
    if both:
        layout_parts.insert(0, both)
    if not layout_parts:
        layout_parts = ["今日沒有起漲／佈局名單"]

    foot = "（WayneBot　量化輔助，不是立即下單）"
    bodies = {
        "night": ("\n" + SHARE_SEP + "\n").join([head, "＝＝夜盤判斷＝＝", night, foot]),
        "layout": ("\n" + SHARE_SEP + "\n").join([head, "＝＝起漲與佈局＝＝", *layout_parts, foot]),
        "trade": ("\n" + SHARE_SEP + "\n").join([head, LINE_TRADE_POINTER, foot]),
    }
    # night 已含 ＝＝夜盤判斷＝＝ 時不要重疊標題
    if night.startswith("＝＝夜盤判斷"):
        bodies["night"] = ("\n" + SHARE_SEP + "\n").join([head, night, foot])
    packs = []
    for pid, label, title in LINE_PACKS:
        packs.append(
            {
                "id": pid,
                "label": label,
                "title": title,
                "text": bodies[pid].strip(),
            }
        )
    return packs


def format_line_share_text(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    us_plain: str = "",
    session_plain: str = "",
    db_path: Optional[str] = None,
    us_snap: Optional[Dict[str, Any]] = None,
) -> str:
    """三段稿接成一則，給測試與存檔。"""
    packs = format_line_share_packs(
        results,
        target_date,
        us_plain=us_plain,
        session_plain=session_plain,
        db_path=db_path,
        us_snap=us_snap,
    )
    return ("\n" + SHARE_SEP + "\n").join(p["text"] for p in packs).strip()


# ------------------------------------------------------------------------------
# 機器人與外部呼叫總入口（徹底修復 Telegram 報錯之核心介面）
# ------------------------------------------------------------------------------
def _postprocess_screen(
    db_path: str, target_date: str, results: Dict[str, Any], apply_us: bool = True
) -> Dict[str, Any]:
    """產業輪動標籤；早上海選才套美股收盤過濾。"""
    try:
        from money_flow import annotate_screen_results

        annotate_screen_results(db_path, target_date, results)
    except Exception:
        pass
    snap: Dict[str, Any] = {}
    if not apply_us:
        return snap
    try:
        from us_overnight import apply_us_overnight, refresh_us_overnight

        snap = refresh_us_overnight(db_path, target_date) or {}
        apply_us_overnight(results, snap)
    except Exception:
        pass
    return snap


def execute_full_screening(
    db_path: str = None,
    target_date: Optional[str] = None,
    apply_us: bool = True,
    session: str = "",
) -> Dict[str, Any]:
    """
    全市場量化選股總入口函式：
    供 bot_servers.py、main_runner.py 及 Telegram 指令直接調用
    """
    engine = ScreeningEngine(db_path=db_path or get_db_path())
    if not target_date:
        target_date = engine.get_latest_trading_date()

    stock_dfs = engine.load_market_data(target_date=target_date, min_volume=1000, min_turnover_k=30000.0)

    if not stock_dfs:
        empty_packs = format_line_share_packs(
            {},
            target_date,
            session_plain="今日無通過流動性的標的。",
            db_path=engine.db_path,
        )
        empty_body = ("\n────────\n").join(p["text"] for p in empty_packs)
        try:
            from screen_sessions import save_line_packs, save_line_share

            save_line_share(engine.db_path, target_date, empty_body)
            save_line_packs(engine.db_path, target_date, empty_packs)
        except Exception:
            pass
        return {
            "status": "empty",
            "date": target_date,
            "as_of": target_date,
            "message": f"⚠️ 查無 {target_date} 之有效交易行情或無標的通過流動性檢驗（日量>=1,000張且日額>=3,000萬）。",
            "line_share": empty_body,
            "line_share_chunks": [p["text"] for p in empty_packs],
            "line_share_packs": empty_packs,
            "results": {},
            "daytrade": [],
            "overnight": [],
            "major_alerts": [],
            "revenue_cross": [],
        }

    results = engine.execute_all_strategies(stock_dfs)
    try:
        from fundamentals import hot_revenue_names
        hot_ids = {h["stock_id"] for h in hot_revenue_names(engine.db_path, limit=80)}
    except Exception:
        hot_ids = set()
    breakout = []
    for key in ("select_01", "select_02", "day_trade"):
        breakout.extend(results.get(key) or [])
    seen = set()
    revenue_cross = []
    for item in breakout:
        sid = str(item.get("stock_id") or "")
        if sid in seen or sid not in hot_ids:
            continue
        if _is_downtrend_no_touch(item):
            continue
        if int(item.get("trust_net") or 0) < 0 and int(item.get("foreign_net") or 0) < 0:
            continue
        seen.add(sid)
        revenue_cross.append(engine._row_for_bot(item))
    results["revenue_cross"] = revenue_cross
    for item in results.get("leave_zero") or []:
        if str(item.get("stock_id") or "") in hot_ids:
            item["revenue_hot"] = True
    results["leave_zero"] = results.get("leave_zero") or []
    us_snap = _postprocess_screen(engine.db_path, target_date, results, apply_us=apply_us)
    mkt_html = ""
    if session == "morning":
        try:
            from taiwan_market import analyze_taiwan_market, apply_market_weights, format_taiwan_market_brief_html

            mkt_snap = analyze_taiwan_market(engine.db_path, target_date)
            results = apply_market_weights(results, mkt_snap, db_path=engine.db_path)
            mkt_html = format_taiwan_market_brief_html(engine.db_path, target_date)
        except Exception:
            mkt_html = ""
    us_plain = ""
    session_plain = ""
    if session == "evening":
        session_plain = "晚間台股收盤（尚未對美股）"
    elif session == "morning":
        session_plain = "今早 06:30（已對美股收盤／盤後）"
    if apply_us:
        try:
            from us_overnight import format_us_plain

            us_plain = format_us_plain(us_snap)
        except Exception:
            pass

    if session in ("evening", "morning"):
        try:
            from screen_sessions import mark_both_sessions, overlap_ids, save_screen_session

            save_screen_session(engine.db_path, target_date, session, results)
            if session == "morning":
                both = overlap_ids(engine.db_path, target_date)
                mark_both_sessions(results, both)
        except Exception:
            pass

    if session == "morning" or not session:
        try:
            from screen_review import save_screen_picks

            save_screen_picks(engine.db_path, target_date, results)
        except Exception:
            pass

    payload = format_screening_payload(results, target_date)
    report_parts = []
    if mkt_html:
        report_parts.append(mkt_html)
    report_parts.extend(p["html"] for p in payload)
    report_text = "\n\n".join(report_parts)
    daytrade = [engine._row_for_bot(x) for x in results.get("day_trade") or []]
    overnight = [engine._row_for_bot(x) for x in results.get("overnight") or []]
    major_alerts = []
    for item in (results.get("select_02") or [])[:8]:
        if int(item.get("trust_net") or 0) < -200 or int(item.get("foreign_net") or 0) < -800:
            major_alerts.append({
                "code": item.get("stock_id"),
                "name": item.get("stock_name"),
                "reason": "突破後法人轉賣超",
            })

    line_packs = format_line_share_packs(
        results,
        target_date,
        us_plain=us_plain,
        session_plain=session_plain,
        db_path=engine.db_path,
        us_snap=us_snap if apply_us else None,
    )
    line_body = ("\n────────\n").join(p["text"] for p in line_packs)
    try:
        from screen_sessions import save_line_packs, save_line_share, save_line_stocks

        save_line_share(engine.db_path, target_date, line_body)
        bucket_packs = build_line_bucket_packs(results, target_date, engine.db_path)
        save_line_packs(engine.db_path, target_date, line_packs + bucket_packs)
        save_line_stocks(
            engine.db_path,
            target_date,
            build_line_stock_bodies(results, target_date, engine.db_path),
        )
    except Exception:
        pass

    return {
        "status": "success",
        "date": target_date,
        "as_of": target_date,
        "total_scanned": len(stock_dfs),
        "results": results,
        "message": report_text,
        "payload": payload,
        "sections": [p["html"] for p in payload],
        "daytrade": daytrade,
        "overnight": overnight,
        "major_alerts": major_alerts,
        "line_share": line_body,
        "line_share_chunks": [p["text"] for p in line_packs],
        "line_share_packs": line_packs,
    }


# 舊程式用 screening_engine.run_full_screening，維持這個模組屬性。
run_full_screening = execute_full_screening


# ------------------------------------------------------------------------------
# 單元測試入口（可直接在 Colab / 本機獨立執行驗證）
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 正在執行 screening_engine.py 獨立單元測試...")
    print("=" * 70)

    # 檢查是否存在資料庫
    test_db = "waynebot_history.db"
    if not os.path.exists(test_db):
        print(f"⚠️ 找不到 {test_db}，請確保歷史資料庫存在於同目錄。")
    else:
        output = run_full_screening(db_path=test_db)
        print(f"✅ 狀態: {output.get('status')}")
        print(f"📅 最新交易日: {output.get('date')}")
        print(f"📊 通過流動性篩選總檔數: {output.get('total_scanned')} 檔")
        print("\n" + "=" * 70)
        print("📱 產出之 Telegram 戰報預覽：")
        print("=" * 70)
        print(output.get("message"))
