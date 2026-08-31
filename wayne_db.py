"""
WayneBot 台股量化交易系統 - Phase 1：資料庫底層與資料結構模組
模組名稱：wayne_db.py
說明：
1. 採用 SQLite3 + threading.Lock() 保證多執行緒安全。
2. 強制開啟 WAL 模式 (PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;) 支援高併發讀寫。
3. 實作 get_db_connection() 上下文管理器，自動處理交易 commit 與例外 rollback。
4. 提供 5 張核心資料表建立與完整 CRUD 介面。
5. 預留 stock_map.json 快取載入與記憶體注入介面。
"""

import os
import json
import sqlite3
import threading
import traceback
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Union

# ==============================================================================
# 全域變數與線程鎖配置
# ==============================================================================
DEFAULT_DB_PATH: str = (
    os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"
)
DB_LOCK: threading.Lock = threading.Lock()

# 靜態股票對照表記憶體快取與保護鎖
_STOCK_MAP_CACHE: Dict[str, Any] = {}
_STOCK_MAP_LOCK: threading.Lock = threading.Lock()


# ==============================================================================
# 連線上下文管理器 (Context Manager)
# ==============================================================================
@contextmanager
def get_db_connection(db_path: str = DEFAULT_DB_PATH):
    """
    資料庫連線上下文管理器 (Context Manager)
    - 取得全域線程鎖以確保併發寫入安全
    - 開啟 WAL 模式與 NORMAL 同步模式
    - 正常結束時自動 commit，發生例外時自動 rollback
    """
    with DB_LOCK:
        conn = sqlite3.connect(
            db_path,
            timeout=30.0,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()
        
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            try:
                err_cursor = conn.cursor()
                err_cursor.execute(
                    """
                    INSERT INTO system_logs (module_name, error_message, stack_trace, created_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    ("wayne_db.context_manager", str(e), traceback.format_exc(), datetime.now().isoformat())
                )
                conn.commit()
            except Exception:
                pass
            raise e
        finally:
            conn.close()


# ==============================================================================
# 資料庫初始化函式
# ==============================================================================
def init_database(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    初始化資料庫，自動建立 5 張核心資料表與對應索引
    1. user_states: 使用者對話與狀態表
    2. cached_data: 結構化分析內容與章節快取表
    3. system_logs: 模組例外與系統日誌表
    4. simulated_positions: AI 模擬持倉表
    5. trade_history: 覆盤交易歷史表
    """
    schema_statements = [
        # 1. user_states 表
        """
        CREATE TABLE IF NOT EXISTS user_states (
            user_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, platform)
        );
        """,
        # 2. cached_data 表
        """
        CREATE TABLE IF NOT EXISTS cached_data (
            chapter_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            is_valid INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """,
        # 3. system_logs 表
        """
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_name TEXT NOT NULL,
            error_message TEXT NOT NULL,
            stack_trace TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """,
        # 4. simulated_positions 表 (AI 模擬持倉)
        """
        CREATE TABLE IF NOT EXISTS simulated_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            buy_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            strategy_factor TEXT NOT NULL,
            stop_loss_price REAL NOT NULL,
            take_profit_price REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('holding', 'closed')) DEFAULT 'holding',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        # 5. trade_history 表 (覆盤交易表)
        """
        CREATE TABLE IF NOT EXISTS trade_history (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            sell_date TEXT NOT NULL,
            buy_price REAL NOT NULL,
            sell_price REAL NOT NULL,
            return_rate REAL NOT NULL,
            exit_reason TEXT NOT NULL,
            review_analysis TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    ]
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        for stmt in schema_statements:
            cursor.execute(stmt)
        
        # 建立常用查詢索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_stock_status ON simulated_positions(stock_id, status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_stock ON trade_history(stock_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cached_valid ON cached_data(chapter_id, is_valid);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at);")


def ensure_core_schema(db_path: str = None) -> None:
    """行情、流水線、母體、使用者持股／觀察清單。"""
    path = db_path or DEFAULT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    init_database(path)
    with get_db_connection(path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
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
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON daily_quotes(stock_id, date);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_date ON daily_quotes(date);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_date TEXT PRIMARY KEY,
                finished_at TEXT,
                status TEXT,
                notes TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_universe (
                stock_id TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                market_type TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                industry TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_watchlist (
                user_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, stock_code)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_holdings (
                user_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                shares REAL NOT NULL,
                cost_price REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, stock_code)
            );
            """
        )
        try:
            from fundamentals import ensure_fundamentals_tables

            ensure_fundamentals_tables(path)
        except Exception:
            pass
        try:
            from portfolio_engine import PortfolioEngine

            PortfolioEngine(path)
        except Exception:
            pass
        try:
            from ai_trader import _load_size_mult

            _load_size_mult(path)
        except Exception:
            pass
        try:
            normalize_quote_hygiene(path)
        except Exception:
            pass


def normalize_quote_hygiene(db_path: str) -> Dict[str, int]:
    """本機已做過、補進程式：日期改 YYYYMMDD；量=0 時用成交金額／收盤估張數。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_quotes'")
    if not cur.fetchone():
        conn.close()
        return {"date_fixed": 0, "volume_filled": 0}
    cur.execute(
        """
        UPDATE daily_quotes
        SET date = replace(date, '-', '')
        WHERE length(date) = 10 AND instr(date, '-') > 0
          AND NOT EXISTS (
              SELECT 1 FROM daily_quotes AS other
              WHERE other.stock_id = daily_quotes.stock_id
                AND other.date = replace(daily_quotes.date, '-', '')
          );
        """
    )
    date_fixed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    cur.execute("DELETE FROM daily_quotes WHERE length(date) = 10 AND instr(date, '-') > 0;")
    cur.execute(
        """
        UPDATE daily_quotes
        SET volume = CAST(turnover_k / close AS INTEGER)
        WHERE (volume IS NULL OR volume = 0) AND close > 0 AND turnover_k > 0;
        """
    )
    volume_filled = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    conn.close()
    return {"date_fixed": int(date_fixed), "volume_filled": int(volume_filled)}


def get_user_watchlist(db_path: str, user_id: str) -> List[Dict[str, Any]]:
    ensure_core_schema(db_path)
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT stock_code, stock_name FROM user_watchlist WHERE user_id = ? ORDER BY stock_code;",
            (str(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def lookup_stocks(db_path: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """用代號或中文名（如南亞、山太士）查標的；興櫃也查名稱目錄。"""
    ensure_core_schema(db_path)
    q = (query or "").strip()
    if not q:
        return []
    with get_db_connection(db_path) as conn:
        latest = conn.execute("SELECT MAX(date) FROM daily_quotes;").fetchone()[0]
        rows = []
        if latest and q.isdigit() and 3 <= len(q) <= 6:
            rows = conn.execute(
                """SELECT stock_id, stock_name, close, pct_change FROM daily_quotes
                   WHERE date=? AND stock_id=? LIMIT 1;""",
                (latest, q),
            ).fetchall()
        elif latest:
            rows = conn.execute(
                """SELECT stock_id, stock_name, close, pct_change FROM daily_quotes
                   WHERE date=? AND stock_name LIKE ?
                   ORDER BY volume DESC LIMIT ?;""",
                (latest, f"%{q}%", int(limit)),
            ).fetchall()
        hits = [dict(r) for r in rows]
        if hits:
            return hits
    ensure_stock_directory(db_path)
    with get_db_connection(db_path) as conn:
        latest = conn.execute("SELECT MAX(date) FROM daily_quotes;").fetchone()[0]
        if q.isdigit() and 3 <= len(q) <= 6:
            drows = conn.execute(
                "SELECT stock_id, stock_name, market FROM stock_directory WHERE stock_id=? LIMIT 1;",
                (q,),
            ).fetchall()
        else:
            drows = conn.execute(
                """SELECT stock_id, stock_name, market FROM stock_directory
                   WHERE stock_name LIKE ? ORDER BY stock_id LIMIT ?;""",
                (f"%{q}%", int(limit)),
            ).fetchall()
        out = []
        for r in drows:
            item = dict(r)
            quote = None
            if latest:
                quote = conn.execute(
                    """SELECT close, pct_change FROM daily_quotes
                       WHERE stock_id=? ORDER BY date DESC LIMIT 1;""",
                    (item["stock_id"],),
                ).fetchone()
            if quote:
                item["close"] = quote["close"]
                item["pct_change"] = quote["pct_change"]
            else:
                item["close"] = None
                item["pct_change"] = None
            out.append(item)
        return out


def ensure_stock_directory(db_path: str) -> None:
    """名稱目錄：日K裡有的＋興櫃 ISIN，讓山太士這種興櫃打得到。"""
    with get_db_connection(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS stock_directory (
                stock_id TEXT PRIMARY KEY,
                stock_name TEXT NOT NULL,
                market TEXT DEFAULT ''
            );"""
        )
        conn.execute(
            """INSERT OR REPLACE INTO stock_directory (stock_id, stock_name, market)
               SELECT stock_id, stock_name, market FROM daily_quotes
               WHERE date = (SELECT MAX(date) FROM daily_quotes);"""
        )
        n_em = conn.execute(
            "SELECT COUNT(*) FROM stock_directory WHERE market='EM';"
        ).fetchone()[0]
    if n_em >= 20:
        return
    try:
        from universe import fetch_isin_universe

        items = fetch_isin_universe()
        with get_db_connection(db_path) as conn:
            for u in items:
                conn.execute(
                    """INSERT INTO stock_directory (stock_id, stock_name, market)
                       VALUES (?, ?, ?)
                       ON CONFLICT(stock_id) DO UPDATE SET
                         stock_name=excluded.stock_name,
                         market=CASE WHEN stock_directory.market='' THEN excluded.market
                                     ELSE stock_directory.market END;""",
                    (u["stock_id"], u["stock_name"], u.get("market_type") or ""),
                )
    except Exception:
        pass
    # 興櫃常見漏網：ISIN 解析失敗時仍能打到名稱
    with get_db_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO stock_directory (stock_id, stock_name, market)
               VALUES ('3595', '山太士', 'EM');"""
        )


def add_to_watchlist(db_path: str, user_id: str, stock_code: str, stock_name: str = "") -> None:
    ensure_core_schema(db_path)
    code = str(stock_code).strip()
    name = (stock_name or "").strip()
    if not name or name == code:
        hits = lookup_stocks(db_path, code, limit=1)
        if hits:
            name = hits[0].get("stock_name") or code
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_watchlist (user_id, stock_code, stock_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, stock_code) DO UPDATE SET stock_name=excluded.stock_name;
            """,
            (str(user_id), code, name or code, now),
        )


def get_user_portfolio(db_path: str, user_id: str) -> List[Dict[str, Any]]:
    ensure_core_schema(db_path)
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT stock_code, stock_name, shares, cost_price FROM user_holdings WHERE user_id = ?;",
            (str(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def add_to_portfolio(
    db_path: str, user_id: str, stock_code: str, stock_name: str, shares: float, cost_price: float
) -> None:
    ensure_core_schema(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_holdings (user_id, stock_code, stock_name, shares, cost_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, stock_code) DO UPDATE SET
                shares=user_holdings.shares + excluded.shares,
                cost_price=(
                    (user_holdings.shares * user_holdings.cost_price + excluded.shares * excluded.cost_price)
                    / NULLIF(user_holdings.shares + excluded.shares, 0)
                ),
                stock_name=excluded.stock_name,
                updated_at=excluded.updated_at;
            """,
            (str(user_id), str(stock_code).strip(), stock_name or stock_code, float(shares), float(cost_price), now),
        )


def sell_from_holdings(
    db_path: str, user_id: str, stock_code: str, shares: float, price: float
) -> str:
    """從 user_holdings 賣出（與買入紀錄同一張表）。"""
    ensure_core_schema(db_path)
    code = str(stock_code).strip()
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT shares, cost_price, stock_name FROM user_holdings WHERE user_id=? AND stock_code=?;",
            (str(user_id), code),
        ).fetchone()
        if not row:
            return f"持股裡沒有 {code}"
        held = float(row["shares"] or 0)
        cost = float(row["cost_price"] or 0)
        name = row["stock_name"] or code
        sell_n = held if shares <= 0 or shares >= held else float(shares)
        pnl = (float(price) - cost) * sell_n
        remain = held - sell_n
        now = datetime.now().isoformat(timespec="seconds")
        if remain <= 1e-9:
            conn.execute(
                "DELETE FROM user_holdings WHERE user_id=? AND stock_code=?;",
                (str(user_id), code),
            )
        else:
            conn.execute(
                "UPDATE user_holdings SET shares=?, updated_at=? WHERE user_id=? AND stock_code=?;",
                (remain, now, str(user_id), code),
            )
        return f"已賣出 {code} {name} {sell_n:g}張 @ {price}，估損益 {pnl:+.0f}（成本 {cost}）"


# ==============================================================================
# 靜態股票對照表 (stock_map.json) 快取與注入介面
# ==============================================================================
def inject_stock_map(stock_data: Dict[str, Any]) -> None:
    """
    手動注入股票對照表記憶體快取（支援動態注入、外部設定或單元測試）
    """
    global _STOCK_MAP_CACHE
    with _STOCK_MAP_LOCK:
        _STOCK_MAP_CACHE = stock_data.copy()


def load_stock_map(json_path: str = "stock_map.json", force_reload: bool = False) -> Dict[str, Any]:
    """
    讀取靜態對照表 stock_map.json 並寫入全域記憶體快取
    :param json_path: stock_map.json 檔案路徑
    :param force_reload: 是否強制重新從磁碟讀取
    :return: 股票代號與名稱/詳細資訊對照字典
    """
    global _STOCK_MAP_CACHE
    with _STOCK_MAP_LOCK:
        if _STOCK_MAP_CACHE and not force_reload:
            return _STOCK_MAP_CACHE

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    _STOCK_MAP_CACHE = json.load(f)
            except Exception as e:
                log_system_error(
                    module_name="wayne_db.load_stock_map",
                    error_message=f"讀取 {json_path} 失敗: {str(e)}",
                    stack_trace=traceback.format_exc()
                )
                _STOCK_MAP_CACHE = {}
        else:
            _STOCK_MAP_CACHE = {}
        return _STOCK_MAP_CACHE


def get_stock_name(stock_id: str, default: Optional[str] = None) -> str:
    """
    依股票代號從快取中取得股票名稱，若無則返回預設值或代號本身
    """
    with _STOCK_MAP_LOCK:
        item = _STOCK_MAP_CACHE.get(str(stock_id))
        if isinstance(item, str):
            return item
        elif isinstance(item, dict) and "name" in item:
            return str(item["name"])
        return default if default is not None else str(stock_id)


def get_all_cached_stocks() -> Dict[str, Any]:
    """
    取得目前記憶體中的全量股票對照快取副本
    """
    with _STOCK_MAP_LOCK:
        return _STOCK_MAP_CACHE.copy()


# ==============================================================================
# 業務 CRUD 操作封裝函式
# ==============================================================================

# --- 1. user_states 操作 ---
def upsert_user_state(user_id: str, platform: str, state: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    新增或更新使用者的對話狀態
    """
    now_str = datetime.now().isoformat()
    sql = """
    INSERT INTO user_states (user_id, platform, state, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id, platform) DO UPDATE SET
        state = excluded.state,
        updated_at = excluded.updated_at;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(sql, (str(user_id), platform, state, now_str))


def get_user_state(user_id: str, platform: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    查詢指定使用者在指定平台的對話狀態
    """
    sql = "SELECT user_id, platform, state, updated_at FROM user_states WHERE user_id = ? AND platform = ?;"
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (str(user_id), platform))
        row = cursor.fetchone()
        return dict(row) if row else None


# --- 2. cached_data 操作 ---
def set_cached_data(
    chapter_id: str,
    title: str,
    content: Union[str, Dict, List],
    is_valid: int = 1,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    快取章節或結構化分析內容 (若為 dict/list 則自動轉為 JSON 字串存儲)
    """
    content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
    now_str = datetime.now().isoformat()
    sql = """
    INSERT INTO cached_data (chapter_id, title, content, is_valid, created_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(chapter_id) DO UPDATE SET
        title = excluded.title,
        content = excluded.content,
        is_valid = excluded.is_valid,
        created_at = excluded.created_at;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(sql, (chapter_id, title, content_str, int(is_valid), now_str))


def get_cached_data(chapter_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    取得快取內容，並嘗試反序列化 parsed_content
    """
    sql = "SELECT chapter_id, title, content, is_valid, created_at FROM cached_data WHERE chapter_id = ? AND is_valid = 1;"
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (chapter_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["parsed_content"] = json.loads(res["content"])
        except Exception:
            res["parsed_content"] = res["content"]
        return res


# --- 3. system_logs 操作 ---
def log_system_error(
    module_name: str,
    error_message: str,
    stack_trace: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    記錄系統例外與錯誤日誌
    """
    now_str = datetime.now().isoformat()
    trace = stack_trace if stack_trace else ""
    sql = """
    INSERT INTO system_logs (module_name, error_message, stack_trace, created_at)
    VALUES (?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (module_name, error_message, trace, now_str))
        return int(cursor.lastrowid)


def get_recent_logs(limit: int = 20, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    取得最新的系統錯誤日誌
    """
    sql = "SELECT id, module_name, error_message, stack_trace, created_at FROM system_logs ORDER BY id DESC LIMIT ?;"
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (int(limit),))
        return [dict(row) for row in cursor.fetchall()]


# --- 4. simulated_positions 操作 (AI 模擬持倉) ---
def add_simulated_position(
    stock_id: str,
    entry_date: str,
    buy_price: float,
    quantity: int,
    strategy_factor: str,
    stop_loss_price: float,
    take_profit_price: float,
    status: str = "holding",
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    新增一筆模擬持倉
    """
    now_str = datetime.now().isoformat()
    sql = """
    INSERT INTO simulated_positions (
        stock_id, entry_date, buy_price, quantity,
        strategy_factor, stop_loss_price, take_profit_price,
        status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            sql,
            (
                str(stock_id), entry_date, float(buy_price), int(quantity),
                strategy_factor, float(stop_loss_price), float(take_profit_price),
                status, now_str, now_str
            )
        )
        return int(cursor.lastrowid)


def get_holding_positions(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    取得所有處於 holding (持倉中) 狀態的模擬部位
    """
    sql = """
    SELECT id, stock_id, entry_date, buy_price, quantity,
           strategy_factor, stop_loss_price, take_profit_price,
           status, created_at, updated_at
    FROM simulated_positions
    WHERE status = 'holding'
    ORDER BY entry_date DESC, id DESC;
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql)
        return [dict(row) for row in cursor.fetchall()]


def close_simulated_position(position_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    將模擬持倉狀態更新為 closed (已平倉)
    """
    now_str = datetime.now().isoformat()
    sql = "UPDATE simulated_positions SET status = 'closed', updated_at = ? WHERE id = ?;"
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (now_str, int(position_id)))
        return bool(cursor.rowcount > 0)


# --- 5. trade_history 操作 (覆盤交易表) ---
def record_trade_history(
    stock_id: str,
    buy_date: str,
    sell_date: str,
    buy_price: float,
    sell_price: float,
    return_rate: float,
    exit_reason: str,
    review_analysis: str,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    記錄一筆已平倉的歷史交易覆盤數據
    """
    now_str = datetime.now().isoformat()
    sql = """
    INSERT INTO trade_history (
        stock_id, buy_date, sell_date, buy_price, sell_price,
        return_rate, exit_reason, review_analysis, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            sql,
            (
                str(stock_id), buy_date, sell_date, float(buy_price), float(sell_price),
                float(return_rate), exit_reason, review_analysis, now_str
            )
        )
        return int(cursor.lastrowid)


def get_trade_history(limit: int = 50, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    取得歷史覆盤交易紀錄清單
    """
    sql = """
    SELECT trade_id, stock_id, buy_date, sell_date, buy_price, sell_price,
           return_rate, exit_reason, review_analysis, created_at
    FROM trade_history
    ORDER BY sell_date DESC, trade_id DESC
    LIMIT ?;
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(sql, (int(limit),))
        return [dict(row) for row in cursor.fetchall()]


# ==============================================================================
# Google Colab / 本地獨立驗證腳本
# ==============================================================================
if __name__ == "__main__":
    import concurrent.futures

    # 指定測試資料庫路徑 (支援 Colab /tmp 或本地目錄)
    TEST_DB = "/tmp/wayne_trading_test.db" if os.path.exists("/tmp") else "wayne_trading_test.db"
    
    # 清理舊測試檔
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    for ext in ["-wal", "-shm"]:
        if os.path.exists(TEST_DB + ext):
            os.remove(TEST_DB + ext)

    print("=" * 65)
    print("🚀 [WayneBot Phase 1] 開始執行資料庫與資料結構模組驗證")
    print("=" * 65)

    # 1. 初始化資料庫與資料表建立
    print("\n[Step 1] 初始化資料庫並建立 5 張核心資料表...")
    init_database(TEST_DB)
    print("✅ 資料庫初始化完成，5 張資料表建立成功。")

    # 2. 驗證 SQLite PRAGMA 配置 (WAL 模式)
    print("\n[Step 2] 驗證 SQLite PRAGMA WAL 模式配置...")
    with get_db_connection(TEST_DB) as conn:
        c = conn.cursor()
        c.execute("PRAGMA journal_mode;")
        journal_mode = c.fetchone()[0]
        c.execute("PRAGMA synchronous;")
        sync_mode = c.fetchone()[0]
        print(f"  - journal_mode: {str(journal_mode).upper()} (預期: WAL)")
        print(f"  - synchronous : {sync_mode} (1=NORMAL, 預期: 1)")
        assert str(journal_mode).upper() == "WAL", "WAL 模式配置失敗！"
        assert sync_mode == 1, "Synchronous 模式配置失敗！"
    print("✅ PRAGMA WAL 模式與同步模式驗證通過。")

    # 3. 測試 1: user_states 狀態寫入與更新
    print("\n[Step 3] 測試 user_states 狀態寫入與更新 (Upsert)...")
    upsert_user_state(user_id="U888001", platform="Telegram", state="AWAITING_STOCK_CODE", db_path=TEST_DB)
    state1 = get_user_state(user_id="U888001", platform="Telegram", db_path=TEST_DB)
    print(f"  - 初始寫入狀態: {state1}")
    upsert_user_state(user_id="U888001", platform="Telegram", state="VIEWING_POSITIONS", db_path=TEST_DB)
    state2 = get_user_state(user_id="U888001", platform="Telegram", db_path=TEST_DB)
    print(f"  - 更新後狀態: {state2}")
    assert state2 is not None and state2["state"] == "VIEWING_POSITIONS"
    print("✅ user_states 模組驗證通過。")

    # 4. 測試 2: cached_data 結構化內容快取
    print("\n[Step 4] 測試 cached_data 結構化分析內容快取...")
    sample_analysis = {
        "pattern": "頭肩底頸線突破",
        "resistance": 450.0,
        "support": 412.0,
        "chip_analysis": {"foreign_investor": "連三買", "investment_trust": "買超放大"}
    }
    set_cached_data(
        chapter_id="CHP_2383_20260821",
        title="台光電型態與籌碼分析",
        content=sample_analysis,
        is_valid=1,
        db_path=TEST_DB
    )
    cache_res = get_cached_data("CHP_2383_20260821", db_path=TEST_DB)
    print(f"  - 快取讀取標題: {cache_res['title']}")
    print(f"  - 解析後籌碼指標: {cache_res['parsed_content']['chip_analysis']}")
    assert cache_res["parsed_content"]["resistance"] == 450.0
    print("✅ cached_data 模組驗證通過。")

    # 5. 測試 3: system_logs 異常堆疊記錄
    print("\n[Step 5] 測試 system_logs 系統日誌寫入...")
    try:
        raise ZeroDivisionError("模擬量化指標計算除以零異常")
    except Exception as ex:
        log_id = log_system_error(
            module_name="indicators.kd",
            error_message=str(ex),
            stack_trace=traceback.format_exc(),
            db_path=TEST_DB
        )
        print(f"  - 成功記錄錯誤日誌 ID: {log_id}")
    logs = get_recent_logs(limit=1, db_path=TEST_DB)
    print(f"  - 最新錯誤訊息: {logs[0]['error_message']}")
    assert "除以零" in logs[0]["error_message"]
    print("✅ system_logs 模組驗證通過。")

    # 6. 測試 4: simulated_positions (AI 模擬持倉)
    print("\n[Step 6] 測試 simulated_positions AI 模擬持倉新增與平倉...")
    pos_id = add_simulated_position(
        stock_id="2383",
        entry_date="2026-08-21",
        buy_price=415.5,
        quantity=2,
        strategy_factor="破底翻+頭肩底頸線突破+外資連三買",
        stop_loss_price=398.0,
        take_profit_price=460.0,
        status="holding",
        db_path=TEST_DB
    )
    print(f"  - 新增模擬持倉成功，持倉 ID: {pos_id}")
    holdings = get_holding_positions(db_path=TEST_DB)
    print(f"  - 當前持倉檔數: {len(holdings)}，標的: {holdings[0]['stock_id']}，買進價: {holdings[0]['buy_price']}")
    assert len(holdings) == 1 and holdings[0]["stock_id"] == "2383"
    
    # 模擬平倉更新
    close_success = close_simulated_position(pos_id, db_path=TEST_DB)
    holdings_after = get_holding_positions(db_path=TEST_DB)
    print(f"  - 平倉執行狀態: {close_success}，平倉後持倉檔數: {len(holdings_after)}")
    assert len(holdings_after) == 0
    print("✅ simulated_positions 模組驗證通過。")

    # 7. 測試 5: trade_history (覆盤交易表)
    print("\n[Step 7] 測試 trade_history 覆盤交易寫入與查詢...")
    trade_id = record_trade_history(
        stock_id="2383",
        buy_date="2026-08-10",
        sell_date="2026-08-21",
        buy_price=415.5,
        sell_price=462.0,
        return_rate=11.19,
        exit_reason="觸及波段滿足點停利出場",
        review_analysis="進場時機精準踩在頸線回測確認點，持有期間量能健康放大，紀律停利達成。",
        db_path=TEST_DB
    )
    print(f"  - 覆盤交易紀錄新增成功，Trade ID: {trade_id}")
    trades = get_trade_history(limit=5, db_path=TEST_DB)
    print(f"  - 歷史交易報酬率: {trades[0]['return_rate']}%，出場原因: {trades[0]['exit_reason']}")
    assert trades[0]["return_rate"] == 11.19
    print("✅ trade_history 模組驗證通過。")

    # 8. 測試 6: stock_map 快取與注入介面
    print("\n[Step 8] 測試 stock_map 快取注入與名稱查詢...")
    mock_stock_map = {
        "2330": {"name": "台積電", "market": "上市", "sector": "半導體"},
        "2383": {"name": "台光電", "market": "上市", "sector": "電子零組件"},
        "3035": {"name": "智原", "market": "上市", "sector": "半導體/IP"},
        "2344": "華邦電"
    }
    inject_stock_map(mock_stock_map)
    print(f"  - 查詢 2330 名稱: {get_stock_name('2330')}")
    print(f"  - 查詢 2383 名稱: {get_stock_name('2383')}")
    print(f"  - 查詢 2344 名稱: {get_stock_name('2344')}")
    print(f"  - 查詢 未收錄標的 9999: {get_stock_name('9999')}")
    assert get_stock_name("2383") == "台光電"
    assert get_stock_name("2344") == "華邦電"
    assert get_stock_name("9999") == "9999"
    print("✅ stock_map 模組驗證通過。")

    # 9. 測試 7: 多執行緒高併發讀寫測試
    print("\n[Step 9] 執行多執行緒高併發讀寫測試 (模擬 Telegram / LINE 同步併發存取)...")
    def worker_task(thread_id: int):
        log_system_error(f"worker_{thread_id}", f"併發測試訊息 {thread_id}", db_path=TEST_DB)
        upsert_user_state(f"user_{thread_id}", "Telegram", f"STATE_{thread_id}", db_path=TEST_DB)
        get_user_state(f"user_{thread_id}", "Telegram", db_path=TEST_DB)
        get_holding_positions(db_path=TEST_DB)
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker_task, i) for i in range(30)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results) and len(results) == 30
    print("✅ 30 筆併發讀寫任務全部順利完成，無資料庫鎖死 (Lock) 情況。")

    print("\n" + "=" * 65)
    print("🎉 [WayneBot Phase 1] 所有資料庫模組與資料結構測試全部驗證通過！")
    print("=" * 65)
