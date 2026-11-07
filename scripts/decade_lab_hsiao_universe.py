# -*- coding: utf-8 -*-
"""蕭氏實驗室流動股母體（雲端；不上話筒；不寫大檔進正式碟）。

強制納入：
1) 使用者指定：光聖 6442、台光電 2383、台燿 6274、聯亞 3081、群聯 8299
2) 上市「近似前百大權值」：實收資本額／面額 × 最新收盤 ≈ 市值，取前 100
再視需要用流動性補齊到目標檔數。
"""
from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path
from typing import List, Optional, Sequence, Set

import numpy as np
import pandas as pd

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = ROOT / "data" / "wayne_market.db"
LAB_DB = ROOT / "data" / "decade_lab.db"

# 使用者點名必測（名稱→代號）
MUST_INCLUDE = {
    "6442": "光聖",
    "2383": "台光電",
    "6274": "台燿",
    "3081": "聯亞",
    "8299": "群聯",
}

TWSE_COMPANY = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"


def _is_probably_etf(stock_id: str) -> bool:
    s = str(stock_id)
    if len(s) == 4 and s.startswith("00"):
        return True
    if s.startswith(("006", "007", "008", "009", "004")):
        return True
    return False


def _http_json(url: str, timeout: int = 60) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "WayneBot-lab/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_twse_top100_by_approx_mcap(*, latest_closes: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """用 TWSE 實收資本額 + 本機最新收盤估算市值，取上市前 100（排除 ETF）。"""
    rows = _http_json(TWSE_COMPANY)
    comp = pd.DataFrame(rows)
    # 欄位名可能有全形空白
    comp.columns = [str(c).strip() for c in comp.columns]
    code_col = "公司代號" if "公司代號" in comp.columns else comp.columns[1]
    name_col = "公司簡稱" if "公司簡稱" in comp.columns else "公司名稱"
    cap_col = "實收資本額"
    par_col = "普通股每股面額"
    out = pd.DataFrame(
        {
            "stock_id": comp[code_col].astype(str).str.strip(),
            "stock_name": comp[name_col].astype(str).str.strip(),
            "paid_in_capital": pd.to_numeric(comp[cap_col], errors="coerce"),
            "par_raw": comp[par_col].astype(str) if par_col in comp.columns else "10",
        }
    )
    out = out[~out["stock_id"].map(_is_probably_etf)]
    # 面額：常見「新台幣壹拾元」→10；壹元→1
    def _par(x: str) -> float:
        s = str(x)
        if "壹元" in s or "一元" in s or "1元" in s:
            return 1.0
        return 10.0

    out["par"] = out["par_raw"].map(_par)
    out["shares"] = out["paid_in_capital"] / out["par"]

    if latest_closes is None:
        con = sqlite3.connect(MARKET_DB)
        latest_closes = pd.read_sql(
            """
            SELECT stock_id, close FROM daily_quotes
            WHERE date = (SELECT MAX(date) FROM daily_quotes)
            """,
            con,
        )
        con.close()
    latest_closes["stock_id"] = latest_closes["stock_id"].astype(str)
    m = out.merge(latest_closes, on="stock_id", how="inner")
    m["close"] = pd.to_numeric(m["close"], errors="coerce")
    m["approx_mcap"] = m["shares"] * m["close"]
    m = m.dropna(subset=["approx_mcap"]).sort_values("approx_mcap", ascending=False)
    top = m.head(100).reset_index(drop=True)
    top["source"] = "twse_paid_in_x_close_top100"
    return top


def select_g_universe(
    *,
    n: int = 100,
    min_bars: int = 200,
    min_avg_turnover_k: float = 1_500_000.0,
    min_avg_close: float = 10.0,
    markets: Sequence[str] = ("TW", "TWO"),
    must_include: Optional[Sequence[str]] = None,
    include_twse_top100: bool = True,
) -> pd.DataFrame:
    """母體＝必測檔 ∪ 上市近似前百大權值 ∪ 流動性補齊。"""
    must = list(must_include) if must_include is not None else list(MUST_INCLUDE.keys())
    con = sqlite3.connect(MARKET_DB)
    dir_df = pd.read_sql("SELECT stock_id, stock_name, market FROM stock_directory", con)
    # 流動用 turnover_k（volume×close 在部分檔位單位不一致，不准當主篩）
    liq = pd.read_sql(
        """
        SELECT stock_id,
               COUNT(*) AS n_bars,
               MIN(date) AS d0,
               MAX(date) AS d1,
               AVG(volume) AS avg_vol,
               AVG(close) AS avg_close,
               AVG(turnover_k) AS avg_turnover_k
        FROM daily_quotes
        GROUP BY stock_id
        """,
        con,
    )
    latest = pd.read_sql(
        "SELECT stock_id, close FROM daily_quotes WHERE date=(SELECT MAX(date) FROM daily_quotes)",
        con,
    )
    con.close()

    base = liq.merge(dir_df, on="stock_id", how="left")
    base["stock_id"] = base["stock_id"].astype(str)

    forced: Set[str] = set(str(x) for x in must)
    top100_ids: List[str] = []
    top100_meta = pd.DataFrame()
    if include_twse_top100:
        try:
            top100_meta = fetch_twse_top100_by_approx_mcap(latest_closes=latest)
            top100_ids = top100_meta["stock_id"].astype(str).tolist()
            forced.update(top100_ids)
        except Exception as e:
            top100_meta = pd.DataFrame({"error": [str(e)]})

    # 先放強制檔（有行情才留）
    have = set(base["stock_id"])
    forced_have = [s for s in forced if s in have]
    forced_missing = sorted(forced - have)

    rows = base[base["stock_id"].isin(forced_have)].copy()
    rows["forced"] = True
    rows["in_twse_top100_approx"] = rows["stock_id"].isin(top100_ids)
    rows["must_named"] = rows["stock_id"].isin(MUST_INCLUDE)

    # 流動性補齊到 n（含上櫃，因台燿／聯亞／群聯在 TWO）
    need = max(0, int(n) - len(rows))
    if need > 0:
        pool = base[
            base["market"].isin(list(markets))
            & (~base["stock_id"].isin(rows["stock_id"]))
            & (~base["stock_id"].map(_is_probably_etf))
            & (base["n_bars"] >= min_bars)
            & (base["avg_close"] >= min_avg_close)
            & (base["avg_turnover_k"] >= min_avg_turnover_k)
        ].sort_values(["avg_turnover_k", "n_bars"], ascending=False)
        extra = pool.head(need).copy()
        extra["forced"] = False
        extra["in_twse_top100_approx"] = extra["stock_id"].isin(top100_ids)
        extra["must_named"] = False
        rows = pd.concat([rows, extra], ignore_index=True)

    # 若前百大＋必測已超過 n，仍全部保留（使用者要求百大與點名檔都要）
    rows = rows.drop_duplicates(subset=["stock_id"]).reset_index(drop=True)
    rows.attrs["phone_sync"] = PHONE_SYNC
    rows.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
    rows.attrs["forced_missing"] = forced_missing
    rows.attrs["twse_top100_n"] = len(top100_ids)
    rows.attrs["must_include"] = MUST_INCLUDE
    return rows


def _finalize_ohlcv(df: pd.DataFrame, *, source: str, adj_kind: str = "") -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["Close"])
    out.attrs["phone_sync"] = PHONE_SYNC
    out.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
    out.attrs["source"] = source
    out.attrs["adj_kind"] = adj_kind
    if len(out):
        d0 = pd.Timestamp(out.index[0]).strftime("%Y%m%d")
        d1 = pd.Timestamp(out.index[-1]).strftime("%Y%m%d")
        out.attrs["span"] = {"d0": d0, "d1": d1, "n": int(len(out))}
        try:
            out.attrs["years"] = (pd.Timestamp(out.index[-1]) - pd.Timestamp(out.index[0])).days / 365.25
        except Exception:
            out.attrs["years"] = float("nan")
    return out


def load_stock_ohlcv(stock_id: str, *, prefer_longest: bool = True) -> pd.DataFrame:
    """讀個股日 K。

    prefer_longest=True（實驗室預設）：官方 daily_quotes 與 lab_daily（yahoo_adjclose）
    取實際較長的那條；來源寫進 attrs，不准冒充官方。不足 20 年就用該檔最長真史。
    """
    sid = str(stock_id)
    con = sqlite3.connect(MARKET_DB)
    off = pd.read_sql(
        """
        SELECT date, open, high, low, close, volume
        FROM daily_quotes WHERE stock_id=? ORDER BY date
        """,
        con,
        params=(sid,),
    )
    con.close()
    off_df = _finalize_ohlcv(off, source="daily_quotes_official", adj_kind="raw_quote")

    lab_df = pd.DataFrame()
    if prefer_longest and LAB_DB.exists():
        con = sqlite3.connect(LAB_DB)
        # 優先還原列（長波）；若無則 raw
        lab = pd.read_sql(
            """
            SELECT date, open, high, low, close, volume, adj_kind, source
            FROM lab_daily
            WHERE symbol=? AND adj_kind='yahoo_adjclose'
              AND IFNULL(pack,'') NOT LIKE '%suspicious%'
            ORDER BY date
            """,
            con,
            params=(sid,),
        )
        if lab is None or len(lab) == 0:
            lab = pd.read_sql(
                """
                SELECT date, open, high, low, close, volume, adj_kind, source
                FROM lab_daily
                WHERE symbol=? AND adj_kind='raw_quote'
                  AND IFNULL(pack,'') NOT LIKE '%suspicious%'
                ORDER BY date
                """,
                con,
                params=(sid,),
            )
        con.close()
        if lab is not None and len(lab) > 0:
            kind = str(lab["adj_kind"].iloc[0] if "adj_kind" in lab.columns else "")
            src = str(lab["source"].iloc[0] if "source" in lab.columns else "yahoo_lab")
            lab_df = _finalize_ohlcv(
                lab[["date", "open", "high", "low", "close", "volume"]],
                source=f"lab_daily:{src}",
                adj_kind=kind,
            )

    if not prefer_longest:
        return off_df
    # 取較長真史；平手優先官方
    n_off = len(off_df)
    n_lab = len(lab_df)
    if n_lab > n_off:
        return lab_df
    return off_df


def load_2330_deep() -> pd.DataFrame:
    con = sqlite3.connect(LAB_DB)
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume, adj_close FROM lab_daily WHERE symbol='2330' ORDER BY date",
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "adj_close": "Adj Close",
        }
    )
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["Close"])


def load_twii() -> pd.DataFrame:
    con = sqlite3.connect(MARKET_DB)
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume FROM index_daily WHERE symbol='TWII' ORDER BY date",
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = df["volume"].fillna(0.0)
    if df["open"].isna().mean() > 0.3:
        df["open"] = df["open"].fillna(df["close"])
        df["high"] = df["high"].fillna(df[["open", "close"]].max(axis=1))
        df["low"] = df["low"].fillna(df[["open", "close"]].min(axis=1))
    df = df.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    )
    return df.dropna(subset=["Close"])


__all__ = [
    "MUST_INCLUDE",
    "select_g_universe",
    "fetch_twse_top100_by_approx_mcap",
    "load_stock_ohlcv",
    "load_2330_deep",
    "load_twii",
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
]
