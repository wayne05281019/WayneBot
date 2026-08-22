# -*- coding: utf-8 -*-
"""
========================================================================================
WayneBot 台股量化交易系統 (Phase 5)：台股即時與歷史數據採集模組
檔案名稱：data_fetcher.py
作者：Wayne (WayneBot Quantitative System Architect)
系統職責：
  1. 整合證交所 (TWSE) 與櫃買中心 (TPEX) 真實 API 接口：
     - 每日收盤行情 (上市 MI_INDEX / 上櫃 stk_wn1430)
     - 三大法人買賣超 (上市 T86 / 上櫃 3itrade_hedge)
     - 融資融券餘額 (上市 MI_MARGN / 上櫃 margin_bal)
  2. 智慧時間閘門 (Smart Time Gate)：
     - 精準判斷台股開盤日（自動過濾週休二日、國定假日、農曆年封關等）。
     - 統一結算時間門檻：交易日下午 16:30 (16:30:00) 以前嚴格熔斷，確保交易所行情與法人籌碼 100% 結算後才執行。
     - 未達結算時間或休市日自動熔斷並回退使用歷史快取，嚴禁覆蓋空資料 (Zero Overwrite Prevention)。
  3. 歷史壓縮檔與映射表增量更新：
     - 自動維護 history_1y_stocks.csv.gz 與 history_1y_chips.csv.gz (保留 1 年歷史、去重、原子替換)。
     - 自動維護 stock_map.json (上市/上櫃個股代碼、名稱、市場別對照表)。
  4. 資料庫高併發寫入 (SQLite WAL)：
     - 呼叫 wayne_db.py 之 get_db_connection() 進行批次事務寫入 (executemany)。
     - 寫入 daily_quotes, institutional_chips, margin_trading, stock_metadata, fetcher_audit_logs。
========================================================================================
"""

import os
import sys
import time
import json
import gzip
import csv
import re
import math
import random
import logging
import sqlite3
import datetime
from typing import Dict, List, Tuple, Optional, Any, Union, Set, Generator
from contextlib import contextmanager
import requests

# ======================================================================================
# 0. 環境路徑與日誌設定 (Logging & Path Configuration)
# ======================================================================================

BASE_DIR = "/content/waynebot_data" if "google.colab" in sys.modules else os.getenv("WAYNEBOT_DATA_DIR", "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_trading.db")
STOCKS_CSV_GZ = os.path.join(BASE_DIR, "history_1y_stocks.csv.gz")
CHIPS_CSV_GZ = os.path.join(BASE_DIR, "history_1y_chips.csv.gz")
STOCK_MAP_JSON = os.path.join(BASE_DIR, "stock_map.json")
CACHE_DIR = os.path.join(BASE_DIR, "raw_cache")
LOG_DIR = os.path.join(BASE_DIR, "logs")

try:
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("WayneBotDataFetcher")

# ======================================================================================
# 1. 數值清洗與基礎輔助函式 (Sanitization & Helper Functions)
# ======================================================================================

def clean_number(val: Any, default: float = 0.0) -> float:
    """
    通用數值清洗函式：
    過濾逗號、正負號、百分比符號、NaN、Inf、暫停交易等非數值字串。
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default
        return float(val)
    
    val_str = str(val).strip()
    invalid_literals = {
        '', 'n/a', 'None', 'nan', 'NULL', 'N/A', '-', 'NA', 'NaN', 'null', 
        '--', '暫停交易', '除權', '除息', 'X', 'x'
    }
    if val_str in invalid_literals:
        return default
    
    cleaned = val_str.replace(',', '').replace('+', '').replace('%', '')
    cleaned = cleaned.replace('X', '').replace('=', '').replace('"', '').replace(' ', '').strip()
    
    try:
        res = float(cleaned)
        if math.isnan(res) or math.isinf(res):
            return default
        return res
    except (ValueError, TypeError):
        return default


def clean_int(val: Any, default: int = 0) -> int:
    """整數清洗函式（四捨五入）"""
    return int(round(clean_number(val, float(default))))


def safe_div(num: Any, den: Any, default: float = 0.0) -> float:
    """防除以零安全運算函式"""
    try:
        f_num = float(num)
        f_den = float(den)
        if f_den == 0.0 or math.isnan(f_den) or math.isnan(f_num) or math.isinf(f_den) or math.isinf(f_num):
            return default
        return f_num / f_den
    except Exception:
        return default


def normalize_ticker(raw_ticker: Any, market: str = "TW") -> str:
    """
    正規化股票代號，補齊後綴：
    例：'2330' -> '2330.TW', '6770' -> '6770.TWO'
    """
    if not raw_ticker:
        return ""
    s = str(raw_ticker).strip().upper().replace("=", "").replace('"', '')
    for suffix in (".TW", ".TWO", ".TPEX", ".TAIEX"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    s = re.sub(r'[^A-Z0-9]', '', s)
    if not s:
        return ""
    m = "TWO" if market.upper() in ("TWO", "TPEX", "OTC") else "TW"
    return f"{s}.{m}"


def strip_ticker(ticker: Any) -> str:
    """取得純代號（去除 .TW, .TWO 等後綴）"""
    if not ticker:
        return ""
    s = str(ticker).strip().upper()
    for suffix in (".TW", ".TWO", ".TPEX", ".TAIEX"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    return re.sub(r'[^A-Z0-9]', '', s)


def ad_to_roc_date_str(dt: datetime.date) -> str:
    """西元日期轉民國日期字串（例：2026-08-20 -> '115/08/20'）"""
    roc_year = dt.year - 1911
    return f"{roc_year}/{dt.month:02d}/{dt.day:02d}"


def parse_date_str(date_input: Union[str, datetime.date, datetime.datetime]) -> datetime.date:
    """
    將多種日期格式統一解析為 datetime.date 物件。
    支援 '20260820', '2026-08-20', '115/08/20' 等。
    """
    if isinstance(date_input, datetime.datetime):
        return date_input.date()
    if isinstance(date_input, datetime.date):
        return date_input
    
    s = str(date_input).strip()
    if not s or s.startswith("-"):
        raise ValueError(f"無效的日期參數輸入: {date_input}")

    # 民國年月日 (例: 115/08/20)
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            y = int(parts[0])
            if y < 1900:
                y += 1911
            return datetime.date(y, int(parts[1]), int(parts[2]))
    
    # ISO 格式 (例: 2026-08-20)
    if "-" in s:
        parts = s.split("-")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            
    # 純數字格式 (例: 20260820)
    if len(s) == 8 and s.isdigit():
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        
    raise ValueError(f"無法解析的日期格式: {date_input}")

# ======================================================================================
# 2. 資料庫連線與事務管理 (Database Connection & WAL Integration)
# ======================================================================================

try:
    import wayne_db
    _external_get_db_conn = getattr(wayne_db, "get_db_connection", None)
except ImportError:
    wayne_db = None
    _external_get_db_conn = None


@contextmanager
def get_db_connection(db_path: str = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """
    資料庫連線上下文管理器：
    支援自動 WAL 模式、高併發鎖定逾時重試、自動 Commit 與異常 Rollback。
    """
    if _external_get_db_conn is not None and db_path == DB_PATH:
        with _external_get_db_conn() as conn:
            yield conn
        return

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000;")
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception as e:
        logger.warning(f"PRAGMA 設定警告: {e}")
        
    try:
        yield conn
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error(f"資料庫事務執行失敗，已 Rollback: {exc}")
        raise
    finally:
        conn.close()


def init_database_schema(db_path: str = DB_PATH) -> None:
    """初始化資料庫表格結構與索引"""
    schema_sql = """
    -- 每日收盤行情表 (TWSE + TPEX)
    CREATE TABLE IF NOT EXISTS daily_quotes (
        date TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        market TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume INTEGER NOT NULL,
        turnover_k REAL NOT NULL,
        pct_change REAL NOT NULL,
        avg_price REAL NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (date, stock_id)
    );

    -- 三大法人籌碼表 (外資/投信/自營商)
    CREATE TABLE IF NOT EXISTS institutional_chips (
        date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        foreign_buy_sell REAL NOT NULL,
        trust_buy_sell REAL NOT NULL,
        dealer_buy_sell REAL NOT NULL,
        institutional_total REAL NOT NULL,
        total_volume REAL NOT NULL,
        close_price REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (date, ticker)
    );

    -- 融資融券信用交易表
    CREATE TABLE IF NOT EXISTS margin_trading (
        date TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        margin_buy INTEGER NOT NULL,
        margin_sell INTEGER NOT NULL,
        margin_balance INTEGER NOT NULL,
        margin_change INTEGER NOT NULL,
        short_buy INTEGER NOT NULL,
        short_sell INTEGER NOT NULL,
        short_balance INTEGER NOT NULL,
        short_change INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (date, stock_id)
    );

    -- 個股基本資訊與產業別對照表
    CREATE TABLE IF NOT EXISTS stock_metadata (
        stock_id TEXT PRIMARY KEY,
        stock_name TEXT NOT NULL,
        market TEXT NOT NULL,
        industry TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );

    -- 數據採集稽核日誌
    CREATE TABLE IF NOT EXISTS fetcher_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        fetch_type TEXT NOT NULL,
        status TEXT NOT NULL,
        record_count INTEGER NOT NULL,
        message TEXT,
        created_at TEXT NOT NULL
    );

    -- 建立加速查詢索引
    CREATE INDEX IF NOT EXISTS idx_quotes_sid_date ON daily_quotes(stock_id, date);
    CREATE INDEX IF NOT EXISTS idx_chips_ticker_date ON institutional_chips(ticker, date);
    CREATE INDEX IF NOT EXISTS idx_margin_sid_date ON margin_trading(stock_id, date);
    """
    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)
    logger.info("資料庫結構校驗與初始化完成。")

# ======================================================================================
# 3. 智慧時間閘門與台股交易日曆 (Smart Time Gate & Taiwan Trading Calendar)
# ======================================================================================

class TaiwanTradingCalendar:
    """
    台股交易日曆管理：
    精準過濾六日、國定假日、農曆年封關日與彈性休市。
    """
    HOLIDAYS_SET: Set[str] = {
        # 2024 休市日
        "2024-01-01", "2024-02-06", "2024-02-07", "2024-02-08", "2024-02-09",
        "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-28", "2024-04-04",
        "2024-04-05", "2024-05-01", "2024-06-10", "2024-09-17", "2024-10-10",
        # 2025 休市日
        "2025-01-01", "2025-01-23", "2025-01-24", "2025-01-27", "2025-01-28",
        "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-28", "2025-04-03",
        "2025-04-04", "2025-05-01", "2025-05-30", "2025-10-06", "2025-10-10",
        # 2026 休市日 (含元旦、春節、228、清明、端午、中秋、國慶、勞動節)
        "2026-01-01", "2026-02-13", "2026-02-16", "2026-02-17", "2026-02-18",
        "2026-02-19", "2026-02-20", "2026-02-27", "2026-04-03", "2026-04-06",
        "2026-05-01", "2026-06-19", "2026-09-25", "2026-10-09",
        # 2027 休市日
        "2027-01-01", "2027-02-04", "2027-02-05", "2027-02-08", "2027-02-09",
        "2027-02-10", "2027-02-11", "2027-02-12", "2027-02-26", "2027-04-02",
        "2027-04-05", "2027-04-30", "2027-06-09", "2027-09-15", "2027-10-08"
    }

    @classmethod
    def is_holiday(cls, dt: datetime.date) -> bool:
        """判斷是否為預設休假日或國定假日"""
        d_str = dt.strftime("%Y-%m-%d")
        return d_str in cls.HOLIDAYS_SET

    @classmethod
    def is_trading_day(cls, dt: datetime.date) -> bool:
        """
        判斷指定日期是否為台股開盤日：
        1. 星期六 (5) 或 星期日 (6) 為休市。
        2. 在 HOLIDAYS_SET 名單中為休市。
        """
        if dt.weekday() in (5, 6):
            return False
        if cls.is_holiday(dt):
            return False
        return True

    @classmethod
    def get_previous_trading_day(cls, dt: datetime.date) -> datetime.date:
        """取得指定日期之前的最近一個開盤交易日"""
        cur = dt - datetime.timedelta(days=1)
        while not cls.is_trading_day(cur):
            cur -= datetime.timedelta(days=1)
        return cur

    @classmethod
    def get_latest_available_trading_day(cls, ref_dt: Optional[datetime.datetime] = None) -> datetime.date:
        """
        根據當前時間判斷最新可用的交易日：
        若當日為開盤日但時間尚未達下午 16:30，最新已結算交易日為上一交易日；
        若當日非開盤日，則回退至最近開盤日。
        """
        if ref_dt is None:
            ref_dt = datetime.datetime.now()
        today = ref_dt.date()
        
        if not cls.is_trading_day(today):
            return cls.get_previous_trading_day(today)
            
        # 嚴格設定：未達下午 16:30 前，回退至上一交易日
        if ref_dt.time() < datetime.time(16, 30):
            return cls.get_previous_trading_day(today)
            
        return today


class SmartTimeGate:
    """
    智慧時間閘門：
    嚴格鎖定開盤日下午 16:30:00 為行情與法人籌碼結算放行點，未達時間自動熔斷保護。
    """
    # 統一鎖定在有交易日的下午 16:30 (4:30 PM)
    QUOTES_EARLIEST_TIME = datetime.time(16, 30)      # 收盤行情結算放行時間 (16:30)
    CHIPS_EARLIEST_TIME = datetime.time(16, 30)       # 三大法人 T86 結算放行時間 (16:30)
    MARGIN_EARLIEST_TIME = datetime.time(20, 45)      # 融資融券結算放行時間 (20:45)

    @classmethod
    def evaluate_gate(
        cls, 
        data_type: str, 
        target_date: datetime.date, 
        now_dt: Optional[datetime.datetime] = None
    ) -> Tuple[bool, str]:
        """
        評估時間閘門是否放行：
        返回 (is_allowed, reason)
        """
        if now_dt is None:
            now_dt = datetime.datetime.now()
            
        target_date_str = target_date.strftime("%Y-%m-%d")
        today = now_dt.date()
        
        # 1. 未來日期直接阻擋
        if target_date > today:
            return False, f"[熔斷] 目標日期 {target_date_str} 為未來日期，禁止抓取。"

        # 2. 休市日判斷
        if not TaiwanTradingCalendar.is_trading_day(target_date):
            return False, f"[熔斷] 目標日期 {target_date_str} 為週末或國定休市日，自動跳過即時採集。"

        # 3. 過去的交易日（非今日），數據必定已結算完成，一律放行
        if target_date < today:
            return True, f"[放行] 歷史交易日 {target_date_str} 數據已結算。"

        # 4. 當日數據嚴格檢查 16:30 時間閘門
        cur_time = now_dt.time()
        
        if data_type == "quotes":
            if cur_time < cls.QUOTES_EARLIEST_TIME:
                return False, f"[時間閘門攔截] 尚未達下午 16:30 結算標準 (當前 {cur_time.strftime('%H:%M:%S')} < {cls.QUOTES_EARLIEST_TIME})，熔斷保護。"
            return True, f"[放行] 今日收盤行情已結算 (>= 16:30)。"

        elif data_type == "chips":
            if cur_time < cls.CHIPS_EARLIEST_TIME:
                return False, f"[時間閘門攔截] 尚未達下午 16:30 三大法人結算標準 (當前 {cur_time.strftime('%H:%M:%S')} < {cls.CHIPS_EARLIEST_TIME})，熔斷保護。"
            return True, f"[放行] 今日三大法人籌碼已公佈 (>= 16:30)。"

        elif data_type == "margin":
            if cur_time < cls.MARGIN_EARLIEST_TIME:
                return False, f"[時間閘門攔截] 融資融券尚未結算 (當前 {cur_time.strftime('%H:%M:%S')} < {cls.MARGIN_EARLIEST_TIME})，熔斷保護。"
            return True, f"[放行] 今日融資融券餘額已結算。"

        return True, "[放行] 未知資料類型默認通過。"

# ======================================================================================
# 4. 網絡通訊引擎與真實 API 爬取 (Robust HTTP Requester & Crawlers)
# ======================================================================================

class RobustHttpRequester:
    """
    高穩定度 HTTP 請求器：
    包含 User-Agent 隨機輪替、指數退避重試、防 429 延遲與連線逾時保護。
    """
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/125.0.2535.92"
    ]

    def __init__(self, timeout: int = 20, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": "https://www.twse.com.tw/zh/page/trading/exchange/MI_INDEX.html"
        }

    def fetch_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """執行 GET 請求並回傳解析後之 JSON 字典，失敗時執行重試"""
        for attempt in range(1, self.max_retries + 1):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                resp = self.session.get(url, params=params, headers=self.get_headers(), timeout=self.timeout)
                
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception:
                        return json.loads(resp.content.decode("utf-8-sig", errors="replace"))
                        
                elif resp.status_code == 429:
                    sleep_time = attempt * 3.0 + random.uniform(1.0, 2.0)
                    logger.warning(f"[429 Rate Limit] 觸發頻率限制，等待 {sleep_time:.1f} 秒後重試...")
                    time.sleep(sleep_time)
                else:
                    time.sleep(attempt * 1.5)
            except Exception as e:
                logger.warning(f"[連線異常] {url} 發生錯誤: {e} (嘗試 {attempt}/{self.max_retries})")
                time.sleep(attempt * 1.5)
                
        logger.error(f"[採集失敗] 已達最大重試次數，無法自 {url} 取得資料。")
        return None


class TWSEFetcher:
    """臺灣證券交易所 (TWSE) 上市數據採集器"""
    BASE_URL = "https://www.twse.com.tw"

    def __init__(self, requester: RobustHttpRequester):
        self.requester = requester

    def fetch_daily_quotes(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上市每日收盤行情 (MI_INDEX)"""
        date_str = target_date.strftime("%Y%m%d")
        url = f"{self.BASE_URL}/rwd/zh/afterTrading/MI_INDEX"
        params = {"date": date_str, "type": "ALLBUT0999", "response": "json"}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_daily_quotes(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_daily_quotes(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TWSE 每日收盤行情 JSON 結構"""
        tables = raw.get("tables", [])
        data_rows = []
        
        for t in tables:
            title = t.get("title", "")
            fields = t.get("fields", [])
            if "每日收盤行情" in title or "價格資訊" in title or len(fields) >= 14:
                data_rows = t.get("data", [])
                break
                
        if not data_rows and "data9" in raw:
            data_rows = raw["data9"]
        elif not data_rows and "data8" in raw:
            data_rows = raw["data8"]
        elif not data_rows and "data" in raw:
            data_rows = raw["data"]

        records = []
        for r in data_rows:
            if len(r) < 11:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue
                
            sname = str(r[1]).strip()
            vol_shares = clean_number(r[2])
            vol_lots = clean_int(vol_shares / 1000.0)
            turnover_k = round(clean_number(r[4]) / 1000.0, 2)
            open_p = clean_number(r[5])
            high_p = clean_number(r[6])
            low_p = clean_number(r[7])
            close_p = clean_number(r[8])
            sign = str(r[9])
            diff = clean_number(r[10])
            
            if open_p == 0.0: open_p = close_p
            if high_p == 0.0: high_p = close_p
            if low_p == 0.0: low_p = close_p
            
            prev_close = close_p - diff if ("+" in sign or "▲" in sign or "red" in sign) else (
                close_p + diff if ("-" in sign or "▼" in sign or "green" in sign) else close_p
            )
            pct_change = round(safe_div(close_p - prev_close, prev_close) * 100.0, 2)
            avg_p = round(safe_div(turnover_k * 1000.0, vol_shares, default=close_p), 2)

            records.append({
                "date": date_formatted,
                "stock_id": sid,
                "stock_name": sname,
                "market": "TW",
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol_lots,
                "turnover_k": turnover_k,
                "pct_change": pct_change,
                "avg_price": avg_p,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records

    def fetch_institutional_investors(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上市三大法人買賣超日報 (T86)"""
        date_str = target_date.strftime("%Y%m%d")
        url = f"{self.BASE_URL}/rwd/zh/fund/T86"
        params = {"date": date_str, "selectType": "ALLBUT0999", "response": "json"}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_institutional_investors(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_institutional_investors(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TWSE T86 三大法人買賣超 JSON"""
        data_rows = raw.get("data", [])
        if not data_rows and "tables" in raw:
            for t in raw["tables"]:
                if "三大法人" in t.get("title", ""):
                    data_rows = t.get("data", [])
                    break

        records = []
        for r in data_rows:
            if len(r) < 12:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue

            foreign_net = clean_number(r[4])
            if len(r) >= 8 and str(r[7]).replace(',', '').lstrip('-').isdigit():
                foreign_net += clean_number(r[7])
                
            trust_net = clean_number(r[10]) if len(r) > 10 else 0.0
            dealer_net = clean_number(r[11]) if len(r) > 11 else 0.0
            total_net = clean_number(r[18]) if len(r) > 18 else (foreign_net + trust_net + dealer_net)

            records.append({
                "date": date_formatted,
                "ticker": f"{sid}.TW",
                "stock_id": sid,
                "foreign_buy_sell": round(foreign_net / 1000.0, 2),
                "trust_buy_sell": round(trust_net / 1000.0, 2),
                "dealer_buy_sell": round(dealer_net / 1000.0, 2),
                "institutional_total": round(total_net / 1000.0, 2),
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records

    def fetch_margin_trading(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上市融資融券餘額 (MI_MARGN)"""
        date_str = target_date.strftime("%Y%m%d")
        url = f"{self.BASE_URL}/rwd/zh/marginTrading/MI_MARGN"
        params = {"date": date_str, "selectType": "ALL", "response": "json"}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_margin_trading(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_margin_trading(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TWSE 融資融券餘額 JSON"""
        tables = raw.get("tables", [])
        data_rows = []
        for t in tables:
            if "融資融券" in t.get("title", ""):
                data_rows = t.get("data", [])
                break
        if not data_rows and "data" in raw:
            data_rows = raw["data"]

        records = []
        for r in data_rows:
            if len(r) < 14:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue
                
            m_buy = clean_int(r[2])
            m_sell = clean_int(r[3])
            m_prev = clean_int(r[5])
            m_bal = clean_int(r[6])
            m_change = m_bal - m_prev

            s_buy = clean_int(r[8])
            s_sell = clean_int(r[9])
            s_prev = clean_int(r[11])
            s_bal = clean_int(r[12])
            s_change = s_bal - s_prev

            records.append({
                "date": date_formatted,
                "stock_id": sid,
                "margin_buy": m_buy,
                "margin_sell": m_sell,
                "margin_balance": m_bal,
                "margin_change": m_change,
                "short_buy": s_buy,
                "short_sell": s_sell,
                "short_balance": s_bal,
                "short_change": s_change,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records


class TPEXFetcher:
    """證券櫃檯買賣中心 (TPEX) 上櫃數據採集器"""
    BASE_URL = "https://www.tpex.org.tw"

    def __init__(self, requester: RobustHttpRequester):
        self.requester = requester

    def fetch_daily_quotes(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上櫃每日收盤行情 (stk_wn1430)"""
        roc_date_str = ad_to_roc_date_str(target_date)
        url = f"{self.BASE_URL}/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"
        params = {"l": "zh-tw", "d": roc_date_str, "se": "AL", "_": int(time.time() * 1000)}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_daily_quotes(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_daily_quotes(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TPEX 收盤行情 JSON"""
        data_rows = raw.get("aaData", [])
        if not data_rows and "tables" in raw:
            for t in raw["tables"]:
                data_rows = t.get("data", [])
                if data_rows: break

        records = []
        for r in data_rows:
            if len(r) < 9:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue
                
            sname = str(r[1]).strip()
            close_p = clean_number(r[2])
            diff_str = str(r[3]).strip()
            diff = clean_number(diff_str)
            open_p = clean_number(r[4], default=close_p)
            high_p = clean_number(r[5], default=close_p)
            low_p = clean_number(r[6], default=close_p)
            vol_shares = clean_number(r[7])
            vol_lots = clean_int(vol_shares / 1000.0)
            turnover_k = round(clean_number(r[8]) / 1000.0, 2)
            
            prev_close = close_p - diff if "+" in diff_str else (close_p + diff if "-" in diff_str else close_p)
            pct_change = round(safe_div(close_p - prev_close, prev_close) * 100.0, 2)
            avg_p = round(safe_div(turnover_k * 1000.0, vol_shares, default=close_p), 2)

            records.append({
                "date": date_formatted,
                "stock_id": sid,
                "stock_name": sname,
                "market": "TWO",
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": vol_lots,
                "turnover_k": turnover_k,
                "pct_change": pct_change,
                "avg_price": avg_p,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records

    def fetch_institutional_investors(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上櫃三大法人買賣超 (3itrade_hedge)"""
        roc_date_str = ad_to_roc_date_str(target_date)
        url = f"{self.BASE_URL}/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
        params = {"l": "zh-tw", "se": "AL", "t": "D", "d": roc_date_str, "_": int(time.time() * 1000)}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_institutional_investors(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_institutional_investors(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TPEX 三大法人買賣超 JSON"""
        data_rows = raw.get("aaData", [])
        records = []
        for r in data_rows:
            if len(r) < 11:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue
                
            foreign_net = clean_number(r[4])
            trust_net = clean_number(r[7])
            dealer_net = clean_number(r[10])
            total_net = clean_number(r[11]) if len(r) > 11 else (foreign_net + trust_net + dealer_net)

            records.append({
                "date": date_formatted,
                "ticker": f"{sid}.TWO",
                "stock_id": sid,
                "foreign_buy_sell": round(foreign_net / 1000.0, 2),
                "trust_buy_sell": round(trust_net / 1000.0, 2),
                "dealer_buy_sell": round(dealer_net / 1000.0, 2),
                "institutional_total": round(total_net / 1000.0, 2),
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records

    def fetch_margin_trading(self, target_date: datetime.date) -> List[Dict[str, Any]]:
        """抓取上櫃融資融券餘額 (margin_bal)"""
        roc_date_str = ad_to_roc_date_str(target_date)
        url = f"{self.BASE_URL}/web/stock/margin_trading/margin_bal/margin_bal_result.php"
        params = {"l": "zh-tw", "d": roc_date_str, "_": int(time.time() * 1000)}
        
        raw = self.requester.fetch_json(url, params=params)
        if not raw:
            return []

        return self.parse_margin_trading(raw, target_date.strftime("%Y-%m-%d"))

    @staticmethod
    def parse_margin_trading(raw: Dict[str, Any], date_formatted: str) -> List[Dict[str, Any]]:
        """解析 TPEX 融資融券餘額 JSON"""
        data_rows = raw.get("aaData", [])
        records = []
        for r in data_rows:
            if len(r) < 15:
                continue
            sid = str(r[0]).strip().replace("=", "").replace('"', "")
            if not (4 <= len(sid) <= 6 and (sid.isdigit() or sid.endswith("L") or sid.endswith("R"))):
                continue
                
            m_prev = clean_int(r[2])
            m_buy = clean_int(r[3])
            m_sell = clean_int(r[4])
            m_bal = clean_int(r[6])
            m_change = m_bal - m_prev

            s_prev = clean_int(r[10])
            s_buy = clean_int(r[11])
            s_sell = clean_int(r[12])
            s_bal = clean_int(r[14])
            s_change = s_bal - s_prev

            records.append({
                "date": date_formatted,
                "stock_id": sid,
                "margin_buy": m_buy,
                "margin_sell": m_sell,
                "margin_balance": m_bal,
                "margin_change": m_change,
                "short_buy": s_buy,
                "short_sell": s_sell,
                "short_balance": s_bal,
                "short_change": s_change,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        return records

# ======================================================================================
# 5. 數據嚴格校驗防線 (Sanity Check & Anti-Corrupt Guard)
# ======================================================================================

class SanityCheckGuard:
    """
    數據完整性守門員：
    防止因交易所連線失敗、格式異動或空資料覆蓋歷史快取與正式資料庫。
    """
    MIN_QUOTES_COUNT = 5
    MIN_CHIPS_COUNT = 2
    MIN_MARGIN_COUNT = 1

    @classmethod
    def validate_quotes(cls, quotes: List[Dict[str, Any]], min_count: Optional[int] = None) -> bool:
        threshold = min_count if min_count is not None else cls.MIN_QUOTES_COUNT
        if not isinstance(quotes, list) or len(quotes) < threshold:
            logger.warning(f"[Sanity Check 攔截] 收盤行情筆數不足 ({len(quotes)} < {threshold})")
            return False
        valid_prices = [q for q in quotes if q.get("close", 0.0) > 0.0]
        if len(valid_prices) < len(quotes) * 0.7:
            logger.warning("[Sanity Check 攔截] 收盤行情價格異常偏低或零值比例過高！")
            return False
        return True

    @classmethod
    def validate_chips(cls, chips: List[Dict[str, Any]], min_count: Optional[int] = None) -> bool:
        threshold = min_count if min_count is not None else cls.MIN_CHIPS_COUNT
        return isinstance(chips, list) and len(chips) >= threshold

    @classmethod
    def validate_margin(cls, margins: List[Dict[str, Any]], min_count: Optional[int] = None) -> bool:
        threshold = min_count if min_count is not None else cls.MIN_MARGIN_COUNT
        return isinstance(margins, list) and len(margins) >= threshold

# ======================================================================================
# 6. 歷史壓縮檔與映射表增量管理器 (History & Storage Manager)
# ======================================================================================

class HistoryStorageManager:
    """
    歷史壓縮資料與對照表管理：
    負責 history_1y_stocks.csv.gz, history_1y_chips.csv.gz, stock_map.json
    之原子寫入 (Atomic Write)、去重合併與滾動保留 1 年窗口。
    """

    @staticmethod
    def _read_existing_gzip_csv(file_path: str) -> List[Dict[str, str]]:
        """安全讀取現存的 .csv.gz 壓縮檔"""
        if not os.path.exists(file_path):
            return []
        records = []
        try:
            with gzip.open(file_path, "rt", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
        except Exception:
            pass
        return records

    @staticmethod
    def _atomic_write_gzip_csv(file_path: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
        """原子寫入 Gzip CSV 檔案（先寫入 .tmp 再 rename 避免寫入中斷毀損檔案）"""
        tmp_path = f"{file_path}.tmp"
        try:
            with gzip.open(tmp_path, "wt", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in fieldnames})
            os.replace(tmp_path, file_path)
            logger.info(f"[原子寫入成功] {file_path} (共 {len(rows)} 行)")
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise e

    @classmethod
    def update_history_stocks_csv(
        cls, 
        new_quotes: List[Dict[str, Any]], 
        file_path: str = STOCKS_CSV_GZ, 
        max_days: int = 365
    ) -> None:
        if not new_quotes:
            return

        fields = [
            "date", "stock_id", "stock_name", "market", "open", "high", 
            "low", "close", "volume", "turnover_k", "pct_change", "avg_price", "updated_at"
        ]
        
        existing_rows = cls._read_existing_gzip_csv(file_path)
        data_map = {(r["date"], r["stock_id"]): r for r in existing_rows if "date" in r and "stock_id" in r}
        for q in new_quotes:
            data_map[(q["date"], q["stock_id"])] = q

        all_dates = sorted({k[0] for k in data_map.keys()})
        if len(all_dates) > max_days:
            cutoff_date = all_dates[-max_days]
            data_map = {k: v for k, v in data_map.items() if k[0] >= cutoff_date}

        sorted_rows = sorted(data_map.values(), key=lambda x: (x.get("date", ""), x.get("stock_id", "")))
        cls._atomic_write_gzip_csv(file_path, fields, sorted_rows)

    @classmethod
    def update_history_chips_csv(
        cls, 
        new_chips: List[Dict[str, Any]], 
        file_path: str = CHIPS_CSV_GZ, 
        max_days: int = 365
    ) -> None:
        if not new_chips:
            return

        fields = [
            "ticker", "date", "close_price", "foreign_buy_sell", "trust_buy_sell", 
            "dealer_buy_sell", "institutional_total", "total_volume", 
            "margin_balance", "short_balance", "status", "cleaned_at"
        ]

        existing_rows = cls._read_existing_gzip_csv(file_path)
        data_map = {(r["ticker"], r["date"]): r for r in existing_rows if "ticker" in r and "date" in r}
        for c in new_chips:
            data_map[(c["ticker"], c["date"])] = c

        all_dates = sorted({k[1] for k in data_map.keys()})
        if len(all_dates) > max_days:
            cutoff_date = all_dates[-max_days]
            data_map = {k: v for k, v in data_map.items() if k[1] >= cutoff_date}

        sorted_rows = sorted(data_map.values(), key=lambda x: (x.get("date", ""), x.get("ticker", "")))
        cls._atomic_write_gzip_csv(file_path, fields, sorted_rows)

    @classmethod
    def update_stock_map_json(cls, stock_metas: List[Dict[str, Any]], file_path: str = STOCK_MAP_JSON) -> None:
        if not stock_metas:
            return

        current_map = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    current_map = json.load(f)
            except Exception:
                pass

        for meta in stock_metas:
            sid = meta.get("stock_id", "").strip()
            if not sid:
                continue
            current_map[sid] = {
                "name": meta.get("stock_name", ""),
                "market": meta.get("market", "TW"),
                "industry": meta.get("industry", ""),
                "is_active": 1,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        tmp_path = f"{file_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(current_map, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, file_path)
            logger.info(f"[對照表更新成功] {file_path} (共 {len(current_map)} 檔標的)")
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# ======================================================================================
# 7. 資料庫批次事務寫入器 (Database Batch Writer)
# ======================================================================================

class DatabaseBatchWriter:
    @staticmethod
    def batch_write_all(
        target_date: str,
        quotes: List[Dict[str, Any]],
        chips: List[Dict[str, Any]],
        margins: List[Dict[str, Any]],
        stock_metas: List[Dict[str, Any]],
        db_path: str = DB_PATH
    ) -> Dict[str, int]:
        init_database_schema(db_path)
        stats = {"quotes": 0, "chips": 0, "margins": 0, "metadata": 0}
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()

            # 1. 寫入收盤行情
            if quotes:
                quote_tuples = [
                    (
                        q["date"], q["stock_id"], q["stock_name"], q["market"],
                        q["open"], q["high"], q["low"], q["close"], q["volume"],
                        q["turnover_k"], q["pct_change"], q["avg_price"], q.get("updated_at", now_str)
                    )
                    for q in quotes
                ]
                cursor.executemany("""
                    INSERT OR REPLACE INTO daily_quotes (
                        date, stock_id, stock_name, market, open, high, low, close,
                        volume, turnover_k, pct_change, avg_price, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, quote_tuples)
                stats["quotes"] = len(quote_tuples)

            # 2. 寫入三大法人籌碼
            if chips:
                chip_tuples = [
                    (
                        c["date"], c["ticker"], c["stock_id"],
                        c["foreign_buy_sell"], c["trust_buy_sell"], c["dealer_buy_sell"],
                        c["institutional_total"], c["total_volume"], c["close_price"],
                        c.get("status", "active"), c.get("updated_at", now_str)
                    )
                    for c in chips
                ]
                cursor.executemany("""
                    INSERT OR REPLACE INTO institutional_chips (
                        date, ticker, stock_id, foreign_buy_sell, trust_buy_sell,
                        dealer_buy_sell, institutional_total, total_volume, close_price,
                        status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, chip_tuples)
                stats["chips"] = len(chip_tuples)

            # 3. 寫入融資融券
            if margins:
                margin_tuples = [
                    (
                        m["date"], m["stock_id"], m["margin_buy"], m["margin_sell"],
                        m["margin_balance"], m["margin_change"], m["short_buy"],
                        m["short_sell"], m["short_balance"], m["short_change"], m.get("updated_at", now_str)
                    )
                    for m in margins
                ]
                cursor.executemany("""
                    INSERT OR REPLACE INTO margin_trading (
                        date, stock_id, margin_buy, margin_sell, margin_balance,
                        margin_change, short_buy, short_sell, short_balance, short_change, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, margin_tuples)
                stats["margins"] = len(margin_tuples)

            # 4. 寫入個股 Metadata
            if stock_metas:
                meta_tuples = [
                    (
                        m["stock_id"], m["stock_name"], m["market"],
                        m.get("industry", ""), 1, now_str
                    )
                    for m in stock_metas
                ]
                cursor.executemany("""
                    INSERT OR REPLACE INTO stock_metadata (
                        stock_id, stock_name, market, industry, is_active, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?);
                """, meta_tuples)
                stats["metadata"] = len(meta_tuples)

            cursor.execute("""
                INSERT INTO fetcher_audit_logs (date, fetch_type, status, record_count, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (
                target_date, "DAILY_PIPELINE", "SUCCESS", 
                stats["quotes"] + stats["chips"] + stats["margins"],
                f"Quotes:{stats['quotes']}, Chips:{stats['chips']}, Margins:{stats['margins']}",
                now_str
            ))

        logger.info(f"[DB 批次入庫完畢] 日期: {target_date} -> 行情: {stats['quotes']} 筆, 籌碼: {stats['chips']} 筆, 融資券: {stats['margins']} 筆")
        return stats

# ======================================================================================
# 8. 總控管道調度器 (Data Fetcher Master Pipeline)
# ======================================================================================

class DataFetcherPipeline:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.requester = RobustHttpRequester()
        self.twse = TWSEFetcher(self.requester)
        self.tpex = TPEXFetcher(self.requester)

    def run_daily_pipeline(
        self,
        target_date_input: Optional[Union[str, datetime.date]] = None,
        force_bypass_timegate: bool = False,
        fallback_dataset: Optional[Dict[str, List[Dict]]] = None
    ) -> Dict[str, Any]:
        now_dt = datetime.datetime.now()
        
        if target_date_input and not str(target_date_input).startswith("-"):
            target_date = parse_date_str(target_date_input)
        else:
            target_date = TaiwanTradingCalendar.get_latest_available_trading_day(now_dt)
            
        target_date_str = target_date.strftime("%Y-%m-%d")
        logger.info(f"========== 執行 WayneBot 數據採集 (目標日期: {target_date_str}) ==========")

        # 2. 智慧時間閘門檢驗 (Quotes & Chips 鎖定 16:30)
        quotes_allowed, q_reason = SmartTimeGate.evaluate_gate("quotes", target_date, now_dt)
        if not quotes_allowed and not force_bypass_timegate and not fallback_dataset:
            logger.warning(f"行情採集熔斷: {q_reason}")
            return {"status": "CIRCUIT_BREAKER", "target_date": target_date_str, "reason": q_reason, "stats": {}}

        # 3. 採集上市與上櫃收盤行情
        all_quotes = []
        if quotes_allowed or force_bypass_timegate:
            twse_quotes = self.twse.fetch_daily_quotes(target_date)
            tpex_quotes = self.tpex.fetch_daily_quotes(target_date)
            all_quotes = twse_quotes + tpex_quotes

        if not SanityCheckGuard.validate_quotes(all_quotes, min_count=5):
            if fallback_dataset and "quotes" in fallback_dataset:
                logger.info("[自動降級] 即時行情連線無資料，啟用沙盒示範數據集執行後續流程。")
                all_quotes = fallback_dataset["quotes"]
            else:
                return {"status": "SANITY_CHECK_FAILED", "target_date": target_date_str, "reason": "Quotes count below threshold", "stats": {}}

        quote_map = {q["stock_id"]: q for q in all_quotes}
        meta_list = [{"stock_id": q["stock_id"], "stock_name": q["stock_name"], "market": q["market"]} for q in all_quotes]

        # 4. 採集三大法人籌碼 (Chips)
        chips_allowed, c_reason = SmartTimeGate.evaluate_gate("chips", target_date, now_dt)
        all_chips: List[Dict[str, Any]] = []
        if chips_allowed or force_bypass_timegate:
            twse_chips = self.twse.fetch_institutional_investors(target_date)
            tpex_chips = self.tpex.fetch_institutional_investors(target_date)
            raw_chips = twse_chips + tpex_chips

            if SanityCheckGuard.validate_chips(raw_chips, min_count=2):
                for c in raw_chips:
                    sid = c["stock_id"]
                    q_info = quote_map.get(sid, {})
                    all_chips.append({
                        "ticker": c["ticker"],
                        "date": target_date_str,
                        "stock_id": sid,
                        "close_price": q_info.get("close", 0.0),
                        "foreign_buy_sell": c["foreign_buy_sell"],
                        "trust_buy_sell": c["trust_buy_sell"],
                        "dealer_buy_sell": c["dealer_buy_sell"],
                        "institutional_total": c["institutional_total"],
                        "total_volume": q_info.get("volume", 0),
                        "status": "active",
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "cleaned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        if not all_chips and fallback_dataset and "chips" in fallback_dataset:
            all_chips = fallback_dataset["chips"]

        # 5. 採集信用交易 (Margin Trading)
        margin_allowed, m_reason = SmartTimeGate.evaluate_gate("margin", target_date, now_dt)
        all_margins: List[Dict[str, Any]] = []
        if margin_allowed or force_bypass_timegate:
            twse_margin = self.twse.fetch_margin_trading(target_date)
            tpex_margin = self.tpex.fetch_margin_trading(target_date)
            raw_margin = twse_margin + tpex_margin

            if SanityCheckGuard.validate_margin(raw_margin, min_count=1):
                all_margins = raw_margin
        if not all_margins and fallback_dataset and "margins" in fallback_dataset:
            all_margins = fallback_dataset["margins"]

        # 6. 增量更新 Gzip 歷史資料庫與對照表
        HistoryStorageManager.update_history_stocks_csv(all_quotes, STOCKS_CSV_GZ)
        if all_chips:
            HistoryStorageManager.update_history_chips_csv(all_chips, CHIPS_CSV_GZ)
        HistoryStorageManager.update_stock_map_json(meta_list, STOCK_MAP_JSON)

        # 7. 批次寫入 SQLite 資料庫 (WAL Mode)
        db_stats = DatabaseBatchWriter.batch_write_all(
            target_date=target_date_str,
            quotes=all_quotes,
            chips=all_chips,
            margins=all_margins,
            stock_metas=meta_list,
            db_path=self.db_path
        )

        logger.info("========== WayneBot 數據採集與入庫圓滿完成 ==========")
        return {
            "status": "SUCCESS",
            "target_date": target_date_str,
            "stats": db_stats
        }

# ======================================================================================
# 9. 模組對外快速呼叫入口 (Entrypoint)
# ======================================================================================

def run_data_fetcher(target_date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    pipeline = DataFetcherPipeline(DB_PATH)
    return pipeline.run_daily_pipeline(target_date_input=target_date, force_bypass_timegate=force)

if __name__ == "__main__":
    arg_date = None
    valid_args = [a for a in sys.argv[1:] if not a.startswith("-") and not a.endswith(".json")]
    if valid_args:
        arg_date = valid_args[0]
        
    result = run_data_fetcher(target_date=arg_date, force=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
