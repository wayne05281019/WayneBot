"""台股收盤基準日：跳過週末；國定假日／颱風停市靠庫裡無完整行情自然排除。"""
from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
from typing import Optional


_WEEKDAY_ZH = "一二三四五六日"


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


def is_tw_equity_session(now=None) -> bool:
    """台股現股連續撮合：平日 09:00–13:30（當沖／隔日沖尾盤進場時段）。"""
    from config import taipei_now

    now = now or taipei_now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt_time(9, 0) <= t <= dt_time(13, 30)


def tw_session_phase(now=None) -> str:
    """pre＝開盤前；open＝盤中；after＝收盤後；weekend＝週末。"""
    from config import taipei_now

    now = now or taipei_now()
    if now.weekday() >= 5:
        return "weekend"
    t = now.time()
    if t < dt_time(9, 0):
        return "pre"
    if t <= dt_time(13, 30):
        return "open"
    return "after"


def daytrade_closed_message(phase: str) -> str:
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "假日"}.get(phase, "非盤中")
    return (
        f"{label}。當沖只在平日 <b>09:00–13:30</b> 盤中即時複核；此刻不應再進當沖。"
        "尾盤想佈局明早，請看「隔日沖」；長線佈局請看「海選」。"
    )
