# -*- coding: utf-8 -*-
# ==============================================================================
# 查股「一頁式個股旗艦卡」——插在查股相簿第一張；不准改既有五張圖。
# 版面以使用者提供範本為準（上市 2383／興櫃 3595）。
# 嚴禁 Pillow／matplotlib；HTML/CSS + Playwright 430×932 @3x → 1290×2796。
# ==============================================================================
from __future__ import annotations

import html
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from playwright.sync_api import sync_playwright

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
    --bg: #0B1120;
    --card: #151E32;
    --line: #243044;
    --text: #F8FAFC;
    --muted: #94A3B8;
    --dim: #64748B;
    --red: #F87171;
    --green: #34D399;
    --cyan: #38BDF8;
    --amber: #FBBF24;
    --gold: #E8C547;
    --purple: #A78BFA;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Noto Sans TC', -apple-system, BlinkMacSystemFont, 'PingFang TC', sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .mono { font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-variant-numeric: tabular-nums; }
  .phone {
    width: 430px; height: 932px; background: var(--bg);
    padding: 48px 14px 60px 14px; /* Telegram 上144／下180 */
    display: flex; flex-direction: column; gap: 7px; overflow: hidden;
  }

  /* —— 頂部 —— */
  .brand {
    font-size: 10px; color: var(--dim); font-weight: 600;
    display: flex; align-items: center; gap: 5px; flex-shrink: 0;
  }
  .brand .dot { width: 8px; height: 8px; border-radius: 50%; background: #334155; }

  .title-row {
    display: flex; align-items: center; gap: 7px; flex-wrap: wrap; flex-shrink: 0;
  }
  .title-main {
    font-size: 15px; font-weight: 900; letter-spacing: -0.2px;
    white-space: nowrap;
  }
  .tag {
    font-size: 9.5px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
    background: rgba(148,163,184,0.12); color: var(--muted);
    border: 1px solid rgba(148,163,184,0.22); white-space: nowrap;
  }

  .price-row {
    display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-shrink: 0;
  }
  .price-block { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .price {
    font-size: 28px; font-weight: 900; color: var(--green); line-height: 1;
    letter-spacing: -0.5px;
  }
  .chg {
    font-size: 13px; font-weight: 800; color: var(--green);
  }
  .pill-row { display: flex; gap: 5px; flex-shrink: 0; }
  .pill {
    font-size: 10px; font-weight: 800; padding: 3px 8px; border-radius: 999px;
    white-space: nowrap; border: 1px solid transparent;
  }
  .pill-amber { color: #FCD34D; background: rgba(251,191,36,0.12); border-color: rgba(251,191,36,0.35); }
  .pill-tan { color: #D6B98C; background: rgba(214,185,140,0.12); border-color: rgba(214,185,140,0.3); }
  .pill-purple { color: var(--purple); background: rgba(167,139,250,0.14); border-color: rgba(167,139,250,0.35); }

  .banner {
    font-size: 10px; font-weight: 700; padding: 6px 10px; border-radius: 8px;
    background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.38);
    color: #FDE68A; display: flex; justify-content: space-between; align-items: center; gap: 6px;
    flex-shrink: 0;
  }
  .banner-em {
    background: rgba(180,83,9,0.16); border-color: rgba(217,119,6,0.4); color: #FBBF24;
  }
  .banner .right { white-space: nowrap; color: #FCD34D; font-weight: 800; }

  /* —— 卡片格 —— */
  .grid2 {
    display: grid; grid-template-columns: 1fr 1fr; gap: 6px; flex-shrink: 0;
  }
  .cell {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 7px 8px; display: flex; flex-direction: column; gap: 3px; min-width: 0;
  }
  .k { font-size: 9.5px; font-weight: 700; color: var(--muted); }
  .v { font-size: 12px; font-weight: 800; line-height: 1.25; }
  .v.gold { color: var(--gold); }
  .v.cyan { color: var(--cyan); }
  .sub { font-size: 9px; color: var(--dim); font-weight: 600; line-height: 1.35; }
  .amber { color: var(--amber); }
  .green { color: var(--green); }
  .red { color: var(--red); }

  .bar {
    height: 5px; background: #0B1120; border: 1px solid #334155; border-radius: 999px; overflow: hidden; margin: 2px 0;
  }
  .bar > i {
    display: block; height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, #0EA5E9, #38BDF8);
  }
  .bar.gold > i { background: linear-gradient(90deg, #D97706, #FBBF24); }

  .pe-track {
    position: relative; height: 6px; margin: 6px 4px 2px 4px;
    background: #0B1120; border: 1px solid #475569; border-radius: 999px;
  }
  .pe-dot {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--cyan); border: 1.5px solid #fff;
    box-shadow: 0 0 8px rgba(56,189,248,0.9);
  }
  .pe-dot.amber-dot {
    background: var(--amber); box-shadow: 0 0 8px rgba(251,191,36,0.9);
  }
  .pe-labs {
    display: flex; justify-content: space-between; font-size: 8.5px;
    color: var(--muted); font-weight: 700; padding: 0 2px;
  }

  .sq-row {
    display: flex; align-items: center; gap: 5px; font-size: 9.5px; color: var(--muted); margin-top: 2px;
  }
  .sqs { display: inline-flex; gap: 2.5px; }
  .sq { width: 8px; height: 8px; border-radius: 2px; }
  .sq-b { background: #EF4444; }
  .sq-s { background: #10B981; }
  .sq-n { background: #475569; }

  .rev-line { font-size: 10px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: clip; }

  /* —— 中段防線 —— */
  .panel {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 8px 9px; flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; gap: 6px;
  }
  .panel-title { font-size: 10.5px; font-weight: 800; color: var(--muted); }

  .rail {
    position: relative; height: 42px; margin: 2px 2px 0 2px;
  }
  .rail-line {
    position: absolute; left: 0; right: 0; top: 20px; height: 3px;
    background: #1E293B; border-radius: 999px;
  }
  .mark {
    position: absolute; top: 0; transform: translateX(-50%);
    display: flex; flex-direction: column; align-items: center; width: 48px;
  }
  .mark .lab { font-size: 7.5px; font-weight: 700; color: var(--dim); white-space: nowrap; }
  .mark .tick {
    width: 2px; height: 12px; background: #64748B; margin-top: 6px; border-radius: 1px;
  }
  .mark .val { font-size: 8.5px; font-weight: 800; color: var(--muted); margin-top: 2px; }
  .mark.alt .lab { margin-top: 22px; order: 3; }
  .mark.alt .tick { margin-top: -2px; order: 1; }
  .mark.alt .val { margin-top: 0; order: 2; }
  .mark.now .lab, .mark.now .val { color: var(--green); }
  .mark.now .tick { background: var(--cyan); height: 16px; margin-top: 6px; width: 3px; }
  .mark.sup .lab, .mark.sup .val { color: var(--cyan); }
  .mark.sup .tick { background: var(--cyan); }
  .mark.res .lab, .mark.res .val { color: var(--red); }
  .mark.res .tick { background: var(--red); }
  .mark.broke .lab, .mark.broke .val { color: var(--amber); }
  .mark.broke .tick { background: var(--amber); }
  .mark .glow {
    position: absolute; top: 16px; width: 10px; height: 10px; border-radius: 50%;
    background: var(--amber); border: 1.5px solid #fff;
    box-shadow: 0 0 8px rgba(251,191,36,0.85); transform: translateX(-50%); left: 50%;
  }

  .stat4 {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px;
  }
  .stat4 .cell { padding: 5px 6px; gap: 2px; }
  .stat4 .v { font-size: 11px; }

  .duo {
    display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 6px; flex-shrink: 0;
  }
  .duo .cell { min-height: 78px; }
  .peer {
    font-size: 10.5px; font-weight: 700; display: flex; justify-content: space-between;
    align-items: center; gap: 4px; padding: 1px 0;
  }
  .peer .meta { color: var(--muted); font-weight: 600; }
  .spark {
    width: 36px; height: 14px; flex-shrink: 0;
  }
  .moat {
    font-size: 11px; font-weight: 700; line-height: 1.4; color: var(--text);
  }
  .moat .risk { color: var(--muted); font-weight: 600; margin-top: 4px; }

  .legend {
    text-align: center; font-size: 8.5px; color: var(--dim); flex-shrink: 0; line-height: 1.3;
  }
</style>
</head>
<body>
  <div class="phone">
    <div class="brand"><span class="dot"></span>Telegram Stock Bot</div>

    <div class="title-row">
      <div class="title-main">{{STATUS_ICON}} {{STATUS_LABEL}}｜{{TICKER}} {{NAME}}</div>
      <span class="tag">{{MARKET_TAG}}</span>
    </div>

    <div class="price-row">
      <div class="price-block">
        <div class="price mono">{{PRICE}}</div>
        <div class="chg mono">{{CHG}}</div>
      </div>
      <div class="pill-row">{{PILLS}}</div>
    </div>

    <div class="banner {{BANNER_CLS}}">
      <span>{{BANNER_LEFT}}</span>
      <span class="right mono">{{BANNER_RIGHT}}</span>
    </div>

    <div class="grid2">
      <div class="cell">
        <div class="k">{{EPS_K}}</div>
        <div class="v {{EPS_V_CLS}} mono">{{EPS_V}}</div>
        <div class="bar {{EPS_BAR_CLS}}"><i style="width:{{EPS_PCT}}%"></i></div>
        <div class="sub">{{EPS_SUB1}}<br>{{EPS_SUB2}}</div>
      </div>
      <div class="cell">
        <div class="k">未來 12 個月滾動本益比</div>
        <div class="v {{PE_V_CLS}} mono">{{PE_V}}</div>
        <div class="pe-track"><div class="pe-dot {{PE_DOT_CLS}}" style="left:{{PE_LEFT}}%"></div></div>
        <div class="pe-labs mono"><span>{{PE_MIN}}</span><span>{{PE_MID}}</span><span>{{PE_MAX}}</span></div>
      </div>
      <div class="cell">
        <div class="k">{{BL_K}}</div>
        <div class="v mono">{{BL_V}}</div>
        {{BL_BOTTOM}}
      </div>
      <div class="cell">
        <div class="k">營收達標進度＋撐壓</div>
        <div class="v rev-line mono">{{REV_LINE}}</div>
        <div class="bar {{REV_BAR_CLS}}"><i style="width:{{REV_PCT}}%"></i></div>
        <div class="sub mono"><span class="{{SUPPORT_CLS}}">{{SUPPORT_TEXT}}</span></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">{{MID_TITLE}}</div>
      <div class="rail">
        <div class="rail-line"></div>
        {{RAIL_MARKS}}
      </div>
      <div class="stat4">{{STAT4}}</div>
    </div>

    <div class="duo">
      <div class="cell">
        <div class="k">{{PEER_K}}</div>
        {{PEERS}}
      </div>
      <div class="cell">
        <div class="k">護城河與風險</div>
        <div class="moat">{{MOAT}}</div>
      </div>
    </div>

    <div class="legend">{{LEGEND}}</div>
  </div>
</body>
</html>
"""


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _sq(flags: Sequence[str]) -> str:
    m = {"B": "sq-b", "S": "sq-s", "N": "sq-n"}
    pads = (list(flags) + ["N"] * 5)[:5]
    return "".join(f'<span class="sq {m.get(x, "sq-n")}"></span>' for x in pads)


def _rail_html(marks: Sequence[dict]) -> str:
    """marks: label, value_text, pct 0-100, kind=now|sup|res|broke|plain, glow?, alt?"""
    parts = []
    for i, m in enumerate(marks):
        kind = str(m.get("kind") or "plain")
        cls = "mark"
        if kind in ("now", "sup", "res", "broke"):
            cls += f" {kind}"
        if m.get("alt") or (i % 2 == 1 and kind == "plain"):
            cls += " alt"
        pct = max(4.0, min(96.0, float(m.get("pct") or 50)))
        glow = '<div class="glow"></div>' if m.get("glow") else ""
        parts.append(
            f'<div class="{cls}" style="left:{pct:.1f}%;">'
            f'<div class="lab">{_esc(m.get("label"))}</div>'
            f'{glow}<div class="tick"></div>'
            f'<div class="val mono">{_esc(m.get("value_text"))}</div>'
            f"</div>"
        )
    return "".join(parts)


def _stat4_html(cells: Sequence[tuple]) -> str:
    out = []
    for k, v, cls in list(cells)[:4]:
        out.append(
            f'<div class="cell"><div class="k">{_esc(k)}</div>'
            f'<div class="v mono {cls}">{_esc(v)}</div></div>'
        )
    return "".join(out)


def _spark_svg(up: bool = True) -> str:
    color = "#34D399" if up else "#F87171"
    # simple polyline
    if up:
        pts = "0,12 6,9 12,10 18,6 24,7 30,3 36,4"
    else:
        pts = "0,3 6,5 12,4 18,8 24,7 30,11 36,12"
    return (
        f'<svg class="spark" viewBox="0 0 36 14" xmlns="http://www.w3.org/2000/svg">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round" points="{pts}"/></svg>'
    )


def _peers_html(rows: Sequence[dict]) -> str:
    parts = []
    for r in rows[:3]:
        spark = _spark_svg(bool(r.get("up", True))) if r.get("spark", True) else ""
        parts.append(
            f'<div class="peer"><span>{_esc(r.get("name"))}</span>'
            f'<span class="meta mono">{_esc(r.get("meta"))}</span>{spark}</div>'
        )
    return "".join(parts) or '<div class="sub">同族群對照待補</div>'


def render_flagship_from_view(view: Dict[str, Any]) -> str:
    """把已組好的 view dict 填進範本 HTML。"""
    pills = "".join(
        f'<span class="pill {c}">{_esc(t)}</span>' for t, c in (view.get("pills") or [])
    )
    bl_bottom = view.get("bl_bottom_html") or ""
    return (
        HTML_TEMPLATE.replace("{{STATUS_ICON}}", _esc(view.get("status_icon")))
        .replace("{{STATUS_LABEL}}", _esc(view.get("status_label")))
        .replace("{{TICKER}}", _esc(view.get("ticker")))
        .replace("{{NAME}}", _esc(view.get("name")))
        .replace("{{MARKET_TAG}}", _esc(view.get("market_tag")))
        .replace("{{PRICE}}", _esc(view.get("price")))
        .replace("{{CHG}}", _esc(view.get("chg")))
        .replace("{{PILLS}}", pills)
        .replace("{{BANNER_CLS}}", _esc(view.get("banner_cls") or ""))
        .replace("{{BANNER_LEFT}}", _esc(view.get("banner_left")))
        .replace("{{BANNER_RIGHT}}", _esc(view.get("banner_right")))
        .replace("{{EPS_K}}", _esc(view.get("eps_k")))
        .replace("{{EPS_V}}", _esc(view.get("eps_v")))
        .replace("{{EPS_V_CLS}}", _esc(view.get("eps_v_cls") or "gold"))
        .replace("{{EPS_BAR_CLS}}", _esc(view.get("eps_bar_cls") or "gold"))
        .replace("{{EPS_PCT}}", str(int(view.get("eps_pct") or 0)))
        .replace("{{EPS_SUB1}}", _esc(view.get("eps_sub1")))
        .replace("{{EPS_SUB2}}", _esc(view.get("eps_sub2")))
        .replace("{{PE_V}}", _esc(view.get("pe_v")))
        .replace("{{PE_V_CLS}}", _esc(view.get("pe_v_cls") or "cyan"))
        .replace("{{PE_DOT_CLS}}", _esc(view.get("pe_dot_cls") or ""))
        .replace("{{PE_LEFT}}", str(int(view.get("pe_left") or 50)))
        .replace("{{PE_MIN}}", _esc(view.get("pe_min")))
        .replace("{{PE_MID}}", _esc(view.get("pe_mid")))
        .replace("{{PE_MAX}}", _esc(view.get("pe_max")))
        .replace("{{BL_K}}", _esc(view.get("bl_k")))
        .replace("{{BL_V}}", _esc(view.get("bl_v")))
        .replace("{{BL_BOTTOM}}", bl_bottom)
        .replace("{{REV_LINE}}", _esc(view.get("rev_line")))
        .replace("{{REV_BAR_CLS}}", _esc(view.get("rev_bar_cls") or ""))
        .replace("{{REV_PCT}}", str(int(view.get("rev_pct") or 0)))
        .replace("{{SUPPORT_CLS}}", _esc(view.get("support_cls") or "amber"))
        .replace("{{SUPPORT_TEXT}}", _esc(view.get("support_text")))
        .replace("{{MID_TITLE}}", _esc(view.get("mid_title")))
        .replace("{{RAIL_MARKS}}", _rail_html(view.get("rail") or []))
        .replace("{{STAT4}}", _stat4_html(view.get("stat4") or []))
        .replace("{{PEER_K}}", _esc(view.get("peer_k")))
        .replace("{{PEERS}}", _peers_html(view.get("peers") or []))
        .replace("{{MOAT}}", view.get("moat_html") or "")
        .replace("{{LEGEND}}", _esc(view.get("legend")))
    )


def mock_view_listed_2383() -> Dict[str, Any]:
    """對齊使用者範本：2383 上市旗艦卡。"""
    f5 = ["S", "S", "S", "S", "S"]
    t5 = ["B", "B", "B", "B", "B"]
    bl_bottom = (
        f'<div class="sq-row"><span>外資</span><span class="sqs">{_sq(f5)}</span></div>'
        f'<div class="sq-row"><span>投信</span><span class="sqs">{_sq(t5)}</span></div>'
    )
    # 價尺：現價 3365 在左（低於半年低），其餘向右
    levels = [
        ("現價", 3365, "now"),
        ("半年低", 3820, "plain"),
        ("大量撐", 4160, "sup"),
        ("大量壓", 4475, "res"),
        ("60日高", 6470, "plain"),
    ]
    lo, hi = 3365, 6470
    rail = []
    for lab, val, kind in levels:
        rail.append(
            {
                "label": lab,
                "value_text": f"{val:,}",
                "pct": (val - lo) / (hi - lo) * 100.0,
                "kind": kind,
            }
        )
    return {
        "status_icon": "☆",
        "status_label": "等止穩",
        "ticker": "2383",
        "name": "台光電",
        "market_tag": "上市・AI高階CCL",
        "price": "3,365.00",
        "chg": "▼ -4.94%",
        "pills": [("投信護盤", "pill-amber"), ("外資賣", "pill-tan")],
        "banner_cls": "",
        "banner_left": "⚠️ 資金偏緊（台幣偏弱・外資賣超）｜多因素並存",
        "banner_right": "USD/TWD 32.95",
        "eps_k": "今年賺錢進度",
        "eps_v": "已賺 82.9 / 估 128 (65%)",
        "eps_v_cls": "cyan",
        "eps_bar_cls": "",
        "eps_pct": 65,
        "eps_sub1": "Q4: 10月✓・11-12待補",
        "eps_sub2": "Q3單季: 40.47元 (創高)",
        "pe_v": "21.4倍 (偏低)",
        "pe_v_cls": "cyan",
        "pe_dot_cls": "",
        "pe_left": int((21.4 - 20) / (32 - 20) * 100),
        "pe_min": "20x",
        "pe_mid": "26x",
        "pe_max": "32x",
        "bl_k": "目標價（正常／保守）＋近5日",
        "bl_v": "正常 4,950｜保守 3,960",
        "bl_bottom_html": bl_bottom,
        "rev_line": "10月244.7億 / 需265億 (92%)",
        "rev_bar_cls": "",
        "rev_pct": 92,
        "support_cls": "amber",
        "support_text": "▲破撐 4,160｜壓 4,475",
        "mid_title": "股價位置與防線（還原權息）",
        "rail": rail,
        "stat4": [
            ("60日回檔", "-48.0%", ""),
            ("月線乖離", "-25.0%", ""),
            ("殖利率", "0.7%(無底)", ""),
            ("溫度計", "22°C", "cyan"),
        ],
        "peer_k": "同族群對照 (CCL)",
        "peers": [
            {"name": "台光電", "meta": "21.4x (+203%)", "up": True, "spark": True},
            {"name": "台燿", "meta": "21.5x (+68%)", "up": True, "spark": True},
            {"name": "聯茂", "meta": "24.0x (+42%)", "up": False, "spark": True},
        ],
        "moat_html": (
            '<div>AI基板市占 &gt; 70%、M9量產</div>'
            '<div class="risk">風險：外資調節、無高息底</div>'
        ),
        "legend": "★可買 ☆等止穩 ⚠️興櫃量小｜5日籌碼(左→右)：🟥買 🟩賣｜估值≠買訊",
    }


def mock_view_emerging_3595() -> Dict[str, Any]:
    """對齊使用者範本：3595 興櫃旗艦卡。"""
    levels = [
        ("現增暫定", 400, "plain"),
        ("現價", 485, "broke"),
        ("前波平台", 561, "plain"),
        ("前高壓", 636, "plain"),
    ]
    lo, hi = 400, 636
    rail = []
    for lab, val, kind in levels:
        rail.append(
            {
                "label": lab,
                "value_text": str(val),
                "pct": (val - lo) / (hi - lo) * 100.0,
                "kind": kind,
                "glow": kind == "broke",
            }
        )
    return {
        "status_icon": "⚠️",
        "status_label": "興櫃量小",
        "ticker": "3595",
        "name": "山太士",
        "market_tag": "興櫃・先進封裝材料",
        "price": "485.00",
        "chg": "▼ -4.28%",
        "pills": [("興櫃無法人・60日量小", "pill-purple")],
        "banner_cls": "banner-em",
        "banner_left": "⚠️ 興櫃透明度較低｜無每日法人進出與融資數據",
        "banner_right": "2027/01 預計上櫃",
        "eps_k": "今年賺錢進度（已出 Q3）",
        "eps_v": "已賺 5.99 / 估 9.2 (65%)",
        "eps_v_cls": "gold",
        "eps_bar_cls": "gold",
        "eps_pct": 65,
        "eps_sub1": "Q4: 10月✅・11・12待補",
        "eps_sub2": "Q3單季: 2.97元",
        "pe_v": "28.0倍 (今年 52.7x 偏高)",
        "pe_v_cls": "gold",
        "pe_dot_cls": "amber-dot",
        "pe_left": int((28.0 - 20) / (32 - 20) * 100),
        "pe_min": "20x",
        "pe_mid": "26x",
        "pe_max": "32x",
        "bl_k": "目標價與現增防線",
        "bl_v": "正常 570｜保守 456",
        "bl_bottom_html": '<div class="sub amber">現增暫定 400元｜稀釋股本 4.68億</div>',
        "rev_line": "10月0.95億 / 年底1.05億 (90%)",
        "rev_bar_cls": "gold",
        "rev_pct": 90,
        "support_cls": "amber",
        "support_text": "▲破撐 561｜壓 636",
        "mid_title": "興櫃防線與流動性警示",
        "rail": rail,
        "stat4": [
            ("現增股數", "610萬股", ""),
            ("Q3毛利", "77.4%", "gold"),
            ("10月 MoM", "+2.9% 緩", ""),
            ("流動性", "⚠️ 價差大難出脫", "amber"),
        ],
        "peer_k": "同族群對照 (封裝材料)",
        "peers": [
            {"name": "山太士", "meta": "28.0x (興櫃)", "spark": False},
            {"name": "崇越", "meta": "17.8x (+19%)", "up": True, "spark": True},
            {"name": "華立", "meta": "14.2x (+15%)", "up": True, "spark": True},
        ],
        "moat_html": (
            '<div>先進封裝高毛利（淨利率 46.9%）</div>'
            '<div class="risk">風險：營收趨緩、量小折價</div>'
        ),
        "legend": "★可買 ☆等止穩 ⚠️興櫃量小｜興櫃不適用法人與融資指標｜估值≠買訊",
    }


def render_flagship_png_from_view(view: Dict[str, Any], save_path: str) -> str:
    page_html = render_flagship_from_view(view)
    out = str(save_path)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": VIEW_W, "height": VIEW_H},
            device_scale_factor=DPR,
        )
        page.set_content(page_html, wait_until="networkidle")
        page.screenshot(path=out, full_page=False)
        browser.close()
    return out


def main() -> None:
    out = Path("/opt/cursor/artifacts/lookup-flagship")
    out.mkdir(parents=True, exist_ok=True)
    p1 = render_flagship_png_from_view(
        mock_view_listed_2383(), str(out / "flagship_2383.png")
    )
    p2 = render_flagship_png_from_view(
        mock_view_emerging_3595(), str(out / "flagship_3595.png")
    )
    print(p1, os.path.getsize(p1))
    print(p2, os.path.getsize(p2))


if __name__ == "__main__":
    main()
