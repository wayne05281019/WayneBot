# -*- coding: utf-8 -*-
# ==============================================================================
# 查股「一頁式個股旗艦卡」——多插在查股相簿第一張；不准改既有高低卡／介紹／結構／大量／走勢。
# 嚴禁 Pillow／matplotlib；HTML/CSS + Playwright 430×932 @3x → 1290×2796。
# 版面以使用者核定 mock 為準（上市櫃／興櫃雙模式）。
# ==============================================================================
from __future__ import annotations

import html
import json
import math
import os
import re
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    --line: #1E293B;
    --text: #F8FAFC;
    --mute: #94A3B8;
    --dim: #64748B;
    --up: #F87171;
    --dn: #34D399;
    --cyan: #38BDF8;
    --amber: #FBBF24;
    --gold: #EAB308;
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
    padding: 48px 14px 60px 14px;
    display: flex; flex-direction: column; gap: 6px; overflow: hidden;
  }

  /* —— 標題列：左狀態名、右大價 —— */
  .head {
    display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; flex-shrink: 0;
  }
  .head-left { min-width: 0; flex: 1 1 auto; }
  .head-title {
    font-size: 13.5px; font-weight: 900; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .head-price {
    text-align: right; flex: 0 0 auto; line-height: 1.05;
  }
  .head-price .px { font-size: 20px; font-weight: 900; }
  .head-price .chg { font-size: 12px; font-weight: 800; }
  .chg-up { color: var(--up); } .chg-dn { color: var(--dn); }

  .pills {
    display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;
  }
  .pill {
    font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 999px;
    border: 1px solid #334155; color: var(--mute); background: rgba(15,23,42,.65);
    white-space: nowrap;
  }
  .pill-chip { color: #FDE68A; border-color: rgba(234,179,8,.45); background: rgba(234,179,8,.12); }
  .pill-warn { color: var(--purple); border-color: rgba(167,139,250,.4); background: rgba(167,139,250,.14); }
  .pill-sell { color: var(--dn); border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.12); }
  .pill-buy { color: var(--up); border-color: rgba(248,113,113,.35); background: rgba(248,113,113,.12); }

  .banner {
    font-size: 10px; font-weight: 700; padding: 6px 10px; border-radius: 9px;
    display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-shrink: 0;
  }
  .banner-fx { background: rgba(245,158,11,.12); border: 1px solid rgba(245,158,11,.42); color: #FDE68A; }
  .banner-em { background: rgba(234,179,8,.10); border: 1px solid rgba(234,179,8,.40); color: #FDE68A; }
  .banner-ok { background: rgba(52,211,153,.10); border: 1px solid rgba(52,211,153,.35); color: #A7F3D0; }
  .banner-bear { background: rgba(248,113,113,.10); border: 1px solid rgba(248,113,113,.4); color: #FECACA; }

  .panel {
    flex: 1 1 0; min-height: 0; overflow: hidden;
    display: flex; flex-direction: column; gap: 6px;
  }

  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; flex-shrink: 0; }
  .cell {
    background: var(--card); border: 1px solid var(--line); border-radius: 11px;
    padding: 7px 8px; display: flex; flex-direction: column; gap: 3px; min-height: 0; overflow: hidden;
  }
  .cell.b-purple { border-color: rgba(167,139,250,.45); }
  .cell.b-cyan { border-color: rgba(56,189,248,.45); }
  .cell.b-gold { border-color: rgba(234,179,8,.45); }
  .cell.b-amber { border-color: rgba(251,191,36,.45); }
  .k { font-size: 9.5px; font-weight: 800; color: var(--mute); }
  .v { font-size: 12px; font-weight: 800; line-height: 1.25; }
  .v.lg { font-size: 13.5px; color: var(--gold); }
  .v.cyan { color: var(--cyan); }
  .v.rev { font-size: 10.5px; letter-spacing: -0.02em; }
  .v .note { font-size: 9.5px; font-weight: 700; color: var(--mute); }
  .sub { font-size: 9.5px; color: var(--dim); font-weight: 600; line-height: 1.3; }
  .sub.amber, .amber { color: var(--amber); font-weight: 800; }
  .nowrap { white-space: nowrap; overflow: hidden; text-overflow: clip; }

  .bar { height: 5px; background: #0B1120; border: 1px solid #334155; border-radius: 999px; overflow: hidden; margin-top: 2px; }
  .bar > i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg,#10B981,#38BDF8); }
  .bar.amber > i { background: linear-gradient(90deg,#F59E0B,#FBBF24); }

  .ruler { margin-top: 4px; }
  .ruler-track {
    position: relative; height: 7px; margin: 6px 4px 0;
    background: #0B1120; border: 1px solid #64748B; border-radius: 999px;
  }
  .ruler-dot {
    position: absolute; top: 50%; transform: translate(-50%,-50%);
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--cyan); border: 1.5px solid #fff; box-shadow: 0 0 7px rgba(56,189,248,.9);
  }
  .ruler-dot.hot { background: var(--amber); box-shadow: 0 0 7px rgba(251,191,36,.9); }
  .ruler-labs {
    display: flex; justify-content: space-between; font-size: 9px; font-weight: 700;
    color: var(--mute); padding: 2px 2px 0;
  }

  .chips { display: flex; flex-direction: column; gap: 3px; margin-top: 2px; }
  .chip-row { display: flex; align-items: center; gap: 5px; font-size: 9.5px; color: var(--mute); font-weight: 700; }
  .sqs { display: inline-flex; gap: 2.5px; }
  .sq { width: 8px; height: 8px; border-radius: 1.5px; }
  .sq-b { background: #EF4444; } .sq-s { background: #10B981; } .sq-n { background: #475569; }

  .block {
    background: var(--card); border: 1px solid var(--line); border-radius: 11px;
    padding: 7px 9px; flex-shrink: 0;
  }
  .block-title { font-size: 10px; font-weight: 900; color: var(--mute); margin-bottom: 4px; }

  .rail {
    position: relative; height: 42px; margin: 2px 2px 4px;
  }
  .rail-line {
    position: absolute; left: 0; right: 0; top: 20px; height: 3px;
    background: #0B1120; border: 1px solid #334155; border-radius: 999px;
  }
  .mk {
    position: absolute; top: 0; transform: translateX(-50%);
    display: flex; flex-direction: column; align-items: center; width: 64px;
  }
  .mk .lab { font-size: 8px; font-weight: 800; color: var(--dim); white-space: nowrap; }
  .mk .tick { width: 2px; height: 10px; background: #64748B; margin-top: 10px; border-radius: 1px; }
  .mk .val { font-size: 9px; font-weight: 800; color: var(--mute); margin-top: 2px; }
  .mk.now .lab, .mk.now .val { color: var(--cyan); }
  .mk.now .tick { background: var(--cyan); height: 14px; margin-top: 8px; box-shadow: 0 0 6px rgba(56,189,248,.8); }
  .mk.broke .lab, .mk.broke .val { color: var(--amber); }
  .mk.broke .tick { background: var(--amber); }
  .mk.up .lab, .mk.up .val { color: var(--up); }
  .mk.up .tick { background: var(--up); }
  .mk.dn .lab, .mk.dn .val { color: var(--dn); }
  .mk.dn .tick { background: var(--dn); }

  .stat4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 5px; }
  .stat4 .cell { padding: 5px 6px; min-height: 44px; }
  .stat4 .v { font-size: 11px; }
  .stat4 .v.warn { color: var(--amber); font-size: 10px; }

  .duo { display: grid; grid-template-columns: 1.1fr .9fr; gap: 6px; flex: 1 1 0; min-height: 0; }
  .duo .cell { min-height: 88px; }
  .peer { font-size: 10.5px; font-weight: 700; line-height: 1.45; }
  .peer span { color: var(--mute); font-weight: 600; }
  .peer .spark { color: var(--dn); }
  .peer .spark.down { color: var(--up); }
  .moat { font-size: 11px; font-weight: 700; line-height: 1.4; color: var(--text); }
  .moat b { color: var(--cyan); font-weight: 800; }
  .moat .risk { color: var(--amber); }

  .foot {
    text-align: center; font-size: 8.5px; color: var(--dim); font-weight: 600;
    line-height: 1.35; flex-shrink: 0; padding-top: 1px;
  }
</style>
</head>
<body>
  <div class="phone">
    <div class="head">
      <div class="head-left">
        <div class="head-title">{{HEAD_TITLE}}</div>
        <div class="pills">{{PILLS}}</div>
      </div>
      <div class="head-price mono">
        <div class="px {{CHG_CLS}}">{{PRICE}}</div>
        <div class="chg {{CHG_CLS}}">{{CHG}}</div>
      </div>
    </div>

    <div class="banner {{BANNER_CLS}}">
      <span>{{BANNER_TEXT}}</span>
      <span class="mono">{{BANNER_RIGHT}}</span>
    </div>

    <div class="panel">
      <div class="grid2">
        <div class="cell b-purple">
          <div class="k">{{EPS_K}}</div>
          <div class="v mono">已賺 {{EPS_YTD}} / 估 {{EPS_EST}} ({{EPS_PCT}}%)</div>
          <div class="bar {{EPS_BAR_CLS}}"><i style="width:{{EPS_BAR}}%"></i></div>
          <div class="sub">{{Q4_LINE}}</div>
          <div class="sub">{{EPS_Q_LINE}}</div>
        </div>
        <div class="cell b-cyan">
          <div class="k">未來 12 個月滾動本益比</div>
          <div class="v cyan mono">{{PE_LINE}}</div>
          <div class="ruler">
            <div class="ruler-track"><div class="ruler-dot {{PE_DOT_CLS}}" style="left:{{PE_LEFT}}%;"></div></div>
            <div class="ruler-labs mono"><span>{{PE_MIN}}</span><span>{{PE_MID}}</span><span>{{PE_MAX}}</span></div>
          </div>
        </div>
        <div class="cell b-gold">
          <div class="k">{{BL_K}}</div>
          <div class="v lg mono">正常 {{TGT_N}}｜保守 {{TGT_C}}</div>
          {{BL_BOTTOM}}
        </div>
        <div class="cell b-amber">
          <div class="k">營收達標進度＋撐壓</div>
          <div class="v rev mono nowrap">{{REV_LINE}}</div>
          <div class="bar {{REV_BAR_CLS}}"><i style="width:{{REV_BAR}}%"></i></div>
          <div class="sub mono"><span class="{{SR_CLS}}">{{SR_TEXT}}</span></div>
        </div>
      </div>

      <div class="block">
        <div class="block-title">{{MID_TITLE}}</div>
        <div class="rail">
          <div class="rail-line"></div>
          {{RAIL}}
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
    </div>

    <div class="foot">{{FOOT}}</div>
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
    if abs(x) >= 1000:
        return f"{x:,.0f}" if abs(x - round(x)) < 1e-6 else f"{x:,.1f}"
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
    "2383": ("6274", "6213"),  # 台燿、聯茂
    "3595": ("5434", "3010"),  # 崇越、華立（封裝材料對照）
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
    if not fund:
        return out

    bucket = industry_bucket(chain, (), name)
    pe_y, pe_n, _ = select_fair_pe_pair(25.0, bucket)
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
    if industry:
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
    support = resist = half_low = high60 = ma60 = None
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
                eps_q = soft.get("eps_q")
                gm = gm if gm is not None else soft.get("gm")
                if eps_y is None:
                    eps_y = soft.get("eps_y")
                if eps_n is None:
                    eps_n = soft.get("eps_n")
                if pe_y is None:
                    pe_y = soft.get("pe_y")
                if pe_n is None:
                    pe_n = soft.get("pe_n")
                if fair is None:
                    fair = soft.get("fair")
                if tgt is None:
                    tgt = soft.get("tgt")
                if thr is None:
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
        finally:
            con2.close()
    except Exception:
        pass

    broke = close is not None and support is not None and close < support
    qty60 = None
    if bars:
        vols = [float(b[4] or 0) for b in bars[-60:]]
        if vols:
            qty60 = sum(vols) / len(vols) / 1000.0

    if emerging:
        status, icon, status_label = "risk", "⚠️", "興櫃量小"
    elif broke:
        status, icon, status_label = "wait", "☆", "等止穩"
    else:
        status, icon, status_label = "buy", "★", "可買"

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
        if emerging:
            rev_line = f"{month_lab} {_fmt_yi(rev_yi)}億 / 年底 {_fmt_yi(thr)}億 ({rev_pct}%)"
        else:
            rev_line = f"{month_lab} {_fmt_yi(rev_yi)} / 需{_fmt_yi(thr)}億 ({rev_pct}%)"
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
        mom_s = f"{month_lab} MoM {mom_pct:+.1f}% 緩" if mom_pct is not None else "近月 MoM —"
        shares_s = f"現增 {place_shares:.0f}萬股" if place_shares is not None else "現增 —"
        gm_lab = f"Q{season_used or 3}毛利"
        stat4 = [
            ("現增股數", shares_s, ""),
            (gm_lab, f"{gm:.1f}%" if gm is not None else "—", ""),
            ("營收月增", mom_s, ""),
            ("流動性", "⚠️ 價差大難出脫", "warn"),
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
        if half_low is not None and close is not None:
            # 太靠近現價會跟標籤互壓，略過
            if abs(float(half_low) - float(close)) / float(close) >= 0.05:
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
        bias = (
            (close - ma60) / ma60 * 100.0
            if close is not None and ma60 not in (None, 0)
            else None
        )
        temp = "—"
        if close is not None and half_low is not None and high60 is not None and high60 > half_low:
            temp = f"{(close - half_low) / (high60 - half_low) * 100:.0f}°C"
        stat4 = [
            ("60日回檔", f"{pull:+.1f}%" if pull is not None else "—", ""),
            ("月線乖離", f"{bias:+.1f}%" if bias is not None else "—", ""),
            ("殖利率", "—（無底）", ""),
            ("溫度計", temp, ""),
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

    if not moat_html:
        if emerging:
            gm_s = f"{gm:.1f}%" if gm is not None else "—"
            moat_html = (
                f"先進封裝高毛利<span>（毛利 {html.escape(gm_s)}）</span>"
                f"｜<span class=\"risk\">風險：營收趨緩、量小折價</span>"
            )
        else:
            moat_html = (
                f"<b>{html.escape(short_ind or industry or '本業')}</b>"
                f"｜<span class=\"risk\">風險：景氣／客戶集中與估值波動</span>"
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
    }


def render_flagship_html(p: Dict[str, Any]) -> str:
    pill_bits = []
    for cls, txt in p.get("pills") or []:
        c = f" {cls}" if cls else ""
        pill_bits.append(f'<span class="pill{c}">{html.escape(str(txt))}</span>')
    pills = "".join(pill_bits)
    head = (
        f'{html.escape(p["icon"])} {html.escape(p["status_label"])}｜'
        f'{html.escape(p["stock_id"])} {html.escape(p["name"])}'
    )
    if p.get("close") is not None:
        price = f"{float(p['close']):,.2f}"
    else:
        price = "—"

    pe_left = max(8, min(92, int(round(float(p.get("pe_dot") or 50)))))
    eps_bar = min(100, int(p.get("eps_pct") or 0))
    rev_bar = min(100, int(p.get("rev_pct") or 0))
    bar_cls = "amber" if p.get("bar_amber") else ""
    sr_cls = "amber" if p.get("broke") else ""

    reg = p.get("regime") or {}
    return (
        HTML_TEMPLATE.replace("{{HEAD_TITLE}}", head)
        .replace("{{PILLS}}", pills)
        .replace("{{PRICE}}", html.escape(price))
        .replace("{{CHG}}", html.escape(str(p.get("chg_txt") or "")))
        .replace("{{CHG_CLS}}", html.escape(str(p.get("chg_cls") or "chg-dn")))
        .replace("{{BANNER_CLS}}", html.escape(str(reg.get("cls") or "banner-ok")))
        .replace("{{BANNER_TEXT}}", html.escape(str(reg.get("text") or "")))
        .replace("{{BANNER_RIGHT}}", html.escape(str(reg.get("right") or "")))
        .replace("{{EPS_K}}", html.escape(str(p.get("eps_k") or "")))
        .replace(
            "{{EPS_YTD}}",
            html.escape(
                _fmt_num(p.get("eps_e"), 2 if (_finite(p.get("eps_e")) or 99) < 10 else 1)
            ),
        )
        .replace("{{EPS_EST}}", html.escape(_fmt_num(p.get("eps_y"), 1)))
        .replace("{{EPS_PCT}}", str(int(p.get("eps_pct") or 0)))
        .replace("{{EPS_BAR}}", str(eps_bar))
        .replace("{{EPS_BAR_CLS}}", bar_cls)
        .replace("{{Q4_LINE}}", html.escape(str(p.get("q4") or "")))
        .replace("{{EPS_Q_LINE}}", html.escape(str(p.get("eps_q_line") or "")))
        .replace("{{PE_LINE}}", html.escape(str(p.get("pe_line") or "—")))
        .replace("{{PE_LEFT}}", str(pe_left))
        .replace("{{PE_DOT_CLS}}", "hot" if p.get("pe_hot") else "")
        .replace("{{PE_MIN}}", html.escape(str(p.get("pe_min") or "—")))
        .replace("{{PE_MID}}", html.escape(str(p.get("pe_mid") or "—")))
        .replace("{{PE_MAX}}", html.escape(str(p.get("pe_max") or "—")))
        .replace("{{BL_K}}", html.escape(str(p.get("bl_k") or "")))
        .replace("{{TGT_N}}", html.escape(str(p.get("tgt_n") or "—")))
        .replace("{{TGT_C}}", html.escape(str(p.get("tgt_c") or "—")))
        .replace("{{BL_BOTTOM}}", str(p.get("bl_bottom") or ""))
        .replace("{{REV_LINE}}", html.escape(str(p.get("rev_line") or "—")))
        .replace("{{REV_BAR}}", str(rev_bar))
        .replace("{{REV_BAR_CLS}}", bar_cls)
        .replace("{{SR_CLS}}", sr_cls)
        .replace("{{SR_TEXT}}", html.escape(str(p.get("sr_text") or "")))
        .replace("{{MID_TITLE}}", html.escape(str(p.get("mid_title") or "")))
        .replace("{{RAIL}}", _rail_html(p.get("marks") or []))
        .replace("{{STAT4}}", _stat4_html(p.get("stat4") or []))
        .replace("{{PEER_K}}", html.escape(str(p.get("peer_k") or "")))
        .replace("{{PEERS}}", str(p.get("peers_html") or ""))
        .replace("{{MOAT}}", str(p.get("moat_html") or ""))
        .replace("{{FOOT}}", html.escape(str(p.get("foot") or "")))
    )


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
    page_html = render_flagship_html(data)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=DPR
        )
        page.set_content(page_html, wait_until="networkidle")
        page.screenshot(path=str(save_path), full_page=False)
        browser.close()
    return save_path


def main() -> None:
    db = os.environ.get("WAYNE_DB_PATH") or "data/wayne_market.db"
    out = "/opt/cursor/artifacts/lookup-flagship"
    os.makedirs(out, exist_ok=True)
    for sid in ("2383", "3595", "6442"):
        path = os.path.join(out, f"flagship_{sid}.png")
        render_flagship_png(sid, path, db_path=db, as_of="20261118")
        print(path, os.path.getsize(path))


if __name__ == "__main__":
    main()
