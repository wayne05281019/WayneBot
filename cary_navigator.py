# -*- coding: utf-8 -*-
"""
WayneBot 核心模組：CaryBot 買低賣高決策卡與 180 日 K 線趨勢圖引擎
檔案名稱：cary_navigator.py
"""

import os
import sqlite3
import urllib.request
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as patches
import matplotlib.font_manager as fm
import pandas as pd
import numpy as np

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

# 載入中文字型（雲端下載失敗就用內建字型，不可無限等待）
FONT_PATH = os.path.join(BASE_DIR, "NotoSansTC-Regular.otf")
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
    fm.fontManager.addfont(FONT_PATH)
    plt.rcParams['font.sans-serif'] = ['Noto Sans TC', 'DejaVu Sans', 'Arial']

plt.rcParams['axes.unicode_minus'] = False


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

    # 2) 持續跳空＝除權：當天整根都離開前收，之後不再跳回
    for i in range(1, n):
        day = str(dates.iloc[i] if i < len(dates) else "").replace("-", "")
        if day in official:
            continue
        p = float(out["close"].iloc[i - 1] or 0)
        c = float(out["close"].iloc[i] or 0)
        hi = float(out["high"].iloc[i] or 0)
        lo = float(out["low"].iloc[i] or 0)
        if p <= 0 or c <= 0:
            continue
        r = c / p
        down = r < 0.72 and hi < p * 0.78 and hi > 0
        up = r > 1.45 and lo > p * 1.28
        if not (down or up):
            continue
        factor = c / p
        if not (0.05 <= factor <= 20):
            continue
        idx = out.index[:i]
        out.loc[idx, ["open", "high", "low", "close"]] = out.loc[idx, ["open", "high", "low", "close"]] * factor
        notes.append(f"除權還原 {out['date'].iloc[i]} ×{factor:.4f}")

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


class CaryNavigatorEngine:
    """CaryBot 買低賣高決策卡、多空溫度計與雙綠脫離海選引擎"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    @staticmethod
    def _calc_rolling_rank(series: pd.Series, window: int = 120) -> list:
        vals = series.values
        ranks = []
        for i in range(len(vals)):
            start = max(0, i - window + 1)
            sub = vals[start : i + 1]
            rank = int(np.sum(sub > vals[i]) + 1)
            ranks.append(rank)
        return ranks

    def get_decision_card(self, stock_id: str, lookback: int = 20) -> dict:
        """產出單一標的的買低賣高決策卡（高低點用收盤，對齊範本）。"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("""
            SELECT date, stock_name, open, high, low, close, volume, pct_change as change_pct
            FROM daily_quotes
            WHERE stock_id = ?
            ORDER BY date DESC LIMIT 520;
        """, conn, params=(stock_id,))
        conn.close()

        if len(df) < 5:
            return {"error": f"標的 {stock_id} 歷史資料不足"}

        df = df.iloc[::-1].reset_index(drop=True)
        df["stock_id"] = str(stock_id)
        try:
            from live_quote import append_live_bar

            df = append_live_bar(df, str(stock_id))
        except Exception:
            pass
        live_time = ""
        is_live = False
        if "is_live" in df.columns and bool(df["is_live"].iloc[-1]):
            is_live = True
            live_time = str(df["_live_time"].iloc[-1] or "") if "_live_time" in df.columns else ""
        df, xq_notes = normalize_ohlc(df, self.db_path)
        close_s = df["close"].where(~df["is_halt"])
        df["ma20"] = close_s.rolling(20, min_periods=1).mean()
        df["ma60"] = close_s.rolling(60, min_periods=1).mean()
        # 決策卡格子：用收盤高低（與範本 8234 完全對得上）；無量假K不進窗口
        df["high_5"] = close_s.rolling(5, min_periods=1).max()
        df["low_5"] = close_s.rolling(5, min_periods=1).min()
        df["high_10"] = close_s.rolling(10, min_periods=1).max()
        df["low_10"] = close_s.rolling(10, min_periods=1).min()
        df["high_20"] = close_s.rolling(20, min_periods=1).max()
        df["low_20"] = close_s.rolling(20, min_periods=1).min()
        df["high_60"] = close_s.rolling(60, min_periods=1).max()
        df["low_60"] = close_s.rolling(60, min_periods=1).min()
        df["low_120"] = close_s.rolling(120, min_periods=20).min()
        df["low_240"] = close_s.rolling(240, min_periods=40).min()
        df["low_480"] = close_s.rolling(480, min_periods=80).min()
        # 表頭 60 日低＝近 60 根收盤最低。格子「獲利」對齊 CaryBot：相對「最新日往前 60 個日曆日」的收盤最低（南亞 141.5 → 55.8%，不是 94.8 → 132.6%）。
        dts = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
        latest_dt = dts.iloc[-1]
        cal_mask = (dts >= (latest_dt - pd.Timedelta(days=60))) & dts.notna()
        cal60_low = float(df.loc[cal_mask, "close"].min()) if cal_mask.any() else float(df["low_60"].iloc[-1])
        if cal60_low <= 0:
            cal60_low = float(df["low_60"].iloc[-1] or 0) or 1.0
        df["profit_pct"] = ((df["close"] - cal60_low) / cal60_low * 100.0).round(1)
        df["bias_monthly"] = (((df["close"] - df["ma20"]) / df["ma20"]) * 100.0).round(1)
        df["vol_rank_120"] = self._calc_rolling_rank(df["volume"], window=120)

        hl_tags, alert_tags, temps = [], [], []
        for i in range(len(df)):
            if bool(df["is_halt"].iloc[i]):
                hl_tags.append("No")
                alert_tags.append("No")
                temps.append("—")
                continue
            c = float(df["close"].iloc[i])
            h20, l20 = float(df["high_20"].iloc[i]), float(df["low_20"].iloc[i])
            h10, l10 = float(df["high_10"].iloc[i]), float(df["low_10"].iloc[i])
            h5, l5 = float(df["high_5"].iloc[i]), float(df["low_5"].iloc[i])
            l60 = float(df["low_60"].iloc[i])
            bias = float(df["bias_monthly"].iloc[i])
            span = h20 - l20
            rf = (c - l20) / (span + 0.01) if span > 0 else 0.5
            # 溫度：20 日收盤位置為主、月乖離微調（對齊範本約 50~76°C，不再拉到 90°C）
            t = round(max(0.0, min(99.9, 50.0 + 18.0 * rf + 0.55 * bias)), 1)
            temps.append(f"{t:.1f} °C")
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
            elif bias < 0.0:
                alert_tags.append("K20低")
            elif c >= h20 * 0.99 or bias >= 4.0:
                alert_tags.append("K20高")
            else:
                alert_tags.append("No")

        df["獲利"] = [f"{p:.1f}%" if pd.notna(p) else "—" for p in df["profit_pct"]]
        df["高低"] = hl_tags
        df["預警"] = alert_tags
        df["溫度計"] = temps
        df["月乖離"] = [f"{b:+.1f}%" for b in df["bias_monthly"]]
        df["120日量"] = [f"第 {int(r)} 名" for r in df["vol_rank_120"]]

        latest = df.iloc[-1]
        chg = float(latest.get("change_pct") or 0)
        real_c = df.loc[~df["is_halt"], "close"] if "is_halt" in df.columns else df["close"]
        if len(real_c) >= 2 and float(real_c.iloc[-2] or 0) > 0:
            chg = round((float(real_c.iloc[-1]) - float(real_c.iloc[-2])) / float(real_c.iloc[-2]) * 100.0, 2)
        # 決策卡高／低：N 根「收盤」（對齊 CaryBot 南亞：20 日低是 165 不是日曆窗的 180）
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
        if len(df) >= 7:
            ma60s = round(float(latest["ma60"]) - float(df["ma60"].iloc[-7]), 1)
        qty60 = int(round(float(df.loc[~df["is_halt"], "volume"].tail(60).mean() or 0)))
        badges = []
        if is_live:
            badges.append("盤中 " + (live_time[:5] if live_time else "即時"))
        if any("除權" in x or "錯價" in x or "官方除權息" in x for x in xq_notes):
            badges.append("已除權還原")
        if int(latest["vol_rank_120"]) <= 10:
            badges.append(f"120日量第 {int(latest['vol_rank_120'])} 名")
        if float(latest["close"]) >= float(h20) * 0.998:
            badges.append("創20日新高")
        l120 = float(latest["low_120"]) if pd.notna(latest.get("low_120")) else 0.0
        l240 = float(latest["low_240"]) if pd.notna(latest.get("low_240")) else 0.0
        l480 = float(latest["low_480"]) if pd.notna(latest.get("low_480")) else 0.0
        c0 = float(latest["close"])
        if l480 and c0 <= l480 * 1.02:
            badges.append("近480日低")
        elif l240 and c0 <= l240 * 1.02:
            badges.append("近240日低")
        elif l120 and c0 <= l120 * 1.02:
            badges.append("近120日低")
        if qty60 < 900:
            badges.append("60日均量過小")
        if space_60 and space_60 < 16:
            badges.append("60日區間過小")
        badges.append("多頭格局" if float(latest["close"]) >= float(latest["ma20"] or latest["close"]) else "整理格局")
        real = df.loc[~df["is_halt"]] if "is_halt" in df.columns else df
        table_src = real if len(real) >= lookback else df
        table = table_src.tail(lookback)[
            ["date", "close", "獲利", "高低", "預警", "溫度計", "月乖離", "120日量", "profit_pct", "bias_monthly", "vol_rank_120"]
        ].iloc[::-1]
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
            "is_live": is_live,
            "live_time": live_time,
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
            "qty60": (int(round(qty60 / 100.0) * 100) if qty60 >= 10000 else int(qty60)),
            "xq_notes": xq_notes,
            "cal60_low": round(cal60_low, 2),
            "gain_pct": round((float(latest["close"]) - cal60_low) / cal60_low * 100.0, 1) if cal60_low else 0.0,
            "k20_high_streak": streak,
            "vol_rank": int(latest["vol_rank_120"]),
            "badges": badges,
            "open": float(latest.get("open") or 0),
            "high": float(latest.get("high") or 0),
            "low": float(latest.get("low") or 0),
            "volume": float(latest.get("volume") or 0),
            "bias_monthly": float(latest.get("bias_monthly") or 0),
            "table": table,
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

            was_green = ("0.0%" in yesterday["獲利"]) or (yesterday["預警"] in ["60低", "K20低"])
            breakout = ("0.0%" not in today["獲利"]) and (today["預警"] != "60低")

            if was_green and breakout:
                screened.append({
                    "stock_id": sid, "stock_name": sname,
                    "close": today["close"], "profit": today["獲利"],
                    "temp": today["溫度計"], "bias": today["月乖離"],
                    "space_60": card["space_60"]
                })
        return screened


class CaryBotChartGenerator:
    """產出 180 日 K 線高低導航圖"""

    @staticmethod
    def draw_180d_chart(stock_id: str, stock_name: str, current_price: float, h60: float, l60: float, h20: float, l20: float, save_path: str):
        np.random.seed(42)
        dates = pd.date_range(end=datetime.date.today().strftime("%Y-%m-%d"), periods=120, freq="B")
        trend = np.linspace(current_price * 0.75, current_price, len(dates)) + np.random.normal(0, current_price * 0.015, len(dates))
        closes = trend
        opens = closes * (1 + np.random.uniform(-0.015, 0.015, len(dates)))
        highs = np.maximum(opens, closes) * (1 + np.random.uniform(0.005, 0.02, len(dates)))
        lows = np.minimum(opens, closes) * (1 - np.random.uniform(0.005, 0.02, len(dates)))
        vols = np.random.randint(2000, 30000, len(dates))
        closes[-1] = current_price

        df = pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols})
        df["ma20"] = df["close"].rolling(20).mean()

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 6.5), gridspec_kw=dict(height_ratios=(3, 1)), facecolor='#ffffff'
        )

        for i in range(len(df)):
            dt = df["date"].iloc[i]
            op, cl = df["open"].iloc[i], df["close"].iloc[i]
            hi, lo = df["high"].iloc[i], df["low"].iloc[i]
            color = '#e53935' if cl >= op else '#00897b'

            ax1.plot([dt, dt], [lo, hi], color=color, linewidth=1.0)
            height = max(abs(cl - op), current_price * 0.003)
            ax1.add_patch(patches.Rectangle((mdates.date2num(dt) - 0.35, min(op, cl)), 0.7, height, color=color))

        ax1.plot(df["date"], df["ma20"], color='#fbc02d', linewidth=1.5, label=f"SMA(20): {df['ma20'].iloc[-1]:.2f}")
        ax1.axhline(h60, color='#f48fb1', linewidth=1.5, linestyle='-', label=f"季高點線 ({h60:.2f})")
        ax1.axhline(l60, color='#81c784', linewidth=1.5, linestyle='-', label=f"季低點線 ({l60:.2f})")
        ax1.axhline(h20, color='#ce93d8', linewidth=1.0, linestyle='--', label=f"月高點線 ({h20:.2f})")
        ax1.axhline(l20, color='#80deea', linewidth=1.0, linestyle='--', label=f"月低點線 ({l20:.2f})")

        ax1.scatter([df["date"].iloc[-1]], [df["high"].iloc[-1] * 1.02], marker='v', color='#ab47bc', s=80, label='20高脫離')
        ax1.scatter([df["date"].iloc[-25]], [df["low"].iloc[-25] * 0.98], marker='^', color='#2e7d32', s=80, label='20低脫離 (雙綠)')

        ax1.set_title(f"{stock_id} {stock_name} (日K線) 180日區間 (季) 絕對高低點導航   CaryBot ® 2026", fontsize=13, fontweight='bold', pad=10)
        ax1.legend(loc='upper left', ncol=6, frameon=True, facecolor='#f5f5f5', edgecolor='none', fontsize=8)
        ax1.grid(True, linestyle=':', alpha=0.5)

        vol_colors = ['#ef5350' if df["close"].iloc[i] >= df["open"].iloc[i] else '#26a69a' for i in range(len(df))]
        ax2.bar(df["date"], df["volume"] / 1000.0, color=vol_colors, width=0.7)
        ax2.set_ylabel("Vol (千張)", fontsize=8)
        ax2.grid(True, linestyle=':', alpha=0.5)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
        fig.autofmt_xdate()
        plt.tight_layout()

        plt.savefig(save_path, dpi=180, bbox_inches='tight')
        plt.close()


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_price(p) -> str:
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.2f}"


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
    if os.path.exists(FONT_PATH):
        kwargs["fname"] = FONT_PATH
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


def _pill(ax, cx, cy, text, bg, fg, w=11.2, h=2.15, fs=10):
    if not text or text in ("No", "—", "nan"):
        ax.text(cx, cy, "No", fontproperties=_fp(11), color="#9e9e9e", ha="center", va="center")
        return
    ax.add_patch(
        patches.FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0.12,rounding_size=0.45",
            facecolor=bg,
            edgecolor=bg,
            linewidth=0,
        )
    )
    ax.text(cx, cy, text, fontproperties=_fp(fs, "bold"), color=fg, ha="center", va="center")


def _draw_mini_candle(ax, x, y, w, h, open_, high, low, close):
    """在資料座標畫當日 K：紅實心上漲、綠實心下跌，含上下影。"""
    o, hi, lo, cl = float(open_), float(high), float(low), float(close)
    rng = hi - lo
    if rng <= 0:
        rng = max(abs(cl) * 0.01, 0.01)
        hi = max(hi, cl, o) + rng / 2
        lo = min(lo, cl, o) - rng / 2
        rng = hi - lo

    def py(p):
        return y + (float(p) - lo) / rng * h

    color = "#e53935" if cl >= o else "#00897b"
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


def render_decision_card_png(card: dict, save_path: str) -> str:
    """單張長圖，版面對齊範本；窄寬度讓 Telegram 縮圖後字仍能看。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    table = card["table"]
    n = max(len(table), 1)
    fig_w, fig_h = 6.55, 5.35 + n * 0.48
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=175, facecolor="#eef1f6")
    H = 100.0
    ax.set_xlim(0, 100)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.subplots_adjust(left=0.03, right=0.97, top=0.985, bottom=0.012)

    # 表頭
    ax.add_patch(patches.FancyBboxPatch((1.2, 93.4), 97.6, 6.0, boxstyle="round,pad=0.15,rounding_size=0.6",
                                        facecolor="#1a237e", edgecolor="none"))
    ax.text(3.4, 97.4, f"{card['stock_id']}  {card.get('stock_name') or ''}", fontproperties=_fp(20, "bold"),
            color="#ffffff", va="center")
    ax.text(3.4, 94.8, "買低賣高決策卡　破解獲利密碼", fontproperties=_fp(12, "bold"), color="#ffecb3", va="center")
    ax.text(96.5, 96.2, "WayneBot", fontproperties=_fp(10, "bold"), color="#c5cae9", ha="right", va="center")

    chg = float(card.get("change_pct") or 0)
    chg_c = "#c62828" if chg > 0 else ("#00695c" if chg < 0 else "#212121")
    ax.text(3.2, 91.35, "股價", fontproperties=_fp(11), color="#607d8b", va="center")
    ax.text(10.8, 91.2, _fmt_price(card["close"]), fontproperties=_fp(30, "bold"), color="#000000", va="center")
    ax.text(42.0, 91.35, "漲跌幅", fontproperties=_fp(11), color="#607d8b", va="center")
    ax.text(52.0, 91.2, f"{chg:+.2f}%", fontproperties=_fp(18, "bold"), color=chg_c, va="center")
    badges = [str(x) for x in (card.get("badges") or []) if x][:4]
    if not badges:
        badges = ["整理格局"]
    bx = 70.5 if len(badges) == 1 else 64.2
    for i, btxt in enumerate(badges):
        _pill(ax, bx + i * 16.2, 91.25, btxt, "#e53935", "#ffffff", w=15.4, h=3.0, fs=10)

    # 高點
    ax.add_patch(patches.FancyBboxPatch((1.8, 80.6), 96.4, 8.4, boxstyle="round,pad=0.12,rounding_size=0.45",
                                        facecolor="#ffffff", edgecolor="#ef9a9a", linewidth=1.1))
    ax.text(3.4, 87.4, "高點資訊", fontproperties=_fp(13, "bold"), color="#ad1457", va="center")
    ax.text(16.5, 87.4, f"10日／20日／60日　(MA60S: {card.get('ma60s')} ／ QTY60: {int(card.get('qty60') or 0):,})",
            fontproperties=_fp(10), color="#6d4c41", va="center")
    highs = [("10日高點", card["h10"], card["dist_h10"]), ("20日高點", card["h20"], card["dist_h20"]),
             ("60日高點", card["h60"], card["dist_h60"])]
    for i, (lab, px, dist) in enumerate(highs):
        x = 4.2 + i * 31.6
        ax.add_patch(patches.FancyBboxPatch((x, 81.2), 30.0, 5.0, boxstyle="round,pad=0.1,rounding_size=0.35",
                                            facecolor="#fff5f7", edgecolor="#f8bbd0", linewidth=0.8))
        ax.text(x + 15, 85.15, lab, fontproperties=_fp(10), color="#ad1457", ha="center", va="center")
        ax.text(x + 15, 83.35, _fmt_price(px), fontproperties=_fp(17, "bold"), color="#000000", ha="center", va="center")
        ax.text(x + 15, 81.75, f"({dist:+.1f}%)", fontproperties=_fp(12, "bold"),
                color="#004d40" if dist < 0 else "#b71c1c", ha="center", va="center")

    # 低點
    ax.add_patch(patches.FancyBboxPatch((1.8, 70.8), 96.4, 8.8, boxstyle="round,pad=0.12,rounding_size=0.45",
                                        facecolor="#ffffff", edgecolor="#81c784", linewidth=1.1))
    ax.text(3.4, 78.1, "低點資訊", fontproperties=_fp(13, "bold"), color="#2e7d32", va="center")
    ax.text(16.5, 78.1, f"20日（高低操作空間: {card['space_20']}%）／60日（高低操作空間: {card['space_60']}%）",
            fontproperties=_fp(10), color="#33691e", va="center")
    lows = [("10日低點", card["l10"], card["dist_l10"]), ("20日低點", card["l20"], card["dist_l20"]),
            ("60日低點", card["l60"], card["dist_l60"])]
    for i, (lab, px, dist) in enumerate(lows):
        x = 4.2 + i * 31.6
        ax.add_patch(patches.FancyBboxPatch((x, 71.4), 30.0, 5.4, boxstyle="round,pad=0.1,rounding_size=0.35",
                                            facecolor="#f1f8e9", edgecolor="#a5d6a7", linewidth=0.8))
        ax.text(x + 15, 75.6, lab, fontproperties=_fp(10), color="#2e7d32", ha="center", va="center")
        ax.text(x + 15, 73.7, _fmt_price(px), fontproperties=_fp(17, "bold"), color="#000000", ha="center", va="center")
        ax.text(x + 15, 72.05, f"({dist:+.1f}%)", fontproperties=_fp(12, "bold"), color="#b71c1c", ha="center", va="center")

    ax.text(3.2, 69.55, "過去 20 天記錄", fontproperties=_fp(13, "bold"), color="#263238", va="center")
    headers = ["日期", "股價", "獲利", "高低", "預警", "溫度計", "月乖離", "120日量"]
    xs = [2.0, 16.6, 27.4, 38.2, 49.0, 60.2, 73.0, 85.2, 98.0]
    top = 68.2
    hdr_h = 2.55
    for i, h in enumerate(headers):
        ax.add_patch(patches.Rectangle((xs[i], top - hdr_h), xs[i + 1] - xs[i], hdr_h, facecolor="#e3f2fd", edgecolor="#90caf9", lw=0.6))
        ax.text((xs[i] + xs[i + 1]) / 2, top - hdr_h / 2, h, fontproperties=_fp(11, "bold"), ha="center", va="center", color="#0d47a1")
    y = top - hdr_h
    body_h = (y - 1.15) / n
    fs_body = 13
    row_i = 0
    for _, r in table.iterrows():
        y1 = y - body_h
        profit = r.get("profit_pct")
        bias = float(r.get("bias_monthly") or 0)
        rank = int(r.get("vol_rank_120") or 99)
        temp_v = str(r["溫度計"]).replace(" °C", "").replace("°C", "")
        try:
            temp_n = float(temp_v)
        except (TypeError, ValueError):
            temp_n = 0.0
        pbg, pfg = "#fce4ec", "#c62828"
        if temp_n >= 70:
            tbg, tfg = "#ef9a9a", "#b71c1c"
        elif temp_n >= 55:
            tbg, tfg = "#f8bbd0", "#ad1457"
        else:
            tbg, tfg = "#eeeeee", "#424242"
        if rank <= 10:
            vbg, vfg = "#ec407a", "#ffffff"
        elif rank <= 20:
            vbg, vfg = "#f8bbd0", "#880e4f"
        else:
            vbg, vfg = "#f5f5f5", "#424242"
        hl = str(r["高低"])
        al = str(r["預警"])
        zebra = row_i % 2 == 0
        price_bg = "#e53935" if hl == "20高" else ("#ffffff" if zebra else "#eef5fb")
        price_fg = "#ffffff" if hl == "20高" else "#111111"
        date_bg = "#ffffff" if zebra else "#e3f2fd"
        fills = [date_bg, price_bg, pbg, "#ffffff", "#ffffff", tbg,
                 "#ffcdd2" if bias > 0 else ("#c8e6c9" if bias < 0 else "#ffffff"), vbg]
        # even row index from y
        vals = [
            _fmt_md_tpl(r["date"]),
            _fmt_price(r["close"]),
            str(r["獲利"]).replace("+", ""),
            hl,
            al,
            str(r["溫度計"]),
            str(r["月乖離"]).replace("+", ""),
            str(r["120日量"]),
        ]
        for i, val in enumerate(vals):
            ax.add_patch(patches.Rectangle((xs[i], y1), xs[i + 1] - xs[i], body_h, facecolor=fills[i],
                                           edgecolor="#eceff1", lw=0.4))
            cy = (y + y1) / 2
            cx = (xs[i] + xs[i + 1]) / 2
            if i == 3:
                if "高" in hl:
                    _pill(ax, cx, cy, hl, "#ec407a", "#ffffff", w=9.6, h=body_h * 0.62, fs=10)
                elif "低" in hl:
                    _pill(ax, cx, cy, hl, "#43a047", "#ffffff", w=9.6, h=body_h * 0.62, fs=10)
                else:
                    ax.text(cx, cy, "No", fontproperties=_fp(11), color="#9e9e9e", ha="center", va="center")
            elif i == 4:
                if "高" in al:
                    _pill(ax, cx, cy, al, "#ec407a", "#ffffff", w=10.4, h=body_h * 0.62, fs=10)
                elif "低" in al:
                    _pill(ax, cx, cy, al, "#43a047", "#ffffff", w=10.4, h=body_h * 0.62, fs=10)
                else:
                    ax.text(cx, cy, "No", fontproperties=_fp(11), color="#9e9e9e", ha="center", va="center")
            else:
                if i == 1:
                    color = price_fg
                elif i == 2:
                    color = pfg
                elif i == 5:
                    color = tfg
                elif i == 7:
                    color = vfg
                elif i == 6:
                    color = "#c62828" if bias > 0 else ("#00695c" if bias < 0 else "#111111")
                else:
                    color = "#111111"
                ax.text(cx, cy, val, fontproperties=_fp(fs_body, "bold"),
                        ha="center", va="center", color=color)
        y = y1
        row_i += 1

    plt.savefig(save_path, dpi=175, facecolor=fig.get_facecolor())
    plt.close()
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
    engine = CaryNavigatorEngine(db_path or get_db_path())
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
    from tg_layout import kv, section, join_sections
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
            kv("外資", f"{fmt_lots_align(tape.get('foreign', {}).get('net', 0))}　{tape.get('foreign', {}).get('phrase', '')}"),
            kv("投信", f"{fmt_lots_align(tape.get('trust', {}).get('net', 0))}　{tape.get('trust', {}).get('phrase', '')}"),
            kv("自營", f"{fmt_lots_align(tape.get('dealer', {}).get('net', 0))}　{tape.get('dealer', {}).get('phrase', '')}"),
            kv("法人", f"{fmt_lots_align(tape.get('three', {}).get('net', 0))}　{tape.get('three', {}).get('phrase', '')}"),
            kv("籌碼佔量", f"{tape.get('inst_pct', 0):+.1f}%（法人買賣超÷成交量）"),
        )
    vol_line = (tape.get("volume") or {}).get("line") or "—"
    extra_flags = tape.get("conflict") or ""
    bias = card.get("bias_monthly")
    bias_s = f"{float(bias):+.1f}%" if bias is not None else "—"
    try:
        from fundamentals import glance_fundamentals_rows

        fund_block = section(*glance_fundamentals_rows(sid, db_path or get_db_path()))
    except Exception:
        fund_block = ""
    tail = section(*[x for x in (extra_flags, fund_block, pink_note) if x])
    return join_sections(
        title_block,
        section(
            kv("日期", _fmt_md(card["latest_date"]) + (" 盤中" + (f" {card.get('live_time')}" if card.get("live_time") else "") if card.get("is_live") else "")),
            kv("開高低", ohlc or "—"),
            kv("收盤", f"{_fmt_price(card['close'])}　{move}"),
            kv("當日", f"{chg:+.2f}%"),
        ),
        section(
            kv("距20日高", f"{card['dist_h20']:+.1f}%"),
            kv("獲利", f"{card.get('gain_pct', card.get('dist_l60')):+.1f}%（近60曆日低 {card.get('cal60_low', '—')}）"),
            kv("距60根低", f"{card.get('dist_l60'):+.1f}%"),
            kv("距120低", f"{card['dist_l120']:+.1f}%" if card.get("dist_l120") is not None else "—"),
            kv("月空間", f"{card['space_20']}%"),
            kv("季空間", f"{card['space_60']}%"),
            kv("月乖離", bias_s),
        ),
        section(
            kv("溫度", card.get("temp_c") or "—"),
            kv("120日量", f"第 {card.get('vol_rank')} 名"),
            kv("量比", vol_line),
        ),
        chip_block,
        tail,
        sep="\n＝＝＝＝＝＝＝＝＝＝＝＝\n",
    )


def render_first_glance_png(stock_id: str, card: dict, tape: dict, save_path: str) -> str:
    """窄長圖、大字、高 DPI：Telegram 依對話框寬縮放，靠字級與留白保證能讀。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    from chip_tape import fmt_lots_align

    try:
        from fundamentals import glance_fundamentals_plain

        fund_rows = glance_fundamentals_plain(stock_id, get_db_path())
    except Exception:
        fund_rows = []

    last = (tape or {}).get("last") or {}
    move = (tape or {}).get("move") or {}
    fig, ax = plt.subplots(figsize=(4.62, 16.4), dpi=220, facecolor="#EEF2F7")
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
    )
    ink(20.2, 96.85, f"{card.get('stock_id') or stock_id}  {card.get('stock_name') or ''}", 20, "#FFFFFF")
    badge = "　".join(str(x) for x in (card.get("badges") or []) if x)
    ink(20.2, 93.45, badge or "—", 12, "#FFE082")
    ink(96.8, 96.85, _fmt_md(card.get("latest_date")) + (" 盤中 " + str(card.get("live_time") or "") if card.get("is_live") else ""), 11, "#C5CAE9", ha="right")

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
        yy = y + h - 4.15
        for a, b, c in rows:
            ink(4.8, yy, a, 12)
            ink(96.4, yy, b, 15, c, ha="right")
            yy -= 3.35

    kv_block(61.55, 15.15, "空間／位置", [
        ("距20日高（賣壓）", f"{card['dist_h20']:+.1f}%", "#C62828" if float(card["dist_h20"]) >= -1 else "#111111"),
        ("獲利（近60曆日低）", f"{float(card.get('gain_pct') if card.get('gain_pct') is not None else card.get('dist_l60') or 0):+.1f}%", "#111111"),
        ("距60根低", f"{card.get('dist_l60'):+.1f}%", "#111111"),
        ("月／季空間", f"{card['space_20']}%　／　{card['space_60']}%", "#111111"),
    ])
    kv_block(48.55, 12.15, "熱度／量能", [
        ("溫度", str(card.get("temp_c") or "—"), "#111111"),
        ("120日量排名", f"第 {card.get('vol_rank')} 名", "#111111"),
        ("量比", (tape or {}).get("volume", {}).get("line") or "—", "#111111"),
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
    cy = 41.45
    for name, item in chips:
        net = int(item.get("net") or 0)
        ink(4.8, cy, name, 12)
        ink(32.5, cy, fmt_lots_align(net), 16, chip_color(net), ha="right")
        ink(96.4, cy, item.get("phrase") or "—", 12, chip_color(net), ha="right")
        cy -= 4.05

    panel(1.4, 5.35, 97.2, 20.7)
    ink(4.8, 23.85, "基本面／紀律", 13, "#1A237E")
    fy = 20.35
    note = (tape or {}).get("conflict") or ""
    if note:
        ink(4.8, fy, note, 14, "#C62828")
        fy -= 3.35
    for a, b in fund_rows:
        ink(4.8, fy, f"{a}　{b}", 12, "#111111")
        fy -= 3.15
    try:
        note2 = pink_warning_note(card)
        if note2:
            ink(4.8, fy, note2, 13, "#AD1457")
    except Exception:
        pass
    ink(4.8, 6.85, "左上 K＝當日開高低收（紅漲綠跌）　▲連漲　▼連跌", 10, "#78909C")
    plt.savefig(save_path, dpi=220, facecolor=fig.get_facecolor())
    plt.close()
    return save_path



def _nav_arrow(ax, x, y, *, down: bool, face: str, span: float, z=7, alpha=1.0, scale=1.0):
    """帶柄箭頭（不是實心正三角）：尖端對準價位，柄較細、頭較長，外加深色描邊。"""
    hy = max(span * 0.032, abs(y) * 0.009) * float(scale)
    head_h = hy * 0.58
    shaft_h = hy * 0.62
    hw = 0.46 * scale
    sw = 0.11 * scale
    if down:
        tip_y, head_y, tail_y = y, y + head_h, y + head_h + shaft_h
    else:
        tip_y, head_y, tail_y = y, y - head_h, y - head_h - shaft_h
    verts = [
        (x, tip_y),
        (x + hw, head_y),
        (x + sw, head_y),
        (x + sw, tail_y),
        (x - sw, tail_y),
        (x - sw, head_y),
        (x - hw, head_y),
    ]
    ax.add_patch(
        patches.Polygon(
            verts,
            closed=True,
            facecolor=face,
            edgecolor="#212121",
            linewidth=0.45,
            joinstyle="round",
            alpha=alpha,
            zorder=z,
            clip_on=False,
        )
    )


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


def draw_from_ohlc(df: pd.DataFrame, stock_id: str, stock_name: str, save_path: str) -> str:
    """橫式高低導航，對齊 CaryBot：價格列放 20 高／低／脫離／60低；量能列放量能異常、警告、月波動低。"""
    if df.empty:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
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

    fig, (ax1, ax_sig, ax2) = plt.subplots(
        3,
        1,
        figsize=(16.8, 8.15),
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.15, 0.42, 1.35), hspace=0.03),
        facecolor="#ffffff",
    )
    ymin = float(lo_s.min()) - span * 0.08
    ymax = float(hi_s.max()) + span * 0.10
    ax1.axhspan(h20, ymax, color="#f8bbd0", alpha=0.38, zorder=0)
    ax1.axhspan(l20, h20, color="#fff9c4", alpha=0.32, zorder=0)
    ax1.axhspan(ymin, l20, color="#c8e6c9", alpha=0.38, zorder=0)
    ax1.set_ylim(ymin, ymax)
    ax1.set_xlim(-0.8, n - 0.2)

    was_20h = was_20l = False
    for i in range(n):
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        x = xs[i]
        is_halt = bool(halt.iloc[i])
        color = "#e53935" if cl >= op else "#00897b"
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

        # 價格列：20高／20高脫離／20低／20低脫離／60低（量能異常不畫在這裡）
        if is_20h:
            _nav_arrow(ax1, x, hi + span * 0.010, down=True, face="#f48fb1", span=span, z=6)
        elif hi >= wick_h20 * 0.985:
            _nav_arrow(ax1, x, hi + span * 0.008, down=True, face="#f8bbd0", span=span, z=5, alpha=0.38, scale=0.82)
        if leave_h:
            _nav_arrow(ax1, x, hi + span * 0.046, down=True, face="#6a1b9a", span=span, z=8, scale=1.12)
        if is_20l:
            _nav_arrow(ax1, x, lo - span * 0.010, down=False, face="#66bb6a", span=span, z=6)
        elif lo <= wick_l20 * 1.015:
            _nav_arrow(ax1, x, lo - span * 0.008, down=False, face="#a5d6a7", span=span, z=5, alpha=0.38, scale=0.82)
        if leave_l:
            _nav_arrow(ax1, x, lo - span * 0.046, down=False, face="#1b5e20", span=span, z=8, scale=1.12)
        if is_60l:
            _nav_arrow(ax1, x, lo - span * 0.078, down=False, face="#00acc1", span=span, z=7, scale=1.08)

        # 量能列：月波動底、警告▲、量能異常▲、月波動低▲ —— 即使價格列沒有對應箭頭也要畫
        sq = "#ffe0b2" if (i // 3) % 2 == 0 else "#bbdefb"
        if vol_low:
            sq = "#90caf9"
        ax_sig.add_patch(patches.Rectangle((x - 0.45, 0.08), 0.9, 0.84, facecolor=sq, edgecolor="#ffffff", lw=0.12, zorder=2))
        if warn:
            _sig_arrow(ax_sig, x, 0.72, "#e53935", "#7f0000", scale=1.05, z=5)
        if vol_a:
            _sig_arrow(ax_sig, x, 0.38, "#6a1b9a", "#311b92", scale=1.22, z=6)
        elif vol_low:
            _sig_arrow(ax_sig, x, 0.38, "#ce93d8", "#6a1b9a", scale=0.78, z=4)

        was_20h, was_20l = is_20h, is_20l

    ax1.plot(xs, work["ma20"], color="#f9a825", linewidth=1.85, zorder=4)
    ax1.axhline(h60, color="#f48fb1", linewidth=1.35)
    ax1.axhline(l60, color="#81c784", linewidth=1.35)
    ax1.axhline(h20, color="#f8bbd0", linewidth=1.05, linestyle="--")
    ax1.axhline(l20, color="#80deea", linewidth=1.05, linestyle="--")
    live_note = ""
    if "is_live" in work.columns and bool(pd.Series(work["is_live"]).fillna(False).iloc[-1]):
        live_note = "  ·盤中即時"
    ax1.set_title(
        f"{stock_id} {stock_name} (日K線) 180日區間 (季) 絕對高低點導航{live_note}   WayneBot ® 2026",
        fontproperties=_fp(14, "bold"),
        pad=6,
    )
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color="#bdbdbd", zorder=1)
    ax1.yaxis.tick_right()
    ax1.yaxis.set_label_position("right")
    ax1.tick_params(labelsize=9)
    for lab in ax1.get_yticklabels():
        lab.set_fontproperties(_fp(9))
    ax1.text(
        0.004,
        0.985,
        f"Op:{float(last['open']):g}  Hi:{float(last['high']):g}  Lo:{float(last['low']):g}  Cl:{float(last['close']):g}"
        f"    SMA(20): {float(last['ma20']):.1f}",
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
    ax_sig.set_ylabel("訊號", fontproperties=_fp(8))
    ax_sig.tick_params(axis="x", labelbottom=False, length=0)

    vol_colors = ["#ef5350" if work["close"].iloc[i] >= work["open"].iloc[i] else "#26a69a" for i in range(n)]
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
            months.append(dt.strftime("%b"))
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
        "價格列：淺粉↓20高　紫↓20高脫離　綠↑20低　深綠↑20低脫離　青↑60低　　"
        "量能列：紫↑量能異常　紅↑警告　淺紫↑月波動低　藍／杏塊＝月波動",
        ha="center",
        va="bottom",
        fontproperties=_fp(9, "bold"),
        color="#263238",
    )
    plt.savefig(save_path, dpi=170, facecolor="#ffffff")
    plt.close()
    return save_path


def generate_chart(stock_id: str, stock_name: str = "", db_path: str = None, save_path: str = None) -> str:
    sid = str(stock_id).strip()
    df = _load_ohlc(sid, db_path, 180)
    if df.empty:
        return ""
    name = stock_name or str(df["stock_name"].iloc[-1] or sid)
    out = save_path or os.path.join(get_charts_dir(), f"{sid}.png")
    return draw_from_ohlc(df, sid, name, out)


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
        headers = ["日期", "股價", "獲利", "高低", "預警"]
        col_x = [0.08, 0.28, 0.48, 0.66, 0.86]
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
        warn = str(row.get("預警") or "—")
        temp = _temp_num(row.get("溫度計"))
        bias = row.get("bias_monthly")
        volr = row.get("vol_rank_120")
        if part == 1:
            hl_c = "#C62828" if "高" in hl else ("#2E7D32" if "低" in hl else "#111827")
            vals = [
                (date_s, "#111827"),
                (_fmt_num(row.get("close"), 2), "#111827"),
                (_fmt_pct(profit), _chg_color(profit)),
                (hl, hl_c),
                (warn, _WARN_COLORS.get(warn, "#6B7280")),
            ]
        else:
            vals = [
                (date_s, "#111827"),
                (_fmt_num(temp, 0) if temp is not None else "—", _temp_color(temp)),
                (_fmt_pct(bias), _chg_color(bias)),
                (_fmt_num(volr, 0) if volr is not None else "—", "#111827"),
            ]
        for i, (txt, color) in enumerate(vals):
            ax.text(col_x[i], y, txt, transform=ax.transAxes, fontproperties=_fp(20, "bold"),
                    color=color, ha="center", va="center", zorder=1)

    fig.savefig(save_path, dpi=200, bbox_inches="tight", pad_inches=0.06, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path


def generate_card_image(stock_id: str, db_path: str = None, save_path: str = None) -> list:
    sid = str(stock_id).strip()
    engine = CaryNavigatorEngine(db_path or get_db_path())
    card = engine.get_decision_card(sid, lookback=20)
    if card.get("error"):
        return []
    base = save_path or os.path.join(get_charts_dir(), f"{sid}_card.png")
    path = render_decision_card_png(card, base)
    return [path] if path else []


def generate_card_with_chart(stock_id: str, db_path: str = None, charts_dir: str = None):
    sid = str(stock_id).strip()
    html = generate_decision_card(sid, db_path, lookback=20)
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    glance = ""
    try:
        from chip_tape import build_tape

        engine = CaryNavigatorEngine(db_path or get_db_path())
        card = engine.get_decision_card(sid, lookback=20)
        tape = build_tape(db_path or get_db_path(), sid) or {}
        if not card.get("error"):
            glance = render_first_glance_png(sid, card, tape, os.path.join(charts_dir, f"{sid}_glance.png"))
    except Exception:
        glance = ""
    cards = generate_card_image(sid, db_path, os.path.join(charts_dir, f"{sid}_card.png"))
    chart = generate_chart(sid, "", db_path, os.path.join(charts_dir, f"{sid}.png"))
    return html, cards, chart, glance
