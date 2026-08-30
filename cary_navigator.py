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
        def _dist_h(h):
            c = float(latest["close"])
            return round((c - float(h)) / c * 100.0, 1) if c else 0.0
        def _dist_l(lo):
            lo = float(lo)
            return round((float(latest["close"]) - lo) / lo * 100.0, 1) if lo else 0.0
        space_20 = int(round((latest["high_20"] - latest["low_20"]) / latest["low_20"] * 100.0))
        space_60 = int(round((latest["high_60"] - latest["low_60"]) / latest["low_60"] * 100.0))
        ma60s = 0.0
        if len(df) >= 6 and float(df["ma60"].iloc[-6] or 0) != 0:
            ma60s = round((float(latest["ma60"]) - float(df["ma60"].iloc[-6])) / float(df["ma60"].iloc[-6]) * 100.0, 2)
        qty60 = int(round(float(df["volume"].tail(60).mean() or 0)))
        badges = []
        if float(latest["close"]) >= float(latest["high_20"]) * 0.998:
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
            "h10": float(latest["high_10"]), "dist_h10": _dist_h(latest["high_10"]),
            "h20": float(latest["high_20"]), "dist_h20": _dist_h(latest["high_20"]),
            "h60": float(latest["high_60"]), "dist_h60": _dist_h(latest["high_60"]),
            "l10": float(latest["low_10"]), "dist_l10": _dist_l(latest["low_10"]),
            "l20": float(latest["low_20"]), "dist_l20": _dist_l(latest["low_20"]),
            "l60": float(latest["low_60"]), "dist_l60": _dist_l(latest["low_60"]),
            "space_20": space_20,
            "space_60": space_60,
            "temp_c": latest["溫度計"],
            "ma20": float(latest["ma20"]),
            "ma60s": ma60s,
            "qty60": qty60,
            "vol_rank": int(latest["vol_rank_120"]),
            "badges": badges,
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
    # 可變字型若寫 normal/bold，matplotlib 常落到 100 細體；改用數值軸。
    if isinstance(weight, str):
        weight = {"light": 400, "normal": 500, "medium": 600, "bold": 700, "heavy": 800}.get(
            weight.lower(), 500
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
    # 淺粉→深桃紅，字一律深色或白，保證對比
    r = 255
    g = int(236 - 140 * t)
    b = int(240 - 90 * t)
    bg = f"#{r:02x}{g:02x}{b:02x}"
    fg = "#111111"
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


def render_decision_card_png(card: dict, save_path: str) -> str:
    """高對比、大字、置中的決策卡（Telegram 手機也能看清）。"""
    if not card or card.get("error"):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    table = card["table"]
    n = max(len(table), 1)
    fig_w, fig_h = 13.4, 8.2 + n * 0.52
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=210, facecolor="#eef0f3")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.subplots_adjust(left=0.025, right=0.975, top=0.985, bottom=0.015)

    # 深藍表頭
    ax.add_patch(patches.Rectangle((0, 92.6), 100, 7.4, facecolor="#1a237e", edgecolor="none"))
    ax.text(2.2, 96.6, f"{card['stock_id']}  {card.get('stock_name') or ''}", fontproperties=_fp(22, "bold"), color="#ffffff", va="center")
    ax.text(2.2, 94.0, "買低賣高決策卡　破解獲利密碼", fontproperties=_fp(12), color="#ffd54f", va="center")

    chg = float(card.get("change_pct") or 0)
    chg_c = "#c62828" if chg > 0 else ("#00695c" if chg < 0 else "#212121")
    ax.text(2.2, 90.4, f"股價  {_fmt_price(card['close'])}", fontproperties=_fp(26, "bold"), color="#111111", va="center")
    ax.text(42, 90.4, f"漲跌幅  {chg:+.2f}%", fontproperties=_fp(16, "bold"), color=chg_c, va="center")
    ax.text(2.2, 87.2, f"120日量 第 {card.get('vol_rank')} 名　溫度計 {card.get('temp_c')}　日期 {_fmt_md(card.get('latest_date'))}", fontproperties=_fp(12), color="#37474f", va="center")
    bx = 68
    for b in (card.get("badges") or [])[:2]:
        bg = "#c62828" if "多頭" in b or "新高" in b else ("#2e7d32" if "過小" in b else "#6a1b9a")
        ax.add_patch(patches.FancyBboxPatch((bx, 88.8), 15, 3.2, boxstyle="round,pad=0.15", facecolor=bg, edgecolor=bg, linewidth=0))
        ax.text(bx + 7.5, 90.4, b, fontproperties=_fp(11, "bold"), color="#ffffff", ha="center", va="center")
        bx += 16

    ax.text(2.2, 84.6, f"高點資訊（收盤）　10／20／60日　MA60S {card.get('ma60s')}　QTY60 {card.get('qty60'):,}", fontproperties=_fp(12, "bold"), color="#880e4f", va="center")
    highs = [("10日高", card["h10"], card["dist_h10"]), ("20日高", card["h20"], card["dist_h20"]), ("60日高", card["h60"], card["dist_h60"])]
    for i, (lab, px, dist) in enumerate(highs):
        x = 2.2 + i * 32.2
        _cell(ax, x, 77.6, 30.6, 6.0, "#fff7f9", "#c2185b", 1.1)
        ax.text(x + 15.3, 82.2, lab, fontproperties=_fp(11), color="#ad1457", ha="center", va="center")
        ax.text(x + 15.3, 79.6, f"{_fmt_price(px)}", fontproperties=_fp(16, "bold"), color="#111", ha="center", va="center")
        ax.text(x + 15.3, 78.2, f"({dist:+.1f}%)", fontproperties=_fp(12, "bold"), color="#c62828" if dist < 0 else "#2e7d32", ha="center", va="center")

    ax.text(2.2, 76.2, f"低點資訊（收盤）　20日空間 {card['space_20']}%　60日空間 {card['space_60']}%　獲利 0%＝貼 60 日收盤低", fontproperties=_fp(12, "bold"), color="#1b5e20", va="center")
    lows = [("10日低", card["l10"], card["dist_l10"]), ("20日低", card["l20"], card["dist_l20"]), ("60日低", card["l60"], card["dist_l60"])]
    for i, (lab, px, dist) in enumerate(lows):
        x = 2.2 + i * 32.2
        near = abs(dist) <= 3
        _cell(ax, x, 69.2, 30.6, 6.0, "#e8f5e9" if near else "#f7fff8", "#2e7d32", 1.1)
        ax.text(x + 15.3, 73.8, lab, fontproperties=_fp(11), color="#1b5e20", ha="center", va="center")
        ax.text(x + 15.3, 71.2, f"{_fmt_price(px)}", fontproperties=_fp(16, "bold"), color="#111", ha="center", va="center")
        ax.text(x + 15.3, 69.8, f"({dist:+.1f}%)", fontproperties=_fp(12, "bold"), color="#c62828", ha="center", va="center")

    ax.text(2.2, 67.6, "過去 20 天紀錄（表頭與數字同一欄置中；底色深淺＝強度）", fontproperties=_fp(12, "bold"), color="#263238", va="center")
    headers = ["日期", "股價", "獲利", "高低", "預警", "溫度計", "月乖離", "120日量"]
    xs = [1.8, 16.2, 28.6, 40.2, 51.6, 63.4, 75.4, 86.8, 98.2]
    top = 66.4
    hdr_h = 3.15
    for i, h in enumerate(headers):
        _cell(ax, xs[i], top - hdr_h, xs[i + 1] - xs[i], hdr_h, "#e3f2fd", "#1565c0", 1.0)
        ax.text((xs[i] + xs[i + 1]) / 2, top - hdr_h / 2, h, fontproperties=_fp(12, "bold"), ha="center", va="center", color="#0d47a1")
    y = top - hdr_h
    body_h = (y - 1.4) / n
    fs_body = 14 if n <= 20 else 13
    for _, r in table.iterrows():
        y1 = y - body_h
        profit = r.get("profit_pct")
        bias = float(r.get("bias_monthly") or 0)
        rank = int(r.get("vol_rank_120") or 99)
        temp_v = str(r["溫度計"]).replace(" °C", "").replace("°C", "")
        pbg, pfg = _heat_pair(profit, 0, 50)
        tbg, tfg = _heat_pair(temp_v, 0, 85)
        vbg, vfg = _heat_pair(max(0, 120 - rank), 0, 80)
        hl = str(r["高低"])
        al = str(r["預警"])
        fills = ["#ffffff", "#ffffff", pbg]
        fills.append("#f48fb1" if "高" in hl else ("#81c784" if "低" in hl else "#ffffff"))
        fills.append("#f48fb1" if "高" in al else ("#81c784" if "低" in al else "#ffffff"))
        fills.extend([tbg, "#ffcdd2" if bias > 0 else "#c8e6c9", vbg])
        fgs = ["#111111", "#111111", pfg]
        fgs.append("#4a0033" if "高" in hl else ("#1b5e20" if "低" in hl else "#111111"))
        fgs.append("#4a0033" if "高" in al else ("#1b5e20" if "低" in al else "#111111"))
        fgs.extend([tfg, "#b71c1c" if bias > 0 else "#1b5e20", vfg])
        vals = [
            _fmt_md(r["date"]),
            _fmt_price(r["close"]),
            str(r["獲利"]),
            hl,
            al,
            str(r["溫度計"]),
            str(r["月乖離"]),
            str(r["120日量"]),
        ]
        for i, val in enumerate(vals):
            _cell(ax, xs[i], y1, xs[i + 1] - xs[i], body_h, fills[i], "#90a4ae", 0.7)
            ax.text((xs[i] + xs[i + 1]) / 2, (y + y1) / 2, val, fontproperties=_fp(fs_body, "bold" if i in (2, 3, 4) else "normal"), ha="center", va="center", color=fgs[i])
        y = y1

    plt.savefig(save_path, dpi=210, facecolor=fig.get_facecolor())
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
        from stock_links import html_stock_anchor, yahoo_urls

        title = html_stock_anchor(sid, name, db_path or get_db_path())
        web, mobile = yahoo_urls(sid, db_path or get_db_path())
    except Exception:
        title = f"<b>{html_escape(sid)} {html_escape(name)}</b>"
        web = mobile = ""
    pink_note = ""
    alerts = list(card["table"]["預警"].head(3))
    if alerts.count("K20高") >= 2 or list(alerts[:2]) == ["K20高", "K20高"]:
        pink_note = "🚨 <b>粉紅預警已滿 2 日 → 紀律考慮賣出</b>"
    chg = float(card.get("change_pct") or 0)
    links = ""
    if web:
        links = f'<a href="{web}">奇摩網頁走勢</a>　<a href="{mobile}">手機技術線</a>'
    lines = [
        f"📌 {title}",
        "完整欄位與虛線格子在下一則圖片（網頁／手機同一張，表頭對齊資料）。",
        f"日期 {html_escape(_fmt_md(card['latest_date']))}　收 {_fmt_price(card['close'])}　{chg:+.2f}%",
        f"格局 {' / '.join(html_escape(x) for x in (card.get('badges') or []))}",
        f"120日量第 {card.get('vol_rank')} 名　溫度計 {html_escape(card['temp_c'])}",
        f"高點(收) 10 {_fmt_price(card['h10'])}({card['dist_h10']:+.1f}%)　20 {_fmt_price(card['h20'])}({card['dist_h20']:+.1f}%)　60 {_fmt_price(card['h60'])}({card['dist_h60']:+.1f}%)",
        f"低點(收) 10 {_fmt_price(card['l10'])}({card['dist_l10']:+.1f}%)　20 {_fmt_price(card['l20'])}({card['dist_l20']:+.1f}%)　60 {_fmt_price(card['l60'])}({card['dist_l60']:+.1f}%)",
        f"操作空間 月 {card['space_20']}%　季 {card['space_60']}%　獲利0%＝尚未脫離60日收盤低",
        pink_note,
        links,
    ]
    try:
        from fundamentals import format_fundamentals_html

        fund = format_fundamentals_html(sid, db_path or get_db_path())
        if fund and "尚無" not in fund:
            lines.append(fund)
    except Exception:
        pass
    return "\n".join(x for x in lines if x)


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
        figsize=(16.2, 10.4),
        sharex=True,
        gridspec_kw=dict(height_ratios=(3.4, 0.34, 1.05), hspace=0.05),
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
        fontsize=16,
        fontweight="bold",
        pad=10,
    )
    ax1.legend(loc="upper left", ncol=3, frameon=True, facecolor="#fafafa", edgecolor="none", fontsize=10)
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
    ax_sig.set_yticklabels(["月波動", "警告", "量能"], fontsize=10)
    ax_sig.set_ylim(-0.6, 2.6)
    ax_sig.grid(True, axis="x", linestyle=(0, (1.2, 1.6)), linewidth=0.4)
    vol_colors = ["#ef5350" if work["close"].iloc[i] >= work["open"].iloc[i] else "#26a69a" for i in range(len(work))]
    ax2.bar(work["dt"], work["volume"] / 1000.0, color=vol_colors, width=0.7)
    ax2.set_ylabel("Vol (千張)", fontsize=12)
    ax2.tick_params(labelsize=11)
    ax2.text(0.01, 0.92, f"Vol: {float(last['volume'])/1000:.3f}K", transform=ax2.transAxes, fontsize=12, va="top", fontweight="bold")
    ax2.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.6, color="#bdbdbd")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    fig.align_ylabels()
    plt.savefig(save_path, dpi=220, bbox_inches="tight", facecolor="#ffffff")
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
    root, ext = os.path.splitext(base)
    summary = render_decision_summary_png(card, f"{root}{ext}")
    table1 = render_decision_table_png(card, f"{root}_t1{ext}", part=1)
    table2 = render_decision_table_png(card, f"{root}_t2{ext}", part=2)
    return [p for p in (summary, table1, table2) if p]


def generate_card_with_chart(stock_id: str, db_path: str = None, charts_dir: str = None):
    sid = str(stock_id).strip()
    html = generate_decision_card(sid, db_path, lookback=20)
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    cards = generate_card_image(sid, db_path, os.path.join(charts_dir, f"{sid}_card.png"))
    chart = generate_chart(sid, "", db_path, os.path.join(charts_dir, f"{sid}.png"))
    return html, cards, chart
