# -*- coding: utf-8 -*-
"""低估 D3 HTML／CSS 渲圖（Playwright 截圖）。

視覺參考使用者提供的 Noto Sans TC + JetBrains Mono 手機框樣式；
內容仍是既有四格：EPS爬坡／本益比位階／目標空間／對帳與撐壓。
無 Playwright 時由 undervalue_card PIL 路徑接手。
"""
from __future__ import annotations

import html
import math
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence

BASE_W = 1080
BASE_H = 1920
SAFE_TOP = 140
SAFE_BOTTOM = 180
CARDS_PER_PAGE = 4

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<style>
  @font-face {
    font-family: 'NotoSansTC';
    src: local('Noto Sans CJK TC'), local('Noto Sans CJK TC Bold'),
         local('Noto Sans TC'), local('NotoSansCJKtc-Regular');
    font-weight: 400 900;
  }
  @font-face {
    font-family: 'JetBrainsMono';
    src: local('JetBrains Mono'), local('JetBrains Mono Bold'),
         local('Noto Sans Mono CJK TC');
    font-weight: 500 700;
  }
  :root {
    --bg-canvas: #0B1120;
    --bg-card: #111827;
    --bg-cell: #161F33;
    --border-subtle: #334155;
    --text-primary: #F8FAFC;
    --text-secondary: #CBD5E1;
    --text-muted: #94A3B8;
    --green: #34D399;
    --green-edge: #10B981;
    --cyan: #38BDF8;
    --amber: #FBBF24;
    --purple: #A78BFA;
    --red: #F87171;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg-canvas);
    font-family: 'NotoSansTC', 'Noto Sans CJK TC', 'PingFang TC', sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
  }
  .mono {
    font-family: 'JetBrainsMono', 'Noto Sans Mono CJK TC', monospace;
    font-variant-numeric: tabular-nums;
  }
  .phone-frame {
    width: 1080px; height: 1920px; background: var(--bg-canvas);
    padding: 140px 28px 180px 28px;
    display: flex; flex-direction: column; gap: 12px; overflow: hidden;
  }
  .page-header { text-align: center; padding: 0 4px 2px; flex-shrink: 0; }
  .page-title { font-size: 34px; font-weight: 900; letter-spacing: 0.02em; }
  .page-sub { margin-top: 6px; font-size: 22px; color: var(--text-secondary); font-weight: 600; }
  .page-meta {
    display: inline-block; margin-top: 10px; font-size: 20px; font-weight: 700;
    color: var(--cyan); background: rgba(56,189,248,0.12);
    border: 1px solid rgba(56,189,248,0.3); padding: 4px 14px; border-radius: 999px;
  }
  .cards-stack { display: flex; flex-direction: column; gap: 12px; flex: 1; min-height: 0; }
  .stock-card {
    background: var(--bg-card); border: 3px solid var(--border-subtle);
    border-radius: 18px; overflow: hidden; display: flex; flex-direction: column;
    flex: 1 1 0; min-height: 0;
  }
  .stock-card.status-buy { border-color: rgba(52, 211, 153, 0.65); }
  .stock-card.status-wait { border-color: rgba(251, 191, 36, 0.6); }
  .stock-card.status-risk { border-color: rgba(167, 139, 250, 0.65); }
  .card-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; min-height: 64px; flex-shrink: 0;
  }
  .stock-card.status-buy .card-head { background: #063528; }
  .stock-card.status-wait .card-head { background: #3a2a0c; }
  .stock-card.status-risk .card-head { background: #2a1e42; }
  .head-left {
    display: flex; align-items: center; gap: 0; flex-wrap: nowrap;
    font-size: 28px; font-weight: 800; white-space: nowrap; overflow: hidden;
  }
  .head-left .sep { color: #7B8A86; padding: 0 7px; font-weight: 500; }
  .head-accent { color: var(--green); }
  .stock-card.status-wait .head-accent { color: var(--amber); }
  .stock-card.status-risk .head-accent { color: var(--purple); }
  .head-main { color: var(--text-primary); }
  .flow-pill {
    flex-shrink: 0; font-size: 22px; font-weight: 800;
    padding: 8px 14px; border-radius: 12px; margin-left: 10px;
  }
  .flow-buy { background: #e8a04a; color: #140c04; }
  .flow-sell { background: #b03038; color: #ffecec; }
  .flow-warn { background: #c88c38; color: #180e04; }
  .flow-purple { background: #7864b4; color: #120a1c; }
  .d3-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    grid-template-rows: minmax(0, 1.05fr) minmax(0, 0.95fr);
    flex: 1; min-height: 0; border-top: 1px solid var(--border-subtle);
  }
  .d3-cell {
    padding: 10px 14px 12px; display: flex; flex-direction: column; gap: 6px;
    justify-content: flex-start; min-height: 0; background: var(--bg-cell);
    overflow: hidden;
  }
  .d3-cell.tl, .d3-cell.bl { border-right: 1px solid var(--border-subtle); }
  .d3-cell.tl, .d3-cell.tr { border-bottom: 1px solid var(--border-subtle); }
  .d3-cell.tr { padding-bottom: 8px; gap: 4px; }
  .d3-cell.tr .cell-top { gap: 2px; }
  .d3-cell.tr .cell-main { font-size: 32px; }
  .d3-cell.tr .cell-sub { font-size: 24px; line-height: 1.15; }
  .d3-cell.tr .pe-gauge { margin-top: auto; flex-shrink: 0; min-height: 48px; }
  .d3-cell.bl, .d3-cell.br { padding-bottom: 10px; }
  .d3-cell.br .sr-line { margin-top: auto; }
  .cell-top { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
  .cell-title { font-size: 28px; font-weight: 900; color: var(--text-primary); letter-spacing: 0.01em; }
  .cell-main { font-size: 36px; font-weight: 800; line-height: 1.15; color: var(--text-primary); }
  .cell-sub {
    font-size: 28px; font-weight: 700; line-height: 1.25; color: var(--text-primary);
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .muted { color: #CBD5E1; font-size: 26px; font-weight: 700; }
  .up { color: var(--green); }
  .cyan { color: var(--cyan); }
  .red { color: var(--red); }
  .amber { color: var(--amber); }
  .pct-pill {
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 22px; font-weight: 900; color: #0c1210;
    background: var(--green); padding: 5px 14px; border-radius: 999px; min-width: 58px;
  }
  .stock-card.status-risk .pct-pill { background: var(--purple); color: #120a1c; }
  .row-bar { display: flex; align-items: center; gap: 12px; width: 100%; }
  .row-bar .lab { flex: 1; min-width: 0; font-size: 28px; font-weight: 800; }
  .mini-track {
    position: relative; width: 120px; height: 18px; flex-shrink: 0;
    background: #0B1220; border: 1px solid #334155; border-radius: 999px; overflow: hidden;
  }
  .mini-fill {
    height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, #10B981, #34D399);
  }
  .stock-card.status-risk .mini-fill { background: linear-gradient(90deg, #7C3AED, #A78BFA); }
  /* 本益比尺：軸＋刻度＋合理帶＋現況點＋三標（老花要看得見；不准跨格） */
  .pe-gauge { width: 100%; padding-top: 2px; }
  /* 三標在尺上方：Telegram 安全區壓縮高度時，下方標籤會被裁 */
  .pe-labels {
    display: flex; justify-content: space-between; margin-bottom: 4px;
    font-size: 22px; font-weight: 900; color: #E2E8F0; line-height: 1.1;
  }
  .pe-labels .fair { color: #7DD3FC; }
  .pe-rail {
    position: relative; height: 24px; width: 100%;
    display: flex; align-items: center;
  }
  .pe-axis {
    position: absolute; left: 0; right: 0; top: 50%; height: 5px;
    transform: translateY(-50%); background: #64748B; border-radius: 999px;
  }
  .pe-fair {
    position: absolute; top: 50%; height: 16px; transform: translateY(-50%);
    background: rgba(56, 189, 248, 0.5); border: 2px solid rgba(125, 211, 252, 0.95);
    border-radius: 8px; z-index: 1;
  }
  .pe-ticks { position: absolute; inset: 0; z-index: 1; }
  .pe-tick {
    position: absolute; top: 50%; width: 11px; height: 11px;
    transform: translate(-50%, -50%); border-radius: 50%; background: #E2E8F0;
    border: 1px solid #0B1120;
  }
  .pe-thumb {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 22px; height: 22px; border-radius: 50%;
    background: #34D399; border: 3px solid #ECFDF5;
    box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.4);
    z-index: 2;
  }
  .pe-thumb.warn { background: #FBBF24; box-shadow: 0 0 0 4px rgba(251, 191, 36, 0.4); }
  .pe-thumb.hot { background: #F87171; box-shadow: 0 0 0 4px rgba(248, 113, 113, 0.4); }
  .sr-line { display: flex; align-items: center; gap: 10px; font-size: 30px; font-weight: 800; }
  .sr-support { color: var(--green); }
  .sr-resist { color: #F87171; }
  .footer-legend {
    text-align: center; font-size: 20px; color: var(--text-secondary); padding-top: 2px; flex-shrink: 0;
  }
  .empty-wrap {
    flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  }
  .empty-title { font-size: 36px; font-weight: 900; }
  .empty-sub { font-size: 24px; color: var(--text-muted); }
</style>
</head>
<body>
  <div class="phone-frame">
    <div class="page-header">
      <div class="page-title">{{TITLE}}</div>
      <div class="page-sub">{{SUB}}</div>
      {{PAGE_META}}
    </div>
    <div class="cards-stack">{{CARDS}}</div>
    <div class="footer-legend">估值≠買訊｜★可買仍須對齊黃金買點才切入</div>
  </div>
</body>
</html>
"""


def playwright_available() -> bool:
    if os.environ.get("WAYNE_UV_HTML", "1").strip() in ("0", "false", "no"):
        return False
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

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


def _fmt_price(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    has_dec = abs(x - round(x)) > 1e-6
    if abs(x) >= 1000:
        return f"{x:,.1f}".rstrip("0").rstrip(".") if has_dec else f"{x:,.0f}"
    if has_dec:
        return f"{x:.1f}"
    if abs(x) >= 100:
        return f"{x:.0f}"
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _fmt_eps(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}" if abs(x - round(x)) > 1e-6 else f"{x:.0f}"
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def _fmt_pct(v: Any) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:+.0f}%" if abs(x) >= 10 else f"{x:+.1f}%"


def _fmt_num(v: Any, digits: int = 1) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def _status_class(mark: Any) -> str:
    m = str(mark or "").lower()
    if m in ("star", "true", "★", "*"):
        return "status-buy"
    if m in ("emerging", "emerge", "⚠️", "warn"):
        return "status-risk"
    return "status-wait"


def _mark_bits(mark: Any) -> tuple[str, str]:
    m = str(mark or "").lower()
    if m in ("star", "true", "★", "*"):
        return "★", "可買"
    if m in ("emerging", "emerge", "⚠️", "warn"):
        return "⚠", "量小"
    return "☆", "等止穩"


def _flow_class(chip: str) -> str:
    s = chip or ""
    if "興櫃" in s:
        return "flow-purple"
    if "同賣" in s or ("調節" in s and "投信" not in s):
        return "flow-warn"
    if "同買" in s or "連買" in s:
        return "flow-buy"
    if "調節" in s:
        return "flow-warn"
    return "flow-buy"


def _build_card(row: Dict[str, Any]) -> str:
    status = _status_class(row.get("mark"))
    glyph, glabel = _mark_bits(row.get("mark"))
    sid = html.escape(str(row.get("stock_id") or "—"))
    name = html.escape(str(row.get("name") or "").strip())
    close_s = html.escape(_fmt_price(row.get("close")))
    gm = _fmt_num(row.get("gross_margin"), 1)
    yoy = _fmt_pct(row.get("yoy_pct"))
    chip = str(row.get("chip_note") or "").strip()
    chip_html = ""
    if chip:
        chip_html = (
            f'<span class="flow-pill {_flow_class(chip)}">{html.escape(chip)}</span>'
        )

    head_bits = [
        f'<span class="head-accent">{html.escape(glyph)} {html.escape(glabel)}</span>',
        f'<span class="sep">|</span><span class="head-main">{sid}{" " + name if name else ""}</span>',
        f'<span class="sep">|</span><span class="head-main">{close_s}元</span>',
    ]
    if gm != "—":
        head_bits.append(
            f'<span class="sep">|</span><span class="head-accent">毛利{html.escape(gm)}%</span>'
        )
    if yoy != "—":
        head_bits.append(
            f'<span class="sep">|</span><span class="head-accent">年增{html.escape(yoy)}</span>'
        )

    eps_e = _finite(row.get("eps_earned"))
    eps_y = _finite(row.get("eps_2026"))
    eps_n = _finite(row.get("eps_2027"))
    earned_pct = None
    climb_pct = None
    if eps_e is not None and eps_n is not None and eps_n > 0:
        earned_pct = max(0.0, min(999.0, eps_e / eps_n * 100.0))
    if eps_y is not None and eps_n is not None and eps_n > 0:
        climb_pct = max(0.0, min(100.0, eps_y / eps_n * 100.0))

    n_raw = row.get("eps_2027_label")
    n_s = str(n_raw) if n_raw else _fmt_eps(eps_n)
    y_s = _fmt_eps(eps_y)
    if eps_y is not None and abs(eps_y - round(eps_y)) < 1e-9 and abs(eps_y) < 100:
        y_s = f"{eps_y:.1f}"
    if not n_raw and eps_n is not None and abs(eps_n - round(eps_n)) < 1e-9 and abs(eps_n) < 100:
        n_s = f"{eps_n:.1f}"
    n_lab = "明" if (n_raw or (eps_n is not None and eps_n >= 100)) else "明年"
    climb_html = ""
    if climb_pct is not None:
        climb_html = f'<span class="pct-pill mono">{int(round(climb_pct))}%</span>'
    earned_extra = (
        f'<span class="muted mono">{int(round(earned_pct))}%</span>'
        if earned_pct is not None
        else ""
    )

    pe_now = _finite(row.get("pe"))
    pe_fwd = _finite(row.get("pe_fwd"))
    pe_year = _finite(row.get("pe_year"))
    pe_next = _finite(row.get("pe_next"))
    fair_lo = pe_next if pe_next is not None else pe_year
    fair_hi = pe_year if pe_year is not None else pe_next
    if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
        fair_lo, fair_hi = fair_hi, fair_lo
    pe_s = _fmt_num(pe_now, 1)
    if pe_s != "—" and pe_now is not None and abs(pe_now - round(pe_now)) < 0.05:
        pe_s = f"{pe_now:.0f}"
    fwd_s = _fmt_num(pe_fwd, 1)
    if fwd_s != "—" and pe_fwd is not None and abs(pe_fwd - round(pe_fwd)) < 0.05:
        fwd_s = f"{pe_fwd:.0f}"
    band = ""
    emerging = status == "status-risk"
    if (not emerging) and fair_lo is not None and fair_hi is not None:
        band = f'<span class="muted">(合理 {fair_lo:.0f}-{fair_hi:.0f}x)</span>'

    # 本益比尺：同一刻度算現況點與合理帶
    scale_vals = [v for v in (pe_now, pe_fwd, fair_lo, fair_hi) if v is not None and v > 0]
    if not scale_vals and pe_now is not None:
        scale_vals = [pe_now]
    span_lo = min(scale_vals) * 0.85 if scale_vals else 10.0
    span_hi = max(scale_vals) * 1.15 if scale_vals else 40.0
    den = max(span_hi - span_lo, 1e-9)

    def _pe_pct(v: Optional[float], *, lo: float = 4.0, hi: float = 96.0) -> float:
        if v is None:
            return 50.0
        return max(lo, min(hi, (float(v) - span_lo) / den * 100.0))

    pe_marker = pe_now if pe_now is not None else pe_fwd
    pe_pct = _pe_pct(pe_marker)
    fair_left = _pe_pct(fair_lo, lo=2.0, hi=90.0) if fair_lo is not None else 35.0
    fair_right = _pe_pct(fair_hi, lo=10.0, hi=98.0) if fair_hi is not None else 65.0
    if fair_right < fair_left:
        fair_left, fair_right = fair_right, fair_left
    fair_width = max(8.0, fair_right - fair_left)
    thumb_cls = "pe-thumb"
    if fair_lo is not None and fair_hi is not None and pe_marker is not None:
        if pe_marker > fair_hi * 1.05:
            thumb_cls = "pe-thumb hot"
        elif pe_marker >= fair_lo:
            thumb_cls = "pe-thumb warn"
    ticks_html = "".join(
        f'<span class="pe-tick" style="left: {(i + 0.5) / 5 * 100:.1f}%;"></span>'
        for i in range(5)
    )
    pe_gauge = f"""
          <div class="pe-gauge">
            <div class="pe-labels"><span>偏低</span><span class="fair">合理帶</span><span>偏貴</span></div>
            <div class="pe-rail">
              <div class="pe-axis"></div>
              <div class="pe-fair" style="left:{fair_left:.1f}%;width:{fair_width:.1f}%;"></div>
              <div class="pe-ticks">{ticks_html}</div>
              <div class="{thumb_cls}" style="left:{pe_pct:.1f}%;"></div>
            </div>
          </div>"""

    fair = _finite(row.get("fair_year"))
    tgt = _finite(row.get("target_next"))
    ups_f = _finite(row.get("ups_fair_pct"))
    ups_t = _finite(row.get("ups_tgt_pct"))
    tgt_rows = []
    if emerging and fair is not None and tgt is not None:
        frac = max(0, min(100, int(round(ups_t or 0))))
        tgt_rows.append(
            f'<div class="row-bar"><div class="lab cell-sub mono">明年看 {_fmt_price(fair)}-{_fmt_price(tgt)}</div>'
            f'<div class="mini-track"><div class="mini-fill" style="width:{frac}%"></div></div></div>'
        )
    else:
        if fair is not None:
            frac = max(0, min(100, int(round(ups_f or 0))))
            ups = f'<span class="up mono">({_fmt_pct(ups_f)})</span>' if ups_f is not None else ""
            tgt_rows.append(
                f'<div class="row-bar"><div class="lab cell-sub mono">今年看 {_fmt_price(fair)} {ups}</div>'
                f'<div class="mini-track"><div class="mini-fill" style="width:{frac}%"></div></div></div>'
            )
        if tgt is not None:
            frac = max(0, min(100, int(round(ups_t or 0))))
            ups = f'<span class="up mono">({_fmt_pct(ups_t)})</span>' if ups_t is not None else ""
            tgt_rows.append(
                f'<div class="row-bar"><div class="lab cell-sub mono">明年看 {_fmt_price(tgt)} {ups}</div>'
                f'<div class="mini-track"><div class="mini-fill" style="width:{frac}%"></div></div></div>'
            )

    thr = _finite(row.get("rev_threshold_yi"))
    oct_r = _finite(row.get("rev_oct_yi"))
    support = _finite(row.get("support"))
    resist = _finite(row.get("resistance"))
    broken = bool(row.get("tech_broken")) or (
        "破撐" in str(row.get("tech_status") or "") or "破撐" in str(row.get("reason") or "")
    )
    if emerging:
        br_title = "【對帳防線】"
        thr_line = f'明年門檻 {_fmt_num(thr, 2 if (thr is not None and thr < 10) else 1)}億/月'
    else:
        br_title = "【對帳與撐壓】"
        thr_line = f'月門檻 {_fmt_num(thr, 1)}億'
        if oct_r is not None:
            mon = str(row.get("rev_month_label") or "最新").strip() or "最新"
            thr_line += f' <span class="muted">({html.escape(mon)}{_fmt_num(oct_r, 1)})</span>'
    if broken and support is not None and not emerging:
        sr_html = (
            f'<div class="sr-line amber mono">▲破撐 {_fmt_price(support)}'
            f'<span class="muted"> | </span>'
            f'<span class="sr-resist">壓 {_fmt_price(resist)}</span></div>'
        )
    else:
        sr_html = (
            f'<div class="sr-line mono">'
            f'<span class="sr-support">撐 {_fmt_price(support)}</span>'
            f'<span class="muted"> | </span>'
            f'<span class="sr-resist">壓 {_fmt_price(resist)}</span></div>'
        )

    return f"""
    <div class="stock-card {status}">
      <div class="card-head">
        <div class="head-left">{''.join(head_bits)}</div>
        {chip_html}
      </div>
      <div class="d3-grid">
        <div class="d3-cell tl">
          <div class="cell-top">
            <div class="cell-title">【EPS爬坡】</div>
            <div class="cell-main mono">已賺 {_fmt_eps(eps_e)} {earned_extra}</div>
          </div>
          <div class="cell-sub mono">今年 {html.escape(y_s)} | {html.escape(n_lab)} {html.escape(n_s)} {climb_html}</div>
        </div>
        <div class="d3-cell tr">
          <div class="cell-top">
            <div class="cell-title">【本益比位階】</div>
            <div class="cell-main mono">今年 {html.escape(pe_s)}x</div>
            <div class="cell-sub mono">前瞻 {html.escape(fwd_s)}x {band}</div>
          </div>
          {pe_gauge}
        </div>
        <div class="d3-cell bl">
          <div class="cell-title">【目標空間】</div>
          <div>{''.join(tgt_rows) if tgt_rows else '<div class="cell-sub muted">—</div>'}</div>
        </div>
        <div class="d3-cell br">
          <div class="cell-top">
            <div class="cell-title">{br_title}</div>
            <div class="cell-sub mono">{thr_line}</div>
          </div>
          {sr_html}
        </div>
      </div>
    </div>
    """


def render_html_page(
    rows: Sequence[Dict[str, Any]],
    save_path: str,
    *,
    as_of: Optional[str] = None,
    page_i: int = 0,
    page_n: int = 1,
    title: str = "版本 D3 終極版｜2×2 矩陣 · 籌碼撐壓整合",
    empty_note: Optional[str] = None,
) -> str:
    from undervalue_card import _as_of_close_label

    date_s = _as_of_close_label(as_of) if as_of else ""
    sub = "已整合外資／投信連買賣與大量區撐壓"
    if date_s:
        sub = f"{date_s}｜{sub}"
    page_meta = ""
    if page_n > 1:
        page_meta = (
            f'<div class="page-meta mono">第{page_i + 1}/{max(1, page_n)}頁</div>'
        )
    if not rows:
        cards = (
            '<div class="empty-wrap">'
            '<div class="empty-title">無真成長低估名單</div>'
            f'<div class="empty-sub">{html.escape(str(empty_note or "已剔除假低估陷阱；有資料再顯示"))}</div>'
            "</div>"
        )
    else:
        cards = "\n".join(_build_card(dict(r)) for r in rows)

    page_html = (
        HTML_TEMPLATE.replace("{{TITLE}}", html.escape(f"{title}（Top {CARDS_PER_PAGE}）"))
        .replace("{{SUB}}", html.escape(sub))
        .replace("{{PAGE_META}}", page_meta)
        .replace("{{CARDS}}", cards)
    )

    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--font-render-hinting=none",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
            ]
        )
        page = browser.new_page(
            viewport={"width": BASE_W, "height": BASE_H},
            device_scale_factor=1,
        )
        # file:// 較穩：字型 local() 可吃系統 Noto
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(page_html)
            tmp = fh.name
        try:
            page.goto(f"file://{tmp}", wait_until="load", timeout=20000)
            page.wait_for_timeout(80)
            page.screenshot(path=save_path, full_page=False, type="png")
        finally:
            browser.close()
            try:
                os.unlink(tmp)
            except Exception:
                pass
    return save_path


def render_html_pages(
    picks: Sequence[Dict[str, Any]],
    out_dir: str,
    *,
    as_of: Optional[str] = None,
    title: str = "版本 D3 終極版｜2×2 矩陣 · 籌碼撐壓整合",
    empty_note: Optional[str] = None,
    prefix: str = "uv_d3",
) -> List[str]:
    from undervalue_card import (
        _order_rows,
        _page_count,
        _sanitize_paint_rows,
    )

    rows = _order_rows(_sanitize_paint_rows(picks))
    os.makedirs(out_dir or ".", exist_ok=True)
    n_pages = _page_count(len(rows)) if rows else 1
    paths: List[str] = []
    if not rows:
        p = os.path.join(out_dir, f"{prefix}_p1.png")
        paths.append(
            render_html_page(
                [], p, as_of=as_of, page_i=0, page_n=1, title=title, empty_note=empty_note
            )
        )
        return paths
    for i in range(n_pages):
        chunk = rows[i * CARDS_PER_PAGE : (i + 1) * CARDS_PER_PAGE]
        p = os.path.join(out_dir, f"{prefix}_p{i + 1}.png")
        paths.append(
            render_html_page(
                chunk,
                p,
                as_of=as_of,
                page_i=i,
                page_n=n_pages,
                title=title,
                empty_note=empty_note,
            )
        )
    return paths
