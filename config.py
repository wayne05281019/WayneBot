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


def get_public_base_url() -> str:
    """Telegram 開 LINE 鈕要走 https。Render 會帶 RENDER_EXTERNAL_URL。"""
    return (
        os.getenv("WAYNE_PUBLIC_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or "https://waynebot-service.onrender.com"
    ).rstrip("/")


def scheduled_job_kind(cron_expr: str) -> str:
    """GHA 兩個 cron：22:30 UTC＝早上海選；其餘＝盤後融合。"""
    s = str(cron_expr or "").strip().strip("'\"")
    if s.startswith("30 22") or " 22 " in f" {s} ":
        return "morning_screen"
    return "increment"


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
    """最後一個要把收盤寫進庫的交易日曆日（週末往回跳；假日靠官方無行情不寫庫）。"""
    from trading_calendar import fuse_end_trading_date

    return fuse_end_trading_date(now)


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


# 每個排程只能有一個擁有者，否則兩邊各自的 pipeline_runs 讓 skip_if_done 失效，
# 使用者會收到兩份同樣的推播。GHA 是可靠的計時器（Render 免費方案會休眠），
# 所以準時推播歸 GHA；Render 只負責讓自己磁碟上的庫保持新鮮供互動查詢。
SCHEDULER_ROLES = ("data", "full", "off")


def scheduler_role() -> str:
    """data＝只更新本機庫（預設）；full＝連推播一起跑；off＝完全不排程。"""
    raw = (os.getenv("WAYNE_SCHEDULER_ROLE") or "").strip().lower()
    if raw in SCHEDULER_ROLES:
        return raw
    if not daily_scheduler_enabled():
        return "off"
    return "data"


def scheduler_owns(job: str) -> bool:
    """這個行程是否該執行該排程。midday 只有常駐端有，所以 data 角色也要跑。"""
    role = scheduler_role()
    if role == "off":
        return False
    if role == "full":
        return True
    # data 角色：morning 推播歸 GHA，其餘（含唯一擁有者 midday）留在本地。
    return str(job or "").strip().lower() != "morning"


def scheduler_may_push(job: str) -> bool:
    """data 角色只在自己是唯一擁有者的排程上推播（midday）。"""
    role = scheduler_role()
    if role == "off":
        return False
    if role == "full":
        return True
    return str(job or "").strip().lower() == "midday"


def skip_telegram_polling() -> bool:
    """Cursor／本機除錯不要跟 Render 搶同一個 Bot 的 getUpdates。"""
    raw = (os.getenv("WAYNE_SKIP_POLLING") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")
