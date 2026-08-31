# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組一【數據與行情核心】
# 檔案名稱：data_fetcher.py
# 核心職責：歷史庫管理、盤中 MIS 毫秒報價、歷史盤中無縫拼接、每日增量更新、暴風眼初篩漏斗
# ==============================================================================

import os
import sys
import time
import json
import zipfile
import shutil
import sqlite3
from datetime import datetime, timedelta
import requests
import pandas as pd

try:
    from config import get_cache_dir, get_db_path, get_github_release_url
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

    def get_cache_dir():
        return os.getenv("WAYNE_CACHE_DIR") or "waynebot_cache"

    def get_github_release_url():
        return os.getenv("GITHUB_RELEASE_URL") or ""

class DataFetcher:
    def __init__(
        self,
        db_path: str = None,
        github_release_url: str = None,
        cache_dir: str = None,
        **kwargs,
    ):
        """
        初始化行情核心引擎
        :param db_path: SQLite 資料庫路徑
        :param github_release_url: GitHub Release 歷史庫 zip 下載連結 (0秒開機用)
        """
        self.db_path = os.path.abspath(db_path or get_db_path())
        self.cache_dir = os.path.abspath(cache_dir or get_cache_dir())
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.github_release_url = github_release_url or get_github_release_url() or (
            "https://github.com/wayne05281019/WayneBot/releases/download/v1.0-data/waynebot_production_complete.zip"
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })
        
        # 確保資料庫就緒（0 秒開機機制）
        self._ensure_database_ready()

    # --------------------------------------------------------------------------
    # 1. 0 秒開機：資料庫存在性檢查與雲端 Release 自動下載解壓
    # --------------------------------------------------------------------------
    def _ensure_database_ready(self):
        """檢查本地資料庫，若不存在則自動自 GitHub Release 串流下載解壓"""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1024 * 1024:
            self._optimize_db_settings()
            return

        print(f"📦 未偵測到本地歷史資料庫，準備自 GitHub Release 下載：{self.github_release_url}")
        zip_temp_path = self.db_path + ".temp.zip"
        try:
            resp = self.session.get(self.github_release_url, stream=True, timeout=60)
            if resp.status_code == 200:
                with open(zip_temp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                
                extract_dir = os.path.dirname(self.db_path) or "."
                with zipfile.ZipFile(zip_temp_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                self._adopt_extracted_database(extract_dir)
                if os.path.exists(zip_temp_path):
                    os.remove(zip_temp_path)
                print(f"✅ 歷史庫下載並解壓完成：{self.db_path}")
            else:
                print(f"⚠️ 下載失敗 (HTTP {resp.status_code})，建立全新空白資料庫結構。")
                self._init_empty_database()
        except Exception as e:
            print(f"⚠️ 雲端下載異常：{e}，建立全新空白資料庫結構。")
            if os.path.exists(zip_temp_path):
                os.remove(zip_temp_path)
            self._init_empty_database()

        self._optimize_db_settings()

    def _adopt_extracted_database(self, extract_dir: str) -> None:
        """zip 內檔名可能是 wayne_trading.db，對齊到正式路徑。"""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1024 * 1024:
            return
        found = None
        for root, _dirs, files in os.walk(extract_dir):
            for name in files:
                if name.endswith(".db") and not name.endswith(("-wal", "-shm")):
                    candidate = os.path.join(root, name)
                    if os.path.getsize(candidate) > 1024 * 1024:
                        found = candidate
                        break
            if found:
                break
        if found and os.path.abspath(found) != os.path.abspath(self.db_path):
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            shutil.copy2(found, self.db_path)
            print(f"✅ 已採用解壓資料庫 {found} → {self.db_path}")

    def _optimize_db_settings(self):
        """啟用 SQLite WAL 模式與效能調優"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _init_empty_database(self):
        """初始化標準資料庫架構與索引"""
        conn = sqlite3.connect(self.db_path)
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
        """取得 SQLite 連線"""
        return sqlite3.connect(self.db_path)

    # --------------------------------------------------------------------------
    # 2. 標的過濾與數值清洗共用工具
    # --------------------------------------------------------------------------
    @staticmethod
    def is_valid_target(stock_id: str, stock_name: str) -> bool:
        try:
            from universe import is_tradable
            return is_tradable(stock_id, stock_name)
        except Exception:
            sid = str(stock_id).strip()
            if len(sid) == 4 and sid.isdigit():
                return True
            if sid.startswith("00") or "KY" in str(stock_name):
                return True
            return False

    @staticmethod
    def clean_num(val, is_float: bool = True):
        if val is None:
            return 0.0 if is_float else 0
        s = str(val).replace(",", "").replace("+", "").replace("X", "").strip()
        if s in ["--", "-", "", "N/A", "null", "None"]:
            return 0.0 if is_float else 0
        try:
            return float(s) if is_float else int(float(s))
        except Exception:
            return 0.0 if is_float else 0

    # --------------------------------------------------------------------------
    # 3. 盤中 MIS 毫秒級即時報價（支援單檔與批次 20~50 檔）
    # --------------------------------------------------------------------------
    def get_realtime_quotes(self, stock_ids: list) -> dict:
        """
        抓取台股盤中即時報價 (TWSE MIS 毫秒級 API)
        :param stock_ids: 股票代號清單，例如 ['2330', '6415', '0050']
        :return: 以 stock_id 為鍵的即時行情字典
        """
        if not stock_ids:
            return {}

        # 1. 查詢標的所屬市場 (TWSE tse / TPEx otc)
        conn = self.get_db_connection()
        placeholders = ",".join(["?"] * len(stock_ids))
        query = f"SELECT stock_id, market, stock_name FROM daily_quotes WHERE stock_id IN ({placeholders}) GROUP BY stock_id;"
        df_market = pd.read_sql_query(query, conn, params=stock_ids)
        conn.close()

        market_map = {}
        for _, row in df_market.iterrows():
            market_map[row["stock_id"]] = (row["market"], row["stock_name"])

        # 2. 組合 MIS API 查詢字串 (ex_ch=tse_2330.tw|otc_6415.two)
        channel_list = []
        for sid in stock_ids:
            m_info = market_map.get(sid, ("TW", sid))
            prefix = "tse" if m_info[0] == "TW" else "otc"
            suffix = "tw" if m_info[0] == "TW" else "two"
            channel_list.append(f"{prefix}_{sid}.{suffix}")

        results = {}
        # 每次最多查詢 40 檔，避免超出 URL 長度限制
        chunk_size = 40
        for i in range(0, len(channel_list), chunk_size):
            chunk = channel_list[i:i + chunk_size]
            ex_ch_str = "|".join(chunk)
            ts = int(time.time() * 1000)
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch_str}&json=1&delay=0&_={ts}"

            try:
                resp = self.session.get(url, timeout=5)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                msg_array = data.get("msgArray", [])

                for item in msg_array:
                    sid = item.get("c")
                    sname = item.get("n")
                    yesterday_close = self.clean_num(item.get("y"))
                    current_price = self.clean_num(item.get("z"))
                    if current_price <= 0:
                        def _book(side):
                            return self.clean_num(str(side or "").split("_")[0])
                        bid, ask = _book(item.get("b")), _book(item.get("a"))
                        if bid > 0 and ask > 0:
                            current_price = round((bid + ask) / 2.0, 2)
                        elif ask > 0:
                            current_price = ask
                        elif bid > 0:
                            current_price = bid
                        else:
                            current_price = yesterday_close

                    open_p = self.clean_num(item.get("o")) or current_price
                    high_p = self.clean_num(item.get("h")) or current_price
                    low_p = self.clean_num(item.get("l")) or current_price
                    
                    # 累積成交量（張）
                    vol_sheets = self.clean_num(item.get("v"), is_float=False)

                    # 漲跌幅計算
                    pct_change = 0.0
                    if yesterday_close > 0 and current_price > 0:
                        pct_change = round(((current_price - yesterday_close) / yesterday_close) * 100.0, 2)

                    results[sid] = {
                        "stock_id": sid,
                        "stock_name": sname,
                        "current_price": current_price,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "yesterday_close": yesterday_close,
                        "volume": vol_sheets,
                        "pct_change": pct_change,
                        "update_time": item.get("t", ""),
                        "is_realtime": True
                    }
            except Exception as e:
                print(f"⚠️ 盤中報價抓取異常 ({chunk[0]}...): {e}")

        return results

    # --------------------------------------------------------------------------
    # 4. 歷史與盤中實時動態無縫拼接（K線量化決策核心）
    # --------------------------------------------------------------------------
    def get_combined_history(self, stock_id: str, days: int = 120, include_today_realtime: bool = True) -> pd.DataFrame:
        """
        取得個股歷史日 K 資料，並於盤中自動無縫拼接今日即時價量
        :param stock_id: 股票代號
        :param days: 抓取天數 (預設 120 天，足夠計算 60MA/Hi120 等量化指標)
        :param include_today_realtime: 是否在開盤期間拼接今日實時行情
        :return: 包含完整指標欄位的 Pandas DataFrame
        """
        conn = self.get_db_connection()
        query = """
        SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        FROM daily_quotes 
        WHERE stock_id = ? 
        ORDER BY date DESC 
        LIMIT ?;
        """
        df = pd.read_sql_query(query, conn, params=(stock_id, days))
        conn.close()

        if df.empty:
            return pd.DataFrame()

        # 依照日期由舊至新排序
        df = df.sort_values("date").reset_index(drop=True)

        # 判斷是否需要拼接今日盤中數據
        if include_today_realtime:
            from config import taipei_today_str

            today_str = taipei_today_str()
            latest_db_date = str(df["date"].iloc[-1])

            # 若資料庫最新日期小於今天（代表今天尚未收盤增量入庫）
            if latest_db_date < today_str:
                now_time = datetime.now().time()
                # 僅在台股盤中或收盤前段 (09:00 ~ 15:30) 進行拼接
                is_trading_hour = (now_time >= datetime.strptime("09:00", "%H:%M").time()) and \
                                  (now_time <= datetime.strptime("15:30", "%H:%M").time())

                if is_trading_hour or True:  # 盤中或盤後均可嘗試抓取最新狀態
                    rt_map = self.get_realtime_quotes([stock_id])
                    if stock_id in rt_map and rt_map[stock_id]["current_price"] > 0:
                        rt = rt_map[stock_id]
                        today_row = {
                            "date": today_str,
                            "stock_id": stock_id,
                            "stock_name": rt["stock_name"] or df["stock_name"].iloc[-1],
                            "market": df["market"].iloc[-1],
                            "open": rt["open"],
                            "high": rt["high"],
                            "low": rt["low"],
                            "close": rt["current_price"],
                            "volume": rt["volume"],
                            "turnover_k": round(rt["volume"] * rt["current_price"], 2), # 盤中估算千元額
                            "pct_change": rt["pct_change"],
                            "avg_price": rt["current_price"],
                            "foreign_net": 0,
                            "trust_net": 0,
                            "dealer_net": 0
                        }
                        df = pd.concat([df, pd.DataFrame([today_row])], ignore_index=True)

        return df

    # --------------------------------------------------------------------------
    # 5. 三層智慧漏斗：開盤前「暴風眼 150 檔候選池」快篩
    # --------------------------------------------------------------------------
    def get_storm_eye_candidates(self, 
                                 lookback_days: int = 20, 
                                 min_avg_volume: int = 1000, 
                                 min_avg_turnover_k: float = 30000.0,
                                 pool_limit: int = 150) -> list:
        """
        第一層智慧漏斗：篩選過去 20 日具備高動能與充沛流動性的「暴風眼候選池」
        :param lookback_days: 評估天數 (預設 20 日)
        :param min_avg_volume: 日均量門檻 (預設 1,000 張)
        :param min_avg_turnover_k: 日均額門檻 (預設 30,000 千元 = 3,000 萬)
        :param pool_limit: 候選池容量上限 (預設 150 檔)
        :return: 候選標的 stock_id 清單
        """
        conn = self.get_db_connection()
        query = f"""
        WITH recent_dates AS (
            SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT {lookback_days}
        ),
        pool_stats AS (
            SELECT 
                stock_id,
                stock_name,
                market,
                AVG(volume) as avg_vol,
                AVG(turnover_k) as avg_turnover,
                MAX(close) as max_c,
                AVG(close) as avg_c
            FROM daily_quotes
            WHERE date IN (SELECT date FROM recent_dates)
            GROUP BY stock_id
            HAVING AVG(volume) >= ? AND AVG(turnover_k) >= ?
        )
        SELECT stock_id, stock_name, market, avg_vol, avg_turnover
        FROM pool_stats
        ORDER BY avg_turnover DESC
        LIMIT ?;
        """
        df = pd.read_sql_query(query, conn, params=(min_avg_volume, min_avg_turnover_k, pool_limit))
        conn.close()

        if df.empty:
            return []

        candidates = df["stock_id"].tolist()
        return candidates

    def _get_json_retry(self, url: str, tries: int = 3):
        last = None
        for i in range(max(1, int(tries))):
            try:
                resp = self.session.get(url, timeout=40)
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}"
            except Exception as e:
                last = e
            time.sleep(1.1 * (i + 1))
        print(f"⚠️ JSON 抓取失敗 {url.split('?')[0]}：{last}")
        return None

    def _fetch_tpex_daily(self, target_date: str) -> list:
        """櫃買收盤。新版 JSON 在 tables[].data（欄名對應），舊版才是 aaData。"""
        yyyy, mm, dd = target_date[:4], target_date[4:6], target_date[6:]
        roc = f"{int(yyyy) - 1911}/{mm}/{dd}"
        urls = [
            f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={yyyy}/{mm}/{dd}&id=&response=json",
            f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc}&o=json",
        ]
        payload = None
        for url in urls:
            payload = self._get_json_retry(url)
            if payload:
                break
        if not payload:
            self._tpex_status = "error"
            return []
        raw_rows, fields = [], []
        if isinstance(payload, dict):
            raw_rows = payload.get("aaData") or []
            if not raw_rows:
                best = None
                for tb in payload.get("tables") or []:
                    title = str(tb.get("title") or "")
                    rows = tb.get("data") or []
                    if not rows:
                        continue
                    if "管理" in title:
                        continue
                    score = len(rows)
                    if "上櫃" in title or "收盤" in title:
                        score += 10000
                    if best is None or score > best[0]:
                        best = (score, rows, tb.get("fields") or [])
                if best:
                    raw_rows, fields = best[1], best[2]
        if not raw_rows:
            self._tpex_status = "empty"
            return []
        self._tpex_status = "ok"
        idx = {str(n): i for i, n in enumerate(fields)}

        def col(row, name, fallback_i):
            i = idx.get(name)
            if i is None:
                i = fallback_i
            if i is None or i >= len(row):
                return 0
            return row[i]

        out = []
        for r in raw_rows:
            if not r or len(r) < 8:
                continue
            sid = str(col(r, "代號", 0)).strip()
            sname = str(col(r, "名稱", 1)).strip()
            if not self.is_valid_target(sid, sname):
                continue
            close_p = self.clean_num(col(r, "收盤", 2), True)
            diff = self.clean_num(col(r, "漲跌", 3), True)
            open_p = self.clean_num(col(r, "開盤", 4), True)
            high_p = self.clean_num(col(r, "最高", 5), True)
            low_p = self.clean_num(col(r, "最低", 6), True)
            avg_p = self.clean_num(col(r, "均價", 7), True)
            volume_shares = self.clean_num(col(r, "成交股數", 8), False)
            turnover_ntd = self.clean_num(col(r, "成交金額(元)", 9), True)
            if turnover_ntd <= 0:
                turnover_ntd = self.clean_num(col(r, "成交金額", 9), True)
            ref_p = close_p - diff if close_p > 0 else 0.0
            pct = round((diff / ref_p * 100.0), 2) if ref_p > 0 else 0.0
            if avg_p <= 0 and volume_shares > 0:
                avg_p = round(turnover_ntd / volume_shares, 2)
            elif avg_p <= 0:
                avg_p = close_p
            out.append({
                "date": target_date, "stock_id": sid, "stock_name": sname,
                "market": "TWO", "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                "volume": int(volume_shares // 1000) if volume_shares >= 1000 else int(volume_shares),
                "turnover_k": round(turnover_ntd / 1000.0, 2),
                "pct_change": pct, "avg_price": avg_p,
            })
        return out

    # --------------------------------------------------------------------------
    # 6. 每日 15:30 增量更新閉環（自動排程調用）
    # --------------------------------------------------------------------------
    def update_daily_market_data(self, target_date: str = None) -> int:
        """
        每日盤後抓取當日上市櫃 2,358 檔行情與三大法人買賣超，並以切片解包寫入 SQLite
        :param target_date: 指定日期 YYYYMMDD，若無則預設今天
        :return: 成功寫入筆數
        """
        if not target_date:
            try:
                from config import taipei_today_str
                target_date = taipei_today_str()
            except Exception:
                target_date = datetime.now().strftime("%Y%m%d")

        print(f"🔄 啟動 {target_date} 盤後增量更新流程...")

        # 1. 抓取上市行情 (TWSE MI_INDEX)
        tw_records = []
        tw_status = "error"
        tw_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={target_date}&type=ALLBUT0999&response=json"
        try:
            resp = self.session.get(tw_url, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                stat = str(data.get("stat") or "")
                if "沒有符合" in stat or "很抱歉" in stat:
                    tw_status = "empty"
                else:
                    tw_status = "ok"
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
                    if not self.is_valid_target(sid, sname):
                        continue

                    volume_shares = self.clean_num(vol_raw, is_float=False)
                    turnover_ntd = self.clean_num(turnover_raw, is_float=True)
                    open_p = self.clean_num(open_raw, is_float=True)
                    high_p = self.clean_num(high_raw, is_float=True)
                    low_p = self.clean_num(low_raw, is_float=True)
                    close_p = self.clean_num(close_raw, is_float=True)
                    diff = self.clean_num(diff_raw, is_float=True)
                    if "-" in str(sign_raw) or "跌" in str(sign_raw):
                        diff = -abs(diff)
                    elif "+" in str(sign_raw) or "漲" in str(sign_raw):
                        diff = abs(diff)

                    ref_p = close_p - diff if close_p > 0 else 0.0
                    pct = round((diff / ref_p * 100.0), 2) if ref_p > 0 else 0.0
                    avg_p = round(turnover_ntd / volume_shares, 2) if volume_shares > 0 else close_p

                    tw_records.append({
                        "date": target_date, "stock_id": str(sid).strip(), "stock_name": str(sname).strip(),
                        "market": "TW", "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                        "volume": int(volume_shares // 1000), "turnover_k": round(turnover_ntd / 1000.0, 2),
                        "pct_change": pct, "avg_price": avg_p
                    })
        except Exception as e:
            print(f"⚠️ 上市增量抓取異常：{e}")

        two_records = self._fetch_tpex_daily(target_date)
        tpex_status = getattr(self, "_tpex_status", "ok" if two_records else "empty")
        attempt = 0
        while tw_status == "ok" and len(tw_records) >= 800 and len(two_records) < 400 and attempt < 4:
            attempt += 1
            print(f"🔁 上市已有 {len(tw_records)} 檔，上櫃只有 {len(two_records)}，第 {attempt} 次再抓櫃買")
            time.sleep(1.15 * attempt)
            extra = self._fetch_tpex_daily(target_date)
            if len(extra) > len(two_records):
                two_records = extra
            tpex_status = getattr(self, "_tpex_status", "ok" if two_records else "empty")

        if tw_status == "empty" and tpex_status == "empty" and not tw_records and not two_records:
            conn = self.get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM daily_quotes WHERE date=?", (target_date,))
            gone = cur.rowcount
            conn.commit()
            conn.close()
            if gone:
                print(f"📭 {target_date} 證交所與櫃買皆無收盤，已刪殘列 {gone}")
            else:
                print(f"📭 {target_date} 非交易日（兩邊官方都沒有行情）。")
            return 0

        # 三大法人（欄位對齊 chips.py，避免舊 T86 錯欄）
        tw_t86 = {}
        two_t86 = {}
        try:
            from chips import fetch_chips_for_date
            merged = fetch_chips_for_date(self.session, target_date)
            tw_t86 = merged
            two_t86 = merged
        except Exception as e:
            print(f"⚠️ 法人籌碼抓取異常：{e}")

        # 4. 組合並寫入資料庫
        all_records = []
        for q in tw_records:
            inst = tw_t86.get(q["stock_id"], {"foreign_net": 0, "trust_net": 0, "dealer_net": 0})
            all_records.append((
                q["date"], q["stock_id"], q["stock_name"], q["market"],
                q["open"], q["high"], q["low"], q["close"],
                q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                inst["foreign_net"], inst["trust_net"], inst["dealer_net"]
            ))

        for q in two_records:
            inst = two_t86.get(q["stock_id"], {"foreign_net": 0, "trust_net": 0, "dealer_net": 0})
            all_records.append((
                q["date"], q["stock_id"], q["stock_name"], q["market"],
                q["open"], q["high"], q["low"], q["close"],
                q["volume"], q["turnover_k"], q["pct_change"], q["avg_price"],
                inst["foreign_net"], inst["trust_net"], inst["dealer_net"]
            ))

        if all_records:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT INTO daily_quotes
            (date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                market=excluded.market,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                turnover_k=excluded.turnover_k,
                pct_change=excluded.pct_change,
                avg_price=excluded.avg_price,
                foreign_net=CASE WHEN excluded.foreign_net=0 AND daily_quotes.foreign_net!=0
                    THEN daily_quotes.foreign_net ELSE excluded.foreign_net END,
                trust_net=CASE WHEN excluded.trust_net=0 AND daily_quotes.trust_net!=0
                    THEN daily_quotes.trust_net ELSE excluded.trust_net END,
                dealer_net=CASE WHEN excluded.dealer_net=0 AND daily_quotes.dealer_net!=0
                    THEN daily_quotes.dealer_net ELSE excluded.dealer_net END;
            """, all_records)
            conn.commit()
            conn.close()
            print(f"✅ {target_date} 增量更新成功：寫入 {len(all_records)} 筆 (上市: {len(tw_records)}, 上櫃: {len(two_records)})")
            try:
                from import_health import audit_import
                health = audit_import(self.db_path, target_date)
                if health.get("problems"):
                    print(f"⚠️ 匯入檢查 {target_date}：{health['problems']} tw={health['tw']} two={health['two']} chips={health['chips_nonzero']}")
                else:
                    print(f"匯入檢查 OK {target_date} 上市{health['tw']} 上櫃{health['two']} 法人非0 {health['chips_nonzero']}")
            except Exception:
                pass
            return len(all_records)
        else:
            print(f"⚠️ {target_date} 非交易日或尚無行情資料。")
            return 0

    def fill_missing_market_days(self, end_date: str = None, max_days: int = 15) -> dict:
        """從資料庫最新交易日的隔天補到台灣今日（假日自動略過）。"""
        try:
            from config import taipei_today_str
            end_date = end_date or taipei_today_str()
        except Exception:
            end_date = end_date or datetime.now().strftime("%Y%m%d")
        conn = self.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM daily_quotes;")
        row = cur.fetchone()
        conn.close()
        latest = str(row[0]).replace("-", "") if row and row[0] else ""
        filled, skipped = [], []
        if not latest:
            n = self.update_daily_market_data(end_date)
            return {"from": "", "to": end_date, "filled": [end_date] if n else [], "skipped": []}
        start = datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)
        end = datetime.strptime(end_date, "%Y%m%d")
        if start > end:
            thin = self._refill_thin_days(end_date, lookback=25, min_rows=1500)
            paired = self.sync_paired_markets()
            return {
                "from": latest, "to": end_date, "filled": thin, "skipped": [],
                "note": "已是最新", "refilled_thin": thin, "paired": paired,
            }
        days = 0
        d = start
        while d <= end and days < max_days:
            ds = d.strftime("%Y%m%d")
            days += 1
            if d.weekday() >= 5:
                skipped.append(ds)
                d += timedelta(days=1)
                continue
            n = int(self.update_daily_market_data(ds) or 0)
            if n > 50:
                filled.append(ds)
            else:
                skipped.append(ds)
            time.sleep(0.35)
            d += timedelta(days=1)
        thin = self._refill_thin_days(end_date, lookback=25, min_rows=1500)
        for ds in thin:
            if ds not in filled:
                filled.append(ds)
        paired = self.sync_paired_markets()
        return {
            "from": latest,
            "to": end_date,
            "filled": filled,
            "skipped": skipped,
            "refilled_thin": thin,
            "paired": paired,
        }

    def sync_paired_markets(self, min_tw: int = 800, min_two: int = 400) -> list:
        """上市有開盤的日子，上櫃一定要同一天進庫；缺邊就整日重抓。"""
        try:
            from import_health import list_coverage_issues
            issues = list_coverage_issues(self.db_path, min_tw=min_tw, min_two=min_two)
        except Exception as e:
            print(f"⚠️ 開盤日配對檢查失敗：{e}")
            return []
        filled = []
        for item in issues:
            ds = item.get("date")
            if not ds:
                continue
            print(f"🔁 開盤日缺邊 {ds}：{item.get('problems')}")
            got = int(self.update_daily_market_data(ds) or 0)
            if got > 50:
                filled.append(ds)
            time.sleep(0.4)
        return filled

    def _refill_thin_days(self, end_date: str, lookback: int = 25, min_rows: int = 1500) -> list:
        """已有日期但檔數偏少、或上市／上櫃一邊缺，就整日重抓。開盤日兩邊都要有。"""
        end_date = str(end_date or "").replace("-", "")[:8]
        conn = self.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT replace(date,'-','') AS d,
                   COUNT(*) AS n,
                   SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END) AS tw,
                   SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END) AS two
            FROM daily_quotes
            WHERE replace(date,'-','') <= ?
            GROUP BY replace(date,'-','')
            ORDER BY d DESC
            LIMIT ?;
            """,
            (end_date, int(lookback) + 8),
        )
        rows = cur.fetchall()
        conn.close()
        filled = []
        for date, n, tw, two in rows:
            ds = str(date)
            try:
                wd = datetime.strptime(ds, "%Y%m%d").weekday()
            except Exception:
                continue
            if wd >= 5:
                continue
            thin = int(n or 0) < int(min_rows)
            unbalanced = (int(tw or 0) >= 800 and int(two or 0) < 400) or (
                int(two or 0) >= 400 and int(tw or 0) < 800
            )
            if not thin and not unbalanced:
                continue
            got = int(self.update_daily_market_data(ds) or 0)
            if got > 50:
                filled.append(ds)
            time.sleep(0.35)
        return filled

    def repair_quote_coverage(self, min_rows: int = 1800, sleep_s: float = 0.4) -> dict:
        """核對開盤日覆蓋：檔數過少的交易日重抓；空白平日試抓（假日會得到 0 並略過）。

        daily_quotes 欄位意義（張＝股/1000）：
        date 開盤日 YYYYMMDD；stock_id 四碼代號；open/high/low/close 當日價；
        volume 成交張數；turnover_k 成交金額千元；pct_change 漲跌％；
        foreign_net/trust_net/dealer_net 外資／投信／自營買賣超（張，正買負賣）。
        決策卡表頭 10/20/60 日高低＝近 N 根「收盤」最高／最低。
        格子「獲利」＝相對最新日往前 60 個日曆日的收盤最低（與表頭 60 根低不同）。
        量單位與法人一律為張。
        """
        conn = self.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, COUNT(*) n,
                   SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END) tw,
                   SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END) two
            FROM daily_quotes GROUP BY date ORDER BY date
            """
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return {"thin": [], "filled": [], "holiday_or_empty": [], "still_thin": []}
        thin = []
        for d, n, tw, two in rows:
            if int(n or 0) < int(min_rows) or (int(tw or 0) >= 800 and int(two or 0) < 400) or (
                int(two or 0) >= 400 and int(tw or 0) < 800
            ):
                thin.append(str(d))
        have = {str(d) for d, *_rest in rows}
        start = datetime.strptime(str(rows[0][0]), "%Y%m%d")
        end = datetime.strptime(str(rows[-1][0]), "%Y%m%d")
        gaps = []
        d = start
        while d <= end:
            ds = d.strftime("%Y%m%d")
            if d.weekday() < 5 and ds not in have:
                gaps.append(ds)
            d += timedelta(days=1)
        filled, empty = [], []
        for ds in thin + gaps:
            n = int(self.update_daily_market_data(ds) or 0)
            if n > 50:
                filled.append(ds)
            elif ds in gaps:
                empty.append(ds)
            time.sleep(sleep_s)
        conn = self.get_db_connection()
        still = conn.execute(
            """
            SELECT date, COUNT(*) n,
                   SUM(CASE WHEN market IN ('TW','TSE') THEN 1 ELSE 0 END) tw,
                   SUM(CASE WHEN market IN ('TWO','OTC','ROCO') THEN 1 ELSE 0 END) two
            FROM daily_quotes GROUP BY date
            HAVING n < ? OR (tw >= 800 AND two < 400) OR (two >= 400 AND tw < 800)
            ORDER BY date
            """,
            (int(min_rows),),
        ).fetchall()
        conn.close()
        return {
            "thin_before": thin,
            "weekday_gaps_tried": gaps,
            "filled": filled,
            "holiday_or_empty": empty,
            "still_thin": [(str(a), int(b), int(c or 0), int(d or 0)) for a, b, c, d in still],
        }


# ==============================================================================
# 單元測試與沙盒驗收入口 (Sandbox Test Suite)
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 啟動 data_fetcher.py 沙盒全功能驗證測試")
    print("=" * 70)

    # 1. 實例化 Fetcher
    fetcher = DataFetcher(db_path="waynebot_history.db")

    # 2. 測試第一層智慧漏斗（暴風眼 150 檔候選池）
    print("\n🔍 【測試 1】暴風眼 150 檔候選池初篩：")
    storm_pool = fetcher.get_storm_eye_candidates(lookback_days=20, min_avg_volume=1000, min_avg_turnover_k=30000.0, pool_limit=150)
    print(f"  • 篩選出暴風眼高動能標的 : {len(storm_pool)} 檔")
    print(f"  • 候選池前 10 檔抽樣    : {storm_pool[:10]}")
    assert len(storm_pool) > 0, "❌ 暴風眼候選池為空！"

    # 3. 測試盤中 MIS 毫秒報價
    print("\n⚡ 【測試 2】MIS 毫秒即時報價測試 (抽樣 5 檔)：")
    test_sids = ["2330", "0050", "00631L", "6415", "5274"]
    rt_quotes = fetcher.get_realtime_quotes(test_sids)
    for sid, q in rt_quotes.items():
        print(f"  • [{sid}] {q['stock_name']:<8} | 現價: {q['current_price']:>7.1f} | 漲跌幅: {q['pct_change']:>+6.2f}% | 成交量: {q['volume']:>6} 張")
    assert len(rt_quotes) > 0, "❌ 即時報價抓取失敗！"

    # 4. 測試歷史與盤中實時動態無縫拼接
    print("\n🔗 【測試 3】歷史 K 線與盤中動態無縫拼接測試 (以 2330 台積電為例)：")
    df_combined = fetcher.get_combined_history("2330", days=10, include_today_realtime=True)
    print(df_combined[["date", "stock_id", "stock_name", "close", "volume", "pct_change"]].to_string(index=False))
    assert not df_combined.empty, "❌ 歷史與即時拼接失敗！"

    print("\n" + "=" * 70)
    print("🎉 data_fetcher.py 沙盒測試全部通過！可安心替換至根目錄。")
    print("=" * 70)


TaiwanMarketFetcher = DataFetcher
