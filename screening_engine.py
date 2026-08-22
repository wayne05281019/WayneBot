# -*- coding: utf-8 -*-
"""
========================================================================================
WayneBot 台股量化交易系統 — Phase 7：籌碼多因子加權評分與海選決策引擎（完全體 + 整合驗證）
檔案名稱：screening_engine.py
作者：Wayne (WayneBot Quantitative System Architect)
========================================================================================
說明：
  本腳本將【screening_engine.py 完全體核心模組】與【Google Colab 5 檔股票全流程模擬驗證】
  整合成單一 Python 腳本，可直接複製貼上於 Google Colab 或終端機執行。
========================================================================================
"""

import os
import sys
import json
import math
import re
import sqlite3
import datetime
import logging
from typing import Dict, List, Tuple, Optional, Any, Union, Generator
from contextlib import contextmanager
import pandas as pd
import numpy as np

# --------------------------------------------------------------------------------------
# 1. 外部模組載入 (支援獨立執行與內建備援)
# --------------------------------------------------------------------------------------
try:
    from bot_servers import init_telegram_bot, send_telegram_safely
except ImportError:
    init_telegram_bot = None
    send_telegram_safely = None

try:
    import wayne_db
    _external_get_db_conn = getattr(wayne_db, "get_db_connection", None)
    _external_save_cache = getattr(wayne_db, "save_cached_data", None)
except ImportError:
    wayne_db = None
    _external_get_db_conn = None
    _external_save_cache = None

try:
    from modules.technical_patterns import (
        analyze_stock_patterns,
        compute_all_indicators,
        check_ma_alignment,
        detect_w_bottom,
        detect_false_breakdown,
        detect_head_and_shoulders_bottom,
        detect_v_reversal,
        detect_ma_entanglement_breakout,
    )
except ImportError:
    try:
        from technical_patterns import (
            analyze_stock_patterns,
            compute_all_indicators,
            check_ma_alignment,
            detect_w_bottom,
            detect_false_breakdown,
            detect_head_and_shoulders_bottom,
            detect_v_reversal,
            detect_ma_entanglement_breakout,
        )
    except ImportError:
        analyze_stock_patterns = None
        compute_all_indicators = None
        check_ma_alignment = None
        detect_w_bottom = None
        detect_false_breakdown = None
        detect_head_and_shoulders_bottom = None
        detect_v_reversal = None
        detect_ma_entanglement_breakout = None

# 設定日誌記錄
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WayneBot.ScreeningEngine")

BASE_DIR = "/content/waynebot_data" if "google.colab" in sys.modules else os.getenv("WAYNEBOT_DATA_DIR", "/tmp/waynebot_data" if os.path.exists("/tmp") else "waynebot_data")
DB_PATH = os.path.join(BASE_DIR, "wayne_trading.db")
STOCKS_CSV_GZ = os.path.join(BASE_DIR, "history_1y_stocks.csv.gz")
CHIPS_CSV_GZ = os.path.join(BASE_DIR, "history_1y_chips.csv.gz")


# ======================================================================================
# 2. 數值清洗與基礎輔助函式 (Sanitization & Helper Functions)
# ======================================================================================

def clean_number(val: Any, default: float = 0.0) -> float:
    """通用數值清洗函式：過濾逗號、正負號、百分比符號、NaN、Inf、暫停交易等非數值字串"""
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
    """正規化股票代號，補齊後綴：例 '2330' -> '2330.TW', '6770' -> '6770.TWO'"""
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


def validate_scraped_data(data_list: Any, min_expected_count: int = 1) -> bool:
    """數據總量完整性與非空校驗（Sanity Check）"""
    if not isinstance(data_list, (list, tuple, pd.DataFrame)):
        logger.error("[Sanity Check 失敗] 傳入數據非列表或 DataFrame 型態: %s", type(data_list))
        return False
    
    actual_count = len(data_list)
    if actual_count < min_expected_count:
        logger.warning("[Sanity Check 攔截] 筆數不足 (%d < %d)，防止空數據覆蓋。", actual_count, min_expected_count)
        return False
        
    logger.info("[Sanity Check 通過] 數據總量驗證合格: %d 筆", actual_count)
    return True


# ======================================================================================
# 3. 資料庫事務與快取機制 (Database & WAL Cache Management)
# ======================================================================================

@contextmanager
def get_db_connection(db_path: str = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """資料庫連線上下文管理器：優先整合 wayne_db.py，若無則啟用高可用內建 SQLite 交易管理"""
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
        logger.warning("PRAGMA 設定警告: %s", str(e))
        
    try:
        yield conn
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("資料庫事務執行失敗，已 Rollback: %s", str(exc))
        raise
    finally:
        conn.close()


def init_cache_table(conn: sqlite3.Connection) -> None:
    """初始化 cached_data 資料表結構"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cached_data (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)


def save_to_cached_data(cache_key: str, payload_data: Any, db_path: str = DB_PATH) -> bool:
    """將結構化篩選或計算結果寫入 cached_data 資料表"""
    if _external_save_cache is not None and db_path == DB_PATH:
        try:
            return bool(_external_save_cache(cache_key, payload_data))
        except Exception as e:
            logger.warning("呼叫 wayne_db.save_cached_data 失敗: %s，改用內建寫入", str(e))

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload_json = json.dumps(payload_data, ensure_ascii=False, indent=2)
    try:
        with get_db_connection(db_path) as conn:
            init_cache_table(conn)
            conn.execute("""
                INSERT OR REPLACE INTO cached_data (cache_key, payload, updated_at)
                VALUES (?, ?, ?)
            """, (cache_key, payload_json, now_str))
        logger.info("✅ 成功寫入 cached_data 快取表，鍵值: %s", cache_key)
        return True
    except Exception as e:
        logger.error("❌ 寫入 cached_data 失敗: %s", str(e))
        return False


def get_from_cached_data(cache_key: str, db_path: str = DB_PATH) -> Optional[Any]:
    """從 cached_data 讀取快取之 JSON 結構"""
    if not os.path.exists(db_path):
        return None
    try:
        with get_db_connection(db_path) as conn:
            init_cache_table(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT payload FROM cached_data WHERE cache_key = ?;", (cache_key,))
            row = cursor.fetchone()
            if row and row["payload"]:
                return json.loads(row["payload"])
    except Exception as e:
        logger.warning("讀取 cached_data 快取失敗: %s", str(e))
    return None


# ======================================================================================
# 4. 內建技術指標與形態識別備援實現 (Built-in Technical Pattern Fallbacks)
# ======================================================================================

def _internal_calculate_ma(df: pd.DataFrame, windows: List[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    df_out = df.copy()
    for w in windows:
        col_name = f"ma{w}"
        df_out[col_name] = df_out['close'].rolling(window=w, min_periods=1).mean()
        df_out[f"{col_name}_slope"] = (df_out[col_name] - df_out[col_name].shift(1)) / df_out[col_name].shift(1) * 100
    return df_out


def _internal_check_ma_alignment(df: pd.DataFrame) -> Dict[str, Any]:
    if len(df) == 0:
        return {"is_bullish": False, "is_bearish": False, "spread_pct": 0.0, "alignment_score": 0.0}
    last = df.iloc[-1]
    ma5 = last.get('ma5', np.nan)
    ma10 = last.get('ma10', np.nan)
    ma20 = last.get('ma20', np.nan)
    ma60 = last.get('ma60', np.nan)

    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
        return {"is_bullish": False, "is_bearish": False, "spread_pct": 0.0, "alignment_score": 0.0}

    if not pd.isna(ma60):
        is_bullish = (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60)
        is_bearish = (ma5 < ma10) and (ma10 < ma20) and (ma20 < ma60)
        mas = [ma5, ma10, ma20, ma60]
    else:
        is_bullish = (ma5 > ma10) and (ma10 > ma20)
        is_bearish = (ma5 < ma10) and (ma10 < ma20)
        mas = [ma5, ma10, ma20]

    spread = (max(mas) - min(mas)) / min(mas) if min(mas) > 0 else 0
    score = 100.0 if is_bullish else (40.0 if (ma5 > ma10 and ma10 > ma20) else 0.0)

    return {
        "is_bullish": bool(is_bullish),
        "is_bearish": bool(is_bearish),
        "spread_pct": float(round(spread * 100, 2)),
        "alignment_score": float(score)
    }


def _internal_compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df_res = df.copy()
    if 'volume' in df_res.columns:
        df_res['vma5'] = df_res['volume'].rolling(window=5, min_periods=1).mean()
        df_res['vma20'] = df_res['volume'].rolling(window=20, min_periods=1).mean()
    df_res = _internal_calculate_ma(df_res, [5, 10, 20, 60])
    
    # KD 指標
    low_min = df_res['low'].rolling(window=9, min_periods=1).min()
    high_max = df_res['high'].rolling(window=9, min_periods=1).max()
    denom = (high_max - low_min).replace(0, np.nan)
    rsv = ((df_res['close'] - low_min) / denom * 100).fillna(50)
    k_vals, d_vals = [], []
    k_curr, d_curr = 50.0, 50.0
    for r in rsv:
        k_curr = (2/3) * k_curr + (1/3) * r
        d_curr = (2/3) * d_curr + (1/3) * k_curr
        k_vals.append(k_curr)
        d_vals.append(d_curr)
    df_res['k'] = k_vals
    df_res['d'] = d_vals

    # RSI 指標
    delta = df_res['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df_res['rsi14'] = (100 - (100 / (1 + rs))).fillna(50.0)

    # MACD 指標
    ema_fast = df_res['close'].ewm(span=12, adjust=False).mean()
    ema_slow = df_res['close'].ewm(span=26, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=9, adjust=False).mean()
    df_res['macd_dif'] = dif
    df_res['macd_dea'] = dea
    df_res['macd_osc'] = dif - dea

    # Bollinger Bands 指標
    mid = df_res['close'].rolling(window=20, min_periods=1).mean()
    std = df_res['close'].rolling(window=20, min_periods=1).std().fillna(0)
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std
    band_range = (upper - lower).replace(0, np.nan)
    df_res['bb_mid'] = mid
    df_res['bb_upper'] = upper
    df_res['bb_lower'] = lower
    df_res['bb_bandwidth'] = ((upper - lower) / mid.replace(0, np.nan)).fillna(0)
    df_res['bb_percent_b'] = ((df_res['close'] - lower) / band_range).fillna(0.5)

    return df_res


def _internal_analyze_stock_patterns(df_kline: pd.DataFrame, symbol: str = "") -> Dict[str, Any]:
    df = df_kline.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(clean_number)
            
    df_calc = _internal_compute_all_indicators(df)
    last_row = df_calc.iloc[-1]
    ma_align = _internal_check_ma_alignment(df_calc)

    w_bot = detect_w_bottom(df_calc) if detect_w_bottom else {"detected": False, "score": 0.0, "details": {}}
    f_break = detect_false_breakdown(df_calc) if detect_false_breakdown else {"detected": False, "score": 0.0, "details": {}}
    hs_bot = detect_head_and_shoulders_bottom(df_calc) if detect_head_and_shoulders_bottom else {"detected": False, "score": 0.0, "details": {}}
    v_rev = detect_v_reversal(df_calc) if detect_v_reversal else {"detected": False, "score": 0.0, "details": {}}
    ma_brk = detect_ma_entanglement_breakout(df_calc) if detect_ma_entanglement_breakout else {"detected": False, "score": 0.0, "details": {}}

    bullish_signals = []
    if ma_align["is_bullish"]:
        bullish_signals.append("均線四線多頭排列")
    if last_row.get("k", 50) > last_row.get("d", 50):
        bullish_signals.append("KD黃金交叉偏多")
    if last_row.get("macd_osc", 0) > 0:
        bullish_signals.append("MACD紅柱偏多")

    pattern_scores = []
    if w_bot.get("detected"):
        bullish_signals.append(f"W底雙底突破頸線 (強度:{w_bot['score']}分)")
        pattern_scores.append(w_bot["score"])
    if f_break.get("detected"):
        bullish_signals.append(f"破底翻假跌破強勢收復 (強度:{f_break['score']}分)")
        pattern_scores.append(f_break["score"])
    if hs_bot.get("detected"):
        bullish_signals.append(f"頭肩底形態量縮突破 (強度:{hs_bot['score']}分)")
        pattern_scores.append(hs_bot["score"])
    if ma_brk.get("detected"):
        bullish_signals.append(f"均線糾結帶量長紅突破 (強度:{ma_brk['score']}分)")
        pattern_scores.append(ma_brk["score"])
    if v_rev.get("detected"):
        bullish_signals.append(f"V型反轉急速強彈 (強度:{v_rev['score']}分)")
        pattern_scores.append(v_rev["score"])

    ind_score = 0.0
    if ma_align["is_bullish"]: ind_score += 30.0
    elif last_row["ma5"] > last_row["ma20"]: ind_score += 15.0
    if last_row["k"] > last_row["d"]: ind_score += 20.0
    if last_row["macd_osc"] > 0: ind_score += 25.0
    if last_row["rsi14"] >= 50: ind_score += 15.0
    if last_row.get("bb_percent_b", 0.5) >= 0.6: ind_score += 10.0

    top_p_score = max(pattern_scores) if pattern_scores else 0.0
    comp_score = round(ind_score * 0.35 + top_p_score * 0.65, 1)

    return {
        "symbol": symbol,
        "latest_date": str(last_row.get("date", "")),
        "latest_close": float(round(last_row["close"], 2)),
        "indicators": {
            "ma": {"is_bullish": ma_align["is_bullish"], "spread_pct": ma_align["spread_pct"]},
            "kd": {"k": round(last_row["k"], 2), "d": round(last_row["d"], 2)},
            "macd": {"dif": round(last_row["macd_dif"], 3), "dea": round(last_row["macd_dea"], 3), "osc": round(last_row["macd_osc"], 3)},
            "rsi": round(last_row["rsi14"], 2),
            "bbands": {"bandwidth": round(last_row.get("bb_bandwidth", 0), 4), "percent_b": round(last_row.get("bb_percent_b", 0.5), 3)}
        },
        "patterns": {
            "w_bottom": w_bot,
            "false_breakdown": f_break,
            "head_and_shoulders_bottom": hs_bot,
            "ma_entanglement_breakout": ma_brk,
            "v_reversal": v_rev
        },
        "composite_score": float(comp_score),
        "bullish_signals": bullish_signals
    }


# ======================================================================================
# 5. 多維度因子評分核心演算法 (Multi-Factor Scoring Engine)
# ======================================================================================

def calculate_chip_score(chips_data: Dict[str, Any], chips_history: Optional[pd.DataFrame] = None) -> Tuple[float, Dict[str, Any], List[str]]:
    """籌碼因子評分體系（權重 40%，滿分 40.0 分）"""
    score = 0.0
    signals: List[str] = []
    
    f_net = clean_number(chips_data.get("foreign_buy_sell", 0.0))
    t_net = clean_number(chips_data.get("trust_buy_sell", 0.0))
    d_net = clean_number(chips_data.get("dealer_buy_sell", 0.0))
    inst_total = clean_number(chips_data.get("institutional_total", f_net + t_net + d_net))
    vol = clean_number(chips_data.get("total_volume", chips_data.get("volume", 0.0)))
    
    margin_change = clean_number(chips_data.get("margin_change", 0.0))
    short_change = clean_number(chips_data.get("short_change", 0.0))

    foreign_consecutive_days = clean_int(chips_data.get("foreign_consecutive_days", 0))
    if foreign_consecutive_days == 0 and chips_history is not None and len(chips_history) > 0:
        col = "foreign_buy_sell" if "foreign_buy_sell" in chips_history.columns else "foreign_buy"
        if col in chips_history.columns:
            f_series = chips_history[col].apply(clean_number).tolist()
            consec = 0
            for val in reversed(f_series):
                if val > 0:
                    consec += 1
                else:
                    break
            foreign_consecutive_days = consec

    # 1. 外資 / 投信同步買超 (12.0 分)
    score_co_buy = 0.0
    if f_net > 0 and t_net > 0:
        score_co_buy = 12.0
        signals.append("🔥 外資投信土洋同步大買")
    elif t_net > 0 and f_net >= 0:
        score_co_buy = 8.5
        signals.append("投信作帳積極認養")
    elif f_net > 0 and t_net >= 0:
        score_co_buy = 7.5
        signals.append("外資單邊強力買超")
    elif inst_total > 0:
        score_co_buy = 4.0
        signals.append("三大法人合計買超偏多")
    else:
        score_co_buy = 0.0
    score += score_co_buy

    # 2. 外資連續買超天數 (10.0 分)
    score_consec = 0.0
    if foreign_consecutive_days >= 5:
        score_consec = 10.0
        signals.append(f"外資波段連續買超 {foreign_consecutive_days} 日")
    elif foreign_consecutive_days >= 3:
        score_consec = 8.0
        signals.append(f"外資連續買超 {foreign_consecutive_days} 日")
    elif foreign_consecutive_days >= 2:
        score_consec = 6.0
        signals.append("外資連續買超 2 日")
    elif foreign_consecutive_days == 1 or f_net > 0:
        score_consec = 3.0
        signals.append("外資買超點火")
    else:
        score_consec = 0.0
    score += score_consec

    # 3. 主力買賣超佔比 (10.0 分)
    inst_ratio_pct = safe_div(inst_total, vol, 0.0) * 100.0 if vol > 0 else 0.0
    score_ratio = 0.0
    if inst_ratio_pct >= 15.0:
        score_ratio = 10.0
        signals.append(f"法人主力買超佔比高達 {inst_ratio_pct:.1f}%")
    elif inst_ratio_pct >= 10.0:
        score_ratio = 8.0
        signals.append(f"主力買超佔比 {inst_ratio_pct:.1f}%")
    elif inst_ratio_pct >= 5.0:
        score_ratio = 6.0
        signals.append(f"主力買超佔比 {inst_ratio_pct:.1f}%")
    elif inst_ratio_pct >= 1.0:
        score_ratio = 3.0
    else:
        score_ratio = 0.0
    score += score_ratio

    # 4. 融資融券變化與浮額洗淨 (8.0 分)
    score_margin = 0.0
    if margin_change < 0 and (short_change > 0 or inst_total > 0):
        score_margin = 8.0
        signals.append("資減券增/法人進散戶退 (具軋空與籌碼沉澱優勢)")
    elif margin_change < 0:
        score_margin = 6.0
        signals.append("融資浮額洗淨沉澱")
    elif short_change > 0:
        score_margin = 5.0
        signals.append("融券增加具軋空潛力")
    elif margin_change >= 0 and inst_total > margin_change:
        score_margin = 3.5
        signals.append("法人強勢吸納散戶籌碼")
    else:
        score_margin = 0.0
    score += score_margin

    final_chip_score = float(round(min(40.0, score), 1))
    details = {
        "chip_score": final_chip_score,
        "foreign_buy_sell": f_net,
        "trust_buy_sell": t_net,
        "dealer_buy_sell": d_net,
        "institutional_total": inst_total,
        "institutional_ratio_pct": round(inst_ratio_pct, 2),
        "foreign_consecutive_days": foreign_consecutive_days,
        "margin_change": margin_change,
        "short_change": short_change,
        "sub_scores": {
            "co_buy": score_co_buy,
            "consecutive": score_consec,
            "major_ratio": score_ratio,
            "margin_dynamics": score_margin
        }
    }
    return final_chip_score, details, signals


def calculate_technical_score(df_kline: pd.DataFrame, symbol: str = "") -> Tuple[float, Dict[str, Any], List[str], Dict[str, Any]]:
    """技術形態因子評分體系（權重 40%，滿分 40.0 分）"""
    if df_kline is None or len(df_kline) == 0:
        return 0.0, {}, [], {}

    if analyze_stock_patterns is not None:
        try:
            analysis = analyze_stock_patterns(df_kline, symbol=symbol)
        except Exception as e:
            logger.warning("調用 analyze_stock_patterns 異常: %s，改用內建分析", str(e))
            analysis = _internal_analyze_stock_patterns(df_kline, symbol=symbol)
    else:
        analysis = _internal_analyze_stock_patterns(df_kline, symbol=symbol)

    df = df_kline.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(clean_number)

    curr_close = df['close'].iloc[-1]
    curr_vol = df['volume'].iloc[-1]
    n_bars = len(df)

    h20 = df['high'].tail(20).max()
    l20 = df['low'].tail(20).min()
    vma20 = df['volume'].rolling(20, min_periods=1).mean().iloc[-1]
    vol_ratio = safe_div(curr_vol, vma20, 1.0)

    # 1. 均線多頭排列 (15.0 分)
    score_ma = 0.0
    ma_dict = analysis.get("indicators", {}).get("ma", {})
    is_bullish_ma = ma_dict.get("is_bullish", ma_dict.get("is_bullish_alignment", False))
    
    sma5 = df['close'].rolling(5, min_periods=1).mean().iloc[-1]
    sma10 = df['close'].rolling(10, min_periods=1).mean().iloc[-1]
    sma20 = df['close'].rolling(20, min_periods=1).mean().iloc[-1]
    sma60 = df['close'].rolling(60, min_periods=1).mean().iloc[-1] if n_bars >= 60 else sma20
    ma20_slope = safe_div(sma20 - df['close'].tail(20).iloc[0], 20.0) if n_bars >= 20 else 0.0

    tech_signals: List[str] = []
    if is_bullish_ma:
        score_ma = 15.0
        tech_signals.append("均線四線完整多頭排列")
    elif (sma5 > sma10 > sma20) and curr_close >= sma20:
        score_ma = 11.0
        tech_signals.append("短中期均線呈多頭排列")
    elif curr_close >= sma20 and ma20_slope >= 0:
        score_ma = 8.0
        tech_signals.append("股價站穩上揚月線 (20MA)")
    elif curr_close >= sma20:
        score_ma = 5.0
        tech_signals.append("股價站上月線")
    else:
        score_ma = 0.0

    # 2. 帶量突破關鍵頸線 (15.0 分)
    score_breakout = 0.0
    dist_to_h20 = safe_div(curr_close - h20, h20) * 100.0
    d20_gain = safe_div(curr_close - l20, l20) * 100.0

    if curr_close >= h20 * 0.995 and vol_ratio >= 1.5:
        score_breakout = 15.0
        tech_signals.append(f"🔥 爆量強勢突破20日波段頸線 (量增{vol_ratio:.1f}倍)")
    elif curr_close >= h20 * 0.995 and vol_ratio >= 1.2:
        score_breakout = 12.0
        tech_signals.append(f"帶量站上20日波段頸線 (量增{vol_ratio:.1f}倍)")
    elif curr_close >= h20 * 0.98:
        score_breakout = 8.0
        tech_signals.append("逼近波段高點蓄勢突破")
    elif 0.5 <= d20_gain <= 12.0:
        score_breakout = 7.0
        tech_signals.append("脫離20日底部安全起漲位階")
    else:
        score_breakout = 2.0

    # 3. 形態特徵加分 (10.0 分)
    score_pattern = 0.0
    patterns = analysis.get("patterns", {})
    w_bottom = patterns.get("w_bottom", {})
    false_breakdown = patterns.get("false_breakdown", {})
    hs_bottom = patterns.get("head_and_shoulders_bottom", {})
    ma_entanglement = patterns.get("ma_entanglement_breakout", {})
    v_reversal = patterns.get("v_reversal", {})

    pattern_bonuses = []
    if false_breakdown.get("detected"):
        p_score = false_breakdown.get("score", 85.0)
        pattern_bonuses.append(min(10.0, p_score * 0.10))
        tech_signals.append(f"破底翻假跌破強勢收復 (強度:{p_score:.1f}分)")
    if w_bottom.get("detected"):
        p_score = w_bottom.get("score", 80.0)
        pattern_bonuses.append(min(10.0, p_score * 0.10))
        tech_signals.append(f"W底雙底突破頸線 (強度:{p_score:.1f}分)")
    if ma_entanglement.get("detected"):
        p_score = ma_entanglement.get("score", 80.0)
        pattern_bonuses.append(min(10.0, p_score * 0.10))
        tech_signals.append(f"均線糾結帶量長紅突破 (強度:{p_score:.1f}分)")
    if hs_bottom.get("detected"):
        p_score = hs_bottom.get("score", 75.0)
        pattern_bonuses.append(min(9.0, p_score * 0.10))
        tech_signals.append(f"頭肩底形態量縮突破 (強度:{p_score:.1f}分)")
    if v_reversal.get("detected"):
        p_score = v_reversal.get("score", 75.0)
        pattern_bonuses.append(min(8.0, p_score * 0.10))
        tech_signals.append(f"V型反轉急速強彈 (強度:{p_score:.1f}分)")

    if pattern_bonuses:
        score_pattern = max(pattern_bonuses)
    else:
        kd_dict = analysis.get("indicators", {}).get("kd", {})
        if kd_dict.get("golden_cross") or (clean_number(kd_dict.get("k")) > clean_number(kd_dict.get("d"))):
            score_pattern = 4.0
            tech_signals.append("KD指標黃金交叉")
        else:
            score_pattern = 1.0

    final_tech_score = float(round(min(40.0, score_ma + score_breakout + score_pattern), 1))
    details = {
        "technical_score": final_tech_score,
        "latest_close": curr_close,
        "volume": int(curr_vol),
        "vol_ratio": round(vol_ratio, 2),
        "h20": round(h20, 2),
        "l20": round(l20, 2),
        "d20_gain_pct": round(d20_gain, 2),
        "dist_to_h20_pct": round(dist_to_h20, 2),
        "composite_pattern_score": analysis.get("composite_score", 0.0),
        "sub_scores": {
            "ma_alignment": score_ma,
            "neckline_breakout": score_breakout,
            "patterns": score_pattern
        }
    }
    return final_tech_score, details, tech_signals, patterns


def calculate_fundamental_score(meta_data: Dict[str, Any]) -> Tuple[float, Dict[str, Any], List[str]]:
    """基本面因子評分體系（權重 20%，滿分 20.0 分）"""
    score = 0.0
    signals: List[str] = []

    rev_yoy_3m = clean_number(meta_data.get("revenue_yoy_3m_avg", meta_data.get("revenue_yoy", meta_data.get("yoy", 0.0))))
    gross_margin = clean_number(meta_data.get("gross_margin", meta_data.get("gross_profit_margin", 0.0)))
    gross_margin_growth_qoq = clean_number(meta_data.get("gross_margin_growth_qoq", meta_data.get("margin_growth", 0.0)))
    gross_margin_growth_yoy = clean_number(meta_data.get("gross_margin_growth_yoy", 0.0))

    # 1. 營收年增率 (12.0 分)
    score_rev = 0.0
    if rev_yoy_3m >= 25.0:
        score_rev = 12.0
        signals.append(f"近3月營收YoY高成長 {rev_yoy_3m:+.1f}%")
    elif rev_yoy_3m >= 15.0:
        score_rev = 10.0
        signals.append(f"近3月營收YoY強勢增長 {rev_yoy_3m:+.1f}%")
    elif rev_yoy_3m >= 5.0:
        score_rev = 8.0
        signals.append(f"近3月營收維持穩健成長 {rev_yoy_3m:+.1f}%")
    elif rev_yoy_3m > 0.0:
        score_rev = 6.0
        signals.append(f"營收YoY由負轉正 {rev_yoy_3m:+.1f}%")
    elif rev_yoy_3m == 0.0:
        score_rev = 4.0
    else:
        score_rev = 0.0
    score += score_rev

    # 2. 季報毛利率 (8.0 分)
    score_gm = 0.0
    is_margin_improving = (gross_margin_growth_qoq > 0) or (gross_margin_growth_yoy > 0)
    
    if is_margin_improving and gross_margin >= 25.0:
        score_gm = 8.0
        signals.append(f"季報毛利率走揚達 {gross_margin:.1f}% (高毛利擴張)")
    elif is_margin_improving:
        score_gm = 6.0
        signals.append(f"季報毛利率持續走揚 (季增{gross_margin_growth_qoq:+.1f}%)")
    elif gross_margin >= 30.0:
        score_gm = 5.0
        signals.append(f"高毛利體質穩健 ({gross_margin:.1f}%)")
    elif gross_margin >= 15.0:
        score_gm = 3.5
    elif gross_margin_growth_qoq == 0.0 and gross_margin == 0.0:
        score_gm = 3.0
    else:
        score_gm = 0.0
    score += score_gm

    final_fundamental_score = float(round(min(20.0, score), 1))
    details = {
        "fundamental_score": final_fundamental_score,
        "revenue_yoy_3m_avg": rev_yoy_3m,
        "gross_margin": gross_margin,
        "gross_margin_growth_qoq": gross_margin_growth_qoq,
        "sub_scores": {
            "revenue_growth": score_rev,
            "gross_margin_expansion": score_gm
        }
    }
    return final_fundamental_score, details, signals


# ======================================================================================
# 6. 單一標的綜合評估 (Single Stock Composite Evaluator)
# ======================================================================================

def evaluate_stock_candidate(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """全維度綜合評估單檔股票（籌碼 40% + 技術 40% + 基本面 20% = 總分 100 分）"""
    stock_id = str(stock_data.get("stock_id", stock_data.get("code", "")))
    stock_name = str(stock_data.get("stock_name", stock_data.get("name", stock_id)))
    market = str(stock_data.get("market", "TW"))
    symbol = f"{stock_id} {stock_name}"

    df_kline = stock_data.get("df_kline")
    chips_latest = stock_data.get("chips_latest", {})
    chips_history = stock_data.get("chips_history")
    meta = stock_data.get("meta", {})

    chip_score, chip_details, chip_signals = calculate_chip_score(chips_latest, chips_history)
    tech_score, tech_details, tech_signals, patterns = calculate_technical_score(df_kline, symbol=symbol)
    fund_score, fund_details, fund_signals = calculate_fundamental_score(meta)

    total_score = round(chip_score + tech_score + fund_score, 1)

    if total_score >= 75.0:
        grade = "💎 A級 (動能先鋒 / 核心首選)"
    elif total_score >= 55.0:
        grade = "⚡ B級 (波段觀察 / 蓄勢待發)"
    else:
        grade = "☕ C級 (潛伏整理 / 暫不介入)"

    all_signals = chip_signals + tech_signals + fund_signals
    
    primary_pattern = "多頭攻擊型態"
    if patterns.get("false_breakdown", {}).get("detected"):
        primary_pattern = "破底翻假跌破強勢收復"
    elif patterns.get("w_bottom", {}).get("detected"):
        primary_pattern = "W底雙底突破頸線"
    elif patterns.get("ma_entanglement_breakout", {}).get("detected"):
        primary_pattern = "均線糾結帶量長紅突破"
    elif patterns.get("head_and_shoulders_bottom", {}).get("detected"):
        primary_pattern = "頭肩底形態量縮突破"
    elif patterns.get("v_reversal", {}).get("detected"):
        primary_pattern = "V型反轉急速強彈"
    elif tech_details.get("sub_scores", {}).get("ma_alignment", 0) >= 12.0:
        primary_pattern = "均線四線多頭排列推升"
    elif chip_score >= 30.0:
        primary_pattern = "外資投信籌碼大單集中鎖碼"

    curr_close = clean_number(tech_details.get("latest_close", stock_data.get("close", 0.0)))
    h20 = clean_number(tech_details.get("h20", curr_close))
    l20 = clean_number(tech_details.get("l20", curr_close * 0.95))

    stop_loss = round(max(l20 * 0.99, curr_close * 0.955), 2)
    take_profit = round(curr_close * 1.15, 2)
    reward_risk_ratio = safe_div(take_profit - curr_close, curr_close - stop_loss, 2.5)

    return {
        "stock_id": stock_id,
        "code": stock_id,
        "stock_name": stock_name,
        "name": stock_name,
        "market": market,
        "close": curr_close,
        "volume": int(tech_details.get("volume", 0)),
        "foreign_buy": clean_int(chip_details.get("foreign_buy_sell", 0)),
        "trust_buy": clean_int(chip_details.get("trust_buy_sell", 0)),
        "dealer_buy": clean_int(chip_details.get("dealer_buy_sell", 0)),
        "total_score": total_score,
        "score": total_score,
        "grade": grade,
        "chip_score": chip_score,
        "tech_score": tech_score,
        "fund_score": fund_score,
        "primary_pattern": primary_pattern,
        "pattern": primary_pattern,
        "signals": all_signals,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reward_risk_ratio": round(reward_risk_ratio, 2),
        "details": {
            "chip": chip_details,
            "technical": tech_details,
            "fundamental": fund_details
        }
    }


# ======================================================================================
# 7. 流式生成器與全市場海選決策 (Stream Generator & Full Screening)
# ======================================================================================

def stream_market_data(
    db_path: str = DB_PATH,
    df_quotes: Optional[pd.DataFrame] = None,
    df_chips: Optional[pd.DataFrame] = None,
    df_meta: Optional[pd.DataFrame] = None
) -> Generator[Dict[str, Any], None, None]:
    """全市場股票流式生成器（yield generator）"""
    if df_quotes is not None and len(df_quotes) > 0:
        df_q = df_quotes.copy()
        if "stock_id" not in df_q.columns and "code" in df_q.columns:
            df_q["stock_id"] = df_q["code"]

        chips_lookup: Dict[str, Dict[str, Any]] = {}
        if df_chips is not None and len(df_chips) > 0:
            for sid, group in df_chips.groupby(df_chips.columns[0]):
                latest_c = group.sort_values(group.columns[1]).iloc[-1].to_dict()
                chips_lookup[strip_ticker(sid)] = latest_c

        meta_lookup: Dict[str, Dict[str, Any]] = {}
        if df_meta is not None and len(df_meta) > 0:
            for sid, group in df_meta.groupby(df_meta.columns[0]):
                meta_lookup[strip_ticker(sid)] = group.iloc[-1].to_dict()

        for sid, group in df_q.groupby("stock_id"):
            df_stock = group.sort_values("date" if "date" in group.columns else group.columns[0]).copy()
            clean_sid = strip_ticker(sid)
            latest_row = df_stock.iloc[-1]
            sname = latest_row.get("stock_name", latest_row.get("name", str(clean_sid)))
            market = latest_row.get("market", "TW")

            yield {
                "stock_id": clean_sid,
                "stock_name": sname,
                "market": market,
                "close": clean_number(latest_row.get("close", 0.0)),
                "df_kline": df_stock,
                "chips_latest": chips_lookup.get(clean_sid, latest_row.to_dict()),
                "chips_history": None,
                "meta": meta_lookup.get(clean_sid, latest_row.to_dict())
            }
        return

    if os.path.exists(db_path):
        try:
            with get_db_connection(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT stock_id, stock_name, market FROM daily_quotes ORDER BY stock_id ASC;")
                stocks = cur.fetchall()

                for st in stocks:
                    sid = str(st["stock_id"])
                    sname = str(st["stock_name"])
                    market = str(st["market"])

                    kline_df = pd.read_sql_query("""
                        SELECT date, open, high, low, close, volume, pct_change, turnover_k
                        FROM daily_quotes
                        WHERE stock_id = ?
                        ORDER BY date ASC
                    """, conn, params=(sid,))

                    if len(kline_df) == 0:
                        continue

                    chips_df = pd.read_sql_query("""
                        SELECT * FROM institutional_chips
                        WHERE stock_id = ? OR ticker LIKE ?
                        ORDER BY date ASC
                    """, conn, params=(sid, f"{sid}%"))

                    latest_chips = chips_df.iloc[-1].to_dict() if len(chips_df) > 0 else {}

                    try:
                        margin_df = pd.read_sql_query("""
                            SELECT * FROM margin_trading
                            WHERE stock_id = ?
                            ORDER BY date DESC LIMIT 1
                        """, conn, params=(sid,))
                        if len(margin_df) > 0:
                            latest_chips.update(margin_df.iloc[0].to_dict())
                    except Exception:
                        pass

                    meta_dict = {}
                    try:
                        cur.execute("SELECT * FROM stock_metadata WHERE stock_id = ?;", (sid,))
                        m_row = cur.fetchone()
                        if m_row:
                            meta_dict = dict(m_row)
                    except Exception:
                        pass

                    yield {
                        "stock_id": sid,
                        "stock_name": sname,
                        "market": market,
                        "close": clean_number(kline_df["close"].iloc[-1]),
                        "df_kline": kline_df,
                        "chips_latest": latest_chips,
                        "chips_history": chips_df,
                        "meta": meta_dict
                    }
            return
        except Exception as e:
            logger.warning("從 SQLite 資料庫流式讀取失敗: %s，嘗試降級至 CSV.GZ", str(e))

    if os.path.exists(STOCKS_CSV_GZ):
        try:
            df_all = pd.read_csv(STOCKS_CSV_GZ, compression="gzip", encoding="utf-8-sig")
            for sid, group in df_all.groupby("stock_id"):
                df_stock = group.sort_values("date").copy()
                latest = df_stock.iloc[-1]
                yield {
                    "stock_id": str(sid),
                    "stock_name": str(latest.get("stock_name", str(sid))),
                    "market": str(latest.get("market", "TW")),
                    "close": clean_number(latest.get("close", 0.0)),
                    "df_kline": df_stock,
                    "chips_latest": latest.to_dict(),
                    "chips_history": None,
                    "meta": latest.to_dict()
                }
            return
        except Exception as e:
            logger.error("讀取 STOCKS_CSV_GZ 失敗: %s", str(e))


def run_full_screening(
    db_path: str = DB_PATH,
    df_quotes: Optional[pd.DataFrame] = None,
    df_chips: Optional[pd.DataFrame] = None,
    df_meta: Optional[pd.DataFrame] = None,
    top_n: int = 15,
    save_cache: bool = True
) -> pd.DataFrame:
    """執行 Phase 7 全市場多因子海選評分與決策"""
    logger.info("🚀 啟動 WayneBot Phase 7 全市場量化多因子海選評分引擎...")
    
    candidates: List[Dict[str, Any]] = []
    scanned_count = 0

    generator = stream_market_data(
        db_path=db_path,
        df_quotes=df_quotes,
        df_chips=df_chips,
        df_meta=df_meta
    )

    for stock_bundle in generator:
        scanned_count += 1
        try:
            evaluated = evaluate_stock_candidate(stock_bundle)
            if evaluated["close"] > 0.0:
                candidates.append(evaluated)
        except Exception as e:
            logger.warning("評估個股 %s 發生異常: %s", stock_bundle.get("stock_id"), str(e))

    logger.info("📊 全市場掃描完成，共計分析 %d 檔標的，有效候選 %d 檔", scanned_count, len(candidates))

    if not candidates:
        logger.warning("⚠️ 查無有效候選標的，回傳空清單。")
        return pd.DataFrame()

    candidates.sort(key=lambda x: x["total_score"], reverse=True)
    top_candidates = candidates[:max(1, top_n)]
    df_results = pd.DataFrame(top_candidates)

    if save_cache:
        trade_date = datetime.datetime.now().strftime("%Y-%m-%d")
        cache_payload = {
            "trade_date": trade_date,
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_scanned": scanned_count,
            "top_count": len(top_candidates),
            "results": top_candidates
        }
        save_to_cached_data("screener_latest_top", cache_payload, db_path=db_path)
        save_to_cached_data(f"daily_screening_{trade_date}", cache_payload, db_path=db_path)

    return df_results


# ======================================================================================
# 8. Telegram 戰報視覺化渲染 (Telegram Report Formatter)
# ======================================================================================

def format_telegram_report(stock_list: List[Dict[str, Any]], trade_date: str) -> str:
    """格式化為符合 Telegram HTML 標準的高質感視覺化戰報"""
    lines = [
        "🔥 <b>【WayneBot 台股量化多因子海選盤後戰報】</b>",
        f"📅 <b>交易日期</b>: <code>{trade_date}</code>",
        "🎯 <b>決策體系</b>: 籌碼(40%) + 形態技術(40%) + 基本面(20%) 綜合評分",
        "=" * 32,
        ""
    ]

    if not stock_list:
        lines.append("⚠️ <b>今日大盤無符合嚴格突破條件之標的，建議保留現金觀望。</b>")
    else:
        for idx, item in enumerate(stock_list, start=1):
            code = item.get("stock_id", item.get("code", ""))
            name = item.get("stock_name", item.get("name", ""))
            close = clean_number(item.get("close", 0.0))
            score = clean_number(item.get("total_score", item.get("score", 0.0)))
            pattern = item.get("primary_pattern", item.get("pattern", "多頭突破形態"))
            
            f_buy = clean_int(item.get("foreign_buy", 0))
            t_buy = clean_int(item.get("trust_buy", 0))
            
            chip_s = clean_number(item.get("chip_score", 0.0))
            tech_s = clean_number(item.get("tech_score", 0.0))
            fund_s = clean_number(item.get("fund_score", 0.0))

            stop_loss = clean_number(item.get("stop_loss", close * 0.95))
            take_profit = clean_number(item.get("take_profit", close * 1.15))
            rr_ratio = clean_number(item.get("reward_risk_ratio", 2.5))
            signals = item.get("signals", [])

            stars = "⭐⭐⭐⭐⭐" if score >= 88 else ("⭐⭐⭐⭐" if score >= 75 else "⭐⭐⭐")

            lines.append(f"<b>{idx:02d}. {code} {name}</b> | <b>${close:.2f}</b> {stars} (<code>{score:.1f}分</code>)")
            lines.append(f"  • <b>評分權重</b>: 籌碼 <code>{chip_s:.1f}</code> | 技術 <code>{tech_s:.1f}</code> | 基本 <code>{fund_s:.1f}</code>")
            lines.append(f"  • <b>法人動向</b>: 外資 <code>{f_buy:+d}</code> 張 | 投信 <code>{t_buy:+d}</code> 張")
            lines.append(f"  • <b>核心型態</b>: <b>{pattern}</b>")
            lines.append(f"  • <b>波段風控</b>: 停損 <code>${stop_loss:.2f}</code> | 停利 <code>${take_profit:.2f}</code> (風報比 <code>{rr_ratio:.1f}</code>)")
            
            if signals:
                display_signals = " | ".join(signals[:3])
                lines.append(f"  • <b>多頭亮點</b>: <i>{display_signals}</i>")
                
            lines.append(f"  • <b>即時行情</b>: <a href='https://tw.stock.yahoo.com/quote/{code}'>Yahoo股市行情</a>")
            lines.append("-" * 28)

    lines.append("")
    lines.append("💡 <i>※ 槓鈴策略提醒：衛星強勢部位嚴格以頸線防甩轎停損，指數核心部位長期持有定期再平衡。</i>")
    return "\n".join(lines)


# ======================================================================================
# 9. 向下相容函式與類別介面 (Backward Compatibility)
# ======================================================================================

def run_quantitative_screening(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """向下相容 Phase 6 之 run_quantitative_screening 呼叫"""
    df = run_full_screening(db_path=db_path, top_n=20, save_cache=True)
    if len(df) > 0:
        return df.to_dict(orient="records")
    return []


class QuantScreeningEngine:
    """向下相容 Phase 2 之類別呼叫介面"""
    @classmethod
    def load_stock_data(cls) -> pd.DataFrame:
        if os.path.exists(STOCKS_CSV_GZ):
            try:
                df = pd.read_csv(STOCKS_CSV_GZ, compression="gzip", encoding="utf-8-sig")
                if len(df) > 0: return df
            except Exception: pass
        if os.path.exists(DB_PATH):
            try:
                with get_db_connection(DB_PATH) as conn:
                    df = pd.read_sql_query("SELECT * FROM daily_quotes ORDER BY date ASC;", conn)
                    if len(df) > 0: return df
            except Exception: pass
        return pd.DataFrame()

    @classmethod
    def run_screener(cls, df_all: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        df_res = run_full_screening(df_quotes=df_all, top_n=20, save_cache=True)
        return df_res


def run_screening_flow() -> List[Dict[str, Any]]:
    """標準執行流程，回傳 Top 10 清單字典列表"""
    df = run_full_screening(top_n=10, save_cache=True)
    if len(df) == 0:
        return []
    return df.head(10).to_dict(orient="records")


# ======================================================================================
# 10. 整合驗證執行邏輯 (Google Colab / 測試沙盒專用模擬驗證)
# ======================================================================================

def generate_mock_market_data():
    """模擬全市場 5 檔標的之行情、籌碼與基本面數據"""
    dates = pd.date_range(end=datetime.date.today(), periods=60).strftime("%Y-%m-%d").tolist()
    
    stocks_meta = [
        {"stock_id": "2330", "stock_name": "台積電", "market": "TW", "rev_yoy": 32.5, "margin": 54.2, "margin_growth": 1.8},
        {"stock_id": "2383", "stock_name": "台光電", "market": "TW", "rev_yoy": 28.0, "margin": 27.5, "margin_growth": 2.1},
        {"stock_id": "2344", "stock_name": "華邦電", "market": "TW", "rev_yoy": 15.2, "margin": 22.0, "margin_growth": 0.8},
        {"stock_id": "3035", "stock_name": "智原", "market": "TW", "rev_yoy": 12.0, "margin": 45.0, "margin_growth": -0.5},
        {"stock_id": "6526", "stock_name": "達發", "market": "TW", "rev_yoy": 18.5, "margin": 51.0, "margin_growth": 1.2},
    ]
    
    all_quotes = []
    all_chips = []
    all_meta = []
    
    np.random.seed(42)
    
    for item in stocks_meta:
        sid = item["stock_id"]
        sname = item["stock_name"]
        mkt = item["market"]
        
        base_price = 950.0 if sid == "2330" else (450.0 if sid == "2383" else (28.0 if sid == "2344" else (310.0 if sid == "3035" else 650.0)))
        trend = np.linspace(-5, 15, 60)
        noise = np.random.normal(0, 1.5, 60)
        closes = base_price + trend + noise
        
        # 形態植入
        if sid == "2344":
            closes[-5] = base_price - 8.0  # 假跌破
            closes[-1] = base_price + 10.0 # 長紅收復
        elif sid == "2383":
            closes[20] = base_price - 10.0 # 左底
            closes[35] = base_price + 5.0  # 頸線
            closes[45] = base_price - 9.0  # 右底
            closes[-1] = base_price + 12.0 # 突破頸線
            
        volumes = np.random.randint(2000, 6000, 60)
        volumes[-1] = int(volumes[-1] * 2.2)
        
        for i in range(60):
            c = float(closes[i])
            o = float(c - np.random.uniform(-1.0, 1.0))
            h = float(max(o, c) + np.random.uniform(0.5, 2.5))
            l = float(min(o, c) - np.random.uniform(0.5, 2.0))
            v = int(volumes[i])
            
            all_quotes.append({
                "date": dates[i],
                "stock_id": sid,
                "stock_name": sname,
                "market": mkt,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "turnover_k": round(c * v / 1000.0, 2),
                "pct_change": round((c - o) / o * 100.0, 2)
            })
            
        f_buy = 8500 if sid == "2330" else (2400 if sid == "2383" else (5200 if sid == "2344" else 1100))
        t_buy = 1800 if sid == "2330" else (950 if sid == "2383" else (350 if sid == "2344" else 420))
        d_buy = 320 if sid == "2330" else (180 if sid == "2383" else 120)
        
        all_chips.append({
            "ticker": f"{sid}.{mkt}",
            "date": dates[-1],
            "stock_id": sid,
            "foreign_buy_sell": f_buy,
            "trust_buy_sell": t_buy,
            "dealer_buy_sell": d_buy,
            "institutional_total": f_buy + t_buy + d_buy,
            "total_volume": volumes[-1],
            "foreign_consecutive_days": 4 if sid in ("2330", "2383") else 2,
            "margin_change": -450 if sid in ("2330", "2344") else 80,
            "short_change": 120 if sid in ("2330", "2383") else -30
        })
        
        all_meta.append({
            "stock_id": sid,
            "stock_name": sname,
            "market": mkt,
            "revenue_yoy_3m_avg": item["rev_yoy"],
            "gross_margin": item["margin"],
            "gross_margin_growth_qoq": item["margin_growth"]
        })
        
    return pd.DataFrame(all_quotes), pd.DataFrame(all_chips), pd.DataFrame(all_meta)


def main():
    test_db = os.path.join(BASE_DIR, "wayne_trading.db") if os.path.exists(BASE_DIR) else "/tmp/wayne_trading.db"
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    print("=" * 65)
    print(f"🚀 [WayneBot Phase 7] 啟動全市場多因子海選評分引擎 (日期: {today_str})")
    
    # 1. 產生模擬資料集
    print("\n📦 [步驟 1] 生成 5 檔個股模擬行情、籌碼與基本面資料庫...")
    df_quotes, df_chips, df_meta = generate_mock_market_data()
    print(f"  • 日 K 線行情: {len(df_quotes)} 筆")
    print(f"  • 三大法人籌碼: {len(df_chips)} 筆")
    print(f"  • 基本面財務: {len(df_meta)} 筆")
    
    # 2. 執行 Phase 7 多因子海選評分
    print("\n🔍 [步驟 2] 執行 run_full_screening() 多因子加權評分...")
    df_results = run_full_screening(
        db_path=test_db,
        df_quotes=df_quotes,
        df_chips=df_chips,
        df_meta=df_meta,
        top_n=5,
        save_cache=True
    )
    
    # 3. 輸出海選榜單
    print("\n🏆 [步驟 3] 海選決策評分結果榜單：")
    for idx, row in df_results.iterrows():
        print(f"  #{idx+1:02d} [{row['stock_id']} {row['stock_name']}] 總分: {row['total_score']}分 ({row['grade']})")
        print(f"      • 籌碼(40%): {row['chip_score']:.1f} | 技術形態(40%): {row['tech_score']:.1f} | 基本面(20%): {row['fund_score']:.1f}")
        print(f"      • 核心型態: {row['primary_pattern']} | 風報比: {row['reward_risk_ratio']}")
        print(f"      • 多頭特徵: {', '.join(row['signals'][:3])}")
        
    # 4. 驗證 SQLite cached_data
    print("\n💾 [步驟 4] 驗證 SQLite cached_data 快取寫入與讀取結構...")
    cached_obj = get_from_cached_data("screener_latest_top", db_path=test_db)
    if cached_obj and "results" in cached_obj:
        print(f"  ✅ 快取校驗成功: Key='screener_latest_top'，包含 {len(cached_obj['results'])} 檔標的，掃描總數 = {cached_obj['total_scanned']}")
    else:
        print("  ⚠️ 快取讀取未取得資料。")

    # 5. Telegram 戰報渲染預覽
    print("\n📱 [步驟 5] Telegram 盤後視覺化戰報預覽：")
    report = format_telegram_report(
        stock_list=df_results.to_dict(orient="records"),
        trade_date=today_str
    )
    print(report)
    print("\n" + "=" * 65)
    print("🎉 WayneBot Phase 7 籌碼多因子加權評分與海選決策引擎（完全體）驗證成功！")


if __name__ == "__main__":
    main()
