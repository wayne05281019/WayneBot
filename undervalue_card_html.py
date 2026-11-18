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
  /* 營收進度：微縮＋不換行，避免 (90%) 被擠到下一行 */
  .cell-v.rev-line { font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
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
    rev_line = str(
        s.get("rev_line")
        or f"{s.get('rev_now') or '—'} / 需{s.get('rev_gate') or '—'} ({int(s.get('rev_pct') or 0)}%)"
    )
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
            <div class="ruler-labels mono"><span>{html.escape(str(s.get('pe_min') or '—'))}</span><span>{html.escape(str(s.get('pe_mid') or '—'))}</span><span>{html.escape(str(s.get('pe_max') or '—'))}</span></div>
          </div>
        </div>
        <div class="d3-cell">
          <div class="cell-k">{bl_title}</div>
          <div class="cell-v mono">正常 {html.escape(s['target_norm'])}｜保守 {html.escape(s['target_cons'])}</div>
          {bl_bottom}
        </div>
        <div class="d3-cell">
          <div class="cell-k">營收達標進度＋撐壓</div>
          <div class="cell-v mono rev-line">{html.escape(rev_line)}</div>
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


_PLAYWRIGHT_OK: Optional[bool] = None


def playwright_available() -> bool:
    """套件在、但 CI 未 `playwright install` 時仍算不可用（避免 launch 炸掉整段 smoke）。"""
    global _PLAYWRIGHT_OK
    if _PLAYWRIGHT_OK is not None:
        return _PLAYWRIGHT_OK
    if os.environ.get("WAYNE_UV_HTML", "1").strip() in ("0", "false", "no"):
        _PLAYWRIGHT_OK = False
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = getattr(p.chromium, "executable_path", None) or ""
            if not exe or not os.path.isfile(exe):
                _PLAYWRIGHT_OK = False
                return False
            # headless shell 路徑也可能缺；試一下極短 launch
            browser = p.chromium.launch(headless=True)
            browser.close()
        _PLAYWRIGHT_OK = True
        return True
    except Exception:
        _PLAYWRIGHT_OK = False
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


def _q4_progress_from_rev_yyyymm(yyyymm: Optional[str]) -> str:
    """依資料庫最新已公布月營收月份，不准用日曆月假裝已公布。"""
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


def _pe_scale_labels(
    pe_fwd12: Optional[float],
    fair_lo: Optional[float],
    fair_hi: Optional[float],
) -> tuple[str, str, str, float]:
    """依各股合理帶＋實際滾動本益比動態產生 pe_min/mid/max 與圓點％。"""
    vals = [v for v in (pe_fwd12, fair_lo, fair_hi) if v is not None and v > 0]
    if not vals:
        return "—", "—", "—", 50.0
    lo = float(min(vals))
    hi = float(max(vals))
    span = max(hi - lo, 1.0)
    pad = max(span * 0.2, 1.5)
    a0 = max(1.0, math.floor(lo - pad))
    a2 = math.ceil(hi + pad)
    if a2 <= a0:
        a2 = a0 + 5
    a1 = round((a0 + a2) / 2.0)
    pe_dot = 50.0
    if pe_fwd12 is not None and a2 > a0:
        pe_dot = (float(pe_fwd12) - a0) / (a2 - a0) * 100.0
        pe_dot = max(8.0, min(92.0, pe_dot))
    return f"{int(a0)}x", f"{int(a1)}x", f"{int(a2)}x", pe_dot


def _streak_flags(flags: Sequence[str], want: str) -> int:
    n = 0
    for x in reversed(list(flags)[:5]):
        if str(x).upper()[:1] != want:
            break
        n += 1
    return n


def _pill_from_5d_flags(
    foreign_5d: Sequence[str], trust_5d: Sequence[str], *, emerging: bool
) -> tuple[str, str]:
    """膠囊必須與方塊同一組 ['B'/'S'/'N']，不准另寫死字樣。"""
    if emerging:
        return "warn", "興櫃無法人"
    f5 = _normalize_5d_flags(foreign_5d)
    t5 = _normalize_5d_flags(trust_5d)
    f_buy = sum(1 for x in f5 if x == "B")
    f_sell = sum(1 for x in f5 if x == "S")
    t_buy = sum(1 for x in t5 if x == "B")
    t_sell = sum(1 for x in t5 if x == "S")
    tb = _streak_flags(t5, "B")
    fb = _streak_flags(f5, "B")
    newest_f = f5[-1] if f5 else "N"
    newest_t = t5[-1] if t5 else "N"
    if newest_f == "S" and newest_t == "S":
        return "sell", "外投同賣"
    if newest_f == "B" and newest_t == "B":
        return "buy", "外投同買"
    if t_buy >= 2 and f_sell >= 2 and newest_t == "B":
        return "sell", "投信護盤・外資賣"
    if tb >= 2:
        return "buy", f"投信連買{tb}日"
    if fb >= 2:
        return "buy", f"外資連買{fb}日"
    if newest_t == "B" and newest_f != "B":
        return "sell", "投信護盤・外資賣" if newest_f == "S" else "投信買・外資平"
    if newest_f == "B":
        return "buy", "外資買超"
    if t_sell >= 2 or f_sell >= 2:
        return "sell", "法人調節"
    return "buy", "—"


def _emerging_note_text(row: Dict[str, Any]) -> str:
    """興櫃左下：寫出暫定價數字，不准只印空泛警示。"""
    tech = str(row.get("tech_status") or "").strip()
    place = _finite(row.get("placement_price"))
    if place is None:
        place = _finite(row.get("offer_price"))
    tech_tail = tech
    for prefix in ("現增暫定價", "現增暫定", "現增"):
        if tech_tail.startswith(prefix):
            tech_tail = tech_tail[len(prefix) :].lstrip("＋+｜| 、")
            break
    tech_tail = tech_tail.strip() or "60日均量過小"
    if place is not None:
        return f"現增暫定 {_fmt_price(place)}元｜{tech_tail}"[:36]
    if tech:
        return tech[:36]
    return "現增暫定價｜60日均量過小"


def pick_row_to_screener_stock(row: Dict[str, Any], *, as_of: Optional[str] = None) -> dict:
    """把融合庫低估列填進模板欄位；不准改 HTML 結構。"""
    mark = str(row.get("mark") or "").lower()
    emerging = mark in ("emerging", "emerge") or bool(row.get("emerging"))
    close = _finite(row.get("close"))
    support = _finite(row.get("support"))
    broken = bool(row.get("tech_broken")) or (
        "破撐" in str(row.get("tech_status") or "") or "破撐" in str(row.get("reason") or "")
    )
    # 現價跌破大量支撐：撐壓列一律 ▲破撐（含興櫃）；上市櫃 ★ 再降 ☆
    price_broke = (
        close is not None and support is not None and close < support
    )
    if price_broke:
        broken = True
    if emerging:
        status, icon, status_label = "risk", "⚠️", "興櫃量小"
    elif mark in ("star", "true", "★", "*") and not broken:
        status, icon, status_label = "buy", "★", "可買"
    else:
        status, icon, status_label = "wait", "☆", "等止穩"

    foreign_5d = _normalize_5d_flags(row.get("foreign_5d"))
    trust_5d = _normalize_5d_flags(row.get("trust_5d"))
    flow_type, flow_pill = _pill_from_5d_flags(foreign_5d, trust_5d, emerging=emerging)

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
    elif _finite(row.get("pe_fwd")) is not None:
        pe_fwd12 = _finite(row.get("pe_fwd"))

    pe_year = _finite(row.get("pe_year"))
    pe_next = _finite(row.get("pe_next"))
    fair_lo = pe_next if pe_next is not None else pe_year
    fair_hi = pe_year if pe_year is not None else pe_next
    if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
        fair_lo, fair_hi = fair_hi, fair_lo
    pe_min, pe_mid, pe_max, pe_dot = _pe_scale_labels(pe_fwd12, fair_lo, fair_hi)

    if pe_fwd12 is not None and fair_lo is not None and fair_hi is not None:
        if pe_fwd12 < fair_lo:
            pe_note = "偏低"
        elif pe_fwd12 > fair_hi:
            pe_note = "偏貴"
        else:
            pe_note = "合理帶"
    elif pe_fwd12 is not None:
        pe_note = "滾動"
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

    resist = _finite(row.get("resistance"))
    # 撐壓列依現價 vs 支撐；興櫃也要橘色 ▲破撐（狀態燈仍可維持 ⚠️）
    support_broken = bool(price_broke)
    support_ok = not support_broken
    if support_broken and support is not None:
        support_text = f"▲破撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
    else:
        support_text = f"撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"

    fair = _finite(row.get("fair_year"))
    tgt = _finite(row.get("target_next"))
    target_norm = _fmt_price(tgt if tgt is not None else fair)
    target_cons = _fmt_price(fair if fair is not None else tgt)

    gm = _finite(row.get("gross_margin"))
    gm_s = f"{gm:.1f}%" if gm is not None else "—"

    rev_ym = str(row.get("rev_yyyymm") or "").replace("-", "")[:6]
    q4 = _q4_progress_from_rev_yyyymm(rev_ym) if rev_ym else _q4_progress_from_rev_yyyymm(
        None
    )
    # 列上若已帶最新公布月標籤但沒 yyyymm，仍不准用日曆月假裝 11月✓
    if not rev_ym:
        lab = str(row.get("rev_month_label") or "").strip()
        if lab.startswith("10"):
            q4 = "Q4: 10月✓・11·12待補"
        elif lab.startswith("11"):
            q4 = "Q4: 10月✓・11月✓・12待補"
        elif lab.startswith("12"):
            q4 = "Q4: 10·11·12月✓"

    month_lab = str(row.get("rev_month_label") or "").strip()
    if not month_lab and len(rev_ym) == 6:
        month_lab = f"{int(rev_ym[4:6])}月"

    def _fmt_yi_num(v: float) -> str:
        if abs(float(v)) < 10:
            return f"{float(v):.2f}".rstrip("0").rstrip(".")
        return _fmt_num(v, 1)

    if oct_r is not None:
        rev_num = _fmt_yi_num(float(oct_r))
        rev_now = f"{month_lab}{rev_num}億" if month_lab else f"{rev_num}億"
    else:
        rev_num = None
        rev_now = "—"
    if thr is not None:
        gate_num = _fmt_yi_num(float(thr))
        rev_gate = f"{gate_num}億"
    else:
        gate_num = None
        rev_gate = "—"
    # 單行：10月18.4 / 需20.5億 (90%)
    if rev_num is not None and gate_num is not None:
        head = f"{month_lab}{rev_num}" if month_lab else rev_num
        rev_line = f"{head} / 需{gate_num}億 ({int(rev_pct)}%)"
    elif rev_num is not None:
        rev_line = f"{rev_now} ({int(rev_pct)}%)"
    else:
        rev_line = "—"

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
        "pe_min": pe_min,
        "pe_mid": pe_mid,
        "pe_max": pe_max,
        "target_norm": target_norm,
        "target_cons": target_cons,
        "foreign_5d": foreign_5d,
        "trust_5d": trust_5d,
        "is_emerging": emerging,
        "emerging_note": _emerging_note_text(row),
        "rev_now": rev_now,
        "rev_gate": rev_gate,
        "rev_line": rev_line,
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
        # 不准寫死 31.50；缺匯率只標 —
        if not market_above_ma20 and int(foreign_sell_days or 0) >= 3:
            regime = {
                "class": "regime-bear",
                "text": "🔴 系統性修正盤・嚴守站回支撐再買",
                "fx_text": "USD/TWD —",
            }
        else:
            regime = {
                "class": "regime-normal",
                "text": "🟢 資金常態盤・依區間與黃金買點操作",
                "fx_text": "USD/TWD —",
            }
    else:
        regime = detect_market_regime(
            float(fx), int(foreign_sell_days or 0), bool(market_above_ma20)
        )
    if empty_note:
        regime = dict(regime)
        regime["text"] = str(empty_note)[:48]
    return regime


def load_usd_twd_hint(db_path: Optional[str] = None) -> Optional[float]:
    """讀庫內即時／最新台幣匯率；沒有就 None（不准假造 31.50）。"""
    path = db_path or os.environ.get("WAYNE_DB_PATH") or ""
    if not path or not os.path.isfile(path):
        return None
    try:
        import json
        import sqlite3

        con = sqlite3.connect(path)
        try:
            try:
                row = con.execute(
                    "SELECT payload FROM us_overnight ORDER BY as_of DESC LIMIT 1"
                ).fetchone()
            except Exception:
                row = None
            if row and row[0]:
                try:
                    payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    fx = _finite((payload or {}).get("usdtwd_px"))
                    if fx is not None:
                        return float(fx)
                except Exception:
                    pass
            for sql in (
                "SELECT close FROM index_daily WHERE symbol IN ('USDTWD','USD/TWD') ORDER BY date DESC LIMIT 1",
                "SELECT close FROM daily_quotes WHERE stock_id IN ('USDTWD','USD/TWD','TWD=X') ORDER BY date DESC LIMIT 1",
            ):
                try:
                    r2 = con.execute(sql).fetchone()
                except Exception:
                    r2 = None
                if r2 and _finite(r2[0]) is not None:
                    return float(r2[0])
        finally:
            con.close()
    except Exception:
        return None
    return None


def load_regime_inputs(db_path: Optional[str] = None, as_of: Optional[str] = None) -> dict:
    """匯率＋外資連賣日數＋大盤是否站上 MA20（Asia/Taipei 開市日鍵）。"""
    path = db_path or os.environ.get("WAYNE_DB_PATH") or ""
    day = str(as_of or "").replace("-", "")[:8]
    out = {
        "usd_twd": load_usd_twd_hint(path) if path else None,
        "foreign_sell_days": 0,
        "market_above_ma20": True,
    }
    if not path or not os.path.isfile(path):
        return out
    try:
        import sqlite3

        con = sqlite3.connect(path)
        try:
            try:
                tw = con.execute(
                    """
                    SELECT close, ma20 FROM index_daily
                    WHERE symbol='TWII'
                      AND (?='' OR REPLACE(CAST(date AS TEXT),'-','')<=?)
                    ORDER BY date DESC LIMIT 1
                    """,
                    (day if len(day) == 8 else "", day if len(day) == 8 else "99999999"),
                ).fetchone()
            except Exception:
                tw = None
            if tw and _finite(tw[0]) is not None and _finite(tw[1]) is not None:
                out["market_above_ma20"] = float(tw[0]) >= float(tw[1])
            try:
                sells = con.execute(
                    """
                    SELECT foreign_net_yi FROM market_inst_bfi_daily
                    WHERE (?='' OR REPLACE(CAST(date AS TEXT),'-','')<=?)
                    ORDER BY date DESC LIMIT 12
                    """,
                    (day if len(day) == 8 else "", day if len(day) == 8 else "99999999"),
                ).fetchall()
            except Exception:
                sells = []
            streak = 0
            for r in sells:
                v = _finite(r[0])
                if v is not None and v < 0:
                    streak += 1
                else:
                    break
            out["foreign_sell_days"] = streak
        finally:
            con.close()
    except Exception:
        return out
    return out


def _chip_coverage_days(con: Any, day: str, n: int = 5) -> List[str]:
    """近 n 個「市場有法人買賣超資料」的交易日（新→舊）。缺資料日（全 0）跳過。"""
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
            GROUP BY d
            HAVING SUM(ABS(COALESCE(foreign_net,0)))
                 + SUM(ABS(COALESCE(trust_net,0))) > 0
            ORDER BY d DESC
            LIMIT ?
            """,
            (day, int(n)),
        ).fetchall()
    except Exception:
        return []
    return [str(r[0]) for r in rows if r and r[0]]


def enrich_live_rows_from_db(
    rows: Sequence[Dict[str, Any]],
    *,
    db_path: Optional[str] = None,
    as_of: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """出圖當下接真收盤／月營收／近5日籌碼；覆寫寫死樣本，不准假 11月✓。"""
    path = db_path or os.environ.get("WAYNE_DB_PATH") or ""
    day = str(as_of or "").replace("-", "")[:8]
    if len(day) != 8:
        day = date.today().strftime("%Y%m%d")
    out: List[Dict[str, Any]] = []
    con = None
    chip_days: List[str] = []
    if path and os.path.isfile(path):
        try:
            import sqlite3

            con = sqlite3.connect(path)
            chip_days = _chip_coverage_days(con, day, 5)
        except Exception:
            con = None
            chip_days = []
    try:
        for raw in rows:
            row = dict(raw)
            sid = str(row.get("stock_id") or "").strip()
            emerging = str(row.get("mark") or "").lower() in ("emerging", "emerge") or bool(
                row.get("emerging")
            )
            if con is not None and sid:
                # 即時／最新收
                try:
                    cq = con.execute(
                        """
                        SELECT close FROM daily_quotes
                        WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                          AND close IS NOT NULL AND close>0
                        ORDER BY date DESC LIMIT 1
                        """,
                        (sid, day),
                    ).fetchone()
                except Exception:
                    cq = None
                if (cq is None or _finite(cq[0]) is None) and emerging:
                    try:
                        cq = con.execute(
                            """
                            SELECT close FROM emerging_quotes
                            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                              AND close IS NOT NULL AND close>0
                            ORDER BY date DESC LIMIT 1
                            """,
                            (sid, day),
                        ).fetchone()
                    except Exception:
                        cq = None
                if cq and _finite(cq[0]) is not None:
                    row["close"] = float(cq[0])

                # 最新月營收（千元→億）
                try:
                    mr = con.execute(
                        """
                        SELECT yyyymm, revenue FROM monthly_revenue
                        WHERE stock_id=? AND REPLACE(CAST(yyyymm AS TEXT),'-','')<=?
                        ORDER BY yyyymm DESC LIMIT 1
                        """,
                        (sid, day[:6]),
                    ).fetchone()
                except Exception:
                    mr = None
                if mr and mr[0] is not None and _finite(mr[1]) is not None:
                    yyyymm = str(mr[0]).replace("-", "")[:6]
                    row["rev_yyyymm"] = yyyymm
                    row["rev_month_label"] = f"{int(yyyymm[4:6])}月"
                    row["rev_oct_yi"] = float(mr[1]) / 100000.0

                # 近 5 個有法人資料的交易日 → B/S/N（強制覆寫樣本陣列）
                if not emerging and chip_days:
                    f_flags: List[str] = []
                    t_flags: List[str] = []
                    for d in reversed(chip_days):  # 左舊→右新
                        try:
                            net = con.execute(
                                """
                                SELECT COALESCE(foreign_net,0), COALESCE(trust_net,0)
                                FROM daily_quotes
                                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
                                LIMIT 1
                                """,
                                (sid, d),
                            ).fetchone()
                        except Exception:
                            net = None
                        if net is None:
                            f_flags.append("N")
                            t_flags.append("N")
                        else:
                            f_flags.append(_net_to_flag(float(net[0] or 0)))
                            t_flags.append(_net_to_flag(float(net[1] or 0)))
                    while len(f_flags) < 5:
                        f_flags.insert(0, "N")
                        t_flags.insert(0, "N")
                    row["foreign_5d"] = f_flags[-5:]
                    row["trust_5d"] = t_flags[-5:]
                    ft, pill = _pill_from_5d_flags(
                        row["foreign_5d"], row["trust_5d"], emerging=False
                    )
                    _ = ft
                    row["chip_note"] = pill
                elif emerging:
                    row["foreign_5d"] = ["N"] * 5
                    row["trust_5d"] = ["N"] * 5
                    row["chip_note"] = "興櫃無法人"

            # 無 DB 時仍清掉與方塊矛盾的寫死 chip；有陣列就依陣列重算
            if row.get("foreign_5d") is not None and row.get("trust_5d") is not None:
                _, pill2 = _pill_from_5d_flags(
                    row.get("foreign_5d"), row.get("trust_5d"), emerging=emerging
                )
                row["chip_note"] = pill2

            close = _finite(row.get("close"))
            support = _finite(row.get("support"))
            if close is not None and support is not None and close < support:
                row["tech_broken"] = True
            out.append(row)
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
    return out


# 相容舊名
def enrich_chip_5d_on_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    db_path: Optional[str] = None,
    as_of: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return enrich_live_rows_from_db(rows, db_path=db_path, as_of=as_of)


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
    rows = enrich_live_rows_from_db(rows, db_path=db_path, as_of=as_of)
    stocks = [pick_row_to_screener_stock(r, as_of=as_of) for r in rows]
    os.makedirs(out_dir or ".", exist_ok=True)
    rin = load_regime_inputs(db_path, as_of)
    reg = regime or resolve_regime(
        usd_twd=rin.get("usd_twd"),
        foreign_sell_days=int(rin.get("foreign_sell_days") or 0),
        market_above_ma20=bool(rin.get("market_above_ma20", True)),
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
