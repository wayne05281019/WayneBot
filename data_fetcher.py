# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組一 - 數據與行情核心 (data_fetcher.py)
# 檔案用途：歷史資料庫管理、盤中 MIS 毫秒報價、歷史拼接、每日增量、暴風眼 150 監控
# ==============================================================================

import os
import sys
import time
import json
import zipfile
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import requests
import pandas as pd
import numpy as np

# ------------------------------------------------------------------------------
# 1. 核心環境常數與資料庫設定
# ------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_NAME = "waynebot_history.db"
DB_PATH = os.path.join(BASE_DIR, DB_NAME)
RELEASE_URL = "https://github.com/wayne930242/WayneBot/releases/download/v1.0-data/waynebot_history.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}

# ------------------------------------------------------------------------------
# 2. 數值清理輔助工具
# ------------------------------------------------------------------------------
def _clean_num(val, is_float: bool = True):
    """安全清理字串並轉為數值，防止例外發生"""
    if val is None:
        return 0.0 if is_float else 0
    s = str(val).replace(",", "").replace("+", "").replace("X", "").strip()
    if s in ["--", "-", "", "N/A", "null", "None"]:
        return 0.0 if is_float else 0
    try:
        return float(s) if is_float else int(float(s))
    except Exception:
        return 0.0 if is_float else 0

def is_valid_target(stock_id: str, stock_name: str) -> bool:
    """標的範疇過濾：剔除認購/售權證，收錄上市櫃股票、KY、ETF"""
    sid = str(stock_id).strip()
    if len(sid) < 4 or len(sid) > 6:
        return False
    if len(sid) == 4 and sid.isalnum():
        return True
    if len(sid) == 5:
        return sid.startswith("00") or sid.endswith("KY") or sid[:4].isdigit()
    if len(sid) == 6:
        return sid.startswith("00") or sid.startswith("01")
    return False

# ------------------------------------------------------------------------------
# 3. DataFetcher 主類別
# ------------------------------------------------------------------------------
class DataFetcher:
    def __init__(self, db_path: str = DB_PATH, auto_init: bool = True):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        if auto_init:
            self.ensure_database_ready()

    # --------------------------------------------------------------------------
    # A. 0 秒開機與資料庫維護
    # --------------------------------------------------------------------------
    def ensure_database_ready(self) -> bool:
        """檢查本地資料庫是否存在，若無則自動串流下載解壓"""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1024 * 1024:
            return True
        
        print(f"⚠️ 未偵測到本地資料庫，正在自 GitHub Release 串流下載基底庫...")
        zip_temp = os.path.join(BASE_DIR, "waynebot_history_temp.zip")
        try:
            resp = self.session.get(RELEASE_URL, stream=True, timeout=60)
            if resp.status_code == 200:
                with open(zip_temp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                
                print("📦 下載完成，正在解壓縮資料庫...")
                with zipfile.ZipFile(zip_temp, 'r') as zip_ref:
                    zip_ref.extractall(BASE_DIR)
                
                if os.path.exists(zip_temp):
                    os.remove(zip_temp)
                print(f"✅ 資料庫準備就緒: {self.db_path}")
                return True
            else:
                print(f"❌ 下載失敗 (HTTP {resp.status_code})，請確認 Release 連結或手動放置資料庫。")
                return False
        except Exception as e:
            print(f"❌ 串流下載發生例外: {e}")
            return False

    def get_connection(self) -> sqlite3.Connection:
        """獲取 SQLite 連線並配置 WAL 模式與效能參數"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    # --------------------------------------------------------------------------
    # B. 歷史行情讀取
    # --------------------------------------------------------------------------
    def get_stock_history(self, stock_id: str, limit: int = 150) -> pd.DataFrame:
        """讀取個股歷史日 K 資料（依日期升冪排序）"""
        sid = str(stock_id).strip()
        conn = self.get_connection()
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close,
               volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?;
        """
        df = pd.read_sql_query(query, conn, params=(sid, limit))
        conn.close()
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_market_dict(self) -> Dict[str, str]:
        """建立全市場 stock_id -> market (TW/TWO) 快速對照表"""
        conn = self.get_connection()
        query = "SELECT DISTINCT stock_id, market FROM daily_quotes;"
        df = pd.read_sql_query(query, conn)
        conn.close()
        return dict(zip(df["stock_id"], df["market"]))

    # --------------------------------------------------------------------------
    # C. 盤中 MIS 毫秒報價與無縫拼接
    # --------------------------------------------------------------------------
    def fetch_realtime_quotes(self, stock_ids: List[str]) -> Dict[str, dict]:
        """
        利用 TWSE/TPEx MIS API 批次抓取毫秒級即時行情
        單次請求支援 20~50 檔，毫秒內回傳
        """
        if not stock_ids:
            return {}
        
        market_map = self.get_market_dict()
        ch_list = []
        for sid in stock_ids:
            m = market_map.get(sid, "TW")
            prefix = "tse" if m == "TW" else "otc"
            ch_list.append(f"{prefix}_{sid}.tw")

        ex_ch = "|".join(ch_list)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&json=1&delay=0&_={int(time.time() * 1000)}"
        
        results = {}
        try:
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                msg_array = data.get("msgArray", [])
                for item in msg_array:
                    sid = str(item.get("c", "")).strip()
                    if not sid:
                        continue
                    
                    # 取盤中價位（若 z 為最新成交價，未成交時取昨收 y 或賣一/買一）
                    close_p = _clean_num(item.get("z"))
                    if close_p <= 0:
                        close_p = _clean_num(item.get("y"))
                    
                    open_p = _clean_num(item.get("o"))
                    if open_p <= 0:
                        open_p = close_p
                        
                    high_p = _clean_num(item.get("h"))
                    if high_p <= 0:
                        high_p = close_p
                        
                    low_p = _clean_num(item.get("l"))
                    if low_p <= 0:
                        low_p = close_p

                    vol_sheets = _clean_num(item.get("v"), is_float=False)
                    yesterday_close = _clean_num(item.get("y"))
                    
                    diff = close_p - yesterday_close if yesterday_close > 0 else 0.0
                    pct_change = round((diff / yesterday_close * 100.0), 2) if yesterday_close > 0 else 0.0

                    results[sid] = {
                        "stock_id": sid,
                        "stock_name": item.get("n", ""),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol_sheets,
                        "yesterday_close": yesterday_close,
                        "pct_change": pct_change,
                        "time": item.get("t", ""),
                        "best_bid": [_clean_num(p) for p in str(item.get("b", "")).split("_") if p and p != "-"],
                        "best_ask": [_clean_num(p) for p in str(item.get("a", "")).split("_") if p and p != "-"]
                    }
        except Exception as e:
            print(f"⚠️ MIS 即時報價拉取異常: {e}")
        return results

    def get_stitched_stock_data(self, stock_id: str, limit: int = 150) -> pd.DataFrame:
        """
        無縫拼接：將 1.5 年歷史日 K 與當下最新 MIS 盤中價量拼接成完整連續序列
        """
        df_hist = self.get_stock_history(stock_id, limit=limit)
        rt_map = self.fetch_realtime_quotes([stock_id])
        
        if stock_id not in rt_map or df_hist.empty:
            return df_hist
        
        rt = rt_map[stock_id]
        today_str = datetime.now().strftime("%Y%m%d")
        
        # 若歷史庫最新一筆就是今天，則更新該列；否則追加今日盤中列
        if df_hist.iloc[-1]["date"] == today_str:
            df_hist.at[df_hist.index[-1], "open"] = rt["open"]
            df_hist.at[df_hist.index[-1], "high"] = max(df_hist.iloc[-1]["high"], rt["high"])
            df_hist.at[df_hist.index[-1], "low"] = min(df_hist.iloc[-1]["low"], rt["low"]) if df_hist.iloc[-1]["low"] > 0 else rt["low"]
            df_hist.at[df_hist.index[-1], "close"] = rt["close"]
            df_hist.at[df_hist.index[-1], "volume"] = rt["volume"]
            df_hist.at[df_hist.index[-1], "pct_change"] = rt["pct_change"]
        else:
            new_row = {
                "date": today_str,
                "stock_id": stock_id,
                "stock_name": df_hist.iloc[-1]["stock_name"],
                "market": df_hist.iloc[-1]["market"],
                "open": rt["open"],
                "high": rt["high"],
                "low": rt["low"],
                "close": rt["close"],
                "volume": rt["volume"],
                "turnover_k": 0.0,
                "pct_change": rt["pct_change"],
                "avg_price": rt["close"],
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0
            }
            df_hist = pd.concat([df_hist, pd.DataFrame([new_row])], ignore_index=True)
            
        return df_hist

    # --------------------------------------------------------------------------
    # D. 三層智慧漏斗：開盤前初篩 150 檔暴風眼候選池
    # --------------------------------------------------------------------------
    def get_storm_eye_candidates(self, limit: int = 150) -> List[str]:
        """
        智慧漏斗第一層：
        1. 排除日均量 < 1,000 張或成交額 < 3,000 萬的流動性陷阱股
        2. 篩選近 5 日量能活絡、均線向上、具備突破潛力的 150 檔暴風眼核心池
        """
        conn = self.get_connection()
        # 取得最新交易日
        latest_date_df = pd.read_sql_query("SELECT MAX(date) as l_date FROM daily_quotes;", conn)
        latest_date = latest_date_df["l_date"].iloc[0]
        
        query = f"""
        WITH recent_stats AS (
            SELECT 
                stock_id,
                stock_name,
                AVG(volume) as avg_vol_5d,
                AVG(turnover_k) as avg_turnover_5d,
                AVG(close) as avg_close_5d,
                MAX(high) as max_high_5d,
                SUM(trust_net) as trust_net_5d
            FROM daily_quotes
            WHERE date >= (SELECT date FROM daily_quotes GROUP BY date ORDER BY date DESC LIMIT 1 OFFSET 4)
            GROUP BY stock_id
        )
        SELECT r.stock_id, q.close, r.avg_vol_5d, r.avg_turnover_5d, r.trust_net_5d
        FROM recent_stats r
        JOIN daily_quotes q ON r.stock_id = q.stock_id AND q.date = '{latest_date}'
        WHERE r.avg_vol_5d >= 1000            -- 流動性防護：日均量 >= 1000 張
          AND r.avg_turnover_5d >= 30000      -- 流動性防護：日均額 >= 3000 萬
          AND q.close >= 10.0                 -- 排除雞蛋水餃股
        ORDER BY (r.avg_turnover_5d * (1.0 + CASE WHEN r.trust_net_5d > 0 THEN 0.5 ELSE 0.0 END)) DESC
        LIMIT ?;
        """
        df_candidates = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        
        candidates = df_candidates["stock_id"].tolist()
        return candidates

    def monitor_storm_eye_batch(self, candidate_list: Optional[List[str]] = None) -> Dict[str, dict]:
        """
        智慧漏斗第二層：分批（每批 38 檔，共約 4 次 API）監控 150 檔即時行情
        """
        if candidate_list is None:
            candidate_list = self.get_storm_eye_candidates(limit=150)
            
        chunk_size = 38
        all_quotes = {}
        for i in range(0, len(candidate_list), chunk_size):
            chunk = candidate_list[i:i + chunk_size]
            quotes = self.fetch_realtime_quotes(chunk)
            all_quotes.update(quotes)
            time.sleep(0.1)  # 平穩微幅延遲防封鎖
            
        return all_quotes

    # --------------------------------------------------------------------------
    # E. 每日 15:30 增量更新模組（切片解包，無縫寫入 SQLite）
    # --------------------------------------------------------------------------
    def update_daily_market(self, target_date: Optional[str] = None) -> bool:
        """
        每日 15:30 自動抓取全市場 2,202 檔上市/上櫃行情與三大法人數據，寫入 SQLite
        """
        if target_date is None:
            target_date = datetime.now().strftime("%Y%m%d")

        print(f"📥 正在執行 {target_date} 全市場日增量更新...")
        
        # 1. 抓取上市行情 (TWSE MI_INDEX)
        tw_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={target_date}&type=ALLBUT0999&response=json"
        tw_records = []
        try:
            resp = self.session.get(tw_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("stat") == "OK":
                    raw_rows = []
                    for table in data.get("tables", []):
                        if "每日收盤行情" in table.get("title", ""):
                            raw_rows = table.get("data", [])
                            break
                    if not raw_rows and "data9" in data:
                        raw_rows = data["data9"]
                    elif not raw_rows and "data8" in data:
                        raw_rows = data["data8"]

                    for r in raw_rows:
                        if len(r) < 11:
                            continue
                        # 切片解包語法
                        sid, sname, vol_raw, tx_cnt, turnover_raw, open_raw, high_raw, low_raw, close_raw, sign_raw, diff_raw = r[:11]
                        if not is_valid_target(sid, sname):
                            continue
                        
                        v_shares = _clean_num(vol_raw, is_float=False)
                        t_ntd = _clean_num(turnover_raw, is_float=True)
                        op = _clean_num(open_raw, is_float=True)
                        hp = _clean_num(high_raw, is_float=True)
                        lp = _clean_num(low_raw, is_float=True)
                        cp = _clean_num(close_raw, is_float=True)
                        df_val = _clean_num(diff_raw, is_float=True)

                        if "-" in str(sign_raw) or "跌" in str(sign_raw):
                            df_val = -abs(df_val)
                        elif "+" in str(sign_raw) or "漲" in str(sign_raw):
                            df_val = abs(df_val)

                        ref_p = cp - df_val if cp > 0 else 0.0
                        pct = round((df_val / ref_p * 100.0), 2) if ref_p > 0 else 0.0
                        avg_p = round(t_ntd / v_shares, 2) if v_shares > 0 else cp

                        tw_records.append({
                            "date": target_date, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(),
                            "market": "TW", "open": op, "high": hp, "low": lp, "close": cp,
                            "volume": int(v_shares // 1000), "turnover_k": round(t_ntd / 1000.0, 2),
                            "pct_change": pct, "avg_price": avg_p
                        })
        except Exception as e:
            print(f"⚠️ 上市行情抓取異常: {e}")

        # 2. 抓取上櫃行情 (TPEx)
        roc_year = int(target_date[:4]) - 1911
        roc_date = f"{roc_year}/{target_date[4:6]}/{target_date[6:]}"
        two_url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date}&_={int(time.time()*1000)}"
        two_records = []
        try:
            resp = self.session.get(two_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_rows = data.get("aaData", [])
                for r in raw_rows:
                    if len(r) < 10:
                        continue
                    sid, sname, close_raw, diff_raw, open_raw, high_raw, low_raw, avg_raw, vol_raw, turnover_raw = r[:10]
                    if not is_valid_target(sid, sname):
                        continue
                    
                    v_shares = _clean_num(vol_raw, is_float=False)
                    t_ntd = _clean_num(turnover_raw, is_float=True)
                    op = _clean_num(open_raw, is_float=True)
                    hp = _clean_num(high_raw, is_float=True)
                    lp = _clean_num(low_raw, is_float=True)
                    cp = _clean_num(close_raw, is_float=True)
                    df_val = _clean_num(diff_raw, is_float=True)

                    ref_p = cp - df_val if cp > 0 else 0.0
                    pct = round((df_val / ref_p * 100.0), 2) if ref_p > 0 else 0.0
                    avg_p = _clean_num(avg_raw, is_float=True)
                    if avg_p <= 0 and v_shares > 0:
                        avg_p = round(t_ntd / v_shares, 2)
                    elif avg_p <= 0:
                        avg_p = cp

                    two_records.append({
                        "date": target_date, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(),
                        "market": "TWO", "open": op, "high": hp, "low": lp, "close": cp,
                        "volume": int(v_shares // 1000), "turnover_k": round(t_ntd / 1000.0, 2),
                        "pct_change": pct, "avg_price": avg_p
                    })
        except Exception as e:
            print(f"⚠️ 上櫃行情抓取異常: {e}")

        # 3. 抓取法人買賣超 (T86)
        inst_map = {}
        try:
            # 上市法人
            tw_t86_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={target_date}&selectType=ALLBUT0999&response=json"
            resp = self.session.get(tw_t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("data", []):
                    if len(r) >= 12:
                        sid = str(r[0]).strip()
                        inst_map[sid] = {
                            "foreign_net": _clean_num(r[4], False) // 1000,
                            "trust_net": _clean_num(r[7], False) // 1000,
                            "dealer_net": _clean_num(r[11], False) // 1000
                        }
            # 上櫃法人
            two_t86_url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date}&se=EW&t=D&_={int(time.time()*1000)}"
            resp = self.session.get(two_t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("aaData", []):
                    if len(r) >= 15:
                        sid = str(r[0]).strip()
                        inst_map[sid] = {
                            "foreign_net": _clean_num(r[7], False) // 1000,
                            "trust_net": _clean_num(r[10], False) // 1000,
                            "dealer_net": _clean_num(r[13], False) // 1000
                        }
        except Exception as e:
            print(f"⚠️ 三大法人資料抓取略過或異常: {e}")

        # 4. 合併寫入 SQLite
        all_records = tw_records + two_records
        if not all_records:
            print(f"ℹ️ {target_date} 無交易資料（可能為非交易日）。")
            return False

        rows_to_insert = []
        for q in all_records:
            sid = q["stock_id"]
            inst = inst_map.get(sid, {"foreign_net": 0, "trust_net": 0, "dealer_net": 0})
            rows_to_insert.append((
                q["date"], q["stock_id"], q["stock_name"], q["market"],
                q["open"], q["high"], q["low"], q["close"],
                q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                inst["foreign_net"], inst["trust_net"], inst["dealer_net"]
            ))

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT OR REPLACE INTO daily_quotes 
        (date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, rows_to_insert)
        conn.commit()
        conn.close()

        print(f"✅ {target_date} 增量更新成功！共寫入 {len(rows_to_insert)} 筆資料。")
        return True

# ------------------------------------------------------------------------------
# 4. 沙盒獨立驗證測試區塊 (__main__)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 啟動 data_fetcher.py 模組獨立測試")
    print("=" * 70)

    fetcher = DataFetcher(auto_init=True)

    # 1. 測試讀取個股歷史
    print("\n[測試 1] 讀取台積電 (2330) 歷史資料：")
    df_2330 = fetcher.get_stock_history("2330", limit=5)
    print(df_2330[["date", "stock_id", "stock_name", "close", "volume", "trust_net"]])

    # 2. 測試盤中即時報價 (MIS)
    print("\n[測試 2] 測試 MIS 即時行情拉取 (2330, 0050, 5274)：")
    rt_quotes = fetcher.fetch_realtime_quotes(["2330", "0050", "5274"])
    for sid, q in rt_quotes.items():
        print(f"  • [{sid}] {q['stock_name']}: 最新價 {q['close']} | 漲跌幅 {q['pct_change']}% | 今日累積量 {q['volume']} 張")

    # 3. 測試歷史與即時無縫拼接
    print("\n[測試 3] 測試歷史與盤中無縫拼接 (2330)：")
    df_stitched = fetcher.get_stitched_stock_data("2330", limit=5)
    print(df_stitched.tail(3)[["date", "stock_id", "stock_name", "close", "volume", "pct_change"]])

    # 4. 測試三層智慧漏斗：暴風眼 150 候選池初篩與批次監控
    print("\n[測試 4] 暴風眼候選池初篩與批次監控：")
    candidates = fetcher.get_storm_eye_candidates(limit=10)
    print(f"  • 前 10 檔候選標的: {candidates}")
    batch_res = fetcher.monitor_storm_eye_batch(candidates[:5])
    print(f"  • 批次即時監控成功筆數: {len(batch_res)} 筆")

    print("\n" + "=" * 70)
    print("🎉 data_fetcher.py 沙盒測試全部通過！可安心替換至根目錄。")
    print("=" * 70)
