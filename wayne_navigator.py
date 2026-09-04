# -*- coding: utf-8 -*-
"""
WayneBot 核心模組：買低賣高決策卡與 180 日 K 線趨勢圖引擎
檔案名稱：wayne_navigator.py
"""

import os
import sqlite3
import urllib.request
from datetime import datetime
from typing import Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as patches
import matplotlib.font_manager as fm
import matplotlib.colors as mcolors
import matplotlib.patheffects as patheffects
from matplotlib.lines import Line2D
from contextlib import contextmanager
from functools import lru_cache, wraps
from threading import Lock
import pandas as pd
import numpy as np

# FT2Font 是共用物件，量字寬要改 size／text，併發產圖時得排隊。
_FT_LOCK = Lock()
# pyplot 全域狀態非 thread-safe；四圖並行會畫出空白／殘缺檔（標題在、K 線不見）。
_MPL_RENDER_LOCK = Lock()


@contextmanager
def mpl_render():
    _MPL_RENDER_LOCK.acquire()
    try:
        yield
    finally:
        _MPL_RENDER_LOCK.release()


def _mpl_serial(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with mpl_render():
            return fn(*args, **kwargs)

    return wrapped
_FT_FONTS = {}
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLE_FONTS = os.path.join(_MODULE_DIR, "fonts")

try:
    from config import get_charts_dir, get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

    def get_charts_dir():
        return os.getenv("WAYNE_CHARTS_DIR") or os.path.join("data", "charts")

BASE_DIR = os.path.dirname(get_db_path()) or "."
DB_PATH = get_db_path()
OUTPUT_DIR = get_charts_dir()
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 靜態字重打進 fonts/，Render 開機不必再壓可變字型（那一步會讓第一檔查詢空等一兩分鐘）。
_WEIGHT_TEXT, _WEIGHT_BOLD = 560, 860
_WEIGHT_FILES = {}


def bundled_weight_path(step: int) -> str:
    return os.path.join(_BUNDLE_FONTS, f"NotoSansTC-w{int(step)}.ttf")


def _pick_font_path() -> str:
    for cand in (
        bundled_weight_path(_WEIGHT_TEXT),
        os.path.join(BASE_DIR, "NotoSansTC-Regular.otf"),
        os.path.join(_MODULE_DIR, "NotoSansTC-Regular.otf"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return os.path.join(BASE_DIR, "NotoSansTC-Regular.otf")


FONT_PATH = _pick_font_path()
if not os.path.exists(FONT_PATH):
    try:
        FONT_URL = "https://github.com/google/fonts/raw/main/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf"
        with urllib.request.urlopen(FONT_URL, timeout=15) as resp:
            with open(FONT_PATH, "wb") as out:
                out.write(resp.read())
        fm.fontManager.addfont(FONT_PATH)
        plt.rcParams['font.sans-serif'] = ['Noto Sans TC', 'DejaVu Sans', 'Arial']
    except Exception:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
else:
    try:
        fm.fontManager.addfont(FONT_PATH)
    except Exception:
        pass
    plt.rcParams['font.sans-serif'] = ['Noto Sans TC', 'DejaVu Sans', 'Arial']

plt.rcParams['axes.unicode_minus'] = False


def _weight_step(weight) -> int:
    return _WEIGHT_BOLD if int(weight) >= 750 else _WEIGHT_TEXT


def _weight_font_path(weight: int) -> str:
    step = _weight_step(weight)
    cached = _WEIGHT_FILES.get(step)
    if cached is not None:
        return cached
    bundled = bundled_weight_path(step)
    if os.path.exists(bundled):
        out = bundled
    else:
        out = os.path.join(BASE_DIR, f"NotoSansTC-w{step}.ttf")
        if not os.path.exists(out):
            try:
                from fontTools.ttLib import TTFont
                from fontTools.varLib import instancer

                src = TTFont(FONT_PATH)
                if "fvar" not in src:
                    _WEIGHT_FILES[step] = FONT_PATH
                    return FONT_PATH
                inst = instancer.instantiateVariableFont(src, {"wght": step}, inplace=False)
                inst["OS/2"].usWeightClass = step
                tmp = f"{out}.{os.getpid()}.tmp"
                inst.save(tmp)
                os.replace(tmp, out)
            except Exception:
                _WEIGHT_FILES[step] = FONT_PATH if os.path.exists(FONT_PATH) else ""
                return _WEIGHT_FILES[step]
    try:
        fm.fontManager.addfont(out)
    except Exception:
        pass
    _WEIGHT_FILES[step] = out
    return out


def _ft_font(weight: int):
    path = _weight_font_path(weight)
    font = _FT_FONTS.get(path)
    if font is None:
        font = fm.get_font(path)
        _FT_FONTS[path] = font
    return font


_FONTS_WARMED = False


def prewarm_card_fonts() -> None:
    """開機載入打包好的兩個靜態字重，避免第一檔查詢才去壓字型。"""
    global _FONTS_WARMED
    if _FONTS_WARMED:
        return
    _weight_font_path(_WEIGHT_TEXT)
    _weight_font_path(_WEIGHT_BOLD)
    with _FT_LOCK:
        _ft_font(_WEIGHT_TEXT)
        _ft_font(_WEIGHT_BOLD)
    _FONTS_WARMED = True


def normalize_ohlc(df: pd.DataFrame, db_path: str = None) -> tuple:
    """除權／錯價還原。回傳 (df, notes)。

    優先用官方除權息表（ex_rights：參考價／前收盤）。沒公告的減資／分割仍用跳空啟發式。
    單日 10 倍跳動多半是匯入錯價。無量且開高低收同一價的假 K 不參與滾動高低。
    """
    if df is None or df.empty:
        return df, []
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    else:
        out["volume"] = 0.0
    notes = []
    n = len(out)
    if n < 3:
        out["is_halt"] = False
        return out, notes

    official = set()
    sid = ""
    if "stock_id" in out.columns and len(out):
        sid = str(out["stock_id"].iloc[-1] or "")
    dates = out["date"].astype(str).str.replace("-", "", regex=False)
    if sid:
        try:
            from ex_rights import load_ex_rights

            for ev in load_ex_rights(sid, db_path):
                ex = str(ev.get("ex_date") or "")
                factor = float(ev.get("factor") or 0)
                if len(ex) != 8 or not (0.05 <= factor <= 20):
                    continue
                mask = dates < ex
                if not bool(mask.any()):
                    continue
                out.loc[mask, ["open", "high", "low", "close"]] = (
                    out.loc[mask, ["open", "high", "low", "close"]] * factor
                )
                official.add(ex)
                notes.append(f"官方除權息 {ex} ×{factor:.4f}")
            dates = out["date"].astype(str).str.replace("-", "", regex=False)
        except Exception:
            official = set()

    def _scale_row(i, factor):
        for col in ("open", "high", "low", "close"):
            if col in out.columns and pd.notna(out.at[out.index[i], col]):
                out.at[out.index[i], col] = float(out.at[out.index[i], col]) * factor

    # 1) 單日 8～12 倍錯價（前後都在正常尺度）
    for i in range(1, n - 1):
        p, c, nxt = float(out["close"].iloc[i - 1] or 0), float(out["close"].iloc[i] or 0), float(out["close"].iloc[i + 1] or 0)
        if p <= 0 or c <= 0 or nxt <= 0:
            continue
        if c / p >= 8 and nxt / c <= 0.15:
            factor = ((p + nxt) / 2.0) / c
            _scale_row(i, factor)
            notes.append(f"修正 {out['date'].iloc[i]} 錯價×{1/factor:.0f}")
        elif c / p <= 0.15 and nxt / c >= 8:
            factor = ((p + nxt) / 2.0) / c
            _scale_row(i, factor)
            notes.append(f"修正 {out['date'].iloc[i]} 錯價")

    # 2) 持續跳空＝除權／減資／分割：當天整根離開前收，之後不再跳回
    for i in range(1, n):
        day = str(dates.iloc[i] if i < len(dates) else "").replace("-", "")
        if day in official:
            continue
        p = float(out["close"].iloc[i - 1] or 0)
        c = float(out["close"].iloc[i] or 0)
        hi = float(out["high"].iloc[i] or 0)
        lo = float(out["low"].iloc[i] or 0)
        vol_p = float(out["volume"].iloc[i - 1] or 0)
        vol_c = float(out["volume"].iloc[i] or 0)
        if p <= 0 or c <= 0:
            continue
        r = c / p
        down = r < 0.82 and hi < p * 0.86 and hi > 0
        up = r > 1.38 and lo > p * 1.22
        mild_down = 0.72 <= r < 0.88 and hi < p * 0.92
        mild_up = 1.15 <= r <= 1.65 and lo > p * 1.08
        if not (down or up or mild_down or mild_up):
            continue
        factor = c / p
        if not (0.05 <= factor <= 20):
            continue
        # 量縮／量增與價格跳動同向時，較像分割或減資
        if vol_p > 0 and vol_c > 0:
            vr = vol_c / vol_p
            if factor > 1.1 and vr < 0.75:
                factor = round(factor)
            elif factor < 0.95 and vr > 1.25:
                inv = 1.0 / factor if factor > 0 else 1.0
                if abs(vr - inv) / max(inv, 1.0) < 0.45:
                    factor = round(factor, 2)
        idx = out.index[:i]
        out.loc[idx, ["open", "high", "low", "close"]] = out.loc[idx, ["open", "high", "low", "close"]] * factor
        tag = "分割" if factor > 1.05 else "減資" if factor < 0.95 else "除權"
        notes.append(f"{tag}還原 {out['date'].iloc[i]} ×{factor:.4f}")
        if sid and db_path:
            try:
                from ex_rights import upsert_heuristic_event

                upsert_heuristic_event(db_path, sid, day, factor, kind=tag)
                official.add(day)
            except Exception:
                pass

    flat = (out["volume"] <= 0) & ((out["high"] - out["low"]).abs() <= 1e-8)
    out["is_halt"] = flat.fillna(False)
    if int(out["is_halt"].sum()) >= 2:
        notes.append(f"略過 {int(out['is_halt'].sum())} 根無量假K")
    return out, notes


def pink_warning_note(card: dict) -> str:
    """粉紅預警＝從最新一根往回連續 K20高的天數（滿 2 日才提紀律賣出，數字用實際連幾日）。"""
    n = int(card.get("k20_high_streak") or 0)
    if n <= 0:
        table = card.get("table")
        if table is not None and hasattr(table, "empty") and not table.empty:
            for a in table["預警"].tolist():
                if str(a) == "K20高":
                    n += 1
                else:
                    break
    if n >= 2:
        return f"粉紅預警已連 {n} 日 → 紀律考慮賣出"
    if n == 1:
        return "粉紅預警第 1 日"
    return ""


class NavigatorEngine:
    """WayneBot 買低賣高決策卡、多空溫度計與雙綠脫離海選引擎"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    @staticmethod
    def _calc_rolling_rank(
        series: pd.Series,
        window: int = 120,
        closes: pd.Series | None = None,
        turnovers: pd.Series | None = None,
    ) -> list:
        from decision_card_signals import calc_volume_rank

        vals = series.tolist()
        cls = closes.tolist() if closes is not None else None
        tns = turnovers.tolist() if turnovers is not None else None
        ranks = []
        for i in range(len(vals)):
            start = max(0, i - window + 1)
            sub_v = vals[start : i + 1]
            sub_c = cls[start : i + 1] if cls else None
            sub_t = tns[start : i + 1] if tns else None
            ranks.append(calc_volume_rank(sub_v, window, closes=sub_c, turnovers=sub_t))
        return ranks

    def get_decision_card(
        self,
        stock_id: str,
        lookback: int = 20,
        merge_live: bool = True,
        live_quote: Optional[dict] = None,
    ) -> dict:
        """產出單一標的的買低賣高決策卡。庫內只用到最後完整收盤日；盤中今日 K 僅 MIS 合併、不寫庫。"""
        from quote_integrity import db_as_of_trading_date

        db_as_of = db_as_of_trading_date(self.db_path)
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("""
            SELECT date, stock_name, open, high, low, close, volume, turnover_k, pct_change as change_pct
            FROM daily_quotes
            WHERE stock_id = ?
            ORDER BY date DESC LIMIT 520;
        """, conn, params=(stock_id,))
        conn.close()

        if len(df) < 5:
            return {"error": f"標的 {stock_id} 歷史資料不足"}

        df = df.iloc[::-1].reset_index(drop=True)
        if db_as_of:
            dnorm = df["date"].astype(str).str.replace("-", "", regex=False)
            df = df[dnorm <= str(db_as_of)].reset_index(drop=True)
        if len(df) < 5:
            return {"error": f"標的 {stock_id} 歷史資料不足"}

        df["stock_id"] = str(stock_id)
        try:
            from live_quote import append_live_bar

            df = append_live_bar(
                df, str(stock_id), merge_live=merge_live, live_quote=live_quote
            )
        except Exception:
            pass
        close_raw = df["close"].astype(float).copy()
        live_time = ""
        is_live = False
        if "is_live" in df.columns and bool(df["is_live"].iloc[-1]):
            is_live = True
            live_time = str(df["_live_time"].iloc[-1] or "") if "_live_time" in df.columns else ""
        df, xq_notes = normalize_ohlc(df, self.db_path)
        close_s = df["close"].where(~df["is_halt"])
        df["ma20"] = close_s.rolling(20, min_periods=1).mean()
        df["ma60"] = close_s.rolling(60, min_periods=1).mean()
        from decision_card_signals import (
            TEMP_ATH_WATCH,
            cal60_low_close_at,
            card_daily_stance,
            card_regime_label,
            compute_card_temperature,
            profit_floor_at,
            profit_pct_cal60_series,
            resolve_daily_change_pct,
            taipei_now,
            format_card_query_stamp,
            volume_headline_rank,
        )
        generated_at = taipei_now().strftime("%Y-%m-%d %H:%M:%S")

        # 獲利：決策卡／顯示一律 60 曆日低（對齊 CaryBot）；貼 20 日低不歸零。
        profit_src = df.copy()
        profit_src["close"] = close_raw.reindex(df.index).astype(float)
        df["profit_pct"] = profit_pct_cal60_series(profit_src)
        cal60_low = cal60_low_close_at(profit_src, -1)
        profit_floor = profit_floor_at(profit_src, -1)
        # 高低點窗口：用除權前收盤（CaryBot 60日高 4560 等），均線仍用還原價。
        hl_src = close_raw.where(~df["is_halt"]) if "is_halt" in df.columns else close_raw
        df["high_5"] = hl_src.rolling(5, min_periods=1).max()
        df["low_5"] = hl_src.rolling(5, min_periods=1).min()
        df["high_10"] = hl_src.rolling(10, min_periods=1).max()
        df["low_10"] = hl_src.rolling(10, min_periods=1).min()
        df["high_20"] = hl_src.rolling(20, min_periods=1).max()
        df["low_20"] = hl_src.rolling(20, min_periods=1).min()
        df["high_60"] = hl_src.rolling(60, min_periods=1).max()
        df["low_60"] = hl_src.rolling(60, min_periods=1).min()
        df["low_120"] = hl_src.rolling(120, min_periods=20).min()
        df["low_240"] = hl_src.rolling(240, min_periods=40).min()
        df["low_480"] = hl_src.rolling(480, min_periods=80).min()
        df["high_120"] = hl_src.rolling(120, min_periods=20).max()
        df["high_240"] = hl_src.rolling(240, min_periods=40).max()
        df["high_480"] = hl_src.rolling(480, min_periods=80).max()
        df["bias_monthly"] = (((df["close"] - df["ma20"]) / df["ma20"]) * 100.0).round(1)
        df["vol_rank_120"] = self._calc_rolling_rank(
            df["volume"], window=120, closes=close_s,
            turnovers=df["turnover_k"] if "turnover_k" in df.columns else None,
        )
        df["vol_rank_480"] = self._calc_rolling_rank(
            df["volume"], window=480, closes=close_s,
            turnovers=df["turnover_k"] if "turnover_k" in df.columns else None,
        )
        df["vol_rank_60"] = self._calc_rolling_rank(
            df["volume"], window=60, closes=close_s,
            turnovers=df["turnover_k"] if "turnover_k" in df.columns else None,
        )

        hl_tags, alert_tags, temp_nums = [], [], []
        for i in range(len(df)):
            if bool(df["is_halt"].iloc[i]):
                hl_tags.append("No")
                alert_tags.append("No")
                temp_nums.append(0.0)
                continue
            c = float(close_raw.iloc[i])
            h20, l20 = float(df["high_20"].iloc[i]), float(df["low_20"].iloc[i])
            h10, l10 = float(df["high_10"].iloc[i]), float(df["low_10"].iloc[i])
            h5, l5 = float(df["high_5"].iloc[i]), float(df["low_5"].iloc[i])
            l60 = float(df["low_60"].iloc[i])
            h60_i = float(df["high_60"].iloc[i])
            bias = float(df["bias_monthly"].iloc[i])
            t = compute_card_temperature(c, h20, l20, bias, high60=h60_i, low60=l60)
            temp_nums.append(t)
            if c >= h20 * 0.998:
                hl_tags.append("20高")
            elif c >= h10 * 0.998:
                hl_tags.append("10高")
            elif c >= h5 * 0.998:
                hl_tags.append("5高")
            elif c <= l20 * 1.002:
                hl_tags.append("20低")
            elif c <= l10 * 1.002:
                hl_tags.append("10低")
            elif c <= l5 * 1.002:
                hl_tags.append("5低")
            else:
                hl_tags.append("No")
            if c <= l60 * 1.005:
                alert_tags.append("60低")
            else:
                from decision_card_signals import alert_tag

                hh, ll = h20, l20
                rsv_i = ((c - ll) / (hh - ll) * 100.0) if hh > ll else 50.0
                alert_tags.append(
                    alert_tag(
                        c,
                        low60=l60,
                        high20=h20,
                        low20=l20,
                        bias_monthly=bias,
                        rsv=rsv_i,
                    )
                )

        temps = [f"{x:.1f} °C" if x > 0 else "—" for x in temp_nums]
        trend_labels, trend_notes = compute_temp_trend_labels(
            temp_nums, closes=[float(x) for x in df["close"].tolist()]
        )
        df["獲利"] = [f"{p:.1f}%" if pd.notna(p) else "—" for p in df["profit_pct"]]
        df["高低"] = hl_tags
        df["預警"] = alert_tags
        df["溫度計"] = temps
        df["升降"] = trend_labels
        df["升降註"] = trend_notes
        df["temp_num"] = temp_nums
        df["月乖離"] = [f"{b:+.1f}%" for b in df["bias_monthly"]]
        df["120日量"] = [f"第 {int(r)} 名" for r in df["vol_rank_120"]]

        latest = df.iloc[-1]
        prev_close = 0.0
        real_c = df.loc[~df["is_halt"], "close"] if "is_halt" in df.columns else df["close"]
        if len(real_c) >= 2:
            prev_close = float(real_c.iloc[-2] or 0)
        y_close = float(latest.get("yesterday_close") or 0) if is_live else 0.0
        chg = resolve_daily_change_pct(
            float(latest["close"]),
            stored_pct=float(latest.get("change_pct") or 0),
            yesterday_close=y_close,
            prev_close=prev_close,
        )
        # 決策卡高／低：N 根「收盤」（南亞範本：20 日低是 165 不是日曆窗的 180）
        h10, h20, h60 = float(latest["high_10"]), float(latest["high_20"]), float(latest["high_60"])
        l10, l20, l60 = float(latest["low_10"]), float(latest["low_20"]), float(latest["low_60"])

        def _dist_h(h):
            c = float(latest["close"])
            return round((c - float(h)) / c * 100.0, 1) if c else 0.0

        def _dist_l(lo):
            lo = float(lo)
            return round((float(latest["close"]) - lo) / lo * 100.0, 1) if lo else 0.0

        space_20 = int(round((h20 - l20) / l20 * 100.0)) if l20 else 0
        space_60 = int(round((h60 - l60) / l60 * 100.0)) if l60 else 0
        ma60s = 0.0
        if len(df) >= 8:
            from decision_card_signals import compute_ma60s

            m0 = float(latest["ma60"] or 0)
            m7 = float(df["ma60"].iloc[-8] or 0)
            ma60s = compute_ma60s(m0, m7, float(latest["close"] or 0))
        raw_qty60 = float(df.loc[~df["is_halt"], "volume"].tail(60).mean() or 0)
        qty60 = int(round(raw_qty60))
        badges = []
        if is_live:
            try:
                from live_quote import mis_session_label

                clock = live_time[:5] if live_time else ""
                tag = mis_session_label(live_time)
                badges.append(f"{tag} {clock}".strip() if clock else tag)
            except Exception:
                badges.append("盤中 " + (live_time[:5] if live_time else "即時"))
        if any("除權" in x or "錯價" in x or "官方除權息" in x for x in xq_notes):
            badges.append("已除權還原")
        vr480 = int(latest["vol_rank_480"])
        vr120 = int(latest["vol_rank_120"])
        vr60 = int(latest["vol_rank_60"])
        vol_lab, vol_n = volume_headline_rank(vr480, vr120, vr60)
        if vol_n <= 10:
            badges.append(f"{vol_lab}第 {vol_n} 名")
        if vol_lab != "120日量" and vr120 != vol_n:
            badges.append(f"120日第 {vr120} 名")
        if float(latest["close"]) >= float(h20) * 0.998:
            badges.append("創20日新高")
        h120 = float(latest["high_120"]) if pd.notna(latest.get("high_120")) else 0.0
        h240 = float(latest["high_240"]) if pd.notna(latest.get("high_240")) else 0.0
        h480 = float(latest["high_480"]) if pd.notna(latest.get("high_480")) else 0.0
        l120 = float(latest["low_120"]) if pd.notna(latest.get("low_120")) else 0.0
        l240 = float(latest["low_240"]) if pd.notna(latest.get("low_240")) else 0.0
        l480 = float(latest["low_480"]) if pd.notna(latest.get("low_480")) else 0.0
        c0 = float(latest["close"])
        if h480 and c0 >= h480 * 0.998:
            badges.append("創480日新高")
        elif h240 and c0 >= h240 * 0.998:
            badges.append("創240日新高")
        elif h120 and c0 >= h120 * 0.998:
            badges.append("創120日新高")
        last_temp = float(temp_nums[-1] or 0) if temp_nums else 0.0
        ath_now = bool(
            (h480 and c0 >= h480 * 0.998)
            or (h240 and c0 >= h240 * 0.998)
            or (h120 and c0 >= h120 * 0.998)
        )
        if ath_now and last_temp >= TEMP_ATH_WATCH:
            badges.append("溫度≥80注意")
        if trend_notes and str(trend_notes[-1] or "") == "價溫背離":
            badges.append("價溫背離少追")
        if l480 and c0 <= l480 * 1.002:
            badges.append("創480日新低")
        elif l240 and c0 <= l240 * 1.002:
            badges.append("創240日新低")
        elif l120 and c0 <= l120 * 1.002:
            badges.append("創120日新低")
        elif l480 and c0 <= l480 * 1.02:
            badges.append("近480日低")
        elif l240 and c0 <= l240 * 1.02:
            badges.append("近240日低")
        elif l120 and c0 <= l120 * 1.02:
            badges.append("近120日低")
        if qty60 < 900:
            badges.append("60日均量過小")
        if space_60 and space_60 < 16:
            badges.append("60日區間過小")
        if len(df) >= 40:
            sp_prev = int(round(
                (float(df["high_60"].iloc[-21]) - float(df["low_60"].iloc[-21]))
                / float(df["low_60"].iloc[-21] or 1)
                * 100.0
            ))
            if space_60 and sp_prev and space_60 >= sp_prev + 6:
                badges.append("波動放大")
        regime = card_regime_label(
            float(latest["close"]),
            float(latest["ma20"] or latest["close"]),
            float(latest["ma60"] or latest["ma20"] or latest["close"]),
            space_60=float(space_60 or 0),
        )
        if regime == "整理格局":
            try:
                from screening_engine import _regime_label as _screen_regime

                sr = _screen_regime(
                    {
                        "close": float(latest["close"]),
                        "ma20": float(latest["ma20"] or 0),
                        "ma60": float(latest["ma60"] or 0),
                        "low20": float(l20),
                        "d20": float(_dist_l(l20)) if l20 else 0,
                    }
                )
                if sr in ("空頭排列", "弱勢破底", "月線下整理"):
                    regime = "空頭整理" if sr == "月線下整理" else sr
            except Exception:
                pass
        badges.append(regime)
        real = df.loc[~df["is_halt"]] if "is_halt" in df.columns else df
        table_src = real if len(real) >= lookback else df
        table = table_src.tail(lookback)[
            [
                "date", "close", "獲利", "高低", "預警", "溫度計", "升降", "升降註", "月乖離", "120日量",
                "profit_pct", "bias_monthly", "vol_rank_120", "temp_num",
            ]
        ].iloc[::-1]
        last_tbl = table.iloc[0] if len(table) else None
        if last_tbl is not None:
            stance, stance_kind = card_daily_stance(
                profit_pct=float(last_tbl.get("profit_pct") or 0),
                alert=str(last_tbl.get("預警") or ""),
                hl=str(last_tbl.get("高低") or ""),
                temp=float(last_tbl.get("temp_num") or 0),
                trend_note=str(last_tbl.get("升降註") or ""),
                bias=float(last_tbl.get("bias_monthly") or 0),
                badges=badges,
            )
        else:
            stance, stance_kind = "等待・按表操課", "wait"
        query_date, query_clock = format_card_query_stamp(
            is_live=is_live,
            latest_date=latest["date"],
            generated_at=generated_at,
        )
        streak = 0
        for a in reversed(alert_tags):
            if a == "K20高":
                streak += 1
            else:
                break
        return {
            "stock_id": str(stock_id),
            "stock_name": str(latest.get("stock_name") or stock_id),
            "latest_date": latest["date"],
            "db_as_of": db_as_of,
            "is_live": is_live,
            "live_time": live_time,
            "generated_at": generated_at,
            "query_date": query_date,
            "query_clock": query_clock,
            "close": float(latest["close"]),
            "change_pct": chg,
            "h10": h10, "dist_h10": _dist_h(h10),
            "h20": h20, "dist_h20": _dist_h(h20),
            "h60": h60, "dist_h60": _dist_h(h60),
            "l10": l10, "dist_l10": _dist_l(l10),
            "l20": l20, "dist_l20": _dist_l(l20),
            "l60": l60, "dist_l60": _dist_l(l60),
            "l120": l120, "dist_l120": _dist_l(l120) if l120 else None,
            "l240": l240, "dist_l240": _dist_l(l240) if l240 else None,
            "l480": l480, "dist_l480": _dist_l(l480) if l480 else None,
            "space_20": space_20,
            "space_60": space_60,
            "temp_c": latest["溫度計"],
            "ma20": float(latest["ma20"]),
            "ma60s": ma60s,
            "qty60": int(qty60),
            "xq_notes": xq_notes,
            "cal60_low": round(cal60_low, 2),
            "profit_floor": round(profit_floor, 2),
            "gain_pct": round(float(latest["profit_pct"]), 1) if pd.notna(latest.get("profit_pct")) else 0.0,
            "k20_high_streak": streak,
            "vol_rank": vr120,
            "vol_rank_480": vr480,
            "vol_rank_60": vr60,
            "prev_close": float(prev_close or 0),
            "badges": badges,
            "open": float(latest.get("open") or 0),
            "high": float(latest.get("high") or 0),
            "low": float(latest.get("low") or 0),
            "volume": float(latest.get("volume") or 0),
            "bias_monthly": float(latest.get("bias_monthly") or 0),
            "stance": stance,
            "stance_kind": stance_kind,
            "table": table,
            "_ohlc": df,
        }

    def scan_double_green_breakout(self) -> list:
        """全市場海選：【雙綠脫離】波段黃金起漲轉折股"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT stock_id, stock_name FROM stock_universe WHERE is_active=1;")
        stocks = cur.fetchall()
        conn.close()

        screened = []
        for sid, sname in stocks:
            card = self.get_decision_card(sid, lookback=5)
            if "error" in card or card["table"].empty:
                continue

            ht = card["table"].iloc[::-1].reset_index(drop=True)
            if len(ht) < 3:
                continue

            today = ht.iloc[-1]
            yesterday = ht.iloc[-2]

            from decision_card_signals import double_green_breakout

            if double_green_breakout(
                float(yesterday.get("profit_pct") or 0),
                str(yesterday.get("預警") or ""),
                float(today.get("profit_pct") or 0),
                str(today.get("預警") or ""),
            ):
                screened.append({
                    "stock_id": sid, "stock_name": sname,
                    "close": today["close"], "profit": today["獲利"],
                    "temp": today["溫度計"], "bias": today["月乖離"],
                    "space_60": card["space_60"]
                })
        return screened


class ChartGenerator:
    """假隨機 K 線已停用。導航圖請用 generate_chart（真實 OHLC）。"""

    @staticmethod
    def draw_180d_chart(*args, **kwargs):
        raise RuntimeError(
            "ChartGenerator.draw_180d_chart 已停用（會畫假資料）。請用 generate_chart。"
        )


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_price(p) -> str:
    """股價顯示：千元以上不要小數，避免萬元股把獲利欄擠爆。"""
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    av = abs(v)
    if av >= 1000:
        return f"{v:,.0f}"
    if av >= 100:
        s = f"{v:,.1f}"
        return s[:-2] if s.endswith(".0") else s
    s = f"{v:,.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _fmt_price_signed(p) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    body = _fmt_price(abs(v))
    if v > 0:
        return f"+{body}"
    if v < 0:
        return f"-{body}"
    return body


def _trend_note_short(note: str) -> str:
    """升降註縮短，避免與主標雙 pill 擠成一團。"""
    n = str(note or "").strip()
    return {
        "價未新低": "未新低",
        "價溫背離": "背離",
    }.get(n, n)


def _fmt_md(date_val) -> str:
    d = str(date_val or "")
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}/{d[4:6]}/{d[6:8]}"
    return d


def _fp(size, weight="normal"):
    # 可變字型數值軸：內文一律偏粗，避免落到 100 細體。
    if isinstance(weight, str):
        weight = {"light": 500, "normal": 700, "medium": 750, "bold": 800, "heavy": 900}.get(
            weight.lower(), 700
        )
    kwargs = {"size": size, "weight": weight}
    path = _weight_font_path(weight) if os.path.exists(FONT_PATH) else ""
    if path:
        kwargs["fname"] = path
    return fm.FontProperties(**kwargs)


def _cell(ax, x, y, w, h, facecolor="#ffffff", edge="#c5c5c5", lw=0.8):
    ax.add_patch(
        patches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="square,pad=0",
            facecolor=facecolor,
            edgecolor=edge,
            linewidth=lw,
            linestyle=(0, (1.6, 1.1)),
            mutation_aspect=1,
        )
    )


def _heat_pair(pct, lo=0.0, hi=45.0):
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "#f4f4f5", "#111111"
    t = max(0.0, min(1.0, (p - lo) / (hi - lo + 0.01)))
    # 底色只淡淡標強度，文字固定近黑，反差才夠
    r = 255
    g = int(250 - 55 * t)
    b = int(250 - 40 * t)
    bg = f"#{r:02x}{g:02x}{b:02x}"
    fg = "#000000"
    return bg, fg


_WARN_COLORS = {"60低": "#1565C0", "K20低": "#2E7D32", "K20高": "#C62828", "No": "#6B7280"}


def _fmt_num(v, nd=2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if nd == 0:
        return str(int(round(f)))
    return f"{f:,.{nd}f}"


def _fmt_pct(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{f:+.1f}%"


def _chg_color(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "#111827"
    if f > 0:
        return "#C62828"
    if f < 0:
        return "#00695C"
    return "#111827"


def _temp_num(v):
    if v is None:
        return None
    s = str(v).replace("°C", "").replace("℃", "").replace("C", "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _temp_color(v) -> str:
    t = _temp_num(v)
    if t is None:
        return "#111827"
    if t >= 70:
        return "#C62828"
    if t <= 30:
        return "#1565C0"
    return "#111827"


def _table_records(card: dict) -> list:
    table = card.get("table")
    if table is None:
        return []
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return list(table)


def _latest_profit(card: dict):
    rows = _table_records(card)
    if not rows:
        return None
    return rows[0].get("profit_pct")


def _fmt_md_tpl(date_val) -> str:
    d = str(date_val or "")
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}/{int(d[4:6])}/{int(d[6:8])}"
    return d


def _lum(color) -> float:
    """相對亮度（WCAG）；用來判斷字色算亮還是暗。"""
    out = 0.0
    for c, k in zip(mcolors.to_rgb(color), (0.2126, 0.7152, 0.0722)):
        out += k * (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _mix(color, other, t: float) -> str:
    """把 color 往 other 混 t 比例，用來取深一階的底色或描邊色。"""
    a, b = mcolors.to_rgb(color), mcolors.to_rgb(other)
    return mcolors.to_hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def _fg_on_panel(fg, bg=None, panel="#FFFFFF") -> str:
    """介紹圖只有字沒有格底：白字會消失，改用夠對比的深色。"""
    try:
        if fg and _wcag(fg, panel) >= 4.5:
            return fg
    except Exception:
        pass
    for cand in (bg, _CARD.get("hi_ink"), _CARD.get("ink"), "#111827"):
        if not cand:
            continue
        try:
            if _wcag(cand, panel) >= 4.5:
                return cand
        except Exception:
            continue
    return "#111827"


def _wcag(fg, bg) -> float:
    """字色與底色的對比倍數；白字壓深底至少要 4.5 才不吃力。"""
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _pill(ax, cx, cy, text, bg, fg, w=11.2, h=2.15, fs=10, z=3):
    if not text or text in ("No", "—", "nan"):
        ax.text(cx, cy, "No", fontproperties=_fp(11), color="#9e9e9e", ha="center", va="center", zorder=z + 1)
        return
    ax.add_patch(
        patches.FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.45",
            facecolor=bg,
            edgecolor=bg,
            linewidth=0,
            zorder=z,
        )
    )
    ax.text(cx, cy, text, fontproperties=_fp(fs, "heavy"), color=fg, ha="center", va="center",
            zorder=z + 1)


def _draw_mini_candle(ax, x, y, w, h, open_, high, low, close, prev_close=None):
    """在資料座標畫當日 K：台股紅漲綠跌（相對昨收），含上下影。"""
    from decision_card_signals import candle_up_taiwan

    o, hi, lo, cl = float(open_), float(high), float(low), float(close)
    rng = hi - lo
    if rng <= 0:
        rng = max(abs(cl) * 0.01, 0.01)
        hi = max(hi, cl, o) + rng / 2
        lo = min(lo, cl, o) - rng / 2
        rng = hi - lo

    def py(p):
        return y + (float(p) - lo) / rng * h

    color = "#e53935" if candle_up_taiwan(cl, prev_close, o) else "#00897b"
    cx = x + w / 2
    ax.plot([cx, cx], [py(lo), py(hi)], color=color, linewidth=2.4, solid_capstyle="round", zorder=4)
    body_lo, body_hi = py(min(o, cl)), py(max(o, cl))
    bh = max(body_hi - body_lo, h * 0.04)
    bw = w * 0.62
    ax.add_patch(
        patches.Rectangle(
            (cx - bw / 2, body_lo),
            bw,
            bh,
            facecolor=color,
            edgecolor=color,
            linewidth=0.4,
            zorder=5,
        )
    )


def horizon_low_cells(card: dict) -> list:
    """120／240／480 日收盤低；有數字就畫第二排。"""
    out = []
    for days, pk, dk in (
        (120, "l120", "dist_l120"),
        (240, "l240", "dist_l240"),
        (480, "l480", "dist_l480"),
    ):
        px, dist = card.get(pk), card.get(dk)
        if px is None or dist is None:
            continue
        try:
            px_f, dist_f = float(px), float(dist)
        except (TypeError, ValueError):
            continue
        if px_f <= 0:
            continue
        out.append((f"{days}低", px_f, dist_f))
    return out


def _fmt_dist(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_dist_short(val) -> str:
    """漲跌幅緊湊寫法：破百的小數點是雜訊，去掉才排得進一列三個數字。"""
    if val is None:
        return "—"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "—"
    return f"{v:+.0f}%" if abs(v) >= 100 else f"{v:+.1f}%"


# 決策卡色票集中一處：要換配色只改這裡，版面計算不動。
_CARD = {
    "page": "#EDF1F7",
    "panel": "#FFFFFF",
    "line": "#DCE3EC",
    "shadow": "#CBD4E1",
    "navy": "#16223F",
    "navy_soft": "#9FB3D9",
    "tag": "#C2185B",
    "ink": "#111827",
    "ink_soft": "#5B6472",
    "ink_mute": "#98A2B3",
    "hi_ink": "#AD1457",
    "hi_line": "#F2B4CB",
    "hi_fill": "#FDF2F6",
    "lo_ink": "#2E7D32",
    "lo_line": "#A7D8AE",
    "lo_fill": "#F1F9F2",
    "lo_hit_fill": "#D7F0DC",
    "lo_hit_line": "#4CAF50",
    "up": "#D81B60",
    "down": "#00695C",
    # 白字要壓在上面的底色壓深一階，對白色至少 5:1 對比。
    "pill_hi": "#AD1457",
    "pill_lo": "#2E7D32",
    "tbl_hdr": "#E7EEF8",
    "tbl_line": "#BACCE6",
    "tbl_ink": "#1E3A8A",
    "zebra": "#F7F9FC",
    "neutral_bg": "#F1F3F6",
    "neutral_fg": "#4B5563",
    "temp_hot_bg": "#F9A8C0",
    "temp_hot_fg": "#7A0B2E",
    "temp_warm_bg": "#FBC7D8",
    "temp_warm_fg": "#9B1145",
    "temp_compress_bg": "#0D47A1",
    "temp_compress_fg": "#FFFFFF",
    "price_not_low_bg": "#E65100",
    "price_not_low_fg": "#FFFFFF",
    "vol_hi_bg": "#F8BBD0",
    "vol_hi_fg": "#880E4F",
    "white": "#FFFFFF",
}


def _row_profit(row):
    if row is None:
        return None
    try:
        v = row.get("profit_pct") if hasattr(row, "get") else None
        if v is not None and v != "":
            return float(v)
    except (TypeError, ValueError, AttributeError):
        pass
    raw = ""
    try:
        raw = str(row.get("獲利") or "")
    except Exception:
        raw = ""
    raw = raw.replace("%", "").replace("+", "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_temp_n(val) -> float:
    s = str(val or "").replace(" °C", "").replace("°C", "").strip()
    if s in ("", "—", "-"):
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _price_at_window_low(i: int, closes: list, w0: int, tol: float = 0.002) -> bool:
    """近窗內收盤是否貼齊波段低（容許千分之二）。"""
    try:
        seg = [float(closes[j]) for j in range(w0, i + 1) if float(closes[j]) > 0]
        if not seg:
            return False
        return float(closes[i]) <= min(seg) * (1.0 + tol)
    except (TypeError, ValueError, IndexError):
        return False


def _price_at_window_high(i: int, closes: list, w0: int, tol: float = 0.002) -> bool:
    """近窗內收盤是否貼齊波段高（容許千分之二）。"""
    try:
        seg = [float(closes[j]) for j in range(w0, i + 1) if float(closes[j]) > 0]
        if not seg:
            return False
        return float(closes[i]) >= max(seg) * (1.0 - tol)
    except (TypeError, ValueError, IndexError):
        return False


def compute_temp_trend_labels(
    temp_nums: list,
    closes: list | None = None,
    window: int = 20,
) -> tuple[list, list]:
    """溫度升降溫標籤。

    低檔：溫度創窗內低但股價未創低 → 溫度壓縮＋價未新低。
    高檔：股價創窗內高但溫度已降、未創新高 → 降溫＋價溫背離（領先指標，少追）。
    """
    labels: list = []
    notes: list = []
    closes = closes or []
    for i, t in enumerate(temp_nums):
        if t <= 0:
            labels.append("—")
            notes.append("")
            continue
        prev = temp_nums[i - 1] if i > 0 and temp_nums[i - 1] > 0 else t
        w0 = max(0, i - window + 1)
        seg = [x for x in temp_nums[w0 : i + 1] if x > 0]
        if len(seg) < 2:
            labels.append("—")
            notes.append("")
            continue
        wmin, wmax = min(seg), max(seg)
        tol = 0.2
        at_max = t >= wmax - tol
        at_min = t <= wmin + tol
        if at_max and not at_min:
            labels.append("最高溫")
            notes.append("")
        elif at_min and not at_max:
            # CaryBot 這格寫「最低溫」；價未新低只當註記，不另造「溫度壓縮」主標。
            labels.append("最低溫")
            notes.append("價未新低" if closes and not _price_at_window_low(i, closes, w0) else "")
        elif t > prev + 0.25:
            labels.append("升溫")
            notes.append("")
        elif t < prev - 0.25:
            labels.append("降溫")
            note = ""
            if closes and _price_at_window_high(i, closes, w0):
                note = "價溫背離"
            notes.append(note)
        else:
            labels.append("—")
            notes.append("")
    return labels, notes


def temp_trend_cell_style(label: str, base: str):
    """升降欄：熱＝高色票、冷＝低色票，無訊號跟列底。"""
    C = _CARD
    base = base or C["white"]
    lab = str(label or "—")
    if lab == "最高溫":
        return C["temp_hot_bg"], C["temp_hot_fg"]
    if lab == "升溫":
        return C["temp_warm_bg"], C["temp_warm_fg"]
    if lab == "溫度壓縮":
        return C["temp_compress_bg"], C["temp_compress_fg"]
    if lab == "最低溫":
        return C["lo_hit_fill"], C["lo_ink"]
    if lab == "降溫":
        return C["lo_fill"], C["lo_ink"]
    return base, C["ink_mute"]


def temp_trend_note_cell_style(note: str, base: str):
    """升降註：價未新低／價溫背離等高對比小字。"""
    C = _CARD
    n = str(note or "")
    if n == "價未新低":
        return C["price_not_low_bg"], C["price_not_low_fg"]
    if n == "價溫背離":
        return C["temp_hot_bg"], C["temp_hot_fg"]
    return base or C["white"], C["ink_mute"]


def _badge_style(text: str):
    """徽章底色依語意（高／低／中性），不整排寫死粉紅。"""
    C = _CARD
    t = str(text or "")
    hot_keys = ("創", "新高", "少追", "過熱", "多頭", "上坡", "突破", "注意", "背離")
    cold_keys = ("低", "冷", "超跌", "止跌", "下坡", "箱型")
    solid_hi = any(k in t for k in ("創", "新高", "新低", "近"))
    if any(k in t for k in hot_keys) or ("高" in t and "低" not in t):
        if solid_hi:
            return C["pill_hi"], C["white"]
        return C["hi_fill"], C["hi_ink"]
    if any(k in t for k in cold_keys):
        if "近" in t and "低" in t:
            return C["pill_lo"], C["white"]
        return C["lo_fill"], C["lo_ink"]
    return C["neutral_bg"], C["neutral_fg"]


def profit_cell_style(profit, prev_profit=None, base: str = "#FFFFFF"):
    """獲利底圖跟高低卡同一套色票：貼零＝低、剛離零＝實綠、其餘跟列底。不整列寫死粉紅。"""
    C = _CARD
    base = base or C["white"]
    try:
        p = float(profit)
    except (TypeError, ValueError):
        return base, C["ink"]
    left_zero = False
    if prev_profit is not None:
        try:
            from decision_card_signals import profit_left_zero_highlight

            left_zero = profit_left_zero_highlight(prev_profit, profit)
        except Exception:
            left_zero = float(prev_profit) <= 0.05 and float(profit) > 0.05
    if left_zero:
        return C["lo_hit_fill"], C["lo_ink"]
    if p <= 0.05:
        return C["lo_fill"], C["lo_ink"]
    if p >= 40:
        return C["pill_hi"], C["white"]
    if p >= 20:
        return C["hi_fill"], C["hi_ink"]
    if p >= 8:
        return C["temp_warm_bg"], C["temp_warm_fg"]
    return base, C["ink"]


def hl_cell_style(hl: str, base: str):
    """高低欄底色：高＝高色、低＝低色、No＝列底。"""
    C = _CARD
    base = base or C["white"]
    hl = str(hl or "")
    if "高" in hl:
        return C["hi_fill"], C["pill_hi"]
    if "低" in hl:
        return C["lo_fill"], C["lo_ink"]
    return base, C["ink_mute"]


def alert_cell_style(alert: str, base: str):
    """預警欄底色：K20高／20高／60低／10低走色票，No＝列底。"""
    C = _CARD
    base = base or C["white"]
    a = str(alert or "")
    if a == "K20高" or ("高" in a and "低" not in a):
        return C["hi_fill"], C["pill_hi"]
    if a in ("60低", "K20低") or "低" in a:
        return C["lo_fill"], C["lo_ink"]
    return base, C["ink_mute"]


def temp_cell_style(temp_n, base: str):
    C = _CARD
    base = base or C["white"]
    try:
        t = float(temp_n)
    except (TypeError, ValueError):
        return base, C["neutral_fg"]
    if t >= 80:
        return C["pill_hi"], C["white"]
    if t >= 32:
        return C["temp_hot_bg"], C["temp_hot_fg"]
    if t >= 24:
        return C["temp_warm_bg"], C["temp_warm_fg"]
    if t >= 16:
        return C["hi_fill"], C["hi_ink"]
    return C["neutral_bg"], C["neutral_fg"]


def vol_rank_cell_style(rank, base: str):
    C = _CARD
    base = base or C["white"]
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return base, C["neutral_fg"]
    if r <= 10:
        return C["pill_hi"], C["white"]
    if r <= 20:
        return C["vol_hi_bg"], C["vol_hi_fg"]
    if r <= 50:
        return C["hi_fill"], C["hi_ink"]
    return C["neutral_bg"], C["neutral_fg"]


def bias_cell_style(bias, base: str):
    C = _CARD
    base = base or C["white"]
    try:
        b = float(bias)
    except (TypeError, ValueError):
        return base, C["ink"]
    if b > 0:
        return C["hi_fill"], C["up"]
    if b < 0:
        return C["lo_fill"], C["down"]
    return base, C["ink"]


def price_cell_style(hl: str, base: str):
    """股價欄：靠近高／低時底色跟高低卡，不是無條件粉紅。"""
    C = _CARD
    base = base or C["white"]
    hl = str(hl or "")
    if "高" in hl:
        return C["hi_fill"], C["pill_hi"]
    if "低" in hl:
        return C["lo_fill"], C["lo_ink"]
    return base, C["ink"]


def _card_text_w(text, fs: float, fig_w: float) -> float:
    """粗估字串寬度（資料座標）：中日韓字一個 em，半角約 0.55 em。量不到真實字寬時的退路。"""
    em = fs / (fig_w / 100.0 * 72.0)
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in str(text)) * em


@lru_cache(maxsize=8192)
def _glyph_w_pt(text: str, fs: float, weight: int) -> float:
    """字串的前進寬度（點）。matplotlib 對齊用的是前進寬度，
    用墨跡寬度算會少 10% 以上，右對齊的數字就會往左吃掉間距。"""
    try:
        with _FT_LOCK:
            font = _ft_font(weight)
            font.set_size(fs, 72)
            font.set_text(text)
            return float(font.get_width_height()[0]) / 64.0
    except Exception:
        return 0.0


def _text_w(text, fs: float, fig_w: float, weight=700) -> float:
    """真實字寬（資料座標）。估算會差幾個百分比，排一列四個數字就會擠在一起。"""
    s = str(text)
    if not s.strip():
        return 0.0
    pt = _glyph_w_pt(s, round(float(fs), 1), int(weight))
    if pt <= 0:
        return _card_text_w(s, fs, fig_w)
    return pt / 72.0 / (fig_w / 100.0)


def fit_label_value(labels, value, row_w, fig_w, *, fa=12.0, fb=15.0, gap=5.5,
                    weight=800, floor=9.5):
    """左標題右數值同一列：等比縮字級直到中間留得下 gap；還是撐不下就換較短的標題寫法。

    回傳 (採用的標題, 標題字級, 數值字級)。標題可傳由長到短的備選清單。
    """
    labels = [labels] if isinstance(labels, str) else list(labels)
    best = (labels[-1], fa, fb)
    for label in labels:
        la, lb = fa, fb
        while True:
            used = (_text_w(label, la, fig_w, weight)
                    + _text_w(value, lb, fig_w, weight) + gap)
            if used <= row_w:
                return label, la, lb
            if lb <= floor:
                best = (label, la, lb)
                break
            la, lb = la * 0.95, lb * 0.95
    return best


def fit_rows(rows, row_w, fig_w, *, fa=12.0, fb=15.0, gap=5.5, weight=800, floor=9.5):
    """同一區塊各列共用字級：取各列需求裡最小的那組，字高一致、右對齊的數字才會對齊。

    rows 是 (標題或標題備選, 數值) 的序列。回傳 (每列採用的標題, 標題字級, 數值字級)。
    """
    rows = list(rows)
    if not rows:
        return [], fa, fb
    picked = [
        fit_label_value(labels, value, row_w, fig_w, fa=fa, fb=fb,
                        gap=gap, weight=weight, floor=floor)
        for labels, value in rows
    ]
    ua = min(p[1] for p in picked)
    ub = min(p[2] for p in picked)
    out = []
    for (labels, value), fallback in zip(rows, picked):
        alts = [labels] if isinstance(labels, str) else list(labels)
        label = fallback[0]
        for alt in alts:
            if (_text_w(alt, ua, fig_w, weight)
                    + _text_w(value, ub, fig_w, weight) + gap) <= row_w:
                label = alt
                break
        out.append(label)
    return out, ua, ub


@_mpl_serial
def render_decision_card_png(card: dict, save_path: str) -> str:
    """單張長圖：區塊由上往下堆疊，圖高跟內容走，Telegram 縮圖後仍能讀。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    table = card["table"]
    n = max(len(table), 1)
    extra_lows = []
    for _lab, _px, dist in horizon_low_cells(card):
        try:
            if float(dist) <= 5.0:
                extra_lows.append((_lab, _px, dist))
        except (TypeError, ValueError):
            pass
    low_rows = 2 if extra_lows else 1
    C = _CARD

    # 每個區塊先算高度再由上往下堆，圖高跟著內容長，不會有人被壓到。
    pad_x = 2.6
    m_top, m_bot = 1.0, 1.35
    from decision_card_signals import format_card_query_stamp

    date_line = str(card.get("query_date") or "")
    clock_line = str(card.get("query_clock") or "")
    if not date_line:
        date_line, clock_line = format_card_query_stamp(
            is_live=bool(card.get("is_live")),
            latest_date=card.get("latest_date"),
            generated_at=card.get("generated_at"),
        )
    head_h = 9.6 if clock_line else 8.6
    title_band, box_h, box_gap, pane_pad = 3.6, 8.8, 1.0, 1.1
    tbl_title_h, hdr_h, body_h = 3.5, 3.15, 3.48
    gap = 1.35
    badge_h, badge_gap = 3.05, 0.85
    stance_h = 4.6

    fig_w = 7.1
    badges = []
    for b in list(card.get("badges") or []):
        b = str(b or "").strip()
        if b and "None" not in b and b not in badges:
            badges.append(b)
    badges = badges[:5] or ["整理格局"]
    badge_w = [_text_w(b, 10.4, fig_w, 900) + 3.4 for b in badges]
    badge_rows, row, row_w = [], [], 0.0
    limit = 100 - 2 * pad_x - 6.4
    for b, bw in zip(badges, badge_w):
        if row and row_w + 1.7 + bw > limit:
            badge_rows.append(row)
            row, row_w = [], 0.0
        row.append((b, bw))
        row_w += (1.7 if row_w else 0) + bw
    if row:
        badge_rows.append(row)
    price_h = 8.35 + len(badge_rows) * badge_h + (len(badge_rows) - 1) * badge_gap
    hi_pane_h = title_band + pane_pad + box_h + pane_pad
    lo_pane_h = title_band + pane_pad + low_rows * box_h + (low_rows - 1) * box_gap + pane_pad
    H = (
        m_top + head_h + gap + price_h + gap + stance_h + gap + hi_pane_h + gap + lo_pane_h
        + gap + tbl_title_h + hdr_h + n * body_h + m_bot
    )
    fig, ax = plt.subplots(figsize=(fig_w, H * 0.076), dpi=160, facecolor=C["page"])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.subplots_adjust(left=0.026, right=0.974, top=0.99, bottom=0.012)

    def tw(text, fs):
        return _text_w(text, fs, fig_w, 900)

    def pane(x, y, w, h, ec=C["line"], fc=C["panel"], r=0.9):
        ax.add_patch(patches.FancyBboxPatch(
            (x + 0.32, y - 0.40), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
            facecolor=C["shadow"], edgecolor="none", zorder=1))
        ax.add_patch(patches.FancyBboxPatch(
            (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
            facecolor=fc, edgecolor=ec, linewidth=1.1, zorder=2))

    def sec_title(x, cy, text, ink, sub=""):
        ax.add_patch(patches.FancyBboxPatch(
            (x, cy - 1.2), 0.9, 2.4, boxstyle="round,pad=0,rounding_size=0.42",
            facecolor=ink, edgecolor="none", zorder=3))
        ax.text(x + 2.1, cy, text, fontproperties=_fp(13.5, "bold"), color=ink, va="center", zorder=3)
        if sub:
            ax.text(x + 2.1 + tw(text, 13.5) + 1.9, cy, sub, fontproperties=_fp(9.6),
                    color=C["ink_soft"], va="center", zorder=3)

    inner_x = pad_x + 2.2
    box_gap_x = 1.7
    box_w = (100 - 2 * inner_x - 2 * box_gap_x) / 3.0

    def metric_box(x, y, lab, px, dist, *, high, hit=False):
        if high:
            fc, ec, lc = C["hi_fill"], C["hi_line"], C["hi_ink"]
        elif hit:
            fc, ec, lc = C["lo_hit_fill"], C["lo_hit_line"], C["lo_ink"]
        else:
            fc, ec, lc = C["lo_fill"], C["lo_line"], C["lo_ink"]
        ax.add_patch(patches.FancyBboxPatch(
            (x, y), box_w, box_h, boxstyle="round,pad=0,rounding_size=0.6",
            facecolor=fc, edgecolor=ec, linewidth=1.0, zorder=3))
        cx = x + box_w / 2
        ax.text(cx, y + 7.15, lab, fontproperties=_fp(10.5, "bold"), color=lc,
                ha="center", va="center", zorder=4)
        ax.text(cx, y + 4.55, _fmt_price(px), fontproperties=_fp(18, "bold"), color=C["ink"],
                ha="center", va="center", zorder=4)
        d = _fmt_dist(dist)
        if high:
            dc = C["down"] if (dist is not None and float(dist) < 0) else C["up"]
        else:
            dc = C["up"]
        ax.text(cx, y + 1.75, f"({d})" if d != "—" else d, fontproperties=_fp(12.5, "bold"),
                color=dc, ha="center", va="center", zorder=4)

    # 標題帶：左代號股名、右品牌＋日期；標語色帶貼底，不留空。
    y = H - m_top - head_h
    ax.add_patch(patches.FancyBboxPatch(
        (pad_x, y), 100 - 2 * pad_x, head_h, boxstyle="round,pad=0,rounding_size=1.0",
        facecolor=C["navy"], edgecolor="none", zorder=2))
    ax.text(pad_x + 2.8, y + head_h - 2.45, f"{card['stock_id']}　{card.get('stock_name') or ''}",
            fontproperties=_fp(20, "bold"), color="#FFFFFF", va="center", zorder=3)
    tag = "買低賣高決策卡　破解獲利密碼"
    tag_w = tw(tag, 10.8) + 3.2
    ax.add_patch(patches.FancyBboxPatch(
        (pad_x + 2.8, y + 1.2), tag_w, 2.85, boxstyle="round,pad=0,rounding_size=0.5",
        facecolor=C["tag"], edgecolor="none", zorder=3))
    ax.text(pad_x + 2.8 + tag_w / 2, y + 2.62, tag, fontproperties=_fp(10.8, "heavy"),
            color="#FFFFFF", ha="center", va="center", zorder=4)
    brand_x = 100 - pad_x - 2.6
    ax.text(brand_x, y + head_h - 2.45, "WayneBot", fontproperties=_fp(11.5, "bold"),
            color=C["navy_soft"], ha="right", va="center", zorder=3)
    if clock_line:
        ax.text(brand_x, y + 4.35, date_line, fontproperties=_fp(10.4, "bold"),
                color="#C5D0E8", ha="right", va="center", zorder=3)
        ax.text(brand_x, y + 1.95, clock_line, fontproperties=_fp(10.4, "bold"),
                color="#FFE082", ha="right", va="center", zorder=3)
    else:
        ax.text(brand_x, y + 2.62, date_line or _fmt_md(card.get("latest_date")),
                fontproperties=_fp(11, "bold"), color="#C5D0E8", ha="right", va="center", zorder=3)

    # 收盤＋漲跌＋開高低昨收；徽章自己一列。
    y -= gap + price_h
    pane(pad_x, y, 100 - 2 * pad_x, price_h)
    chg = float(card.get("change_pct") or 0)
    chg_c = C["up"] if chg > 0 else (C["down"] if chg < 0 else C["ink"])
    prev_c = float(card.get("prev_close") or 0)
    chg_amt = (float(card["close"]) - prev_c) if prev_c else None
    px_cy = y + price_h - 2.55
    ax.text(pad_x + 3.2, px_cy + 0.28, "收盤", fontproperties=_fp(10.5), color=C["ink_soft"],
            va="center", zorder=3)
    ax.text(pad_x + 11.2, px_cy, _fmt_price(card["close"]), fontproperties=_fp(26, "bold"),
            color=C["ink"], va="center", zorder=3)
    ax.text(48.0, px_cy, f"{chg:+.2f}%", fontproperties=_fp(18, "bold"), color=chg_c,
            va="center", zorder=3)
    if chg_amt is not None:
        ax.text(66.5, px_cy, _fmt_price_signed(chg_amt), fontproperties=_fp(15, "bold"), color=chg_c,
                va="center", zorder=3)
    ohlc_cy = y + price_h - 5.35
    ohlc_bits = [
        f"開 {_fmt_price(card.get('open'))}",
        f"高 {_fmt_price(card.get('high'))}",
        f"低 {_fmt_price(card.get('low'))}",
    ]
    if prev_c:
        ohlc_bits.append(f"昨 {_fmt_price(prev_c)}")
    ax.text(pad_x + 3.2, ohlc_cy, "　".join(ohlc_bits), fontproperties=_fp(11.2, "bold"),
            color=C["ink_soft"], va="center", zorder=3)
    by = y + 1.35 + (len(badge_rows) - 1) * (badge_h + badge_gap)
    for brow in badge_rows:
        bx = pad_x + 3.2
        for btxt, bw in brow:
            b_bg, b_fg = _badge_style(btxt)
            solid = b_bg in (C["pill_hi"], C["pill_lo"])
            edge = b_bg if solid else C["line"]
            ax.add_patch(patches.FancyBboxPatch(
                (bx, by), bw, badge_h, boxstyle="round,pad=0,rounding_size=0.55",
                facecolor=b_bg, edgecolor=edge,
                linewidth=0 if solid else 0.9, zorder=3))
            ax.text(bx + bw / 2, by + badge_h / 2, btxt, fontproperties=_fp(10.2, "heavy"),
                    color=b_fg, ha="center", va="center", zorder=4)
            bx += bw + 1.7
        by -= badge_h + badge_gap

    # 今日態度：按表，不是下單、不抄紅箭頭。
    y -= gap + stance_h
    kind = str(card.get("stance_kind") or "wait")
    stance_txt = str(card.get("stance") or "等待・按表操課")
    if kind == "avoid":
        s_fc, s_ec, s_ink = C["hi_fill"], C["hi_line"], C["hi_ink"]
    elif kind == "watch":
        s_fc, s_ec, s_ink = C["lo_hit_fill"], C["lo_hit_line"], C["lo_ink"]
    else:
        s_fc, s_ec, s_ink = C["panel"], C["line"], C["ink"]
    pane(pad_x, y, 100 - 2 * pad_x, stance_h, ec=s_ec, fc=s_fc)
    ax.text(pad_x + 3.2, y + stance_h / 2 + 0.55, f"今日態度　{stance_txt}",
            fontproperties=_fp(14.5, "heavy"), color=s_ink, va="center", zorder=4)
    ax.text(pad_x + 3.2, y + stance_h / 2 - 1.15, "按表操課・不是下單指令　紅箭頭只是觀察",
            fontproperties=_fp(9.4), color=C["ink_soft"], va="center", zorder=4)

    # 高點
    y -= gap + hi_pane_h
    pane(pad_x, y, 100 - 2 * pad_x, hi_pane_h, ec=C["hi_line"])
    sec_title(pad_x + 2.6, y + hi_pane_h - title_band / 2, "高點資訊", C["hi_ink"],
              f"10日／20日／60日　MA60S {card.get('ma60s')}　QTY60 {int(card.get('qty60') or 0):,}")
    highs = [("10日高點", card["h10"], card["dist_h10"]),
             ("20日高點", card["h20"], card["dist_h20"]),
             ("60日高點", card["h60"], card["dist_h60"])]
    for i, (lab, px, dist) in enumerate(highs):
        metric_box(inner_x + i * (box_w + box_gap_x), y + pane_pad, lab, px, dist, high=True)

    # 低點：短中期一排，120／240／480 另一排，貼到 2% 內就實綠。
    y -= gap + lo_pane_h
    pane(pad_x, y, 100 - 2 * pad_x, lo_pane_h, ec=C["lo_line"])
    sec_title(pad_x + 2.6, y + lo_pane_h - title_band / 2, "低點資訊", C["lo_ink"],
              f"20日（高低操作空間 {card['space_20']}%）／60日（高低操作空間 {card['space_60']}%）")
    lows = [("10日低點", card["l10"], card["dist_l10"]),
            ("20日低點", card["l20"], card["dist_l20"]),
            ("60日低點", card["l60"], card["dist_l60"])]
    row1_y = y + pane_pad + ((box_h + box_gap) if extra_lows else 0)
    for i, (lab, px, dist) in enumerate(lows):
        hit = dist is not None and float(dist) <= 2.0
        metric_box(inner_x + i * (box_w + box_gap_x), row1_y, lab, px, dist, high=False, hit=hit)
    if extra_lows:
        for i, (lab, px, dist) in enumerate(extra_lows[:3]):
            hit = dist is not None and float(dist) <= 2.0
            metric_box(inner_x + i * (box_w + box_gap_x), y + pane_pad,
                       f"{lab[:-1]}日低點", px, dist, high=False, hit=hit)

    # 過去 20 天：預警欄露出高低；升降溫＝溫度趨勢（不是股價漲跌）；量能上色。
    y -= gap + tbl_title_h
    sec_title(pad_x + 0.6, y + tbl_title_h / 2, "過去 20 天記錄", "#37474F",
              "預警會露出 20高／10低；升降溫＝溫度計；最右欄＝120日量排名")
    headers = ["日期", "股價", "獲利", "預警", "溫度計", "升降溫", "月乖離", "120日量"]
    # 股價欄加寬（萬元股）、升降溫略加寬給雙標；日期／獲利略收。
    weights = [12.2, 12.2, 8.8, 10.6, 11.0, 14.2, 9.6, 12.4]
    pill_cols = {3, 5, 7}
    span = 100 - 2 * pad_x
    xs = [pad_x]
    for wgt in weights:
        xs.append(xs[-1] + span * wgt / sum(weights))
    tbl_top = y
    for i, h in enumerate(headers):
        ax.add_patch(patches.Rectangle((xs[i], tbl_top - hdr_h), xs[i + 1] - xs[i], hdr_h,
                                       facecolor=C["tbl_hdr"], edgecolor=C["tbl_line"], lw=0.7, zorder=2))
        ax.text((xs[i] + xs[i + 1]) / 2, tbl_top - hdr_h / 2, h, fontproperties=_fp(11.2, "bold"),
                ha="center", va="center", color=C["tbl_ink"], zorder=3)
    ry = tbl_top - hdr_h
    from decision_card_signals import display_alert_cell

    for row_i, (_, r) in enumerate(table.iterrows()):
        y1 = ry - body_h
        bias = float(r.get("bias_monthly") or 0)
        rank = int(r.get("vol_rank_120") or 99)
        temp_n = float(r.get("temp_num") or 0) or _parse_temp_n(r.get("溫度計"))
        trend = str(r.get("升降") or "—")
        trend_note = str(r.get("升降註") or "")
        hl = str(r["高低"])
        al = display_alert_cell(str(r["預警"]), hl)
        zebra = row_i % 2 == 0
        base = C["white"] if zebra else C["zebra"]
        nxt = table.iloc[row_i + 1] if row_i + 1 < len(table) else None
        p_bg, p_fg = profit_cell_style(_row_profit(r), _row_profit(nxt), base)
        px_bg, px_fg = price_cell_style(hl, base)
        al_bg, al_fg = alert_cell_style(al, base)
        tbg, tfg = temp_cell_style(temp_n, base)
        tr_bg, tr_fg = temp_trend_cell_style(trend, base)
        vbg, vfg = vol_rank_cell_style(rank, base)
        b_bg, b_fg = bias_cell_style(bias, base)
        fills = [base, px_bg, p_bg, al_bg, tbg, tr_bg, b_bg, vbg]
        fgs = [C["ink"], px_fg, p_fg, al_fg, tfg, tr_fg, b_fg, vfg]
        vals = [
            _fmt_md_tpl(r["date"]),
            _fmt_price(r["close"]),
            str(r["獲利"]).replace("+", ""),
            al,
            str(r["溫度計"]),
            trend,
            str(r["月乖離"]).replace("+", ""),
            str(r["120日量"]),
        ]
        for i, val in enumerate(vals):
            col_w = xs[i + 1] - xs[i]
            ax.add_patch(patches.Rectangle((xs[i], y1), col_w, body_h,
                                           facecolor=fills[i], edgecolor=C["line"], lw=0.5, zorder=2))
            cx, cy = (xs[i] + xs[i + 1]) / 2, (ry + y1) / 2
            if i in pill_cols:
                if val in ("No", "—") or not str(val).strip():
                    ax.text(cx, cy, "No" if val in ("No", "—", "") else val,
                            fontproperties=_fp(11), color=fgs[i], ha="center", va="center", zorder=3)
                elif i == 5 and trend_note:
                    note = _trend_note_short(trend_note)
                    nbg, nfg = temp_trend_note_cell_style(trend_note, base)
                    max_w = col_w * 0.92
                    # 主標過長時縮字（如「溫度壓縮」）
                    main_lab = "壓縮" if trend == "溫度壓縮" else trend
                    main_fs = 9.6 if len(main_lab) >= 3 else 10.2
                    note_fs = 8.8
                    main_w = min(tw(main_lab, main_fs) + 2.4, max_w)
                    note_w = min(tw(note, note_fs) + 2.0, max_w)
                    # 上下拉開，避免兩顆 pill 垂直重疊糊成一團（8/27、8/28 常見）
                    _pill(
                        ax,
                        cx,
                        cy + body_h * 0.20,
                        main_lab,
                        tr_bg,
                        tr_fg,
                        w=main_w,
                        h=body_h * 0.32,
                        fs=main_fs,
                    )
                    _pill(
                        ax,
                        cx,
                        cy - body_h * 0.22,
                        note,
                        nbg,
                        nfg,
                        w=note_w,
                        h=body_h * 0.28,
                        fs=note_fs,
                    )
                else:
                    pill_w = min(tw(val, 11.0) + 3.0, col_w * 0.90)
                    _pill(ax, cx, cy, val, fills[i], fgs[i], w=pill_w,
                          h=body_h * 0.74, fs=11.0)
            else:
                # 萬元股價字串較長：略縮字級，避免溢進獲利欄
                px_fs = 10.5 if (i == 1 and len(str(val)) >= 7) else 12
                ax.text(cx, cy, val, fontproperties=_fp(px_fs, "bold"), ha="center", va="center",
                        color=fgs[i], zorder=3)
        ry = y1
    ax.add_patch(patches.Rectangle((pad_x, ry), span, tbl_top - ry, facecolor="none",
                                   edgecolor=C["tbl_line"], lw=1.1, zorder=4))

    fig.savefig(save_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path

def _load_ohlc(stock_id: str, db_path: str = None, days: int = 180) -> pd.DataFrame:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    df = pd.read_sql_query(
        """
        SELECT date, stock_name, open, high, low, close, volume, pct_change
        FROM daily_quotes WHERE stock_id = ? ORDER BY date DESC LIMIT ?
        """,
        conn,
        params=(str(stock_id).strip(), days),
    )
    conn.close()
    if df.empty:
        return df
    df = df.iloc[::-1].reset_index(drop=True)
    df["stock_id"] = str(stock_id).strip()
    try:
        from live_quote import append_live_bar

        df = append_live_bar(df, str(stock_id).strip())
    except Exception:
        pass
    return df


def generate_decision_card(stock_id: str, db_path: str = None, lookback: int = 20) -> str:
    sid = str(stock_id).strip()
    df = _load_ohlc(sid, db_path, 375)
    if df.empty or len(df) < 5:
        return f"⚠️ 找不到 <code>{html_escape(sid)}</code> 的日 K（請先完成歷史庫／盤後增量）。"
    engine = NavigatorEngine(db_path or get_db_path())
    card = engine.get_decision_card(sid, lookback=lookback)
    if "error" in card:
        return f"⚠️ {html_escape(card['error'])}"
    name = card.get("stock_name") or str(df["stock_name"].iloc[-1] or sid)
    try:
        from stock_links import yahoo_urls

        web, mobile = yahoo_urls(sid, db_path or get_db_path())
    except Exception:
        web = mobile = ""
    pink_note = pink_warning_note(card)
    chg = float(card.get("change_pct") or 0)
    from tg_layout import kv_compact, section, join_sections
    from chip_tape import build_tape, fmt_lots_align

    tape = build_tape(db_path or get_db_path(), sid) or {}
    move = (tape.get("move") or {}).get("text") or f"{chg:+.2f}%"
    last = tape.get("last") or {}
    ohlc = ""
    if last:
        ohlc = f"{_fmt_price(last.get('open'))} / {_fmt_price(last.get('high'))} / {_fmt_price(last.get('low'))}"
    badge = "　".join(str(x) for x in (card.get("badges") or []) if x)
    links = ""
    if web:
        links = f'<a href="{web}">網頁走勢</a>　<a href="{mobile}">技術線</a>'
    head = f"<b>{html_escape(sid)} {html_escape(name)}</b>"
    if links:
        head = f"{head}　　{links}"
    title_block = f"{head}\n{html_escape(badge)}" if badge else head
    chip_block = ""
    if tape:
        chip_block = section(
            kv_compact("外資", f"{fmt_lots_align(tape.get('foreign', {}).get('net', 0))}　{tape.get('foreign', {}).get('phrase', '')}"),
            kv_compact("投信", f"{fmt_lots_align(tape.get('trust', {}).get('net', 0))}　{tape.get('trust', {}).get('phrase', '')}"),
            kv_compact("自營", f"{fmt_lots_align(tape.get('dealer', {}).get('net', 0))}　{tape.get('dealer', {}).get('phrase', '')}"),
            kv_compact("法人", f"{fmt_lots_align(tape.get('three', {}).get('net', 0))}　{tape.get('three', {}).get('phrase', '')}"),
            kv_compact("籌碼佔量", f"{tape.get('inst_pct', 0):+.1f}%（法人買賣超÷成交量）"),
        )
    vol_line = (tape.get("volume") or {}).get("line") or "—"
    extra_flags = tape.get("conflict") or ""
    bias = card.get("bias_monthly")
    bias_s = f"{float(bias):+.1f}%" if bias is not None else "—"
    from decision_card_signals import volume_headline_rank, volume_rank_pair_text

    vol_lab, vol_n = volume_headline_rank(
        card.get("vol_rank_480") or 99,
        card.get("vol_rank") or 99,
        card.get("vol_rank_60") or 99,
    )
    vol_pair = volume_rank_pair_text(
        card.get("vol_rank_480") or 99,
        card.get("vol_rank") or 99,
        card.get("vol_rank_60") or 99,
    )
    try:
        from fundamentals import glance_fundamentals_rows

        fund_block = section(*glance_fundamentals_rows(sid, db_path or get_db_path()))
    except Exception:
        fund_block = ""
    tail = section(*[x for x in (extra_flags, fund_block, pink_note) if x])
    try:
        from live_quote import live_clock_suffix

        date_note = live_clock_suffix(bool(card.get("is_live")), str(card.get("live_time") or ""))
    except Exception:
        date_note = " 盤中" + (f" {card.get('live_time')}" if card.get("live_time") else "") if card.get("is_live") else ""
    return join_sections(
        title_block,
        section(
            kv_compact("日期", _fmt_md(card["latest_date"]) + date_note),
            kv_compact("開高低", ohlc or "—"),
            kv_compact("收盤", f"{_fmt_price(card['close'])}　{move}"),
            kv_compact("當日", f"{chg:+.2f}%"),
        ),
        section(
            kv_compact("距20日高", f"{card['dist_h20']:+.1f}%"),
            kv_compact("獲利", f"{card.get('gain_pct', card.get('dist_l60')):+.1f}%（近60曆日低 {card.get('cal60_low', '—')}）"),
            kv_compact("距60根低", f"{card.get('dist_l60'):+.1f}%"),
            kv_compact("距120低", _fmt_dist(card.get("dist_l120"))),
            kv_compact("距240低", _fmt_dist(card.get("dist_l240"))),
            kv_compact("距480低", _fmt_dist(card.get("dist_l480"))),
            kv_compact("月空間", f"{card['space_20']}%"),
            kv_compact("季空間", f"{card['space_60']}%"),
            kv_compact("月乖離", bias_s),
        ),
        section(
            kv_compact("溫度", card.get("temp_c") or "—"),
            kv_compact("量排名", vol_pair),
            kv_compact("量比", vol_line),
        ),
        chip_block,
        tail,
        sep="\n＝＝＝＝＝＝＝＝＝＝＝＝\n",
    )


@_mpl_serial
def render_first_glance_png(stock_id: str, card: dict, tape: dict, save_path: str, db_path: str = None) -> str:
    """窄長圖、大字、高 DPI：Telegram 依對話框寬縮放，靠字級與留白保證能讀。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    from chip_tape import fmt_lots_align

    try:
        from fundamentals import glance_fundamentals_plain

        fund_rows = glance_fundamentals_plain(stock_id, db_path or get_db_path())
    except Exception:
        fund_rows = []

    last = (tape or {}).get("last") or {}
    move = (tape or {}).get("move") or {}
    fig, ax = plt.subplots(figsize=(4.62, 16.4), dpi=150, facecolor="#EEF2F7")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.subplots_adjust(left=0.028, right=0.972, top=0.988, bottom=0.012)

    def panel(x, y, w, h, fc="#FFFFFF", ec="#D5DDE8"):
        ax.add_patch(patches.FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.18,rounding_size=0.55",
            facecolor=fc, edgecolor=ec, linewidth=0.9, zorder=1,
        ))

    def ink(x, y, text, size=12, color="#607D8B", ha="left", va="center"):
        ax.text(x, y, text, fontproperties=_fp(size, "bold"), color=color, ha=ha, va=va, zorder=3)

    row_w = 96.4 - 4.8

    def wid(text, fs):
        return _text_w(text, fs, 4.62, 800)

    def fit_fs(text, fs, avail, floor=8.5):
        """字太長就縮到放得下，長期低點那種一列四個數字才不會撞到邊。"""
        while fs > floor and wid(text, fs) > avail:
            fs -= 0.4
        return fs

    panel(1.4, 90.55, 97.2, 8.7, "#15256B", "#15256B")
    ax.add_patch(patches.FancyBboxPatch(
        (3.0, 91.15), 14.8, 7.5, boxstyle="round,pad=0.1,rounding_size=0.4",
        facecolor="#F4F6FB", edgecolor="none", zorder=2,
    ))
    _draw_mini_candle(
        ax, 4.1, 91.45, 12.6, 6.9,
        last.get("open") or card.get("open") or card.get("close") or 0,
        last.get("high") or card.get("high") or card.get("close") or 0,
        last.get("low") or card.get("low") or card.get("close") or 0,
        last.get("close") or card.get("close") or 0,
        last.get("yesterday_close") or card.get("prev_close") or None,
    )
    ink(20.2, 96.85, f"{card.get('stock_id') or stock_id}  {card.get('stock_name') or ''}", 20, "#FFFFFF")
    badge = "　".join(str(x) for x in (card.get("badges") or []) if x)
    ink(20.2, 93.45, badge or "—", fit_fs(badge or "—", 12, 94.0 - 20.2, floor=7.0), "#FFE082")
    try:
        from live_quote import live_clock_suffix

        date_note = live_clock_suffix(bool(card.get("is_live")), str(card.get("live_time") or ""))
    except Exception:
        date_note = " 盤中 " + str(card.get("live_time") or "") if card.get("is_live") else ""
    ink(96.8, 96.85, _fmt_md(card.get("latest_date")) + date_note, 11, "#C5CAE9", ha="right")

    chg = float(card.get("change_pct") or 0)
    up = int(move.get("sign") or 0)
    tri_c = "#C62828" if up > 0 else ("#00695C" if up < 0 else "#37474F")
    panel(1.4, 77.55, 97.2, 12.2)
    ink(4.8, 87.15, "收盤", 11)
    ink(4.8, 83.35, _fmt_price(card.get("close")), 34, "#0D1117")
    ohlc = f"開 {_fmt_price(last.get('open'))}　高 {_fmt_price(last.get('high'))}　低 {_fmt_price(last.get('low'))}" if last else ""
    ink(4.8, 79.35, ohlc, 12, "#455A64")
    ink(96.4, 86.55, move.get("text") or f"{chg:+.2f}%", 16, tri_c, ha="right")
    ink(96.4, 82.85, f"當日 {chg:+.2f}%", 14, tri_c, ha="right")

    def kv_block(y, h, title, rows):
        panel(1.4, y, 97.2, h)
        ink(4.8, y + h - 1.55, title, 13, "#1A237E")
        labels, fa, fb = fit_rows([(r[0], r[1]) for r in rows], row_w, 4.62)
        yy = y + h - 4.15
        for (_, b, c), a in zip(rows, labels):
            ink(4.8, yy, a, fa)
            ink(96.4, yy, b, fb, _fg_on_panel(c), ha="right")
            yy -= 3.35

    kv_block(61.55, 15.15, "空間／位置", [
        ("距20日高（賣壓）", f"{card['dist_h20']:+.1f}%",
         price_cell_style("20高" if float(card["dist_h20"]) >= -1 else "No", _CARD["white"])[1]),
        ("獲利（近60曆日低）",
         f"{float(card.get('gain_pct') if card.get('gain_pct') is not None else card.get('dist_l60') or 0):+.1f}%",
         profit_cell_style(float(card.get('gain_pct') if card.get('gain_pct') is not None else card.get('dist_l60') or 0), None, _CARD["white"])[1]),
        (["距120／240／480低", "距120/240/480低", "距長期低"], " ".join([
            _fmt_dist_short(card.get("dist_l120")),
            _fmt_dist_short(card.get("dist_l240")),
            _fmt_dist_short(card.get("dist_l480")),
        ]), _CARD["ink"]),
        ("月／季空間", f"{card['space_20']}%　／　{card['space_60']}%", _CARD["ink"]),
    ])
    _temp_n = _temp_num(card.get("temp_c"))
    from decision_card_signals import volume_headline_rank, volume_rank_pair_text

    vol_lab, vol_n = volume_headline_rank(
        card.get("vol_rank_480") or 99,
        card.get("vol_rank") or 99,
        card.get("vol_rank_60") or 99,
    )
    vol_pair = volume_rank_pair_text(
        card.get("vol_rank_480") or 99,
        card.get("vol_rank") or 99,
        card.get("vol_rank_60") or 99,
    )
    kv_block(48.55, 12.15, "熱度／量能", [
        ("溫度", str(card.get("temp_c") or "—"), temp_cell_style(_temp_n, _CARD["white"])[1]),
        ("量排名", vol_pair,
         vol_rank_cell_style(int(vol_n or 99), _CARD["white"])[1]),
        ("量比", (tape or {}).get("volume", {}).get("line") or "—", _CARD["ink"]),
    ])

    def chip_color(n):
        if n > 0:
            return "#B71C1C"
        if n < 0:
            return "#1B5E20"
        return "#546E7A"

    chips = [
        ("外資", (tape or {}).get("foreign") or {}),
        ("投信", (tape or {}).get("trust") or {}),
        ("自營", (tape or {}).get("dealer") or {}),
        ("法人", (tape or {}).get("three") or {}),
    ]
    panel(1.4, 26.85, 97.2, 20.85)
    ink(4.8, 45.5, "籌碼（張）", 13, "#1A237E")
    ink(96.4, 45.5, f"佔量 {(tape or {}).get('inst_pct', 0):+.1f}%＝法人÷成交", 11, "#546E7A", ha="right")
    # 張數右緣固定；四列共用字級，位數不同也對得齊。
    lots_right = 38.0
    lots_of = {name: fmt_lots_align(int(item.get("net") or 0)) for name, item in chips}
    phrase_of = {name: (item.get("phrase") or "—") for name, item in chips}
    _, f_name, f_lots = fit_rows(
        [(name, lots_of[name]) for name, _ in chips], lots_right - 4.8, 4.62,
        fa=12.0, fb=16.0, gap=4.0, floor=10.0,
    )
    f_phrase = min(
        fit_fs(phrase_of[name], 12, 96.4 - lots_right - 4.2, floor=8.0) for name, _ in chips
    )
    cy = 41.45
    for name, item in chips:
        net = int(item.get("net") or 0)
        ink(4.8, cy, name, f_name)
        ink(lots_right, cy, lots_of[name], f_lots, chip_color(net), ha="right")
        ink(96.4, cy, phrase_of[name], f_phrase, chip_color(net), ha="right")
        cy -= 4.05

    panel(1.4, 5.35, 97.2, 20.7)
    ink(4.8, 23.85, "基本面／紀律", 13, "#1A237E")
    fy = 20.35
    note = (tape or {}).get("conflict") or ""
    if note:
        ink(4.8, fy, note, fit_fs(note, 14, row_w), "#C62828")
        fy -= 3.35
    fund_lines = [f"{a}　{b}" for a, b in fund_rows]
    f_fund = min([fit_fs(line, 12, row_w) for line in fund_lines] or [12])
    for line in fund_lines:
        ink(4.8, fy, line, f_fund, "#111111")
        fy -= 3.15
    try:
        note2 = pink_warning_note(card)
        if note2:
            ink(4.8, fy, note2, fit_fs(note2, 13, row_w), "#AD1457")
    except Exception:
        pass
    ink(4.8, 6.85, "左上 K＝當日開高低收（紅漲綠跌＝相對昨收）　▲連漲　▼連跌", 10, "#78909C")
    plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    return save_path



# 導航箭頭配色：(壓在淺底時, 壓在同色系底時)。
# 淺粉箭頭放在粉紅區、淺綠箭頭放在綠區會看不見，所以同色系底要換深色。
_NAV_TONE = {
    "h20": ("#EC407A", "#AD1457"),
    "h20_near": ("#F48FB1", "#C2185B"),
    "h20_leave": ("#7B1FA2", "#4A148C"),
    "l20": ("#43A047", "#1B5E20"),
    "l20_near": ("#81C784", "#2E7D32"),
    "l20_leave": ("#00838F", "#00463F"),
    "l60": ("#00ACC1", "#006064"),
}


def _nav_legend_key(kind: str, marker: str, *, ms: float = 9.0, hollow: bool = False):
    face = _NAV_TONE[kind][0] if kind in _NAV_TONE else "#546e7a"
    if hollow:
        return Line2D(
            [], [], linestyle="none", marker=marker, markerfacecolor="none",
            markeredgecolor=face, markeredgewidth=1.05, markersize=ms,
        )
    return Line2D(
        [], [], linestyle="none", marker=marker, markerfacecolor=face,
        markeredgecolor=_mix(face, "#000000", 0.42), markeredgewidth=0.85,
        markersize=ms,
    )


def _draw_nav_legend(ax1) -> None:
    """雙列圖例：上列價格箭頭、下列量能＋均線（對齊 CaryBot 密度）。"""
    row1 = [
        (_nav_legend_key("h20", "v"), "20高"),
        (_nav_legend_key("h20_leave", "v"), "20高脫離"),
        (_nav_legend_key("l20", "^"), "20低"),
        (_nav_legend_key("l20_leave", "^"), "20低脫離"),
        (_nav_legend_key("l60", "^"), "60低"),
    ]
    row2 = [
        (Line2D([], [], linestyle="none", marker="^", markerfacecolor="#6a1b9a",
                markeredgecolor="#311b92", markeredgewidth=0.9, markersize=9), "量能異常"),
        (Line2D([], [], linestyle="none", marker="^", markerfacecolor="#e53935",
                markeredgecolor="#7f0000", markeredgewidth=0.9, markersize=9), "警告"),
        (Line2D([], [], linestyle="none", marker="^", markerfacecolor="#ce93d8",
                markeredgecolor="#6a1b9a", markeredgewidth=0.8, markersize=8), "月波動低"),
        (Line2D([], [], color="#f9a825", lw=2.25), "SMA(20)"),
        (Line2D([], [], color="#f48fb1", lw=1.75), "季高點線"),
    ]
    row3 = [
        (Line2D([], [], color="#81c784", lw=1.75), "季低點線"),
        (Line2D([], [], color="#f8bbd0", lw=1.15, linestyle="--"), "月高點線"),
        (Line2D([], [], color="#80deea", lw=1.15, linestyle="--"), "月低點線"),
        (_nav_legend_key("h20_near", "v", ms=10, hollow=True), "接近高低（空心）"),
    ]
    kw = dict(
        loc="upper left",
        ncol=5,
        handlelength=1.25,
        handletextpad=0.38,
        columnspacing=0.95,
        borderpad=0.45,
        labelspacing=0.28,
        framealpha=0.97,
        facecolor="#f3f6f9",
        edgecolor="#90a4ae",
        prop=_fp(8.2, "bold"),
    )
    leg1 = ax1.legend([h for h, _ in row1], [t for _, t in row1], bbox_to_anchor=(0.004, 1.018), **kw)
    leg1.set_zorder(10)
    ax1.add_artist(leg1)
    leg2 = ax1.legend([h for h, _ in row2], [t for _, t in row2], bbox_to_anchor=(0.004, 0.972), **kw)
    leg2.set_zorder(10)
    ax1.add_artist(leg2)
    kw3 = {**kw, "ncol": 4}
    leg3 = ax1.legend([h for h, _ in row3], [t for _, t in row3], bbox_to_anchor=(0.004, 0.926), **kw3)
    leg3.set_zorder(10)


def _nav_tone(kind: str, y: float, h20: float, l20: float) -> str:
    light, dark = _NAV_TONE[kind]
    same_hue = (kind[0] == "h" and y >= h20) or (kind[0] == "l" and y <= l20)
    return dark if same_hue else light


def _nav_arrow(ax, y_tip, x, *, down: bool, face: str, arrow_h: float, hw=0.58,
               z=7, alpha=1.0, hollow=False):
    """帶柄箭頭：尖端對準價位；外加白色光暈，壓在 K 棒或色塊上都能跳出來。"""
    head_h = arrow_h * 0.52
    shaft_h = arrow_h * 0.48
    sw = hw * 0.27
    s = 1.0 if down else -1.0
    head_y = y_tip + s * head_h
    tail_y = head_y + s * shaft_h
    verts = [
        (x, y_tip),
        (x + hw, head_y),
        (x + sw, head_y),
        (x + sw, tail_y),
        (x - sw, tail_y),
        (x - sw, head_y),
        (x - hw, head_y),
    ]
    poly = patches.Polygon(
        verts,
        closed=True,
        facecolor="none" if hollow else face,
        edgecolor=face if hollow else _mix(face, "#000000", 0.42),
        linewidth=1.15 if hollow else 0.85,
        joinstyle="round",
        alpha=alpha,
        zorder=z,
    )
    poly.set_path_effects([
        patheffects.withStroke(linewidth=2.4, foreground="#FFFFFF"),
        patheffects.Normal(),
    ])
    ax.add_patch(poly)


def _sig_arrow(ax, x, y, face: str, edge: str, scale: float = 1.0, z=6):
    """量能列向上箭頭。"""
    h = 0.22 * scale
    hw = 0.20 * scale
    sw = 0.055 * scale
    tip, head, tail = y + h * 0.55, y, y - h * 0.72
    verts = [
        (x, tip),
        (x + hw, head),
        (x + sw, head),
        (x + sw, tail),
        (x - sw, tail),
        (x - sw, head),
        (x - hw, head),
    ]
    ax.add_patch(
        patches.Polygon(
            verts,
            closed=True,
            facecolor=face,
            edgecolor=edge,
            linewidth=0.55,
            joinstyle="round",
            zorder=z,
            clip_on=False,
        )
    )


@_mpl_serial
def draw_from_ohlc(
    df: pd.DataFrame,
    stock_id: str,
    stock_name: str,
    save_path: str,
    *,
    already_normalized: bool = False,
) -> str:
    """橫式高低導航：價格列放 20 高／低／脫離／60低；量能列放量能異常、警告、月波動低。"""
    if df.empty:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    if already_normalized or "is_halt" in df.columns:
        work = df.copy()
    else:
        work, _notes = normalize_ohlc(df.copy(), db_path=None)
    work["dt"] = pd.to_datetime(work["date"].astype(str), format="%Y%m%d", errors="coerce")
    if work["dt"].isna().all():
        work["dt"] = pd.to_datetime(work["date"].astype(str), errors="coerce")
    work = work.dropna(subset=["dt"]).reset_index(drop=True)
    if work.empty:
        return ""
    if "is_halt" not in work.columns:
        work["is_halt"] = False
    n = len(work)
    xs = np.arange(n, dtype=float)
    halt = work["is_halt"].fillna(False).astype(bool)
    hi_s = work["high"].where(~halt)
    lo_s = work["low"].where(~halt)
    cl_s = work["close"].where(~halt)
    h20 = float(hi_s.tail(20).max())
    l20 = float(lo_s.tail(20).min())
    h60 = float(hi_s.tail(60).max())
    l60 = float(lo_s.tail(60).min())
    work["ma20"] = cl_s.rolling(20, min_periods=1).mean()
    work["vol_ma"] = work["volume"].where(~halt).rolling(20, min_periods=1).mean()
    tr = (work["high"] - work["low"]).where(~halt)
    work["atr20"] = tr.rolling(20, min_periods=5).mean()
    last = work.iloc[-1]
    span = max(float(hi_s.max()) - float(lo_s.min()), 1.0)

    # 時間軸橫向；畫布改橫幅，手機縮圖後日期軸才讀得下去。
    fig, (ax1, ax_sig, ax2) = plt.subplots(
        3,
        1,
        figsize=(12.8, 7.2),
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.15, 0.42, 1.35), hspace=0.04),
        facecolor="#ffffff",
    )
    # 箭頭一格一格往外疊，先把空間留出來，才不會被畫框切掉或互相壓住。
    arrow_h = span * 0.066
    arrow_gap = span * 0.020
    arrow_step = arrow_h * 1.18
    arrow_hw = 1.15
    ymin = float(lo_s.min()) - arrow_gap - 3 * arrow_step - span * 0.02
    ymax = float(hi_s.max()) + arrow_gap + 2 * arrow_step + span * 0.03
    ax1.axhspan(h20, ymax, color="#f8bbd0", alpha=0.38, zorder=0)
    ax1.axhspan(l20, h20, color="#fff9c4", alpha=0.32, zorder=0)
    ax1.axhspan(ymin, l20, color="#c8e6c9", alpha=0.38, zorder=0)
    ax1.set_ylim(ymin, ymax)
    ax1.set_xlim(-0.8, n - 0.2)

    was_20h = was_20l = was_60l = was_near_h = was_near_l = False
    from decision_card_signals import candle_up_taiwan

    candle_up = []
    for i in range(n):
        prev_c = float(work["close"].iloc[i - 1]) if i else None
        candle_up.append(
            candle_up_taiwan(float(work["close"].iloc[i]), prev_c, float(work["open"].iloc[i]))
        )
    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        x = xs[i]
        is_halt = bool(halt.iloc[i])
        color = "#e53935" if candle_up[i] else "#00897b"
        ax1.plot([x, x], [lo, hi], color="#bdbdbd" if is_halt else color, linewidth=1.05, zorder=3, solid_capstyle="round")
        body = max(abs(cl - op), span * 0.0018)
        ax1.add_patch(
            patches.Rectangle(
                (x - 0.32, min(op, cl)),
                0.64,
                body,
                facecolor="#eeeeee" if is_halt else color,
                edgecolor="#eeeeee" if is_halt else color,
                zorder=3,
            )
        )
        if is_halt:
            ax_sig.add_patch(patches.Rectangle((x - 0.42, 0.05), 0.84, 0.9, facecolor="#eceff1", edgecolor="#ffffff", lw=0.15, zorder=2))
            continue

        wick_h20 = float(hi_s.iloc[max(0, i - 19) : i + 1].max())
        wick_l20 = float(lo_s.iloc[max(0, i - 19) : i + 1].min())
        close_h20 = float(cl_s.iloc[max(0, i - 19) : i + 1].max())
        close_l20 = float(cl_s.iloc[max(0, i - 19) : i + 1].min())
        wick_l60 = float(lo_s.iloc[max(0, i - 59) : i + 1].min())
        ma20_i = float(work["ma20"].iloc[i] or 0)
        bias_i = ((cl - ma20_i) / ma20_i * 100.0) if ma20_i else 0.0
        hh, ll = close_h20, close_l20
        rsv = ((cl - ll) / (hh - ll) * 100.0) if hh > ll else 50.0
        is_20h = hi >= wick_h20 * 0.999 or cl >= close_h20 * 0.998
        is_20l = lo <= wick_l20 * 1.001 or cl <= close_l20 * 1.002
        is_60l = lo <= wick_l60 * 1.001
        leave_h = was_20h and not is_20h
        leave_l = was_20l and not is_20l
        vol_a = float(work["volume"].iloc[i] or 0) >= float(work["vol_ma"].iloc[i] or 1) * 2.0
        atr = float(work["atr20"].iloc[i] or 0)
        vol_low = bool(cl > 0 and atr / cl < 0.018)
        warn = rsv >= 80 or bias_i >= 8.0 or cl >= close_h20 * 0.99

        # 價格列只標「當天才發生」的事件：連續貼著高低的每一天都畫，箭頭就得縮小到看不清。
        # 期間有沒有連續，看 K 棒貼在哪一條帶就知道；逐日紀錄在決策卡的表裡。
        near_h = not is_20h and hi >= wick_h20 * 0.985
        near_l = not is_20l and lo <= wick_l20 * 1.015
        up_stack, dn_stack = [], []
        if is_20h and not was_20h:
            dn_stack.append(("h20", 1.0, False))
        elif near_h and not was_near_h:
            dn_stack.append(("h20_near", 0.72, True))
        if leave_h:
            dn_stack.append(("h20_leave", 1.06, False))
        if is_20l and not was_20l:
            up_stack.append(("l20", 1.0, False))
        elif near_l and not was_near_l:
            up_stack.append(("l20_near", 0.72, True))
        if leave_l:
            up_stack.append(("l20_leave", 1.06, False))
        if is_60l and not was_60l:
            up_stack.append(("l60", 1.06, False))
        for k, (kind, sc, hollow) in enumerate(dn_stack):
            tip = hi + arrow_gap + k * arrow_step
            _nav_arrow(ax1, tip, x, down=True, face=_nav_tone(kind, tip, h20, l20),
                       arrow_h=arrow_h * sc, hw=arrow_hw * sc, z=6 + k, hollow=hollow,
                       alpha=0.58 if hollow else 1.0)
        for k, (kind, sc, hollow) in enumerate(up_stack):
            tip = lo - arrow_gap - k * arrow_step
            _nav_arrow(ax1, tip, x, down=False, face=_nav_tone(kind, tip, h20, l20),
                       arrow_h=arrow_h * sc, hw=arrow_hw * sc, z=6 + k, hollow=hollow,
                       alpha=0.58 if hollow else 1.0)

        # 量能列：月波動底、警告▲、量能異常▲、月波動低▲ —— 即使價格列沒有對應箭頭也要畫
        # 底色只在月波動低時上色，其餘留白；原本三天一換的橘藍相間只是視覺噪音。
        if vol_low:
            ax_sig.add_patch(patches.Rectangle((x - 0.45, 0.08), 0.9, 0.84,
                                               facecolor="#90caf9", edgecolor="none", zorder=2))
        if warn:
            ax_sig.add_patch(patches.Rectangle((x - 0.45, 0.52), 0.9, 0.42,
                                               facecolor="#ffcdd2", edgecolor="none", alpha=0.62, zorder=1))
            _sig_arrow(ax_sig, x, 0.72, "#e53935", "#7f0000", scale=1.05, z=5)
        if vol_a:
            _sig_arrow(ax_sig, x, 0.38, "#6a1b9a", "#311b92", scale=1.22, z=6)
        elif vol_low:
            _sig_arrow(ax_sig, x, 0.38, "#ce93d8", "#6a1b9a", scale=0.78, z=4)

        was_20h, was_20l, was_60l = is_20h, is_20l, is_60l
        was_near_h, was_near_l = near_h, near_l

    ax1.plot(xs, work["ma20"], color="#f9a825", linewidth=1.85, zorder=4)
    ax1.axhline(h60, color="#f48fb1", linewidth=1.35)
    ax1.axhline(l60, color="#81c784", linewidth=1.35)
    ax1.axhline(h20, color="#f8bbd0", linewidth=1.05, linestyle="--")
    ax1.axhline(l20, color="#80deea", linewidth=1.05, linestyle="--")
    live_note = ""
    if "is_live" in work.columns and bool(pd.Series(work["is_live"]).fillna(False).iloc[-1]):
        t = str(work["_live_time"].iloc[-1] or "") if "_live_time" in work.columns else ""
        try:
            from live_quote import mis_session_label

            live_note = f"  ·{mis_session_label(t)}" + (f" {t[:5]}" if t else "")
        except Exception:
            live_note = "  ·盤中即時"
    ax1.set_title(
        f"{stock_id} {stock_name} (日K線) 180日區間 (季) 絕對高低點導航{live_note}   WayneBot ® 2026",
        fontproperties=_fp(14, "bold"),
        pad=6,
    )
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color="#bdbdbd", zorder=1)
    _draw_nav_legend(ax1)
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelsize=9)
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(9))
    ax1.text(
        0.004,
        0.985,
        f"Op:{_fmt_price(last['open'])}  Hi:{_fmt_price(last['high'])}  "
        f"Lo:{_fmt_price(last['low'])}  Cl:{_fmt_price(last['close'])}"
        f"    SMA(20): {_fmt_price(last['ma20'])}",
        transform=ax1.transAxes,
        ha="left",
        va="top",
        fontproperties=_fp(10, "bold"),
        color="#1b5e20",
        zorder=9,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="#e8f5e9", edgecolor="#a5d6a7", linewidth=0.6),
    )

    ax_sig.set_yticks([])
    ax_sig.set_ylim(0, 1)
    ax_sig.set_xlim(-0.8, n - 0.2)
    ax_sig.set_ylabel("量能\n訊號", fontproperties=_fp(7.5))
    ax_sig.tick_params(axis="x", labelbottom=False, length=0)

    vol_colors = ["#ef5350" if candle_up[i] else "#26a69a" for i in range(n)]
    ax2.bar(xs, work["volume"] / 1000.0, color=vol_colors, width=0.72, zorder=3)
    ax2.yaxis.tick_right()
    ax2.yaxis.set_label_position("right")
    ax2.tick_params(labelsize=9)
    ax2.set_xlim(-0.8, n - 0.2)
    ax2.text(
        0.006,
        0.92,
        f"Vol: {float(last['volume']) / 1000:.2f}K",
        transform=ax2.transAxes,
        fontproperties=_fp(10, "bold"),
        va="top",
        zorder=4,
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#eceff1", edgecolor="none"),
    )
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color="#bdbdbd")
    # 月份刻度
    months, mpos = [], []
    prev_m = None
    for i, dt in enumerate(work["dt"]):
        key = (dt.year, dt.month)
        if key != prev_m:
            months.append(dt.strftime("%b '%y"))
            mpos.append(i)
            prev_m = key
    ax2.set_xticks(mpos)
    ax2.set_xticklabels(months, fontproperties=_fp(9))
    for lab in ax2.get_yticklabels():
        lab.set_fontproperties(_fp(9))

    fig.subplots_adjust(left=0.03, right=0.96, top=0.90, bottom=0.11)
    fig.text(
        0.50,
        0.015,
        "K 線紅漲綠跌＝相對昨收（台股慣例）；價格列箭頭見圖上方圖例；箭頭壓在粉紅／綠色區時自動換深色，實心＝當日觸發、縮小＝連續中、空心＝接近　　"
        "量能列：紫↑量能異常　紅↑警告　淺紫↑月波動低　藍／杏塊＝月波動",
        ha="center",
        va="bottom",
        fontproperties=_fp(9, "bold"),
        color="#263238",
    )
    plt.savefig(save_path, dpi=140, facecolor="#ffffff")
    plt.close()
    return save_path


def generate_chart(
    stock_id: str,
    stock_name: str = "",
    db_path: str = None,
    save_path: str = None,
    df=None,
    *,
    already_normalized: bool = False,
) -> str:
    sid = str(stock_id).strip()
    if df is None or getattr(df, "empty", True):
        df = _load_ohlc(sid, db_path, 180)
        already_normalized = False
    else:
        df = df.tail(180).copy()
    if df.empty:
        return ""
    name = stock_name or str(df["stock_name"].iloc[-1] or sid)
    out = save_path or os.path.join(get_charts_dir(), f"{sid}.png")
    return draw_from_ohlc(
        df, sid, name, out, already_normalized=already_normalized
    )


@_mpl_serial
def render_decision_summary_png(card: dict, save_path: str) -> str:
    """窄圖 + 超大字：Telegram 會把圖縮成對話框寬，只有窄圖大 pt 才看得清。"""
    from matplotlib.patches import FancyBboxPatch

    code = str(card.get("stock_id") or "")
    name = str(card.get("stock_name") or "")
    close = card.get("close")
    chg = card.get("change_pct")
    profit = _latest_profit(card)
    dist = card.get("dist_h20")
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

    fig, ax = plt.subplots(figsize=(4.4, 3.7), dpi=200)
    fig.patch.set_facecolor("#F4F6FB")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0.03, 0.05),
            0.94,
            0.90,
            boxstyle="round,pad=0.02,rounding_size=0.04",
            facecolor="#FFFFFF",
            edgecolor="#D0D7E2",
            linewidth=1.4,
            transform=ax.transAxes,
        )
    )
    ax.text(0.08, 0.86, f"{code}  {name}", transform=ax.transAxes, fontproperties=_fp(20, "bold"),
            color="#111827", ha="left", va="center")
    ax.text(0.08, 0.58, _fmt_num(close, 2), transform=ax.transAxes, fontproperties=_fp(48, "bold"),
            color="#111827", ha="left", va="center")
    ax.text(0.08, 0.34, _fmt_pct(chg), transform=ax.transAxes, fontproperties=_fp(28, "bold"),
            color=_chg_color(chg), ha="left", va="center")
    ax.text(0.08, 0.16, f"獲利 {_fmt_pct(profit)}", transform=ax.transAxes, fontproperties=_fp(18, "bold"),
            color=_chg_color(profit), ha="left", va="center")
    ax.text(0.08, 0.07, f"距20日高 {_fmt_pct(dist)}", transform=ax.transAxes, fontproperties=_fp(18, "bold"),
            color=_chg_color(dist), ha="left", va="center")
    fig.savefig(save_path, dpi=200, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path


@_mpl_serial
def render_decision_table_png(card: dict, save_path: str, part: int = 1) -> str:
    """窄圖大字 20 日表。拆成兩張（各 4～5 欄），手機上才不會被壓成螞蟻字。"""
    from matplotlib.patches import FancyBboxPatch

    code = str(card.get("stock_id") or "")
    name = str(card.get("stock_name") or "")
    rows = _table_records(card)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n_rows = max(len(rows), 1)
    fig_h = 2.2 + n_rows * 0.42
    fig, ax = plt.subplots(figsize=(4.5, fig_h), dpi=200)
    fig.patch.set_facecolor("#F4F6FB")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0.015, 0.01),
            0.97,
            0.98,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor="#FFFFFF",
            edgecolor="#D0D7E2",
            linewidth=1.2,
            transform=ax.transAxes,
        )
    )
    title = f"{code} {name}  ·  20日表 {part}/2"
    ax.text(0.05, 0.965, title, transform=ax.transAxes, fontproperties=_fp(16, "bold"),
            color="#111827", ha="left", va="center")

    if part == 1:
        headers = ["日期", "股價", "獲利", "預警"]
        col_x = [0.10, 0.34, 0.58, 0.82]
    else:
        headers = ["日期", "溫度", "月乖離", "量排名"]
        col_x = [0.10, 0.36, 0.60, 0.84]

    y0, y1 = 0.925, 0.03
    row_h = (y0 - y1) / (n_rows + 1.2)
    for i, h in enumerate(headers):
        ax.text(col_x[i], y0 - row_h * 0.4, h, transform=ax.transAxes, fontproperties=_fp(14, "bold"),
                color="#4B5563", ha="center", va="center")
    ax.plot([0.04, 0.96], [y0 - row_h * 0.82, y0 - row_h * 0.82], color="#D1D5DB",
            linewidth=1.0, transform=ax.transAxes)

    for r, row in enumerate(rows):
        y = y0 - row_h * (r + 1.55)
        bg = "#EEF2FF" if r % 2 == 0 else "#FFFFFF"
        ax.add_patch(
            FancyBboxPatch(
                (0.03, y - row_h * 0.42),
                0.94,
                row_h * 0.84,
                boxstyle="square,pad=0",
                facecolor=bg,
                edgecolor="none",
                transform=ax.transAxes,
                zorder=0,
            )
        )
        date_s = _fmt_md(row.get("date"))
        if len(date_s) >= 5:
            date_s = date_s[-5:]
        profit = row.get("profit_pct")
        hl = str(row.get("高低") or "—")
        from decision_card_signals import display_alert_cell

        warn = display_alert_cell(str(row.get("預警") or "—"), hl)
        temp = _temp_num(row.get("溫度計"))
        bias = row.get("bias_monthly")
        volr = row.get("vol_rank_120")
        if part == 1:
            base = _CARD["white"]
            _, warn_fg = alert_cell_style(warn, base)
            _, prof_fg = profit_cell_style(profit, None, base)
            vals = [
                (date_s, _CARD["ink"]),
                (_fmt_num(row.get("close"), 2), _CARD["ink"]),
                (_fmt_pct(profit), prof_fg),
                (warn, warn_fg),
            ]
        else:
            base = _CARD["white"]
            _, bias_fg = bias_cell_style(bias, base)
            _, vol_fg = vol_rank_cell_style(volr, base)
            vals = [
                (date_s, _CARD["ink"]),
                (_fmt_num(temp, 0) if temp is not None else "—", temp_cell_style(temp, base)[1]),
                (_fmt_pct(bias), bias_fg),
                (_fmt_num(volr, 0) if volr is not None else "—", vol_fg),
            ]
        for i, (txt, color) in enumerate(vals):
            ax.text(col_x[i], y, txt, transform=ax.transAxes, fontproperties=_fp(20, "bold"),
                    color=color, ha="center", va="center", zorder=1)

    fig.savefig(save_path, dpi=200, bbox_inches="tight", pad_inches=0.06, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path


def generate_card_image(stock_id: str, db_path: str = None, save_path: str = None) -> list:
    sid = str(stock_id).strip()
    engine = NavigatorEngine(db_path or get_db_path())
    card = engine.get_decision_card(sid, lookback=20)
    if card.get("error"):
        return []
    base = save_path or os.path.join(get_charts_dir(), f"{sid}_card.png")
    path = render_decision_card_png(card, base)
    return [path] if path else []


def render_stock_pack(stock_id: str, db_path: str = None, charts_dir: str = None) -> dict:
    """看這檔：決策卡只算一次，介紹圖／高低卡／導航／籌碼一次產出。"""
    sid = str(stock_id).strip()
    db_path = db_path or get_db_path()
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    engine = NavigatorEngine(db_path)
    card = engine.get_decision_card(sid, lookback=20)
    if card.get("error"):
        return {
            "error": card.get("error"),
            "card": card,
            "glance": "",
            "cards": [],
            "chart": "",
            "chips": "",
        }
    ohlc = card.pop("_ohlc", None)
    tape = {}
    try:
        from chip_tape import build_tape

        tape = build_tape(db_path, sid) or {}
    except Exception:
        tape = {}
    glance = render_first_glance_png(
        sid, card, tape, os.path.join(charts_dir, f"{sid}_glance.png"), db_path=db_path
    ) or ""
    card_path = render_decision_card_png(card, os.path.join(charts_dir, f"{sid}_card.png")) or ""
    chart = generate_chart(
        sid, "", db_path, os.path.join(charts_dir, f"{sid}.png"), ohlc, already_normalized=True
    ) or ""
    chips = ""
    try:
        from chips import generate_chips_image

        chips = generate_chips_image(sid, db_path, os.path.join(charts_dir, f"{sid}_chips.png")) or ""
    except Exception:
        chips = ""
    return {
        "card": card,
        "tape": tape,
        "glance": glance,
        "cards": [card_path] if card_path else [],
        "chart": chart,
        "chips": chips,
    }


def generate_card_with_chart(stock_id: str, db_path: str = None, charts_dir: str = None):
    sid = str(stock_id).strip()
    pack = render_stock_pack(sid, db_path, charts_dir)
    html = generate_decision_card(sid, db_path, lookback=20)
    return html, pack.get("cards") or [], pack.get("chart") or "", pack.get("glance") or ""
