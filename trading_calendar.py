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


def morning_screen_pipeline_key(db_path: str, now=None) -> str:
    """早上海選 pipeline_runs 鍵：用 06:35 當下的基準日，避免盤後 fuse 後誤查 screen-{今日}。"""
    from config import taipei_now

    ref = now or taipei_now()
    morning = ref.replace(hour=6, minute=35, second=0, microsecond=0)
    as_of = resolve_screen_as_of(db_path, now=morning)
    return f"screen-{as_of or 'none'}"


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


def daytrade_closed_message(phase: str) -> str:
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "假日"}.get(phase, "非盤中")
    return (
        f"{label}。當沖只在平日 <b>09:00–13:30</b> 盤中即時複核；此刻不應再進當沖。"
        "尾盤想佈局明早，請看「隔日沖」；長線佈局請看「海選」。"
    )
