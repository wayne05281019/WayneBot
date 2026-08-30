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

# 載入中文字型
FONT_PATH = os.path.join(BASE_DIR, "NotoSansTC-Regular.otf")
if not os.path.exists(FONT_PATH):
    try:
        FONT_URL = "https://github.com/google/fonts/raw/main/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf"
        urllib.request.urlretrieve(FONT_URL, FONT_PATH)
        fm.fontManager.addfont(FONT_PATH)
        plt.rcParams['font.sans-serif'] = ['Noto Sans TC', 'DejaVu Sans', 'Arial']
    except Exception:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
else:
    fm.fontManager.addfont(FONT_PATH)
    plt.rcParams['font.sans-serif'] = ['Noto Sans TC', 'DejaVu Sans', 'Arial']

plt.rcParams['axes.unicode_minus'] = False


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
            ORDER BY date DESC LIMIT 375;
        """, conn, params=(stock_id,))
        conn.close()

        if len(df) < 5:
            return {"error": f"標的 {stock_id} 歷史資料不足"}

        df = df.iloc[::-1].reset_index(drop=True)
        df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
        df["ma60"] = df["close"].rolling(60, min_periods=1).mean()
        # 決策卡格子：用收盤高低（與範本 8234 完全對得上）
        df["high_5"] = df["close"].rolling(5, min_periods=1).max()
        df["low_5"] = df["close"].rolling(5, min_periods=1).min()
        df["high_10"] = df["close"].rolling(10, min_periods=1).max()
        df["low_10"] = df["close"].rolling(10, min_periods=1).min()
        df["high_20"] = df["close"].rolling(20, min_periods=1).max()
        df["low_20"] = df["close"].rolling(20, min_periods=1).min()
        df["high_60"] = df["close"].rolling(60, min_periods=1).max()
        df["low_60"] = df["close"].rolling(60, min_periods=1).min()
        # 獲利＝相對 60 日收盤低；0%＝貼底（獲利零）
        df["profit_pct"] = ((df["close"] - df["low_60"]) / df["low_60"].replace(0, np.nan) * 100.0).round(1)
        df["bias_monthly"] = (((df["close"] - df["ma20"]) / df["ma20"]) * 100.0).round(1)
        df["vol_rank_120"] = self._calc_rolling_rank(df["volume"], window=120)

        hl_tags, alert_tags, temps = [], [], []
        for i in range(len(df)):
            c = float(df["close"].iloc[i])
            h20, l20 = float(df["high_20"].iloc[i]), float(df["low_20"].iloc[i])
            h10, l10 = float(df["high_10"].iloc[i]), float(df["low_10"].iloc[i])
            h5, l5 = float(df["high_5"].iloc[i]), float(df["low_5"].iloc[i])
            l60 = float(df["low_60"].iloc[i])
            bias = float(df["bias_monthly"].iloc[i])
            t = ((c - l20) / (h20 - l20 + 0.01) * 70.0 + (bias + 25.0) / 65.0 * 30.0)
            t = round(max(0.0, min(99.9, t)), 1)
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
            elif c >= h20 * 0.99 or bias >= 8.0:
                alert_tags.append("K20高")
            elif c <= l20 * 1.01 or bias < 0.0:
                alert_tags.append("K20低")
            else:
                alert_tags.append("No")

        df["獲利"] = [f"{p:.1f}%" if pd.notna(p) else "—" for p in df["profit_pct"]]
        df["高低"] = hl_tags
        df["預警"] = alert_tags
        df["溫度計"] = temps
        df["月乖離"] = [f"{b:+.1f}%" for b in df["bias_monthly"]]
        df["120日量"] = [f"第 {int(r)} 名" for r in df["vol_rank_120"]]

        latest = df.iloc[-1]
        dts = pd.to_datetime(df["date"].astype(str), errors="coerce")
        end_d = dts.iloc[-1]

        def _cal_close(days, how):
            start = end_d - pd.Timedelta(days=int(days) - 1)
            s = df.loc[dts >= start, "close"]
            if s.empty:
                s = df["close"].tail(max(3, int(days) // 2))
            return float(s.max() if how == "max" else s.min())

        def _cal_vol_mean(days):
            start = end_d - pd.Timedelta(days=int(days) - 1)
            s = df.loc[dts >= start, "volume"]
            return int(round(float(s.mean() or 0)))

        # 決策卡高／低：日曆 10／20／60 日收盤（對齊範本；20 日低是 36.30 不是 20 根K的 33.75）
        h10, h20, h60 = _cal_close(10, "max"), _cal_close(20, "max"), _cal_close(60, "max")
        l10, l20, l60 = _cal_close(10, "min"), _cal_close(20, "min"), _cal_close(60, "min")

        def _dist_h(h):
            c = float(latest["close"])
            return round((c - float(h)) / c * 100.0, 1) if c else 0.0

        def _dist_l(lo):
            lo = float(lo)
            return round((float(latest["close"]) - lo) / lo * 100.0, 1) if lo else 0.0

        space_20 = int(round((h20 - l20) / l20 * 100.0)) if l20 else 0
        space_60 = int(round((h60 - l60) / l60 * 100.0)) if l60 else 0
        ma60s = 0.0
        if len(df) >= 6:
            ma60s = round(float(latest["ma60"]) - float(df["ma60"].iloc[-6]), 2)
        qty60 = _cal_vol_mean(60)
        badges = []
        if float(latest["close"]) >= float(h20) * 0.998:
            badges.append("創20日新高")
        if qty60 < 800:
            badges.append("60日均量過小")
        badges.append("多頭格局" if float(latest["close"]) >= float(latest["ma20"]) else "整理格局")
        table = df.tail(lookback)[
            ["date", "close", "獲利", "高低", "預警", "溫度計", "月乖離", "120日量", "profit_pct", "bias_monthly", "vol_rank_120"]
        ].iloc[::-1]
        return {
            "stock_id": str(stock_id),
            "stock_name": str(latest.get("stock_name") or stock_id),
            "latest_date": latest["date"],
            "close": float(latest["close"]),
            "change_pct": float(latest["change_pct"] or 0),
            "h10": h10, "dist_h10": _dist_h(h10),
            "h20": h20, "dist_h20": _dist_h(h20),
            "h60": h60, "dist_h60": _dist_h(h60),
            "l10": l10, "dist_l10": _dist_l(l10),
            "l20": l20, "dist_l20": _dist_l(l20),
            "l60": l60, "dist_l60": _dist_l(l60),
            "space_20": space_20,
            "space_60": space_60,
            "temp_c": latest["溫度計"],
            "ma20": float(latest["ma20"]),
            "ma60s": ma60s,
            "qty60": qty60,
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
    ax.add_patch(patches.FancyBboxPatch((2.15, 93.55), 8.0, 5.7, boxstyle="round,pad=0.08,rounding_size=0.35",
                                        facecolor="#eceff1", edgecolor="none"))
    _draw_mini_candle(
        ax, 2.4, 93.7, 7.2, 5.4,
        card.get("open") or card.get("close") or 0,
        card.get("high") or card.get("close") or 0,
        card.get("low") or card.get("close") or 0,
        card.get("close") or 0,
    )
    ax.text(11.2, 97.4, f"{card['stock_id']}  {card.get('stock_name') or ''}", fontproperties=_fp(20, "bold"),
            color="#ffffff", va="center")
    ax.text(11.2, 94.8, "買低賣高決策卡　破解獲利密碼", fontproperties=_fp(12, "bold"), color="#ffecb3", va="center")
    ax.text(96.5, 96.2, "WayneBot", fontproperties=_fp(10, "bold"), color="#c5cae9", ha="right", va="center")

    chg = float(card.get("change_pct") or 0)
    chg_c = "#c62828" if chg > 0 else ("#00695c" if chg < 0 else "#212121")
    ax.text(3.2, 91.35, "股價", fontproperties=_fp(11), color="#607d8b", va="center")
    ax.text(10.8, 91.2, _fmt_price(card["close"]), fontproperties=_fp(30, "bold"), color="#000000", va="center")
    ax.text(42.0, 91.35, "漲跌幅", fontproperties=_fp(11), color="#607d8b", va="center")
    ax.text(52.0, 91.2, f"{chg:+.2f}%", fontproperties=_fp(18, "bold"), color=chg_c, va="center")
    badge = (card.get("badges") or ["整理格局"])[-1]
    _pill(ax, 86.5, 91.25, badge, "#e53935" if "多頭" in badge else "#546e7a", "#ffffff", w=18, h=3.0, fs=12)

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
    for _, r in table.iterrows():
        y1 = y - body_h
        profit = r.get("profit_pct")
        bias = float(r.get("bias_monthly") or 0)
        rank = int(r.get("vol_rank_120") or 99)
        temp_v = str(r["溫度計"]).replace(" °C", "").replace("°C", "")
        pbg, pfg = _heat_pair(profit, 0, 50)
        tbg, tfg = _heat_pair(temp_v, 0, 85)
        if rank <= 20:
            vbg, vfg = _heat_pair(21 - rank, 0, 20)
        else:
            vbg, vfg = "#ffffff", "#000000"
        hl = str(r["高低"])
        al = str(r["預警"])
        fills = ["#ffffff" if _ % 2 == 0 else "#fafafa" for _ in range(2)] + [pbg, "#ffffff", "#ffffff", tbg,
                                                                               "#ffcdd2" if bias > 0 else "#c8e6c9", vbg]
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
                color = pfg if i == 2 else (tfg if i == 5 else (vfg if i == 7 else ("#c62828" if i == 6 and bias > 0 else ("#00695c" if i == 6 else "#111111"))))
                ax.text(cx, cy, val, fontproperties=_fp(fs_body, "bold"),
                        ha="center", va="center", color="#000000" if i not in (2, 5, 6, 7) else color)
        y = y1

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
    return df.iloc[::-1].reset_index(drop=True)


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
    pink_note = ""
    alerts = list(card["table"]["預警"].head(3))
    if alerts.count("K20高") >= 2 or list(alerts[:2]) == ["K20高", "K20高"]:
        pink_note = "🚨 粉紅預警已滿 2 日 → 紀律考慮賣出"
    chg = float(card.get("change_pct") or 0)
    from tg_layout import title_line, kv, section, join_sections
    from chip_tape import build_tape, fmt_lots

    tape = build_tape(db_path or get_db_path(), sid) or {}
    move = (tape.get("move") or {}).get("text") or f"{chg:+.2f}%"
    shape = tape.get("shape") or ""
    last = tape.get("last") or {}
    ohlc = ""
    if last:
        ohlc = f"{_fmt_price(last.get('open'))} / {_fmt_price(last.get('high'))} / {_fmt_price(last.get('low'))}"
    badge = "　".join(str(x) for x in (card.get("badges") or []) if x)
    if shape:
        badge = f"{badge}　{shape}".strip()
    links = ""
    if web:
        links = f'<a href="{web}">網頁走勢</a>　　<a href="{mobile}">技術線</a>'
    chip_block = ""
    if tape:
        chip_block = section(
            kv("外資", f"{fmt_lots(tape.get('foreign', {}).get('net', 0))}　{tape.get('foreign', {}).get('phrase', '')}"),
            kv("投信", f"{fmt_lots(tape.get('trust', {}).get('net', 0))}　{tape.get('trust', {}).get('phrase', '')}"),
            kv("自營", f"{fmt_lots(tape.get('dealer', {}).get('net', 0))}　{tape.get('dealer', {}).get('phrase', '')}"),
            kv("法人", f"{fmt_lots(tape.get('three', {}).get('net', 0))}　{tape.get('three', {}).get('phrase', '')}"),
            kv("佔成交", f"{tape.get('inst_pct', 0):+.1f}%"),
        )
    vol_line = (tape.get("volume") or {}).get("line") or "—"
    extra_flags = tape.get("conflict") or ""
    bias = card.get("bias_monthly")
    bias_s = f"{float(bias):+.1f}%" if bias is not None else "—"
    return join_sections(
        title_line("第一眼", sid, name, badge),
        section(
            kv("日期", _fmt_md(card["latest_date"])),
            kv("開高低", ohlc or "—"),
            kv("收盤", f"{_fmt_price(card['close'])}　{move}"),
            kv("當日", f"{chg:+.2f}%"),
        ),
        section(
            kv("距20日高", f"{card['dist_h20']:+.1f}%"),
            kv("距60日低", f"{card.get('dist_l60'):+.1f}%（獲利）"),
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
        extra_flags,
        pink_note,
        links,
        "下圖：當日K＋籌碼條 → 決策卡 → 高低導航。完整法人格請按籌碼。",
    )


def render_first_glance_png(stock_id: str, card: dict, tape: dict, save_path: str) -> str:
    """窄圖：股號旁當日 K、收盤連漲跌三角形、籌碼連買連賣。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    from chip_tape import fmt_lots

    last = (tape or {}).get("last") or {}
    move = (tape or {}).get("move") or {}
    fig, ax = plt.subplots(figsize=(5.15, 8.35), dpi=175, facecolor="#eef1f6")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.subplots_adjust(left=0.03, right=0.97, top=0.98, bottom=0.02)
    ax.add_patch(patches.FancyBboxPatch((1.6, 90.4), 96.8, 8.4, boxstyle="round,pad=0.12,rounding_size=0.5",
                                        facecolor="#1a237e", edgecolor="none"))
    ax.add_patch(patches.FancyBboxPatch((2.4, 90.7), 12.6, 7.8, boxstyle="round,pad=0.08,rounding_size=0.35",
                                        facecolor="#eceff1", edgecolor="none"))
    _draw_mini_candle(
        ax, 3.0, 91.0, 11.5, 7.2,
        last.get("open") or card.get("open") or card.get("close") or 0,
        last.get("high") or card.get("high") or card.get("close") or 0,
        last.get("low") or card.get("low") or card.get("close") or 0,
        last.get("close") or card.get("close") or 0,
    )
    ax.text(16.5, 96.6, f"{card.get('stock_id') or stock_id}  {card.get('stock_name') or ''}",
            fontproperties=_fp(18, "bold"), color="#ffffff", va="center")
    badge = "　".join(str(x) for x in (card.get("badges") or []) if x)
    shape = (tape or {}).get("shape") or ""
    ax.text(16.5, 93.4, f"{badge}　{shape}".strip(), fontproperties=_fp(11, "bold"), color="#ffe082", va="center")
    ax.text(97.6, 96.6, "第一眼", fontproperties=_fp(10, "bold"), color="#c5cae9", ha="right", va="center")

    chg = float(card.get("change_pct") or 0)
    tri_c = "#c62828" if int(move.get("sign") or 0) > 0 else ("#00695c" if int(move.get("sign") or 0) < 0 else "#37474f")
    ax.text(4.0, 86.8, _fmt_price(card.get("close")), fontproperties=_fp(28, "bold"), color="#000000", va="center")
    ax.text(48.0, 87.6, move.get("text") or f"{chg:+.2f}%", fontproperties=_fp(13, "bold"), color=tri_c, va="center")
    ax.text(48.0, 84.7, f"當日 {chg:+.2f}%　{_fmt_md(card.get('latest_date'))}",
            fontproperties=_fp(11, "bold"), color="#455a64", va="center")
    if last:
        ax.text(4.0, 82.4, f"開 {_fmt_price(last.get('open'))}　高 {_fmt_price(last.get('high'))}　低 {_fmt_price(last.get('low'))}",
                fontproperties=_fp(11, "bold"), color="#37474f", va="center")

    rows = [
        ("距20日高", f"{card['dist_h20']:+.1f}%"),
        ("距60日低", f"{card.get('dist_l60'):+.1f}% 獲利"),
        ("月／季空間", f"{card['space_20']}%　／　{card['space_60']}%"),
        ("月乖離", f"{float(card.get('bias_monthly') or 0):+.1f}%"),
        ("溫度", str(card.get("temp_c") or "—")),
        ("120日量", f"第 {card.get('vol_rank')} 名"),
        ("量比", (tape or {}).get("volume", {}).get("line") or "—"),
    ]
    y = 79.2
    for lab, val in rows:
        ax.text(4.2, y, lab, fontproperties=_fp(11, "bold"), color="#607d8b", va="center")
        ax.text(96.0, y, val, fontproperties=_fp(13, "bold"), color="#111111", ha="right", va="center")
        y -= 3.35

    ax.add_patch(patches.FancyBboxPatch((2.0, 11.6), 96.0, 43.4, boxstyle="round,pad=0.1,rounding_size=0.4",
                                        facecolor="#ffffff", edgecolor="#cfd8dc", linewidth=0.9))
    ax.text(4.6, 52.6, "籌碼（張）", fontproperties=_fp(13, "bold"), color="#1a237e", va="center")
    ax.text(96.0, 52.6, f"佔成交 {(tape or {}).get('inst_pct', 0):+.1f}%",
            fontproperties=_fp(11, "bold"), color="#455a64", ha="right", va="center")

    def chip_color(n):
        if n > 0:
            return "#b71c1c"
        if n < 0:
            return "#1b5e20"
        return "#455a64"

    chips = [
        ("外資", (tape or {}).get("foreign") or {}),
        ("投信", (tape or {}).get("trust") or {}),
        ("自營", (tape or {}).get("dealer") or {}),
        ("法人", (tape or {}).get("three") or {}),
    ]
    cy = 47.8
    for lab, item in chips:
        net = int(item.get("net") or 0)
        ax.text(5.2, cy + 1.35, lab, fontproperties=_fp(11, "bold"), color="#546e7a", va="center")
        ax.text(5.2, cy - 1.15, fmt_lots(net), fontproperties=_fp(16, "bold"), color=chip_color(net), va="center")
        ax.text(96.2, cy, item.get("phrase") or "—", fontproperties=_fp(11, "bold"),
                color=chip_color(net), ha="right", va="center")
        cy -= 8.6

    note = (tape or {}).get("conflict") or ""
    ax.text(4.0, 8.8, note or "價量與籌碼同向較穩；背離先當警示不是立即反手。",
            fontproperties=_fp(10, "bold"), color="#c62828" if note else "#546e7a", va="center")
    ax.text(4.0, 5.6, "▲紅＝連漲　▼綠＝連跌　K 縮圖＝當日開高低收",
            fontproperties=_fp(10), color="#78909c", va="center")
    plt.savefig(save_path, dpi=175, facecolor=fig.get_facecolor())
    plt.close()
    return save_path


def draw_from_ohlc(df: pd.DataFrame, stock_id: str, stock_name: str, save_path: str) -> str:
    if df.empty:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    work = df.copy()
    work["dt"] = pd.to_datetime(work["date"].astype(str), errors="coerce")
    work = work.dropna(subset=["dt"]).reset_index(drop=True)
    if work.empty:
        return ""
    h20, l20 = float(work["high"].tail(20).max()), float(work["low"].tail(20).min())
    h60, l60 = float(work["high"].tail(60).max()), float(work["low"].tail(60).min())
    work["ma20"] = work["close"].rolling(20, min_periods=1).mean()
    work["vol_ma"] = work["volume"].rolling(20, min_periods=1).mean()
    last = work.iloc[-1]
    fig, (ax1, ax_sig, ax2) = plt.subplots(
        3,
        1,
        figsize=(9.2, 12.4),
        sharex=True,
        gridspec_kw=dict(height_ratios=(3.4, 0.42, 1.05), hspace=0.06),
        facecolor="#ffffff",
    )
    ymin, ymax = float(work["low"].min()) * 0.96, float(work["high"].max()) * 1.04
    ax1.axhspan(h20, ymax, color="#fce4ec", alpha=0.55, zorder=0)
    ax1.axhspan(l20, h20, color="#fffde7", alpha=0.45, zorder=0)
    ax1.axhspan(ymin, l20, color="#e8f5e9", alpha=0.55, zorder=0)
    ax1.set_ylim(ymin, ymax)
    for i in range(len(work)):
        dt = work["dt"].iloc[i]
        op, cl = float(work["open"].iloc[i]), float(work["close"].iloc[i])
        hi, lo = float(work["high"].iloc[i]), float(work["low"].iloc[i])
        color = "#e53935" if cl >= op else "#00897b"
        x = mdates.date2num(dt)
        ax1.plot([dt, dt], [lo, hi], color=color, linewidth=1.05, zorder=3)
        height = max(abs(cl - op), float(cl) * 0.002)
        ax1.add_patch(patches.Rectangle((x - 0.32, min(op, cl)), 0.64, height, color=color, zorder=3))
        c20h = work["high"].iloc[max(0, i - 19) : i + 1].max()
        c20l = work["low"].iloc[max(0, i - 19) : i + 1].min()
        c60l = work["low"].iloc[max(0, i - 59) : i + 1].min()
        if hi >= c20h * 0.999:
            ax1.scatter([dt], [hi * 1.012], marker="v", color="#ec407a", s=48, zorder=4)
        if lo <= c20l * 1.001:
            ax1.scatter([dt], [lo * 0.988], marker="^", color="#43a047", s=48, zorder=4)
        if lo <= c60l * 1.001:
            ax1.scatter([dt], [lo * 0.972], marker="^", color="#00acc1", s=64, zorder=4)
        vol_a = float(work["volume"].iloc[i]) >= float(work["vol_ma"].iloc[i] or 1) * 2.2
        if vol_a:
            ax1.scatter([dt], [hi * 1.028], marker="v", color="#7b1fa2", s=52, zorder=5)
            ax_sig.scatter([dt], [2], marker="v", color="#7b1fa2", s=28)
        if cl >= c20h * 0.99:
            ax_sig.scatter([dt], [1], marker="s", color="#e53935", s=18)
        ax_sig.scatter([dt], [0], marker="s", color="#90caf9", s=12)
    ax1.plot(work["dt"], work["ma20"], color="#fbc02d", linewidth=1.7, label=f"SMA(20): {float(last['ma20']):.2f}", zorder=4)
    ax1.axhline(h60, color="#f48fb1", linewidth=1.4, label=f"季高點線 ({h60:.2f})")
    ax1.axhline(l60, color="#66bb6a", linewidth=1.4, label=f"季低點線 ({l60:.2f})")
    ax1.axhline(h20, color="#ce93d8", linewidth=1.05, linestyle="--", label=f"月高點線 ({h20:.2f})")
    ax1.axhline(l20, color="#80deea", linewidth=1.05, linestyle="--", label=f"月低點線 ({l20:.2f})")
    ax1.set_title(
        f"{stock_id} {stock_name} (日K線) 180日區間 (季) 絕對高低點導航   WayneBot ® 2026",
        fontproperties=_fp(14, "bold"),
        pad=10,
    )
    ax1.legend(loc="upper left", ncol=2, frameon=True, facecolor="#fafafa", edgecolor="none", prop=_fp(10))
    ax1.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.6, color="#bdbdbd")
    ax1.tick_params(labelsize=11)
    ax1.set_ylabel("價格", fontsize=12)
    ax1.text(
        0.99,
        0.02,
        f"Op:{last['open']:g}  Hi:{last['high']:g}  Lo:{last['low']:g}  Cl:{last['close']:g}",
        transform=ax1.transAxes,
        ha="right",
        va="bottom",
        fontsize=12,
        color="#212121",
        fontweight="bold",
    )
    ax_sig.set_yticks([0, 1, 2])
    ax_sig.set_yticklabels(["月波動", "警告", "量能"], fontproperties=_fp(10))
    ax_sig.set_ylim(-0.6, 2.6)
    ax_sig.grid(True, axis="x", linestyle=(0, (1.2, 1.6)), linewidth=0.4)
    vol_colors = ["#ef5350" if work["close"].iloc[i] >= work["open"].iloc[i] else "#26a69a" for i in range(len(work))]
    ax2.bar(work["dt"], work["volume"] / 1000.0, color=vol_colors, width=0.7)
    ax2.set_ylabel("Vol (千張)", fontproperties=_fp(11))
    ax2.tick_params(labelsize=11)
    ax2.text(0.01, 0.92, f"Vol: {float(last['volume'])/1000:.2f}K", transform=ax2.transAxes, fontsize=12, va="top", fontweight="bold")
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.6, color="#bdbdbd")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    fig.align_ylabels()
    fig.subplots_adjust(bottom=0.10)
    fig.text(
        0.5,
        0.012,
        "怎麼看：粉紅帶＝壓力（月/季高附近）　綠帶＝支撐（月/季低附近）　黃線＝20日均線\n"
        "▼粉紅＝碰到20日高（賣壓）　▲綠＝碰到20日低（支撐）　量能列＝爆量　警告列＝靠近20日高",
        ha="center",
        va="bottom",
        fontproperties=_fp(11, "bold"),
        color="#37474f",
    )
    plt.savefig(save_path, dpi=160, bbox_inches="tight", facecolor="#ffffff", pad_inches=0.22)
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
