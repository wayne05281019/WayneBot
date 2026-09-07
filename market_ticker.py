"""大盤頁頂部時段跑馬燈。Telegram 氣泡不能捲字，改送循環 GIF。

沒接到的市場不寫。加權／櫃買用證交所 MIS 最後一筆（delay=0）；
台指期用期交所即時報價，沒接到才退庫內；
日經／韓國／滬指與美股指數／盤前期貨用 Yahoo 1 分鐘 spark（與隔夜美股同一路）。
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("WayneBot.MarketTicker")

TW = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")

# 名稱, Yahoo 代號（沒有官方即時列才走這條）
ASIA_INDEX = (
    ("日經", "^N225"),
    ("韓國", "^KS11"),
    ("滬指", "000001.SS"),
)
US_CASH = (
    ("道瓊", "^DJI"),
    ("標普", "^GSPC"),
    ("那斯達克", "^IXIC"),
    ("費半", "^SOX"),
)
US_PRE_FUT = (
    ("標普期", "ES=F"),
    ("那斯達克期", "NQ=F"),
    ("道瓊期", "YM=F"),
)

SLOT_TITLE = {
    "tw_open": "台股開盤",
    "asia_pm": "亞股午後",
    "us_pre": "美股盤前",
    "us_night": "美股時段",
    "weekend": "休市對照",
}

_UP = (232, 72, 72)
_DOWN = (46, 168, 96)
_INK = (236, 242, 248)
_MUTED = (168, 186, 204)
_BG = (18, 26, 38)
_LABEL_BG = (28, 52, 78)
_LABEL_FG = (140, 210, 255)
_RULE = (70, 96, 122)

_TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
_YAHOO_SPARK = "https://query1.finance.yahoo.com/v8/finance/spark"

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
)
_TAIFEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://mis.taifex.com.tw",
    "Referer": "https://mis.taifex.com.tw/",
}


def ticker_slot(now: Optional[datetime] = None) -> str:
    """依台北時段＋美股盤別決定跑馬燈。週六凌晨若美股現金還在，仍走美股時段。"""
    from config import taipei_now
    from trading_calendar import is_tw_equity_session, is_tw_market_holiday

    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW)
    else:
        dt = dt.astimezone(TW)
    if is_tw_equity_session(dt):
        return "tw_open"
    t = dt.time()
    tw_off = dt.weekday() >= 5 or is_tw_market_holiday(dt.strftime("%Y%m%d"))
    if not tw_off:
        if dt_time(13, 30) < t < dt_time(16, 0):
            return "asia_pm"
        if dt_time(16, 0) <= t < dt_time(21, 30):
            return "us_pre"
    try:
        from us_overnight import us_tape_phase

        if us_tape_phase(dt) in ("regular", "post"):
            return "us_night"
    except Exception:
        pass
    if not tw_off and (t >= dt_time(21, 30) or t < dt_time(9, 0)):
        return "us_night"
    return "weekend"


def _fmt_px(px: float) -> str:
    if abs(px) >= 1000:
        return f"{px:,.0f}"
    if abs(px) >= 100:
        return f"{px:,.1f}"
    return f"{px:,.2f}"


def _fmt_pct(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    return f"{pct:+.2f}%"


def _seg(name: str, px=None, pct=None, extra: str = "") -> Optional[Dict[str, Any]]:
    if extra:
        side_pct = 1.0 if extra == "漲" else (-1.0 if extra == "跌" else None)
        return {"name": name, "text": f"{name} {extra}", "pct": side_pct}
    if px is None:
        return None
    body = f"{name} {_fmt_px(float(px))}"
    p = None if pct is None else float(pct)
    if p is not None:
        body += f" {_fmt_pct(p)}"
    return {"name": name, "text": body, "pct": p, "px": float(px)}


def _yahoo_quote(sym: str, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1m&range=1d&includePrePost=true"
    )
    try:
        resp = _SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        return _quote_from_yahoo_chart(result[0], sym)
    except Exception:
        logger.debug("跑馬燈 Yahoo 沒接到 %s", sym, exc_info=True)
        return None


def _last_non_null(vals) -> Optional[float]:
    for v in reversed(list(vals or [])):
        if v is None:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if n == n:  # not NaN
            return n
    return None


def _quote_from_yahoo_chart(block: Dict[str, Any], sym: str) -> Optional[Dict[str, Any]]:
    meta = (block or {}).get("meta") or {}
    qblock = (((block or {}).get("indicators") or {}).get("quote") or [{}])[0]
    last_1m = _last_non_null((qblock or {}).get("close"))
    px = last_1m
    if px is None:
        try:
            px = float(meta.get("regularMarketPrice"))
        except (TypeError, ValueError):
            px = None
    if px is None or px <= 0:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    pct = meta.get("regularMarketChangePercent")
    if prev_f and prev_f > 0:
        pct = (px - prev_f) / prev_f * 100.0
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    return {"px": px, "pct": pct_f, "symbol": meta.get("symbol") or sym}


def _quote_from_spark_block(block: Dict[str, Any], sym: str) -> Optional[Dict[str, Any]]:
    last_1m = _last_non_null((block or {}).get("close"))
    px = last_1m
    if px is None:
        try:
            px = float(block.get("fulldayPrice"))
        except (TypeError, ValueError):
            px = None
    if px is None or px <= 0:
        return None
    prev = block.get("chartPreviousClose") or block.get("previousClose")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    pct = block.get("fulldayChangePercent")
    if last_1m is not None and prev_f and prev_f > 0:
        pct = (last_1m - prev_f) / prev_f * 100.0
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    return {"px": float(px), "pct": pct_f, "symbol": block.get("symbol") or sym}


def _yahoo_spark(pairs: Tuple[Tuple[str, str], ...], timeout: float = 2.4) -> List[Dict[str, Any]]:
    """一次抓多檔 1 分鐘 spark；沒接到的不寫。失敗再逐檔 1 分鐘圖。"""
    if not pairs:
        return []
    syms = [sym for _n, sym in pairs]
    by_sym: Dict[str, Dict[str, Any]] = {}
    try:
        resp = _SESSION.get(
            _YAHOO_SPARK,
            params={"symbols": ",".join(syms), "range": "1d", "interval": "1m"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        for sym in syms:
            block = payload.get(sym)
            if not isinstance(block, dict):
                continue
            q = _quote_from_spark_block(block, sym)
            if q:
                by_sym[sym] = q
    except Exception:
        logger.debug("跑馬燈 Yahoo spark 失敗", exc_info=True)
    missing = [(name, sym) for name, sym in pairs if sym not in by_sym]
    if missing:
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as ex:
            futs = {ex.submit(_yahoo_quote, sym, timeout): (name, sym) for name, sym in missing}
            for fut in as_completed(futs):
                name, sym = futs[fut]
                try:
                    q = fut.result()
                except Exception:
                    q = None
                if q:
                    by_sym[sym] = q
    out: List[Dict[str, Any]] = []
    for name, sym in pairs:
        q = by_sym.get(sym)
        if not q:
            continue
        seg = _seg(name, q.get("px"), q.get("pct"))
        if seg:
            out.append(seg)
    return out


def _yahoo_many(pairs: Tuple[Tuple[str, str], ...], timeout: float = 2.4) -> List[Dict[str, Any]]:
    return _yahoo_spark(pairs, timeout=timeout)


def _tw_index_seg(live: Optional[Dict[str, Any]], snap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    live = live or {}
    snap = snap or {}
    px = float(live.get("close") or 0) or float(snap.get("close") or 0)
    if px <= 0:
        return None
    pct = live.get("pct_change")
    if pct is None:
        pct = snap.get("chg1_pct")
    return _seg("加權", px, pct)


def _tx_seg(snap: Optional[Dict[str, Any]], *, night: bool = False, live: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if live and float(live.get("close") or 0) > 0:
        label = "台指期夜盤" if night else "台指期"
        return _seg(label, live.get("close"), live.get("pct_change"))
    snap = snap or {}
    fut = (snap.get("futures_night") if night else None) or snap.get("futures") or {}
    if night:
        from taiwan_market import resolve_futures_night

        db = snap.get("_db_path")
        night_row = snap.get("futures_night")
        if not night_row and db:
            try:
                night_row = resolve_futures_night(db, snap.get("as_of"))
            except Exception:
                night_row = None
        fut = night_row or fut
    px = float((fut or {}).get("close") or 0)
    if px <= 0:
        return None
    pct = fut.get("pct_change")
    label = "台指期夜盤" if night else "台指期"
    return _seg(label, px, pct)


def _num_or_none(val) -> Optional[float]:
    s = str(val or "").replace(",", "").replace("+", "").replace("%", "").strip()
    if s in ("", "-", "--", "N/A", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick_tx_quote_row(rows: List[Dict[str, Any]], *, night: bool) -> Optional[Dict[str, Any]]:
    """近月臺指期：日盤 *-F、夜盤 *-M。量最大者；沒量就取第一筆有成交價的。"""
    suffix = "-M" if night else "-F"
    cands: List[Tuple[float, Dict[str, Any]]] = []
    for row in rows or []:
        sid = str(row.get("SymbolID") or "")
        if not sid.startswith("TXF") or sid.endswith("-S") or sid.endswith("-P"):
            continue
        if not sid.endswith(suffix):
            continue
        px = _num_or_none(row.get("CLastPrice"))
        if not px or px <= 0:
            continue
        vol = _num_or_none(row.get("CTotalVolume")) or 0.0
        cands.append((vol, row))
    if not cands:
        return None
    cands.sort(key=lambda kv: kv[0], reverse=True)
    return cands[0][1]


def fetch_tx_live(*, night: bool = False, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    """期交所即時報價（不寫庫）。沒接到回 None。"""
    payload = {
        "MarketType": "1" if night else "0",
        "SymbolType": "F",
        "KindID": "1",
        "CID": "",
        "ExpireMonth": "",
        "SymbolID": "",
        "Fcode": "",
    }
    try:
        resp = requests.post(
            _TAIFEX_QUOTE_URL,
            json=payload,
            headers=_TAIFEX_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        rows = ((resp.json() or {}).get("RtData") or {}).get("QuoteList") or []
        row = pick_tx_quote_row(rows, night=night)
        if not row:
            return None
        px = _num_or_none(row.get("CLastPrice"))
        if not px or px <= 0:
            return None
        pct = _num_or_none(row.get("CDiffRate"))
        t = str(row.get("CTime") or "").strip()
        clock = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
        return {
            "close": px,
            "pct_change": pct,
            "update_time": clock,
            "symbol": row.get("SymbolID"),
            "is_realtime": True,
        }
    except Exception:
        logger.debug("跑馬燈期交所即時失敗 night=%s", night, exc_info=True)
        return None


def _us_from_snap(us: Dict[str, Any], keys) -> List[Dict[str, Any]]:
    out = []
    mapping = (
        ("道瓊", "dji_px", "dji_pct"),
        ("標普", "spx_px", "spx_pct"),
        ("那斯達克", "ixic_px", "ixic_pct"),
        ("費半", "sox_px", "sox_pct"),
        ("標普期", "es_f_px", "es_f_pct"),
        ("那斯達克期", "nq_f_px", "nq_f_pct"),
        ("道瓊期", "ym_f_px", "ym_f_pct"),
    )
    want = set(keys)
    for name, px_k, pct_k in mapping:
        if name not in want:
            continue
        px = us.get(px_k)
        pct = us.get(pct_k)
        if px is None and pct is None:
            continue
        if px is None:
            # 只有漲跌％也寫，不編造價格
            out.append({"name": name, "text": f"{name} {_fmt_pct(pct)}", "pct": pct})
        else:
            seg = _seg(name, px, pct)
            if seg:
                out.append(seg)
    return out


def _load_us(db_path: str) -> Dict[str, Any]:
    try:
        from us_overnight import load_us_overnight
        from taiwan_market import resolve_market_as_of

        as_of = resolve_market_as_of(db_path)
        us = load_us_overnight(db_path, as_of) if as_of else {}
        if us.get("ok") or us.get("vix") is not None or us.get("dji_pct") is not None:
            return us
    except Exception:
        logger.debug("跑馬燈讀美股快取失敗", exc_info=True)
    return {}


def collect_ticker(
    db_path: str = None,
    *,
    live: Optional[Dict[str, Any]] = None,
    snap: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    yahoo: bool = True,
    live_otc: Optional[Dict[str, Any]] = None,
    live_tx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """組時段項目。yahoo=False 時不打外網（Yahoo／期交所即時）。"""
    from config import taipei_now

    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW)
    else:
        dt = dt.astimezone(TW)
    slot = ticker_slot(dt)
    title = SLOT_TITLE[slot]
    snap = dict(snap or {})
    if db_path:
        snap["_db_path"] = db_path
    items: List[Dict[str, Any]] = []
    clock = dt.strftime("%H:%M:%S")
    items.append({"name": "此刻", "text": clock, "pct": None})

    if yahoo:
        try:
            from live_quote import fetch_mis_index_quote, fetch_mis_otc_index_quote

            if live is None or not float((live or {}).get("close") or 0):
                live = fetch_mis_index_quote(fresh=True, require_session=False) or live
            if live_otc is None:
                live_otc = fetch_mis_otc_index_quote(fresh=True)
            if live_tx is None:
                live_tx = fetch_tx_live(night=(slot in ("us_pre", "us_night")))
        except Exception:
            logger.debug("跑馬燈補即時失敗", exc_info=True)

    night_tx = slot in ("us_pre", "us_night")

    if slot in ("tw_open", "asia_pm", "weekend"):
        tw = _tw_index_seg(live, snap)
        if tw:
            items.append(tw)
        otc = _seg("櫃買", (live_otc or {}).get("close"), (live_otc or {}).get("pct_change")) if live_otc else None
        if otc:
            items.append(otc)
        tx = _tx_seg(snap, night=False, live=live_tx if not night_tx else None)
        if tx:
            items.append(tx)
        if yahoo and slot != "weekend":
            items.extend(_yahoo_many(ASIA_INDEX))

    if slot == "us_pre":
        if yahoo:
            fut = _yahoo_many(US_PRE_FUT)
            if not fut:
                us = _load_us(db_path) if db_path else {}
                fut = _us_from_snap(us, ("標普期", "那斯達克期", "道瓊期"))
            items.extend(fut)
        else:
            us = _load_us(db_path) if db_path else {}
            items.extend(_us_from_snap(us, ("標普期", "那斯達克期", "道瓊期")))
        tw = _tw_index_seg(live, snap)
        if tw:
            items.append(tw)
        tx = _tx_seg(snap, night=True, live=live_tx)
        if tx:
            items.append(tx)

    if slot == "us_night":
        cash: List[Dict[str, Any]] = []
        if yahoo:
            cash = _yahoo_many(US_CASH)
        if not cash:
            us = _load_us(db_path) if db_path else {}
            cash = _us_from_snap(us, ("道瓊", "標普", "那斯達克", "費半"))
        items.extend(cash)
        try:
            from us_overnight import electronics_night_side

            us = _load_us(db_path) if db_path else {}
            side = electronics_night_side(us)
            if side:
                items.append(_seg("電子夜盤", extra=side))
        except Exception:
            pass
        night = _tx_seg(snap, night=True, live=live_tx)
        if night:
            items.append(night)

    items = [x for x in items if x]
    if not any(x.get("name") != "此刻" for x in items):
        return {"slot": slot, "title": title, "items": [], "clock": clock}
    return {"slot": slot, "title": title, "items": items, "clock": clock}


def ticker_plain(bundle: Dict[str, Any]) -> str:
    title = str(bundle.get("title") or "")
    bits = [str(x.get("text") or "") for x in (bundle.get("items") or []) if x.get("text")]
    if not bits:
        return ""
    return f"{title}　" + "　·　".join(bits)


def ticker_html(bundle: Dict[str, Any]) -> str:
    from tg_layout import html_escape

    plain = ticker_plain(bundle)
    if not plain:
        return ""
    return f"<i>{html_escape(plain)}</i>"


def _ticker_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    try:
        from wayne_navigator import _WEIGHT_BOLD, _WEIGHT_TEXT, _weight_font_path

        path = _weight_font_path(_WEIGHT_BOLD if bold else _WEIGHT_TEXT)
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def _ink_color(pct) -> tuple:
    if pct is None:
        return _INK
    if float(pct) > 0:
        return _UP
    if float(pct) < 0:
        return _DOWN
    return _INK


TICKER_W = 1080
TICKER_H = 88
TICKER_FRAMES = 40
TICKER_FRAME_MS = 55


def render_ticker_gif(bundle: Dict[str, Any], save_path: str) -> str:
    """整條從最左跑到最右，循環無縫。時段名跟報價一起捲，不留左欄。沒有項目就不畫。"""
    from PIL import Image, ImageDraw

    items = [x for x in (bundle.get("items") or []) if x.get("text")]
    if not items:
        return ""
    title = str(bundle.get("title") or "跑馬燈")
    W, H = TICKER_W, TICKER_H
    body_f = _ticker_font(50, bold=True)
    segs: List[Tuple[str, tuple]] = [(f"{title}    ·    ", _LABEL_FG)]
    for it in items:
        segs.append((str(it["text"]) + "    ·    ", _ink_color(it.get("pct"))))
    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    parts_w = [float(measure.textlength(t, font=body_f)) for t, _c in segs]
    unit_w = max(1, int(round(sum(parts_w))))
    copies = max(3, (W + unit_w + unit_w - 1) // unit_w)
    strip_w = unit_w * copies + 8
    strip = Image.new("RGB", (strip_w, H), _BG)
    sd = ImageDraw.Draw(strip)
    x = 0.0
    for _copy in range(copies):
        for (text, color), tw in zip(segs, parts_w):
            try:
                sd.text((x, H / 2), text, font=body_f, fill=color, anchor="lm")
            except TypeError:
                sd.text((x, max(4, (H - 50) / 2)), text, font=body_f, fill=color)
            x += tw

    n = TICKER_FRAMES
    frames = []
    for i in range(n):
        ox = int(round(i * unit_w / float(n))) % unit_w
        crop = strip.crop((ox, 0, ox + W, H))
        frame = Image.new("RGB", (W, H), _BG)
        frame.paste(crop, (0, 0))
        dr = ImageDraw.Draw(frame)
        dr.rectangle((0, 0, W - 1, 3), fill=_LABEL_FG)
        dr.rectangle((0, H - 4, W - 1, H - 1), fill=_LABEL_FG)
        frames.append(frame)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    frames[0].save(
        save_path,
        save_all=True,
        append_images=frames[1:],
        duration=TICKER_FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return save_path


def build_market_ticker(
    db_path: str,
    *,
    live: Optional[Dict[str, Any]] = None,
    snap: Optional[Dict[str, Any]] = None,
    save_dir: str = None,
    now: Optional[datetime] = None,
    yahoo: bool = True,
) -> Dict[str, Any]:
    """回傳 bundle + gif 路徑；失敗就空路徑，頁面仍可送。"""
    bundle = collect_ticker(db_path, live=live, snap=snap, now=now, yahoo=yahoo)
    gif = ""
    if bundle.get("items"):
        try:
            from config import get_charts_dir

            folder = save_dir or get_charts_dir()
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"market_ticker_{int(time.time() * 1000)}.gif")
            gif = render_ticker_gif(bundle, path)
        except Exception:
            logger.exception("跑馬燈 GIF 失敗")
            gif = ""
    bundle["gif"] = gif
    bundle["plain"] = ticker_plain(bundle)
    bundle["html"] = ticker_html(bundle)
    return bundle
