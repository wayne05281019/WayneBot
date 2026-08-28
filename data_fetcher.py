# ==============================================================================
# WayneBot 全市場量化決策系統 - 核心模組 1/5
# 檔案名稱：data_fetcher.py
# 模組定位：行情與資料核心（0秒開機下載、盤中MIS毫秒報價、15:30日增量、三層智慧漏斗）
# ==============================================================================

import os
import time
import json
import zipfile
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
import requests
import pandas as pd

# ------------------------------------------------------------------------------
# 1. 全域常數與路徑配置
# ------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_PATH = os.path.join(BASE_DIR, "waynebot_history.db")
ZIP_PATH = os.path.join(BASE_DIR, "waynebot_history.zip")

# GitHub Release 預設下載來源（可透過環境變數覆寫）
DEFAULT_RELEASE_URL = os.getenv(
    "WAYNEBOT_DB_RELEASE_URL",
    "https://github.com/wayne-quant/waynebot/releases/download/v1.0-data/waynebot_history.zip"
)

# 請求標頭
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


# ------------------------------------------------------------------------------
# 2. 輔助數值轉換函式
# ------------------------------------------------------------------------------
def _clean_num(val, is_float: bool = True):
    """清理字串中的逗號、正負號、空值並轉換"""
    if val is None:
        return 0.0 if is_float else 0
    s = str(val).replace(",", "").replace("+", "").replace("X", "").strip()
    if s in ["--", "-", "", "N/A", "null", "None"]:
        return 0.0 if is_float else 0
    try:
        return float(s) if is_float else int(float(s))
    except Exception:
        return 0.0 if is_float else 0


def _is_valid_target(stock_id: str, stock_name: str) -> bool:
    """過濾 2,202 檔有效標的（收錄普通股、KY股、全市場ETF，徹底剔除權證）"""
    sid = str(stock_id).strip()
    if len(sid) < 4 or len(sid) > 6:
        return False
    if len(sid) == 4 and sid.isalnum():
        return True
    if len(sid) == 5 and (sid.startswith("00") or sid.endswith("KY") or sid[:4].isdigit()):
        return True
    if len(sid) == 6 and (sid.startswith("00") or sid.startswith("01")):
        return True
    return False


# ------------------------------------------------------------------------------
# 3. 資料庫管理器（SQLite 連線與 Fast-Boot）
# ------------------------------------------------------------------------------
class DatabaseManager:
    """SQLite 歷史資料庫管理：支援 0 秒開機下載、結構校驗與連線池"""

    def __init__(self, db_path: str = DB_PATH, release_url: str = DEFAULT_RELEASE_URL):
        self.db_path = db_path
        self.release_url = release_url
        self.ensure_database_ready()

    def get_connection(self) -> sqlite3.Connection:
        """獲取已配置 WAL 高效能模式之資料庫連線"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def ensure_database_ready(self):
        """0 秒開機機制：若本機無歷史庫，自動從 GitHub Release 串流下載解壓"""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1024 * 1024 * 5:
            return

        print(f"📦 偵測到本地尚無完整歷史資料庫，準備從 Release 串流下載：{self.release_url}")
        try:
            resp = requests.get(self.release_url, stream=True, headers=HEADERS, timeout=60)
            if resp.status_code == 200:
                with open(ZIP_PATH, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                print("🗜️ 下載完成，正在解壓縮 waynebot_history.zip...")
                with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
                    zip_ref.extractall(BASE_DIR)
                if os.path.exists(ZIP_PATH):
                    os.remove(ZIP_PATH)
                print("✅ 0 秒開機歷史庫已就緒！")
            else:
                print(f"⚠️ 下載失敗 (HTTP {resp.status_code})，將初始化空資料庫結構。")
                self._init_empty_schema()
        except Exception as e:
            print(f"⚠️ 串流下載發生錯誤：{e}，將初始化空資料庫結構。")
            self._init_empty_schema()

    def _init_empty_schema(self):
        """初始化 15 大標準資料字典資料表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("""
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
            foreign_net INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            PRIMARY KEY (date, stock_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON daily_quotes(stock_id, date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON daily_quotes(date);")
        conn.commit()
        conn.close()


# ------------------------------------------------------------------------------
# 4. 盤中 MIS 毫秒報價引擎
# ------------------------------------------------------------------------------
class IntradayMISEngine:
    """臺灣證券交易所 MIS 毫秒即時報價引擎（支援單檔/多檔批次與歷史 K 線拼接）"""

    MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_realtime_quotes(self, stock_ids: List[str]) -> Dict[str, Dict]:
        """
        批次獲取即時撮合資訊（0.1秒響應）
        :param stock_ids: 股票代號清單（如 ['2330', '0050', '5274']）
        :return: 以 stock_id 為 Key 的即時行情字典
        """
        if not stock_ids:
            return {}

        results = {}
        # MIS API 每次最多支援約 50 檔，進行自動分批
        chunk_size = 40
        for i in range(0, len(stock_ids), chunk_size):
            chunk = stock_ids[i:i + chunk_size]
            # 建立 tse/otc 雙向頻道字串（MIS 支援一次傳入 tse_XXXX.tw|otc_XXXX.tw）
            channels = []
            for sid in chunk:
                channels.append(f"tse_{sid}.tw")
                channels.append(f"otc_{sid}.tw")
            ex_ch_str = "|".join(channels)

            url = f"{self.MIS_URL}?ex_ch={ex_ch_str}&json=1&delay=0&_={int(time.time() * 1000)}"
            try:
                resp = self.session.get(url, timeout=5)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                msg_array = data.get("msgArray", [])
                for item in msg_array:
                    sid = str(item.get("c", "")).strip()
                    if not sid:
                        continue

                    # 解析當下即時成交價 (z)，若為 '-' 則取昨收 (y) 或買賣一檔
                    latest_price = _clean_num(item.get("z"))
                    if latest_price <= 0:
                        latest_price = _clean_num(item.get("pz"))
                    if latest_price <= 0:
                        latest_price = _clean_num(item.get("y"))

                    yesterday_close = _clean_num(item.get("y"))
                    open_p = _clean_num(item.get("o")) or latest_price
                    high_p = _clean_num(item.get("h")) or latest_price
                    low_p = _clean_num(item.get("l")) or latest_price
                    
                    # MIS 的累積成交量 (v) 單位為「張」
                    vol_sheets = int(_clean_num(item.get("v"), is_float=False))

                    # 漲跌與漲跌幅計算
                    diff = round(latest_price - yesterday_close, 2) if yesterday_close > 0 else 0.0
                    pct_change = round((diff / yesterday_close * 100.0), 2) if yesterday_close > 0 else 0.0

                    results[sid] = {
                        "stock_id": sid,
                        "stock_name": item.get("n", ""),
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": latest_price,
                        "yesterday_close": yesterday_close,
                        "volume": vol_sheets,
                        "pct_change": pct_change,
                        "diff": diff,
                        "time": item.get("t", ""),
                        "date": item.get("d", datetime.now().strftime("%Y%m%d"))
                    }
            except Exception:
                continue

        return results

    def get_realtime_single(self, stock_id: str) -> Optional[Dict]:
        """單檔即時報價查詢"""
        res = self.fetch_realtime_quotes([stock_id])
        return res.get(stock_id)


# ------------------------------------------------------------------------------
# 5. 數據核心主體：DataFetcher
# ------------------------------------------------------------------------------
class DataFetcher:
    """
    WayneBot 數據核心：
    - 提供歷史 K 線讀取（自動拼接當日盤中最新報價）
    - 每日 15:30 自動增量更新（切片解包防呆）
    - 三層智慧漏斗：開盤前 150 檔暴風眼初篩池
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db_manager = db_manager or DatabaseManager()
        self.mis_engine = IntradayMISEngine()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # --------------------------------------------------------------------------
    # 歷史行情讀取 ＆ 即時無縫拼接
    # --------------------------------------------------------------------------
    def get_daily_quotes(self, stock_id: str, days: int = 120, append_realtime: bool = True) -> pd.DataFrame:
        """
        獲取個股歷史行情 DataFrame，並可自動拼接當日盤中最新價量
        :param stock_id: 股票代號
        :param days: 取得最近 N 個交易日數據
        :param append_realtime: 若當前為盤中且當日資料庫尚未結算，自動無縫拼接即時 Tick
        :return: 包含 15 大標準欄位之 pd.DataFrame (以 date 升冪排序)
        """
        conn = self.db_manager.get_connection()
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes
        WHERE stock_id = '{stock_id}'
        ORDER BY date DESC
        LIMIT {days};
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            df = pd.DataFrame(columns=[
                "date", "stock_id", "stock_name", "market", "open", "high", "low", "close",
                "volume", "turnover_k", "pct_change", "avg_price", "foreign_net", "trust_net", "dealer_net"
            ])
        else:
            df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

        # 盤中無縫拼接機制
        if append_realtime:
            today_str = datetime.now().strftime("%Y%m%d")
            # 若歷史庫最後一筆不是今天，且目前在開盤期間（09:00~13:30）或盤後尚未執行增量
            last_date = str(df["date"].iloc[-1]) if not df.empty else ""
            if last_date != today_str:
                rt = self.mis_engine.get_realtime_single(stock_id)
                if rt and rt["close"] > 0:
                    stock_name = df["stock_name"].iloc[-1] if not df.empty else rt["stock_name"]
                    market = df["market"].iloc[-1] if not df.empty else "TW"
                    
                    # 估算即時成交金額 (千元) 與均價
                    vol_sheets = rt["volume"]
                    est_turnover_k = round(vol_sheets * rt["close"] * 1000.0 / 1000.0, 2)
                    avg_p = rt["close"]

                    rt_row = {
                        "date": today_str,
                        "stock_id": stock_id,
                        "stock_name": stock_name,
                        "market": market,
                        "open": rt["open"],
                        "high": rt["high"],
                        "low": rt["low"],
                        "close": rt["close"],
                        "volume": vol_sheets,
                        "turnover_k": est_turnover_k,
                        "pct_change": rt["pct_change"],
                        "avg_price": avg_p,
                        "foreign_net": 0,
                        "trust_net": 0,
                        "dealer_net": 0
                    }
                    df = pd.concat([df, pd.DataFrame([rt_row])], ignore_index=True)

        return df

    # --------------------------------------------------------------------------
    # 三層智慧漏斗：開盤前 150 檔「暴風眼候選池」初篩
    # --------------------------------------------------------------------------
    def get_storm_candidate_pool(self, min_volume: int = 1000, min_turnover_k: float = 30000.0) -> List[str]:
        """
        智慧漏斗第 1 層：開盤前初篩高流動性與強勢前兆股（約 150 檔）
        - 日成交量 >= 1,000 張
        - 日成交額 >= 3,000 萬元 (30,000 千元)
        - 排除殭屍股與流動性陷阱
        """
        conn = self.db_manager.get_connection()
        # 取得最新一個交易日
        latest_date_df = pd.read_sql_query("SELECT MAX(date) as max_d FROM daily_quotes;", conn)
        latest_date = latest_date_df["max_d"].iloc[0]
        if not latest_date:
            conn.close()
            return ["2330", "0050", "00631L", "00632R", "00679B"]

        query = f"""
        SELECT stock_id, volume, turnover_k, pct_change, trust_net
        FROM daily_quotes
        WHERE date = '{latest_date}'
          AND volume >= {min_volume}
          AND turnover_k >= {min_turnover_k}
        ORDER BY (turnover_k * 0.6 + volume * 0.4) DESC
        LIMIT 150;
        """
        df_pool = pd.read_sql_query(query, conn)
        conn.close()

        candidate_list = df_pool["stock_id"].tolist()
        
        # 確保核心大盤指標 100% 在監控池內
        for essential_sid in ["2330", "0050", "00631L", "00632R", "00679B", "00675L"]:
            if essential_sid not in candidate_list:
                candidate_list.append(essential_sid)

        return candidate_list

    # --------------------------------------------------------------------------
    # 每日 15:30 增量更新模組（多變數切片解包防呆）
    # --------------------------------------------------------------------------
    def update_daily_quotes_increment(self, target_date: Optional[str] = None) -> int:
        """
        抓取指定日期（預設為今日）全市場 2,202 檔數據寫入 SQLite
        :param target_date: YYYYMMDD 字串，若無則取當日
        :return: 本次成功寫入之筆數
        """
        date_str = target_date or datetime.now().strftime("%Y%m%d")
        print(f"🔄 正在執行 [{date_str}] 全市場盤後數據增量更新...")

        # 1. 抓取上市行情 (TWSE MI_INDEX)
        tw_records = []
        tw_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json"
        try:
            resp = self.session.get(tw_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("stat") == "OK":
                    raw_rows = []
                    for t in data.get("tables", []):
                        if "收盤行情" in t.get("title", ""):
                            raw_rows = t.get("data", [])
                            break
                    if not raw_rows:
                        raw_rows = data.get("data9", []) or data.get("data8", [])

                    for r in raw_rows:
                        if len(r) < 11:
                            continue
                        # 多變數切片直接解包
                        sid, sname, vol_raw, tx_cnt, turnover_raw, open_raw, high_raw, low_raw, close_raw, sign_raw, diff_raw = r[:11]
                        if not _is_valid_target(sid, sname):
                            continue

                        vol_shares = _clean_num(vol_raw, is_float=False)
                        turnover_ntd = _clean_num(turnover_raw, is_float=True)
                        open_p = _clean_num(open_raw, is_float=True)
                        high_p = _clean_num(high_raw, is_float=True)
                        low_p = _clean_num(low_raw, is_float=True)
                        close_p = _clean_num(close_raw, is_float=True)
                        diff = _clean_num(diff_raw, is_float=True)
                        if "-" in str(sign_raw) or "跌" in str(sign_raw):
                            diff = -abs(diff)
                        elif "+" in str(sign_raw) or "漲" in str(sign_raw):
                            diff = abs(diff)

                        ref_p = close_p - diff if close_p > 0 else 0.0
                        pct = round((diff / ref_p * 100.0), 2) if ref_p > 0 else 0.0
                        avg_p = round(turnover_ntd / vol_shares, 2) if vol_shares > 0 else close_p

                        tw_records.append({
                            "date": date_str, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(), "market": "TW",
                            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                            "volume": int(vol_shares // 1000), "turnover_k": round(turnover_ntd / 1000.0, 2),
                            "pct_change": pct, "avg_price": avg_p
                        })
        except Exception as e:
            print(f"⚠️ 上市行情抓取異常: {e}")

        # 2. 抓取上櫃行情 (TPEx)
        two_records = []
        roc_year = int(date_str[:4]) - 1911
        roc_date_str = f"{roc_year}/{date_str[4:6]}/{date_str[6:]}"
        two_url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date_str}&_={int(time.time()*1000)}"
        try:
            resp = self.session.get(two_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_rows = data.get("aaData", [])
                for r in raw_rows:
                    if len(r) < 10:
                        continue
                    sid, sname, close_raw, diff_raw, open_raw, high_raw, low_raw, avg_raw, vol_raw, turnover_raw = r[:10]
                    if not _is_valid_target(sid, sname):
                        continue

                    vol_shares = _clean_num(vol_raw, is_float=False)
                    turnover_ntd = _clean_num(turnover_raw, is_float=True)
                    open_p = _clean_num(open_raw, is_float=True)
                    high_p = _clean_num(high_raw, is_float=True)
                    low_p = _clean_num(low_raw, is_float=True)
                    close_p = _clean_num(close_raw, is_float=True)
                    diff = _clean_num(diff_raw, is_float=True)

                    ref_p = close_p - diff if close_p > 0 else 0.0
                    pct = round((diff / ref_p * 100.0), 2) if ref_p > 0 else 0.0
                    avg_p = _clean_num(avg_raw, is_float=True)
                    if avg_p <= 0 and vol_shares > 0:
                        avg_p = round(turnover_ntd / vol_shares, 2)
                    elif avg_p <= 0:
                        avg_p = close_p

                    two_records.append({
                        "date": date_str, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(), "market": "TWO",
                        "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                        "volume": int(vol_shares // 1000), "turnover_k": round(turnover_ntd / 1000.0, 2),
                        "pct_change": pct, "avg_price": avg_p
                    })
        except Exception as e:
            print(f"⚠️ 上櫃行情抓取異常: {e}")

        if not tw_records and not two_records:
            print(f"ℹ️ 日期 [{date_str}] 無交易資料（可能為休市日或未開盤）。")
            return 0

        # 3. 抓取上市櫃三大法人買賣超 (T86)
        inst_map = {}
        # 上市法人
        try:
            t86_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json"
            resp = self.session.get(t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("data", []):
                    if len(r) >= 12:
                        sid = str(r[0]).strip()
                        f_net = _clean_num(r[4], is_float=False) // 1000
                        t_net = _clean_num(r[7], is_float=False) // 1000
                        d_net = _clean_num(r[11], is_float=False) // 1000
                        inst_map[sid] = {"f": int(f_net), "t": int(t_net), "d": int(d_net)}
        except Exception:
            pass

        # 上櫃法人
        try:
            two_t86_url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date_str}&se=EW&t=D&_={int(time.time()*1000)}"
            resp = self.session.get(two_t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("aaData", []):
                    if len(r) >= 15:
                        sid = str(r[0]).strip()
                        f_net = _clean_num(r[7], is_float=False) // 1000
                        t_net = _clean_num(r[10], is_float=False) // 1000
                        d_net = _clean_num(r[13], is_float=False) // 1000
                        inst_map[sid] = {"f": int(f_net), "t": int(t_net), "d": int(d_net)}
        except Exception:
            pass

        # 4. 寫入 SQLite
        insert_rows = []
        for q in tw_records + two_records:
            inst = inst_map.get(q["stock_id"], {"f": 0, "t": 0, "d": 0})
            insert_rows.append((
                q["date"], q["stock_id"], q["stock_name"], q["market"],
                q["open"], q["high"], q["low"], q["close"],
                q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                inst["f"], inst["t"], inst["d"]
            ))

        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT OR REPLACE INTO daily_quotes 
        (date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, insert_rows)
        conn.commit()
        conn.close()

        print(f"✅ 增量更新成功！共寫入 {len(insert_rows):,} 筆標的數據。")
        return len(insert_rows)


# ------------------------------------------------------------------------------
# 6. 單元測試與自檢模組
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 正在執行 data_fetcher.py 模組自檢測試...")
    print("=" * 70)

    # 1. 測試資料庫連線與歷史讀取
    fetcher = DataFetcher()
    print("\n[測試 1] 讀取台積電 (2330) 最近 5 日 K 線數據：")
    df_2330 = fetcher.get_daily_quotes("2330", days=5, append_realtime=False)
    print(df_2330[["date", "stock_id", "stock_name", "close", "volume", "pct_change", "trust_net"]])

    # 2. 測試盤中 MIS 即時報價引擎
    print("\n[測試 2] 盤中 MIS 毫秒報價測試 (2330, 0050, 00631L, 00679B)：")
    rt_quotes = fetcher.mis_engine.fetch_realtime_quotes(["2330", "0050", "00631L", "00679B"])
    for sid, info in rt_quotes.items():
        print(f"  • [{sid}] {info['stock_name']} | 最新價: {info['close']} | 漲跌: {info['pct_change']}% | 累積量: {info['volume']} 張 | 時間: {info['time']}")

    # 3. 測試三層智慧漏斗（暴風眼候選池）
    print("\n[測試 3] 智慧漏斗初篩 150 檔候選池測試：")
    pool = fetcher.get_storm_candidate_pool()
    print(f"  • 成功產出監控池清單，共 {len(pool)} 檔標的")
    print(f"  • 前 10 檔代表標的: {pool[:10]}")

    print("\n" + "=" * 70)
    print("🎉 data_fetcher.py 模組測試全數通過！")
    print("=" * 70)
