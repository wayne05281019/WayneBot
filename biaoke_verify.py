# -*- coding: utf-8 -*-
"""從第一篇起：用官方加權／台指期日夜盤核對飆大點位與右肩（高過前高低不破前低）。

15 分 K 庫沒有，不數他的 5／9 段。不是買訊。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.BiaokeVerify")

TAIPEI = ZoneInfo("Asia/Taipei")
PIVOT_45839 = 45839.0
PIVOT_YMD = "20260903"
CROSS_46506 = 46506.0
TARGET_48218 = 48218.0

_WATCH_ASK = re.compile(
    r"(46506|45839|48218|右肩|低不破前低|高有過前高|夜盤|"
    r"有守住|守住.{0,8}(45839|低點)|穿越.{0,8}46506)"
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _iso_day(ymd: str) -> str:
    s = _ymd(ymd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else str(ymd or "")


def _px_s(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def taipei_today() -> str:
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def fetch_tx_ohlc(*, night: bool = True, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """期交所即時近月臺指期 OHLC。pytest 不打外網。沒接到就空。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_BIAOKE_LIVE_TEST") != "1":
        return None
    try:
        import requests
        from market_ticker import (
            _TAIFEX_HEADERS,
            _TAIFEX_QUOTE_URL,
            _num_or_none,
            pick_tx_quote_row,
        )
    except Exception:
        return None
    payload = {
        "MarketType": "1" if night else "0",
        "SymbolType": "F",
        "KindID": "1",
        "CID": "",
        "ExpireMonth": "",
        "SymbolID": "",
        "Fcode": "",
    }
    try:
        resp = requests.post(
            _TAIFEX_QUOTE_URL,
            json=payload,
            headers=_TAIFEX_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        rows = ((resp.json() or {}).get("RtData") or {}).get("QuoteList") or []
        row = pick_tx_quote_row(rows, night=night)
    except Exception:
        logger.debug("台指期即時 OHLC 失敗 night=%s", night, exc_info=True)
        return None
    if not row:
        return None
    last = _num_or_none(row.get("CLastPrice"))
    if not last:
        return None
    t = str(row.get("CTime") or "").strip()
    clock = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
    return {
        "date": _ymd(row.get("CDate")),
        "session": "night" if night else "regular",
        "symbol": str(row.get("SymbolID") or ""),
        "open": _num_or_none(row.get("COpenPrice")),
        "high": _num_or_none(row.get("CHighPrice")),
        "low": _num_or_none(row.get("CLowPrice")),
        "close": last,
        "volume": int(_num_or_none(row.get("CTotalVolume")) or 0),
        "pct_change": _num_or_none(row.get("CDiffRate")),
        "update_time": clock,
        "source": "taifex_mis",
        "is_realtime": True,
    }


def _twii_rows(db_path: str, since: str = "20260801") -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    y0 = _ymd(since) or "20260801"
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            "SELECT date, high, low, close FROM index_daily "
            "WHERE symbol='TWII' AND date>=? ORDER BY date",
            (y0,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    out = []
    for d, h, lo, c in rows:
        if h is None or lo is None or c is None:
            continue
        out.append(
            {
                "date": _ymd(d),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
            }
        )
    return out


def _tx_row(db_path: str, ymd: str, session: str) -> Optional[Dict[str, Any]]:
    key = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not key:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        row = conn.execute(
            "SELECT date, open, high, low, close FROM futures_daily "
            "WHERE symbol='TX' AND session=? AND date=?",
            (session, key),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if not row or row[2] is None or row[3] is None or row[4] is None:
        return None
    return {
        "date": str(row[0]),
        "open": float(row[1] or 0),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "session": session,
        "source": "futures_daily",
    }


def refresh_recent_twii(db_path: str, *, range_: str = "1mo") -> int:
    """缺加權日 K 就用 Yahoo 補。失敗不編。pytest 不打外網。"""
    if not db_path or os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    try:
        from taiwan_market import _fetch_index_daily, ensure_index_daily_table
    except Exception:
        return 0
    ensure_index_daily_table(db_path)
    try:
        df = _fetch_index_daily(range_ or "1mo")
    except Exception:
        logger.debug("加權補洞失敗 range=%s", range_, exc_info=True)
        return 0
    if df is None or getattr(df, "empty", True):
        return 0
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for _, r in df.iterrows():
            ymd = _ymd(r.get("date"))
            if not ymd:
                continue
            close = float(r.get("close") or 0)
            if close <= 0:
                continue
            conn.execute(
                """
                INSERT INTO index_daily(date, symbol, close, volume, pct_change, updated_at,
                                        open, high, low)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    close=excluded.close,
                    open=COALESCE(NULLIF(excluded.open, 0), index_daily.open),
                    high=COALESCE(NULLIF(excluded.high, 0), index_daily.high),
                    low=COALESCE(NULLIF(excluded.low, 0), index_daily.low),
                    pct_change=excluded.pct_change,
                    updated_at=excluded.updated_at
                """,
                (
                    ymd,
                    "TWII",
                    close,
                    float(r.get("volume") or 0),
                    float(r.get("pct_change") or 0),
                    datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    float(r.get("open") or close),
                    float(r.get("high") or close),
                    float(r.get("low") or close),
                ),
            )
            n += 1
        conn.commit()
    except sqlite3.Error:
        logger.debug("加權近月寫庫失敗", exc_info=True)
        return 0
    finally:
        conn.close()
    return n


def right_shoulder(
    bars: Sequence[Dict[str, Any]],
    *,
    pivot_ymd: str,
    pivot_low: float,
    lookback: int = 8,
) -> Dict[str, Any]:
    """有守住＝後來高有過前高、低不破這根低。庫沒這天就空。"""
    key = _ymd(pivot_ymd)
    out: Dict[str, Any] = {
        "ok": False,
        "pivot": key,
        "pivot_low": pivot_low,
        "prior_high": None,
        "prior_high_date": "",
        "held": None,
        "passed_prior_high": None,
        "broke_on": "",
        "hh_date": "",
        "hh": None,
        "later_low": None,
        "later_low_date": "",
        "last_date": "",
        "last_close": None,
        "last_high": None,
        "n_later": 0,
    }
    dates = [str(b.get("date") or "") for b in bars]
    try:
        i = dates.index(key)
    except ValueError:
        return out
    prior = list(bars[max(0, i - lookback) : i])
    if not prior:
        return out
    ph = max(prior, key=lambda b: float(b["high"]))
    later = list(bars[i + 1 :])
    broke = [b for b in later if float(b["low"]) < pivot_low]
    hh = [b for b in later if float(b["high"]) > float(ph["high"])]
    nearest = min(later, key=lambda b: float(b["low"])) if later else None
    last = later[-1] if later else None
    out.update(
        {
            "ok": True,
            "prior_high": round(float(ph["high"]), 2),
            "prior_high_date": str(ph["date"]),
            "held": not broke,
            "passed_prior_high": bool(hh),
            "broke_on": str(broke[0]["date"]) if broke else "",
            "hh_date": str(hh[0]["date"]) if hh else "",
            "hh": round(float(hh[0]["high"]), 2) if hh else None,
            "later_low": round(float(nearest["low"]), 2) if nearest else None,
            "later_low_date": str(nearest["date"]) if nearest else "",
            "last_date": str(last["date"]) if last else "",
            "last_close": round(float(last["close"]), 2) if last else None,
            "last_high": round(float(last["high"]), 2) if last else None,
            "n_later": len(later),
        }
    )
    return out


def check_cross(bar: Optional[Dict[str, Any]], level: float) -> Dict[str, Any]:
    out = {"ok": False, "crossed": None, "above_last": None}
    if not bar or bar.get("high") is None:
        return out
    hi = float(bar["high"])
    last = float(bar.get("close") or hi)
    out.update(
        {
            "ok": True,
            "crossed": hi >= level,
            "above_last": last >= level,
            "high": hi,
            "low": float(bar["low"]) if bar.get("low") is not None else None,
            "close": last,
            "open": bar.get("open"),
            "date": str(bar.get("date") or ""),
            "time": str(bar.get("update_time") or ""),
            "source": str(bar.get("source") or ""),
        }
    )
    return out


def watch_sep11(db_path: str = "", *, live_night: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """9/11 兩則：45839 有守、右肩、今晚夜盤穿越 46506。"""
    if db_path and os.path.isfile(db_path):
        try:
            refresh_recent_twii(db_path)
        except Exception:
            logger.debug("補 9/11 加權略過", exc_info=True)
    bars = _twii_rows(db_path, "20260820") if db_path else []
    sh = right_shoulder(bars, pivot_ymd=PIVOT_YMD, pivot_low=PIVOT_45839)
    night = live_night
    if night is None:
        night = fetch_tx_ohlc(night=True)
        if night and db_path:
            store_tx_live(db_path, night)
    if night is None and db_path:
        night = _tx_row(db_path, taipei_today(), "night") or _tx_row(
            db_path, "20260911", "night"
        )
    day = fetch_tx_ohlc(night=False) if live_night is None else None
    if day is None and db_path:
        day = _tx_row(db_path, taipei_today(), "regular") or _tx_row(
            db_path, "20260911", "regular"
        )
    elif day and db_path:
        store_tx_live(db_path, day)
    cross = check_cross(night, CROSS_46506)
    day_vs = check_cross(day, PIVOT_45839) if day else {"ok": False}
    twii_last = bars[-1] if bars else None
    twii_held_today = None
    if twii_last and twii_last["date"] >= PIVOT_YMD:
        twii_held_today = float(twii_last["low"]) >= PIVOT_45839
    return {
        "shoulder": sh,
        "night": night or {},
        "day": day or {},
        "cross_46506": cross,
        "twii_last": twii_last or {},
        "twii_held_today": twii_held_today,
        "tx_day_low_vs_45839": day_vs,
        "note_15m": "庫沒15分K，不數他說的5段／下降軌有沒有破壞。",
    }


def format_watch(db_path: str = "", *, live_night: Optional[Dict[str, Any]] = None) -> str:
    w = watch_sep11(db_path, live_night=live_night)
    sh = w.get("shoulder") or {}
    cross = w.get("cross_46506") or {}
    night = w.get("night") or {}
    tw = w.get("twii_last") or {}
    lines = [
        "他 9/11 08:43：未來 2～3 交易日看 9/3 加權低 45839 有沒有守；"
        "有守＝右肩高有過前高、低不破前低，高檔震盪趨勢向上。",
        "同日 17:49：今晚夜盤至少穿越 46506。15 分 5 段／下降軌庫沒 15 分 K 不數。",
    ]
    if sh.get("ok"):
        bit = (
            f"加權 9/3 低 {PIVOT_45839:.2f}；前高 {sh.get('prior_high_date')} "
            f"{_px_s(sh.get('prior_high'))}。"
        )
        if sh.get("passed_prior_high"):
            bit += f"{sh.get('hh_date')} 高 {_px_s(sh.get('hh'))} 已過前高。"
        else:
            bit += "後來高還沒過前高。"
        if sh.get("held"):
            bit += (
                f"後來最低 {sh.get('later_low_date')} {_px_s(sh.get('later_low'))}，"
                "到目前加權日 K 低不破 45839。"
            )
        else:
            bit += f"{sh.get('broke_on')} 加權日 K 已破 45839。"
        if sh.get("last_date"):
            bit += (
                f"最近一根 {sh.get('last_date')} 收 {_px_s(sh.get('last_close'))} "
                f"高 {_px_s(sh.get('last_high'))}。"
            )
        lines.append(bit)
    elif tw:
        lines.append(
            f"加權最近 {tw.get('date')} 收 {_px_s(tw.get('close'))} "
            f"低 {_px_s(tw.get('low'))}。9/3 那根庫沒對上就不說守住。"
        )
    if w.get("twii_held_today") is True and tw.get("date"):
        lines.append(
            f"{tw.get('date')} 加權低 {_px_s(tw.get('low'))} 仍高於 45839。"
        )
    elif w.get("twii_held_today") is False and tw.get("date"):
        lines.append(
            f"{tw.get('date')} 加權低 {_px_s(tw.get('low'))} 已低於 45839。"
        )
    day = w.get("day") or {}
    if day.get("low") is not None:
        lines.append(
            f"台指期日盤 {day.get('date')} 低 {_px_s(day.get('low'))} 收 {_px_s(day.get('close'))}"
            "（45839 是加權低，不是台指期低；日盤低可能低於 45839，仍以加權判有守）。"
        )
    if cross.get("ok"):
        clock = night.get("update_time") or ""
        src = "即時" if night.get("is_realtime") else "日結"
        bit = (
            f"夜盤{src} {night.get('date') or ''} {clock} "
            f"開 {_px_s(night.get('open'))} 高 {_px_s(cross.get('high'))} "
            f"低 {_px_s(cross.get('low'))} 現 {_px_s(cross.get('close'))}。"
        )
        if cross.get("crossed"):
            bit += "高已穿越 46506。"
        else:
            bit += "高還沒穿越 46506。"
        if cross.get("above_last"):
            bit += "現價仍在 46506 之上。"
        else:
            bit += "現價回到 46506 之下。"
        lines.append(bit)
    else:
        lines.append("今晚夜盤官方即時還沒接到，不猜有沒有穿越 46506。")
    lines.append("不是買訊。")
    return "\n".join(lines)


def format_watch_html(db_path: str = "") -> str:
    raw = format_watch(db_path)
    if not raw:
        return ""
    return "\n".join(html_escape(line) for line in raw.split("\n"))


def is_watch_ask(ask: str) -> bool:
    return bool(_WATCH_ASK.search(ask or ""))


def origin_first_post(db_path: str = "") -> Dict[str, Any]:
    """2023-12-04 智原支撐 370。有官方日 K 才對當日低。"""
    from biaoke_link import bar_on

    out = {
        "date": "2023-12-04",
        "stock_id": "3035",
        "stock_name": "智原",
        "claimed": 370.0,
        "role": "support",
        "text": "智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！",
        "bar": None,
        "held_that_day": None,
    }
    bar = bar_on(db_path, "3035", "20231204") if db_path else None
    if (
        not bar
        and db_path
        and os.path.isfile(db_path)
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        try:
            from biaoke_walk import fetch_stock_month, upsert_fetched_quotes

            rows = fetch_stock_month("3035", "202312", name="智原")
            if rows:
                upsert_fetched_quotes(db_path, rows)
                bar = bar_on(db_path, "3035", "20231204")
        except Exception:
            logger.debug("第一篇智原日K補洞失敗", exc_info=True)
            bar = None
    if bar:
        out["bar"] = bar
        lo = bar.get("low")
        out["held_that_day"] = float(lo) >= 370.0 if lo is not None else None
    return out


def claim_hit_stats(db_path: str) -> Dict[str, Any]:
    """公開文對價表的命中摘要。庫沒日 K 的列不算進命中率。"""
    out = {
        "n": 0,
        "with_bar": 0,
        "target_n": 0,
        "target_hit": 0,
        "support_n": 0,
        "support_hold": 0,
    }
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_claims'"
        ).fetchone()
        if not hit:
            return out
        rows = conn.execute(
            "SELECT role, then_close, hit FROM biaoke_claims WHERE IFNULL(club,0)=0"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out["n"] = len(rows)
    for role, then_close, hit_s in rows:
        if then_close is not None:
            out["with_bar"] += 1
        hs = str(hit_s or "")
        if role == "target":
            if "庫沒這天" in hs:
                continue
            out["target_n"] += 1
            if "碰到" in hs:
                out["target_hit"] += 1
        elif role == "support":
            if "庫沒這天" in hs:
                continue
            out["support_n"] += 1
            if "有守" in hs and "跌破" not in hs.split("；")[-1]:
                out["support_hold"] += 1
            elif "當日低有守" in hs and "後續低跌破" not in hs:
                out["support_hold"] += 1
            elif "後續低有守" in hs:
                out["support_hold"] += 1
    return out


def store_tx_live(db_path: str, bar: Optional[Dict[str, Any]]) -> bool:
    """把期交所即時 OHLC 寫進 futures_daily。pytest 不寫。"""
    if not db_path or not bar or os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    ymd = _ymd(bar.get("date"))
    hi = bar.get("high")
    lo = bar.get("low")
    close = bar.get("close")
    if not ymd or hi is None or lo is None or close is None:
        return False
    try:
        from taiwan_market import ensure_futures_daily_table
    except Exception:
        return False
    ensure_futures_daily_table(db_path)
    session = "night" if str(bar.get("session") or "") in ("night", "1") else "regular"
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date, symbol, session) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                pct_change=excluded.pct_change,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                ymd,
                "TX",
                session,
                str(bar.get("symbol") or ""),
                float(bar.get("open") or close),
                float(hi),
                float(lo),
                float(close),
                None,
                int(bar.get("volume") or 0),
                0,
                float(bar.get("pct_change") or 0),
                str(bar.get("source") or "taifex_mis"),
                datetime.now(TAIPEI).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    except sqlite3.Error:
        logger.debug("台指期即時寫庫失敗", exc_info=True)
        return False
    finally:
        conn.close()
    return True


def format_origin_backtest(db_path: str = "") -> str:
    first = origin_first_post(db_path)
    st = claim_hit_stats(db_path)
    lines = [
        "從 2023-12-04 第一篇起對官方日 K（能對才寫，庫沒就標缺）。"
    ]
    bit = f"第一篇 {first['date']} {first['stock_id']}{first['stock_name']} 支撐{int(first['claimed'])}。"
    bar = first.get("bar") or {}
    if bar:
        bit += (
            f"當日收 {_px_s(bar.get('close'))} 低 {_px_s(bar.get('low'))} "
            + ("當日低有守。" if first.get("held_that_day") else "當日低跌破。")
        )
    else:
        bit += "庫沒 2023-12-04 日 K，不編有沒有守。"
    lines.append(bit)
    if st.get("target_n"):
        lines.append(
            f"公開文有日 K 的目標價 {st['target_n']} 則，後來高碰到 {st['target_hit']}；"
            f"支撐 {st['support_n']} 則，後續有守 {st['support_hold']}。"
        )
    try:
        from biaoke_audit import format_audit, load_audit_runs

        if db_path and load_audit_runs(db_path):
            lines.append(format_audit(db_path).split("\n")[0])
    except Exception:
        pass
    lines.append("附圖只核文內點位對官方 OHLC，不讀 CMoney 圖像素。不是買訊。")
    return "\n".join(lines)
