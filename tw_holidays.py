"""台股休市：證交所開休市年曆＋人事行政總處北市停班（颱風等天然災害）。

國定假／補假／僅結算：https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule
颱風／天然災害：北市公教停班才休市（證交所「天然災害停止上班之處理」）。
來源 https://www.dgpa.gov.tw/typh/daily/nds.html
  全日或上午停班：前一晚 19:00–22:00 公告（23:00 前播出）；沒公告則當日 04:30 前補發（05:00 前播出）。
  僅下午停班：當日 10:30 前公告；集中市場仍開市，不當全日休市。

沒官方列就當開市，不猜颱風。
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

logger = logging.getLogger("WayneBot.TWHolidays")

TW = ZoneInfo("Asia/Taipei")
TWSE_HOLIDAY_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
DGPA_NDS_URL = "https://www.dgpa.gov.tw/typh/daily/nds.html"

# 證交所 115 年平日無交易（與 OpenAPI 對過）。週末不列入。
_SEED_CLOSED: Dict[str, str] = {
    "20260101": "元旦",
    "20260212": "僅結算",
    "20260213": "僅結算",
    "20260216": "春節",
    "20260217": "春節",
    "20260218": "春節",
    "20260219": "春節",
    "20260220": "春節",
    "20260227": "和平紀念日補假",
    "20260403": "兒童節補假",
    "20260406": "掃墓節補假",
    "20260501": "勞動節",
    "20260619": "端午節",
    "20260925": "中秋節",
    "20260928": "教師節",
    "20261009": "國慶日補假",
    "20261026": "光復節補假",
    "20261225": "行憲紀念日",
}

_ROC_YMD = re.compile(r"(\d{3})年\s*(\d{1,2})月\s*(\d{1,2})日")
_UPDATED = re.compile(r"更新時間：\s*(20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})")
# 真實頁是 <TD headers='city_Name'><FONT>臺北市</FONT></TD><TD headers='StopWorkSchool_Info'>…
_CITY_ROW = re.compile(
    r"<td[^>]*headers=['\"]city_Name['\"][^>]*>(.*?)</td>\s*"
    r"<td[^>]*>(.*?)</td>",
    re.I | re.S,
)
_TAG = re.compile(r"<[^>]+>")


def _norm_ymd(val) -> str:
    return str(val or "").replace("-", "").replace("/", "").strip()[:8]


def roc_to_ymd(roc_date: str) -> str:
    s = str(roc_date or "").replace("-", "").strip()
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911}{s[3:]}"
    return s[:8]


def short_holiday_zh(name: str, desc: str = "") -> str:
    n = str(name or "").strip()
    d = str(desc or "")
    blob = n + d
    if "市場無交易" in n:
        return "僅結算"
    if "開國紀念" in n:
        return "元旦"
    if "農曆" in n or "春節" in n:
        return "春節"
    if "勞動節" in n:
        return "勞動節"
    if "端午" in n:
        return "端午節"
    if "中秋" in n:
        return "中秋節"
    if "孔子" in n or "教師" in n:
        return "教師節"
    if "國慶" in n:
        return "國慶日補假" if "補假" in blob else "國慶日"
    if "光復" in n:
        return "光復節補假" if "補假" in blob else "光復節"
    if "行憲" in n:
        return "行憲紀念日"
    if "和平紀念" in n:
        return "和平紀念日補假" if "補假" in blob else "和平紀念日"
    if "兒童節" in n or "掃墓" in n:
        if "補假" in d and "兒童" in d:
            return "兒童節補假"
        if "補假" in d:
            return "掃墓節補假"
        return "兒童節及掃墓節"
    return n[:12]


def row_is_closed_session(name: str, desc: str) -> bool:
    blob = f"{name or ''}{desc or ''}"
    if "開始交易" in blob or "最後交易" in blob:
        return False
    return "市場無交易" in blob or "放假" in blob or "補假" in blob


def parse_twse_holiday_rows(rows: List[Any]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ymd = roc_to_ymd(str(row.get("Date") or ""))
        if len(ymd) != 8 or not ymd.isdigit():
            continue
        try:
            if datetime.strptime(ymd, "%Y%m%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        name = str(row.get("Name") or "")
        desc = str(row.get("Description") or "")
        if not row_is_closed_session(name, desc):
            continue
        out[ymd] = {"zh": short_holiday_zh(name, desc), "source": "twse"}
    return out


def _plain_cell(html: str) -> str:
    text = _TAG.sub("", str(html or ""))
    return re.sub(r"\s+", "", text)


def parse_dgpa_nds(html: str) -> Dict[str, Any]:
    """解析人事行政總處停班頁。沒北市列或無訊息＝開市。"""
    raw = str(html or "")
    ymd = ""
    header = re.search(
        r"Header_YMD[^>]*>\s*([^<]*\d{3}年[^<]*\d{1,2}月[^<]*\d{1,2}日)",
        raw,
        re.I,
    )
    m = _ROC_YMD.search(header.group(1) if header else raw)
    if m:
        ymd = f"{int(m.group(1)) + 1911}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    um = _UPDATED.search(raw)
    updated = um.group(1) if um else ""
    if not ymd and updated:
        digits = "".join(ch for ch in updated if ch.isdigit())
        if len(digits) >= 8:
            ymd = digits[:8]
    if "無停班停課訊息" in raw:
        return {"ymd": ymd, "taipei_text": "", "halt": False, "zh": "", "updated": updated}
    taipei = ""
    for city, cell in _CITY_ROW.findall(raw):
        city_s = _plain_cell(city)
        cell_s = _plain_cell(cell)
        if city_s in ("臺北市", "台北市"):
            taipei = cell_s
            break
    halt, zh = _taipei_cell_to_halt(taipei)
    return {
        "ymd": ymd,
        "taipei_text": taipei,
        "halt": halt,
        "zh": zh,
        "updated": updated,
    }


def _taipei_cell_to_halt(text: str) -> tuple[bool, str]:
    t = str(text or "").replace(" ", "").replace("　", "")
    if not t or "照常" in t:
        return False, ""
    afternoon_only = ("下午" in t or "晚間" in t) and "上午" not in t and "全日" not in t
    if afternoon_only and "停止上班" in t:
        return False, ""
    if "停止上班" not in t and "全日" not in t:
        return False, ""
    if "颱風" in t:
        return True, "颱風停班"
    return True, "北市停班"


def ensure_tw_holidays_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tw_holidays (
            ymd TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
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
        ensure_tw_holidays_table(path)
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT ymd, kind, name_zh, source FROM tw_holidays"
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for ymd, kind, zh, src in rows:
        out[str(ymd)] = {
            "kind": str(kind or ""),
            "zh": str(zh or ""),
            "source": str(src or ""),
        }
    return out


def lookup_tw_session(ymd: str, db_path: str = None) -> Dict[str, str]:
    """kind＝open／full_close／weekend。沒列到的平日當開市。"""
    key = _norm_ymd(ymd)
    empty = {"kind": "open", "zh": "", "ymd": key, "source": ""}
    if len(key) != 8:
        return empty
    try:
        dt = datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return empty
    if dt.weekday() >= 5:
        return {"kind": "weekend", "zh": "週末", "ymd": key, "source": ""}
    db_rows = _load_db_rows(db_path or get_db_path())
    rec = db_rows.get(key)
    if rec and rec.get("kind") == "full_close":
        return {"kind": "full_close", "zh": rec.get("zh") or "", "ymd": key, "source": rec.get("source") or ""}
    zh = _SEED_CLOSED.get(key)
    if zh:
        return {"kind": "full_close", "zh": zh, "ymd": key, "source": "seed"}
    return empty


def previous_tw_trading_day(ymd: str, db_path: str = None) -> str:
    key = _norm_ymd(ymd)
    try:
        dt = datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return ""
    for _ in range(18):
        dt -= timedelta(days=1)
        st = lookup_tw_session(dt.strftime("%Y%m%d"), db_path)
        if st["kind"] == "open":
            return st["ymd"]
    return ""


def closed_tw_session(now: Optional[datetime] = None, db_path: str = None) -> Optional[Dict[str, str]]:
    if now is None:
        dt = datetime.now(TW)
    elif now.tzinfo is None:
        dt = now.replace(tzinfo=TW)
    else:
        dt = now.astimezone(TW)
    st = lookup_tw_session(dt.strftime("%Y%m%d"), db_path)
    if st["kind"] != "full_close":
        return None
    prev = previous_tw_trading_day(st["ymd"], db_path)
    return {**st, "prev_ymd": prev}


def holiday_banner_lines(closed: Optional[Dict[str, str]]) -> List[str]:
    """20260925 台股中秋節休市＋上一收盤 20260924。"""
    if not closed:
        return []
    zh = str(closed.get("zh") or "").strip()
    ymd = str(closed.get("ymd") or "")
    prev = str(closed.get("prev_ymd") or "")
    if not ymd or not zh:
        return []
    if zh == "僅結算":
        lines = [f"{ymd} 台股僅結算、無交易"]
    else:
        lines = [f"{ymd} 台股{zh}休市"]
    if prev:
        lines.append(f"上一收盤 {prev}")
    return lines


def fetch_twse_holiday_rows(timeout: int = 8) -> List[Any]:
    resp = requests.get(
        TWSE_HOLIDAY_URL,
        timeout=timeout,
        headers={"User-Agent": "WayneBot/1.0", "Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_dgpa_nds_html(timeout: int = 8) -> str:
    resp = requests.get(
        DGPA_NDS_URL,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WayneBot/1.0",
            "Accept": "text/html",
        },
    )
    resp.raise_for_status()
    raw = resp.content or b""
    for enc in ("utf-8", resp.apparent_encoding, "big5", "cp950"):
        if not enc:
            continue
        try:
            text = raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        if "停班" in text or "縣市" in text:
            return text
    return raw.decode("utf-8", errors="replace")


def _upsert_close(conn: sqlite3.Connection, ymd: str, zh: str, source: str) -> None:
    conn.execute(
        """
        INSERT INTO tw_holidays(ymd, kind, name_zh, source, fetched_at)
        VALUES (?, 'full_close', ?, ?, ?)
        ON CONFLICT(ymd) DO UPDATE SET
            kind='full_close',
            name_zh=excluded.name_zh,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        WHERE tw_holidays.source != 'twse' OR excluded.source = 'twse'
        """,
        (ymd, zh, source, datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S")),
    )


def refresh_tw_holiday_calendar(db_path: str = None, rows: List[Any] = None) -> Dict[str, Any]:
    """盤後抓證交所開休市表。解析不到足夠列就沿用種子，不寫空表。"""
    path = db_path or get_db_path()
    ensure_tw_holidays_table(path)
    try:
        raw = rows if rows is not None else fetch_twse_holiday_rows()
        parsed = parse_twse_holiday_rows(raw)
    except Exception:
        logger.warning("證交所開休市表抓不到", exc_info=True)
        parsed = {}
    if len(parsed) < 3:
        return {"ok": False, "full": 0, "reason": "parsed_too_few"}
    conn = sqlite3.connect(path)
    try:
        for ymd, rec in parsed.items():
            _upsert_close(conn, ymd, rec["zh"], rec.get("source") or "twse")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "full": len(parsed)}


def refresh_tw_typhoon_halt(db_path: str = None, html: str = None) -> Dict[str, Any]:
    """抓人事行政總處北市停班。全日／上午停班才寫休市；僅下午不當休市。"""
    path = db_path or get_db_path()
    ensure_tw_holidays_table(path)
    try:
        raw = html if html is not None else fetch_dgpa_nds_html()
        parsed = parse_dgpa_nds(raw)
    except Exception:
        logger.warning("人事行政總處停班頁抓不到", exc_info=True)
        return {"ok": False, "halt": False, "reason": "fetch_failed"}
    ymd = str(parsed.get("ymd") or "")
    if len(ymd) != 8:
        return {"ok": False, "halt": False, "reason": "no_date"}
    if not parsed.get("halt"):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "DELETE FROM tw_holidays WHERE ymd=? AND source='dgpa'",
                (ymd,),
            )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "halt": False, "ymd": ymd, "zh": ""}
    existing = lookup_tw_session(ymd, path)
    if existing.get("source") in ("twse", "seed"):
        return {
            "ok": True,
            "halt": True,
            "ymd": ymd,
            "zh": existing.get("zh") or str(parsed.get("zh") or "北市停班"),
            "kept": existing.get("source"),
        }
    conn = sqlite3.connect(path)
    try:
        _upsert_close(conn, ymd, str(parsed.get("zh") or "北市停班"), "dgpa")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "halt": True, "ymd": ymd, "zh": parsed.get("zh") or "北市停班"}
