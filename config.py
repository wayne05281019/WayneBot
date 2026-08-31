# ==============================================================================
# WayneBot 全域設定：統一資料庫路徑、快取目錄與執行模式
# ==============================================================================
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_DEFAULT_DB = "data/wayne_market.db"


def get_db_path() -> str:
    path = (
        os.getenv("WAYNE_DB_PATH")
        or os.getenv("DB_PATH")
        or _DEFAULT_DB
    ).strip()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def get_cache_dir() -> str:
    path = (os.getenv("WAYNE_CACHE_DIR") or "waynebot_cache").strip()
    os.makedirs(path, exist_ok=True)
    return path


def get_charts_dir() -> str:
    path = (os.getenv("WAYNE_CHARTS_DIR") or os.path.join("data", "charts")).strip()
    os.makedirs(path, exist_ok=True)
    return path


def get_port() -> int:
    try:
        return int(os.getenv("PORT", "10000"))
    except ValueError:
        return 10000


def get_telegram_token() -> str:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TG_BOT_TOKEN")
        or ""
    ).strip()


def get_telegram_chat_id() -> str:
    return (
        os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("TG_CHAT_ID")
        or ""
    ).strip()


def get_telegram_config() -> dict:
    return {"token": get_telegram_token(), "chat_id": get_telegram_chat_id()}


def get_github_release_url() -> str:
    return (
        os.getenv("GITHUB_RELEASE_URL")
        or "https://github.com/wayne05281019/WayneBot/releases/download/v1.0-data/waynebot_production_complete.zip"
    ).strip()


def is_once_mode(argv=None) -> bool:
    """GitHub Actions / 本機一次性工作：跑完即結束（不開 Web／輪詢）。"""
    return job_kind(argv) in ("increment", "morning_screen", "evening_screen", "midday_review")


def taipei_now():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        from datetime import datetime
        return datetime.now()


def taipei_today_str() -> str:
    return taipei_now().strftime("%Y%m%d")


def fuse_end_date(now=None) -> str:
    """最後一個要把收盤寫進庫的日曆日。

    證交所 13:30 收、盤後到 14:30；櫃買 15:00 收。兩邊絕大多數收盤表
    最慢台灣 16:30 就齊，開機／盤中不要先寫「今天」。
    """
    from datetime import timedelta

    now = now or taipei_now()
    cutoff = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if now >= cutoff:
        return now.strftime("%Y%m%d")
    return (now - timedelta(days=1)).strftime("%Y%m%d")


def job_kind(argv=None) -> str:
    """once／increment＝盤後抓數；morning_screen＝早上只寄海選；web＝常駐。"""
    import sys

    args = argv if argv is not None else sys.argv[1:]
    mode = (os.getenv("WAYNE_JOB") or os.getenv("WAYNE_MODE") or os.getenv("RUN_MODE") or "").strip().lower()
    if "--morning" in args or "--morning-screen" in args or mode in ("morning", "morning_screen", "screen"):
        return "morning_screen"
    if "--evening" in args or "--evening-screen" in args or mode in ("evening", "evening_screen"):
        return "evening_screen"
    if "--midday" in args or "--midday-review" in args or mode in ("midday", "midday_review"):
        return "midday_review"
    if "--increment" in args or "--fuse" in args or mode in ("increment", "fuse"):
        return "increment"
    if "--once" in args or "--daily" in args or mode in ("once", "daily", "pipeline", "runner"):
        return "increment"
    return "web"


def daily_scheduler_enabled() -> bool:
    raw = (os.getenv("ENABLE_DAILY_SCHEDULER") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def skip_telegram_polling() -> bool:
    """Cursor／本機除錯不要跟 Render 搶同一個 Bot 的 getUpdates。"""
    raw = (os.getenv("WAYNE_SKIP_POLLING") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")
