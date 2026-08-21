import csv
import gc
import gzip
import json
import logging
import math
import os
import re
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Union

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WayneBot.ScreeningEngine")

def clean_number(val: Any, default: float = 0.0) -> float:
    """
    寬容處理千分位逗號、正負號、百分比、空值、--、N/A 等字串，安全轉為 float。
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default
        return float(val)
    val_str = str(val).strip()
    invalid_literals = {"", "--", "-", "N/A", "n/a", "NA", "null", "NULL", "nan", "NaN", "None"}
    if val_str in invalid_literals:
        return default
    cleaned_str = val_str.replace(",", "").replace("+", "").replace("%", "").strip()
    try:
        result = float(cleaned_str)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default

def normalize_ticker(raw_ticker: Any) -> str:
    """
    標準化台股代碼，去除 .TW、.TWO、空白及非代碼字元，返回純代碼字串。
    """
    if raw_ticker is None:
        return ""
    ticker_str = str(raw_ticker).strip().upper()
    for suffix in [".TW", ".TWO", ".TPEX", ".TAIEX"]:
        if ticker_str.endswith(suffix):
            ticker_str = ticker_str[:-len(suffix)]
    return re.sub(r"[^A-Z0-9]", "", ticker_str)

def validate_scraped_data(data_list: List[Any], min_expected_count: int = 800) -> bool:
    """
    爬蟲與抓取數據的健全性檢驗（Sanity Check），防止抓到空資料覆蓋資料庫。
    """
    if not isinstance(data_list, list):
        logger.error(f"[Sanity Check 失敗] 非列表型態: {type(data_list)}")
        return False
    actual_count = len(data_list)
    if actual_count < min_expected_count:
        logger.warning(f"[Sanity Check 攔截] 筆數不足 ({actual_count} < {min_expected_count})，防止覆蓋資料庫。")
        return False
    logger.info(f"[Sanity Check 通過] 數據總量驗證合格: {actual_count} 筆")
    return True

def stream_filter_chips(file_path: str = "history_1y_chips.csv.gz") -> Generator[Dict[str, Any], None, None]:
    """
    使用 Python 生成器（yield）流式逐筆讀取 gzip 壓縮 CSV，實作三道過濾網。
    """
    if not os.path.exists(file_path):
        logger.error(f"檔案不存在: {file_path}")
        return
    required_fields = ["ticker", "date", "close_price", "foreign_buy_sell", "trust_buy_sell", "dealer_buy_sell", "total_volume"]
    processed_count = 0
    yielded_count = 0
    try:
        with gzip.open(file_path, mode="rt", encoding="utf-8-sig", errors="replace") as gz_file:
            reader = csv.DictReader(gz_file)
            if reader.fieldnames is None:
                return
            for raw_row in reader:
                processed_count += 1
                if not raw_row or not all(k in raw_row for k in required_fields):
                    continue
                raw_ticker = raw_row.get("ticker", "")
                raw_date = raw_row.get("date", "").strip()
                ticker = normalize_ticker(raw_ticker)
                if not ticker or not raw_date:
                    continue
                status = str(raw_row.get("status", "")).strip().lower()
                invalid_statuses = {"deprecated", "invalid_test", "test", "ignore", "disabled"}
                if status in invalid_statuses or ticker.startswith("TEST"):
                    continue
                close_price = clean_number(raw_row.get("close_price"), default=0.0)
                foreign_buy_sell = clean_number(raw_row.get("foreign_buy_sell"), default=0.0)
                trust_buy_sell = clean_number(raw_row.get("trust_buy_sell"), default=0.0)
                dealer_buy_sell = clean_number(raw_row.get("dealer_buy_sell"), default=0.0)
                total_volume = clean_number(raw_row.get("total_volume"), default=0.0)
                if close_price <= 0.0 or total_volume < 0.0:
                    continue
                institutional_total = foreign_buy_sell + trust_buy_sell + dealer_buy_sell
                yielded_count += 1
                yield {
                    "ticker": ticker,
                    "date": raw_date,
                    "close_price": close_price,
                    "foreign_buy_sell": foreign_buy_sell,
                    "trust_buy_sell": trust_buy_sell,
                    "dealer_buy_sell": dealer_buy_sell,
                    "institutional_total": institutional_total,
                    "total_volume": total_volume,
                    "status": "active",
                    "cleaned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    finally:
        gc.collect()
        logger.info(f"流式讀取完成: 讀取 {processed_count} 行，產出 {yielded_count} 筆。")

def save_filtered_data_to_cache(verified_item: Dict[str, Any], key_prefix: str = "chips_") -> bool:
    """
    將單筆篩選後的資料寫入 wayne_db 的 cached_data 資料表中。
    """
    if not isinstance(verified_item, dict):
        return False
    ticker = verified_item.get("ticker", "")
    date_str = verified_item.get("date", "")
    if not ticker or not date_str:
        return False

    try:
        import wayne_db
        get_db_conn = getattr(wayne_db, "get_db_connection", None)
    except ImportError:
        get_db_conn = None

    if get_db_conn is None:
        logger.error("無法取得 wayne_db.get_db_connection")
        return False

    cache_key = f"{key_prefix}{ticker}_{date_str}"
    payload_json = json.dumps(verified_item, ensure_ascii=False)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _execute_save(conn):
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cached_data (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            INSERT OR REPLACE INTO cached_data (cache_key, payload, updated_at)
            VALUES (?, ?, ?)
        """, (cache_key, payload_json, updated_at))
        if hasattr(conn, "commit"):
            conn.commit()

    try:
        db_resource = get_db_conn()
        if hasattr(db_resource, "__enter__") and hasattr(db_resource, "__exit__"):
            with db_resource as conn:
                _execute_save(conn)
        else:
            try:
                _execute_save(db_resource)
            finally:
                if hasattr(db_resource, "close"):
                    db_resource.close()
        return True
    except Exception as e:
        logger.exception(f"寫入快取至資料庫時發生異常 (cache_key={cache_key}): {e}")
        return False
