"""台股收盤基準日：跳過週末；國定假日／北市停班見 tw_holidays。"""
from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta
from typing import Optional


_WEEKDAY_ZH = "一二三四五六日"


def is_tw_market_holiday(ymd: str) -> bool:
    """平日國定假／補假／僅結算／北市停班。週末請用 weekday，不走這份表。"""
    s = normalize_ymd(ymd)
    if len(s) != 8:
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return False
    from tw_holidays import lookup_tw_session

    return lookup_tw_session(s)["kind"] == "full_close"


def is_tw_open_calendar_day(ymd: str) -> bool:
    """週一～五且不是國定休市／北市停班。"""
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


def last_open_calendar_day_on_or_before(ymd: str) -> str:
    """往回跳過週末與台股休市（年曆／北市停班）。"""
    d = datetime.strptime(normalize_ymd(ymd), "%Y%m%d")
    for _ in range(20):
        s = d.strftime("%Y%m%d")
        if is_trading_weekday(s) and not is_tw_market_holiday(s):
            return s
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def fuse_end_trading_date(now=None) -> str:
    """16:30 前不算今天；結果必為可開市的週一～五。"""
    from config import taipei_now

    now = now or taipei_now()
    cutoff = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if now >= cutoff:
        raw = now.strftime("%Y%m%d")
    else:
        raw = (now - timedelta(days=1)).strftime("%Y%m%d")
    return last_open_calendar_day_on_or_before(raw)


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


def format_md_weekday(ymd: str) -> str:
    """20260909 → 9/9（三）。籌碼表頭用短日期＋星期。"""
    s = normalize_ymd(ymd)
    if len(s) != 8:
        return str(ymd or "")
    try:
        d = datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return s
    wd = _WEEKDAY_ZH[d.weekday()]
    return f"{int(s[4:6])}/{int(s[6:8])}（{wd}）"


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


def is_tw_tail_session(now=None) -> bool:
    """尾盤：交易日 12:45–13:30。當沖不該再新進，改對照已進場或看隔日沖。"""
    from config import taipei_now

    now = now or taipei_now()
    if not is_tw_equity_session(now):
        return False
    return now.time() >= dt_time(12, 45)


def tw_session_phase(now=None) -> str:
    """pre＝開盤前；open＝盤中；after＝收盤後；weekend＝週末或台股休市。"""
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
            "⚡ 隔日沖候選（休市參考）",
            "休市參考：上個交易日強勢收盤候選，不是叫你現在買。"
            "明早開高觀察；未持倉僅供參考。",
        )
    return (
        "⚡ 隔日沖候選（收盤後參考）",
        "收盤後參考：今日強勢收盤候選，供明早開盤價差觀察。"
        "尾盤買進時段已過；若未持倉僅供觀察，不是叫你再買。",
    )


def daytrade_closed_title(phase: str) -> str:
    """非盤中當沖標題：不要再寫盤中即時。"""
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "休市"}.get(phase, "非盤中")
    return f"⚡ 當沖候選（{label}）"


def daytrade_closed_message(phase: str) -> str:
    label = {"pre": "尚未開盤", "after": "已收盤", "weekend": "休市"}.get(phase, "非盤中")
    return (
        f"{label}。當沖只在平日 <b>09:00–13:30</b> 盤中即時複核；此刻不應再進當沖。"
        "尾盤想佈局明早，請看「隔日沖」；長線佈局請看「海選」。"
    )


def daytrade_list_heading(kind: str) -> tuple[str, str]:
    """盤中／尾盤當沖標題與「現在要做什麼」。數字怎麼讀寫在卡片上。"""
    if kind == "tail":
        return (
            "⚡ 當沖候選（尾盤）",
            "現在已過 12:45。沒進場的不要再進當沖。"
            "已進場的：看下面「漲到這裡先出／跌破這裡就走」。"
            "尾盤想佈局明早，請按「隔日沖」。",
        )
    return (
        "⚡ 當沖候選（盤中）",
        "現在盤中。沒進場：不要貴過「現在不要貴過」那一價。"
        "已進場：漲 3% 先出一部分，跌破均價先走。"
        "只列此刻漲幅 2%～8.5%；現價旁邊小字是報價幾點幾分。",
    )
