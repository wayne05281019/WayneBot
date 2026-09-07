"""美股全日休市／提早收盤：NYSE 官方年曆，不自造日期與原因。

來源：https://www.nyse.com/markets/hours-calendars
種子＝官方 2026–2028 表；盤後會再抓同一頁覆蓋。沒抓到就用種子。
週末不是年曆列，標「週末」。提早收盤仍算有開市，不當全日休市。
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

logger = logging.getLogger("WayneBot.USHolidays")

NY = ZoneInfo("America/New_York")
NYSE_CALENDAR_URL = "https://www.nyse.com/markets/hours-calendars"

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# 官方英文名 → 大盤頁用的中文原因（前面會加「美股…休市」）
HOLIDAY_ZH = {
    "new year's day": "元旦",
    "martin luther king, jr. day": "馬丁路德金恩日",
    "washington's birthday": "總統日",
    "good friday": "耶穌受難日",
    "memorial day": "陣亡將士紀念日",
    "juneteenth national independence day": "六月節",
    "independence day": "獨立紀念日",
    "labor day": "勞動節",
    "thanksgiving day": "感恩節",
    "christmas day": "聖誕節",
}

# NYSE 官方表：全日休市（含 observed 補休日）。
# https://www.nyse.com/markets/hours-calendars
_SEED_FULL: Dict[str, Dict[str, str]] = {
    "20260101": {"en": "New Year's Day", "zh": "元旦"},
    "20260119": {"en": "Martin Luther King, Jr. Day", "zh": "馬丁路德金恩日"},
    "20260216": {"en": "Washington's Birthday", "zh": "總統日"},
    "20260403": {"en": "Good Friday", "zh": "耶穌受難日"},
    "20260525": {"en": "Memorial Day", "zh": "陣亡將士紀念日"},
    "20260619": {"en": "Juneteenth National Independence Day", "zh": "六月節"},
    "20260703": {"en": "Independence Day", "zh": "獨立紀念日"},
    "20260907": {"en": "Labor Day", "zh": "勞動節"},
    "20261126": {"en": "Thanksgiving Day", "zh": "感恩節"},
    "20261225": {"en": "Christmas Day", "zh": "聖誕節"},
    "20270101": {"en": "New Year's Day", "zh": "元旦"},
    "20270118": {"en": "Martin Luther King, Jr. Day", "zh": "馬丁路德金恩日"},
    "20270215": {"en": "Washington's Birthday", "zh": "總統日"},
    "20270326": {"en": "Good Friday", "zh": "耶穌受難日"},
    "20270531": {"en": "Memorial Day", "zh": "陣亡將士紀念日"},
    "20270618": {"en": "Juneteenth National Independence Day", "zh": "六月節"},
    "20270705": {"en": "Independence Day", "zh": "獨立紀念日"},
    "20270906": {"en": "Labor Day", "zh": "勞動節"},
    "20271125": {"en": "Thanksgiving Day", "zh": "感恩節"},
    "20271224": {"en": "Christmas Day", "zh": "聖誕節"},
    "20280117": {"en": "Martin Luther King, Jr. Day", "zh": "馬丁路德金恩日"},
    "20280221": {"en": "Washington's Birthday", "zh": "總統日"},
    "20280414": {"en": "Good Friday", "zh": "耶穌受難日"},
    "20280529": {"en": "Memorial Day", "zh": "陣亡將士紀念日"},
    "20280619": {"en": "Juneteenth National Independence Day", "zh": "六月節"},
    "20280704": {"en": "Independence Day", "zh": "獨立紀念日"},
    "20280904": {"en": "Labor Day", "zh": "勞動節"},
    "20281123": {"en": "Thanksgiving Day", "zh": "感恩節"},
    "20281225": {"en": "Christmas Day", "zh": "聖誕節"},
}

# 官方註腳：1:00 p.m. ET 提早收盤（仍有開市，不當「沒開市」）。
_SEED_EARLY: Dict[str, Dict[str, str]] = {
    "20261127": {"en": "Day after Thanksgiving", "zh": "感恩節隔日提早收盤"},
    "20261224": {"en": "Christmas Eve", "zh": "聖誕夜提早收盤"},
    "20271126": {"en": "Day after Thanksgiving", "zh": "感恩節隔日提早收盤"},
    "20281124": {"en": "Day after Thanksgiving", "zh": "感恩節隔日提早收盤"},
    "20280703": {"en": "Independence Day eve", "zh": "獨立紀念日前日提早收盤"},
}

_DATE_IN_CELL = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2})",
    re.I,
)
_DATE_WITH_YEAR = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(20\d{2})",
    re.I,
)
_HEAD_YEARS = re.compile(
    r"<th>\s*Holiday\s*</th>\s*<th>\s*(20\d{2})\s*</th>\s*<th>\s*(20\d{2})\s*</th>\s*<th>\s*(20\d{2})\s*</th>",
    re.I,
)
_ROW = re.compile(
    r"<th>([^<]+)</th>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>",
    re.I,
)


def _norm_ymd(val: Any) -> str:
    s = str(val or "").replace("-", "").strip()
    return s[:8] if len(s) >= 8 and s[:8].isdigit() else ""


def _as_ny(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(NY)
    if now.tzinfo is None:
        return now.replace(tzinfo=NY)
    return now.astimezone(NY)


def us_calendar_ymd(now: Optional[datetime] = None) -> str:
    """紐約日曆日＝今晚／此刻對上的那一場美股現金盤日期。"""
    return _as_ny(now).strftime("%Y%m%d")


def _norm_name(name: str) -> str:
    s = html_lib.unescape(str(name or "")).replace("\u2019", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def holiday_zh(en_name: str) -> str:
    key = _norm_name(en_name)
    if key in HOLIDAY_ZH:
        return HOLIDAY_ZH[key]
    for en, zh in HOLIDAY_ZH.items():
        if en in key:
            return zh
    return ""


def _cell_ymd(cell: str, year: int) -> Optional[str]:
    raw = html_lib.unescape(cell or "")
    compact = re.sub(r"[\s*]+$", "", raw).strip()
    if not compact or compact.startswith("—") or compact.startswith("-"):
        return None
    m = _DATE_IN_CELL.search(compact)
    if not m:
        return None
    month = _MONTHS[m.group(2).lower()]
    day = int(m.group(3))
    try:
        return datetime(year, month, day).strftime("%Y%m%d")
    except ValueError:
        return None


def parse_nyse_calendar(html: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """從 NYSE hours-calendars 頁抽出全日休市與提早收盤。解析失敗就回空，不猜。"""
    text = html_lib.unescape(html or "")
    head = _HEAD_YEARS.search(text)
    if not head:
        return {"full_close": {}, "early_close": {}}
    years = [int(head.group(i)) for i in (1, 2, 3)]
    full: Dict[str, Dict[str, str]] = {}
    for m in _ROW.finditer(text):
        en = html_lib.unescape(m.group(1)).strip()
        if _norm_name(en) == "holiday":
            continue
        zh = holiday_zh(en)
        if not zh:
            continue
        rec = {"en": en, "zh": zh}
        for year, cell in zip(years, (m.group(2), m.group(3), m.group(4))):
            ymd = _cell_ymd(cell, year)
            if ymd:
                full[ymd] = rec
    early: Dict[str, Dict[str, str]] = {}
    for para in re.findall(r"<p[^>]*>(.*?)</p>", text, flags=re.I | re.S):
        plain = re.sub(r"<[^>]+>", " ", para)
        plain = html_lib.unescape(plain)
        if "close early" not in plain.lower():
            continue
        reason_zh = "提早收盤"
        reason_en = "Early close"
        low = plain.lower()
        if "day after thanksgiving" in low:
            reason_zh = "感恩節隔日提早收盤"
            reason_en = "Day after Thanksgiving"
        elif "december 24" in low:
            reason_zh = "聖誕夜提早收盤"
            reason_en = "Christmas Eve"
        elif "july 3" in low:
            reason_zh = "獨立紀念日前日提早收盤"
            reason_en = "Independence Day eve"
        for dm in _DATE_WITH_YEAR.finditer(plain):
            month = _MONTHS[dm.group(2).lower()]
            day = int(dm.group(3))
            year = int(dm.group(4))
            try:
                ymd = datetime(year, month, day).strftime("%Y%m%d")
            except ValueError:
                continue
            if ymd in full:
                continue
            early[ymd] = {"en": reason_en, "zh": reason_zh}
    return {"full_close": full, "early_close": early}


def ensure_us_holidays_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS us_holidays (
            ymd TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name_en TEXT DEFAULT '',
            name_zh TEXT DEFAULT '',
            source TEXT DEFAULT '',
            fetched_at TEXT DEFAULT ''
        );
        """
    )
    conn.commit()
    conn.close()


def _load_db_rows(db_path: str = None) -> Dict[str, Dict[str, str]]:
    path = db_path or get_db_path()
    try:
        ensure_us_holidays_table(path)
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT ymd, kind, name_en, name_zh FROM us_holidays"
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for ymd, kind, en, zh in rows:
        out[str(ymd)] = {"kind": str(kind), "en": str(en or ""), "zh": str(zh or "")}
    return out


def lookup_us_session(ymd: str, db_path: str = None) -> Dict[str, str]:
    """kind＝open／full_close／early_close／weekend。沒列到的平日當開市，不猜假日。"""
    key = _norm_ymd(ymd)
    empty = {"kind": "open", "en": "", "zh": "", "ymd": key}
    if len(key) != 8:
        return empty
    try:
        dt = datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return empty
    if dt.weekday() >= 5:
        return {"kind": "weekend", "en": "Weekend", "zh": "週末", "ymd": key}
    db_rows = _load_db_rows(db_path) if db_path else {}
    rec = db_rows.get(key)
    if rec and rec.get("kind") in ("full_close", "early_close"):
        return {"kind": rec["kind"], "en": rec.get("en") or "", "zh": rec.get("zh") or "", "ymd": key}
    seed = _SEED_FULL.get(key)
    if seed:
        return {"kind": "full_close", "en": seed["en"], "zh": seed["zh"], "ymd": key}
    seed = _SEED_EARLY.get(key)
    if seed:
        return {"kind": "early_close", "en": seed["en"], "zh": seed["zh"], "ymd": key}
    return empty


def previous_trading_day(ymd: str, db_path: str = None) -> str:
    key = _norm_ymd(ymd)
    try:
        dt = datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return ""
    for _ in range(18):
        dt -= timedelta(days=1)
        st = lookup_us_session(dt.strftime("%Y%m%d"), db_path)
        if st["kind"] in ("open", "early_close"):
            return st["ymd"]
    return ""


def closed_us_session(now: Optional[datetime] = None, db_path: str = None) -> Optional[Dict[str, str]]:
    """今晚／此刻紐約日若全日沒開，回日期、中文原因、前一交易日。有開或只提早收盤回 None。"""
    ymd = us_calendar_ymd(now)
    st = lookup_us_session(ymd, db_path)
    if st["kind"] not in ("full_close", "weekend"):
        return None
    prev = previous_trading_day(ymd, db_path)
    return {
        "ymd": ymd,
        "kind": st["kind"],
        "en": st.get("en") or "",
        "zh": st.get("zh") or "",
        "prev_ymd": prev,
    }


def holiday_banner_lines(closed: Optional[Dict[str, str]]) -> list[str]:
    """大盤／美股塊開頭：20260907 美股勞動節休市＋上一收盤 20260904。"""
    if not closed:
        return []
    zh = str(closed.get("zh") or "").strip()
    ymd = str(closed.get("ymd") or "")
    prev = str(closed.get("prev_ymd") or "")
    if not ymd or not zh:
        return []
    lines = [f"{ymd} 美股{zh}休市"]
    if prev:
        lines.append(f"上一收盤 {prev}")
    return lines


def fetch_nyse_calendar_html(timeout: int = 20) -> str:
    resp = requests.get(
        NYSE_CALENDAR_URL,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html",
        },
    )
    resp.raise_for_status()
    return resp.text or ""


def refresh_us_holiday_calendar(db_path: str = None, html: str = None) -> Dict[str, Any]:
    """盤後抓 NYSE 年曆寫進庫。解析不到足夠全日休市就沿用種子，不寫空表。"""
    path = db_path or get_db_path()
    ensure_us_holidays_table(path)
    try:
        raw = html if html is not None else fetch_nyse_calendar_html()
        parsed = parse_nyse_calendar(raw)
    except Exception:
        logger.exception("NYSE 休市年曆抓不到")
        return {"ok": False, "full": 0, "early": 0}
    full = parsed.get("full_close") or {}
    early = parsed.get("early_close") or {}
    if len(full) < 8:
        logger.warning("NYSE 休市年曆解析太少 full=%s，沿用種子", len(full))
        return {"ok": False, "full": len(full), "early": len(early)}
    now = datetime.now(NY).isoformat()
    conn = sqlite3.connect(path)
    for ymd, rec in full.items():
        conn.execute(
            """
            INSERT INTO us_holidays(ymd, kind, name_en, name_zh, source, fetched_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(ymd) DO UPDATE SET
                kind=excluded.kind,
                name_en=excluded.name_en,
                name_zh=excluded.name_zh,
                source=excluded.source,
                fetched_at=excluded.fetched_at
            """,
            (ymd, "full_close", rec.get("en") or "", rec.get("zh") or "", NYSE_CALENDAR_URL, now),
        )
    for ymd, rec in early.items():
        conn.execute(
            """
            INSERT INTO us_holidays(ymd, kind, name_en, name_zh, source, fetched_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(ymd) DO UPDATE SET
                kind=excluded.kind,
                name_en=excluded.name_en,
                name_zh=excluded.name_zh,
                source=excluded.source,
                fetched_at=excluded.fetched_at
            """,
            (ymd, "early_close", rec.get("en") or "", rec.get("zh") or "", NYSE_CALENDAR_URL, now),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "full": len(full), "early": len(early), "source": NYSE_CALENDAR_URL}
