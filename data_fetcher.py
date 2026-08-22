"""
data_fetcher.py
WayneBot 旗艦量化交易系統 - 智慧交易日回溯與台灣證交所真實盤後籌碼引擎
"""

import os
import sys
import time
import json
import sqlite3
import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple

import requests
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WayneBot.DataFetcher")

DATABASE_PATH = os.getenv("WAYNE_DB_PATH", "wayne_stock.db")

# ==============================================================================
# 1. 智慧交易日判定中樞 (Trading Date Resolver)
# ==============================================================================
class TradingDateResolver:
    """自動過濾假日、週末與開盤日 16:30 結算閥值，精準定位有效交易日"""
    
    @staticmethod
    def get_latest_effective_date(target_time: Optional[datetime.datetime] = None) -> str:
        """
        計算目前查詢當下，證交所已完成結算發布的「最近真實交易日」
        格式：YYYYMMDD
        """
        now = target_time or datetime.datetime.now()
        
        # 1. 若為週一至週五，但在 16:30 之前查詢，代表當日盤後籌碼未結算完成 ➔ 從昨天開始回溯
        if now.weekday() < 5:  # 0~4 為週一至週五
            if now.time() < datetime.time(16, 30):
                cursor_date = now.date() - datetime.timedelta(days=1)
            else:
                cursor_date = now.date()
        else:
            # 2. 若為週末（週六/週日） ➔ 從最近的週五開始回溯
            days_back = now.weekday() - 4  # 週六減 1 天，週日減 2 天
            cursor_date = now.date() - datetime.timedelta(days=days_back)

        # 3. 遞迴向前探測最多 10 天（過濾連續國定假日如春節、清明、颱風假等）
        for _ in range(10):
            # 略過週末
            if cursor_date.weekday() >= 5:
                cursor_date -= datetime.timedelta(days=1)
                continue
                
            date_str = cursor_date.strftime("%Y%m%d")
            
            # 向證交所快速探測該日是否有交易資料
            if TradingDateResolver.verify_twse_trading_day(date_str):
                logger.info(f"🎯 成功定位最近有效開盤結算日: {date_str}")
                return date_str
                
            # 若該日為國定假日休市（證交所回傳無資料），繼續往前推一天
            logger.info(f"⚠️ {date_str} 非台股開盤日或休市，向前回溯前一交易日...")
            cursor_date -= datetime.timedelta(days=1)

        # 保底回傳 cursor_date
        return cursor_date.strftime("%Y%m%d")

    @staticmethod
    def verify_twse_trading_day(date_str: str) -> bool:
        """輕量探測證交所該日期是否有開盤交易紀錄"""
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=MS&response=json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                # 若證交所回傳 stat == 'OK' 且有資料，代表該日為真實開盤日
                if data.get("stat") == "OK":
                    return True
        except Exception as e:
            logger.warning(f"探測交易日 {date_str} 異常: {e}")
        return False

# ==============================================================================
# 2. 證交所與三大法人真實數據抓取引擎
# ==============================================================================
class TWSEDataFetcher:
    """真實抓取台灣證券交易所收盤價與三大法人買賣超"""

    @staticmethod
    def fetch_closing_prices(date_str: str) -> Dict[str, Dict[str, Any]]:
        """
        抓取當日所有上市股票收盤行情 (MI_INDEX)
        包含：證券代號、名稱、收盤價、漲跌幅、成交量
        """
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        stock_map = {}
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("stat") == "OK":
                    # 尋找包含「每日收盤行情」的表格欄位（通常是 tables[8] 或 tables[9]）
                    for table in res_json.get("tables", []):
                        fields = table.get("fields", [])
                        if "證券代號" in fields and "收盤價" in fields:
                            col_idx_sym = fields.index("證券代號")
                            col_idx_name = fields.index("證券名稱")
                            col_idx_close = fields.index("收盤價")
                            col_idx_sign = fields.index("漲跌(+/-)")
                            col_idx_diff = fields.index("漲跌價差")
                            col_idx_vol = fields.index("成交股數")

                            for row in table.get("data", []):
                                sym = row[col_idx_sym].strip()
                                name = row[col_idx_name].strip()
                                close_str = row[col_idx_close].replace(",", "").strip()
                                diff_str = row[col_idx_diff].replace(",", "").strip()
                                sign_str = row[col_idx_sign].replace("<p>", "").replace("</p>", "").replace("+", "").replace("-", "-").strip()
                                vol_str = row[col_idx_vol].replace(",", "").strip()

                                try:
                                    close_price = float(close_str)
                                    diff = float(diff_str) if diff_str != "--" else 0.0
                                    if "-" in str(row[col_idx_sign]):
                                        diff = -diff
                                    
                                    prev_close = close_price - diff
                                    pct = (diff / prev_close * 100) if prev_close > 0 else 0.0
                                    vol_shares = int(vol_str) if vol_str.isdigit() else 0

                                    stock_map[sym] = {
                                        "symbol": sym,
                                        "name": name,
                                        "date": date_str,
                                        "close_price": close_price,
                                        "change_amount": diff,
                                        "change_pct": round(pct, 2),
                                        "volume_shares": vol_shares,
                                        "volume_lots": vol_shares // 1000
                                    }
                                except ValueError:
                                    continue
                    logger.info(f"✅ 成功自證交所載入 {len(stock_map)} 檔個股真實收盤報價 ({date_str})")
        except Exception as e:
            logger.error(f"抓取證交所收盤行情失敗 ({date_str}): {e}")

        return stock_map

    @staticmethod
    def fetch_institutional_investors(date_str: str) -> Dict[str, Dict[str, int]]:
        """
        抓取當日三大法人買賣超日報 (T86)
        包含：外資買賣超、投信買賣超、自營商買賣超（單位：張）
        """
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        chip_map = {}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("stat") == "OK":
                    fields = res_json.get("fields", [])
                    data_rows = res_json.get("data", [])
                    
                    # 辨識外資與投信買賣超欄位索引
                    col_sym = fields.index("證券代號") if "證券代號" in fields else 0
                    col_foreign = -1
                    col_trust = -1

                    for idx, f in enumerate(fields):
                        if "外陸資買賣超股數" in f or "外資買賣超股數" in f:
                            col_foreign = idx
                        elif "投信買賣超股數" in f:
                            col_trust = idx

                    for row in data_rows:
                        sym = row[col_sym].strip()
                        foreign_shares = int(row[col_foreign].replace(",", "")) if col_foreign != -1 else 0
                        trust_shares = int(row[col_trust].replace(",", "")) if col_trust != -1 else 0
                        
                        chip_map[sym] = {
                            "foreign_buy_lots": foreign_shares // 1000,
                            "trust_buy_lots": trust_shares // 1000
                        }
                    logger.info(f"✅ 成功自證交所載入 {len(chip_map)} 檔個股真實法人籌碼 ({date_str})")
        except Exception as e:
            logger.error(f"抓取三大法人買賣超失敗 ({date_str}): {e}")

        return chip_map

# ==============================================================================
# 3. 本地資料庫持久化與同步
# ==============================================================================
def sync_market_data_to_db() -> str:
    """
    執行端到端真實資料同步：
    1. 計算最近真實交易日（自動跳過週末、休市與未結算時段）
    2. 下載當日真實收盤行情與三大法人籌碼
    3. 寫入 SQLite 資料庫持久保存
    """
    trade_date = TradingDateResolver.get_latest_effective_date()
    quotes = TWSEDataFetcher.fetch_closing_prices(trade_date)
    chips = TWSEDataFetcher.fetch_institutional_investors(trade_date)

    if not quotes:
        logger.warning(f"未能取得 {trade_date} 之行情數據，取消資料庫寫入。")
        return trade_date

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stock_data (
            symbol TEXT,
            name TEXT,
            date TEXT,
            close_price REAL,
            change_pct REAL,
            volume_lots INTEGER,
            foreign_buy INTEGER,
            trust_buy INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, date)
        )
    """)

    for sym, q in quotes.items():
        chip = chips.get(sym, {"foreign_buy_lots": 0, "trust_buy_lots": 0})
        cursor.execute("""
            INSERT OR REPLACE INTO daily_stock_data 
            (symbol, name, date, close_price, change_pct, volume_lots, foreign_buy, trust_buy, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            sym, q["name"], trade_date, q["close_price"], q["change_pct"],
            q["volume_lots"], chip["foreign_buy_lots"], chip["trust_buy_lots"]
        ))

    conn.commit()
    conn.close()
    logger.info(f"🎉 {trade_date} 台股真實全市場盤後數據已同步至本地資料庫！")
    return trade_date

if __name__ == "__main__":
    latest_date = sync_market_data_to_db()
    print(f"最近有效交易日：{latest_date} 資料同步完成。")
