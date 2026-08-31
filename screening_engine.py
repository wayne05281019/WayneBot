# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組二 - 即時選股與價位精算核心
# 檔案路徑：screening_engine.py
# 核心功能：
#   1. CaryBot 四大即時選股（周帶量突破、突破Hi120、突破Hi480、雙綠脫離）
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
        """海選基準日：優先取上市＋上櫃都齊的最近交易日，避免停在上櫃 0 的半套日。"""
        try:
            from import_health import latest_complete_quote_date

            complete = latest_complete_quote_date(self.db_path)
            if complete:
                return complete
        except Exception:
            pass
        with self._get_connection() as conn:
            cursor = conn.cursor()
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

        # 1. 篩選當日符合流動性門檻的標的清單
        query_candidates = f"""
        SELECT stock_id, stock_name, market, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes 
        WHERE date = '{target_date}'
          AND volume >= {min_volume}
          AND turnover_k >= {min_turnover_k}
          AND close > 0;
        """
        df_candidates = pd.read_sql_query(query_candidates, conn)
        valid_sids = df_candidates['stock_id'].tolist()

        if not valid_sids:
            conn.close()
            return {}

        # 2. 批次載入這些標的的歷史 K 線數據（取最近 500 個交易日）
        placeholders = ','.join([f"'{s}'" for s in valid_sids])
        query_history = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id IN ({placeholders})
          AND date <= '{target_date}'
        ORDER BY stock_id, date ASC;
        """
        df_all = pd.read_sql_query(query_history, conn)
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

        # 均線計算
        ma5 = close_series.rolling(5).mean().iloc[-1]
        ma5_prev = close_series.rolling(5).mean().iloc[-2] if len(df) >= 6 else ma5
        ma20 = close_series.rolling(20).mean().iloc[-1] if len(df) >= 20 else ma5
        ma60 = close_series.rolling(60).mean().iloc[-1] if len(df) >= 60 else ma20
        
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
            "ma60": round(ma60, 2),
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
        res_sel_04 = []
        res_day_trade = []
        res_overnight = []
        res_leave_zero = []

        for sid, df in stock_dfs.items():
            info = self.calculate_indicators(df)
            if not info:
                continue

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
            avg_p = info["avg_price"]

            # ------------------------------------------------------------------
            # CaryBot Select 01: 周帶量突破 (5日高 + Q60R > 2.0)
            # ------------------------------------------------------------------
            if hi5 and c >= hi5 and q >= 2.0 and pct > 0.5:
                res_sel_01.append(info)

            # ------------------------------------------------------------------
            # CaryBot Select 02: 突破Hi120 (半年新高 + Q60R > 2.5)
            # ------------------------------------------------------------------
            if hi120 and c >= hi120 and q >= 2.5 and pct > 1.0:
                res_sel_02.append(info)

            # ------------------------------------------------------------------
            # CaryBot Select 03: 突破Hi480 (兩年新高大底 + Q60R > 3.0)
            # ------------------------------------------------------------------
            if hi480 and c >= hi480 and q >= 3.0 and pct > 1.5:
                res_sel_03.append(info)

            # ------------------------------------------------------------------
            # CaryBot Select 04: 雙綠脫離 (D20由底轉正脫離 + 60日破底消失)
            # ------------------------------------------------------------------
            if prev_d20 <= 1.0 and d20 >= 2.0 and c > info["low60"] * 1.03 and pct > 1.0:
                res_sel_04.append(info)

            # 獲利脫離零：昨收仍貼近近60曆日低（獲利≈0），今日轉正；
            # 再要求量能放大或 20 低脫離，對齊「剛起漲＋大量／底圖」較穩的買點。
            dts = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
            if len(df) >= 5 and dts.notna().sum() >= 5:
                def _cal60(i: int) -> float:
                    end = dts.iloc[i]
                    m = (dts >= (end - pd.Timedelta(days=60))) & (dts <= end)
                    return float(df.loc[m, "close"].min() or 0)

                lo_y, lo_t = _cal60(-2), _cal60(-1)
                py = ((float(info["prev_close"]) - lo_y) / lo_y * 100.0) if lo_y > 0 else 99.0
                pt = ((float(c) - lo_t) / lo_t * 100.0) if lo_t > 0 else 0.0
                vols = df["volume"].to_numpy(dtype=float)
                last_v = float(vols[-1])
                window = vols[-120:] if len(vols) >= 120 else vols
                rank = int(int((window > last_v).sum()) + 1)
                leave_l20 = prev_d20 <= 2.0 and d20 >= 2.0
                vol_hot = leave_l20 or rank <= 20 or q >= 2.0
                just_left = py <= 2.0 and pt >= 0.4 and pt <= 12.0 and pt > py + 0.25
                sid_s = str(info.get("stock_id") or "")
                if just_left and vol_hot and len(sid_s) == 4 and sid_s.isdigit():
                    item = dict(info)
                    item["profit"] = round(pt, 1)
                    item["vol_rank_120"] = rank
                    item["leave_l20"] = leave_l20
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
        res_sel_04.sort(key=sort_key, reverse=True)
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

        return {
            "select_01": res_sel_01,
            "select_02": res_sel_02,
            "select_03": res_sel_03,
            "select_04": res_sel_04,
            "leave_zero": res_leave_zero,
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

    def screen_daytrade(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        target_date = target_date or self.get_latest_trading_date()
        dfs = self.load_market_data(target_date=target_date)
        if not dfs:
            return []
        results = self.execute_all_strategies(dfs)
        _postprocess_screen(self.db_path, target_date, results)
        return [self._row_for_bot(x) for x in results.get("day_trade") or []]

    def screen_overnight(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        target_date = target_date or self.get_latest_trading_date()
        dfs = self.load_market_data(target_date=target_date)
        if not dfs:
            return []
        results = self.execute_all_strategies(dfs)
        _postprocess_screen(self.db_path, target_date, results)
        return [self._row_for_bot(x) for x in results.get("overnight") or []]

    def run_full_screening(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        return execute_full_screening(self.db_path, target_date)


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


def _pct_str(pct) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return ""
    return f"+{p:.2f}%" if p > 0 else f"{p:.2f}%"


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


def _stock_card_html(item: Dict[str, Any], idx: int) -> str:
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
    if item.get("chase_warning"):
        notices.append(_hot("少追") + html_escape("＝靠近20日收盤高"))
    if item.get("is_s_tier"):
        notices.append(_hot("S級") + html_escape("＝投信連買＋5MA向上"))
    if item.get("leave_l20"):
        notices.append(_hot("20低脫離"))
    if item.get("revenue_hot"):
        notices.append(_hot("營收轉強"))
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
        f"<b>{idx}.</b> {title}",
        f"格局　{regime}",
        f"收盤　{close_s}　漲跌　{_pct_html(item.get('pct_change'))}",
        f"量　　{vol:,}張　量比　{_q_html(item.get('q60r'))}" + (f"　額　{html_escape(to_s)}" if to_s else ""),
        f"均線　月{_px_str(item.get('ma20'))}　季{_px_str(item.get('ma60'))}",
        f"法人　{html_escape(_chip_plain(item))}",
    ]
    if notices:
        body.append("注意　" + "　".join(notices))
    if item.get("profit") is not None:
        body.append(f"獲利　{html_escape(item.get('profit'))}%（近60曆日低點上來）")
    if item.get("vol_rank_120"):
        rank = int(item["vol_rank_120"])
        rank_s = f"第{rank}名"
        body.append("120量　" + (_hot(rank_s) if rank <= 20 else html_escape(rank_s)))
    plan = _safety_plan_html(item)
    if plan:
        body.extend(plan)
    return f"<blockquote>{chr(10).join(body)}</blockquote>"


def _compact_line(item: Dict[str, Any]) -> str:
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
    return (
        f"{html_escape(sid)} {html_escape(sname)}　"
        f"{html_escape(_regime_label(item))}　收{_px_str(item.get('close'))}　{pct}　"
        f"量{int(item.get('volume') or 0):,}張　{html_escape(q_s)}{extra}{plan}"
    )


def format_screening_payload(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    us_html: str = "",
) -> List[Dict[str, Any]]:
    """每個分類一則訊息；標題由左邊小動圖 + 分類名的貼紙呈現。"""
    payload: List[Dict[str, Any]] = []
    specs = [
        ("revenue_cross", "📈", "優先看", "營收轉強 × 量價突破", 8, False),
        ("leave_zero", "🌱", "起漲", "獲利脫離零 × 量能／20低脫離", 8, True),
        ("select_01", "🔥", "Select 01", "周帶量突破", 8, True),
        ("select_02", "🏆", "Select 02", "突破半年高 Hi120", 8, True),
        ("select_03", "💎", "Select 03", "突破兩年高 Hi480", 8, True),
        ("select_04", "🌱", "Select 04", "雙綠脫離底部起漲", 8, True),
        ("day_trade", "⚡", "當沖", "保險進場／第一停利＋3%／衝頂＋6%／均價停損", 10, True),
        ("overnight", "🌙", "隔日沖", "尾盤保險買進區間、明早開高、跌破防守先走", 10, True),
    ]
    first = True
    us_regime = results.get("_us_regime") if isinstance(results, dict) else ""
    for key, emoji, label, subtitle, cap, skip_empty in specs:
        items = results.get(key) or []
        if skip_empty and not items:
            if key in ("day_trade", "overnight") and us_regime == "risk_off":
                pass
            else:
                continue
        head = f"{html_escape(subtitle)}　共 {len(items)} 檔"
        if first:
            bits = [
                f"<b>WayneBot 海選</b>　昨收 {html_escape(target_date)}",
                "<i>給家人轉貼用。價位是保險參考，不是保證獲利。</i>",
            ]
            if us_html:
                bits.append(us_html)
            head = "\n".join(bits) + "\n" + head
            first = False
        part: Dict[str, Any] = {
            "mark_key": key,
            "mark_label": f"{label} · {len(items)}檔",
            "mark_hint": subtitle,
        }
        if not items:
            if key in ("day_trade", "overnight") and us_regime == "risk_off":
                part["html"] = head + "\n<i>隔夜逆風：當沖／隔日沖今日不列（VIX 或美股四大／費半過弱）。</i>"
            else:
                part["html"] = head + "\n<i>今日無符合條件標的</i>"
            payload.append(part)
            continue
        detail_n = min(cap, len(items))
        cards = [_stock_card_html(it, n + 1) for n, it in enumerate(items[:detail_n])]
        body = head + "\n" + "\n".join(cards)
        rest = items[detail_n:]
        if rest:
            shown = rest[:12]
            compact = "\n".join(_compact_line(it) for it in shown)
            more = f"\n…另 {len(rest) - len(shown)} 檔（完整請打「海選」看分類）" if len(rest) > len(shown) else ""
            body += f"\n<b>其餘 {len(rest)} 檔（同樣有價位，不必點開）</b>\n{compact}{html_escape(more)}"
        part["html"] = body
        part["picks"] = [
            (
                str(it.get("stock_id") or it.get("code") or ""),
                str(it.get("stock_name") or it.get("name") or ""),
            )
            for it in items[:detail_n]
            if it.get("stock_id") or it.get("code")
        ]
        payload.append(part)

    if payload:
        payload[-1]["html"] += (
            "\n💡 <i>藍字股名＝奇摩。按鈕由上到下對應名單（看這檔／➕）。"
            "保險進場／停利／停損已寫在排名裡；該注意的漲跌、少追、S級、20低脫離、營收轉強、輪動進、隔夜逆風用<b>粗體</b>。"
            "量化僅供輔助，進場請設移動停損。</i>"
        )
    else:
        payload.append({"html": f"<b>WayneBot 海選</b>　昨收 {html_escape(target_date)}\n<i>今日無符合條件標的</i>"})
    return payload


def format_screening_sections(results: Dict[str, List[Dict[str, Any]]], target_date: str) -> List[str]:
    return [p["html"] for p in format_screening_payload(results, target_date)]


def format_line_share_text(
    results: Dict[str, List[Dict[str, Any]]],
    target_date: str,
    us_plain: str = "",
) -> str:
    """一則純文字，方便複製／轉貼 LINE（不含 HTML）。"""
    specs = [
        ("revenue_cross", "優先看　營收轉強×量價"),
        ("leave_zero", "起漲　獲利脫離零×量能"),
        ("select_01", "Select01　周帶量突破"),
        ("select_02", "Select02　突破半年高"),
        ("select_03", "Select03　突破兩年高"),
        ("select_04", "Select04　雙綠脫離"),
        ("day_trade", "當沖"),
        ("overnight", "隔日沖"),
    ]

    def one(it: Dict[str, Any]) -> str:
        sid = str(it.get("stock_id") or it.get("code") or "")
        sname = str(it.get("stock_name") or it.get("name") or "")
        q = it.get("q60r")
        try:
            q_s = f"{float(q):.1f}×" if q is not None else ""
        except (TypeError, ValueError):
            q_s = ""
        s = " S級" if it.get("is_s_tier") else ""
        head = (
            f"{sid} {sname} {_regime_label(it)} 收{_px_str(it.get('close'))} "
            f"{_pct_str(it.get('pct_change'))} 量{int(it.get('volume') or 0):,}張 {q_s}{s}"
        ).strip()
        plan = _safety_plan_plain(it)
        if plan:
            return head + "\n  " + "\n  ".join(plan)
        chips = _chip_plain(it)
        if any(int(it.get(k) or 0) for k in ("foreign_net", "trust_net", "dealer_net")):
            return f"{head}\n  {chips}"
        return head

    lines = [
        f"WayneBot 海選 {target_date}（昨收，早上寄出給家人）",
        "量化輔助，不是立即下單。當沖請看保險進場／第一停利／衝頂／均價停損。",
    ]
    if us_plain:
        lines.append(us_plain)
    lines.append("")
    for key, title in specs:
        items = results.get(key) or []
        lines.append(f"【{title}】{len(items)}檔")
        if not items:
            continue
        cap = 8 if key in ("day_trade", "overnight") else 12
        for it in items[:cap]:
            lines.append(one(it))
        if len(items) > cap:
            lines.append(f"…另 {len(items) - cap} 檔（完整請看 Telegram）")
        lines.append("")
    lines.append("（WayneBot）")
    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3880].rstrip() + "\n…（已截短，完整名單看 Telegram）"
    return text


# ------------------------------------------------------------------------------
# 機器人與外部呼叫總入口（徹底修復 Telegram 報錯之核心介面）
# ------------------------------------------------------------------------------
def _postprocess_screen(db_path: str, target_date: str, results: Dict[str, Any]) -> Dict[str, Any]:
    """產業輪動標籤＋隔夜美股過濾。美股抓不到就不過濾。"""
    try:
        from money_flow import annotate_items_with_sector_flow

        for lst in results.values():
            if isinstance(lst, list):
                annotate_items_with_sector_flow(db_path, target_date, lst)
    except Exception:
        pass
    snap: Dict[str, Any] = {}
    try:
        from us_overnight import apply_us_overnight, refresh_us_overnight

        snap = refresh_us_overnight(db_path, target_date) or {}
        apply_us_overnight(results, snap)
    except Exception:
        pass
    return snap


def execute_full_screening(db_path: str = None, target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    全市場量化選股總入口函式：
    供 bot_servers.py、main_runner.py 及 Telegram 指令直接調用
    """
    engine = ScreeningEngine(db_path=db_path or get_db_path())
    if not target_date:
        target_date = engine.get_latest_trading_date()

    stock_dfs = engine.load_market_data(target_date=target_date, min_volume=1000, min_turnover_k=30000.0)

    if not stock_dfs:
        return {
            "status": "empty",
            "date": target_date,
            "as_of": target_date,
            "message": f"⚠️ 查無 {target_date} 之有效交易行情或無標的通過流動性檢驗（日量>=1,000張且日額>=3,000萬）。",
            "line_share": f"WayneBot 海選 {target_date}\n今日無通過流動性的標的。",
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
        if int(item.get("trust_net") or 0) < 0 and int(item.get("foreign_net") or 0) < 0:
            continue
        seen.add(sid)
        revenue_cross.append(engine._row_for_bot(item))
    results["revenue_cross"] = revenue_cross
    for item in results.get("leave_zero") or []:
        if str(item.get("stock_id") or "") in hot_ids:
            item["revenue_hot"] = True
    results["leave_zero"] = results.get("leave_zero") or []
    us_snap = _postprocess_screen(engine.db_path, target_date, results)
    us_html = ""
    us_plain = ""
    try:
        from us_overnight import format_us_html, format_us_plain

        us_html = format_us_html(us_snap)
        us_plain = format_us_plain(us_snap)
    except Exception:
        pass

    try:
        from screen_review import save_screen_picks

        save_screen_picks(engine.db_path, target_date, results)
    except Exception:
        pass

    payload = format_screening_payload(results, target_date, us_html=us_html)
    report_text = "\n\n".join(p["html"] for p in payload)
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
        "line_share": format_line_share_text(results, target_date, us_plain=us_plain),
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
