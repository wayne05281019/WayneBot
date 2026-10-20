# -*- coding: utf-8 -*-
"""台股大盤附圖：美股四指數、台指電子盤、恐懼與貪婪。只畫官方成交，沒有走勢就不上圖。"""
from __future__ import annotations

import io
import logging
import math
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("WayneBot.SessionCards")

NY = ZoneInfo("America/New_York")
TP = ZoneInfo("Asia/Taipei")

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})

_US_SPECS = (
    ("dji", "^DJI", "道瓊"),
    ("spx", "^GSPC", "S&P500"),
    ("ixic", "^IXIC", "那斯達克"),
    ("sox", "^SOX", "費城半導體"),
)

_TAIFEX_OPENAPI = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
_TAIFEX_TICK_PAGE = "https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData"
_TAIFEX_ZIP = (
    "https://www.taifex.com.tw/file/taifex/Dailydownload/Dailydownload/Daily_{y}_{m}_{d}.zip"
)

_BG = "#1b1b1b"
_CARD = "#2c2c2c"
_UP = "#ef5350"
_DN = "#66bb6a"
_MUTED = "#e0e0e0"
_DASH = "#d0d0d0"
_TITLE = "#f5f5f5"


def _ymd_slash(ymd: str) -> str:
    s = str(ymd or "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return s


def _next_ymd(ymd: str) -> str:
    dt = datetime.strptime(ymd, "%Y%m%d") + timedelta(days=1)
    return dt.strftime("%Y%m%d")


def _is_weekend(ymd: str) -> bool:
    try:
        return datetime.strptime(ymd, "%Y%m%d").weekday() >= 5
    except ValueError:
        return True


def _cash_end(session_ymd: str) -> Tuple[int, int]:
    try:
        from us_holidays import lookup_us_session

        kind = (lookup_us_session(session_ymd) or {}).get("kind")
    except Exception:
        kind = "open"
    if kind == "early_close":
        return (13, 0)
    return (16, 0)


def _chart(sym: str, interval: str, range_: str) -> Dict[str, Any]:
    from urllib.parse import quote

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}"
        f"?interval={interval}&range={range_}"
    )
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = ((resp.json().get("chart") or {}).get("result") or [None])[0] or {}
    return result if isinstance(result, dict) else {}


def _daily_closes(block: Dict[str, Any]) -> List[Tuple[str, float]]:
    stamps = block.get("timestamp") or []
    closes = (((block.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out: List[Tuple[str, float]] = []
    for ts, cl in zip(stamps, closes):
        if cl is None:
            continue
        ymd = datetime.fromtimestamp(int(ts), NY).strftime("%Y%m%d")
        out.append((ymd, float(cl)))
    return out


def _intraday_closes(block: Dict[str, Any], session_ymd: str) -> List[float]:
    end_h, end_m = _cash_end(session_ymd)
    stamps = block.get("timestamp") or []
    closes = (((block.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out: List[float] = []
    for ts, cl in zip(stamps, closes):
        if cl is None:
            continue
        dt = datetime.fromtimestamp(int(ts), NY)
        if dt.strftime("%Y%m%d") != session_ymd:
            continue
        hm = (dt.hour, dt.minute)
        if hm < (9, 30) or hm > (end_h, end_m):
            continue
        out.append(float(cl))
    return out


def _fmt_num(val: float, *, integers: bool) -> str:
    if integers and abs(val - round(val)) < 1e-6:
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def _card(
    *,
    name: str,
    last: float,
    prev: float,
    series: Sequence[float],
    integers: bool = False,
    chg: Optional[float] = None,
    pct: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    pts = [float(x) for x in series if x is not None]
    if len(pts) < 2 or prev is None or prev <= 0 or last is None:
        return None
    if chg is None:
        chg = float(last) - float(prev)
    if pct is None:
        pct = chg / float(prev) * 100.0
    return {
        "name": name,
        "last": float(last),
        "prev": float(prev),
        "chg": float(chg),
        "pct": float(pct),
        "series": pts,
        "integers": integers,
    }


def fetch_us_cash_cards(
    now: Optional[datetime] = None, us_snap: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """美股現金盤走勢。只留預期交易日的 5 分收，週末不會畫出星期六。"""
    from us_overnight import expected_us_print_session

    session = expected_us_print_session(now)
    cards: List[Dict[str, Any]] = []
    missing: List[str] = []
    snap = us_snap or {}
    snap_sess = str(snap.get("us_session") or "").replace("-", "")[:8]
    snap_ok = bool(snap.get("ok")) and snap_sess == session and not snap.get("_press_miss")
    for key, sym, name in _US_SPECS:
        try:
            intra = _intraday_closes(_chart(sym, "5m", "5d"), session)
            daily = _daily_closes(_chart(sym, "1d", "10d"))
        except Exception:
            logger.exception("美股走勢抓不到 %s", sym)
            missing.append(name)
            continue
        prevs = [px for ymd, px in daily if ymd < session]
        sess_px = [px for ymd, px in daily if ymd == session]
        prev = prevs[-1] if prevs else None
        last = sess_px[-1] if sess_px else (intra[-1] if intra else None)
        chg = pct = None
        if snap_ok and snap.get(f"{key}_px") is not None and prev:
            last = float(snap[f"{key}_px"])
            if snap.get(f"{key}_chg") is not None:
                chg = float(snap[f"{key}_chg"])
            if snap.get(f"{key}_pct") is not None:
                pct = float(snap[f"{key}_pct"])
        got = _card(name=name, last=last, prev=prev, series=intra, chg=chg, pct=pct)
        if got is None:
            missing.append(name)
        else:
            cards.append(got)
    return {"session": session, "cards": cards, "missing": missing}


def latest_taifex_tick_zip_ymd(html: str) -> str:
    """下載頁由新到舊。檔名日期是歸屬交易日，不是走勢標題。"""
    marker = "Daily_"
    idx = html.find(marker)
    if idx < 0:
        return ""
    chunk = html[idx : idx + 24]
    parts = chunk.replace(".zip", "").split("_")
    if len(parts) < 4:
        return ""
    y, m, d = parts[1], parts[2], parts[3][:2]
    if len(y) == 4 and len(m) == 2 and len(d) == 2 and f"{y}{m}{d}".isdigit():
        return f"{y}{m}{d}"
    return ""


def parse_tx_night_ticks(text: str) -> List[Tuple[str, str, str, float, int]]:
    """期交所逐筆：TX 夜盤（15:00 起，跨日 05:00 前）。價差月份不要。"""
    out: List[Tuple[str, str, str, float, int]] = []
    for i, ln in enumerate(text.splitlines()):
        if i == 0 or "TX" not in ln:
            continue
        p = ln.split(",")
        if len(p) < 6:
            continue
        if p[1].strip() != "TX":
            continue
        month = p[2].strip()
        if not month or "/" in month:
            continue
        stamp = p[3].strip()
        if len(stamp) < 6 or not (stamp >= "150000" or stamp < "050000"):
            continue
        try:
            px = float(p[4])
            qty = int(float(p[5]))
        except ValueError:
            continue
        if px <= 0:
            continue
        out.append((p[0].strip(), month, stamp, px, qty))
    return out


def build_tx_night_card(
    ticks: Sequence[Tuple[str, str, str, float, int]],
    prev_close: Optional[float],
) -> Optional[Dict[str, Any]]:
    evening = [t for t in ticks if t[2] >= "150000"]
    if not evening or prev_close is None or prev_close <= 0:
        return None
    session = min(t[0] for t in evening)
    if len(session) != 8 or _is_weekend(session):
        return None
    nxt = _next_ymd(session)
    kept = [
        t
        for t in ticks
        if (t[0] == session and t[2] >= "150000") or (t[0] == nxt and t[2] < "050000")
    ]
    vol: Dict[str, int] = {}
    for _d, month, _t, _px, qty in kept:
        vol[month] = vol.get(month, 0) + int(qty)
    if not vol:
        return None
    month = max(vol, key=lambda m: vol[m])
    front = [t for t in kept if t[1] == month]
    front.sort(key=lambda t: (0 if t[2] >= "150000" else 1, t[0], t[2]))
    buckets: Dict[Tuple[int, str, int, int], float] = {}
    for d, _m, stamp, px, _q in front:
        hh = int(stamp[:2])
        mm = int(stamp[2:4]) // 5 * 5
        buckets[(0 if stamp >= "150000" else 1, d, hh, mm)] = px
    series = [buckets[k] for k in sorted(buckets)]
    vol_buckets: Dict[Tuple[int, str, int, int], int] = {}
    for d, _m, stamp, _px, qty in front:
        hh = int(stamp[:2])
        mm = int(stamp[2:4]) // 5 * 5
        key = (0 if stamp >= "150000" else 1, d, hh, mm)
        vol_buckets[key] = vol_buckets.get(key, 0) + int(qty)
    volumes = [int(vol_buckets.get(k, 0)) for k in sorted(buckets)]
    last_stamp = front[-1][2]
    card = _card(
        name="台指電子盤",
        last=front[-1][3],
        prev=float(prev_close),
        series=series,
        integers=True,
    )
    if card is None:
        return None
    card["session"] = session
    card["month"] = month
    card["volumes"] = volumes
    card["asof_time"] = f"{last_stamp[:2]}:{last_stamp[2:4]}:{last_stamp[4:6]}"
    card["volume"] = int(sum(volumes))
    return card


def _read_tick_zip(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name)
    for enc in ("cp950", "big5", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", errors="replace")


def _regular_settlement(session_ymd: str, month: str) -> Optional[float]:
    try:
        resp = _SESSION.get(_TAIFEX_OPENAPI, timeout=40)
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        logger.exception("台指期結算抓不到")
        return None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if str(row.get("Contract") or "").strip().upper() != "TX":
            continue
        if str(row.get("TradingSession") or "") != "一般":
            continue
        if str(row.get("Date") or "") != session_ymd:
            continue
        if str(row.get("ContractMonth(Week)") or "").strip() != month:
            continue
        raw = str(row.get("SettlementPrice") or "").replace(",", "").strip()
        try:
            px = float(raw)
        except ValueError:
            return None
        return px if px > 0 else None
    return None


def fetch_tx_after_hours_card(now: Optional[datetime] = None) -> Dict[str, Any]:
    """最新一檔期交所逐筆夜盤。沒有 15:00 起的官方成交就不上圖。"""
    _ = now
    try:
        page = _SESSION.get(_TAIFEX_TICK_PAGE, timeout=30)
        page.raise_for_status()
        ymd = latest_taifex_tick_zip_ymd(page.text)
        if len(ymd) != 8:
            return {"card": None, "missing": True}
        url = _TAIFEX_ZIP.format(y=ymd[:4], m=ymd[4:6], d=ymd[6:])
        blob = _SESSION.get(url, timeout=40)
        blob.raise_for_status()
        ticks = parse_tx_night_ticks(_read_tick_zip(blob.content))
    except Exception:
        logger.exception("台指期盤後走勢抓不到")
        return {"card": None, "missing": True}
    evening = [t for t in ticks if t[2] >= "150000"]
    if not evening:
        return {"card": None, "missing": True}
    session = min(t[0] for t in evening)
    if _is_weekend(session):
        return {"card": None, "missing": True}
    nxt = _next_ymd(session)
    kept = [
        t
        for t in ticks
        if (t[0] == session and t[2] >= "150000") or (t[0] == nxt and t[2] < "050000")
    ]
    vol: Dict[str, int] = {}
    for _d, month, _t, _px, qty in kept:
        vol[month] = vol.get(month, 0) + int(qty)
    if not vol:
        return {"card": None, "missing": True}
    month = max(vol, key=lambda m: vol[m])
    prev = _regular_settlement(session, month)
    card = build_tx_night_card(ticks, prev)
    return {"card": card, "missing": card is None}


def fetch_vix_card(us_snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """恐慌指數＝VIX 官方日收。沒有兩根以上真收就不組卡，不准畫假線。"""
    try:
        daily = _daily_closes(_chart("^VIX", "1d", "6mo"))
    except Exception:
        logger.exception("恐慌指數走勢抓不到")
        return {"card": None, "missing": True, "source": ""}
    daily = [(ymd, px) for ymd, px in daily if px and px > 0]
    if len(daily) < 2:
        return {"card": None, "missing": True, "source": ""}
    daily = daily[-40:]
    session = daily[-1][0]
    series = [px for _, px in daily]
    last = float(series[-1])
    prev = float(series[-2])
    snap = us_snap or {}
    snap_sess = str(snap.get("us_session") or "").replace("-", "")[:8]
    snap_vix = snap.get("vix")
    if snap_sess == session and snap_vix is not None:
        try:
            pinned = float(snap_vix)
        except (TypeError, ValueError):
            pinned = 0.0
        if pinned > 0:
            last = pinned
            series[-1] = pinned
    card = _card(name="恐慌指數", last=last, prev=prev, series=series, integers=False)
    if not card:
        return {"card": None, "missing": True, "source": "yahoo_vix"}
    card["session"] = session
    return {"card": card, "missing": False, "source": "yahoo_vix"}


def assemble_session_cards(
    now: Optional[datetime] = None,
    us_snap: Optional[Dict[str, Any]] = None,
    cnn_fear: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    us = fetch_us_cash_cards(now, us_snap)
    tx = fetch_tx_after_hours_card(now)
    fear = cnn_fear if isinstance(cnn_fear, dict) else (us_snap or {}).get("cnn_fear")
    if not isinstance(fear, dict) or fear.get("score") is None:
        fear = None
    return {
        "us": us,
        "tx": tx,
        "fear": fear,
        "notes": omission_lines(us, tx, fear),
    }


def omission_lines(
    us: Dict[str, Any],
    tx: Dict[str, Any],
    fear: Optional[Dict[str, Any]] = None,
) -> List[str]:
    lines = [f"{name}這次沒有官方走勢，不上圖" for name in (us or {}).get("missing") or []]
    if (tx or {}).get("missing") or not ((tx or {}).get("card") or {}).get("series"):
        lines.append("台指電子盤這次沒有官方走勢，不上圖")
    if fear is None:
        lines.append("恐懼與貪婪指數這次沒有官方讀數，不上圖")
    return lines


def session_card_jobs(bundle: Optional[Dict[str, Any]]) -> List[Tuple[str, Any]]:
    """送圖順序硬鎖：美股四大 → 台指電子盤 → 恐懼與貪婪。"""
    bundle = bundle or {}
    jobs: List[Tuple[str, Any]] = []
    us = bundle.get("us") or {}
    if us.get("cards"):
        sess = str(us.get("session") or "")
        head = (
            f"美股收盤　{sess[:4]}/{sess[4:6]}/{sess[6:8]}"
            if len(sess) == 8
            else "美股收盤"
        )
        jobs.append(("us", {"cards": us["cards"], "heading": head, "columns": 2, "layout": "grid"}))
    tx = bundle.get("tx") or {}
    tx_card = tx.get("card")
    if tx_card and tx_card.get("series"):
        sess = str(tx_card.get("session") or "")
        head = (
            f"台指電子盤　{sess[:4]}/{sess[4:6]}/{sess[6:8]}"
            if len(sess) == 8
            else "台指電子盤"
        )
        jobs.append(("tx", {"cards": [tx_card], "heading": head, "columns": 1, "layout": "board"}))
    fear = bundle.get("fear")
    if isinstance(fear, dict) and fear.get("score") is not None:
        sess = str(fear.get("session") or "")
        head = (
            f"恐懼與貪婪指數　{sess[:4]}/{sess[4:6]}/{sess[6:8]}"
            if len(sess) == 8
            else "恐懼與貪婪指數"
        )
        jobs.append(("fear", {"fear": fear, "heading": head}))
    return jobs


def _side_color(chg: float) -> str:
    if chg > 0:
        return _UP
    if chg < 0:
        return _DN
    return _MUTED


def _draw_spark(ax, series: Sequence[float], prev: float) -> None:
    import numpy as np

    ys = np.asarray(series, dtype=float)
    xs = np.arange(len(ys), dtype=float)
    lo = float(min(ys.min(), prev))
    hi = float(max(ys.max(), prev))
    pad = max((hi - lo) * 0.12, abs(prev) * 0.001)
    ax.set_xlim(-0.2, max(len(ys) - 1, 1) + 0.2)
    ax.set_ylim(lo - pad, hi + pad)
    ax.axhline(prev, color=_DASH, linestyle=(0, (4, 3)), linewidth=1.3, zorder=2)
    ax.fill_between(xs, prev, ys, where=ys >= prev, interpolate=True, color=_UP, alpha=0.35, zorder=1)
    ax.fill_between(xs, prev, ys, where=ys <= prev, interpolate=True, color=_DN, alpha=0.35, zorder=1)
    # 跨過昨收的那一段跟填充同一顏色，不另畫一條混色線。
    for i in range(len(ys) - 1):
        y0, y1 = float(ys[i]), float(ys[i + 1])
        if (y0 >= prev and y1 >= prev) or (y0 < prev and y1 < prev):
            ax.plot([xs[i], xs[i + 1]], [y0, y1], color=_side_color(y0 - prev) if y0 != prev else _side_color(y1 - prev), lw=2.2, solid_capstyle="round", zorder=3)
        else:
            if y1 == y0:
                continue
            x_cross = xs[i] + (prev - y0) / (y1 - y0)
            ax.plot([xs[i], x_cross], [y0, prev], color=_side_color(y0 - prev), lw=2.2, zorder=3)
            ax.plot([x_cross, xs[i + 1]], [prev, y1], color=_side_color(y1 - prev), lw=2.2, zorder=3)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_facecolor(_CARD)


def _draw_volume_bars(ax, volumes: Sequence[float], series: Sequence[float], prev: float) -> None:
    import numpy as np

    vols = np.asarray([max(0.0, float(v or 0)) for v in volumes], dtype=float)
    ys = np.asarray(list(series), dtype=float)
    if len(vols) != len(ys) or len(ys) < 2:
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_facecolor(_CARD)
        return
    xs = np.arange(len(vols), dtype=float)
    vmax = float(vols.max()) if vols.max() > 0 else 1.0
    colors = [_side_color(float(y) - float(prev)) for y in ys]
    ax.bar(xs, vols, width=0.8, color=colors, alpha=0.85, zorder=2)
    ax.set_xlim(-0.6, max(len(vols) - 1, 1) + 0.6)
    ax.set_ylim(0, vmax * 1.15)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_facecolor(_CARD)


def render_session_cards(
    path: str,
    cards: Sequence[Dict[str, Any]],
    *,
    heading: str,
    columns: int,
    layout: str = "grid",
) -> str:
    """手機縮圖要看得清：字大、標跟數字分開、昨收是虛線。"""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from wayne_navigator import _fp

    got = [c for c in cards if c and c.get("series")]
    if not got:
        return ""
    cols = max(1, min(columns, len(got)))
    rows = (len(got) + cols - 1) // cols
    fig_w = 9.2 if cols == 1 else 10.2
    dpi = 130
    head_in = 0.55
    row_h = 6.85 if cols == 1 else 3.75
    fig_h = head_in + rows * row_h + 0.28
    # 單張台指電子盤是橫圖。畫布太扁會被直式查股門檻（高 900、48KB）整張丟掉。
    if cols == 1 and layout not in ("spark",):
        fig_h = max(fig_h, 960 / dpi)
    if layout == "spark":
        dpi = 140
        fig_w = 9.2
        fig_h = 4.05
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=_BG)
    fig.text(
        0.045,
        1 - (0.28 / fig_h),
        heading,
        color=_TITLE,
        fontproperties=_fp(24, "bold"),
        ha="left",
        va="top",
    )
    gap_x = 0.03
    gap_y = 0.025
    top = 1 - (head_in / fig_h)
    bottom = 0.03
    grid_h = top - bottom
    card_w = (1 - gap_x * (cols + 1)) / cols
    card_h = (grid_h - gap_y * (rows + 1)) / rows
    for i, card in enumerate(got):
        r, c = divmod(i, cols)
        x = gap_x + c * (card_w + gap_x)
        y = top - gap_y - (r + 1) * card_h - r * gap_y
        ax = fig.add_axes([x, y, card_w, card_h])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_facecolor(_CARD)
        ax.add_patch(
            FancyBboxPatch(
                (0, 0),
                1,
                1,
                boxstyle="round,pad=0.012,rounding_size=0.04",
                facecolor=_CARD,
                edgecolor=_CARD,
                transform=ax.transAxes,
                mutation_aspect=card_w / card_h * fig_w / fig_h,
            )
        )
        col = _side_color(float(card["chg"]))
        integers = bool(card.get("integers"))
        arrow = "▲" if card["chg"] > 0 else ("▼" if card["chg"] < 0 else "")
        chg_abs = _fmt_num(abs(float(card["chg"])), integers=integers)
        board = layout == "board" and cols == 1
        fp_name = _fp(22 if cols > 1 else 26, "bold")
        fp_px = _fp(34 if cols > 1 else 44, "bold")
        fp_meta = _fp(17 if cols > 1 else 22, "bold")
        ax.text(0.06, 0.90, card["name"], color=_TITLE, fontproperties=fp_name, ha="left", va="top")
        ax.text(0.94, 0.90, f"{arrow}{chg_abs}", color=col, fontproperties=fp_meta, ha="right", va="top")
        ax.text(
            0.06,
            0.70 if board else 0.68,
            _fmt_num(float(card["last"]), integers=integers),
            color=col,
            fontproperties=fp_px,
            ha="left",
            va="center",
        )
        ax.text(
            0.94,
            0.70 if board else 0.68,
            f"({float(card['pct']):+.2f}%)",
            color=col,
            fontproperties=fp_meta,
            ha="right",
            va="center",
        )
        if board:
            meta_bits = []
            if card.get("asof_time"):
                meta_bits.append(str(card["asof_time"]))
            if card.get("volume") is not None:
                meta_bits.append(f"量 {int(card['volume']):,}")
            if meta_bits:
                ax.text(
                    0.06,
                    0.56,
                    "　".join(meta_bits),
                    color=_MUTED,
                    fontproperties=_fp(16, "bold"),
                    ha="left",
                    va="center",
                )
            spark = fig.add_axes([x + card_w * 0.06, y + card_h * 0.22, card_w * 0.88, card_h * 0.28])
            _draw_spark(spark, card["series"], float(card["prev"]))
            vols = card.get("volumes") or []
            if vols:
                vol_ax = fig.add_axes(
                    [x + card_w * 0.06, y + card_h * 0.06, card_w * 0.88, card_h * 0.14]
                )
                _draw_volume_bars(vol_ax, vols, card["series"], float(card["prev"]))
        else:
            spark = fig.add_axes(
                [x + card_w * 0.06, y + card_h * 0.08, card_w * 0.88, card_h * 0.40]
            )
            _draw_spark(spark, card["series"], float(card["prev"]))
    fig.savefig(path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return path


_FEAR_BAND_COLORS = (
    (0.0, 25.0, "#e53935", "極度恐懼"),
    (25.0, 45.0, "#ef6c00", "恐懼"),
    (45.0, 55.0, "#f9a825", "中立"),
    (55.0, 75.0, "#7cb342", "貪婪"),
    (75.0, 100.0, "#2e7d32", "極度貪婪"),
)


def render_fear_greed_gauge(
    path: str,
    fear: Dict[str, Any],
    *,
    heading: str,
) -> str:
    """CNN 風格半圓指針＋中文檔位＋官方歷史列。沒分數就不畫。"""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Wedge

    from wayne_navigator import _fp

    score = fear.get("score")
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return ""
    if score_f < 0 or score_f > 100:
        return ""
    from cnn_fear import gauge_face

    face = str(fear.get("face") or gauge_face(score_f))
    band = str(fear.get("band") or "")
    hist = [h for h in (fear.get("history") or []) if isinstance(h, dict)]

    dpi = 140
    fig_w, fig_h = 9.2, 7.2
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=_BG)
    fig.text(
        0.045,
        1 - (0.30 / fig_h),
        heading,
        color=_TITLE,
        fontproperties=_fp(24, "bold"),
        ha="left",
        va="top",
    )
    panel = fig.add_axes([0.06, 0.08, 0.88, 0.82])
    panel.set_xlim(0, 1)
    panel.set_ylim(0, 1)
    panel.axis("off")
    panel.set_facecolor(_CARD)
    panel.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.03",
            facecolor=_CARD,
            edgecolor=_CARD,
            transform=panel.transAxes,
        )
    )

    gauge = fig.add_axes([0.14, 0.38, 0.72, 0.48])
    gauge.set_xlim(-1.25, 1.25)
    gauge.set_ylim(-0.25, 1.25)
    gauge.set_aspect("equal")
    gauge.axis("off")
    gauge.set_facecolor(_CARD)

    def _ang(val: float) -> float:
        # 0 → 180°（左），100 → 0°（右），與 CNN 半圓一致。
        return 180.0 - (max(0.0, min(100.0, val)) / 100.0) * 180.0

    for lo, hi, color, lab in _FEAR_BAND_COLORS:
        wedge = Wedge(
            (0, 0),
            1.0,
            _ang(hi),
            _ang(lo),
            width=0.34,
            facecolor=color,
            edgecolor=_BG,
            linewidth=1.2,
            alpha=0.92,
        )
        gauge.add_patch(wedge)
        mid = (lo + hi) / 2.0
        rad = math.radians(_ang(mid))
        lx, ly = 1.12 * math.cos(rad), 1.12 * math.sin(rad)
        gauge.text(lx, ly, lab, color=_TITLE, fontproperties=_fp(12, "bold"), ha="center", va="center")

    for tick in (0, 25, 50, 75, 100):
        rad = math.radians(_ang(tick))
        gauge.plot(
            [0.62 * math.cos(rad), 1.0 * math.cos(rad)],
            [0.62 * math.sin(rad), 1.0 * math.sin(rad)],
            color=_BG,
            lw=1.0,
            alpha=0.7,
            zorder=3,
        )
        gauge.text(
            1.22 * math.cos(rad),
            1.22 * math.sin(rad) - (0.06 if tick in (0, 100) else 0),
            str(tick),
            color=_MUTED,
            fontproperties=_fp(11, "bold"),
            ha="center",
            va="center",
        )

    prad = math.radians(_ang(score_f))
    gauge.plot(
        [0, 0.78 * math.cos(prad)],
        [0, 0.78 * math.sin(prad)],
        color="#111111",
        lw=4.5,
        solid_capstyle="round",
        zorder=5,
    )
    gauge.plot(0, 0, "o", color="#111111", markersize=10, zorder=6)
    gauge.text(0, -0.08, face, color=_TITLE, fontproperties=_fp(40, "bold"), ha="center", va="top")
    if band:
        gauge.text(0, -0.22, band, color=_MUTED, fontproperties=_fp(16, "bold"), ha="center", va="top")

    y0 = 0.30
    panel.text(0.08, y0 + 0.04, "歷史", color=_TITLE, fontproperties=_fp(16, "bold"), ha="left", va="top")
    if hist:
        for i, row in enumerate(hist[:4]):
            yy = y0 - 0.06 - i * 0.055
            panel.text(
                0.08,
                yy,
                str(row.get("label") or ""),
                color=_MUTED,
                fontproperties=_fp(14, "bold"),
                ha="left",
                va="center",
            )
            panel.text(
                0.55,
                yy,
                str(row.get("face") or ""),
                color=_TITLE,
                fontproperties=_fp(16, "bold"),
                ha="right",
                va="center",
            )
            panel.text(
                0.92,
                yy,
                str(row.get("band") or ""),
                color=_MUTED,
                fontproperties=_fp(14, "bold"),
                ha="right",
                va="center",
            )
    else:
        panel.text(
            0.08,
            y0 - 0.06,
            "（本日無官方歷史列）",
            color=_MUTED,
            fontproperties=_fp(13, "bold"),
            ha="left",
            va="center",
        )

    fig.savefig(path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return path


def paint_session_job(path: str, kind: str, spec: Dict[str, Any]) -> str:
    """統一出圖入口：美股 grid／台指電子盤／恐懼貪婪儀表。"""
    if kind == "fear":
        return render_fear_greed_gauge(path, spec.get("fear") or {}, heading=str(spec.get("heading") or "恐懼與貪婪指數"))
    return render_session_cards(
        path,
        spec.get("cards") or [],
        heading=str(spec.get("heading") or ""),
        columns=int(spec.get("columns") or 1),
        layout=str(spec.get("layout") or "grid"),
    )
