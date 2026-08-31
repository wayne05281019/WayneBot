"""隔夜美股：台股早上開盤用的是美股已收盤（必要時加夜盤期貨）。

四大指數＝道瓊／標普／那斯達克／費半；VIX＝恐慌指數水位（不是分點）。
半導體／電子再對照費半與台積 ADR。這是開盤風險過濾，不是內幕、也不保證開盤一定跟。
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

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=10d"

# 台股開盤前最常對照的美股四大＋恐慌＋電子鏈。
SYMBOLS = (
    ("dji", "^DJI", "道瓊"),
    ("spx", "^GSPC", "標普"),
    ("ixic", "^IXIC", "那斯達克"),
    ("sox", "^SOX", "費半"),
    ("vix", "^VIX", "VIX"),
    ("nq_f", "NQ=F", "那指期"),
    ("tsm", "TSM", "台積ADR"),
    ("nvda", "NVDA", "輝達"),
)

CHIP_HINTS = ("半導體", "電子零組件", "電子工業", "光電", "電腦及週邊", "通信網路")

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


def _fetch_symbol(sym: str) -> Dict[str, Any]:
    url = YAHOO_CHART.format(sym=url_quote(sym, safe=""))
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"yahoo empty {sym}")
    block = result[0]
    meta = block.get("meta") or {}
    qblock = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = qblock.get("close") or []
    px = meta.get("regularMarketPrice")
    try:
        px_f = float(px) if px is not None else None
    except (TypeError, ValueError):
        px_f = None
    chg = meta.get("regularMarketChangePercent")
    try:
        pct = float(chg) if chg is not None else None
    except (TypeError, ValueError):
        pct = None
    if pct is None:
        pct = _pct_from_closes(closes, px_f)
    ts = 0
    stamps = block.get("timestamp") or []
    if stamps:
        ts = int(stamps[-1])
    elif meta.get("regularMarketTime"):
        ts = int(meta["regularMarketTime"])
    session = ""
    if ts:
        session = datetime.fromtimestamp(ts, tz=ZoneInfo("America/New_York")).strftime("%Y%m%d")
    return {"symbol": meta.get("symbol") or sym, "price": px_f, "pct": pct, "session": session}


def fetch_us_tape() -> Dict[str, Any]:
    """抓現金四大＋VIX＋那指期＋台積 ADR／輝達。失敗的欄位留空，不整包丟掉。"""
    out: Dict[str, Any] = {"ok": False, "fetched_at": datetime.now(timezone.utc).isoformat()}
    sessions = []
    for key, sym, _label in SYMBOLS:
        try:
            bar = _fetch_symbol(sym)
        except Exception:
            logger.exception("美股夜盤抓不到 %s", sym)
            continue
        out[f"{key}_px"] = bar.get("price")
        out[f"{key}_pct"] = bar.get("pct")
        if key == "vix":
            out["vix"] = bar.get("price")
            out["vix_pct"] = bar.get("pct")
        if bar.get("session"):
            sessions.append(bar["session"])
        time.sleep(0.05)
    if sessions:
        out["us_session"] = max(sessions)
    out["ok"] = any(out.get(k) is not None for k in ("vix", "ixic_pct", "spx_pct", "dji_pct"))
    out["regime"] = classify_us_regime(out)
    return out


def classify_us_regime(snap: Dict[str, Any]) -> str:
    """中性／偏空／逆風。VIX 看水位；指數看跌幅。沒接到數字＝unknown，不過濾。"""
    if snap.get("vix") is None and snap.get("ixic_pct") is None and snap.get("spx_pct") is None:
        return "unknown"
    try:
        vix = float(snap["vix"]) if snap.get("vix") is not None else 0.0
    except (TypeError, ValueError):
        vix = 0.0
    cash = []
    for k in ("dji_pct", "spx_pct", "ixic_pct"):
        try:
            if snap.get(k) is not None:
                cash.append(float(snap[k]))
        except (TypeError, ValueError):
            pass
    worst = min(cash) if cash else 0.0
    try:
        nq_f = float(snap["nq_f_pct"]) if snap.get("nq_f_pct") is not None else None
    except (TypeError, ValueError):
        nq_f = None
    if nq_f is not None:
        worst = min(worst, nq_f)
    if vix >= 25 or worst <= -2.5:
        return "risk_off"
    if vix >= 18 or worst <= -1.2:
        return "caution"
    return "ok"


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
    """早上 07:30 與手動海選都走這裡。15 分鐘內有庫就沿用，免得每次打海選狂打 Yahoo。"""
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
        logger.exception("美股夜盤整包失敗")
        return cached
    if snap.get("ok"):
        save_us_overnight(db_path, as_of, snap)
        return _row_from_snap(as_of, snap)
    return cached or _row_from_snap(as_of, snap)


REGIME_LABEL = {
    "ok": "隔夜中性",
    "caution": "隔夜偏空",
    "risk_off": "隔夜逆風",
    "unknown": "美股夜盤沒接到",
}


def _fmt_pct(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_vix(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.1f}"
    except (TypeError, ValueError):
        return "—"


def format_us_html(snap: Dict[str, Any]) -> str:
    if not snap:
        return ""
    from tg_layout import html_escape

    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "美股夜盤")
    sess = snap.get("us_session") or ""
    sess_s = f"{sess[:4]}/{sess[4:6]}/{sess[6:]}" if len(str(sess)) == 8 else (sess or "—")
    lines = [
        f"<b>隔夜美股</b>　{html_escape(label)}　美股交易日 {html_escape(sess_s)}",
        (
            f"道瓊 {_fmt_pct(snap.get('dji_pct'))}　標普 {_fmt_pct(snap.get('spx_pct'))}　"
            f"那斯達克 {_fmt_pct(snap.get('ixic_pct'))}　費半 {_fmt_pct(snap.get('sox_pct'))}"
        ),
        (
            f"VIX {_fmt_vix(snap.get('vix'))}（{_fmt_pct(snap.get('vix_pct'))}）　"
            f"那指期 {_fmt_pct(snap.get('nq_f_pct'))}　"
            f"台積ADR {_fmt_pct(snap.get('tsm_pct'))}　輝達 {_fmt_pct(snap.get('nvda_pct'))}"
        ),
    ]
    regime = snap.get("regime")
    try:
        sox = float(snap["sox_pct"]) if snap.get("sox_pct") is not None else None
    except (TypeError, ValueError):
        sox = None
    if regime == "risk_off":
        lines.append("逆風＝當沖／隔日沖今日不列；突破與貼月高往後排。半導體對照費半／ADR，不是保證開盤一定跟。")
    elif regime == "caution":
        lines.append("偏空＝當沖／隔日沖拿掉貼月高與電子逆風檔。佈局仍先看高低卡，不要因為美股敘事追高。")
    elif regime == "ok" and sox is not None and sox <= -1.5:
        lines.append("大盤中性，但費半／ADR 弱：當沖／隔日沖不列電子鏈，佈局名單標費半逆風。")
    elif regime == "ok":
        lines.append("中性＝大盤不過濾；美股只當開盤風險對照。電子仍對照費半。")
    else:
        lines.append("沒接到美股數字就不過濾，避免假資料把名單打掉。")
    return "\n".join(lines)


def format_us_plain(snap: Dict[str, Any]) -> str:
    if not snap:
        return ""
    label = REGIME_LABEL.get(snap.get("regime") or "unknown", "美股夜盤")
    return (
        f"隔夜美股 {label} 道瓊{_fmt_pct(snap.get('dji_pct'))} 標普{_fmt_pct(snap.get('spx_pct'))} "
        f"那指{_fmt_pct(snap.get('ixic_pct'))} 費半{_fmt_pct(snap.get('sox_pct'))} "
        f"VIX {_fmt_vix(snap.get('vix'))}"
    )


def apply_us_overnight(results: Dict[str, Any], snap: Dict[str, Any]) -> None:
    """在產業標籤之後呼叫。只往下過濾，不因為美股大漲加碼追高。"""
    if not results:
        return
    snap = snap or {}
    regime = snap.get("regime") or "unknown"
    results["_us_regime"] = regime
    try:
        sox = float(snap["sox_pct"]) if snap.get("sox_pct") is not None else None
    except (TypeError, ValueError):
        sox = None
    try:
        tsm = float(snap["tsm_pct"]) if snap.get("tsm_pct") is not None else None
    except (TypeError, ValueError):
        tsm = None

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

    layout_keys = ("revenue_cross", "leave_zero", "select_01", "select_02", "select_03", "select_04")
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
