# -*- coding: utf-8 -*-
# ==============================================================================
# 【給 AI 開發者的強制施工規範（必讀）】
# 1. 嚴禁使用 Pillow (PIL) 或 matplotlib 畫圖！
# 2. 必須直接使用本檔內建的 HTML_TEMPLATE + Playwright (viewport 430x932, DPR=3)
#    截圖輸出 1290x2796 滿版 PNG 後，透過 Telegram sendPhoto 發送。
# 3. 只需將即時股價、EPS、營收、外資投信近 5 日買賣超與台幣匯率填入
#    render_screener_pages()，切勿自行改寫或破壞 HTML/CSS 排版結構。
# ==============================================================================
"""
WayneBot「低估名單」Version D3 終極整合檔（純實戰訊號版）
特性：
- 玻璃擬態深色卡片 + 白話標籤（無艱澀縮寫）
- 內建未來 12 個月滾動 EPS / 本益比實數刻度尺（跨年不跳號）
- 內建動態匯率與外資資金水位橫幅
- 左下角精準渲染「外資 / 投信近 5 日買賣方塊」（固定 5 格，左舊→右新：紅買、綠賣）
- 興櫃標的自動切換為「現增暫定價＋流動性警示」
- 每頁最多 4 檔，iPhone 18 Pro Max @3x (1290x2796) 滿版含 Telegram 上下安全邊距

安裝需求：
    pip install playwright requests
    playwright install chromium
"""
from __future__ import annotations

import html
import math
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests
from playwright.sync_api import sync_playwright

MAX_PER_PAGE = 4
VIEW_W = 430
VIEW_H = 932
DPR = 3
OUT_W = VIEW_W * DPR  # 1290
OUT_H = VIEW_H * DPR  # 2796

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=JetBrains+Mono:wght@500;700&display=swap');
  :root {
    --bg-canvas: #0B1120;
    --bg-card: linear-gradient(180deg, rgba(19, 28, 49, 0.96) 0%, rgba(15, 23, 42, 0.98) 100%);
    --bg-cell: #151E32;
    --border-subtle: #1E293B;
    --text-primary: #F8FAFC;
    --text-secondary: #94A3B8;
    --text-muted: #64748B;
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
  .phone-frame {
    width: 430px; height: 932px; background: var(--bg-canvas);
    padding: 48px 14px 60px 14px; /* 上 144px / 下 180px Telegram 安全邊距 */
    display: flex; flex-direction: column; gap: 6px; overflow: hidden;
  }
  .mono { font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-variant-numeric: tabular-nums; }
  .page-header {
    display: flex; align-items: center; padding: 2px 2px 2px 2px; flex-shrink: 0;
  }
  .page-title {
    font-size: 14.5px; font-weight: 900; color: var(--text-primary); letter-spacing: -0.2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 100%;
  }
  .regime-banner {
    font-size: 10.5px; font-weight: 700; padding: 5px 10px; border-radius: 8px;
    display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; gap: 8px;
  }
  .regime-normal { background: rgba(52, 211, 153, 0.12); border: 1px solid rgba(52, 211, 153, 0.35); color: #A7F3D0; }
  .regime-fx { background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.42); color: #FDE68A; }
  .regime-bear { background: rgba(248, 113, 113, 0.12); border: 1px solid rgba(248, 113, 113, 0.42); color: #FECACA; }

  .cards-stack {
    display: flex; flex-direction: column; gap: 6px; flex: 1 1 0; min-height: 0; overflow: hidden;
  }
  .stock-card {
    background: var(--bg-card); border: 1px solid var(--border-subtle);
    border-radius: 13px; padding: 7px 9px; display: flex; flex-direction: column; gap: 5px;
    flex: 1 1 0; min-height: 0; overflow: hidden;
  }
  .stock-card.status-buy { border-color: rgba(52, 211, 153, 0.5); box-shadow: 0 0 12px rgba(52, 211, 153, 0.08); }
  .stock-card.status-wait { border-color: rgba(251, 191, 36, 0.45); box-shadow: 0 0 12px rgba(251, 191, 36, 0.06); }
  .stock-card.status-risk { border-color: rgba(167, 139, 250, 0.5); box-shadow: 0 0 12px rgba(167, 139, 250, 0.08); }

  .card-top {
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
    min-width: 0; flex-shrink: 0;
  }
  .card-head-text {
    font-size: 12px; font-weight: 800; color: var(--text-primary);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    min-width: 0; flex: 1 1 auto;
  }
  .flow-pill {
    font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 999px;
    white-space: nowrap; flex: 0 0 auto; max-width: 42%; overflow: hidden; text-overflow: ellipsis;
  }
  .flow-buy { background: rgba(248, 113, 113, 0.16); color: var(--tw-up); border: 1px solid rgba(248, 113, 113, 0.3); }
  .flow-sell { background: rgba(52, 211, 153, 0.15); color: var(--tw-down); border: 1px solid rgba(52, 211, 153, 0.3); }
  .flow-warn { background: rgba(167, 139, 250, 0.18); color: var(--purple); border: 1px solid rgba(167, 139, 250, 0.35); }

  .d3-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 5px; flex: 1 1 0; min-height: 0;
  }
  .d3-cell {
    background: #151E32; border: 1px solid #1E293B; border-radius: 8px;
    padding: 5px 7px; display: flex; flex-direction: column; justify-content: space-between; gap: 2px;
    min-height: 0; overflow: hidden;
  }
  .cell-k { font-size: 9.5px; color: var(--text-secondary); font-weight: 700; }
  .cell-v { font-size: 11px; font-weight: 700; color: var(--text-primary); line-height: 1.25; }
  .cell-sub { font-size: 9.5px; color: var(--text-muted); }

  .up { color: var(--tw-up); } .down { color: var(--tw-down); }
  .cyan { color: var(--cyan); } .amber { color: var(--amber); }

  /* 進度條 */
  .prog-track { height: 4px; background: #0B1120; border: 1px solid #334155; border-radius: 999px; overflow: hidden; }
  .prog-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #10B981, #38BDF8); }
  .prog-fill-amber { background: linear-gradient(90deg, #F59E0B, #FBBF24); }

  /* 本益比實數刻度尺：軌道＋15x/20x/25x，圓點限 5%～95% */
  .ruler-wrap { display: flex; flex-direction: column; gap: 2px; margin-top: 1px; }
  .ruler-track {
    position: relative; height: 6px; background: #0B1120;
    border: 1px solid #64748B; border-radius: 999px; margin: 3px 6px 0 6px;
  }
  .ruler-dot {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 9px; height: 9px; border-radius: 50%; background: #38BDF8;
    border: 1.5px solid #FFF; box-shadow: 0 0 6px rgba(56, 189, 248, 0.85);
  }
  .ruler-labels {
    display: flex; justify-content: space-between; font-size: 9px;
    color: var(--text-secondary); font-weight: 700; padding: 0 4px;
  }

  /* 精準 5 日籌碼紅綠方塊 */
  .flow-blocks-row { display: flex; align-items: center; gap: 5px; font-size: 9.5px; color: var(--text-secondary); flex-wrap: nowrap; }
  .sq-group { display: inline-flex; gap: 2.5px; align-items: center; }
  .sq { width: 7px; height: 7px; border-radius: 1.5px; display: inline-block; flex-shrink: 0; }
  .sq-b { background: #EF4444; } /* 買超: 紅 */
  .sq-s { background: #10B981; } /* 賣超: 綠 */
  .sq-n { background: #475569; } /* 持平: 灰 */

  .footer-legend {
    text-align: center; font-size: 9px; color: var(--text-muted); padding-top: 1px; flex-shrink: 0;
  }
</style>
</head>
<body>
  <div class="phone-frame">
    <div class="page-header">
      <div class="page-title">真成長低估掃描｜{{DATE_STR}}・第 {{PAGE_NO}}/{{TOTAL_PAGES}} 頁</div>
    </div>
    <div class="regime-banner {{REGIME_CLASS}}">
      <span>{{REGIME_TEXT}}</span>
      <span class="mono">{{FX_TEXT}}</span>
    </div>
    <div class="cards-stack">{{STOCK_CARDS_HTML}}</div>
    <div class="footer-legend">★可買 ☆等止穩 ⚠️興櫃量小｜5日籌碼(左→右)：🟥買 🟩賣｜估值≠買訊</div>
  </div>
</body>
</html>
"""


def calc_forward_12m_eps(
    eps_this_year: float, eps_next_year: float, ref_date: date | None = None
) -> float:
    """未來 12 個月平滑滾動 EPS：隨月份推進調整權重，跨年不跳號。"""
    d = ref_date or date.today()
    months_left = max(0, 12 - d.month + 1)
    w_this = months_left / 12.0
    return round(eps_this_year * w_this + eps_next_year * (1.0 - w_this), 2)


def detect_market_regime(
    usd_twd: float, foreign_sell_days: int, market_above_ma20: bool
) -> dict:
    """依台幣匯率與外資/大盤水位動態切換模式。"""
    if usd_twd >= 32.8 and foreign_sell_days >= 2 and not market_above_ma20:
        return {
            "class": "regime-fx",
            "text": "⚠️ 台幣急貶外資提款盤・非基本面轉壞",
            "fx_text": f"USD/TWD {usd_twd:.2f}",
        }
    if not market_above_ma20 and foreign_sell_days >= 3:
        return {
            "class": "regime-bear",
            "text": "🔴 系統性修正盤・嚴守站回支撐再買",
            "fx_text": f"USD/TWD {usd_twd:.2f}",
        }
    return {
        "class": "regime-normal",
        "text": "🟢 資金常態盤・依區間與黃金買點操作",
        "fx_text": f"USD/TWD {usd_twd:.2f}",
    }


def _render_5day_squares(flags: list[str]) -> str:
    """精準產生 5 格籌碼燈號（'B'=紅買, 'S'=綠賣, 'N'=灰平），固定 5 格不會錯位。"""
    padded = (flags + ["N"] * 5)[:5]
    cls_map = {"B": "sq-b", "S": "sq-s", "N": "sq-n"}
    return "".join(f'<span class="sq {cls_map.get(x, "sq-n")}"></span>' for x in padded)


def _build_card_html(s: dict) -> str:
    status_cls = {"buy": "status-buy", "wait": "status-wait", "risk": "status-risk"}.get(
        s.get("status", "wait"), "status-wait"
    )
    flow_cls = {"buy": "flow-buy", "sell": "flow-sell", "warn": "flow-warn"}.get(
        s.get("flow_type", "buy"), "flow-buy"
    )
    support_cls = "down" if s.get("support_ok") else "amber"
    bar_cls = "prog-fill-amber" if s.get("status") == "risk" else ""

    if s.get("is_emerging"):
        bl_bottom = (
            f'<div class="cell-sub amber">'
            f'{html.escape(s.get("emerging_note", "興櫃量小注意流動性"))}</div>'
        )
        bl_title = "目標價（現增暫定價）"
    else:
        f_sq = _render_5day_squares(s.get("foreign_5d", ["N"] * 5))
        t_sq = _render_5day_squares(s.get("trust_5d", ["N"] * 5))
        bl_bottom = (
            f'<div class="flow-blocks-row">'
            f'<span>外資</span><span class="sq-group">{f_sq}</span>'
            f'<span>投信</span><span class="sq-group">{t_sq}</span>'
            f"</div>"
        )
        bl_title = "目標價（正常／保守）＋近5日"

    pe_left = max(8, min(92, int(round(float(s.get("pe_dot_pct") or 50)))))
    return f"""
    <div class="stock-card {status_cls}">
      <div class="card-top">
        <div class="card-head-text">{html.escape(s['icon'])} {html.escape(s['status_label'])}｜{html.escape(s['ticker'])} {html.escape(s['name'])}｜{html.escape(s['price'])}元｜毛利{html.escape(s['gm_q3'])}</div>
        <span class="flow-pill {flow_cls}">{html.escape(s['flow_pill'])}</span>
      </div>
      <div class="d3-grid">
        <div class="d3-cell">
          <div class="cell-k">今年賺錢進度</div>
          <div class="cell-v mono">已賺 {html.escape(s['eps_ytd'])} / 估 {html.escape(s['eps_est_yr'])} ({int(s['eps_pct'])}%)</div>
          <div class="prog-track"><div class="prog-fill {bar_cls}" style="width: {min(100, int(s['eps_pct']))}%;"></div></div>
          <div class="cell-sub">{html.escape(s['q4_progress'])}</div>
        </div>
        <div class="d3-cell">
          <div class="cell-k">未來 12 個月滾動本益比</div>
          <div class="cell-v mono cyan">{html.escape(s['pe_fwd12m'])}倍 <span class="cell-sub">({html.escape(s['pe_note'])})</span></div>
          <div class="ruler-wrap">
            <div class="ruler-track"><div class="ruler-dot" style="left: {pe_left}%;"></div></div>
            <div class="ruler-labels mono"><span>15x</span><span>20x</span><span>25x</span></div>
          </div>
        </div>
        <div class="d3-cell">
          <div class="cell-k">{bl_title}</div>
          <div class="cell-v mono">正常 {html.escape(s['target_norm'])}｜保守 {html.escape(s['target_cons'])}</div>
          {bl_bottom}
        </div>
        <div class="d3-cell">
          <div class="cell-k">營收達標進度＋撐壓</div>
          <div class="cell-v mono">{html.escape(s['rev_now'])} / 需 {html.escape(s['rev_gate'])} ({int(s['rev_pct'])}%)</div>
          <div class="prog-track"><div class="prog-fill {bar_cls}" style="width: {min(100, int(s['rev_pct']))}%;"></div></div>
          <div class="cell-sub mono"><span class="{support_cls}">{html.escape(s['support_text'])}</span></div>
        </div>
      </div>
    </div>
    """


def render_screener_pages(
    stocks: list[dict], date_str: str, regime: dict, out_dir: str = "."
) -> list[str]:
    out_paths = []
    total_pages = max(1, math.ceil(len(stocks) / MAX_PER_PAGE)) if stocks else 1

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": VIEW_W, "height": VIEW_H},
            device_scale_factor=DPR,
        )

        for page_idx in range(total_pages):
            chunk = stocks[page_idx * MAX_PER_PAGE : (page_idx + 1) * MAX_PER_PAGE]
            cards_html = "\n".join(_build_card_html(s) for s in chunk) if chunk else ""
            page_html = (
                HTML_TEMPLATE.replace("{{DATE_STR}}", date_str)
                .replace("{{PAGE_NO}}", str(page_idx + 1))
                .replace("{{TOTAL_PAGES}}", str(total_pages))
                .replace("{{REGIME_CLASS}}", regime["class"])
                .replace("{{REGIME_TEXT}}", regime["text"])
                .replace("{{FX_TEXT}}", regime["fx_text"])
                .replace("{{STOCK_CARDS_HTML}}", cards_html)
            )
            page.set_content(page_html, wait_until="networkidle")
            out_file = str(Path(out_dir) / f"screener_d3_p{page_idx + 1}.png")
            page.screenshot(path=out_file, full_page=False)
            out_paths.append(out_file)

        browser.close()
    return out_paths


def send_telegram_photo(
    bot_token: str, chat_id: str, png_path: str, caption: str = ""
) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    with open(png_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": f},
            timeout=20,
        )
    return resp.json()


# --- WayneBot 接線：把既有低估列填進上面模板欄位（不改 HTML/CSS）---


def playwright_available() -> bool:
    if os.environ.get("WAYNE_UV_HTML", "1").strip() in ("0", "false", "no"):
        return False
    try:
        from playwright.sync_api import sync_playwright as _sp  # noqa: F401

        return True
    except Exception:
        return False


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
    if digits == 0:
        return f"{x:.0f}"
    s = f"{x:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _fmt_price(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"{x:,.0f}" if abs(x - round(x)) < 1e-6 else f"{x:,.1f}"
    if abs(x - round(x)) < 1e-6 and abs(x) >= 100:
        return f"{x:.0f}"
    return _fmt_num(x, 1)


def _net_to_flag(v: float) -> str:
    if v > 0:
        return "B"
    if v < 0:
        return "S"
    return "N"


def _normalize_5d_flags(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)) and raw:
        out = []
        for x in raw[:5]:
            s = str(x or "N").upper()[:1]
            out.append(s if s in ("B", "S", "N") else "N")
        return (out + ["N"] * 5)[:5]
    return ["N"] * 5


def _as_of_date(as_of: Optional[str]) -> date:
    s = str(as_of or "").replace("-", "")[:8]
    if len(s) == 8 and s.isdigit():
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            pass
    return date.today()


def _date_str(as_of: Optional[str]) -> str:
    d = _as_of_date(as_of)
    return d.strftime("%m/%d")


def pick_row_to_screener_stock(row: Dict[str, Any], *, as_of: Optional[str] = None) -> dict:
    """把融合庫低估列填進模板欄位；不准改 HTML 結構。"""
    mark = str(row.get("mark") or "").lower()
    emerging = mark in ("emerging", "emerge") or bool(row.get("emerging"))
    broken = bool(row.get("tech_broken")) or (
        "破撐" in str(row.get("tech_status") or "") or "破撐" in str(row.get("reason") or "")
    )
    if emerging:
        status, icon, status_label = "risk", "⚠️", "興櫃量小"
    elif mark in ("star", "true", "★", "*") and not broken:
        status, icon, status_label = "buy", "★", "可買"
    else:
        status, icon, status_label = "wait", "☆", "等止穩"

    chip = str(row.get("chip_note") or "").strip()
    # 膠囊精簡：右邊單留籌碼，避免蓋住左側「毛利%」
    if emerging or "興櫃" in chip:
        flow_type, flow_pill = "warn", "興櫃無法人"
    elif "同賣" in chip:
        flow_type, flow_pill = "sell", "外投同賣"
    elif "投信" in chip and ("調節" in chip or "賣" in chip):
        flow_type, flow_pill = "sell", "投信護盤・外資賣"
    elif "同買" in chip:
        flow_type, flow_pill = "buy", "外投同買"
    elif "投信連買" in chip:
        flow_type, flow_pill = "buy", chip.replace("投信連買", "投信連買")[:10]
    elif "外資連買" in chip:
        flow_type, flow_pill = "buy", chip[:10]
    elif chip:
        flow_type, flow_pill = "buy", chip[:10]
    else:
        flow_type, flow_pill = "buy", "—"

    close = _finite(row.get("close"))
    eps_y = _finite(row.get("eps_2026"))
    eps_n = _finite(row.get("eps_2027"))
    eps_e = _finite(row.get("eps_earned"))
    ref_d = _as_of_date(as_of)
    fwd_eps = None
    if eps_y is not None and eps_n is not None:
        fwd_eps = calc_forward_12m_eps(eps_y, eps_n, ref_d)
    elif eps_n is not None:
        fwd_eps = eps_n
    elif eps_y is not None:
        fwd_eps = eps_y

    pe_fwd12 = None
    if close is not None and fwd_eps is not None and fwd_eps > 0:
        pe_fwd12 = close / fwd_eps

    # 固定軌道 15x～25x；圓點座標限 5%～95%
    pe_lo, pe_hi = 15.0, 25.0
    pe_dot = 50.0
    if pe_fwd12 is not None:
        pe_dot = (float(pe_fwd12) - pe_lo) / (pe_hi - pe_lo) * 100.0
        pe_dot = max(8.0, min(92.0, pe_dot))

    pe_year = _finite(row.get("pe_year"))
    pe_next = _finite(row.get("pe_next"))
    fair_lo = pe_next if pe_next is not None else pe_year
    fair_hi = pe_year if pe_year is not None else pe_next
    if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
        fair_lo, fair_hi = fair_hi, fair_lo
    if pe_fwd12 is not None and fair_lo is not None and fair_hi is not None:
        if pe_fwd12 < fair_lo:
            pe_note = "偏低"
        elif pe_fwd12 > fair_hi:
            pe_note = "偏貴"
        else:
            pe_note = "合理帶"
    elif pe_fwd12 is not None:
        if pe_fwd12 < 18:
            pe_note = "偏低"
        elif pe_fwd12 > 22:
            pe_note = "偏貴"
        else:
            pe_note = "合理帶"
    else:
        pe_note = "滾動"

    eps_pct = 0
    if eps_e is not None and eps_y is not None and eps_y > 0:
        eps_pct = max(0, min(999, int(round(eps_e / eps_y * 100.0))))

    thr = _finite(row.get("rev_threshold_yi"))
    oct_r = _finite(row.get("rev_oct_yi"))
    rev_pct = 0
    if thr is not None and thr > 0 and oct_r is not None:
        rev_pct = max(0, min(999, int(round(oct_r / thr * 100.0))))

    support = _finite(row.get("support"))
    resist = _finite(row.get("resistance"))
    support_ok = not broken
    if broken and support is not None:
        support_text = f"▲破撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
    else:
        support_text = f"撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"

    fair = _finite(row.get("fair_year"))
    tgt = _finite(row.get("target_next"))
    target_norm = _fmt_price(tgt if tgt is not None else fair)
    target_cons = _fmt_price(fair if fair is not None else tgt)

    gm = _finite(row.get("gross_margin"))
    gm_s = f"{gm:.1f}%" if gm is not None else "—"

    # Q4: 10月✓・11·12待補（依 as_of 月份）
    m = ref_d.month
    if m <= 9:
        q4 = "Q4: 10·11·12待補"
    elif m == 10:
        q4 = "Q4: 10月✓・11·12待補"
    elif m == 11:
        q4 = "Q4: 10月✓・11月✓・12待補"
    else:
        q4 = "Q4: 10·11·12月✓"

    emerging_note = "現增暫定價＋量小警示"
    tech = str(row.get("tech_status") or "").strip()
    if tech and "現增" not in tech:
        emerging_note = f"現增暫定價＋{tech}"[:28]
    elif tech:
        emerging_note = tech[:28]

    return {
        "status": status,
        "icon": icon,
        "status_label": status_label,
        "ticker": str(row.get("stock_id") or "—"),
        "name": str(row.get("name") or "").strip(),
        "price": _fmt_price(close),
        "gm_q3": gm_s,
        "flow_type": flow_type,
        "flow_pill": flow_pill,
        "eps_ytd": _fmt_num(eps_e, 2 if (eps_e is not None and abs(eps_e) < 10) else 1),
        "eps_est_yr": _fmt_num(eps_y, 1),
        "eps_pct": eps_pct,
        "q4_progress": q4,
        "pe_fwd12m": _fmt_num(pe_fwd12, 1),
        "pe_note": pe_note,
        "pe_dot_pct": pe_dot,
        "pe_min": "15x",
        "pe_mid": "20x",
        "pe_max": "25x",
        "target_norm": target_norm,
        "target_cons": target_cons,
        "foreign_5d": _normalize_5d_flags(row.get("foreign_5d")),
        "trust_5d": _normalize_5d_flags(row.get("trust_5d")),
        "is_emerging": emerging,
        "emerging_note": emerging_note,
        "rev_now": f"{_fmt_num(oct_r, 1)}億" if oct_r is not None else "—",
        "rev_gate": f"{_fmt_num(thr, 1)}億" if thr is not None else "—",
        "rev_pct": rev_pct,
        "support_ok": support_ok,
        "support_text": support_text,
    }


def resolve_regime(
    *,
    usd_twd: Optional[float] = None,
    foreign_sell_days: int = 0,
    market_above_ma20: bool = True,
    empty_note: Optional[str] = None,
) -> dict:
    fx = _finite(usd_twd)
    if fx is None:
        fx = 31.50
    regime = detect_market_regime(float(fx), int(foreign_sell_days or 0), bool(market_above_ma20))
    if empty_note:
        regime = dict(regime)
        regime["text"] = str(empty_note)[:48]
    return regime


def load_usd_twd_hint(db_path: Optional[str] = None) -> Optional[float]:
    """盡量讀庫內已有匯率；沒有就 None（不准假造）。"""
    path = db_path or os.environ.get("WAYNE_DB_PATH") or ""
    if not path or not os.path.isfile(path):
        return None
    try:
        import sqlite3

        con = sqlite3.connect(path)
        try:
            for sql in (
                "SELECT value FROM market_snapshots WHERE key IN ('usd_twd','USDTWD','USD/TWD') ORDER BY as_of DESC LIMIT 1",
                "SELECT close FROM daily_quotes WHERE stock_id IN ('USDTWD','USD/TWD','TWD=X') ORDER BY date DESC LIMIT 1",
            ):
                try:
                    row = con.execute(sql).fetchone()
                except Exception:
                    row = None
                if row and _finite(row[0]) is not None:
                    return float(row[0])
        finally:
            con.close()
    except Exception:
        return None
    return None


def enrich_chip_5d_on_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    db_path: Optional[str] = None,
    as_of: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """若列上尚無 foreign_5d／trust_5d，從 daily_quotes 近 5 日淨額填入（左舊→右新）。"""
    path = db_path or os.environ.get("WAYNE_DB_PATH") or ""
    day = str(as_of or "").replace("-", "")[:8]
    out: List[Dict[str, Any]] = []
    con = None
    if path and os.path.isfile(path) and len(day) == 8:
        try:
            import sqlite3

            con = sqlite3.connect(path)
        except Exception:
            con = None
    try:
        for raw in rows:
            row = dict(raw)
            if row.get("foreign_5d") and row.get("trust_5d"):
                out.append(row)
                continue
            sid = str(row.get("stock_id") or "").strip()
            if con is None or not sid:
                row.setdefault("foreign_5d", ["N"] * 5)
                row.setdefault("trust_5d", ["N"] * 5)
                out.append(row)
                continue
            try:
                nets = con.execute(
                    """
                    SELECT COALESCE(foreign_net, 0), COALESCE(trust_net, 0)
                    FROM daily_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                    ORDER BY date DESC LIMIT 5
                    """,
                    (sid, day),
                ).fetchall()
            except Exception:
                nets = []
            # DB 新→舊；畫面左舊→右新
            nets_old_first = list(reversed(nets))
            while len(nets_old_first) < 5:
                nets_old_first.insert(0, (0, 0))
            row["foreign_5d"] = [_net_to_flag(float(n[0])) for n in nets_old_first[-5:]]
            row["trust_5d"] = [_net_to_flag(float(n[1])) for n in nets_old_first[-5:]]
            out.append(row)
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
    return out


def render_html_pages(
    picks: Sequence[Dict[str, Any]],
    out_dir: str,
    *,
    as_of: Optional[str] = None,
    title: str = "",
    empty_note: Optional[str] = None,
    prefix: str = "uv_d3",
    regime: Optional[dict] = None,
    db_path: Optional[str] = None,
) -> List[str]:
    """產品入口：填資料 → 原模板 Playwright 截 1290×2796。"""
    _ = title
    from undervalue_card import _order_rows, _sanitize_paint_rows

    rows = _order_rows(_sanitize_paint_rows(picks))
    rows = enrich_chip_5d_on_rows(rows, db_path=db_path, as_of=as_of)
    stocks = [pick_row_to_screener_stock(r, as_of=as_of) for r in rows]
    os.makedirs(out_dir or ".", exist_ok=True)
    fx = load_usd_twd_hint(db_path)
    reg = regime or resolve_regime(
        usd_twd=fx,
        empty_note=empty_note if not stocks else None,
    )
    date_s = _date_str(as_of)
    paths = render_screener_pages(stocks, date_s, reg, out_dir=out_dir)
    # 產品檔名 uv_d3_pN.png
    renamed: List[str] = []
    for i, p in enumerate(paths):
        dest = os.path.join(out_dir, f"{prefix}_p{i + 1}.png")
        if os.path.abspath(p) != os.path.abspath(dest):
            try:
                if os.path.exists(dest):
                    os.remove(dest)
                os.replace(p, dest)
            except Exception:
                dest = p
        renamed.append(dest)
    return renamed


def render_html_page(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    page_i: int = 0,
    page_n: int = 1,
    title: str = "",
    empty_note: Optional[str] = None,
) -> str:
    _ = (page_i, page_n, title)
    out_dir = os.path.dirname(save_path) or "."
    paths = render_html_pages(
        rows, out_dir, as_of=as_of, empty_note=empty_note, prefix="_uv_tmp"
    )
    src = paths[0]
    if os.path.abspath(src) != os.path.abspath(save_path):
        if os.path.exists(save_path):
            os.remove(save_path)
        os.replace(src, save_path)
    return save_path
