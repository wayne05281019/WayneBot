"""隔夜美股：台股開盤對照現金收盤，收盤後再看盤後。盤中期貨不看。

四大指數＝道瓊／標普／那斯達克／費半；VIX＝收盤恐慌水位。
06:30 台灣＝美股已收、盤後還在：台積 ADR／輝達盤後＋那指／標普／道瓊期續勢。
只過濾逆風，不拿來追高。大跌會在早上海選前先單獨通知一則。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from urllib.parse import quote as url_quote

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

logger = logging.getLogger("WayneBot.USOvernight")

# 台股開盤前最常對照的美股四大＋恐慌＋電子鏈。
SYMBOLS = (
    ("dji", "^DJI", "道瓊"),
    ("spx", "^GSPC", "標普"),
    ("ixic", "^IXIC", "那斯達克"),
    ("sox", "^SOX", "費半"),
    ("vix", "^VIX", "VIX"),
    ("tsm", "TSM", "台積ADR"),
    ("nvda", "NVDA", "輝達"),
)

# 現金收盤後才抓：指數盤後續勢用期貨，個股／費半 ETF 用盤後成交。
FUTURES = (
    ("es_f", "ES=F", "標普期"),
    ("nq_f", "NQ=F", "那指期"),
    ("ym_f", "YM=F", "道瓊期"),
)
POST_NAMES = (
    ("tsm", "TSM"),
    ("nvda", "NVDA"),
    ("soxx", "SOXX"),
)

CHIP_HINTS = ("半導體", "電子零組件", "電子工業", "光電", "電腦及週邊", "通信網路")
NY = ZoneInfo("America/New_York")

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
)


def ensure_us_overnight_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS us_overnight (
            as_of TEXT PRIMARY KEY,
            fetched_at TEXT,
            us_session TEXT DEFAULT '',
            regime TEXT DEFAULT 'unknown',
            vix REAL,
            vix_pct REAL,
            dji_pct REAL,
            spx_pct REAL,
            ixic_pct REAL,
            sox_pct REAL,
            nq_f_pct REAL,
            tsm_pct REAL,
            nvda_pct REAL,
            payload TEXT DEFAULT '{}'
        );
        """
    )
    conn.commit()
    conn.close()


def is_chip_industry(industry: str) -> bool:
    s = str(industry or "")
    return any(h in s for h in CHIP_HINTS)


def us_tape_phase(now: Optional[datetime] = None) -> str:
    """regular＝美股現金盤中（期貨不看）；post＝16:00–20:00 盤後；overnight＝其餘隔夜。"""
    dt = datetime.now(NY) if now is None else now.astimezone(NY)
    if dt.weekday() < 5:
        hm = (dt.hour, dt.minute)
        if (9, 30) <= hm < (16, 0):
            return "regular"
        if (16, 0) <= hm < (20, 0):
            return "post"
    return "overnight"


def _chart_url(sym: str, interval: str = "1d", range_: str = "10d", include_prepost: bool = False) -> str:
    q = f"interval={interval}&range={range_}"
    if include_prepost:
        q += "&includePrePost=true"
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(sym, safe='')}?{q}"


def _pct_from_closes(closes: List[Any], last_px: Optional[float]) -> Optional[float]:
    nums = [float(x) for x in closes if x is not None]
    if last_px is not None and last_px > 0:
        if len(nums) >= 2:
            prev = nums[-2]
            if prev:
                return (last_px - prev) / prev * 100.0
        if len(nums) >= 1 and nums[-1]:
            return (last_px - nums[-1]) / nums[-1] * 100.0 if last_px != nums[-1] else 0.0
    if len(nums) >= 2 and nums[-2]:
        return (nums[-1] - nums[-2]) / nums[-2] * 100.0
    return None


def _as_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _floats(snap: Dict[str, Any], keys) -> List[float]:
    out: List[float] = []
    for k in keys:
        v = _as_float(snap.get(k))
        if v is not None:
            out.append(v)
    return out


def last_post_from_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """1 分 K（含盤後）裡，取現金收盤後最後一筆。盤中還沒有盤後 bar 就回 None。"""
    meta = block.get("meta") or {}
    period = meta.get("currentTradingPeriod") or {}
    post = period.get("post") or {}
    regular = period.get("regular") or {}
    start = int(post.get("start") or 0) or int(regular.get("end") or 0)
    end = int(post.get("end") or 0)
    if not start:
        return None
    stamps = block.get("timestamp") or []
    closes = ((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    last_px = None
    last_t = None
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        t = int(ts)
        if t < start:
            continue
        if end and t > end:
            continue
        last_px, last_t = float(close), t
    if last_px is None:
        return None
    prev = _as_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
    pct = (last_px - prev) / prev * 100.0 if prev else None
    chg = (last_px - prev) if prev is not None else None
    return {"price": last_px, "ts": last_t, "previous_close": prev, "pct": pct, "chg": chg}


def _fetch_symbol(sym: str) -> Dict[str, Any]:
    url = _chart_url(sym, interval="1d", range_="10d")
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"yahoo empty {sym}")
    block = result[0]
    meta = block.get("meta") or {}
    qblock = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = qblock.get("close") or []
    px = _as_float(meta.get("regularMarketPrice"))
    pct = _as_float(meta.get("regularMarketChangePercent"))
    chg = _as_float(meta.get("regularMarketChange"))
    if pct is None:
        pct = _pct_from_closes(closes, px)
    if chg is None and px is not None and pct is not None:
        prev = px / (1.0 + pct / 100.0) if pct != -100.0 else None
        if prev:
            chg = px - prev
    ts = 0
    stamps = block.get("timestamp") or []
    if stamps:
        ts = int(stamps[-1])
    elif meta.get("regularMarketTime"):
        ts = int(meta["regularMarketTime"])
    session = ""
    if ts:
        session = datetime.fromtimestamp(ts, tz=NY).strftime("%Y%m%d")
    return {"symbol": meta.get("symbol") or sym, "price": px, "pct": pct, "chg": chg, "session": session}


def _fetch_post_last(sym: str) -> Optional[Dict[str, Any]]:
    url = _chart_url(sym, interval="1m", range_="1d", include_prepost=True)
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        return None
    return last_post_from_block(result[0])


def fetch_us_tape(now: Optional[datetime] = None) -> Dict[str, Any]:
    """抓美股現金收盤；收盤後再補盤後。盤中不抓期貨。失敗的欄位留空，不整包丟掉。"""
    phase = us_tape_phase(now)
    out: Dict[str, Any] = {
        "ok": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "us_phase": phase,
    }
    sessions = []
    for key, sym, _label in SYMBOLS:
        try:
            bar = _fetch_symbol(sym)
        except Exception:
            logger.exception("美股收盤抓不到 %s", sym)
            continue
        out[f"{key}_px"] = bar.get("price")
        out[f"{key}_pct"] = bar.get("pct")
        out[f"{key}_chg"] = bar.get("chg")
        if key == "vix":
            out["vix"] = bar.get("price")
            out["vix_pct"] = bar.get("pct")
            out["vix_chg"] = bar.get("chg")
        if bar.get("session"):
            sessions.append(bar["session"])
        time.sleep(0.05)
    if phase != "regular":
        for key, sym, _label in FUTURES:
            try:
                bar = _fetch_symbol(sym)
            except Exception:
                logger.exception("美股盤後期貨抓不到 %s", sym)
                continue
            out[f"{key}_px"] = bar.get("price")
            out[f"{key}_pct"] = bar.get("pct")
            out[f"{key}_chg"] = bar.get("chg")
            time.sleep(0.05)
        for key, sym in POST_NAMES:
            try:
                ext = _fetch_post_last(sym)
            except Exception:
                logger.exception("美股盤後抓不到 %s", sym)
                continue
            if not ext:
                continue
            out[f"{key}_post_px"] = ext.get("price")
            out[f"{key}_post_pct"] = ext.get("pct")
            out[f"{key}_post_chg"] = ext.get("chg")
            time.sleep(0.05)
    if sessions:
        out["us_session"] = max(sessions)
    out["ok"] = any(out.get(k) is not None for k in ("vix", "ixic_pct", "spx_pct", "dji_pct", "nq_f_pct"))
    out["regime"] = classify_us_regime(out)
    return out


def index_worst_pct(snap: Dict[str, Any]) -> Optional[float]:
    """大盤最弱的那根。盤後才把期貨續勢算進去；盤中期貨不算。"""
    vals = _floats(snap, ("dji_pct", "spx_pct", "ixic_pct"))
    phase = snap.get("us_phase") or "regular"
    if phase in ("post", "overnight"):
        vals.extend(_floats(snap, ("nq_f_pct", "es_f_pct", "ym_f_pct")))
    if not vals:
        return None
    return min(vals)


def effective_sox_pct(snap: Dict[str, Any]) -> Optional[float]:
    vals = _floats(snap, ("sox_pct",))
    if (snap.get("us_phase") or "regular") in ("post", "overnight"):
        vals.extend(_floats(snap, ("soxx_post_pct",)))
    return min(vals) if vals else None


def effective_tsm_pct(snap: Dict[str, Any]) -> Optional[float]:
    vals = _floats(snap, ("tsm_pct",))
    if (snap.get("us_phase") or "regular") in ("post", "overnight"):
        vals.extend(_floats(snap, ("tsm_post_pct",)))
    return min(vals) if vals else None


def effective_nvda_pct(snap: Dict[str, Any]) -> Optional[float]:
    vals = _floats(snap, ("nvda_pct",))
    if (snap.get("us_phase") or "regular") in ("post", "overnight"):
        vals.extend(_floats(snap, ("nvda_post_pct",)))
    return min(vals) if vals else None


def electronics_night_side(snap: Dict[str, Any]) -> str:
    """台股電子鏈夜盤：漲／跌／平。沒數字回空字串。"""
    snap = snap or {}
    votes = []
    for v in (effective_sox_pct(snap), effective_tsm_pct(snap), effective_nvda_pct(snap)):
        if v is not None:
            votes.append(v)
    if not votes:
        return ""
    down = sum(1 for v in votes if v <= -1.0)
    up = sum(1 for v in votes if v >= 1.0)
    avg = sum(votes) / len(votes)
    if down >= 2 or avg <= -1.0:
        return "跌"
    if up >= 2 or avg >= 1.0:
        return "漲"
    return "平"


def classify_us_regime(snap: Dict[str, Any]) -> str:
    """中性／偏空／逆風。現金收盤為底；收盤後才看盤後續勢。期貨盤中不參與判定。"""
    worst = index_worst_pct(snap)
    vix = _as_float(snap.get("vix"))
    if vix is None and worst is None:
        return "unknown"
    vix_n = vix or 0.0
    worst_n = worst if worst is not None else 0.0
    if vix_n >= 25 or worst_n <= -2.5:
        return "risk_off"
    if vix_n >= 18 or worst_n <= -1.2:
        return "caution"
    return "ok"


def should_alert_us_drop(snap: Dict[str, Any]) -> bool:
    """大跌才通知：逆風，或指數／盤後最弱 ≤ -1.2%，或台積ADR／費半 ≤ -2%。VIX 偏高但指數沒跌不吵。"""
    if not snap:
        return False
    regime = snap.get("regime") or classify_us_regime(snap)
    if regime == "unknown":
        return False
    if regime == "risk_off":
        return True
    worst = index_worst_pct(snap)
    if worst is not None and worst <= -1.2:
        return True
    tsm = effective_tsm_pct(snap)
    sox = effective_sox_pct(snap)
    if tsm is not None and tsm <= -2.0:
        return True
    if sox is not None and sox <= -2.0:
        return True
    return False


def _row_from_snap(as_of: str, snap: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "as_of": as_of,
        "fetched_at": snap.get("fetched_at") or "",
        "us_session": snap.get("us_session") or "",
        "regime": snap.get("regime") or "unknown",
        "vix": snap.get("vix"),
        "vix_pct": snap.get("vix_pct"),
        "dji_pct": snap.get("dji_pct"),
        "spx_pct": snap.get("spx_pct"),
        "ixic_pct": snap.get("ixic_pct"),
        "sox_pct": snap.get("sox_pct"),
        "nq_f_pct": snap.get("nq_f_pct"),
        "tsm_pct": snap.get("tsm_pct"),
        "nvda_pct": snap.get("nvda_pct"),
        "payload": json.dumps(snap, ensure_ascii=False),
        "ok": bool(snap.get("ok")),
    }


def save_us_overnight(db_path: str, as_of: str, snap: Dict[str, Any]) -> None:
    ensure_us_overnight_table(db_path)
    row = _row_from_snap(as_of, snap)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO us_overnight(
            as_of, fetched_at, us_session, regime, vix, vix_pct,
            dji_pct, spx_pct, ixic_pct, sox_pct, nq_f_pct, tsm_pct, nvda_pct, payload
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of) DO UPDATE SET
            fetched_at=excluded.fetched_at,
            us_session=excluded.us_session,
            regime=excluded.regime,
            vix=excluded.vix,
            vix_pct=excluded.vix_pct,
            dji_pct=excluded.dji_pct,
            spx_pct=excluded.spx_pct,
            ixic_pct=excluded.ixic_pct,
            sox_pct=excluded.sox_pct,
            nq_f_pct=excluded.nq_f_pct,
            tsm_pct=excluded.tsm_pct,
            nvda_pct=excluded.nvda_pct,
            payload=excluded.payload
        """,
        (
            as_of,
            row["fetched_at"],
            row["us_session"],
            row["regime"],
            row["vix"],
            row["vix_pct"],
            row["dji_pct"],
            row["spx_pct"],
            row["ixic_pct"],
            row["sox_pct"],
            row["nq_f_pct"],
            row["tsm_pct"],
            row["nvda_pct"],
            row["payload"],
        ),
    )
    conn.commit()
    conn.close()


def load_us_overnight(db_path: str, as_of: str) -> Dict[str, Any]:
    ensure_us_overnight_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM us_overnight WHERE as_of=?", (as_of,)).fetchone()
    conn.close()
    if not row:
        return {}
    data = dict(row)
    try:
        extra = json.loads(data.get("payload") or "{}")
        if isinstance(extra, dict):
            for k, v in extra.items():
                data.setdefault(k, v)
    except Exception:
        pass
    data["ok"] = data.get("regime") not in (None, "", "unknown") or data.get("vix") is not None
    return data


def refresh_us_overnight(db_path: str, as_of: str, max_age_sec: int = 900) -> Dict[str, Any]:
    """早上 06:30 與手動海選都走這裡。15 分鐘內有庫就沿用，免得每次打海選狂打 Yahoo。"""
    as_of = str(as_of or "").replace("-", "")
    cached = load_us_overnight(db_path, as_of)
    if cached.get("fetched_at"):
        try:
            ts = datetime.fromisoformat(str(cached["fetched_at"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
            if age >= 0 and age < max_age_sec and cached.get("regime") != "unknown":
                return cached
        except Exception:
            pass
    try:
        snap = fetch_us_tape()
    except Exception:
        logger.exception("美股收盤整包失敗")
        return cached
    if snap.get("ok"):
        save_us_overnight(db_path, as_of, snap)
        merged = _row_from_snap(as_of, snap)
        merged.update(snap)
        return merged
    return cached or {**_row_from_snap(as_of, snap), **snap}


REGIME_LABEL = {
    "ok": "隔夜中性",
    "caution": "隔夜偏空",
    "risk_off": "隔夜逆風",
    "unknown": "美股收盤沒接到",
}

_PHASE_LABEL = {
    "regular": "現金收盤（盤中不看期貨）",
    "post": "收盤＋盤後",
    "overnight": "收盤＋盤後續勢",
}

_CASH_ITEMS = (
    ("dji_pct", "dji_chg", "道瓊"),
    ("spx_pct", "spx_chg", "標普"),
    ("ixic_pct", "ixic_chg", "那斯達克"),
    ("sox_pct", "sox_chg", "費半"),
)

_FUTURES_ITEMS = (
    ("nq_f_pct", "nq_f_chg", "NQ"),
    ("es_f_pct", "es_f_chg", "ES"),
    ("ym_f_pct", "ym_f_chg", "YM"),
)

_ADR_ITEMS = (
    ("tsm_pct", "tsm_chg", "台積ADR"),
    ("nvda_pct", "nvda_chg", "輝達"),
)

_ADR_CASH_ITEMS = (
    ("tsm_pct", "tsm_chg", "台積ADR收盤"),
    ("tsm_post_pct", "tsm_post_chg", "台積盤後"),
    ("nvda_pct", "nvda_chg", "輝達收盤"),
    ("nvda_post_pct", "nvda_post_chg", "輝達盤後"),
)

_DROP_POST_ITEMS = (
    ("nq_f_pct", "nq_f_chg", "NQ"),
    ("tsm_post_pct", "tsm_post_chg", "台積ADR"),
    ("nvda_post_pct", "nvda_post_chg", "輝達"),
)

_LABEL_W = 8

PHASE_LABEL = _PHASE_LABEL


def _fmt_pct(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_pts(chg, decimals: int = 2) -> str:
    if chg is None:
        return ""
    try:
        return f"{float(chg):+.{decimals}f}點"
    except (TypeError, ValueError):
        return ""


def _fmt_move(pct, chg=None, *, pts_decimals: int = 2) -> str:
    if pct is None:
        return "—"
    pct_s = _fmt_pct(pct)
    pts_s = _fmt_pts(chg, pts_decimals)
    return f"{pct_s}（{pts_s}）" if pts_s else pct_s


def _fmt_vix(snap: Dict[str, Any]) -> str:
    level = snap.get("vix")
    if level is None:
        return "—"
    try:
        base = f"{float(level):.2f}"
    except (TypeError, ValueError):
        return "—"
    pct = snap.get("vix_pct")
    if pct is None:
        return base
    return f"{base}（{_fmt_pct(pct)}）"


def _quote_rows(snap: Dict[str, Any], items, *, pts_decimals: int = 2) -> list:
    """保留給測試／舊呼叫；實際排版請用 _quote_row_lines。"""
    from tg_layout import html_escape

    _ = pts_decimals
    return [(label, html_escape(_fmt_move(snap.get(pct_k), snap.get(chg_k)))) for pct_k, chg_k, label in items]


def _quote_row_lines(snap: Dict[str, Any], items, *, label_width: int = _LABEL_W) -> str:
    from tg_layout import html_escape, pad_label

    lines = []
    for pct_k, chg_k, label in items:
        move = _fmt_move(snap.get(pct_k), snap.get(chg_k))
        lines.append(f"{pad_label(label, label_width)}{html_escape(move)}")
    return "\n".join(lines)


def _cash_indices_block(snap: Dict[str, Any]) -> str:
    from tg_layout import section_eq

    body = _quote_row_lines(snap, _CASH_ITEMS)
    return f"{section_eq('現金收盤')}\n{body}" if body else section_eq("現金收盤")


def _post_futures_block(snap: Dict[str, Any]) -> str:
    from tg_layout import section_eq

    body = _quote_row_lines(snap, _FUTURES_ITEMS)
    return f"{section_eq('盤後期貨')}\n{body}" if body else section_eq("盤後期貨")


def _post_adr_block(snap: Dict[str, Any], *, with_cash: bool = False) -> str:
    from tg_layout import section_eq

    items = _ADR_CASH_ITEMS if with_cash else _ADR_ITEMS
    body = _quote_row_lines(snap, items)
    return f"{section_eq('ADR')}\n{body}" if body else section_eq("ADR")


def _drop_post_block(snap: Dict[str, Any]) -> str:
    from tg_layout import section_eq

    body = _quote_row_lines(snap, _DROP_POST_ITEMS)
    return f"{section_eq('盤後續勢')}\n{body}" if body else section_eq("盤後續勢")


def _vix_row(snap: Dict[str, Any]) -> str:
    from tg_layout import html_escape, pad_label

    return f"{pad_label('VIX', _LABEL_W)}{html_escape(_fmt_vix(snap))}"


def _session_label(snap: Dict[str, Any]) -> str:
    sess = snap.get("us_session") or ""
    if len(str(sess)) == 8:
        return f"{sess[:4]}/{sess[4:6]}/{sess[6:]}"
    return str(sess or "—")


def _cash_indices_line(snap: Dict[str, Any]) -> str:
    """相容舊測試／純文字摘要。"""
    return _cash_indices_block(snap).replace("<b>== ", "").replace(" ==</b>", "").replace("<code>", "").replace("</code>", "")


def _plain_quote_rows(snap: Dict[str, Any], items) -> str:
    lines = [
        f"{label}　{_fmt_move(snap.get(pct_k), snap.get(chg_k))}"
        for pct_k, chg_k, label in items
    ]
    return "\n".join(lines)


def _post_futures_line(snap: Dict[str, Any]) -> str:
    return _plain_quote_rows(snap, _FUTURES_ITEMS)


def _post_adr_line(snap: Dict[str, Any], *, with_cash: bool = False) -> str:
    items = _ADR_CASH_ITEMS if with_cash else _ADR_ITEMS
    return _plain_quote_rows(snap, items)


def _drop_post_line(snap: Dict[str, Any]) -> str:
    return _plain_quote_rows(snap, _DROP_POST_ITEMS)


def format_us_html(snap: Dict[str, Any]) -> str:
    if not snap:
        return ""
    from tg_layout import headline_lines, html_escape, join_sections

    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "美股收盤")
    phase = snap.get("us_phase") or "regular"
    phase_s = _PHASE_LABEL.get(phase, "現金收盤")
    blocks = [
        headline_lines(
            "<b>美股收盤</b>",
            f"判斷　{html_escape(label)}",
            f"階段　{html_escape(phase_s)}",
            f"美股交易日　{html_escape(_session_label(snap))}",
        ),
        _cash_indices_block(snap),
        _vix_row(snap),
    ]
    posted = phase in ("post", "overnight") and any(
        snap.get(k) is not None for k in ("nq_f_pct", "es_f_pct", "ym_f_pct", "tsm_post_pct", "nvda_post_pct")
    )
    if posted:
        blocks.extend([_post_futures_block(snap), _post_adr_block(snap, with_cash=True)])
    else:
        blocks.append(_post_adr_block(snap))
    return join_sections(*blocks)


def format_night_plain(snap: Dict[str, Any]) -> str:
    """轉寄稿用的夜盤整塊：美股現金／盤後＋電子鏈漲跌。"""
    if not snap:
        return "＝＝夜盤判斷＝＝\n這次沒接到美股數字"
    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "美股收盤")
    phase = snap.get("us_phase") or "regular"
    phase_s = _PHASE_LABEL.get(phase, "")
    lines = [
        "＝＝夜盤判斷＝＝",
        label,
        phase_s,
        "【現金收盤】",
        _plain_quote_rows(snap, _CASH_ITEMS),
        f"VIX　{_fmt_vix(snap)}",
    ]
    if phase in ("post", "overnight"):
        lines.extend(["【盤後期貨】", _post_futures_line(snap), "【ADR】", _post_adr_line(snap, with_cash=True)])
    else:
        lines.extend(["【ADR】", _post_adr_line(snap), "（現金收盤，盤中期貨不看）"])
    side = electronics_night_side(snap)
    if side:
        lines.extend(
            [
                f"電子夜盤　{side}",
                _plain_quote_rows(
                    snap,
                    (
                        ("sox_pct", "sox_chg", "費半"),
                        ("tsm_pct", "tsm_chg", "台積ADR"),
                        ("nvda_pct", "nvda_chg", "輝達"),
                    ),
                ),
                "（台指期／電子期夜盤報價這次沒接公開源；電子漲跌改看費半＋台積ADR＋輝達）",
            ]
        )
    else:
        lines.append("電子夜盤　沒接到費半／ADR，這次不判斷漲跌")
    return "\n".join(lines)


def format_us_plain(snap: Dict[str, Any]) -> str:
    """短行摘要；轉寄稿請用 format_night_plain。"""
    if not snap:
        return ""
    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "美股收盤")
    phase = snap.get("us_phase") or "regular"
    extra = ""
    if phase in ("post", "overnight") and snap.get("nq_f_pct") is not None:
        extra = f" 盤後NQ{_fmt_move(snap.get('nq_f_pct'), snap.get('nq_f_chg'))}"
    side = electronics_night_side(snap)
    elec = f" 電子夜盤{side}" if side else ""
    return (
        f"美股收盤 {label} {_cash_indices_line(snap)} "
        f"VIX {_fmt_vix(snap)}{extra}{elec}"
    )


def format_us_drop_alert(snap: Dict[str, Any]) -> str:
    """06:30 海選前的單獨一則：只在大跌時寄，一早打開就能看到。"""
    from tg_layout import headline_lines, html_escape, join_sections

    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "隔夜偏空")
    blocks = [
        headline_lines(
            "<b>美股收盤偏弱</b>",
            "一早提醒",
            f"判斷　{html_escape(label)}",
            f"美股交易日　{html_escape(_session_label(snap))}",
        ),
        _cash_indices_block(snap),
        _vix_row(snap),
    ]
    phase = snap.get("us_phase") or "regular"
    if phase in ("post", "overnight") and any(
        snap.get(k) is not None for k in ("nq_f_pct", "tsm_post_pct")
    ):
        blocks.append(_drop_post_block(snap))
    if snap.get("regime") == "risk_off":
        blocks.append("06:30 海選會把當沖／隔日沖拿掉。佈局先看高低卡，不要因為缺口去追。")
    else:
        blocks.append("06:30 海選會加嚴：貼月高與電子逆風檔會拿掉。不是叫你現在下單。")
    return join_sections(*blocks)


def apply_us_overnight(results: Dict[str, Any], snap: Dict[str, Any]) -> None:
    """在產業標籤之後呼叫。只往下過濾，不因為美股大漲加碼追高。"""
    if not results:
        return
    snap = snap or {}
    regime = snap.get("regime") or "unknown"
    results["_us_regime"] = regime
    sox = effective_sox_pct(snap)
    tsm = effective_tsm_pct(snap)

    def mark(item: Dict[str, Any]) -> None:
        chip = is_chip_industry(str(item.get("industry") or ""))
        if chip and sox is not None and sox <= -1.5:
            item["us_peer_headwind"] = True
        if chip and tsm is not None and tsm <= -2.0:
            item["us_peer_headwind"] = True
        if regime == "risk_off":
            item["us_risk_off"] = True
        elif regime == "caution":
            item["us_caution"] = True

    for lst in list(results.values()):
        if isinstance(lst, list):
            for item in lst:
                if isinstance(item, dict):
                    mark(item)

    def demote(x: Dict[str, Any]):
        return (
            0 if x.get("us_peer_headwind") else 1,
            0 if x.get("chase_warning") else 1,
            1 if x.get("is_s_tier") else 0,
            x.get("q60r") or 0,
        )

    layout_keys = ("leave_zero", "golden_buy", "revenue_cross", "select_01", "select_02", "select_03")
    if regime == "unknown" and sox is None and tsm is None:
        return

    def keep_intraday(x: Dict[str, Any]) -> bool:
        if x.get("us_peer_headwind"):
            return False
        if regime == "caution" and x.get("chase_warning"):
            return False
        return True

    if regime == "risk_off":
        results["day_trade"] = []
        results["overnight"] = []
    elif isinstance(results.get("day_trade"), list) or isinstance(results.get("overnight"), list):
        if isinstance(results.get("day_trade"), list):
            results["day_trade"] = [x for x in results["day_trade"] if keep_intraday(x)]
        if isinstance(results.get("overnight"), list):
            results["overnight"] = [x for x in results["overnight"] if keep_intraday(x)]
    if regime != "unknown" or sox is not None or tsm is not None:
        for k in layout_keys:
            if isinstance(results.get(k), list):
                results[k].sort(key=demote, reverse=True)
