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
    return (os.getenv("GITHUB_RELEASE_URL") or "").strip()


def is_once_mode(argv=None) -> bool:
    """GitHub Actions / 本機一次性盤後排程：跑完流水線即結束。"""
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if "--once" in args or "--daily" in args:
        return True
    mode = (os.getenv("WAYNE_MODE") or os.getenv("RUN_MODE") or "web").strip().lower()
    return mode in ("once", "daily", "pipeline", "runner")


def daily_scheduler_enabled() -> bool:
    raw = (os.getenv("ENABLE_DAILY_SCHEDULER") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")
