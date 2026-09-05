"""台股收盤基準日：跳過週末；國定假日用證交所開休市表；颱風停市靠庫裡無完整行情。"""
from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
from typing import Optional, Set


_WEEKDAY_ZH = "一二三四五六日"

# 證交所 115 年開休市：只列「平日休市」（週末不必重複）。開始／最後交易日不列入。
# https://www.twse.com.tw/zh/trading/holiday.html
_CLOSED_WEEKDAYS_2026 = frozenset(
    {
        "20260101",
        "20260212",
        "20260213",
        "20260216",
        "20260217",
        "20260218",
        "20260219",
        "20260220",
        "20260227",
        "20260403",
        "20260406",
        "20260501",
        "20260619",
        "20260925",
        "20260928",
        "20261009",
        "20261026",
        "20261225",
    }
)
_CLOSED_CACHE: dict[str, Set[str]] = {"2026": set(_CLOSED_WEEKDAYS_2026)}


def _roc_to_ymd(roc_date: str) -> str:
    """1150101 → 20260101。"""
    s = str(roc_date or "").replace("-", "").strip()
    if len(s) == 7:
        yy, md = int(s[:3]), s[3:]
        return f"{yy + 1911}{md}"
    return s[:8]


def _row_is_closed_session(name: str, desc: str) -> bool:
    blob = f"{name or ''}{desc or ''}"
    if "開始交易" in blob or "最後交易" in blob:
        return False
    return "市場無交易" in blob or "放假" in blob or "補假" in blob


def _closed_weekdays_for_year(year: int) -> Set[str]:
    key = str(year)
    cached = _CLOSED_CACHE.get(key)
    if cached is not None:
        return cached
    closed: Set[str] = set()
    if year == 2026:
        closed.update(_CLOSED_WEEKDAYS_2026)
    try:
        import requests

        r = requests.get(
            "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
            timeout=4,
        )
        r.raise_for_status()
        rows = r.json()
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ymd = _roc_to_ymd(str(row.get("Date") or ""))
                if len(ymd) != 8 or not ymd.startswith(key):
                    continue
                try:
                    if datetime.strptime(ymd, "%Y%m%d").weekday() >= 5:
                        continue
                except ValueError:
                    continue
                if _row_is_closed_session(
                    str(row.get("Name") or ""), str(row.get("Description") or "")
                ):
                    closed.add(ymd)
    except Exception:
        pass
    _CLOSED_CACHE[key] = closed
    return closed


def is_tw_market_holiday(ymd: str) -> bool:
    """平日國定假／補假／無交易結算日。週末請用 weekday，不走這份表。"""
    s = normalize_ymd(ymd)
    if len(s) != 8:
        return False
    try:
        d = datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return False
    if d.weekday() >= 5:
        return False
    return s in _closed_weekdays_for_year(d.year)


def is_tw_open_calendar_day(ymd: str) -> bool:
    """週一～五且不是國定休市。颱風臨時停市不在年曆，仍靠庫無收盤。"""
    return is_trading_weekday(ymd) and not is_tw_market_holiday(ymd)


def normalize_ymd(val) -> str:
    return str(val or "").replace("-", "").strip()[:8]


def is_trading_weekday(ymd: str) -> bool:
    """週六日一定不是台股開盤日（其餘靠庫裡有無完整收盤判斷）。"""
    s = normalize_ymd(ymd)
    if len(s) != 8:
        return False
    try:
        return datetime.strptime(s, "%Y%m%d").weekday() < 5
    except ValueError:
        return False


def last_weekday_on_or_before(ymd: str) -> str:
    """往回跳過週六日，停在最近一個週一～五的日曆日。"""
    d = datetime.strptime(normalize_ymd(ymd), "%Y%m%d")
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def fuse_end_trading_date(now=None) -> str:
    """16:30 前不算今天；結果必為週一～五（不含國定假，假日本身靠 fuse 不寫庫）。"""
    from config import taipei_now

    now = now or taipei_now()
    cutoff = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if now >= cutoff:
        raw = now.strftime("%Y%m%d")
    else:
        raw = (now - timedelta(days=1)).strftime("%Y%m%d")
    return last_weekday_on_or_before(raw)


def format_trading_date_zh(ymd: str) -> str:
    """20260828 → 2026/08/28（五）"""
    s = normalize_ymd(ymd)
    if len(s) != 8:
        return str(ymd or "")
    try:
        d = datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return s
    wd = _WEEKDAY_ZH[d.weekday()]
    return f"{s[:4]}/{s[4:6]}/{s[6:8]}（{wd}）"


def resolve_screen_as_of(db_path: str, now=None) -> Optional[str]:
    """
    海選／盤後顯示基準日：
    1. 庫裡最近一個上市＋上櫃都齊的日期
    2. 不得晚於 fuse_end_trading_date
    3. 不得是週六日（庫裡若有殘留假資料也跳過）
    國定假日、颱風停市：官方無收盤 → 庫裡不會齊 → 自動往前找。
    """
    if not db_path:
        return fuse_end_trading_date(now)
    try:
        from import_health import latest_complete_quote_date

        complete = latest_complete_quote_date(db_path, now=now)
        if complete:
            return complete
    except Exception:
        pass
    return fuse_end_trading_date(now)


def morning_screen_pipeline_key(db_path: str, now=None) -> str:
    """早上海選 pipeline_runs 鍵：用 06:35 當下的基準日，避免盤後 fuse 後誤查 screen-{今日}。"""
    from config import taipei_now

    ref = now or taipei_now()
    morning = ref.replace(hour=6, minute=35, second=0, microsecond=0)
    as_of = resolve_screen_as_of(db_path, now=morning)
    return f"screen-{as_of or 'none'}"


def is_tw_equity_session(now=None) -> bool:
    """台股現股連續撮合：交易日 09:00–13:30。國定假日平日不當盤中。"""
    from config import taipei_now

    now = now or taipei_now()
    if now.weekday() >= 5:
        return False
    if is_tw_market_holiday(now.strftime("%Y%m%d")):
        return False
    t = now.time()
    return dt_time(9, 0) <= t <= dt_time(13, 30)


def tw_session_phase(now=None) -> str:
    """pre＝開盤前；open＝盤中；after＝收盤後；weekend＝週末或國定假。"""
    from config import taipei_now

    now = now or taipei_now()
    if now.weekday() >= 5 or is_tw_market_holiday(now.strftime("%Y%m%d")):
        return "weekend"
    t = now.time()
    if t < dt_time(9, 0):
        return "pre"
    if t <= dt_time(13, 30):
        return "open"
    return "after"


def overnight_list_heading(phase: str) -> tuple[str, str]:
    """非盤中隔日沖標題／副標。盤中維持「盤中即時」。"""
    if phase == "pre":
        return (
            "⚡ 隔日沖候選（開盤前預覽）",
            "開盤前預覽：昨收強勢候選，供今日尾盤佈局參考（09:00 後再依盤中價複核）。"
            "尾盤保險買進；明早開高+3.5～4.8%；防守跌破先走。",
        )
    if phase == "weekend":
        return (
            "⚡ 隔日沖候選（假日參考）",
            "假日參考：上個交易日強勢收盤候選，不是叫你現在買。"
            "明早開高觀察；未持倉僅供參考。",
        )
    return (
        "⚡ 隔日沖候選（收盤後參考）",
        "收盤後參考：今日強勢收盤候選，供明早開盤價差觀察。"
        "尾盤買進時段已過；若未持倉僅供觀察，不是叫你再買。",
    )


def daytrade_closed_title(phase: str) -> str:
    """非盤中當沖標題：不要再寫盤中即時。"""
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "假日"}.get(phase, "非盤中")
    return f"⚡ 當沖候選（{label}）"


def daytrade_closed_message(phase: str) -> str:
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "假日"}.get(phase, "非盤中")
    return (
        f"{label}。當沖只在平日 <b>09:00–13:30</b> 盤中即時複核；此刻不應再進當沖。"
        "尾盤想佈局明早，請看「隔日沖」；長線佈局請看「海選」。"
    )
