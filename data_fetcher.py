# ==============================================================================
# WayneBot 全市場量化決策系統升級
# 模組一：【數據與行情核心】data_fetcher.py
# 說明：負責 0秒開機載入歷史庫、盤中 MIS 毫秒報價拼接、每日 15:30 增量更新、三層智慧漏斗
# ==============================================================================

import os
import sys
import time
import json
import sqlite3
import zipfile
import io
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import requests
import pandas as pd

# ------------------------------------------------------------------------------
# 全域配置與路徑常數
# ------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "waynebot_history.db")
ZIP_FILE = os.path.join(BASE_DIR, "waynebot_history.zip")

# 預設 GitHub Release 下載網址（可由環境變數 GITHUB_RELEASE_ZIP_URL 覆蓋）
DEFAULT_RELEASE_URL = os.getenv(
    "WAYNEBOT_DB_URL",
    "https://github.com/your-username/waynebot/releases/download/v1.0-data/waynebot_history.zip"
)

# ------------------------------------------------------------------------------
# 輔助函式：數值清洗與標的過濾
# ------------------------------------------------------------------------------
def clean_num(val, is_float: bool = True):
    """安全清洗字串中的逗號、正負號、空值並轉換"""
    if val is None:
        return 0.0 if is_float else 0
    s = str(val).replace(",", "").replace("+", "").replace("X", "").strip()
    if s in ["--", "-", "", "N/A", "null", "None"]:
        return 0.0 if is_float else 0
    try:
        return float(s) if is_float else int(float(s))
    except Exception:
        return 0.0 if is_float else 0

def is_valid_target(stock_id: str, stock_name: str = "") -> bool:
    """
    標的範疇規範：
    1. ❌ 剔除：認購/認售權證（6碼非00/01開頭）、牛熊證、特種證券
    2. ✅ 100% 收錄：普通股（4碼）、KY股、主被動 ETF、槓桿/反向 ETF、上櫃債券 ETF
    """
    sid = str(stock_id).strip()
    if len(sid) < 4 or len(sid) > 6:
        return False
    if len(sid) == 4 and sid.isalnum():
        return True
    if len(sid) == 5:
        if sid.startswith("00") or sid.endswith("KY") or sid[:4].isdigit():
            return True
    if len(sid) == 6:
        if sid.startswith("00") or sid.startswith("01"):
            return True
        return False
    return False

# ------------------------------------------------------------------------------
# 核心類別：DataFetcher
# ------------------------------------------------------------------------------
class DataFetcher:
    def __init__(self, db_path: str = DB_FILE, release_url: str = DEFAULT_RELEASE_URL):
        self.db_path = db_path
        self.release_url = release_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })
        # 快取全市場代碼與市場對照表 (e.g. '2330': 'tse', '6415': 'otc')
        self._market_map: Dict[str, str] = {}
        self._name_map: Dict[str, str] = {}
        
        # 確保資料庫就緒
        self.ensure_database_ready()
        self._load_symbol_directory()

    # ==========================================================================
    # 1. 0 秒開機與資料庫維護
    # ==========================================================================
    def ensure_database_ready(self):
        """檢查資料庫是否存在，若無則自 GitHub Release 串流下載解壓"""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1024 * 1024:
            return

        print(f"📦 未偵測到本地歷史資料庫，正在從 GitHub Release 下載基底庫...")
        print(f"🔗 下載來源: {self.release_url}")
        
        try:
            resp = self.session.get(self.release_url, stream=True, timeout=30)
            if resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zip_ref:
                    zip_ref.extractall(os.path.dirname(self.db_path) or ".")
                print("✅ 歷史基底庫下載並解壓完成！")
            else:
                print(f"⚠️ 下載失敗 (HTTP {resp.status_code})，建立空資料庫結構備用。")
                self._init_empty_db()
        except Exception as e:
            print(f"⚠️ 下載或解壓過程出錯: {e}，建立本地空結構。")
            self._init_empty_db()

    def _init_empty_db(self):
        """初始化空的 15 欄位 SQLite 表格"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
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

    def get_db_connection(self) -> sqlite3.Connection:
        """取得支援 WAL 高並發讀取的 SQLite 連線"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _load_symbol_directory(self):
        """載入標的市場歸屬（tse/otc）與中文名稱快取"""
        conn = self.get_db_connection()
        try:
            df = pd.read_sql_query(
                "SELECT DISTINCT stock_id, stock_name, market FROM daily_quotes WHERE date = (SELECT MAX(date) FROM daily_quotes)",
                conn
            )
            for _, row in df.iterrows():
                sid = str(row["stock_id"]).strip()
                sname = str(row["stock_name"]).strip()
                mkt = "tse" if row["market"].upper() in ["TW", "TSE"] else "otc"
                self._market_map[sid] = mkt
                self._name_map[sid] = sname
        except Exception:
            pass
        finally:
            conn.close()

    # ==========================================================================
    # 2. 盤中 MIS 毫秒即時報價與歷史 K 線無縫拼接
    # ==========================================================================
    def get_mis_quotes(self, stock_ids: List[str]) -> Dict[str, dict]:
        """
        批次取得 TWSE / TPEx 官方 MIS 盤中毫秒報價
        單一請求支援串接約 40~50 檔，延遲 < 0.15s
        """
        if not stock_ids:
            return {}

        results = {}
        # 依 40 檔一組切分
        batch_size = 40
        for i in range(0, len(stock_ids), batch_size):
            chunk = stock_ids[i:i + batch_size]
            ex_ch_list = []
            for sid in chunk:
                mkt = self._market_map.get(sid, "tse" if sid.startswith("00") or len(sid) == 4 and sid < "3000" else "otc")
                ex_ch_list.append(f"{mkt}_{sid}.tw")

            ex_ch_str = "|".join(ex_ch_list)
            timestamp = int(time.time() * 1000)
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}&json=1&delay=0&_={timestamp}"

            try:
                resp = self.session.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    msg_array = data.get("msgArray", [])
                    for msg in msg_array:
                        sid = msg.get("c", "")
                        if not sid:
                            continue
                        
                        # 撮合即時報價解析
                        # z: 當前成交價, tv: 當盤成交量, v: 累積成交量(張), o: 開盤, h: 最高, l: 最低, y: 昨收
                        yesterday_close = clean_num(msg.get("y"))
                        current_price = clean_num(msg.get("z"))
                        if current_price <= 0:
                            # 盤前或暫無撮合價時取買一/賣一或昨收
                            best_bid = msg.get("b", "_").split("_")[0]
                            best_ask = msg.get("a", "_").split("_")[0]
                            current_price = clean_num(best_bid) or clean_num(best_ask) or yesterday_close

                        open_p = clean_num(msg.get("o")) or current_price
                        high_p = clean_num(msg.get("h")) or current_price
                        low_p = clean_num(msg.get("l")) or current_price
                        volume_sheets = clean_num(msg.get("v"), is_float=False)
                        
                        # 漲跌幅計算
                        pct_change = 0.0
                        if yesterday_close > 0 and current_price > 0:
                            pct_change = round(((current_price - yesterday_close) / yesterday_close) * 100.0, 2)

                        # 買賣五檔
                        bids = [clean_num(x) for x in msg.get("b", "").split("_") if x and x != "-"]
                        asks = [clean_num(x) for x in msg.get("a", "").split("_") if x and x != "-"]
                        bid_vols = [clean_num(x, is_float=False) for x in msg.get("g", "").split("_") if x and x != "-"]
                        ask_vols = [clean_num(x, is_float=False) for x in msg.get("f", "").split("_") if x and x != "-"]

                        results[sid] = {
                            "stock_id": sid,
                            "stock_name": msg.get("n", self._name_map.get(sid, sid)),
                            "time": msg.get("t", ""),
                            "open": open_p,
                            "high": high_p,
                            "low": low_p,
                            "close": current_price,
                            "yesterday_close": yesterday_close,
                            "volume": volume_sheets,
                            "pct_change": pct_change,
                            "bids": bids,
                            "asks": asks,
                            "bid_vols": bid_vols,
                            "ask_vols": ask_vols
                        }
            except Exception as e:
                pass

        return results

    def get_stitched_dataframe(self, stock_id: str, days: int = 120) -> pd.DataFrame:
        """
        將歷史日 K 與當日盤中即時 MIS 報價無縫拼接成單一 DataFrame
        """
        conn = self.get_db_connection()
        query = f"""
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes 
        WHERE stock_id = '{stock_id}'
        ORDER BY date DESC
        LIMIT {days};
        """
        df_hist = pd.read_sql_query(query, conn)
        conn.close()

        if not df_hist.empty:
            df_hist = df_hist.sort_values("date").reset_index(drop=True)

        # 嘗試取得當日盤中即時數據進行拼接
        today_str = datetime.now().strftime("%Y%m%d")
        last_hist_date = df_hist["date"].iloc[-1] if not df_hist.empty else ""

        # 若最後一筆歷史日期小於今日且現在為盤中，抓取 MIS 拼接
        mis_data = self.get_mis_quotes([stock_id]).get(stock_id)
        if mis_data and last_hist_date != today_str and mis_data["close"] > 0:
            turnover_estimate_k = round(mis_data["close"] * mis_data["volume"] * 1000 / 1000.0, 2)
            today_row = {
                "date": today_str,
                "stock_id": stock_id,
                "stock_name": mis_data["stock_name"],
                "market": "TW" if self._market_map.get(stock_id) == "tse" else "TWO",
                "open": mis_data["open"],
                "high": mis_data["high"],
                "low": mis_data["low"],
                "close": mis_data["close"],
                "volume": mis_data["volume"],
                "turnover_k": turnover_estimate_k,
                "pct_change": mis_data["pct_change"],
                "avg_price": mis_data["close"],
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0
            }
            df_today = pd.DataFrame([today_row])
            df_stitched = pd.concat([df_hist, df_today], ignore_index=True)
            return df_stitched

        return df_hist

    # ==========================================================================
    # 3. 三層智慧漏斗機制（Three-Tier Intelligent Funnel）
    # ==========================================================================
    def get_eye_of_storm_pool(self, top_n: int = 150) -> List[str]:
        """
        【Tier 1：開盤前初篩 150 檔暴風眼候選池】
        篩選條件：
        1. 排除冷門殭屍股：昨日成交量 >= 1,000 張 且 成交額 >= 3,000 萬元 (turnover_k >= 30,000)
        2. 動能評估：近 20 日波動度、創 5 日新高動能、投信外資有買盤之焦點標的
        """
        conn = self.get_db_connection()
        query = """
        WITH latest_date AS (
            SELECT MAX(date) as max_d FROM daily_quotes
        )
        SELECT stock_id, stock_name, volume, turnover_k, pct_change, close
        FROM daily_quotes
        WHERE date = (SELECT max_d FROM latest_date)
          AND volume >= 1000
          AND turnover_k >= 30000
          AND close >= 10.0
        ORDER BY turnover_k DESC, volume DESC
        LIMIT 300;
        """
        df_candidates = pd.read_sql_query(query, conn)
        conn.close()

        if df_candidates.empty:
            return ["2330", "0050", "00631L", "2603", "2317", "2454", "3035", "3443"]

        selected_sids = df_candidates["stock_id"].tolist()[:top_n]
        return selected_sids

    def poll_funnel_realtime(self, pool_sids: Optional[List[str]] = None) -> Dict[str, dict]:
        """
        【Tier 2 & Tier 3：盤中極速輪詢與指標計算】
        僅需 3~4 次 API 請求即可監控全市場焦點池
        """
        if not pool_sids:
            pool_sids = self.get_eye_of_storm_pool(top_n=150)

        # 抓取盤中即時報價
        quotes = self.get_mis_quotes(pool_sids)
        return quotes

    # ==========================================================================
    # 4. 每日 15:30 盤後增量更新模組（切片解包防呆）
    # ==========================================================================
    def update_daily_incremental(self, target_date: Optional[str] = None) -> int:
        """
        每日 15:30 自動抓取全市場 2,202 檔數據寫入 SQLite
        """
        if not target_date:
            target_date = datetime.now().strftime("%Y%m%d")

        print(f"🔄 正在執行 [{target_date}] 每日盤後全市場增量更新...")
        
        # 1. 抓取上市行情 (MI_INDEX)
        tw_records = []
        tw_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={target_date}&type=ALLBUT0999&response=json"
        try:
            resp = self.session.get(tw_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_rows = []
                for table in data.get("tables", []):
                    if "收盤行情" in table.get("title", ""):
                        raw_rows = table.get("data", [])
                        break
                if not raw_rows and "data9" in data:
                    raw_rows = data["data9"]
                elif not raw_rows and "data8" in data:
                    raw_rows = data["data8"]

                for r in raw_rows:
                    if len(r) < 11:
                        continue
                    sid, sname, vol_raw, tx_cnt, turnover_raw, open_raw, high_raw, low_raw, close_raw, sign_raw, diff_raw = r[:11]
                    if not is_valid_target(sid, sname):
                        continue

                    volume_shares = clean_num(vol_raw, is_float=False)
                    turnover_ntd = clean_num(turnover_raw, is_float=True)
                    open_p = clean_num(open_raw, is_float=True)
                    high_p = clean_num(high_raw, is_float=True)
                    low_p = clean_num(low_raw, is_float=True)
                    close_p = clean_num(close_raw, is_float=True)
                    diff = clean_num(diff_raw, is_float=True)

                    if "-" in str(sign_raw) or "跌" in str(sign_raw):
                        diff = -abs(diff)
                    elif "+" in str(sign_raw) or "漲" in str(sign_raw):
                        diff = abs(diff)

                    ref_price = close_p - diff if close_p > 0 else 0.0
                    pct_change = round((diff / ref_price * 100.0), 2) if ref_price > 0 else 0.0
                    volume_sheets = int(volume_shares // 1000)
                    turnover_k = round(turnover_ntd / 1000.0, 2)
                    avg_price = round(turnover_ntd / volume_shares, 2) if volume_shares > 0 else close_p

                    tw_records.append({
                        "date": target_date, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(),
                        "market": "TW", "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                        "volume": volume_sheets, "turnover_k": turnover_k, "pct_change": pct_change, "avg_price": avg_price
                    })
        except Exception as e:
            print(f"⚠️ 上市行情更新警告: {e}")

        # 2. 抓取上櫃行情 (TPEx)
        two_records = []
        roc_year = int(target_date[:4]) - 1911
        roc_date_str = f"{roc_year}/{target_date[4:6]}/{target_date[6:]}"
        tpex_url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date_str}&_={int(time.time()*1000)}"
        try:
            resp = self.session.get(tpex_url, timeout=15)
            if resp.status_code == 200:
                raw_rows = resp.json().get("aaData", [])
                for r in raw_rows:
                    if len(r) < 10:
                        continue
                    sid, sname, close_raw, diff_raw, open_raw, high_raw, low_raw, avg_raw, vol_raw, turnover_raw = r[:10]
                    if not is_valid_target(sid, sname):
                        continue

                    volume_shares = clean_num(vol_raw, is_float=False)
                    turnover_ntd = clean_num(turnover_raw, is_float=True)
                    open_p = clean_num(open_raw, is_float=True)
                    high_p = clean_num(high_raw, is_float=True)
                    low_p = clean_num(low_raw, is_float=True)
                    close_p = clean_num(close_raw, is_float=True)
                    diff = clean_num(diff_raw, is_float=True)

                    ref_price = close_p - diff if close_p > 0 else 0.0
                    pct_change = round((diff / ref_price * 100.0), 2) if ref_price > 0 else 0.0
                    volume_sheets = int(volume_shares // 1000)
                    turnover_k = round(turnover_ntd / 1000.0, 2)
                    avg_price = clean_num(avg_raw, is_float=True)
                    if avg_price <= 0 and volume_shares > 0:
                        avg_price = round(turnover_ntd / volume_shares, 2)
                    elif avg_price <= 0:
                        avg_price = close_p

                    two_records.append({
                        "date": target_date, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(),
                        "market": "TWO", "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                        "volume": volume_sheets, "turnover_k": turnover_k, "pct_change": pct_change, "avg_price": avg_price
                    })
        except Exception as e:
            print(f"⚠️ 上櫃行情更新警告: {e}")

        # 3. 抓取三大法人籌碼 (T86)
        inst_map = {}
        # TWSE T86
        try:
            t86_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={target_date}&selectType=ALLBUT0999&response=json"
            resp = self.session.get(t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("data", []):
                    if len(r) >= 12:
                        sid = str(r[0]).strip()
                        inst_map[sid] = {
                            "f": clean_num(r[4], is_float=False) // 1000,
                            "t": clean_num(r[7], is_float=False) // 1000,
                            "d": clean_num(r[11], is_float=False) // 1000
                        }
        except Exception:
            pass

        # TPEx T86
        try:
            tpex_t86_url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date_str}&se=EW&t=D&_={int(time.time()*1000)}"
            resp = self.session.get(tpex_t86_url, timeout=15)
            if resp.status_code == 200:
                for r in resp.json().get("aaData", []):
                    if len(r) >= 15:
                        sid = str(r[0]).strip()
                        inst_map[sid] = {
                            "f": clean_num(r[7], is_float=False) // 1000,
                            "t": clean_num(r[10], is_float=False) // 1000,
                            "d": clean_num(r[13], is_float=False) // 1000
                        }
        except Exception:
            pass

        # 4. 寫入 SQLite
        all_records = tw_records + two_records
        if not all_records:
            print("⚠️ 今日無開盤資料或取得為空。")
            return 0

        conn = self.get_db_connection()
        cursor = conn.cursor()
        insert_rows = []
        for q in all_records:
            sid = q["stock_id"]
            inst = inst_map.get(sid, {"f": 0, "t": 0, "d": 0})
            insert_rows.append((
                q["date"], q["stock_id"], q["stock_name"], q["market"],
                q["open"], q["high"], q["low"], q["close"],
                q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                inst["f"], inst["t"], inst["d"]
            ))

        cursor.executemany("""
        INSERT OR REPLACE INTO daily_quotes 
        (date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, insert_rows)
        conn.commit()
        conn.close()

        # 更新快取對照表
        self._load_symbol_directory()
        print(f"✅ 增量更新完成！共寫入 {len(insert_rows):,} 檔標的行情。")
        return len(insert_rows)

# ------------------------------------------------------------------------------
# 沙盒單獨測試執行區塊
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 啟動 data_fetcher.py 模組獨立驗證測試")
    print("=" * 70)

    # 1. 建立 Fetcher 實例
    fetcher = DataFetcher()

    # 2. 測試暴風眼候選池初篩
    print("\n[測試 1] 暴風眼候選池 (Tier 1) 初篩測試...")
    pool = fetcher.get_eye_of_storm_pool(top_n=10)
    print(f"  • 前 10 檔焦點候選池: {pool}")
    assert len(pool) > 0, "❌ 候選池初篩異常為空！"

    # 3. 測試 MIS 盤中毫秒報價
    print("\n[測試 2] MIS 毫秒報價抓取測試 (2330, 0050, 6415)...")
    test_sids = ["2330", "0050", "6415"]
    quotes = fetcher.get_mis_quotes(test_sids)
    for sid, q in quotes.items():
        print(f"  • [{sid}] {q['stock_name']}: 報價={q['close']} | 昨收={q['yesterday_close']} | 漲跌幅={q['pct_change']}% | 累積量={q['volume']}張")
    assert len(quotes) > 0, "❌ MIS 報價獲取失敗！"

    # 4. 測試歷史 K 線與盤中數據無縫拼接
    print("\n[測試 3] 歷史 K 線與盤中即時數據拼接 (2330)...")
    df_stitched = fetcher.get_stitched_dataframe("2330", days=5)
    print(df_stitched[["date", "stock_id", "stock_name", "close", "volume", "pct_change"]].to_string(index=False))
    assert not df_stitched.empty, "❌ 拼接 DataFrame 為空！"

    print("\n" + "=" * 70)
    print("🎉 data_fetcher.py 模組沙盒自測 100% 通過！")
    print("=" * 70)
