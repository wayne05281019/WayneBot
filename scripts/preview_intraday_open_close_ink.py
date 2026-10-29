#!/usr/bin/env python3
"""Preview-only：今日開→收墨線臉（查股第 5 張候選）。

- 不准接話筒／不准改查股送序。
- 路徑只認 Yahoo chart 1m（已允許源）；標「非官方定稿／暫讀」。
- 不准用日 K 捏假折線。無點列 → 空態卡「暫無今日路徑資料」。
- 興櫃：Yahoo 通常只到 13:30；日均價規則另標，不拿 Yahoo 現價冒充官方均價收。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

# repo root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

TZ = ZoneInfo("Asia/Taipei")

# 預覽五檔（使用者 2026-10-29 點名）
PREVIEW_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("3595", "山太士", "EM"),
    ("7853", "政美應用", "EM"),
    ("2383", "台光電", "TW"),
    ("6274", "台燿", "TWO"),
    ("1303", "南亞", "TW"),
)

_SLUG = {
    "3595": "shantashi",
    "7853": "zhengmei",
    "2383": "taiguangdian",
    "6274": "taiyao",
    "1303": "nanya",
}


@dataclass
class PathSeries:
    stock_id: str
    name: str
    market: str
    yahoo_symbol: str
    times: List[datetime]
    closes: List[float]
    volumes_lots: List[float]  # 張
    opens: List[float]
    highs: List[float]
    lows: List[float]
    prev_close: float
    source: str
    label: str
    fetched_at: datetime


def _ua() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }


def _yahoo_ids(stock_id: str, market: str, db_path: Optional[str]) -> List[str]:
    from kline_hop import yahoo_chart_symbol

    primary = yahoo_chart_symbol(stock_id, db_path)
    alts: List[str] = [primary]
    for sfx in ("TW", "TWO"):
        cand = f"{stock_id}.{sfx}"
        if cand not in alts:
            alts.append(cand)
    # EM 優先 TWO
    if str(market).upper() == "EM":
        alts = sorted(alts, key=lambda s: (0 if s.endswith(".TWO") else 1, s))
    return alts


def fetch_yahoo_1m_today(
    stock_id: str,
    name: str,
    market: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[PathSeries]:
    """單檔按需：Yahoo chart interval=1m range=1d。失敗回 None。"""
    import requests
    from kline_hop import parse_yahoo_chart_bars

    now = datetime.now(TZ)
    today = now.strftime("%Y%m%d")
    last_err = ""
    for yid in _yahoo_ids(stock_id, market, db_path):
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(yid, safe='')}"
            f"?interval=1m&range=1d"
        )
        try:
            resp = requests.get(url, timeout=12, headers=_ua())
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            payload = resp.json() or {}
            block = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
            if not block:
                last_err = "empty chart"
                continue
            meta = block.get("meta") or {}
            bars = parse_yahoo_chart_bars(payload)
            # 只留今日台北開市窗點
            times: List[datetime] = []
            closes: List[float] = []
            vols: List[float] = []
            opens: List[float] = []
            highs: List[float] = []
            lows: List[float] = []
            for b in bars:
                t_raw = str(b.get("t") or "")
                if len(t_raw) < 12 or not t_raw.startswith(today):
                    continue
                dt = datetime.strptime(t_raw, "%Y%m%d%H%M").replace(tzinfo=TZ)
                # 上市櫃 09:00–13:30；興櫃 Yahoo 常見也只到 13:30
                hm = dt.hour * 100 + dt.minute
                if hm < 900 or hm > 1500:
                    continue
                c = float(b["c"])
                times.append(dt)
                closes.append(c)
                vols.append(float(b.get("v") or 0.0))
                opens.append(float(b.get("o") or c))
                highs.append(float(b.get("h") or c))
                lows.append(float(b.get("l") or c))
            if len(closes) < 2:
                last_err = f"{yid} today points<{2}"
                continue
            prev = meta.get("chartPreviousClose")
            if prev is None:
                prev = meta.get("previousClose")
            if prev is None or float(prev) <= 0:
                last_err = "no prev close"
                continue
            prev_f = float(prev)
            em_note = ""
            if str(market).upper() == "EM":
                em_note = "；興櫃官方收＝日均價，Yahoo 現／昨收＝成交暫讀，非定稿"
                t1 = times[-1]
                if t1.hour * 100 + t1.minute <= 1330:
                    em_note += "；此源路徑常見只到 13:30（興櫃窗至 15:00）"
            # 盤後（台北已過 13:30 上市／15:00 興櫃）標行情已收但非官方融合
            sess_end = 1500 if str(market).upper() == "EM" else 1330
            hm_now = now.hour * 100 + now.minute
            if hm_now > sess_end:
                stamp = "行情已收・非官方定稿"
            elif hm_now < 900:
                stamp = "盤前・暫無完整今日路徑"
            else:
                stamp = f"盤中暫讀 {now.strftime('%H:%M')}"
            label = (
                f"Yahoo 1m 暫讀・{stamp}・非官方日 K"
                f"{em_note}"
            )
            return PathSeries(
                stock_id=stock_id,
                name=name,
                market=market,
                yahoo_symbol=str(meta.get("symbol") or yid),
                times=times,
                closes=closes,
                volumes_lots=vols,
                opens=opens,
                highs=highs,
                lows=lows,
                prev_close=prev_f,
                source=f"yahoo:chart:1m:{yid}",
                label=label,
                fetched_at=now,
            )
        except Exception as exc:  # noqa: BLE001 — preview soft fail
            last_err = str(exc)
            continue
    sys.stderr.write(f"[skip] {stock_id} {name}: {last_err}\n")
    return None


def _fmt_px(v: float) -> str:
    av = abs(v)
    if av >= 1000:
        return f"{v:,.0f}"
    if av >= 100:
        return f"{v:,.1f}".rstrip("0").rstrip(".")
    if av >= 10:
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return f"{v:,.2f}"


def _side_color(delta: float, up: str, dn: str, mute: str) -> str:
    if delta > 0:
        return up
    if delta < 0:
        return dn
    return mute


def render_empty(
    out_path: str,
    *,
    stock_id: str,
    name: str,
    market: str,
    reason: str,
) -> str:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from ink_chart_theme import INK, INK2, MUTE, PAPER, RULE, fp

    fig = plt.figure(figsize=(12.8, 7.2), dpi=160, facecolor=PAPER)
    ax = fig.add_axes([0.06, 0.08, 0.88, 0.82])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0.05, 0.18),
            0.90,
            0.62,
            boxstyle="square,pad=0.012",
            facecolor=PAPER,
            edgecolor=INK,
            linewidth=1.4,
            transform=ax.transAxes,
        )
    )
    ax.text(
        0.5,
        0.62,
        f"{stock_id}　{name}",
        fontproperties=fp(28, True),
        color=INK,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.48,
        "暫無今日路徑資料",
        fontproperties=fp(22, True),
        color=INK2,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.36,
        f"{reason}　｜　{market}　｜　不是買訊",
        fontproperties=fp(12, False),
        color=MUTE,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.08,
        "preview only · 未接話筒",
        fontproperties=fp(11, False),
        color=RULE if False else MUTE,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, facecolor=PAPER, edgecolor="none")
    plt.close(fig)
    return out_path


def render_path(series: PathSeries, out_path: str) -> str:
    """墨線臉：昨收基準紅綠帶＋折線＋量柱＋開高低現統計。無五檔／內外盤。"""
    import numpy as np
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    from ink_chart_theme import DN, INK, INK2, MUTE, PAPER, RULE, UP, fp

    times = series.times
    ys = np.asarray(series.closes, dtype=float)
    vs = np.asarray(series.volumes_lots, dtype=float)
    prev = float(series.prev_close)
    # 統計：開＝首根開；高／低＝路徑；現＝末收；量＝張加總
    open_px = float(series.opens[0])
    high_px = float(np.max(series.highs))
    low_px = float(np.min(series.lows))
    last_px = float(ys[-1])
    chg = last_px - prev
    pct = (chg / prev * 100.0) if prev else 0.0
    vol_sum = float(np.nansum(vs))
    col = _side_color(chg, UP, DN, MUTE)
    arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "－")

    # 時間軸：分鐘 offset from 09:00
    def _x(dt: datetime) -> float:
        return (dt.hour - 9) * 60 + dt.minute

    xs = np.asarray([_x(t) for t in times], dtype=float)
    # 上市櫃窗 09:00–13:30＝270 分；興櫃標到 15:00 空窗
    x_end = 360.0 if str(series.market).upper() == "EM" else 270.0

    fig_w, fig_h, dpi = 14.2, 8.4, 160
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=PAPER)

    # 外框
    fig.patches.append(
        Rectangle(
            (0.015, 0.02),
            0.97,
            0.96,
            transform=fig.transFigure,
            facecolor=PAPER,
            edgecolor=INK,
            linewidth=1.35,
            zorder=-1,
            clip_on=False,
        )
    )

    # 標題列
    fig.text(
        0.04,
        0.935,
        f"{series.stock_id}　{series.name}",
        fontproperties=fp(22, True),
        color=INK,
        ha="left",
        va="top",
    )
    fig.text(
        0.04,
        0.895,
        "今日開→收　｜　不是買訊　｜　preview",
        fontproperties=fp(11, False),
        color=MUTE,
        ha="left",
        va="top",
    )
    fig.text(
        0.96,
        0.935,
        series.fetched_at.strftime("%Y-%m-%d %H:%M Asia/Taipei"),
        fontproperties=fp(11, False),
        color=MUTE,
        ha="right",
        va="top",
    )

    # 頭列：現價＋漲跌（左）／開高低現統計格（右）— 全在圖上方，不壓折線
    fig.text(
        0.04,
        0.825,
        _fmt_px(last_px),
        fontproperties=fp(36, True),
        color=col,
        ha="left",
        va="center",
    )
    fig.text(
        0.04,
        0.755,
        f"{arrow}{_fmt_px(abs(chg))}　({pct:+.2f}%)",
        fontproperties=fp(15, True),
        color=col,
        ha="left",
        va="center",
    )

    stats = [
        ("開盤", _fmt_px(open_px), INK),
        ("最高", _fmt_px(high_px), UP if high_px >= prev else DN),
        ("最低", _fmt_px(low_px), DN if low_px <= prev else UP),
        ("現價", _fmt_px(last_px), col),
        ("昨收", _fmt_px(prev), INK2),
        ("漲跌", f"{chg:+.2f}".rstrip("0").rstrip("."), col),
        ("漲跌幅", f"{pct:+.2f}%", col),
        ("量(張)", f"{vol_sum:,.0f}", INK),
    ]
    # 2×4 格貼右上；底邊停在主圖頂之上
    sx0, sy_top = 0.42, 0.86
    cell_w, cell_h = 0.125, 0.048
    gap_x, gap_y = 0.012, 0.008
    for i, (lab, val, vc) in enumerate(stats):
        r, c = divmod(i, 4)
        x = sx0 + c * (cell_w + gap_x)
        y = sy_top - cell_h - r * (cell_h + gap_y)
        fig.patches.append(
            FancyBboxPatch(
                (x, y),
                cell_w,
                cell_h,
                boxstyle="square,pad=0.003",
                facecolor=PAPER,
                edgecolor=RULE,
                linewidth=0.9,
                transform=fig.transFigure,
                clip_on=False,
            )
        )
        fig.text(
            x + 0.008,
            y + cell_h * 0.52,
            lab,
            fontproperties=fp(9, False),
            color=MUTE,
            ha="left",
            va="center",
            transform=fig.transFigure,
        )
        fig.text(
            x + cell_w - 0.008,
            y + cell_h * 0.52,
            val,
            fontproperties=fp(12, True),
            color=vc,
            ha="right",
            va="center",
            transform=fig.transFigure,
        )

    # 主圖＋量（左寬）＋來源說明（右窄）；頭列已結束於 ~0.74
    ax = fig.add_axes([0.07, 0.26, 0.68, 0.42])
    vol_ax = fig.add_axes([0.07, 0.10, 0.68, 0.14], sharex=ax)
    ax.set_facecolor(PAPER)
    vol_ax.set_facecolor(PAPER)

    hi = float(max(float(np.max(ys)), prev, high_px))
    lo = float(min(float(np.min(ys)), prev, low_px))
    pad = max((hi - lo) * 0.10, abs(prev) * 0.002, 0.5)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(0.0, x_end)

    ax.axhline(prev, color=MUTE, linestyle=(0, (4, 3)), linewidth=1.35, zorder=2)
    ax.fill_between(xs, prev, ys, where=ys >= prev, interpolate=True, color=UP, alpha=0.22, zorder=1)
    ax.fill_between(xs, prev, ys, where=ys <= prev, interpolate=True, color=DN, alpha=0.22, zorder=1)
    for i in range(len(ys) - 1):
        a, b = float(ys[i]), float(ys[i + 1])
        x0, x1 = float(xs[i]), float(xs[i + 1])
        if (a >= prev and b >= prev) or (a < prev and b < prev):
            ax.plot(
                [x0, x1],
                [a, b],
                color=_side_color(a - prev if a != prev else b - prev, UP, DN, MUTE),
                lw=2.05,
                solid_capstyle="round",
                zorder=3,
            )
        else:
            if b == a:
                continue
            t = (prev - a) / (b - a)
            xc = x0 + t * (x1 - x0)
            ax.plot([x0, xc], [a, prev], color=_side_color(a - prev, UP, DN, MUTE), lw=2.05, zorder=3)
            ax.plot([xc, x1], [prev, b], color=_side_color(b - prev, UP, DN, MUTE), lw=2.05, zorder=3)

    # 昨收標
    ax.text(
        0.995,
        prev,
        f" 昨收 {_fmt_px(prev)}",
        fontproperties=fp(9, False),
        color=MUTE,
        ha="right",
        va="bottom",
        transform=ax.get_yaxis_transform(),
        zorder=5,
    )

    # 量柱
    if len(xs) >= 2:
        width = max(float(np.median(np.diff(xs))) * 0.75, 0.6)
    else:
        width = 1.0
    vcols = [_side_color(float(y) - prev, UP, DN, MUTE) for y in ys]
    vol_ax.bar(xs, vs, width=width, color=vcols, alpha=0.85, zorder=2, linewidth=0)
    vol_ax.set_ylim(0, max(float(np.max(vs)) * 1.15, 1.0))

    # 時刻刻度
    if str(series.market).upper() == "EM":
        tick_h = [9, 10, 11, 12, 13, 14, 15]
    else:
        tick_h = [9, 10, 11, 12, 13]
    tick_x = [(h - 9) * 60 for h in tick_h]
    tick_lab = [f"{h:02d}" for h in tick_h]
    for a in (ax, vol_ax):
        a.set_xticks(tick_x)
        a.tick_params(colors=MUTE, length=3, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(INK)
            sp.set_linewidth(0.95)
        a.grid(True, axis="both", color=RULE, linewidth=0.7, zorder=0)
    ax.set_xticklabels([])
    vol_ax.set_xticklabels(tick_lab, fontproperties=fp(10, False), color=MUTE)
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(10, False))
        lab.set_color(MUTE)
    vol_ax.set_yticks([])
    vol_ax.text(
        0.01,
        0.92,
        "量(張)",
        transform=vol_ax.transAxes,
        fontproperties=fp(9, False),
        color=MUTE,
        va="top",
        ha="left",
    )

    # 右側說明（無五檔／內外盤 — 無真 MIS 序列不畫）
    note_ax = fig.add_axes([0.78, 0.10, 0.18, 0.58])
    note_ax.set_xlim(0, 1)
    note_ax.set_ylim(0, 1)
    note_ax.axis("off")
    note_ax.add_patch(
        FancyBboxPatch(
            (0.0, 0.0),
            1.0,
            1.0,
            boxstyle="square,pad=0.01",
            facecolor=PAPER,
            edgecolor=RULE,
            linewidth=1.0,
            transform=note_ax.transAxes,
        )
    )
    # 長句手動折行，避免 matplotlib wrap 假開
    def _wrap(s: str, n: int = 14) -> List[str]:
        s = str(s or "").strip()
        if not s:
            return [""]
        out: List[str] = []
        while s:
            out.append(s[:n])
            s = s[n:]
        return out

    note_blocks: List[Tuple[str, bool]] = [("資料來源", True)]
    for part in _wrap(series.source, 18):
        note_blocks.append((part, False))
    note_blocks.append(("", False))
    for part in _wrap(series.label, 14):
        note_blocks.append((part, False))
    note_blocks.extend(
        [
            ("", False),
            (f"點數 {len(ys)}（1 分）", False),
            (f"首 {times[0].strftime('%H:%M')} → 末 {times[-1].strftime('%H:%M')}", False),
            ("", False),
            ("五檔／內外盤", False),
            ("無真 MIS 欄，不上", False),
            ("", False),
            ("不是買訊", True),
        ]
    )
    y = 0.96
    for line, heavy in note_blocks:
        if line:
            note_ax.text(
                0.06,
                y,
                line,
                fontproperties=fp(10 if heavy else 8.5, heavy),
                color=INK if heavy else MUTE,
                ha="left",
                va="top",
                transform=note_ax.transAxes,
            )
        y -= 0.055 if line else 0.028

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, facecolor=PAPER, edgecolor="none")
    plt.close(fig)
    return out_path


def default_out_dir() -> str:
    env = os.environ.get("WAYNE_INTRADAY_PREVIEW_DIR", "").strip()
    if env:
        return env
    # Project store media（本回合預覽交付）
    store = "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/intraday-open-close-chart-20261029"
    if os.path.isdir(os.path.dirname(store)):
        return store
    return os.path.join(_ROOT, "artifacts", "intraday-open-close-preview")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Preview ink 今日開→收（不接話筒）")
    ap.add_argument("--out-dir", default=default_out_dir())
    ap.add_argument("--db", default=os.path.join(_ROOT, "data", "wayne_market.db"))
    args = ap.parse_args(list(argv) if argv is not None else None)

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    for sid, name, market in PREVIEW_SYMBOLS:
        slug = _SLUG.get(sid, sid)
        out_path = os.path.join(out_dir, f"preview-{sid}-{slug}.png")
        series = fetch_yahoo_1m_today(sid, name, market, db_path=args.db)
        if series is None:
            render_empty(
                out_path,
                stock_id=sid,
                name=name,
                market=market,
                reason="Yahoo 1m 今日無可用點列",
            )
            results.append(
                {
                    "stock_id": sid,
                    "name": name,
                    "market": market,
                    "path": out_path,
                    "ok": False,
                    "source": None,
                    "n": 0,
                }
            )
            print(f"[empty] {sid} {name} -> {out_path}")
            continue
        render_path(series, out_path)
        results.append(
            {
                "stock_id": sid,
                "name": name,
                "market": market,
                "path": out_path,
                "ok": True,
                "source": series.source,
                "label": series.label,
                "n": len(series.closes),
                "prev": series.prev_close,
                "last": series.closes[-1],
                "t0": series.times[0].isoformat(),
                "t1": series.times[-1].isoformat(),
            }
        )
        print(
            f"[ok] {sid} {name} n={len(series.closes)} "
            f"{series.times[0].strftime('%H:%M')}→{series.times[-1].strftime('%H:%M')} "
            f"src={series.source} -> {out_path}"
        )

    manifest = os.path.join(out_dir, "preview-manifest-20261029.txt")
    with open(manifest, "w", encoding="utf-8") as f:
        f.write(f"as_of_taipei={datetime.now(TZ).isoformat()}\n")
        f.write("not_buy_signal=1\n")
        f.write("phone_wired=0\n")
        for r in results:
            f.write(
                f"{r['stock_id']}\t{r['name']}\t{r['market']}\tok={int(r['ok'])}\t"
                f"n={r['n']}\tsource={r.get('source') or '-'}\t{r['path']}\n"
            )
    print(f"[manifest] {manifest}")
    return 0 if all(r["ok"] for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
