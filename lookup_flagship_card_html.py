# -*- coding: utf-8 -*-
# ==============================================================================
# 【給 AI 開發者的強制施工規範（必讀）】
# 1. 嚴禁使用 Pillow (PIL) 或 matplotlib 畫圖！
# 2. 必須直接使用本檔內建的 HTML_TEMPLATE + Playwright (viewport 430x932, DPR=3)
#    截圖輸出 1290x2796 滿版 PNG 後，透過 Telegram sendPhoto 發送。
# 3. 本檔已修正「尺規數字重疊下面 4 格」與「底部卡片過度拉長空白」問題，
#    切勿自行改寫 CSS 結構；只需將即時數據填入 render_single_card() 即可。
# 4. 數據防呆：務必確保「正常目標價 >= 保守目標價」，且區分「累計EPS」與「最新單季EPS」。
# 5. 查股相簿多一張旗艦卡（插第一張）；不准改既有五張圖。低估按鍵走 undervalue D3，不是這張。
# ==============================================================================
"""
WayneBot「單股查詢旗艦卡」單一整合檔（支援 上市/上櫃 與 興櫃 自動切換）
安裝需求：
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VIEW_W = 430
VIEW_H = 932
DPR = 3

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=JetBrains+Mono:wght@500;700&display=swap');
  :root {
    --bg-canvas: #0B1120;
    --bg-card: linear-gradient(180deg, rgba(19, 28, 49, 0.96) 0%, rgba(15, 23, 42, 0.98) 100%);
    --bg-cell: rgba(21, 30, 50, 0.88);
    --border-subtle: #1E293B;
    --text-primary: #F8FAFC;
    --text-secondary: #CBD5E1;
    --text-muted: #94A3B8;
    --tw-up: #F87171;
    --tw-down: #34D399;
    --cyan: #38BDF8;
    --amber: #FBBF24;
    --purple: #A78BFA;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg-canvas);
    font-family: 'Noto Sans TC', -apple-system, BlinkMacSystemFont, 'PingFang TC', sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
  }
  /* 430x932 @3x = 1290x2796，預留上 144px / 下 180px Telegram 安全邊距 */
  .phone-frame {
    width: 430px; height: 932px; background: var(--bg-canvas);
    padding: 28px 6px 38px 6px;
    display: flex; flex-direction: column; justify-content: space-between; gap: 8px; overflow: hidden;
  }
  .mono { font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-variant-numeric: tabular-nums; }

  .outer-card {
    background: var(--bg-card); border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 16px; padding: 10px 10px; display: flex; flex-direction: column; justify-content: space-between; flex: 1; gap: 5px;
  }
  .outer-card.is-wait { border-color: rgba(251, 191, 36, 0.45); }
  .outer-card.is-risk { border-color: rgba(167, 139, 250, 0.5); }
  .outer-card.is-buy  { border-color: rgba(52, 211, 153, 0.5); }

  /* Header */
  .header-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  .header-top > div:first-child { min-width: 0; flex: 1; }
  .stock-title { font-size: 26px; font-weight: 900; line-height: 1.15; white-space: nowrap; overflow: hidden; }
  .stock-sub { font-size: 15px; color: #CBD5E1; margin-top: 5px; white-space: nowrap; overflow: hidden; }
  .header-right { text-align: right; flex-shrink: 0; }
  .price-main { font-size: 26px; font-weight: 800; line-height: 1.1; }
  .price-chg { font-size: 15px; font-weight: 700; margin-top: 4px; }
  .flow-pill {
    display: inline-block; margin-top: 6px; font-size: 13px; font-weight: 700;
    padding: 3px 10px; border-radius: 999px;
    background: rgba(52, 211, 153, 0.14); color: var(--tw-down); border: 1px solid rgba(52, 211, 153, 0.3);
  }
  .up { color: var(--tw-up); } .down { color: var(--tw-down); }
  .cyan { color: var(--cyan); } .amber { color: var(--amber); }

  /* Regime Strip */
  .regime-banner {
    font-size: 12px; font-weight: 700; padding: 6px 10px; border-radius: 9px;
    display: flex; justify-content: space-between; align-items: center;
    background: rgba(245, 158, 11, 0.13); border: 1px solid rgba(245, 158, 11, 0.4); color: #FDE68A;
  }


  /* Action Callout Bar */
  .callout-bar {
    font-size: 11.5px; font-weight: 700; padding: 6px 10px; border-radius: 9px;
    background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.4); color: #E0F2FE;
  }
  .callout-bar.is-em {
    background: rgba(167, 139, 250, 0.13); border-color: rgba(167, 139, 250, 0.42); color: #EDE9FE;
  }

  /* 2x2 Core Matrix */
  .d3-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 7px; }
  .d3-cell {
    background: var(--bg-cell); border: 1px solid #1E293B; border-radius: 10px;
    min-width: 0; padding: 8px 9px; display: flex; flex-direction: column; justify-content: flex-start; gap: 5px;
  }
  .cell-k { font-size: 12px; font-weight: 700; color: #CBD5E1; letter-spacing: 0.2px; }
  .cell-v { font-size: 13.5px; font-weight: 800; color: #FFFFFF; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cell-sub { font-size: 11.5px; color: #E2E8F0; line-height: 1.35; }

  /* 空軌要看得見：淺灰底＋白細框，填色帶微光 */
  .prog-track {
    height: 8px; border-radius: 999px; overflow: hidden;
    background: rgba(148, 163, 184, 0.22); border: 1px solid rgba(226, 232, 240, 0.28);
  }
  .prog-fill {
    height: 100%; border-radius: 999px; background: linear-gradient(90deg, #22D3EE, #38BDF8);
    box-shadow: 0 0 8px rgba(56, 189, 248, 0.75);
  }
  .prog-fill-amber { background: linear-gradient(90deg, #F59E0B, #FCD34D); box-shadow: 0 0 8px rgba(251, 191, 36, 0.75); }

  /* 本益比刻度尺：中線＋小刻度＋左中右大刻度，點不再孤零零 */
  .ruler-track {
    position: relative; height: 14px; margin: 5px 4px 1px 4px;
    background:
      linear-gradient(#E2E8F0, #E2E8F0) left center / 2px 14px no-repeat,
      linear-gradient(#E2E8F0, #E2E8F0) center center / 2px 14px no-repeat,
      linear-gradient(#E2E8F0, #E2E8F0) right center / 2px 14px no-repeat,
      repeating-linear-gradient(90deg, rgba(203, 213, 225, 0.6) 0 1.5px, transparent 1.5px 8.333%) center / 100% 7px no-repeat,
      linear-gradient(rgba(203, 213, 225, 0.45), rgba(203, 213, 225, 0.45)) center / 100% 2px no-repeat;
  }
  .ruler-dot {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 13px; height: 13px; border-radius: 50%; background: #38BDF8;
    border: 2px solid #FFF; box-shadow: 0 0 10px 3px rgba(56, 189, 248, 0.85);
  }
  .ruler-labels { display: flex; justify-content: space-between; font-size: 11px; color: #CBD5E1; }

  .flow-blocks-row { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: #E2E8F0; }
  .sq-group { display: inline-flex; gap: 2.5px; align-items: center; }
  .sq { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
  .sq-b { background: #EF4444; } .sq-s { background: #10B981; } .sq-n { background: #475569; }

  /* Price Ruler Section (固定高度，絕對不會壓到下面4格) */
  .pos-card {
    background: var(--bg-cell); border: 1px solid #1E293B; border-radius: 10px;
    padding: 9px 10px; display: flex; flex-direction: column; gap: 8px;
  }
  .pos-ruler-box {
    position: relative; height: 46px; padding: 18px 0 20px 0; margin: 0 6px;
  }
  .pos-line {
    height: 5px; border-radius: 999px; position: relative;
    background: linear-gradient(90deg, #334155 0%, #38BDF8 45%, #F59E0B 72%, #EF4444 100%);
  }
  .pm {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    display: flex; flex-direction: column; align-items: center;
  }
  .pm-tick { width: 2px; height: 10px; background: #94A3B8; }
  .pm-now {
    width: 11px; height: 11px; border-radius: 50%; background: #38BDF8;
    border: 2px solid #FFF; box-shadow: 0 0 8px rgba(56, 189, 248, 0.9);
  }
  .pm-top { position: absolute; bottom: 13px; white-space: nowrap; font-size: 11px; color: #E2E8F0; }
  .pm-bot { position: absolute; top: 12px; white-space: nowrap; font-size: 11.5px; font-weight: 700; color: #FFFFFF; }

  .metrics-4 {
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 5px;
    padding-top: 2px; text-align: center;
  }
  .m4-box {
    display: flex; flex-direction: column; justify-content: center; gap: 2px;
    padding: 6px 4px; border-radius: 8px;
    background: rgba(30, 41, 59, 0.6); border: 1px solid rgba(148, 163, 184, 0.2);
  }
  .m4-box.tint-green { background: rgba(16, 185, 129, 0.14); border-color: rgba(52, 211, 153, 0.35); }
  .m4-box.tint-blue  { background: rgba(56, 189, 248, 0.14); border-color: rgba(56, 189, 248, 0.38); }
  .m4-box.tint-amber { background: rgba(245, 158, 11, 0.14); border-color: rgba(251, 191, 36, 0.38); }
  .m4-box.tint-red   { background: rgba(239, 68, 68, 0.14); border-color: rgba(248, 113, 113, 0.38); }
  .m4-k { font-size: 11px; color: #CBD5E1; }
  .m4-v { font-size: 13px; font-weight: 800; color: #FFFFFF; }

  /* Bottom Split (固定緊湊高度，不留大塊黑底) */
  .bottom-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 7px; }
  .peer-row { display: flex; justify-content: space-between; font-size: 13px; font-weight: 700; padding: 3px 0; }
  .moat-text { font-size: 12.5px; color: #E2E8F0; line-height: 1.45; }
  .moat-text strong { color: var(--text-primary); }

  .footer-legend { text-align: center; font-size: 10.5px; color: #CBD5E1; padding-top: 2px; }
</style>
</head>
<body>
  <div class="phone-frame">
    <div class="outer-card {{CARD_STATUS_CLS}}">
      <!-- HEADER -->
      <div class="header-top">
        <div>
          <div class="stock-title">{{ICON}} {{STATUS_LABEL}}｜{{TICKER}} {{NAME}}</div>
          <div class="stock-sub">{{MARKET_SECTOR}}</div>
        </div>
        <div class="header-right">
          <div class="price-main mono {{PRICE_CLASS}}">{{PRICE}}</div>
          <div class="price-chg mono {{PRICE_CLASS}}">{{CHANGE_PCT}}</div>
          <span class="flow-pill">{{FLOW_PILL}}</span>
        </div>
      </div>

      <!-- REGIME STRIP -->
      <div class="regime-banner">
        <span>{{REGIME_TEXT}}</span>
        <span class="mono">{{REGIME_RIGHT}}</span>
      </div>

      <!-- ACTION CALLOUT -->
      <div class="callout-bar {{CALLOUT_CLS}}">💡 策略提示：{{ACTION_CALLOUT}}</div>

      <!-- 2x2 CORE MATRIX -->
      <div class="d3-grid">
        <div class="d3-cell">
          <div class="cell-k">今年賺錢進度</div>
          <div class="cell-v mono">已賺 {{EPS_YTD}} / 估 {{EPS_EST_YR}} ({{EPS_PCT}}%)</div>
          <div class="prog-track"><div class="prog-fill {{BAR_CLS}}" style="width: {{EPS_PCT_CLAMP}}%;"></div></div>
          <div class="cell-sub">{{Q4_PROGRESS}}｜最新單季 {{EPS_LATEST_Q}}</div>
        </div>

        <div class="d3-cell">
          <div class="cell-k">未來 12 個月滾動本益比</div>
          <div class="cell-v mono cyan">{{PE_FWD12M}}倍 <span class="cell-sub">({{PE_NOTE}})</span></div>
          <div class="ruler-track"><div class="ruler-dot" style="left: {{PE_DOT_PCT}}%;"></div></div>
          <div class="ruler-labels mono"><span>{{PE_MIN}}</span><span>{{PE_MID}}</span><span>{{PE_MAX}}</span></div>
        </div>

        <div class="d3-cell">
          <div class="cell-k">{{BL_TITLE}}</div>
          <div class="cell-v mono">正常 {{TARGET_NORM}}｜保守 {{TARGET_CONS}}</div>
          {{BL_BOTTOM_HTML}}
        </div>

        <div class="d3-cell">
          <div class="cell-k">營收達標進度＋撐壓</div>
          <div class="cell-v mono">{{REV_NOW}} / {{REV_GATE}} ({{REV_PCT}}%)</div>
          <div class="prog-track"><div class="prog-fill {{BAR_CLS}}" style="width: {{REV_PCT_CLAMP}}%;"></div></div>
          <div class="cell-sub mono {{SUPPORT_CLASS}}">{{SUPPORT_TEXT}}</div>
        </div>
      </div>

      <!-- PRICE RULER SECTION -->
      <div class="pos-card">
        <div class="cell-k">{{RULER_TITLE}}</div>
        <div class="pos-ruler-box">
          <div class="pos-line">
            {{RULER_MARKERS_HTML}}
          </div>
        </div>
        <div class="metrics-4">
          <div class="m4-box {{M1_TINT}}"><span class="m4-k">{{M1_K}}</span><span class="m4-v mono">{{M1_V}}</span></div>
          <div class="m4-box {{M2_TINT}}"><span class="m4-k">{{M2_K}}</span><span class="m4-v mono">{{M2_V}}</span></div>
          <div class="m4-box {{M3_TINT}}"><span class="m4-k">{{M3_K}}</span><span class="m4-v mono">{{M3_V}}</span></div>
          <div class="m4-box {{M4_TINT}}"><span class="m4-k">{{M4_K}}</span><span class="m4-v mono">{{M4_V}}</span></div>
        </div>
      </div>

      <!-- EXTRA DEPTH STRIP (利用統整後的空間補上融資/10日累計/關鍵事件) -->
      <div class="d3-cell" style="padding: 6px 9px;">
        <div class="cell-k">{{EXTRA_STRIP_TITLE}}</div>
        <div class="cell-v mono" style="font-size: 11.5px;">{{EXTRA_STRIP_VAL}}</div>
      </div>

      <!-- BOTTOM SPLIT -->
      <div class="bottom-split">
        <div class="d3-cell">
          <div class="cell-k">同族群對照 ({{PEER_CHAIN}})</div>
          {{PEERS_HTML}}
        </div>
        <div class="d3-cell">
          <div class="cell-k">護城河與最大風險</div>
          <div class="moat-text"><strong>優勢：</strong>{{MOAT_TEXT}}<br><span class="up"><strong>風險：</strong>{{RISK_TEXT}}</span></div>
        </div>
      </div>
    </div>

    <div class="footer-legend">{{FOOTER_TEXT}}</div>
  </div>
</body>
</html>
"""


def _finite(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def _fmt_num(v: Any, digits: int = 1) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    s = f"{x:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _fmt_price(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    # 千元以上一律整數，避免格內「正常 4,088.9｜…」被裁掉％與保守價
    if abs(x) >= 1000:
        return f"{round(x):,}"
    if abs(x - round(x)) < 1e-9:
        return f"{x:.0f}"
    if abs(x) >= 100:
        return f"{x:.1f}"
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _fmt_yi(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    if abs(x) < 10:
        return f"{x:.2f}".rstrip("0").rstrip(".")
    return _fmt_num(x, 1)


def calc_forward_12m_eps(y: float, n: float, ref: Optional[date] = None) -> float:
    d = ref or date.today()
    w = max(0, 12 - d.month + 1) / 12.0
    return round(y * w + n * (1.0 - w), 2)


def _net_flag(v: float) -> str:
    if v > 0:
        return "B"
    if v < 0:
        return "S"
    return "N"


def _sq(flags: Sequence[str]) -> str:
    m = {"B": "sq-b", "S": "sq-s", "N": "sq-n"}
    out = []
    for x in (list(flags) + ["N"] * 5)[:5]:
        out.append(f'<span class="sq {m.get(str(x)[:1].upper(),"sq-n")}"></span>')
    return "".join(out)


def _streak(flags: Sequence[str], want: str) -> int:
    n = 0
    for x in reversed(list(flags)[:5]):
        if str(x).upper()[:1] != want:
            break
        n += 1
    return n


def _chip_pills(f5: Sequence[str], t5: Sequence[str]) -> List[Tuple[str, str]]:
    """回傳 [(cls, txt), ...]；mock 風格可拆成「投信護盤」「外資賣」兩顆。"""
    f5 = [(str(x).upper()[:1] if str(x).upper()[:1] in "BSN" else "N") for x in (list(f5) + ["N"] * 5)[:5]]
    t5 = [(str(x).upper()[:1] if str(x).upper()[:1] in "BSN" else "N") for x in (list(t5) + ["N"] * 5)[:5]]
    tb, fb = _streak(t5, "B"), _streak(f5, "B")
    f_sell = sum(1 for x in f5 if x == "S")
    t_buy = sum(1 for x in t5 if x == "B")
    nf, nt = f5[-1], t5[-1]
    if nf == "S" and nt == "S":
        return [("pill-sell", "外投同賣")]
    if nf == "B" and nt == "B":
        return [("pill-buy", "外投同買")]
    if (t_buy >= 2 and f_sell >= 2 and nt == "B") or (nt == "B" and nf == "S"):
        return [("pill-chip", "投信護盤"), ("pill-sell", "外資賣")]
    if tb >= 2:
        return [("pill-buy", f"投信連買{tb}日")]
    if fb >= 2:
        return [("pill-buy", f"外資連買{fb}日")]
    if f_sell >= 2:
        return [("pill-sell", "法人調節")]
    return []


# 旗艦卡短產業／同族偏好（顯示標籤；價／EPS 仍走官方庫）
_INDUSTRY_SHORT_FORCE = {
    "3595": "先進封裝材料",
    "2383": "AI高階CCL",
}
_PEER_PREF = {
    "2383": ("6274", "6213"),  # 台燿、聯茂（不准混設備股）
    "3595": ("5434", "3010"),  # 崇越、華立（封裝材料對照）
}
# 官方季報／現增尚未入庫時，旗艦卡用已核定數字補缺（有庫優先；不准發明 OHLC）
_FLAGSHIP_FUND_OVERLAY: Dict[str, Dict[str, Any]] = {
    "3595": {
        "season": 3,
        "eps_e": 5.99,
        "eps_q": 2.97,
        "gm": 77.4,
        "eps_y": 9.2,
        "eps_n": 20.4,
        "pe_y": 28.0,
        "pe_n": 22.0,
        "tgt": 570.0,
        "fair": 456.0,
        "thr": 1.05,
        "placement": 400.0,
        "dilute_yi": 4.68,
        "place_shares": 610.0,
        "listing_note": "2027/01 預計上櫃",
        "moat_text": "先進封裝高毛利（77.4%）",
        "risk_text": "營收趨緩、量小折價",
    },
    "2383": {
        "moat_text": "AI基板市占 &gt; 70%、M9量產",
        "risk_text": "外資調節、無高息底",
    },
}


def _q4(yyyymm: Optional[str]) -> str:
    s = str(yyyymm or "").replace("-", "")[:6]
    if len(s) != 6 or not s.isdigit():
        return "Q4: 10·11·12待補"
    m = int(s[4:6])
    if m < 10:
        return "Q4: 10·11·12待補"
    if m == 10:
        return "Q4: 10月✓・11·12待補"
    if m == 11:
        return "Q4: 10月✓・11月✓・12待補"
    return "Q4: 10·11·12月✓"


def _pe_scale(pe: Optional[float], lo: Optional[float], hi: Optional[float]) -> Tuple[str, str, str, float]:
    vals = [v for v in (pe, lo, hi) if v is not None and v > 0]
    if not vals:
        return "—", "—", "—", 50.0
    a, b = float(min(vals)), float(max(vals))
    pad = max((b - a) * 0.2, 1.5)
    x0, x2 = max(1.0, math.floor(a - pad)), math.ceil(b + pad)
    if x2 <= x0:
        x2 = x0 + 5
    x1 = round((x0 + x2) / 2)
    pct = 50.0
    if pe is not None:
        pct = max(8.0, min(92.0, (float(pe) - x0) / (x2 - x0) * 100.0))
    return f"{int(x0)}x", f"{int(x1)}x", f"{int(x2)}x", pct


def _chip_days(con: sqlite3.Connection, day: str, n: int = 5) -> List[str]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-','') AS d FROM daily_quotes
        WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
        GROUP BY d
        HAVING SUM(ABS(COALESCE(foreign_net,0)))+SUM(ABS(COALESCE(trust_net,0)))>0
        ORDER BY d DESC LIMIT ?
        """,
        (day, n),
    ).fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


def _regime(con: sqlite3.Connection, day: str) -> dict:
    fx = None
    try:
        row = con.execute("SELECT payload FROM us_overnight ORDER BY as_of DESC LIMIT 1").fetchone()
        if row and row[0]:
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            fx = _finite((payload or {}).get("usdtwd_px"))
    except Exception:
        pass
    above = True
    try:
        tw = con.execute(
            "SELECT close, ma20 FROM index_daily WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')<=? ORDER BY date DESC LIMIT 1",
            (day,),
        ).fetchone()
        if tw and _finite(tw[0]) is not None and _finite(tw[1]) is not None:
            above = float(tw[0]) >= float(tw[1])
    except Exception:
        pass
    streak = 0
    try:
        for r in con.execute(
            "SELECT foreign_net_yi FROM market_inst_bfi_daily WHERE REPLACE(CAST(date AS TEXT),'-','')<=? ORDER BY date DESC LIMIT 12",
            (day,),
        ).fetchall():
            v = _finite(r[0])
            if v is not None and v < 0:
                streak += 1
            else:
                break
    except Exception:
        pass
    if fx is None:
        return {"cls": "banner-ok", "text": "資金水位中性｜匯率待補", "right": "USD/TWD —"}
    if fx >= 32.8 and streak >= 2 and not above:
        return {
            "cls": "banner-fx",
            "text": "⚠️ 資金偏緊（台幣偏弱・外資賣超）｜多因素並存",
            "right": f"USD/TWD {fx:.2f}",
        }
    if not above and streak >= 3:
        return {
            "cls": "banner-bear",
            "text": "⚠️ 大盤偏弱（站下 MA20・外資連賣）｜多因素並存",
            "right": f"USD/TWD {fx:.2f}",
        }
    return {
        "cls": "banner-ok",
        "text": "資金水位中性｜依區間與支撐操作",
        "right": f"USD/TWD {fx:.2f}",
    }


def _rail_html(marks: Sequence[dict]) -> str:
    vals = [float(m["value"]) for m in marks if _finite(m.get("value")) is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1e-6)
    parts = []
    for m in marks:
        v = _finite(m.get("value"))
        if v is None:
            continue
        pct = max(3.0, min(97.0, (v - lo) / span * 100.0))
        kind = str(m.get("kind") or "")
        cls = "mk"
        if kind:
            cls += f" {kind}"
        parts.append(
            f'<div class="{cls}" style="left:{pct:.1f}%;">'
            f'<div class="lab">{html.escape(str(m.get("label") or ""))}</div>'
            f'<div class="tick"></div>'
            f'<div class="val mono">{html.escape(_fmt_price(v))}</div></div>'
        )
    return "".join(parts)


def _stat4_html(cells: Sequence[Tuple[str, str, str]]) -> str:
    """(k, v, extra_cls)"""
    out = []
    for k, v, extra in list(cells)[:4]:
        out.append(
            f'<div class="cell"><div class="k">{html.escape(k)}</div>'
            f'<div class="v mono {html.escape(extra)}">{html.escape(v)}</div></div>'
        )
    while len(out) < 4:
        out.append('<div class="cell"><div class="k">—</div><div class="v">—</div></div>')
    return "".join(out)


def _short_industry(sid: str, chain: str, emerging: bool = False) -> str:
    forced = _INDUSTRY_SHORT_FORCE.get(str(sid))
    if forced:
        return forced
    c = str(chain or "")
    if re.search(r"CCL|銅箔基板|PCB.*材料|材料設備", c, re.I):
        return "AI高階CCL"
    if re.search(r"先進封裝|封裝材料|特化材料", c, re.I):
        return "先進封裝材料"
    if not c:
        return "—"
    tail = c.split("-")[-1].strip()
    return tail or c


def _prior_platform(bars: Sequence[tuple]) -> Tuple[Optional[float], Optional[float]]:
    """興櫃前波平台／前高壓：取上一根完整柱的低／高（官方柱，非發明）。"""
    if len(bars) < 2:
        return None, None
    prev = bars[-2]
    lo = _finite(prev[2])
    hi = _finite(prev[1])
    return lo, hi


def _soft_growth(
    con: sqlite3.Connection,
    sid: str,
    *,
    close: Optional[float],
    chain: str,
    name: str,
) -> Dict[str, Any]:
    """旗艦卡顯示用軟估算：不強制過低估鐵律；缺官方季報就不填。"""
    out: Dict[str, Any] = {}
    try:
        from undervalue_growth import (
            estimate_eps_year_next,
            industry_bucket,
            load_quarter_fundamentals,
            load_recent_moms,
            price_targets,
            select_fair_pe_pair,
        )
    except Exception:
        return out

    fund = {}
    season_used = None
    for year, season in ((2026, 3), (2026, 2), (2026, 1), (2025, 4)):
        f = load_quarter_fundamentals(con, sid, year=year, season=season)
        if f.get("eps") is not None or f.get("gross_margin_pct") is not None:
            fund = f
            season_used = season
            break
    ov = _FLAGSHIP_FUND_OVERLAY.get(sid) or {}
    from_overlay = False
    # 庫內還沒有更新季時，用已核定 overlay（例如 3595 Q3）；官方季報一入庫就自動改用庫
    if ov and ov.get("season") and (season_used is None or int(season_used) < int(ov["season"])):
        from_overlay = True
        fund = {
            "eps": ov.get("eps_e"),
            "eps_single": ov.get("eps_q"),
            "gross_margin_pct": ov.get("gm"),
        }
        season_used = int(ov["season"])
    if not fund and not ov:
        return out

    bucket = industry_bucket(chain, (), name)
    pe_y, pe_n, _ = select_fair_pe_pair(25.0, bucket)
    if ov.get("pe_y") is not None:
        pe_y = float(ov["pe_y"])
    if ov.get("pe_n") is not None:
        pe_n = float(ov["pe_n"])
    moms, last_rev, ytd_rev, m_last = load_recent_moms(con, sid, n=3)
    eps_est = estimate_eps_year_next(
        eps_ytd_cum=fund.get("eps"),
        eps_q3_single=fund.get("eps_single"),
        ytd_rev=ytd_rev,
        last_rev=last_rev,
        moms=moms,
        m_last=m_last or 10,
        yoy_pct=None,
    )
    out["eps_e"] = _finite(fund.get("eps"))
    out["eps_q"] = _finite(fund.get("eps_single"))
    out["gm"] = _finite(fund.get("gross_margin_pct"))
    out["season"] = season_used
    out["pe_y"] = pe_y
    out["pe_n"] = pe_n
    out["bucket"] = bucket
    if eps_est.get("ok") and close and close > 0:
        out["eps_y"] = _finite(eps_est.get("eps_2026"))
        out["eps_n"] = _finite(eps_est.get("eps_2027"))
        out["thr"] = _finite(eps_est.get("rev_threshold_yi"))
        tg = price_targets(
            float(close),
            20.0,
            float(eps_est["eps_2026"]),
            float(eps_est["eps_2027"]),
            float(pe_y),
            float(pe_n),
        )
        out["fair"] = _finite(tg.get("fair_year"))
        out["tgt"] = _finite(tg.get("target_next"))
    # overlay 只在「庫缺那一季」時整組帶入；庫有官方季報就全部用滾動估算
    if from_overlay:
        for k in ("eps_e", "eps_q", "gm", "eps_y", "eps_n", "thr", "fair", "tgt", "pe_y", "pe_n"):
            if ov.get(k) is not None:
                out[k] = _finite(ov.get(k))
        out["season"] = int(ov["season"])
    return out


def _peer_pe(con: sqlite3.Connection, sid: str, day: str) -> Optional[float]:
    """粗本益：現價／最新累計 EPS（僅同族對照顯示；非買訊）。"""
    q = con.execute(
        """
        SELECT close FROM daily_quotes
        WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? AND close>0
        ORDER BY date DESC LIMIT 1
        """,
        (sid, day),
    ).fetchone()
    if not q:
        q = con.execute(
            """
            SELECT close FROM emerging_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? AND close>0
            ORDER BY date DESC LIMIT 1
            """,
            (sid, day),
        ).fetchone()
    eps = con.execute(
        """
        SELECT eps FROM quarterly_income
        WHERE stock_id=? AND eps IS NOT NULL AND eps>0
        ORDER BY year DESC, season DESC LIMIT 1
        """,
        (sid,),
    ).fetchone()
    if not q or not eps:
        return None
    c, e = _finite(q[0]), _finite(eps[0])
    if c is None or e is None or e <= 0:
        return None
    return c / e


def _load_peers(
    con: sqlite3.Connection,
    sid: str,
    industry: str,
    day: str,
    *,
    emerging: bool,
    limit: int = 3,
) -> List[dict]:
    ordered: List[str] = []
    pref = _PEER_PREF.get(sid) or ()
    for p in pref:
        if p != sid:
            ordered.append(str(p))
    # 有同族偏好就只走偏好，不准再用細項鏈去塞設備股（如川寶）
    if not ordered and industry:
        for row in con.execute(
            "SELECT stock_id FROM stock_fine_industry WHERE chain=? LIMIT 40",
            (industry,),
        ).fetchall():
            pid = str(row[0])
            if pid != sid and pid not in ordered:
                ordered.append(pid)
    out: List[dict] = []
    for pid in ordered:
        pn = con.execute(
            "SELECT stock_name FROM stock_directory WHERE stock_id=?", (pid,)
        ).fetchone()
        if not pn:
            continue
        pe = _peer_pe(con, pid, day)
        # 上市同族對照只留有本益比的；不准用「收 xx」混進來
        if (not emerging) and pe is None:
            continue
        close_row = con.execute(
            """
            SELECT close FROM daily_quotes
            WHERE stock_id=? AND close>0 ORDER BY date DESC LIMIT 1
            """,
            (pid,),
        ).fetchone()
        out.append(
            {
                "stock_id": pid,
                "name": str(pn[0]),
                "pe": pe,
                "close": _finite(close_row[0]) if close_row else None,
            }
        )
        if len(out) >= limit:
            break
    return out


_TONE_TINT: Dict[str, str] = {
    "dn": "tint-green",
    "good": "tint-green",
    "up": "tint-red",
    "hot": "tint-red",
    "cold": "tint-blue",
    "warn": "tint-amber",
}


# 上市櫃一般業財報法定公告期限（月, 日, 標籤）；官方行事曆沒有未來法說時才用
_REPORT_DEADLINES: Tuple[Tuple[int, int, str], ...] = (
    (3, 31, "年報期限"),
    (5, 15, "Q1財報期限"),
    (8, 14, "Q2財報期限"),
    (11, 14, "Q3財報期限"),
)


def _next_event_label(db_path: str, sid: str, day: str) -> str:
    """官方 company_events 有未來法說／股東會就用；否則給下一個法定財報期限。"""
    try:
        con = sqlite3.connect(db_path)
        try:
            row = con.execute(
                """
                SELECT event_date, kind FROM company_events
                WHERE stock_id=? AND event_date>? AND kind IN ('法說','常會','臨時會')
                ORDER BY event_date ASC LIMIT 1
                """,
                (sid, day),
            ).fetchone()
        finally:
            con.close()
    except Exception:
        row = None
    if row:
        ymd, kind = str(row[0]), str(row[1])
        lab = "法說" if kind == "法說" else "股東會"
        return f"{lab} {ymd[:4]}/{ymd[4:6]}/{ymd[6:8]}"
    y = int(day[:4])
    md = int(day[4:8])
    for yy in (y, y + 1):
        for mm, dd, lab in _REPORT_DEADLINES:
            if yy > y or mm * 100 + dd > md:
                return f"{lab} {yy}/{mm:02d}/{dd:02d}"
    return "財報期限 —"


def _strategy_tip(
    *,
    emerging: bool,
    broke: bool,
    support: Optional[float],
    thr: Optional[float],
    chip_f: Sequence[str],
    rev_ym: Optional[str] = None,
    buy_sig: Optional[str] = None,
) -> str:
    if emerging:
        if thr is None:
            return "興櫃量小價差大，量縮別追高"
        mm = int(rev_ym[4:6]) if rev_ym and len(rev_ym) == 6 else 0
        if mm == 10:
            span = "11–12 月"
        elif 1 <= mm <= 11:
            span = f"{mm + 1} 月"
        else:
            span = "月"
        return f"興櫃量小價差大，緊盯 {span}營收過 {_fmt_yi(thr)} 億門檻"
    foreign_selling = sum(1 for x in list(chip_f)[-5:] if x == "S") >= 3
    if buy_sig:
        why = "高低卡剛離零" if buy_sig == "leave_zero" else "紅箭頭過 ma60 確認"
        if support is not None and broke:
            return f"{why}，買點成立；仍在大量撐 {_fmt_price(support)} 下，分批別重壓"
        if support is not None:
            return f"{why}，買點成立；跌破大量撐 {_fmt_price(support)} 先停看"
        return f"{why}，買點成立"
    if support is None:
        return "撐壓待補，先看高低卡買點再動"
    s = _fmt_price(support)
    if broke:
        if foreign_selling:
            return f"等站回大量撐 {s} 或外資賣壓縮手再出手"
        return f"等站回大量撐 {s} 再出手"
    return f"守住大量撐 {s} 再看高低卡買點，跌破先停看"


def _buy_signal(db_path: str, sid: str, day: str) -> Optional[str]:
    """只認已量化過關的買訊：高低卡剛離零（leave_zero）或 ma60_lower 確認紅箭頭。"""
    try:
        import pandas as pd

        from decision_card_signals import leave_zero_from_quote_df
        from red_arrow_quant import nav_low_ma60_lower_mask

        con = sqlite3.connect(db_path)
        try:
            rows = con.execute(
                """
                SELECT stock_id, REPLACE(CAST(date AS TEXT),'-','') AS d, open, high, low, close, volume
                FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? AND close>0
                ORDER BY d DESC LIMIT 200
                """,
                (sid, day),
            ).fetchall()
        finally:
            con.close()
        if len(rows) < 61:
            return None
        df = pd.DataFrame(
            list(reversed(rows)),
            columns=["stock_id", "date", "open", "high", "low", "close", "volume"],
        )
        try:
            from wayne_navigator import frame_for_cal60_profit

            profit_df = frame_for_cal60_profit(df, db_path)
        except Exception:
            profit_df = df
        if leave_zero_from_quote_df(profit_df):
            return "leave_zero"
        mask = nav_low_ma60_lower_mask(df)
        if len(mask) and bool(mask.iloc[-1]):
            return "red_arrow"
    except Exception:
        return None
    return None


def build_flagship_payload(
    db_path: str,
    stock_id: str,
    *,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    sid = str(stock_id or "").strip()
    day = str(as_of or "").replace("-", "")[:8]
    if len(day) != 8:
        day = date.today().strftime("%Y%m%d")
    ref = date(int(day[:4]), int(day[4:6]), int(day[6:8]))

    name, market, industry = sid, "", ""
    emerging = False
    close = pct = None
    bars: List[tuple] = []
    support = resist = half_low = high60 = ma60 = ma20 = None
    rev_yi = rev_ym = mom_pct = None
    chip_f = ["N"] * 5
    chip_t = ["N"] * 5
    peers_raw: List[dict] = []
    regime = {"cls": "banner-ok", "text": "", "right": ""}
    listing_note = "預計上櫃 —"

    con = sqlite3.connect(db_path)
    try:
        r = con.execute(
            "SELECT stock_name, market FROM stock_directory WHERE stock_id=?", (sid,)
        ).fetchone()
        if r:
            name, market = str(r[0] or sid), str(r[1] or "")
        emerging = market.upper() in ("EM", "EMERGING", "興櫃")

        try:
            fi = con.execute(
                "SELECT chain FROM stock_fine_industry WHERE stock_id=?", (sid,)
            ).fetchone()
            if fi and fi[0]:
                industry = str(fi[0])
        except Exception:
            pass

        q = con.execute(
            """
            SELECT close, pct_change FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
              AND close IS NOT NULL AND close>0
            ORDER BY date DESC LIMIT 1
            """,
            (sid, day),
        ).fetchone()
        if q:
            close, pct = _finite(q[0]), _finite(q[1])
        if close is None and emerging:
            q = con.execute(
                """
                SELECT close FROM emerging_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND close>0 ORDER BY date DESC LIMIT 1
                """,
                (sid, day),
            ).fetchone()
            if q:
                close = _finite(q[0])

        cols = [c[1] for c in con.execute("PRAGMA table_info(daily_quotes)").fetchall()]
        pcol = "adj_close" if "adj_close" in cols else "close"
        try:
            bars = con.execute(
                f"""
                SELECT date, high, low, {pcol}, volume FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND {pcol}>0 ORDER BY date ASC
                """,
                (sid, day),
            ).fetchall()
        except Exception:
            bars = []
        if not bars and emerging:
            bars = con.execute(
                """
                SELECT date, high, low, close, volume FROM emerging_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND close>0 ORDER BY date ASC
                """,
                (sid, day),
            ).fetchall()

        if bars:
            closes = [float(b[3]) for b in bars]
            lows = [float(b[2]) for b in bars if _finite(b[2])]
            highs = [float(b[1]) for b in bars if _finite(b[1])]
            if close is None and closes:
                close = closes[-1]
            win = closes[-60:] if len(closes) >= 60 else closes
            if win:
                ma60 = sum(win) / len(win)
            win20 = closes[-20:]
            if len(win20) >= 20:
                ma20 = sum(win20) / 20.0
            if highs:
                high60 = max(highs[-60:] if len(highs) >= 60 else highs)
            if lows:
                half_low = min(lows[-126:] if len(lows) >= 126 else lows)

        # 興櫃：前波平台／前高壓取上一根官方柱；上市：大量區
        if emerging:
            plat_lo, plat_hi = _prior_platform(bars)
            if plat_lo is not None:
                support = plat_lo
            if plat_hi is not None:
                resist = plat_hi
        else:
            try:
                import pandas as pd
                from vol_zone_chart import find_volume_zone

                if len(bars) >= 12:
                    df = pd.DataFrame(
                        [
                            {
                                "date": str(b[0]),
                                "open": float(b[3]),
                                "high": float(b[1] or b[3]),
                                "low": float(b[2] or b[3]),
                                "close": float(b[3]),
                                "volume": float(b[4] or 0),
                            }
                            for b in bars
                        ]
                    )
                    z = find_volume_zone(df) or {}
                    support = _finite(z.get("low"))
                    resist = _finite(z.get("high"))
            except Exception:
                pass

        if pct is None and len(bars) >= 2:
            c0, c1 = _finite(bars[-1][3]), _finite(bars[-2][3])
            if c0 is not None and c1 not in (None, 0):
                pct = (c0 - c1) / c1 * 100.0

        mr = con.execute(
            """
            SELECT yyyymm, revenue FROM monthly_revenue
            WHERE stock_id=? AND REPLACE(CAST(yyyymm AS TEXT),'-','')<=?
            ORDER BY yyyymm DESC LIMIT 2
            """,
            (sid, day[:6]),
        ).fetchall()
        if mr:
            rev_ym = str(mr[0][0]).replace("-", "")[:6]
            rev_yi = float(mr[0][1]) / 100000.0 if _finite(mr[0][1]) else None
            if len(mr) >= 2 and _finite(mr[0][1]) and _finite(mr[1][1]) and float(mr[1][1]) > 0:
                mom_pct = (float(mr[0][1]) - float(mr[1][1])) / float(mr[1][1]) * 100.0

        if not emerging:
            days = _chip_days(con, day, 5)
            got_f: List[str] = []
            got_t: List[str] = []
            for d in reversed(list(days)[:5]):
                net = con.execute(
                    """
                    SELECT foreign_net, trust_net FROM daily_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
                    LIMIT 1
                    """,
                    (sid, str(d).replace("-", "")[:8]),
                ).fetchone()
                if net is None:
                    got_f.append("N")
                    got_t.append("N")
                else:
                    got_f.append(_net_flag(float(net[0] or 0)))
                    got_t.append(_net_flag(float(net[1] or 0)))
            if got_f:
                chip_f = (["N"] * 5 + got_f)[-5:]
                chip_t = (["N"] * 5 + got_t)[-5:]

        peers_raw = _load_peers(
            con, sid, industry, day, emerging=emerging, limit=2 if emerging else 3
        )

        regime = (
            {
                "cls": "banner-em",
                "text": "⚠️ 興櫃透明度較低｜無每日法人進出與融資數據",
                "right": listing_note,
            }
            if emerging
            else _regime(con, day)
        )
    finally:
        con.close()

    # 成長估算／季報（低估鐵律過不了仍用軟估算填旗艦卡；不准發明柱）
    eps_e = eps_y = eps_n = eps_q = None
    pe_y = pe_n = fair = tgt = thr = gm = None
    placement = dilute_yi = place_shares = None
    season_used = None
    peer_label = _short_industry(sid, industry, emerging)
    moat_html = ""

    try:
        con2 = sqlite3.connect(db_path)
        try:
            from undervalue_growth import enrich_growth_row

            qty60_tmp = 1000.0
            if bars:
                vols = [float(b[4] or 0) for b in bars[-60:]]
                if vols:
                    qty60_tmp = sum(vols) / len(vols) / 1000.0
            eg = enrich_growth_row(
                con2,
                sid=sid,
                name=name,
                close=float(close or 0),
                pe=20.0,
                peer_med_raw=25.0,
                as_of=day,
                yoy_pct=None,
                qty60=float(qty60_tmp),
                market_type="EM" if emerging else "TW",
            )
            if eg:
                eps_e = _finite(eg.get("eps_earned"))
                eps_y = _finite(eg.get("eps_2026"))
                eps_n = _finite(eg.get("eps_2027"))
                pe_y = _finite(eg.get("pe_year"))
                pe_n = _finite(eg.get("pe_next"))
                fair = _finite(eg.get("fair_year"))
                tgt = _finite(eg.get("target_next"))
                thr = _finite(eg.get("rev_threshold_yi"))
                gm = _finite(eg.get("gross_margin"))
                if (not emerging) and _finite(eg.get("support")) is not None:
                    support = _finite(eg.get("support"))
                if (not emerging) and _finite(eg.get("resistance")) is not None:
                    resist = _finite(eg.get("resistance"))
                if eg.get("industry"):
                    peer_label = _short_industry(sid, str(eg.get("industry")), emerging)

            soft = _soft_growth(con2, sid, close=close, chain=industry, name=name)
            if soft:
                season_used = soft.get("season")
                eps_e = eps_e if eps_e is not None else soft.get("eps_e")
                eps_q = soft.get("eps_q") if soft.get("eps_q") is not None else eps_q
                gm = soft.get("gm") if soft.get("gm") is not None else gm
                # soft／overlay 若季別更新，允許蓋過 enrich 的舊季數字
                if soft.get("eps_e") is not None and (
                    season_used is not None
                    and int(season_used) >= 3
                    and (eps_e is None or float(soft["eps_e"]) > float(eps_e or 0))
                ):
                    eps_e = soft.get("eps_e")
                if soft.get("eps_y") is not None:
                    eps_y = soft.get("eps_y")
                if soft.get("eps_n") is not None:
                    eps_n = soft.get("eps_n")
                if soft.get("pe_y") is not None:
                    pe_y = soft.get("pe_y")
                if soft.get("pe_n") is not None:
                    pe_n = soft.get("pe_n")
                if soft.get("fair") is not None:
                    fair = soft.get("fair")
                if soft.get("tgt") is not None:
                    tgt = soft.get("tgt")
                if soft.get("thr") is not None:
                    thr = soft.get("thr")

            row = con2.execute(
                "SELECT detail_json FROM undervalue_picks WHERE stock_id=? ORDER BY as_of DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if row and row[0]:
                d = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                placement = _finite(d.get("placement_price") or d.get("offer_price"))
                dilute_yi = _finite(d.get("dilute_capital_yi") or d.get("dilution_yi"))
                place_shares = _finite(d.get("placement_shares_wan") or d.get("offer_shares_wan"))
                if d.get("listing_eta"):
                    listing_note = str(d.get("listing_eta"))
                    if emerging:
                        regime["right"] = listing_note
                if d.get("industry_short"):
                    peer_label = str(d.get("industry_short"))
                if d.get("moat_text"):
                    moat_html = str(d.get("moat_text"))
                if (not emerging) and _finite(d.get("support")) is not None:
                    support = _finite(d.get("support"))
                if (not emerging) and _finite(d.get("resistance")) is not None:
                    resist = _finite(d.get("resistance"))

            # 現增／上櫃核定 overlay（庫缺才補）
            ov = _FLAGSHIP_FUND_OVERLAY.get(sid) or {}
            if emerging and ov:
                if placement is None and ov.get("placement") is not None:
                    placement = float(ov["placement"])
                if dilute_yi is None and ov.get("dilute_yi") is not None:
                    dilute_yi = float(ov["dilute_yi"])
                if place_shares is None and ov.get("place_shares") is not None:
                    place_shares = float(ov["place_shares"])
                if ov.get("listing_note") and listing_note == "預計上櫃 —":
                    listing_note = str(ov["listing_note"])
                    regime["right"] = listing_note
        finally:
            con2.close()
    except Exception:
        pass

    # 營收月門檻：軟估若低於「近月營收×溫和成長」就抬到這條（避免需需／門檻過低）
    if rev_yi is not None and rev_yi > 0:
        gate_floor = float(rev_yi) * (1.10 if emerging else 1.08)
        if thr is None or float(thr) < gate_floor:
            thr = gate_floor

    broke = close is not None and support is not None and close < support
    qty60 = None
    if bars:
        vols = [float(b[4] or 0) for b in bars[-60:]]
        if vols:
            qty60 = sum(vols) / len(vols) / 1000.0

    buy_sig = None if emerging else _buy_signal(db_path, sid, day)
    if emerging:
        status, icon, status_label = "risk", "⚠️", "興櫃量小"
    elif buy_sig:
        status, icon, status_label = "buy", "★", "可買"
    elif broke:
        status, icon, status_label = "wait", "☆", "等止穩"
    else:
        status, icon, status_label = "wait", "☆", "等買點"

    # pills：市場短標 + 籌碼／興櫃警示（可多顆）
    short_ind = _short_industry(sid, industry, emerging)
    pills: List[Tuple[str, str]] = []
    if emerging:
        pills.append(("", f"興櫃・{short_ind}"))
        pills.append(
            (
                "pill-warn",
                "興櫃無法人・60日量小" if (qty60 is None or qty60 < 400) else "興櫃無法人",
            )
        )
    else:
        mkt_lab = "上市" if market.upper() in ("TW", "TSE", "") else (market or "上市")
        pills.append(("", mkt_lab))
        if short_ind and short_ind != "—":
            pills.append(("", short_ind))
        pills.extend(_chip_pills(chip_f, chip_t))

    fwd = None
    if eps_y is not None and eps_n is not None:
        fwd = calc_forward_12m_eps(eps_y, eps_n, ref)
    elif eps_n is not None:
        fwd = eps_n
    elif eps_y is not None:
        fwd = eps_y
    pe_fwd = (close / fwd) if (close and fwd and fwd > 0) else None
    pe_year_now = (close / eps_y) if (close and eps_y and eps_y > 0) else None
    fair_lo = pe_n if pe_n is not None else pe_y
    fair_hi = pe_y if pe_y is not None else pe_n
    if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
        fair_lo, fair_hi = fair_hi, fair_lo
    pe_min, pe_mid, pe_max, pe_dot = _pe_scale(pe_fwd, fair_lo, fair_hi)
    if pe_fwd is not None and fair_lo is not None and fair_hi is not None:
        pe_note = "偏低" if pe_fwd < fair_lo else ("偏貴" if pe_fwd > fair_hi else "合理帶")
    elif pe_fwd is not None:
        pe_note = "滾動"
    else:
        pe_note = ""
    if pe_year_now is not None and pe_year_now > 40:
        pe_note = f"今年{_fmt_num(pe_year_now,1)}x偏高"
    if pe_fwd is None:
        pe_line = "—"
    elif pe_note:
        pe_line = f"{_fmt_num(pe_fwd, 1)}倍 ({pe_note})"
    else:
        pe_line = f"{_fmt_num(pe_fwd, 1)}倍"

    eps_pct = int(round(eps_e / eps_y * 100)) if (eps_e and eps_y and eps_y > 0) else 0
    month_lab = f"{int(rev_ym[4:6])}月" if rev_ym and len(rev_ym) == 6 else ""
    if rev_yi is not None and thr is not None and thr > 0:
        rev_pct = int(round(rev_yi / thr * 100))
        # 壓縮空白，避免一行被截斷
        # 對齊 mock 一行：月營收 / 門檻億 (％)；興櫃不加「年底」以免裁％
        thr_s = _fmt_yi(thr) if thr < 100 else _fmt_num(thr, 0)
        if emerging:
            rev_line = f"{month_lab} {_fmt_yi(rev_yi)} / {thr_s}億 ({rev_pct}%)"
        else:
            rev_line = f"{month_lab} {_fmt_yi(rev_yi)} / 需{thr_s}億 ({rev_pct}%)"
    elif rev_yi is not None:
        rev_pct = 0
        rev_line = f"{month_lab} {_fmt_yi(rev_yi)}億"
    else:
        rev_pct = 0
        rev_line = "—"

    sr_text = (
        f"▲破撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
        if broke
        else f"撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
    )

    # 正常＝較高目標、保守＝較低（對齊 mock）
    tgt_vals = [v for v in (tgt, fair) if v is not None]
    if len(tgt_vals) >= 2:
        tgt_hi, tgt_lo = max(tgt_vals), min(tgt_vals)
    elif len(tgt_vals) == 1:
        tgt_hi = tgt_lo = tgt_vals[0]
    else:
        tgt_hi = tgt_lo = None

    if emerging:
        mid_title = "興櫃防線與流動性警示"
        marks = []
        if placement is not None:
            marks.append({"label": "現增暫定", "value": placement, "kind": ""})
        if close is not None:
            marks.append({"label": "現價", "value": close, "kind": "broke" if broke else "now"})
        if support is not None:
            marks.append(
                {"label": "前波平台", "value": support, "kind": "broke" if broke else ""}
            )
        if resist is not None:
            marks.append({"label": "前高壓", "value": resist, "kind": "up"})
        elif high60 is not None:
            marks.append({"label": "前高壓", "value": high60, "kind": "up"})
        if mom_pct is None:
            mom_s, mom_tone = "—", ""
        else:
            mom_tag = "強" if mom_pct >= 10 else ("緩" if mom_pct >= 0 else "減")
            mom_s = f"{mom_pct:+.1f}%{mom_tag}"
            mom_tone = "up" if mom_pct >= 10 else ("dn" if mom_pct < 0 else "warn")
        shares_s = f"{place_shares:.0f}萬股" if place_shares is not None else "—"
        gm_lab = f"Q{season_used or 3}毛利"
        stat4 = [
            ("現增股數", shares_s, "cold" if place_shares is not None else ""),
            (gm_lab, f"{gm:.1f}%" if gm is not None else "—", "good" if (gm or 0) >= 40 else ""),
            (f"{month_lab or '近月'}MoM", mom_s, mom_tone),
            ("⚠️ 價差大", "難出脫", "warn"),
        ]
        bl_k = "目標價與現增防線"
        if placement is None and dilute_yi is None:
            bl_bottom = '<div class="sub amber">現增暫定 —｜稀釋股本 —</div>'
        else:
            place_s = f"{_fmt_price(placement)}元" if placement is not None else "—"
            dilute_s = f"{_fmt_yi(dilute_yi)}億" if dilute_yi is not None else "—"
            bl_bottom = (
                f'<div class="sub amber">現增暫定 {html.escape(place_s)}｜'
                f"稀釋股本 {html.escape(dilute_s)}</div>"
            )
        foot = "★可買 ☆等止穩 ⚠️興櫃量小｜興櫃不適用法人與融資指標｜估值≠買訊"
    else:
        mid_title = "股價位置與防線（還原權息）"
        marks = []
        if close is not None:
            marks.append({"label": "現價", "value": close, "kind": "now"})
        if half_low is not None:
            marks.append({"label": "半年低", "value": half_low, "kind": "dn"})
        if support is not None:
            marks.append(
                {"label": "大量撐", "value": support, "kind": "broke" if broke else ""}
            )
        if resist is not None:
            marks.append({"label": "大量壓", "value": resist, "kind": "up"})
        if high60 is not None:
            marks.append({"label": "60日高", "value": high60, "kind": ""})
        pull = (
            (close - high60) / high60 * 100.0
            if close is not None and high60 not in (None, 0)
            else None
        )
        # 月線＝20 日均
        bias = (
            (close - ma20) / ma20 * 100.0
            if close is not None and ma20 not in (None, 0)
            else None
        )
        temp = "—"
        temp_tone = ""
        if close is not None and half_low is not None and high60 is not None and high60 > half_low:
            deg = (close - half_low) / (high60 - half_low) * 100
            if deg < 15:
                temp_tag, temp_tone = "極冷", "cold"
            elif deg < 35:
                temp_tag, temp_tone = "偏冷", "cold"
            elif deg <= 65:
                temp_tag = "中性"
            elif deg <= 85:
                temp_tag, temp_tone = "偏熱", "hot"
            else:
                temp_tag, temp_tone = "過熱", "hot"
            temp = f"{deg:.0f}°C（{temp_tag}）"
        # 官方殖利率（daily_valuation）；沒有就標無底，不准假造
        dy = None
        try:
            con_dy = sqlite3.connect(db_path)
            try:
                row_dy = con_dy.execute(
                    """
                    SELECT dividend_yield FROM daily_valuation
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                      AND dividend_yield IS NOT NULL
                    ORDER BY date DESC LIMIT 1
                    """,
                    (sid, day),
                ).fetchone()
                if row_dy:
                    dy = _finite(row_dy[0])
            finally:
                con_dy.close()
        except Exception:
            dy = None
        if dy is None:
            yield_s, yield_tone = "—（無底）", ""
        elif dy >= 4.0:
            yield_s, yield_tone = f"{dy:.1f}%（息撐）", "warn"
        else:
            yield_s, yield_tone = f"{dy:.1f}%（無底）", ""

        def _signed_tone(v: Optional[float]) -> str:
            if v is None or abs(v) < 0.05:
                return ""
            return "up" if v > 0 else "dn"

        stat4 = [
            ("60日回檔", f"{pull:+.1f}%" if pull is not None else "—", _signed_tone(pull)),
            ("月線乖離", f"{bias:+.1f}%" if bias is not None else "—", _signed_tone(bias)),
            ("殖利率", yield_s, yield_tone),
            ("溫度計", temp, temp_tone),
        ]
        bl_k = "目標價（正常／保守）＋近5日"
        bl_bottom = (
            f'<div class="chips">'
            f'<div class="chip-row"><span>外資</span><span class="sqs">{_sq(chip_f)}</span></div>'
            f'<div class="chip-row"><span>投信</span><span class="sqs">{_sq(chip_t)}</span></div>'
            f"</div>"
        )
        foot = "★可買 ☆等止穩 ⚠️興櫃量小｜5日籌碼(左→右)：🟥買 🟩賣｜估值≠買訊"

    # peers html（對齊 mock：名 + 倍數）
    peer_lines = []
    if emerging:
        self_pe = _fmt_num(pe_fwd, 1) if pe_fwd is not None else "—"
        peer_lines.append(
            f'<div class="peer mono">{html.escape(name)} {html.escape(self_pe)}x '
            f"<span>(興櫃)</span></div>"
        )
    else:
        self_pe = _fmt_num(pe_fwd, 1) if pe_fwd is not None else "—"
        peer_lines.append(
            f'<div class="peer mono">{html.escape(name)} {html.escape(self_pe)}x</div>'
        )
    for p in peers_raw[: 2 if emerging else 2]:
        if p.get("pe") is not None:
            ppe = f"{_fmt_num(p.get('pe'), 1)}x"
        elif p.get("close") is not None:
            ppe = f"收 {_fmt_price(p.get('close'))}"
        else:
            ppe = "—"
        peer_lines.append(
            f'<div class="peer mono">{html.escape(str(p["name"]))} '
            f"<span>{html.escape(ppe)}</span></div>"
        )
    if len(peer_lines) <= 1 and not peers_raw:
        peer_lines = ['<div class="peer">同族群對照待補</div>']

    ov_moat = _FLAGSHIP_FUND_OVERLAY.get(sid) or {}
    if not moat_html and ov_moat.get("moat_text") and ov_moat.get("risk_text"):
        moat_html = (
            f"{ov_moat['moat_text']}｜"
            f"<span class=\"risk\">風險：{ov_moat['risk_text']}</span>"
        )
    elif not moat_html:
        if emerging:
            gm_s = f"毛利 {gm:.1f}%" if gm is not None else "毛利待補"
            moat_html = (
                f"{html.escape(short_ind or industry or '本業')}<span>（{html.escape(gm_s)}）</span>"
                f"｜<span class=\"risk\">風險：興櫃量小折價、價差大</span>"
            )
        else:
            moat_html = (
                f"<b>{html.escape(short_ind or industry or '本業')}</b>"
                f"｜<span class=\"risk\">風險：景氣／客戶集中與估值波動</span>"
            )

    # EXTRA 條：上市＝10日籌碼＋融資；興櫃＝量能／現增／上櫃
    if emerging:
        extra_title = "興櫃量能與進度"
        qty_note = (
            "60日均量偏低"
            if (qty60 is None or float(qty60) < 400)
            else f"60日均量 {float(qty60):.0f}張"
        )
        shares_note = (
            f"上櫃現增 {place_shares:.0f}萬股"
            if place_shares is not None
            else "上櫃現增 —"
        )
        m_list = re.search(r"(\d{4})/(\d{1,2})", listing_note or "")
        list_note = (
            f"預計上櫃 {m_list.group(1)}/{int(m_list.group(2)):02d}" if m_list else "預計上櫃 —"
        )
        extra_val = f"{qty_note}｜{shares_note}｜{list_note}"
    else:
        extra_title = "融資・10日籌碼與關鍵日"
        f10 = t10 = None
        m5 = None
        try:
            con_x = sqlite3.connect(db_path)
            try:
                rows10 = con_x.execute(
                    """
                    SELECT foreign_net, trust_net FROM daily_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                      AND (foreign_net IS NOT NULL OR trust_net IS NOT NULL)
                      AND NOT (IFNULL(foreign_net,0)=0 AND IFNULL(trust_net,0)=0)
                    ORDER BY date DESC LIMIT 10
                    """,
                    (sid, day),
                ).fetchall()
                if rows10:
                    f10 = sum(float(r[0] or 0) for r in rows10)
                    t10 = sum(float(r[1] or 0) for r in rows10)
                mrows = con_x.execute(
                    """
                    SELECT margin_bal FROM daily_margin
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                      AND margin_bal IS NOT NULL
                    ORDER BY date DESC LIMIT 6
                    """,
                    (sid, day),
                ).fetchall()
                if len(mrows) >= 2:
                    newest = float(mrows[0][0])
                    older = float(mrows[min(5, len(mrows) - 1)][0])
                    m5 = newest - older
            finally:
                con_x.close()
        except Exception:
            pass

        def _lot(v: Optional[float]) -> str:
            if v is None:
                return "—"
            # daily_quotes foreign_net 多為張
            return f"{v:+,.0f}張"

        f_s = _lot(f10)
        t_s = _lot(t10)
        m_s = "融資 —" if m5 is None else f"融資 {_lot(m5)}"
        ev = _next_event_label(db_path, sid, day)
        # 法定期限是「最晚」日，不是公司公告日，標「前」
        ev = re.sub(r"^(年報|Q\d財報)期限 (\S+)$", lambda m: f"{'財報' if m.group(1) == '年報' else m.group(1)} {m.group(2)}前", ev)
        extra_val = f"外資10日 {f_s}｜投信 {t_s}｜{m_s}｜{ev}"

    tip = _strategy_tip(
        emerging=emerging,
        broke=broke,
        buy_sig=buy_sig,
        support=support,
        thr=thr,
        chip_f=chip_f,
        rev_ym=rev_ym,
    )

    chg_cls = "chg-up" if (pct is not None and pct >= 0) else "chg-dn"
    if pct is None:
        chg_txt = ""
    else:
        arrow = "▲" if pct >= 0 else "▼"
        chg_txt = f"{arrow}{abs(pct):.2f}%"

    season_note = ""
    qlab = f"Q{season_used}" if season_used else "最新"
    if eps_q is not None:
        season_note = f"{qlab}單季: {_fmt_num(eps_q, 2)}元"
        if (not emerging) and eps_q and eps_e and abs(float(eps_e)) > 0:
            if float(eps_q) >= 0.35 * abs(float(eps_e)):
                season_note += "（創高）"

    if emerging and season_used == 3:
        eps_k = "今年賺錢進度（已出Q3）"
    elif emerging and season_used:
        eps_k = f"今年賺錢進度（已出Q{season_used}）"
    else:
        eps_k = "今年賺錢進度"

    return {
        "emerging": emerging,
        "chip_f": chip_f,
        "chip_t": chip_t,
        "peers_raw": peers_raw,
        "icon": icon,
        "status_label": status_label,
        "stock_id": sid,
        "name": name,
        "close": close,
        "pct": pct,
        "chg_cls": chg_cls,
        "chg_txt": chg_txt,
        "pills": pills,
        "regime": regime,
        "eps_k": eps_k,
        "eps_e": eps_e,
        "eps_y": eps_y,
        "eps_pct": max(0, min(999, eps_pct)),
        "q4": _q4(rev_ym),
        "eps_q_line": season_note or "最新單季 —",
        "pe_fwd": pe_fwd,
        "pe_line": pe_line,
        "pe_note": pe_note,
        "pe_min": pe_min,
        "pe_mid": pe_mid,
        "pe_max": pe_max,
        "pe_dot": pe_dot,
        "pe_hot": bool(pe_fwd is not None and fair_hi is not None and pe_fwd > fair_hi),
        "bl_k": bl_k,
        "tgt_n": _fmt_price(tgt_hi),
        "tgt_c": _fmt_price(tgt_lo),
        "bl_bottom": bl_bottom,
        "rev_line": rev_line,
        "rev_pct": max(0, min(999, rev_pct)),
        "broke": broke,
        "sr_text": sr_text,
        "mid_title": mid_title,
        "marks": marks,
        "stat4": stat4,
        "peer_k": f"同族群對照（{peer_label}）",
        "peers_html": "".join(peer_lines),
        "moat_html": moat_html,
        "foot": foot,
        "bar_amber": emerging or broke,
        "extra_title": extra_title,
        "extra_val": extra_val,
        "tip": tip,
    }




def _render_5day_squares(flags: Sequence[str]) -> str:
    padded = (list(flags) + ["N"] * 5)[:5]
    cls_map = {"B": "sq-b", "S": "sq-s", "N": "sq-n"}
    return "".join(f'<span class="sq {cls_map.get(x, "sq-n")}"></span>' for x in padded)


def _build_ruler_markers(markers: Sequence[dict]) -> str:
    """自動防止相鄰標記重疊（最小間距 18%），確保數字不撞車。"""
    sorted_m = sorted(markers, key=lambda x: float(x["pct"]))
    merged: List[dict] = []
    for m in sorted_m:
        if merged and str(merged[-1]["val"]) == str(m["val"]):
            if merged[-1].get("is_now"):
                continue
            if m.get("is_now"):
                merged[-1] = dict(m)
            continue
        merged.append(dict(m))
    gap = 18.0 if len(merged) <= 5 else 88.0 / max(1, len(merged) - 1)
    placed: List[dict] = []
    for m in merged:
        pct = max(6.0, min(94.0, float(m["pct"])))
        if placed and pct - placed[-1]["pct"] < gap:
            pct = placed[-1]["pct"] + gap
        placed.append({**m, "pct": pct})
    for i in range(len(placed) - 1, -1, -1):
        cap = 94.0 if i == len(placed) - 1 else placed[i + 1]["pct"] - gap
        placed[i]["pct"] = min(placed[i]["pct"], cap)

    out = []
    for m in placed:
        dot_html = (
            '<div class="pm-now"></div>' if m.get("is_now") else '<div class="pm-tick"></div>'
        )
        top_cls = "cyan" if m.get("is_now") else ""
        out.append(
            f'<div class="pm" style="left:{m["pct"]}%;">'
            f'<span class="pm-top {top_cls}">{html.escape(str(m["label"]))}</span>'
            f"{dot_html}"
            f'<span class="pm-bot mono {top_cls}">{html.escape(str(m["val"]))}</span>'
            f"</div>"
        )
    return "\n".join(out)


def payload_to_card(p: Dict[str, Any]) -> Dict[str, Any]:
    """把 build_flagship_payload 輸出轉成 render_single_card 的 d。"""
    emerging = bool(p.get("emerging"))
    close = p.get("close")
    marks = list(p.get("marks") or [])
    vals = [float(m["value"]) for m in marks if _finite(m.get("value")) is not None]
    lo = min(vals) if vals else 0.0
    hi = max(vals) if vals else 1.0
    span = (hi - lo) or 1.0
    ruler = []
    for m in marks:
        v = _finite(m.get("value"))
        if v is None:
            continue
        kind = str(m.get("kind") or "")
        is_now = kind in ("now", "broke") and str(m.get("label")) == "現價"
        if not is_now and kind == "now":
            is_now = True
        ruler.append(
            {
                "label": str(m.get("label") or ""),
                "val": _fmt_price(v),
                "pct": (float(v) - lo) / span * 100.0,
                "is_now": is_now or (str(m.get("label")) == "現價"),
            }
        )

    # m4 from stat4 tuples (k, v, cls)
    m4 = []
    for row in (p.get("stat4") or [])[:4]:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            val = re.sub(r"（([^）]*)）$", r"(\1)", str(row[1]))
            tone = str(row[2]) if len(row) >= 3 and row[2] else ""
            m4.append((str(row[0]), val, _TONE_TINT.get(tone, "")))
    while len(m4) < 4:
        m4.append(("—", "—", ""))

    # peers for card（自己一律第一列；上市不准「收 xx」）
    peers = []
    pe_fwd = p.get("pe_fwd")
    if pe_fwd is not None:
        self_pe = f"{_fmt_num(pe_fwd, 1)}x" + (" (興櫃)" if emerging else "")
    else:
        self_pe = "— (興櫃)" if emerging else "—"
    peers.append({"name": str(p.get("name") or ""), "val": self_pe})
    for raw in p.get("peers_raw") or []:
        if raw.get("pe") is not None:
            val = f"{_fmt_num(raw.get('pe'), 1)}x"
        elif emerging and raw.get("close") is not None:
            val = f"收 {_fmt_price(raw.get('close'))}"
        else:
            continue
        peers.append({"name": str(raw.get("name") or ""), "val": val})
    if not peers:
        pe_line = str(p.get("pe_line") or "—")
        peers = [{"name": str(p.get("name") or ""), "val": pe_line.replace("倍", "x")}]

    # flow pill from chips / emerging
    flow_pill = "興櫃量小" if emerging else "籌碼中性"
    for cls, txt in p.get("pills") or []:
        t = str(txt)
        if "投信" in t or "外資" in t or "興櫃" in t:
            flow_pill = t
            break

    # market_sector from pills / peer
    market_sector = str(p.get("peer_k") or "").replace("同族群對照（", "").replace("）", "")
    if emerging:
        market_sector = f"興櫃・{market_sector}" if market_sector else "興櫃"
    else:
        # prefer short industry from pills
        bits = [str(t) for _, t in (p.get("pills") or []) if t and "興櫃" not in str(t) and "投信" not in str(t) and "外資" not in str(t)]
        if bits:
            market_sector = "・".join(bits[:2])

    # rev split
    rev_line = str(p.get("rev_line") or "—")
    rev_now, rev_gate = rev_line, "—"
    if " / " in rev_line:
        left, right = rev_line.split(" / ", 1)
        rev_now = left.strip()
        # strip (pct%)
        if "(" in right:
            rev_gate = right.split("(")[0].strip()
        else:
            rev_gate = right.strip()
        rev_gate = rev_gate.lstrip("需").strip()

    # moat / risk
    moat_html = str(p.get("moat_html") or "")
    moat_text, risk_text = moat_html, "—"
    if "風險" in moat_html:
        # strip tags roughly
        plain = re.sub(r"<[^>]+>", "", moat_html)
        parts = re.split(r"風險[：:]", plain, maxsplit=1)
        moat_text = parts[0].strip("｜| ")
        risk_text = parts[1].strip() if len(parts) > 1 else "—"
    else:
        moat_text = re.sub(r"<[^>]+>", "", moat_html).strip() or "—"

    pe_fwd = p.get("pe_fwd")
    pe_note = str(p.get("pe_note") or "")
    if pe_fwd is None:
        pe_fwd_s = "—"
    else:
        pe_fwd_s = _fmt_num(pe_fwd, 1)

    # foreign/trust 5d from bl_bottom squares is awkward; store on payload if available
    foreign_5d = list(p.get("chip_f") or ["N"] * 5)
    trust_5d = list(p.get("chip_t") or ["N"] * 5)

    emerging_note = "現增暫定 —｜稀釋股本 —"
    bl_bottom = str(p.get("bl_bottom") or "")
    if emerging:
        plain = re.sub(r"<[^>]+>", "", bl_bottom)
        if plain:
            emerging_note = plain

    status = "risk" if emerging else ("wait" if p.get("broke") else "buy")
    # icon already on payload
    icon = str(p.get("icon") or ("⚠️" if emerging else ("☆" if p.get("broke") else "★")))

    pct = p.get("pct")
    if pct is None:
        chg = ""
        is_up = False
    else:
        arrow = "▲" if float(pct) >= 0 else "▼"
        chg = f"{arrow} {abs(float(pct)):.2f}%"
        is_up = float(pct) >= 0

    price = f"{float(close):,.2f}" if close is not None else "—"

    # ensure target_norm >= target_cons numerically when both parse
    tgt_n = str(p.get("tgt_n") or "—")
    tgt_c = str(p.get("tgt_c") or "—")

    # Q4 / latest quarter
    q4 = str(p.get("q4") or "Q4進度 —")
    eps_q = str(p.get("eps_q_line") or "—")
    # eps_q_line may be "Q3單季: 40.47元（創高）" — card wants just the number part after label
    eps_latest = eps_q
    if ":" in eps_q:
        eps_latest = eps_q.split(":", 1)[1].strip()
    # 格寬只夠一行數字，「創高」標記不上卡
    eps_latest = eps_latest.replace("（創高）", "")
    # 模板後面固定接「｜最新單季 xx元」，Q4 前綴省掉才放得下一行
    q4 = q4.replace("Q4: ", "").replace("・", " ")

    # peer_chain short
    peer_chain = str(p.get("peer_k") or "")
    if "（" in peer_chain and peer_chain.endswith("）"):
        peer_chain = peer_chain.split("（", 1)[1][:-1]
    elif "(" in peer_chain and peer_chain.endswith(")"):
        peer_chain = peer_chain.split("(", 1)[1][:-1]

    return {
        "status": status,
        "icon": icon,
        "status_label": str(p.get("status_label") or ""),
        "ticker": str(p.get("stock_id") or ""),
        "name": str(p.get("name") or ""),
        "market_sector": market_sector,
        "price": price,
        "change_pct": chg,
        "is_up": is_up,
        "flow_pill": flow_pill,
        "regime_text": str((p.get("regime") or {}).get("text") or ""),
        "regime_right": str((p.get("regime") or {}).get("right") or ""),
        "eps_k": str(p.get("eps_k") or "今年賺錢進度"),
        "eps_ytd": _fmt_num(p.get("eps_e"), 2 if (_finite(p.get("eps_e")) or 99) < 10 else 1),
        # 百元以上估 EPS 用整數，避免「已賺…／估… (xx%)」一行被 ellipsis 吃掉％
        "eps_est_yr": _fmt_num(
            p.get("eps_y"),
            0 if (_finite(p.get("eps_y")) or 0) >= 100 else 1,
        ),
        "eps_pct": int(p.get("eps_pct") or 0),
        "q4_progress": q4,
        "eps_latest_q": eps_latest,
        "pe_fwd12m": pe_fwd_s,
        "pe_note": pe_note or "—",
        "pe_dot_pct": int(round(float(p.get("pe_dot") or 50))),
        "pe_min": str(p.get("pe_min") or "—"),
        "pe_mid": str(p.get("pe_mid") or "—"),
        "pe_max": str(p.get("pe_max") or "—"),
        "target_norm": tgt_n,
        "target_cons": tgt_c,
        "foreign_5d": foreign_5d,
        "trust_5d": trust_5d,
        "is_emerging": emerging,
        "emerging_note": emerging_note,
        "rev_now": rev_now,
        "rev_gate": rev_gate,
        "rev_pct": int(p.get("rev_pct") or 0),
        "support_ok": not bool(p.get("broke")),
        "support_text": str(p.get("sr_text") or ""),
        "ruler_markers": ruler,
        "m4": m4,
        "peer_chain": peer_chain or "—",
        "peers": peers[:3],
        "moat_text": moat_text,
        "risk_text": risk_text,
        "extra_title": str(
            p.get("extra_title")
            or ("興櫃量能與進度" if emerging else "融資與10日籌碼・關鍵日")
        ),
        "extra_val": str(p.get("extra_val") or "—"),
        "action_callout": str(p.get("tip") or "先看高低卡買點再動"),
        "m4_tints": [m[2] for m in m4[:4]],
    }


def fill_flagship_html(d: Dict[str, Any]) -> str:
    """只填 HTML，不出圖（CI／單元測試用）。"""
    is_em = bool(d.get("is_emerging", False))
    if is_em:
        bl_title = "目標價與現增防線"
        bl_bottom = (
            f'<div class="cell-sub amber">{html.escape(d.get("emerging_note", "現增與流動性待補"))}</div>'
        )
        footer = "★可買 ☆等止穩 ⚠️興櫃量小｜興櫃不適用法人與融資指標｜估值≠買訊"
        ruler_title = "興櫃防線與流動性警示"
    else:
        bl_title = "目標價 (正常／保守) ＋近5日"
        f_sq = _render_5day_squares(d.get("foreign_5d", ["N"] * 5))
        t_sq = _render_5day_squares(d.get("trust_5d", ["N"] * 5))
        bl_bottom = (
            f'<div class="flow-blocks-row">'
            f'<span>外資</span><span class="sq-group">{f_sq}</span>'
            f'<span>投信</span><span class="sq-group">{t_sq}</span>'
            f"</div>"
        )
        footer = "★可買 ☆等止穩 ⚠️興櫃量小｜5日籌碼(左→右)：🟥買 🟩賣｜估值≠買訊"
        ruler_title = "股價位置與防線 (還原權息)"

    peers_html = "\n".join(
        f'<div class="peer-row"><span>{html.escape(p["name"])}</span>'
        f'<span class="mono">{html.escape(p["val"])}</span></div>'
        for p in (d.get("peers") or [])[:3]
    )
    tints = (list(d.get("m4_tints") or []) + [""] * 4)[:4]

    rep = {
        "CARD_STATUS_CLS": {"buy": "is-buy", "wait": "is-wait", "risk": "is-risk"}.get(
            d.get("status", "wait"), "is-wait"
        ),
        "ICON": d["icon"],
        "STATUS_LABEL": d["status_label"],
        "TICKER": d["ticker"],
        "NAME": d["name"],
        "MARKET_SECTOR": d["market_sector"],
        "PRICE": d["price"],
        "CHANGE_PCT": d["change_pct"],
        "PRICE_CLASS": "up" if d.get("is_up") else "down",
        "FLOW_PILL": d["flow_pill"],
        "REGIME_TEXT": d["regime_text"],
        "REGIME_RIGHT": d["regime_right"],
        "EPS_K": d.get("eps_k") or "今年賺錢進度",
        "EPS_YTD": d["eps_ytd"],
        "EPS_EST_YR": d["eps_est_yr"],
        "EPS_PCT": str(int(d["eps_pct"])),
        "EPS_PCT_CLAMP": str(min(100, int(d["eps_pct"]))),
        "BAR_CLS": "prog-fill-amber" if is_em else "",
        "Q4_PROGRESS": d["q4_progress"],
        "EPS_LATEST_Q": d["eps_latest_q"],
        "PE_FWD12M": d["pe_fwd12m"],
        "PE_NOTE": d["pe_note"],
        "PE_DOT_PCT": str(max(5, min(95, int(d["pe_dot_pct"])))),
        "PE_MIN": d["pe_min"],
        "PE_MID": d["pe_mid"],
        "PE_MAX": d["pe_max"],
        "BL_TITLE": bl_title,
        "BL_BOTTOM_HTML": bl_bottom,
        "TARGET_NORM": d["target_norm"],
        "TARGET_CONS": d["target_cons"],
        "REV_NOW": d["rev_now"],
        "REV_GATE": d["rev_gate"],
        "REV_PCT": str(int(d["rev_pct"])),
        "REV_PCT_CLAMP": str(min(100, int(d["rev_pct"]))),
        "SUPPORT_CLASS": "down" if d.get("support_ok") else "amber",
        "SUPPORT_TEXT": d["support_text"],
        "RULER_TITLE": ruler_title,
        "RULER_MARKERS_HTML": _build_ruler_markers(d.get("ruler_markers") or []),
        "M1_K": d["m4"][0][0],
        "M1_V": d["m4"][0][1],
        "M2_K": d["m4"][1][0],
        "M2_V": d["m4"][1][1],
        "M3_K": d["m4"][2][0],
        "M3_V": d["m4"][2][1],
        "M4_K": d["m4"][3][0],
        "M4_V": d["m4"][3][1],
        "M1_TINT": tints[0],
        "M2_TINT": tints[1],
        "M3_TINT": tints[2],
        "M4_TINT": tints[3],
        "CALLOUT_CLS": "is-em" if is_em else "",
        "ACTION_CALLOUT": html.escape(
            str(d.get("action_callout") or ("興櫃量小價差大，緊盯月營收門檻" if is_em else "等待站回大量支撐或外資賣壓縮手"))
        ),
        "PEER_CHAIN": d["peer_chain"],
        "PEERS_HTML": peers_html,
        "MOAT_TEXT": d["moat_text"],
        "RISK_TEXT": d["risk_text"],
        "EXTRA_STRIP_TITLE": d.get("extra_title")
        or ("興櫃量能與進度" if is_em else "融資與10日籌碼・關鍵日"),
        "EXTRA_STRIP_VAL": d.get("extra_val") or "—",
        "FOOTER_TEXT": footer,
    }
    page_html = HTML_TEMPLATE
    for k, v in rep.items():
        page_html = page_html.replace("{{" + k + "}}", str(v))
    return page_html


def render_flagship_html(p: Dict[str, Any]) -> str:
    """單元測試／預覽：payload → HTML。"""
    return fill_flagship_html(payload_to_card(p))


# 模板字級不動；只有真的溢出（數字／％會被 ellipsis 吃掉）的那一行才逐 0.5px 縮，下限 9.5px
_AUTOFIT_JS = """async () => {
  await document.fonts.ready;
  // 籌碼列：一行放不下時改兩列「外資 ■■■■■／投信 ■■■■■」，標籤不跟方塊拆開
  for (const row of document.querySelectorAll('.flow-blocks-row')) {
    for (const s of row.children) s.style.whiteSpace = 'nowrap';
    if (row.scrollWidth > row.clientWidth + 0.5 || row.offsetHeight > 20) {
      row.style.display = 'grid';
      row.style.gridTemplateColumns = 'auto 1fr';
      row.style.rowGap = '3px';
    }
  }
  // 2×2 格的副行是單行資訊，不准把「元」「億」擠成孤字行
  for (const el of document.querySelectorAll('.d3-grid .cell-sub')) {
    el.style.whiteSpace = 'nowrap';
  }
  for (const el of document.querySelectorAll('.stock-title, .stock-sub, .cell-v, .cell-sub, .m4-v, .callout-bar')) {
    let fs = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > el.clientWidth + 0.5 && fs > 9.5) {
      fs -= 0.5;
      el.style.fontSize = fs + 'px';
    }
  }
}"""


def render_single_card(d: Dict[str, Any], output_png: str) -> str:
    page_html = fill_flagship_html(d)
    out = str(output_png)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": VIEW_W, "height": VIEW_H},
            device_scale_factor=DPR,
        )
        page.set_content(page_html, wait_until="networkidle")
        page.evaluate(_AUTOFIT_JS)
        page.screenshot(path=out, full_page=False)
        browser.close()
    return out


def render_flagship_png(
    stock_id: str,
    save_path: str,
    *,
    db_path: Optional[str] = None,
    as_of: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    path = db_path or os.environ.get("WAYNE_DB_PATH") or "data/wayne_market.db"
    data = payload or build_flagship_payload(path, stock_id, as_of=as_of)
    return render_single_card(payload_to_card(data), save_path)


def main() -> None:
    db = os.environ.get("WAYNE_DB_PATH") or "data/wayne_market.db"
    out = Path("/opt/cursor/artifacts/lookup-flagship")
    out.mkdir(parents=True, exist_ok=True)
    for sid in ("2383", "3595"):
        path = out / f"flagship_{sid}.png"
        render_flagship_png(sid, str(path), db_path=db, as_of="20261118")
        print(path, path.stat().st_size)


if __name__ == "__main__":
    main()
