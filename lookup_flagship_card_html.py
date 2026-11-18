# -*- coding: utf-8 -*-
# ==============================================================================
# 查股「一頁式個股旗艦卡」——多插在查股相簿第一張；不准改既有高低卡／介紹／結構／大量／走勢。
# 嚴禁 Pillow／matplotlib；HTML/CSS + Playwright 430×932 @3x → 1290×2796。
# 視覺對齊低估 D3（#0B1120／#151E32／玻璃擬態）；數據接真庫，不准寫死假數。
# ==============================================================================
from __future__ import annotations

import html
import json
import math
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from playwright.sync_api import sync_playwright

VIEW_W = 430
VIEW_H = 932
DPR = 3
OUT_W = VIEW_W * DPR
OUT_H = VIEW_H * DPR

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
    display: flex; flex-direction: column; gap: 5px; overflow: hidden;
  }
  .mono { font-family: 'JetBrains Mono', 'Noto Sans TC', monospace; font-variant-numeric: tabular-nums; }
  .head-row {
    display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-shrink: 0;
  }
  .head-main {
    font-size: 12.5px; font-weight: 900; min-width: 0; flex: 1 1 auto;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .chg-up { color: var(--tw-up); } .chg-down { color: var(--tw-down); }
  .flow-pill {
    font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 999px;
    white-space: nowrap; flex: 0 0 auto; max-width: 38%; overflow: hidden; text-overflow: ellipsis;
  }
  .flow-buy { background: rgba(248, 113, 113, 0.16); color: var(--tw-up); border: 1px solid rgba(248, 113, 113, 0.3); }
  .flow-sell { background: rgba(52, 211, 153, 0.15); color: var(--tw-down); border: 1px solid rgba(52, 211, 153, 0.3); }
  .flow-warn { background: rgba(167, 139, 250, 0.18); color: var(--purple); border: 1px solid rgba(167, 139, 250, 0.35); }

  .regime-banner {
    font-size: 10px; font-weight: 700; padding: 5px 9px; border-radius: 8px;
    display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; gap: 6px;
  }
  .regime-normal { background: rgba(52, 211, 153, 0.12); border: 1px solid rgba(52, 211, 153, 0.35); color: #A7F3D0; }
  .regime-fx { background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.42); color: #FDE68A; }
  .regime-bear { background: rgba(248, 113, 113, 0.12); border: 1px solid rgba(248, 113, 113, 0.42); color: #FECACA; }
  .regime-em { background: rgba(167, 139, 250, 0.14); border: 1px solid rgba(167, 139, 250, 0.4); color: #DDD6FE; }

  .panel {
    background: var(--bg-card); border: 1px solid var(--border-subtle);
    border-radius: 12px; padding: 7px 8px; display: flex; flex-direction: column; gap: 5px;
    flex: 1 1 0; min-height: 0; overflow: hidden;
  }
  .panel.status-buy { border-color: rgba(52, 211, 153, 0.5); }
  .panel.status-wait { border-color: rgba(251, 191, 36, 0.45); }
  .panel.status-risk { border-color: rgba(167, 139, 250, 0.5); }

  .d3-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; flex: 0 0 auto; }
  .d3-cell {
    background: #151E32; border: 1px solid #1E293B; border-radius: 8px;
    padding: 5px 7px; display: flex; flex-direction: column; justify-content: space-between; gap: 2px;
    min-height: 0; overflow: hidden;
  }
  .cell-k { font-size: 9px; color: var(--text-secondary); font-weight: 700; }
  .cell-v { font-size: 10.5px; font-weight: 700; color: var(--text-primary); line-height: 1.25; }
  .cell-v.rev-line { font-size: 9.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cell-sub { font-size: 9px; color: var(--text-muted); }
  .up { color: var(--tw-up); } .down { color: var(--tw-down); }
  .cyan { color: var(--cyan); } .amber { color: var(--amber); }

  .prog-track { height: 4px; background: #0B1120; border: 1px solid #334155; border-radius: 999px; overflow: hidden; }
  .prog-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #10B981, #38BDF8); }
  .prog-fill-amber { background: linear-gradient(90deg, #F59E0B, #FBBF24); }

  .ruler-wrap { display: flex; flex-direction: column; gap: 2px; margin-top: 1px; }
  .ruler-track {
    position: relative; height: 6px; background: #0B1120;
    border: 1px solid #64748B; border-radius: 999px; margin: 3px 4px 0 4px;
  }
  .ruler-dot {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 9px; height: 9px; border-radius: 50%; background: #38BDF8;
    border: 1.5px solid #FFF; box-shadow: 0 0 6px rgba(56, 189, 248, 0.85);
  }
  .ruler-labels {
    display: flex; justify-content: space-between; font-size: 8.5px;
    color: var(--text-secondary); font-weight: 700; padding: 0 2px;
  }

  .flow-blocks-row { display: flex; align-items: center; gap: 4px; font-size: 9px; color: var(--text-secondary); flex-wrap: nowrap; }
  .sq-group { display: inline-flex; gap: 2px; align-items: center; }
  .sq { width: 7px; height: 7px; border-radius: 1.5px; display: inline-block; flex-shrink: 0; }
  .sq-b { background: #EF4444; } .sq-s { background: #10B981; } .sq-n { background: #475569; }

  .section-k { font-size: 9.5px; font-weight: 800; color: var(--text-secondary); margin-bottom: 3px; }
  .price-rail {
    position: relative; height: 28px; margin: 4px 2px 2px 2px;
  }
  .price-rail-track {
    position: absolute; left: 0; right: 0; top: 14px; height: 4px;
    background: #0B1120; border: 1px solid #334155; border-radius: 999px;
  }
  .rail-mark {
    position: absolute; top: 0; transform: translateX(-50%);
    display: flex; flex-direction: column; align-items: center; gap: 1px;
  }
  .rail-mark .tick { width: 2px; height: 10px; background: #64748B; border-radius: 1px; margin-top: 10px; }
  .rail-mark.now .tick { background: #38BDF8; height: 14px; margin-top: 8px; }
  .rail-mark.broke .tick { background: #FBBF24; }
  .rail-lab { font-size: 7.5px; color: var(--text-muted); font-weight: 700; white-space: nowrap; }
  .rail-mark.now .rail-lab { color: var(--cyan); }
  .rail-val { font-size: 8px; color: var(--text-secondary); font-weight: 700; }

  .stat4 {
    display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 4px; margin-top: 4px;
  }
  .stat4 .d3-cell { padding: 4px 5px; }
  .stat4 .cell-v { font-size: 10px; }

  .bottom-duo {
    display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 5px; margin-top: 2px; flex: 1 1 0; min-height: 0;
  }
  .bottom-duo .d3-cell { min-height: 72px; }
  .peer-line { font-size: 9.5px; font-weight: 600; color: var(--text-primary); line-height: 1.35; }
  .peer-line span { color: var(--text-muted); font-weight: 500; }
  .moat-text { font-size: 10px; font-weight: 600; color: var(--text-primary); line-height: 1.35; }

  .footer-legend {
    text-align: center; font-size: 8.5px; color: var(--text-muted); padding-top: 1px; flex-shrink: 0;
    line-height: 1.3;
  }
  .meta-line { font-size: 9.5px; color: var(--text-secondary); font-weight: 600; margin-top: -2px; }
</style>
</head>
<body>
  <div class="phone-frame">
    <div class="head-row">
      <div class="head-main">{{HEAD_MAIN}}</div>
      <span class="flow-pill {{FLOW_CLS}}">{{FLOW_PILL}}</span>
    </div>
    <div class="meta-line">{{META_LINE}}</div>
    <div class="regime-banner {{REGIME_CLASS}}">
      <span>{{REGIME_TEXT}}</span>
      <span class="mono">{{FX_TEXT}}</span>
    </div>
    <div class="panel status-{{STATUS}}">
      <div class="d3-grid">
        <div class="d3-cell">
          <div class="cell-k">{{EPS_TITLE}}</div>
          <div class="cell-v mono">已賺 {{EPS_YTD}} / 估 {{EPS_EST}} ({{EPS_PCT}}%)</div>
          <div class="prog-track"><div class="prog-fill {{BAR_CLS}}" style="width: {{EPS_BAR}}%;"></div></div>
          <div class="cell-sub">{{Q4_OR_HALF}}｜最新單季 {{EPS_Q}}</div>
        </div>
        <div class="d3-cell">
          <div class="cell-k">未來 12 個月滾動本益比</div>
          <div class="cell-v mono cyan">{{PE_FWD}}倍 <span class="cell-sub">({{PE_NOTE}})</span></div>
          <div class="ruler-wrap">
            <div class="ruler-track"><div class="ruler-dot" style="left: {{PE_LEFT}}%;"></div></div>
            <div class="ruler-labels mono"><span>{{PE_MIN}}</span><span>{{PE_MID}}</span><span>{{PE_MAX}}</span></div>
          </div>
        </div>
        <div class="d3-cell">
          <div class="cell-k">{{BL_TITLE}}</div>
          <div class="cell-v mono">正常 {{TGT_NORM}}｜保守 {{TGT_CONS}}</div>
          {{BL_BOTTOM}}
        </div>
        <div class="d3-cell">
          <div class="cell-k">營收達標進度＋撐壓</div>
          <div class="cell-v mono rev-line">{{REV_LINE}}</div>
          <div class="prog-track"><div class="prog-fill {{BAR_CLS}}" style="width: {{REV_BAR}}%;"></div></div>
          <div class="cell-sub mono"><span class="{{SUPPORT_CLS}}">{{SUPPORT_TEXT}}</span></div>
        </div>
      </div>

      <div>
        <div class="section-k">股價位置與防線（還原權息）</div>
        <div class="price-rail">
          <div class="price-rail-track"></div>
          {{RAIL_MARKS}}
        </div>
        <div class="stat4">{{STAT4}}</div>
      </div>

      <div class="bottom-duo">
        <div class="d3-cell">
          <div class="cell-k">同族群代表對照</div>
          {{PEERS_HTML}}
        </div>
        <div class="d3-cell">
          <div class="cell-k">護城河與最大風險</div>
          <div class="moat-text">{{MOAT_TEXT}}</div>
        </div>
      </div>
    </div>
    <div class="footer-legend">{{LEGEND}}</div>
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


def _fmt_yi_num(v: float) -> str:
    if abs(float(v)) < 10:
        return f"{float(v):.2f}".rstrip("0").rstrip(".")
    return _fmt_num(v, 1)


def calc_forward_12m_eps(
    eps_this_year: float, eps_next_year: float, ref_date: date | None = None
) -> float:
    d = ref_date or date.today()
    months_left = max(0, 12 - d.month + 1)
    w_this = months_left / 12.0
    return round(eps_this_year * w_this + eps_next_year * (1.0 - w_this), 2)


def detect_market_regime_neutral(
    usd_twd: float, foreign_sell_days: int, market_above_ma20: bool
) -> dict:
    """中性客觀橫幅：不准寫「非基本面轉壞」這類絕對句。"""
    fx = f"USD/TWD {usd_twd:.2f}"
    if usd_twd >= 32.8 and foreign_sell_days >= 2 and not market_above_ma20:
        return {
            "class": "regime-fx",
            "text": "⚠️ 資金偏緊（台幣偏弱・外資賣超）｜多因素並存",
            "fx_text": fx,
        }
    if not market_above_ma20 and foreign_sell_days >= 3:
        return {
            "class": "regime-bear",
            "text": "⚠️ 大盤偏弱（站下 MA20・外資連賣）｜多因素並存",
            "fx_text": fx,
        }
    return {
        "class": "regime-normal",
        "text": "資金水位中性｜依區間與支撐操作",
        "fx_text": fx,
    }


def _net_to_flag(v: float) -> str:
    if v > 0:
        return "B"
    if v < 0:
        return "S"
    return "N"


def _normalize_5d(raw: Any) -> List[str]:
    if isinstance(raw, (list, tuple)) and raw:
        out = []
        for x in raw[:5]:
            s = str(x or "N").upper()[:1]
            out.append(s if s in ("B", "S", "N") else "N")
        return (out + ["N"] * 5)[:5]
    return ["N"] * 5


def _render_5day_squares(flags: Sequence[str]) -> str:
    padded = (list(flags) + ["N"] * 5)[:5]
    cls_map = {"B": "sq-b", "S": "sq-s", "N": "sq-n"}
    return "".join(f'<span class="sq {cls_map.get(x, "sq-n")}"></span>' for x in padded)


def _streak(flags: Sequence[str], want: str) -> int:
    n = 0
    for x in reversed(list(flags)[:5]):
        if str(x).upper()[:1] != want:
            break
        n += 1
    return n


def _pill_from_5d(f5: Sequence[str], t5: Sequence[str], *, emerging: bool) -> Tuple[str, str]:
    if emerging:
        return "warn", "興櫃無法人"
    f5 = _normalize_5d(f5)
    t5 = _normalize_5d(t5)
    f_sell = sum(1 for x in f5 if x == "S")
    t_buy = sum(1 for x in t5 if x == "B")
    tb, fb = _streak(t5, "B"), _streak(f5, "B")
    nf, nt = f5[-1], t5[-1]
    if nf == "S" and nt == "S":
        return "sell", "外投同賣"
    if nf == "B" and nt == "B":
        return "buy", "外投同買"
    if t_buy >= 2 and f_sell >= 2 and nt == "B":
        return "sell", "投信護盤・外資賣"
    if tb >= 2:
        return "buy", f"投信連買{tb}日"
    if fb >= 2:
        return "buy", f"外資連買{fb}日"
    if nt == "B" and nf == "S":
        return "sell", "投信護盤・外資賣"
    if nf == "B":
        return "buy", "外資買超"
    if f_sell >= 2 or sum(1 for x in t5 if x == "S") >= 2:
        return "sell", "法人調節"
    return "buy", "—"


def _q4_from_yyyymm(yyyymm: Optional[str]) -> str:
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


def _pe_scale(
    pe: Optional[float], fair_lo: Optional[float], fair_hi: Optional[float]
) -> Tuple[str, str, str, float]:
    vals = [v for v in (pe, fair_lo, fair_hi) if v is not None and v > 0]
    if not vals:
        return "—", "—", "—", 50.0
    lo, hi = float(min(vals)), float(max(vals))
    pad = max((hi - lo) * 0.2, 1.5)
    a0 = max(1.0, math.floor(lo - pad))
    a2 = math.ceil(hi + pad)
    if a2 <= a0:
        a2 = a0 + 5
    a1 = round((a0 + a2) / 2.0)
    pct = 50.0
    if pe is not None and a2 > a0:
        pct = max(8.0, min(92.0, (float(pe) - a0) / (a2 - a0) * 100.0))
    return f"{int(a0)}x", f"{int(a1)}x", f"{int(a2)}x", pct


def _chip_days(con: sqlite3.Connection, day: str, n: int = 5) -> List[str]:
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-','') AS d
            FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
            GROUP BY d
            HAVING SUM(ABS(COALESCE(foreign_net,0)))+SUM(ABS(COALESCE(trust_net,0)))>0
            ORDER BY d DESC LIMIT ?
            """,
            (day, n),
        ).fetchall()
    except Exception:
        return []
    return [str(r[0]) for r in rows if r and r[0]]


def _load_fx_regime(con: sqlite3.Connection, day: str) -> dict:
    fx = None
    try:
        row = con.execute(
            "SELECT payload FROM us_overnight ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            fx = _finite((payload or {}).get("usdtwd_px"))
    except Exception:
        fx = None
    above = True
    try:
        tw = con.execute(
            """
            SELECT close, ma20 FROM index_daily WHERE symbol='TWII'
              AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 1
            """,
            (day,),
        ).fetchone()
        if tw and _finite(tw[0]) is not None and _finite(tw[1]) is not None:
            above = float(tw[0]) >= float(tw[1])
    except Exception:
        pass
    streak = 0
    try:
        sells = con.execute(
            """
            SELECT foreign_net_yi FROM market_inst_bfi_daily
            WHERE REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 12
            """,
            (day,),
        ).fetchall()
        for r in sells:
            v = _finite(r[0])
            if v is not None and v < 0:
                streak += 1
            else:
                break
    except Exception:
        pass
    if fx is None:
        return {
            "class": "regime-normal",
            "text": "資金水位中性｜匯率待補",
            "fx_text": "USD/TWD —",
        }
    return detect_market_regime_neutral(float(fx), streak, above)


def _rail_marks_html(marks: Sequence[dict]) -> str:
    """marks: [{label, value, pct, kind}] kind=now|broke|plain"""
    parts = []
    for m in marks:
        kind = str(m.get("kind") or "plain")
        cls = "rail-mark"
        if kind == "now":
            cls += " now"
        elif kind == "broke":
            cls += " broke"
        pct = max(2.0, min(98.0, float(m.get("pct") or 50)))
        parts.append(
            f'<div class="{cls}" style="left:{pct:.1f}%;">'
            f'<div class="rail-lab">{html.escape(str(m.get("label") or ""))}</div>'
            f'<div class="tick"></div>'
            f'<div class="rail-val mono">{html.escape(_fmt_price(m.get("value")))}</div>'
            f"</div>"
        )
    return "".join(parts)


def _stat4_html(cells: Sequence[Tuple[str, str]]) -> str:
    out = []
    for k, v in list(cells)[:4]:
        out.append(
            f'<div class="d3-cell"><div class="cell-k">{html.escape(k)}</div>'
            f'<div class="cell-v mono">{html.escape(v)}</div></div>'
        )
    while len(out) < 4:
        out.append('<div class="d3-cell"><div class="cell-k">—</div><div class="cell-v">—</div></div>')
    return "".join(out)


def build_flagship_payload(
    db_path: str,
    stock_id: str,
    *,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """從真庫組一檔旗艦卡資料；缺欄就標 —，不准填假匯率／假 11月✓。"""
    sid = str(stock_id or "").strip()
    day = str(as_of or "").replace("-", "")[:8]
    if len(day) != 8:
        day = date.today().strftime("%Y%m%d")
    ref_d = date(int(day[:4]), int(day[4:6]), int(day[6:8]))

    con = sqlite3.connect(db_path)
    try:
        name, market = sid, ""
        try:
            r = con.execute(
                "SELECT stock_name, market FROM stock_directory WHERE stock_id=?",
                (sid,),
            ).fetchone()
            if r:
                name, market = str(r[0] or sid), str(r[1] or "")
        except Exception:
            pass
        emerging = market.upper() in ("EM", "EMERGING", "興櫃")

        industry = ""
        try:
            fi = con.execute(
                "SELECT chain FROM stock_fine_industry WHERE stock_id=?",
                (sid,),
            ).fetchone()
            if fi and fi[0]:
                industry = str(fi[0])
        except Exception:
            pass

        close = pct = None
        try:
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
        except Exception:
            pass
        if close is None and emerging:
            try:
                q = con.execute(
                    """
                    SELECT close FROM emerging_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                      AND close IS NOT NULL AND close>0
                    ORDER BY date DESC LIMIT 1
                    """,
                    (sid, day),
                ).fetchone()
                if q:
                    close = _finite(q[0])
            except Exception:
                pass

        # OHLC window for levels (prefer adj if column exists)
        bars = []
        try:
            cols = [c[1] for c in con.execute("PRAGMA table_info(daily_quotes)").fetchall()]
            price_col = "adj_close" if "adj_close" in cols else "close"
            bars = con.execute(
                f"""
                SELECT date, high, low, {price_col}, volume
                FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND {price_col} IS NOT NULL AND {price_col}>0
                ORDER BY date ASC
                """,
                (sid, day),
            ).fetchall()
        except Exception:
            bars = []
        if not bars and emerging:
            try:
                bars = con.execute(
                    """
                    SELECT date, high, low, close, volume FROM emerging_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                      AND close IS NOT NULL AND close>0
                    ORDER BY date ASC
                    """,
                    (sid, day),
                ).fetchall()
            except Exception:
                bars = []

        half_low = ma60 = high60 = None
        if bars:
            closes = [float(b[3]) for b in bars]
            lows = [float(b[2]) for b in bars if _finite(b[2])]
            highs = [float(b[1]) for b in bars if _finite(b[1])]
            if closes:
                close = close if close is not None else closes[-1]
                window = closes[-60:] if len(closes) >= 60 else closes
                ma60 = sum(window) / len(window)
                high60 = max(highs[-60:] if len(highs) >= 60 else highs) if highs else max(window)
            # ~126 trading days ≈ half year
            if lows:
                half_low = min(lows[-126:] if len(lows) >= 126 else lows)

        support = resist = None
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

        # monthly revenue
        rev_yi = rev_ym = None
        try:
            mr = con.execute(
                """
                SELECT yyyymm, revenue FROM monthly_revenue
                WHERE stock_id=? AND REPLACE(CAST(yyyymm AS TEXT),'-','')<=?
                ORDER BY yyyymm DESC LIMIT 1
                """,
                (sid, day[:6]),
            ).fetchone()
            if mr and _finite(mr[1]) is not None:
                rev_ym = str(mr[0]).replace("-", "")[:6]
                rev_yi = float(mr[1]) / 100000.0
        except Exception:
            pass

        # chips（左舊→右新）；結果放 chip_foreign／chip_trust，避免作用域混淆
        chip_foreign: List[str] = ["N", "N", "N", "N", "N"]
        chip_trust: List[str] = ["N", "N", "N", "N", "N"]
        if not emerging:
            days = _chip_days(con, day, 5)
            got_f: List[str] = []
            got_t: List[str] = []
            for d in reversed(list(days)[:5]):
                dkey = str(d).replace("-", "")[:8]
                net = con.execute(
                    """
                    SELECT foreign_net, trust_net FROM daily_quotes
                    WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
                    LIMIT 1
                    """,
                    (str(sid), dkey),
                ).fetchone()
                if net is None:
                    got_f.append("N")
                    got_t.append("N")
                else:
                    fv = float(net[0]) if net[0] is not None else 0.0
                    tv = float(net[1]) if net[1] is not None else 0.0
                    got_f.append(_net_to_flag(fv))
                    got_t.append(_net_to_flag(tv))
            if len(got_f) >= 5:
                chip_foreign = got_f[-5:]
                chip_trust = got_t[-5:]
            elif got_f:
                chip_foreign = (["N"] * 5 + got_f)[-5:]
                chip_trust = (["N"] * 5 + got_t)[-5:]

        # peers from same chain
        peers: List[dict] = []
        if industry:
            try:
                ids = [
                    str(r[0])
                    for r in con.execute(
                        "SELECT stock_id FROM stock_fine_industry WHERE chain=? LIMIT 40",
                        (industry,),
                    ).fetchall()
                    if str(r[0]) != sid
                ]
                for pid in ids[:12]:
                    pq = con.execute(
                        """
                        SELECT close FROM daily_quotes
                        WHERE stock_id=? AND close>0
                        ORDER BY date DESC LIMIT 1
                        """,
                        (pid,),
                    ).fetchone()
                    pn = con.execute(
                        "SELECT stock_name FROM stock_directory WHERE stock_id=?",
                        (pid,),
                    ).fetchone()
                    if not pq:
                        continue
                    peers.append(
                        {
                            "stock_id": pid,
                            "name": (pn[0] if pn else pid),
                            "close": float(pq[0]),
                        }
                    )
                    if len(peers) >= 3:
                        break
            except Exception:
                peers = []

        regime = (
            {
                "class": "regime-em",
                "text": "⚠️ 興櫃透明度較低｜無每日法人進出與融資數據",
                "fx_text": "預計上櫃 —",
            }
            if emerging
            else _load_fx_regime(con, day)
        )
    finally:
        con.close()

    # try 區塊結束後接續；籌碼用 chip_*（若上方 try 早退則預設灰）
    try:
        chip_foreign
        chip_trust
    except NameError:
        chip_foreign = ["N", "N", "N", "N", "N"]
        chip_trust = ["N", "N", "N", "N", "N"]

    # EPS／目標／門檻：優先真庫成長估算；低估 detail 次之；缺欄標 —
    eps_e = eps_y = eps_n = eps_q = None
    pe_year = pe_next = fair = tgt = thr = gm = None
    placement = None
    try:
        con2 = sqlite3.connect(db_path)
        try:
            # 季報最新 EPS／毛利（官方）
            try:
                qi = con2.execute(
                    """
                    SELECT eps, gross_margin_pct, season FROM quarterly_income
                    WHERE stock_id=? ORDER BY year DESC, season DESC LIMIT 2
                    """,
                    (sid,),
                ).fetchone()
                if qi:
                    eps_e = _finite(qi[0])
                    gm = _finite(qi[1])
                    eps_q = eps_e
            except Exception:
                pass
            # 成長估算（同一套官方庫推估，不是寫死假數）
            try:
                from undervalue_growth import enrich_growth_row

                qty60 = 1000.0
                if bars:
                    vols = [float(b[4] or 0) for b in bars[-60:]]
                    if vols:
                        qty60 = sum(vols) / max(len(vols), 1) / 1000.0
                eg = enrich_growth_row(
                    con2,
                    sid=sid,
                    name=name,
                    close=float(close or 0),
                    pe=20.0,
                    peer_med_raw=25.0,
                    as_of=day,
                    yoy_pct=None,
                    qty60=float(qty60),
                    market_type="EM" if emerging else "TW",
                )
            except Exception:
                eg = None
            if eg:
                eps_e = _finite(eg.get("eps_earned")) or eps_e
                eps_y = _finite(eg.get("eps_2026"))
                eps_n = _finite(eg.get("eps_2027"))
                pe_year = _finite(eg.get("pe_year"))
                pe_next = _finite(eg.get("pe_next"))
                fair = _finite(eg.get("fair_year"))
                tgt = _finite(eg.get("target_next"))
                thr = _finite(eg.get("rev_threshold_yi"))
                gm = _finite(eg.get("gross_margin")) or gm
                if _finite(eg.get("support")) is not None:
                    support = _finite(eg.get("support"))
                if _finite(eg.get("resistance")) is not None:
                    resist = _finite(eg.get("resistance"))
                # 興櫃只認 directory／市場別，不准被估算列誤標翻成興櫃
            row = con2.execute(
                """
                SELECT mark, close, detail_json FROM undervalue_picks
                WHERE stock_id=? ORDER BY as_of DESC LIMIT 1
                """,
                (sid,),
            ).fetchone()
            if row and row[2]:
                d = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                eps_e = eps_e or _finite(d.get("eps_earned"))
                eps_y = eps_y or _finite(d.get("eps_2026"))
                eps_n = eps_n or _finite(d.get("eps_2027"))
                eps_q = eps_q or _finite(d.get("eps_latest_q") or d.get("eps_q"))
                pe_year = pe_year or _finite(d.get("pe_year"))
                pe_next = pe_next or _finite(d.get("pe_next"))
                fair = fair or _finite(d.get("fair_year"))
                tgt = tgt or _finite(d.get("target_next"))
                thr = thr or _finite(d.get("rev_threshold_yi"))
                gm = gm or _finite(d.get("gross_margin"))
                if emerging:
                    placement = _finite(d.get("placement_price") or d.get("offer_price"))
        finally:
            con2.close()
    except Exception:
        pass

    flow_type, flow_pill = _pill_from_5d(chip_foreign, chip_trust, emerging=emerging)
    broke = close is not None and support is not None and close < support
    if emerging:
        # 興櫃量小：無 60 日均量或極低
        qty60 = None
        if bars:
            vols = [float(b[4] or 0) for b in bars[-60:]]
            if vols:
                qty60 = sum(vols) / len(vols) / 1000.0  # 張粗估
        status, icon, status_label = "risk", "⚠️", "興櫃量小"
        if qty60 is not None and qty60 >= 400:
            status, icon, status_label = "wait", "☆", "等止穩"
    elif broke:
        status, icon, status_label = "wait", "☆", "等止穩"
    else:
        status, icon, status_label = "buy", "★", "可買"

    fwd = None
    if eps_y is not None and eps_n is not None:
        fwd = calc_forward_12m_eps(eps_y, eps_n, ref_d)
    elif eps_n is not None:
        fwd = eps_n
    elif eps_y is not None:
        fwd = eps_y
    pe_fwd = (close / fwd) if (close and fwd and fwd > 0) else None
    fair_lo = pe_next if pe_next is not None else pe_year
    fair_hi = pe_year if pe_year is not None else pe_next
    if fair_lo is not None and fair_hi is not None and fair_lo > fair_hi:
        fair_lo, fair_hi = fair_hi, fair_lo
    pe_min, pe_mid, pe_max, pe_dot = _pe_scale(pe_fwd, fair_lo, fair_hi)
    if pe_fwd is not None and fair_lo is not None and fair_hi is not None:
        pe_note = "偏低" if pe_fwd < fair_lo else ("偏貴" if pe_fwd > fair_hi else "合理帶")
    else:
        pe_note = "滾動"

    eps_pct = 0
    if eps_e is not None and eps_y is not None and eps_y > 0:
        eps_pct = max(0, min(999, int(round(eps_e / eps_y * 100))))
    rev_pct = 0
    if thr is not None and thr > 0 and rev_yi is not None:
        rev_pct = max(0, min(999, int(round(rev_yi / thr * 100))))

    month_lab = f"{int(rev_ym[4:6])}月" if rev_ym and len(rev_ym) == 6 else ""
    if rev_yi is not None and thr is not None:
        rev_line = f"{month_lab}{_fmt_yi_num(rev_yi)} / 需{_fmt_yi_num(thr)}億 ({rev_pct}%)"
    elif rev_yi is not None:
        rev_line = f"{month_lab}{_fmt_yi_num(rev_yi)}億"
    else:
        rev_line = "—"

    support_text = (
        f"▲破撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
        if broke and support is not None
        else f"撐 {_fmt_price(support)}｜壓 {_fmt_price(resist)}"
    )

    # price rail
    if emerging:
        anchors = []
        if placement is not None:
            anchors.append(("現增", placement, "plain"))
        if close is not None:
            anchors.append(("現價", close, "now" if not broke else "broke"))
        if support is not None:
            anchors.append(("平台", support, "broke" if broke else "plain"))
        if high60 is not None:
            anchors.append(("前高", high60, "plain"))
    else:
        anchors = []
        if half_low is not None:
            anchors.append(("半年低", half_low, "plain"))
        if close is not None:
            anchors.append(("現價", close, "now" if not broke else "broke"))
        if support is not None:
            anchors.append(("大量撐", support, "broke" if broke else "plain"))
        if resist is not None:
            anchors.append(("大量壓", resist, "plain"))
        if high60 is not None:
            anchors.append(("60高", high60, "plain"))

    vals = [a[1] for a in anchors if _finite(a[1]) is not None]
    lo_v, hi_v = (min(vals), max(vals)) if vals else (0.0, 1.0)
    span = max(hi_v - lo_v, 1e-6)
    rail = [
        {
            "label": lab,
            "value": val,
            "pct": (float(val) - lo_v) / span * 100.0,
            "kind": kind,
        }
        for lab, val, kind in anchors
    ]

    # mid 4 stats
    if emerging:
        mom = "—"
        try:
            con3 = sqlite3.connect(db_path)
            mrs = con3.execute(
                """
                SELECT yyyymm, revenue FROM monthly_revenue WHERE stock_id=?
                ORDER BY yyyymm DESC LIMIT 2
                """,
                (sid,),
            ).fetchall()
            con3.close()
            if len(mrs) >= 2 and _finite(mrs[0][1]) and _finite(mrs[1][1]) and float(mrs[1][1]) > 0:
                mom_pct = (float(mrs[0][1]) - float(mrs[1][1])) / float(mrs[1][1]) * 100.0
                mom = f"{mom_pct:+.1f}%"
        except Exception:
            pass
        stat4 = [
            ("現增／稀釋", f"暫定 {_fmt_price(placement)}元" if placement else "現增 —"),
            ("最新毛利", f"{gm:.1f}%" if gm is not None else "—"),
            ("近月營收月增", mom),
            ("流動性", "⚠️ 價差大難出脫"),
        ]
    else:
        pullback = (
            (close - high60) / high60 * 100.0
            if close is not None and high60 not in (None, 0)
            else None
        )
        bias = (
            (close - ma60) / ma60 * 100.0
            if close is not None and ma60 not in (None, 0)
            else None
        )
        # 溫度粗估：相對半年低～60高
        temp = "—"
        if close is not None and half_low is not None and high60 is not None and high60 > half_low:
            t = (close - half_low) / (high60 - half_low) * 100.0
            temp = f"{t:.0f}°"
        stat4 = [
            ("60日高回檔", f"{pullback:+.1f}%" if pullback is not None else "—"),
            ("月線乖離", f"{bias:+.1f}%" if bias is not None else "—"),
            ("現金殖利率", "—｜地板未標"),
            ("溫度計", temp),
        ]

    peers_html_lines = []
    for p in peers[:3]:
        peers_html_lines.append(
            f'<div class="peer-line mono">{html.escape(p["stock_id"])} {html.escape(str(p["name"]))}'
            f' <span>收 {_fmt_price(p["close"])}</span></div>'
        )
    if not peers_html_lines:
        peers_html_lines = ['<div class="peer-line">同族群對照待補</div>']

    mkt_label = "興櫃" if emerging else ("上市" if market.upper() in ("TW", "TSE", "") else market or "上市櫃")
    chg_s = ""
    if pct is not None:
        chg_s = f"<span class=\"{'chg-up' if pct >= 0 else 'chg-down'}\">{pct:+.2f}%</span>"

    return {
        "status": status,
        "icon": icon,
        "status_label": status_label,
        "stock_id": sid,
        "name": name,
        "market_label": mkt_label,
        "industry": industry or "—",
        "close": close,
        "pct": pct,
        "chg_html": chg_s,
        "flow_type": flow_type,
        "flow_pill": flow_pill,
        "emerging": emerging,
        "regime": regime,
        "eps_earned": eps_e,
        "eps_year": eps_y,
        "eps_q": eps_q,
        "eps_pct": eps_pct,
        "q4": "已賺(上半年)" if emerging and eps_e is not None and (eps_y is None or eps_y <= 0) else _q4_from_yyyymm(rev_ym),
        "eps_title": "今年賺錢進度" if not emerging else "賺錢進度（興櫃）",
        "pe_fwd": pe_fwd,
        "pe_note": pe_note,
        "pe_min": pe_min,
        "pe_mid": pe_mid,
        "pe_max": pe_max,
        "pe_dot": pe_dot,
        "target_norm": _fmt_price(tgt if tgt is not None else fair),
        "target_cons": _fmt_price(fair if fair is not None else tgt),
        "foreign_5d": list(chip_foreign),
        "trust_5d": list(chip_trust),
        "placement": placement,
        "rev_line": rev_line,
        "rev_pct": rev_pct,
        "support_ok": not broke,
        "support_text": support_text,
        "rail": rail,
        "stat4": stat4,
        "peers_html": "".join(peers_html_lines),
        "moat_text": (
            f"{industry}｜興櫃流動性與資訊揭露較弱，價差與出脫風險需自行控管。"
            if emerging
            else f"{industry or '本業'}｜最大風險：景氣／客戶集中與估值波動（估值≠買訊）。"
        ),
        "legend": (
            "★可買 ☆等止穩 ⚠️興櫃量小｜興櫃不適用法人與融資指標｜估值≠買訊"
            if emerging
            else "★可買 ☆等止穩 ⚠️興櫃量小｜5日籌碼(左→右)：🟥買 🟩賣｜估值≠買訊"
        ),
    }


def render_flagship_html(payload: Dict[str, Any]) -> str:
    s = payload
    emerging = bool(s.get("emerging"))
    bar_cls = "prog-fill-amber" if s.get("status") == "risk" else ""
    flow_cls = {"buy": "flow-buy", "sell": "flow-sell", "warn": "flow-warn"}.get(
        s.get("flow_type"), "flow-buy"
    )
    support_cls = "down" if s.get("support_ok") else "amber"
    pe_left = max(8, min(92, int(round(float(s.get("pe_dot") or 50)))))

    if emerging:
        place = _fmt_price(s.get("placement"))
        bl_title = "目標價（現增／上櫃）"
        bl_bottom = (
            f'<div class="cell-sub amber">現增暫定 {html.escape(place)}元｜稀釋／上櫃時程待補</div>'
        )
    else:
        bl_title = "目標價（正常／保守）＋近5日"
        f_sq = _render_5day_squares(s.get("foreign_5d") or [])
        t_sq = _render_5day_squares(s.get("trust_5d") or [])
        bl_bottom = (
            f'<div class="flow-blocks-row">'
            f'<span>外資</span><span class="sq-group">{f_sq}</span>'
            f'<span>投信</span><span class="sq-group">{t_sq}</span></div>'
        )

    head = (
        f"{html.escape(s['icon'])} {html.escape(s['status_label'])}｜"
        f"{html.escape(s['stock_id'])} {html.escape(s['name'])}｜"
        f"{html.escape(_fmt_price(s.get('close')))}元"
    )
    if s.get("chg_html"):
        head += f" {s['chg_html']}"

    meta = f"{html.escape(s.get('market_label') or '')}・{html.escape(s.get('industry') or '—')}"
    reg = s.get("regime") or {}
    eps_bar = min(100, int(s.get("eps_pct") or 0))
    rev_bar = min(100, int(s.get("rev_pct") or 0))

    html_out = (
        HTML_TEMPLATE.replace("{{HEAD_MAIN}}", head)
        .replace("{{FLOW_CLS}}", flow_cls)
        .replace("{{FLOW_PILL}}", html.escape(str(s.get("flow_pill") or "—")))
        .replace("{{META_LINE}}", meta)
        .replace("{{REGIME_CLASS}}", str(reg.get("class") or "regime-normal"))
        .replace("{{REGIME_TEXT}}", html.escape(str(reg.get("text") or "")))
        .replace("{{FX_TEXT}}", html.escape(str(reg.get("fx_text") or "")))
        .replace("{{STATUS}}", html.escape(str(s.get("status") or "wait")))
        .replace("{{EPS_TITLE}}", html.escape(str(s.get("eps_title") or "今年賺錢進度")))
        .replace("{{EPS_YTD}}", html.escape(_fmt_num(s.get("eps_earned"), 2 if (_finite(s.get("eps_earned")) or 0) < 10 else 1)))
        .replace("{{EPS_EST}}", html.escape(_fmt_num(s.get("eps_year"), 1)))
        .replace("{{EPS_PCT}}", str(int(s.get("eps_pct") or 0)))
        .replace("{{EPS_BAR}}", str(eps_bar))
        .replace("{{BAR_CLS}}", bar_cls)
        .replace("{{Q4_OR_HALF}}", html.escape(str(s.get("q4") or "")))
        .replace("{{EPS_Q}}", html.escape(_fmt_num(s.get("eps_q"), 2)))
        .replace("{{PE_FWD}}", html.escape(_fmt_num(s.get("pe_fwd"), 1)))
        .replace("{{PE_NOTE}}", html.escape(str(s.get("pe_note") or "")))
        .replace("{{PE_LEFT}}", str(pe_left))
        .replace("{{PE_MIN}}", html.escape(str(s.get("pe_min") or "—")))
        .replace("{{PE_MID}}", html.escape(str(s.get("pe_mid") or "—")))
        .replace("{{PE_MAX}}", html.escape(str(s.get("pe_max") or "—")))
        .replace("{{BL_TITLE}}", html.escape(bl_title))
        .replace("{{TGT_NORM}}", html.escape(str(s.get("target_norm") or "—")))
        .replace("{{TGT_CONS}}", html.escape(str(s.get("target_cons") or "—")))
        .replace("{{BL_BOTTOM}}", bl_bottom)
        .replace("{{REV_LINE}}", html.escape(str(s.get("rev_line") or "—")))
        .replace("{{REV_BAR}}", str(rev_bar))
        .replace("{{SUPPORT_CLS}}", support_cls)
        .replace("{{SUPPORT_TEXT}}", html.escape(str(s.get("support_text") or "")))
        .replace("{{RAIL_MARKS}}", _rail_marks_html(s.get("rail") or []))
        .replace("{{STAT4}}", _stat4_html(s.get("stat4") or []))
        .replace("{{PEERS_HTML}}", s.get("peers_html") or "")
        .replace("{{MOAT_TEXT}}", html.escape(str(s.get("moat_text") or "")))
        .replace("{{LEGEND}}", html.escape(str(s.get("legend") or "")))
    )
    return html_out


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
    db = os.environ.get("WAYNE_DB_PATH") or "data/wayne_market.db"
    out_dir = "/opt/cursor/artifacts/lookup-flagship"
    os.makedirs(out_dir, exist_ok=True)
    as_of = "20261118"
    for sid in ("6442", "2383", "3595"):
        p = os.path.join(out_dir, f"flagship_{sid}.png")
        render_flagship_png(sid, p, db_path=db, as_of=as_of)
        print(p, os.path.getsize(p))


if __name__ == "__main__":
    main()
