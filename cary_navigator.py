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
        """產出單一標的的買低賣高決策卡"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("""
            SELECT date, open, high, low, close, volume, pct_change as change_pct
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

        df["high_10"] = df["high"].rolling(10, min_periods=1).max()
        df["low_10"] = df["low"].rolling(10, min_periods=1).min()
        df["high_20"] = df["high"].rolling(20, min_periods=1).max()
        df["low_20"] = df["low"].rolling(20, min_periods=1).min()
        df["high_60"] = df["high"].rolling(60, min_periods=1).max()
        df["low_60"] = df["low"].rolling(60, min_periods=1).min()

        df["profit_pct"] = ((df["close"] - df["low_20"]) / df["low_20"] * 100.0).round(1)
        df["bias_monthly"] = (((df["close"] - df["ma20"]) / df["ma20"]) * 100.0).round(1)
        df["vol_rank_120"] = self._calc_rolling_rank(df["volume"], window=120)

        hl_tags, alert_tags, temps = [], [], []
        for i in range(len(df)):
            c = df["close"].iloc[i]
            h20, l20 = df["high_20"].iloc[i], df["low_20"].iloc[i]
            l60 = df["low_60"].iloc[i]
            bias = df["bias_monthly"].iloc[i]

            # 溫度計演算法
            t = ((c - l20) / (h20 - l20 + 0.01) * 70.0 + (bias + 25.0) / 65.0 * 30.0)
            t = round(max(0.0, min(99.9, t)), 1)
            temps.append(f"{t:.1f} °C")

            # 高低標籤
            if c >= h20 * 0.995: hl_tags.append("20高")
            elif c <= l20 * 1.005: hl_tags.append("20低")
            elif c >= df["high_10"].iloc[i] * 0.995: hl_tags.append("10高")
            elif c <= df["low_10"].iloc[i] * 1.005: hl_tags.append("5低")
            else: hl_tags.append("No")

            # 預警標籤
            if c <= l60 * 1.005: alert_tags.append("60低")
            elif bias >= 10.0: alert_tags.append("K20高")
            elif bias < 0.0: alert_tags.append("K20低")
            else: alert_tags.append("No")

        df["獲利"] = [f"{p:.1f}%" for p in df["profit_pct"]]
        df["高低"] = hl_tags
        df["預警"] = alert_tags
        df["溫度計"] = temps
        df["月乖離"] = [f"{b:+.1f}%" for b in df["bias_monthly"]]
        df["120日量"] = [f"第 {r} 名" for r in df["vol_rank_120"]]

        latest = df.iloc[-1]
        space_20 = int(round((latest["high_20"] - latest["low_20"]) / latest["low_20"] * 100.0))
        space_60 = int(round((latest["high_60"] - latest["low_60"]) / latest["low_60"] * 100.0))

        table = df.tail(lookback)[["date", "close", "獲利", "高低", "預警", "溫度計", "月乖離", "120日量"]].iloc[::-1]

        return {
            "stock_id": stock_id,
            "latest_date": latest["date"],
            "close": latest["close"],
            "h10": latest["high_10"], "dist_h10": round((latest["close"] - latest["high_10"]) / latest["close"] * 100.0, 1),
            "h20": latest["high_20"], "dist_h20": round((latest["close"] - latest["high_20"]) / latest["close"] * 100.0, 1),
            "h60": latest["high_60"], "dist_h60": round((latest["close"] - latest["high_60"]) / latest["close"] * 100.0, 1),
            "l10": latest["low_10"], "dist_l10": round((latest["close"] - latest["low_10"]) / latest["low_10"] * 100.0, 1),
            "l20": latest["low_20"], "dist_l20": round((latest["close"] - latest["low_20"]) / latest["low_20"] * 100.0, 1),
            "l60": latest["low_60"], "dist_l60": round((latest["close"] - latest["low_60"]) / latest["low_60"] * 100.0, 1),
            "space_20": space_20,
            "space_60": space_60,
            "temp_c": latest["溫度計"],
            "table": table
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


def generate_decision_card(stock_id: str, db_path: str = None, lookback: int = 12) -> str:
    sid = str(stock_id).strip()
    df = _load_ohlc(sid, db_path, 375)
    if df.empty or len(df) < 5:
        return f"⚠️ 找不到 <code>{html_escape(sid)}</code> 的日 K（請先完成歷史庫／盤後增量）。"
    engine = CaryNavigatorEngine(db_path or get_db_path())
    card = engine.get_decision_card(sid, lookback=lookback)
    if "error" in card:
        return f"⚠️ {html_escape(card['error'])}"
    name = str(df["stock_name"].iloc[-1] or sid)
    pink_note = ""
    alerts = list(card["table"]["預警"].head(3))
    if alerts.count("K20高") >= 2 or alerts[:2] == ["K20高", "K20高"]:
        pink_note = "\n🚨 <b>粉紅預警已滿 2 日 → 紀律考慮賣出</b>"
    lines = [
        f"📌 <b>決策卡 {html_escape(sid)} {html_escape(name)}</b>",
        f"日期 {html_escape(card['latest_date'])}  收 {card['close']}",
        f"溫度計 {html_escape(card['temp_c'])}  月空間 {card['space_20']}%  季空間 {card['space_60']}%",
        f"距20高 {card['dist_h20']}%  距20低 {card['dist_l20']}%  距60高 {card['dist_h60']}%  距60低 {card['dist_l60']}%",
        pink_note,
        "<code>日期       收盤   獲利   高低  預警  溫度</code>",
    ]
    for _, r in card["table"].head(lookback).iterrows():
        d = str(r["date"])
        if len(d) == 8:
            d = f"{d[4:6]}/{d[6:]}"
        lines.append(
            f"<code>{d}</code> {r['close']:.1f} {html_escape(r['獲利'])} "
            f"{html_escape(r['高低'])} {html_escape(r['預警'])} {html_escape(r['溫度計'])}"
        )
    try:
        from fundamentals import format_fundamentals_html
        fund = format_fundamentals_html(sid, db_path or get_db_path())
        if fund and "尚無" not in fund:
            lines.append("")
            lines.append(fund)
    except Exception:
        pass
    return "\n".join([x for x in lines if x is not None])


def draw_from_ohlc(df: pd.DataFrame, stock_id: str, stock_name: str, save_path: str) -> str:
    if df.empty:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    work = df.copy()
    work["dt"] = pd.to_datetime(work["date"].astype(str), errors="coerce")
    work = work.dropna(subset=["dt"])
    if work.empty:
        return ""
    h20, l20 = work["high"].tail(20).max(), work["low"].tail(20).min()
    h60, l60 = work["high"].tail(60).max(), work["low"].tail(60).min()
    work["ma20"] = work["close"].rolling(20, min_periods=1).mean()
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 6.5), gridspec_kw=dict(height_ratios=(3, 1)), facecolor="#ffffff"
    )
    for i in range(len(work)):
        dt = work["dt"].iloc[i]
        op, cl = work["open"].iloc[i], work["close"].iloc[i]
        hi, lo = work["high"].iloc[i], work["low"].iloc[i]
        color = "#e53935" if cl >= op else "#00897b"
        ax1.plot([dt, dt], [lo, hi], color=color, linewidth=1.0)
        height = max(abs(cl - op), float(cl) * 0.003)
        ax1.add_patch(patches.Rectangle((mdates.date2num(dt) - 0.35, min(op, cl)), 0.7, height, color=color))
    ax1.plot(work["dt"], work["ma20"], color="#fbc02d", linewidth=1.5, label="SMA20")
    ax1.axhline(h60, color="#f48fb1", linewidth=1.2, label=f"季高 {h60:.2f}")
    ax1.axhline(l60, color="#81c784", linewidth=1.2, label=f"季低 {l60:.2f}")
    ax1.axhline(h20, color="#ce93d8", linewidth=1.0, linestyle="--", label=f"月高 {h20:.2f}")
    ax1.axhline(l20, color="#80deea", linewidth=1.0, linestyle="--", label=f"月低 {l20:.2f}")
    ax1.set_title(f"{stock_id} {stock_name} 高低導航", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper left", ncol=3, fontsize=8)
    ax1.grid(True, linestyle=":", alpha=0.5)
    vol_colors = ["#ef5350" if work["close"].iloc[i] >= work["open"].iloc[i] else "#26a69a" for i in range(len(work))]
    ax2.bar(work["dt"], work["volume"], color=vol_colors, width=0.7)
    ax2.set_ylabel("量(張)")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(save_path, dpi=160, bbox_inches="tight")
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


def generate_card_with_chart(stock_id: str, db_path: str = None, charts_dir: str = None):
    sid = str(stock_id).strip()
    html = generate_decision_card(sid, db_path)
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    chart = generate_chart(sid, "", db_path, os.path.join(charts_dir, f"{sid}.png"))
    return html, chart
