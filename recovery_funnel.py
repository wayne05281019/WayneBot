# -*- coding: utf-8 -*-
"""復原路漏斗：硬閘少而狠、軟縮可排序、兩欄輸出（真可買／復原觀察）。

進場買訊不改：只認勝率／剛離零／已確認紅箭。不准合成總分榜。
phone 顯示用；非買訊欄必須標清楚。Asia/Taipei desk 單一基準日。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
DAY_TURNOVER_K_MIN = 5000.0  # 與 buy_exclude 同：500 萬
MAX_BUY_OK = 12
MAX_OBSERVE = 24
MAX_SAME_FINE = 2

# 主題 OR：電子供應鏈粗標（細項／產業字串）
_THEME_HINTS = (
    "連接",
    "電子",
    "半導體",
    "光電",
    "電腦",
    "通信",
    "AI",
    "伺服",
    "PCB",
    "被動",
    "機構",
    "電源",
    "散熱",
)


def _ymd(raw: Any) -> str:
    s = str(raw or "").replace("-", "").strip()
    return s[:8] if len(s) >= 8 and s[:8].isdigit() else ""


def _zh(ymd: str) -> str:
    d = _ymd(ymd)
    if len(d) != 8:
        return d or "—"
    return f"{int(d[4:6])}/{int(d[6:8])}"


def _taipei_now(now=None) -> datetime:
    if now is None:
        return datetime.now(TAIPEI)
    if getattr(now, "tzinfo", None) is None:
        return now.replace(tzinfo=TAIPEI)
    return now.astimezone(TAIPEI)


def ensure_recovery_tables(db_path: str) -> None:
    con = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS recovery_runs (
              as_of TEXT PRIMARY KEY,
              regime TEXT,
              ran_at TEXT NOT NULL,
              n_buy INTEGER NOT NULL DEFAULT 0,
              n_observe INTEGER NOT NULL DEFAULT 0,
              notes TEXT,
              payload_json TEXT
            );
            CREATE TABLE IF NOT EXISTS recovery_picks (
              as_of TEXT NOT NULL,
              stock_id TEXT NOT NULL,
              bucket TEXT NOT NULL,
              name TEXT,
              fine TEXT,
              score REAL,
              labels_json TEXT,
              reasons_json TEXT,
              buy_signals_json TEXT,
              PRIMARY KEY (as_of, stock_id, bucket)
            );
            CREATE TABLE IF NOT EXISTS recovery_punish (
              stock_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              start_ymd TEXT,
              end_ymd TEXT,
              title TEXT,
              fetched_at TEXT NOT NULL,
              PRIMARY KEY (stock_id, kind, start_ymd)
            );
            """
        )
        con.commit()
    finally:
        con.close()


def fetch_and_store_punish(db_path: str, *, now=None) -> int:
    """H7：證交所處置公告 → recovery_punish。失敗＝0，不准假名單。"""
    import urllib.request

    ensure_recovery_tables(db_path)
    press = _taipei_now(now)
    end = press.strftime("%Y%m%d")
    start = (press - timedelta(days=45)).strftime("%Y%m%d")
    # RWD 用民國年參數常見；API 也收西元 startDate 時用西元試一次
    url = (
        "https://www.twse.com.tw/rwd/zh/announcement/punish"
        f"?response=json&startDate={start}&endDate={end}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.twse.com.tw/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("recovery H7 punish fetch failed: %s", exc)
        return 0
    if str(raw.get("stat") or "") != "OK":
        return 0
    rows = list(raw.get("data") or [])
    stamp = press.isoformat()
    n = 0
    con = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            sid = re.sub(r"\D", "", str(row[2] or ""))
            if len(sid) != 4:
                continue  # 略過權證等
            period = str(row[6] or "")
            # 115/11/09～115/11/13
            m = re.search(
                r"(\d{2,3})/(\d{1,2})/(\d{1,2}).{0,3}(\d{2,3})/(\d{1,2})/(\d{1,2})",
                period,
            )
            start_ymd = end_ymd = ""
            if m:
                y1, mo1, d1, y2, mo2, d2 = m.groups()
                start_ymd = f"{1911 + int(y1):04d}{int(mo1):02d}{int(d1):02d}"
                end_ymd = f"{1911 + int(y2):04d}{int(mo2):02d}{int(d2):02d}"
            title = str(row[7] or row[5] or "處置")[:120]
            con.execute(
                """
                INSERT OR REPLACE INTO recovery_punish
                (stock_id, kind, start_ymd, end_ymd, title, fetched_at)
                VALUES (?,?,?,?,?,?)
                """,
                (sid, "punish", start_ymd, end_ymd, title, stamp),
            )
            n += 1
        con.commit()
    finally:
        con.close()
    return n


def active_punish_ids(db_path: str, as_of: str) -> Set[str]:
    day = _ymd(as_of)
    if not day:
        return set()
    ensure_recovery_tables(db_path)
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        out: Set[str] = set()
        for sid, start_ymd, end_ymd in con.execute(
            "SELECT stock_id, start_ymd, end_ymd FROM recovery_punish WHERE kind='punish'"
        ):
            s = _ymd(start_ymd)
            e = _ymd(end_ymd)
            if s and e and s <= day <= e:
                out.add(str(sid))
            elif s and not e and s <= day:
                # 缺迄日：公布日起算保守擋 10 日曆日
                try:
                    dt = datetime.strptime(s, "%Y%m%d") + timedelta(days=10)
                    if day <= dt.strftime("%Y%m%d"):
                        out.add(str(sid))
                except Exception:
                    out.add(str(sid))
        return out
    finally:
        con.close()


def _resolve_desk(db_path: str) -> str:
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(db_path) or "")
    except Exception:
        return ""


def _twii_regime(db_path: str, desk: str) -> Tuple[str, Dict[str, Any]]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        row = con.execute(
            """
            SELECT date, open, high, low, close, volume, regime
            FROM index_daily WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')<=?
            ORDER BY date DESC LIMIT 1
            """,
            (desk,),
        ).fetchone()
        if not row:
            return "", {}
        return str(row[6] or ""), {
            "date": _ymd(row[0]),
            "o": row[1],
            "h": row[2],
            "l": row[3],
            "c": row[4],
            "v": row[5],
            "regime": row[6],
        }
    finally:
        con.close()


def _universe_meta(db_path: str) -> Dict[str, Dict[str, str]]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        out: Dict[str, Dict[str, str]] = {}
        for sid, name, mkt, atype, ind in con.execute(
            "SELECT stock_id, stock_name, market_type, asset_type, industry FROM stock_universe"
        ):
            out[str(sid)] = {
                "name": str(name or ""),
                "market": str(mkt or ""),
                "asset_type": str(atype or ""),
                "industry": str(ind or ""),
            }
        return out
    finally:
        con.close()


def _fine_map(db_path: str) -> Dict[str, str]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        return {
            str(sid): str(chain or "")
            for sid, chain in con.execute(
                "SELECT stock_id, chain FROM stock_fine_industry"
            )
        }
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _quote_row(db_path: str, sid: str, desk: str) -> Optional[Dict[str, Any]]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        row = con.execute(
            """
            SELECT date, open, high, low, close, volume, turnover_k, pct_change
            FROM daily_quotes
            WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (sid, desk),
        ).fetchone()
        if not row:
            return None
        return {
            "date": _ymd(row[0]),
            "o": row[1],
            "h": row[2],
            "l": row[3],
            "c": row[4],
            "v": row[5],
            "turnover_k": row[6],
            "pct": row[7],
        }
    finally:
        con.close()


def _recent_quotes(db_path: str, sid: str, desk: str, n: int = 25) -> List[Dict[str, Any]]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        rows = list(
            con.execute(
                """
                SELECT date, close, volume, high, low, turnover_k
                FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                ORDER BY date DESC LIMIT ?
                """,
                (sid, desk, int(n)),
            )
        )
        out = []
        for r in reversed(rows):
            out.append(
                {
                    "date": _ymd(r[0]),
                    "c": float(r[1] or 0),
                    "v": float(r[2] or 0),
                    "h": float(r[3] or 0),
                    "l": float(r[4] or 0),
                    "turnover_k": float(r[5] or 0) if r[5] is not None else None,
                }
            )
        return out
    finally:
        con.close()


def _eps_pack(db_path: str, sid: str) -> Dict[str, Any]:
    """近四季／可算窗 EPS（觀測站累計列經 fundamentals.recent_eps_windows）。

    不准把「最新一列累計」假稱近四季。缺 n=4 就標 ttm=None，不准發明。
    """
    out: Dict[str, Any] = {
        "eps_ttm": None,
        "eps_ttm_n": 0,
        "eps_latest_cum": None,
        "windows": {},
    }
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        rows = [
            {"year": int(y), "season": int(s), "eps": float(e)}
            for y, s, e in con.execute(
                """
                SELECT year, season, eps FROM quarterly_income
                WHERE stock_id=? AND eps IS NOT NULL
                ORDER BY year, season
                """,
                (sid,),
            )
            if e is not None
        ]
    except Exception:
        return out
    finally:
        con.close()
    if not rows:
        return out
    out["eps_latest_cum"] = float(rows[-1]["eps"])
    try:
        from fundamentals import recent_eps_windows

        wins = recent_eps_windows(rows, max_n=4)
    except Exception:
        wins = {}
    out["windows"] = {
        int(k): float(v.get("eps_sum"))
        for k, v in (wins or {}).items()
        if v and v.get("eps_sum") is not None
    }
    if 4 in out["windows"]:
        out["eps_ttm"] = out["windows"][4]
        out["eps_ttm_n"] = 4
    return out


def _eps_ytd(db_path: str, sid: str) -> Optional[float]:
    """相容舊呼叫：優先近四季合計；否則 None（不准退回誤用累計列當正 EPS）。"""
    pack = _eps_pack(db_path, sid)
    ttm = pack.get("eps_ttm")
    return float(ttm) if ttm is not None else None


def _rev_yoy(db_path: str, sid: str) -> Tuple[Optional[float], str]:
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        row = con.execute(
            """
            SELECT yyyymm, yoy_pct, revenue FROM monthly_revenue
            WHERE stock_id=? AND revenue IS NOT NULL AND revenue>0
            ORDER BY yyyymm DESC LIMIT 1
            """,
            (sid,),
        ).fetchone()
        if not row:
            return None, ""
        yoy = float(row[1]) if row[1] is not None else None
        return yoy, str(row[0] or "")
    except Exception:
        return None, ""
    finally:
        con.close()


def _prev_open_day(desk: str) -> str:
    d = _ymd(desk)
    if len(d) != 8:
        return ""
    try:
        from datetime import datetime as _dt
        from trading_calendar import last_open_calendar_day_on_or_before

        prev = (_dt.strptime(d, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        return last_open_calendar_day_on_or_before(prev)
    except Exception:
        return ""


def _pe_fresh_ok(pe_date: str, desk: str, market: str) -> bool:
    """本益資料日必須貼 desk：同日；上市允許官方常晚一日（T−1 開市日）。

    上櫃／興櫃要求同日。過舊＝不准進真可買（查股有資料日落後標；漏斗硬閘對齊）。
    """
    pe_d, desk_d = _ymd(pe_date), _ymd(desk)
    if len(pe_d) != 8 or len(desk_d) != 8:
        return False
    if pe_d == desk_d:
        return True
    mkt = (market or "").upper()
    if mkt in ("TW", "TSE", "LISTED", ""):
        # 空 market 保守當上市口徑（BWIBBU 常 T−1）
        return pe_d == _prev_open_day(desk_d)
    return False


def _pe_row(db_path: str, sid: str) -> Optional[float]:
    """相容：回最新 pe 數值；缺日檢查請用 _pe_pack。"""
    pack = _pe_pack(db_path, sid)
    pe = pack.get("pe")
    return float(pe) if pe is not None else None


def _pe_pack(db_path: str, sid: str) -> Dict[str, Any]:
    empty = {"date": "", "pe": None, "pb": None, "source": ""}
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        cols = {
            str(r[1]).lower()
            for r in con.execute("PRAGMA table_info(daily_valuation)")
        }
        if "date" not in cols or "pe" not in cols:
            return empty
        select = ["date", "pe"]
        select.append("pb" if "pb" in cols else "NULL")
        select.append("source" if "source" in cols else "''")
        row = con.execute(
            f"SELECT {', '.join(select)} FROM daily_valuation "
            "WHERE stock_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not row:
            return empty
        return {
            "date": _ymd(row[0]),
            "pe": float(row[1]) if row[1] is not None else None,
            "pb": float(row[2]) if row[2] is not None else None,
            "source": str(row[3] or ""),
        }
    except Exception:
        return empty
    finally:
        con.close()


def _collect_signal_maps(
    db_path: str, desk: str
) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    """回傳 signals[sid]=set、names[sid]。不准呼叫 build_combo_screen（避免循環）。"""
    from pipeline_observe import _live_judge_pack, _streak_top_rows

    signals: Dict[str, Set[str]] = {}
    names: Dict[str, str] = {}

    def _ingest(sig: str, items: Sequence[Any]) -> None:
        for it in items or []:
            if isinstance(it, dict):
                sid = str(it.get("sid") or it.get("stock_id") or "").strip()
                nm = str(it.get("name") or it.get("stock_name") or "").strip()
            else:
                sid = str(it or "").strip()
                nm = ""
            if not sid:
                continue
            signals.setdefault(sid, set()).add(sig)
            if nm:
                names[sid] = nm

    # 勝率 roster
    try:
        from winrate_buypoint import latest_roster_as_of, load_winrate_roster, roster_marked

        latest = _ymd(latest_roster_as_of(db_path))
        use = desk if desk and roster_marked(db_path, desk) else latest
        rows = load_winrate_roster(db_path, use) if use else []
        _ingest(
            "winrate",
            [
                {"sid": str(r.get("stock_id") or ""), "name": str(r.get("stock_name") or "")}
                for r in rows
            ],
        )
        if not rows:
            _, items = _live_judge_pack(db_path, "winrate_buypoint", desk, limit=24)
            _ingest("winrate", items)
    except Exception:
        _, items = _live_judge_pack(db_path, "winrate_buypoint", desk, limit=24)
        _ingest("winrate", items)

    _, lz = _live_judge_pack(db_path, "leave_zero", desk, limit=24)
    _ingest("leave_zero", lz)
    _, ma = _live_judge_pack(db_path, "ma60_lower", desk, limit=24)
    if not ma and desk:
        try:
            from screen_sessions import load_session_results, screen_session_has_data

            if screen_session_has_data(db_path, desk):
                res = load_session_results(db_path, desk, "morning") or {}
                if not any(res.values()):
                    res = load_session_results(db_path, desk, "evening") or {}
                ma = [
                    {"sid": str(s), "name": ""}
                    for s in (res.get("ma60_lower") or [])
                    if str(s or "").strip()
                ]
        except Exception:
            pass
    _ingest("ma60_lower", ma)

    try:
        from undervalue_sync import load_picks

        picks = load_picks(db_path, desk) if desk else []
        stars = [
            {"sid": str(r.get("stock_id") or ""), "name": str(r.get("name") or "")}
            for r in picks
            if str(r.get("mark") or "") == "star"
        ]
        if stars:
            _ingest("undervalue_star", stars)
        else:
            _, items = _live_judge_pack(
                db_path, "undervalue", desk, limit=16, bucket_key="star"
            )
            _ingest("undervalue_star", items)
    except Exception:
        _, items = _live_judge_pack(
            db_path, "undervalue", desk, limit=16, bucket_key="star"
        )
        _ingest("undervalue_star", items)

    for kind, sig in (
        ("foreign", "streak_foreign"),
        ("trust", "streak_trust"),
        ("both", "streak_both"),
    ):
        _, items = _streak_top_rows(db_path, kind, as_of=desk, limit=8)
        if not items:
            _, items = _live_judge_pack(db_path, sig, desk, limit=8)
        _ingest(sig, items)

    # 還在零
    try:
        from screen_sessions import load_session_results, screen_session_has_data

        if desk and screen_session_has_data(db_path, desk):
            res = load_session_results(db_path, desk, "morning") or {}
            if not any(res.values()):
                res = load_session_results(db_path, desk, "evening") or {}
            _ingest(
                "golden_buy",
                [{"sid": str(s), "name": ""} for s in (res.get("golden_buy") or [])],
            )
    except Exception:
        pass

    # 洞燭點名
    try:
        from biaoke_field_scan import load_dongzhu_precursor

        prec = load_dongzhu_precursor(db_path) or {}
        for key in ("leaders", "seconds", "picks", "stocks"):
            _ingest("dongzhu", prec.get(key) or [])
    except Exception:
        pass

    return signals, names


def _hard_market_ok(meta: Dict[str, str]) -> Tuple[bool, str]:
    from universe import is_etf_asset, is_screen_equity

    sid = ""  # filled by caller via meta
    at = meta.get("asset_type") or ""
    name = meta.get("name") or ""
    mkt = (meta.get("market") or "").upper()
    # 興櫃不進真可買；觀察也可擋（復原路核心）
    if mkt in ("EM", "EG", "興櫃") or "興櫃" in (meta.get("industry") or ""):
        return False, "興櫃"
    # 用 asset／名稱判斷 ETF
    if is_etf_asset(asset_type=at, stock_id=sid, stock_name=name):
        return False, "ETF"
    if at and not is_screen_equity("", name, at):
        # KY／STOCK 才收
        if str(at).upper() not in ("STOCK", "KY"):
            return False, f"asset={at}"
    return True, ""


def _liquidity_ok(bars: Sequence[Dict[str, Any]]) -> Tuple[bool, str]:
    if not bars:
        return False, "無柱"
    last = bars[-1]
    turn = last.get("turnover_k")
    if turn is not None and float(turn) < DAY_TURNOVER_K_MIN:
        return False, "成交額低"
    if len(bars) >= 21:
        vs = [float(b.get("v") or 0) for b in bars[-21:-1]]
        avg = sum(vs) / max(1, len(vs))
        if avg > 0 and float(last.get("v") or 0) < avg * 0.5:
            return False, "量縮"
    return True, ""


def _structure_broke(bars: Sequence[Dict[str, Any]]) -> bool:
    """粗結構破底：收盤創近 60 根新低且跌破前低。"""
    if len(bars) < 25:
        return False
    closes = [float(b["c"]) for b in bars if b.get("c")]
    lows = [float(b["l"]) for b in bars if b.get("l")]
    if len(closes) < 25:
        return False
    c = closes[-1]
    prior_low = min(lows[-60:-1] or lows[:-1])
    return bool(prior_low > 0 and c < prior_low * 0.995)


def _soft_score(
    *,
    sid: str,
    sigs: Set[str],
    fine: str,
    industry: str,
    bars: Sequence[Dict[str, Any]],
    twii: Dict[str, Any],
    yoy: Optional[float],
    pe: Optional[float],
    eps: Optional[float],
) -> Tuple[float, List[str]]:
    score = 0.0
    notes: List[str] = []
    # S1 主題 OR
    blob = f"{fine} {industry}"
    theme = any(h in blob for h in _THEME_HINTS) or ("dongzhu" in sigs)
    if theme:
        score += 3.0
        notes.append("主題")
    else:
        score -= 0.5
    # S3 抗跌：近 5 日漲跌 vs 大盤（有 pct 才比）
    if len(bars) >= 6 and twii.get("c") and twii.get("date"):
        try:
            c0 = float(bars[-6]["c"])
            c1 = float(bars[-1]["c"])
            stock_ret = (c1 / c0 - 1.0) * 100.0 if c0 else 0.0
            # 粗：若個股跌幅小於 8% 在急殺週加分（無完整 TWII 窗時）
            if stock_ret > -8:
                score += 1.5
                notes.append("相對抗跌")
            elif stock_ret < -15:
                score -= 1.0
                notes.append("弱勢")
        except Exception:
            pass
    # S4 營運
    if yoy is not None:
        if yoy >= 0:
            score += 1.5
            notes.append("營收YoY+")
        elif yoy > -15:
            score += 0.3
        else:
            score -= 1.5
            notes.append("營收崩")
    # S5 估值
    if eps is not None and eps < 0:
        score -= 2.0
        notes.append("虧損")
    if pe is not None:
        if 0 < pe <= 18:
            score += 1.2
            notes.append("本益偏低")
        elif pe > 35:
            score -= 1.5
            notes.append("本益偏高")
    # S6 籌碼
    if "streak_both" in sigs:
        score += 1.5
        notes.append("雙買")
    elif "streak_foreign" in sigs or "streak_trust" in sigs:
        score += 0.8
        notes.append("連買")
    if "undervalue_star" in sigs:
        score += 1.0
        notes.append("低估★")
    # 買訊加分（不作唯一）
    if "winrate" in sigs:
        score += 2.0
    if "leave_zero" in sigs:
        score += 1.5
    if "ma60_lower" in sigs:
        score += 1.2
    return score, notes


def _dedupe_buy(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同細項最多 MAX_SAME_FINE；已按 score 降序。"""
    counts: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for r in rows:
        fine = str(r.get("fine") or "") or "_"
        if counts.get(fine, 0) >= MAX_SAME_FINE:
            continue
        counts[fine] = counts.get(fine, 0) + 1
        out.append(r)
        if len(out) >= MAX_BUY_OK:
            break
    return out


def run_recovery_funnel(
    db_path: str,
    *,
    as_of: Optional[str] = None,
    now=None,
    refresh_punish: bool = True,
) -> Dict[str, Any]:
    """跑完整漏斗並落檔。回傳話筒／排程共用 payload。"""
    ensure_recovery_tables(db_path)
    press = _taipei_now(now)
    desk = _ymd(as_of) or _resolve_desk(db_path)
    if refresh_punish:
        try:
            fetch_and_store_punish(db_path, now=press)
        except Exception:
            logger.exception("H7 punish refresh")

    regime, twii = _twii_regime(db_path, desk)
    punish = active_punish_ids(db_path, desk) if desk else set()
    uni = _universe_meta(db_path)
    fine_map = _fine_map(db_path)
    signals, names = _collect_signal_maps(db_path, desk)

    buy_rows: List[Dict[str, Any]] = []
    obs_rows: List[Dict[str, Any]] = []
    rejected = 0

    for sid, sigs in signals.items():
        meta = uni.get(sid) or {"name": names.get(sid, ""), "market": "", "asset_type": "", "industry": ""}
        name = names.get(sid) or meta.get("name") or ""
        fine = fine_map.get(sid) or ""
        industry = meta.get("industry") or ""

        # H2
        ok_m, why_m = _hard_market_ok({**meta, "name": name})
        # patch sid into etf check
        try:
            from universe import is_etf_asset

            if is_etf_asset(
                asset_type=meta.get("asset_type") or "",
                stock_id=sid,
                stock_name=name,
            ):
                ok_m, why_m = False, "ETF"
        except Exception:
            pass
        if not ok_m:
            rejected += 1
            continue

        # H7
        if sid in punish:
            rejected += 1
            continue

        bars = _recent_quotes(db_path, sid, desk, n=65)
        if not bars or _ymd(bars[-1].get("date")) != desk:
            # 無當日柱：軟降，仍可進觀察若有訊號（但真可買不要）
            q_ok = False
        else:
            q_ok = True

        liq_ok, liq_why = _liquidity_ok(bars) if bars else (False, "無柱")
        broke = _structure_broke(bars) if bars else False
        eps_pack = _eps_pack(db_path, sid)
        eps_ttm = eps_pack.get("eps_ttm")
        # 軟縮用：有近四季用近四季；否則不拿累計列冒充正 EPS（避免假保護）
        eps_for_soft = float(eps_ttm) if eps_ttm is not None else None
        yoy, rev_ym = _rev_yoy(db_path, sid)
        pe_pack = _pe_pack(db_path, sid)
        pe = pe_pack.get("pe")
        pe_date = str(pe_pack.get("date") or "")
        mkt = str(meta.get("market") or "").upper()

        # S8 新鮮度：月營收過舊（>45 天）降權在 score
        fresh_penalty = 0.0
        if rev_ym and len(str(rev_ym)) >= 6:
            try:
                ym = str(rev_ym).replace("-", "")[:6]
                # desk 年月
                desk_ym = desk[:6]
                # 粗比：yyyymm 差
                if ym < desk_ym:
                    # 允許上月；再更舊扣分
                    dy = int(desk_ym[:4]) - int(ym[:4])
                    dm = int(desk_ym[4:6]) - int(ym[4:6]) + dy * 12
                    if dm > 2:
                        fresh_penalty = -1.0
            except Exception:
                pass

        score, soft_notes = _soft_score(
            sid=sid,
            sigs=sigs,
            fine=fine,
            industry=industry,
            bars=bars,
            twii=twii,
            yoy=yoy,
            pe=pe if _pe_fresh_ok(pe_date, desk, mkt) else None,
            eps=eps_for_soft,
        )
        score += fresh_penalty
        if fresh_penalty:
            soft_notes.append("營收偏舊")

        labels: List[str] = []
        if "golden_buy" in sigs:
            labels.append("還在零")
        if str(meta.get("asset_type") or "").upper() == "KY" or "KY" in name:
            labels.append("KY")
        if "dongzhu" in sigs:
            labels.append("洞燭")

        entry = sigs & {"winrate", "leave_zero", "ma60_lower"}
        reasons: List[str] = []
        if not liq_ok:
            reasons.append(liq_why or "流動性")
        if broke:
            reasons.append("結構破底")
        if not q_ok:
            reasons.append("無當日柱")

        row = {
            "sid": sid,
            "name": name,
            "fine": fine or industry,
            "score": round(score, 2),
            "labels": labels,
            "soft": soft_notes,
            "signals": sorted(sigs),
            "entry": sorted(entry),
            "reasons": reasons,
            "pe": pe,
            "pe_date": pe_date,
            "eps": eps_for_soft,
            "eps_ttm": eps_ttm,
            "yoy": yoy,
        }

        # 真可買硬條件：買訊＋柱＋流動＋結構；估值必須是「貼 desk 的官方本益」
        can_buy = bool(entry) and q_ok and liq_ok and not broke
        if pe is None:
            can_buy = False
            reasons.append("本益缺")
        elif not _pe_fresh_ok(pe_date, desk, mkt):
            can_buy = False
            reasons.append("本益落後")
        elif pe <= 0:
            can_buy = False
            reasons.append("本益無效")
        elif pe > 40:
            can_buy = False
            reasons.append("本益過熱")
        # 近四季 EPS 有算到且 ≤0 → 擋（與證交所不公布本益同向）；缺窗不拿累計列放行
        if eps_ttm is not None and float(eps_ttm) <= 0:
            can_buy = False
            reasons.append("近四季EPS≤0")
        # 首日標註（有 leave_zero／winrate 當日）
        if "leave_zero" in entry or "winrate" in entry:
            labels.append("首日")

        if can_buy:
            buy_rows.append(row)
        else:
            # 觀察池：硬資格已過（非處置／非興櫃ETF），軟縮後仍留
            if "結構破底" in reasons and not entry:
                rejected += 1
                continue
            obs_rows.append(row)

    buy_rows.sort(key=lambda r: (-float(r["score"]), r["sid"]))
    obs_rows.sort(key=lambda r: (-float(r["score"]), r["sid"]))
    buy_rows = _dedupe_buy(buy_rows)
    # 觀察去掉已在真可買的
    buy_ids = {r["sid"] for r in buy_rows}
    obs_rows = [r for r in obs_rows if r["sid"] not in buy_ids][:MAX_OBSERVE]

    payload = {
        "as_of": desk,
        "ran_at": press.isoformat(),
        "regime": regime,
        "twii": twii,
        "n_buy": len(buy_rows),
        "n_observe": len(obs_rows),
        "rejected": rejected,
        "punish_n": len(punish),
        "buy_ok": buy_rows,
        "observe": obs_rows,
        "notes": "復原路漏斗｜硬閘＋軟縮｜不准總分榜｜買訊僅三種",
    }
    _save_run(db_path, payload)
    return payload


def _save_run(db_path: str, payload: Dict[str, Any]) -> None:
    desk = _ymd(payload.get("as_of"))
    if not desk:
        return
    ensure_recovery_tables(db_path)
    con = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        con.execute("DELETE FROM recovery_picks WHERE as_of=?", (desk,))
        for bucket, key in (("buy_ok", "buy_ok"), ("observe", "observe")):
            for r in payload.get(key) or []:
                con.execute(
                    """
                    INSERT OR REPLACE INTO recovery_picks
                    (as_of, stock_id, bucket, name, fine, score, labels_json, reasons_json, buy_signals_json)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        desk,
                        r["sid"],
                        bucket,
                        r.get("name") or "",
                        r.get("fine") or "",
                        float(r.get("score") or 0),
                        json.dumps(r.get("labels") or [], ensure_ascii=False),
                        json.dumps(
                            (r.get("reasons") or []) + (r.get("soft") or []),
                            ensure_ascii=False,
                        ),
                        json.dumps(r.get("entry") or r.get("signals") or [], ensure_ascii=False),
                    ),
                )
        con.execute(
            """
            INSERT OR REPLACE INTO recovery_runs
            (as_of, regime, ran_at, n_buy, n_observe, notes, payload_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                desk,
                str(payload.get("regime") or ""),
                str(payload.get("ran_at") or ""),
                int(payload.get("n_buy") or 0),
                int(payload.get("n_observe") or 0),
                str(payload.get("notes") or ""),
                json.dumps(payload, ensure_ascii=False)[:200000],
            ),
        )
        con.commit()
    finally:
        con.close()


def load_recovery_run(db_path: str, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    ensure_recovery_tables(db_path)
    desk = _ymd(as_of) or _resolve_desk(db_path)
    con = sqlite3.connect(str(db_path), timeout=15.0)
    try:
        row = None
        if desk:
            row = con.execute(
                "SELECT payload_json FROM recovery_runs WHERE as_of=?", (desk,)
            ).fetchone()
        if not row:
            row = con.execute(
                "SELECT payload_json FROM recovery_runs ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        if not row or not row[0]:
            return None
        return json.loads(row[0])
    except Exception:
        return None
    finally:
        con.close()


def format_recovery_funnel_html(payload: Dict[str, Any]) -> str:
    from html import escape
    from tg_layout import join_dashed, title_line

    desk = _zh(payload.get("as_of") or "")
    regime = escape(str(payload.get("regime") or "—"))
    tw = payload.get("twii") or {}
    tw_c = tw.get("c")
    tw_bit = ""
    if isinstance(tw_c, (int, float)):
        tw_bit = f"｜加權 {_zh(str(tw.get('date') or ''))} 收 {tw_c:,.0f}"

    def _fmt_rows(rows: Sequence[Dict[str, Any]], limit: int = 12) -> str:
        parts = []
        for r in list(rows)[:limit]:
            sid = escape(str(r.get("sid") or ""))
            name = escape(str(r.get("name") or ""))
            labs = "・".join(str(x) for x in (r.get("labels") or [])[:3])
            entry = "/".join(str(x) for x in (r.get("entry") or [])[:3])
            bit = f"{sid} {name}".strip()
            if entry:
                bit += f"〔{escape(entry)}〕"
            if labs:
                bit += f" {escape(labs)}"
            parts.append(bit)
        return "、".join(parts) if parts else "（空）"

    buy = list(payload.get("buy_ok") or [])
    obs = list(payload.get("observe") or [])
    blocks = [
        title_line("綜合篩選・復原路", desk, "漏斗"),
        f"regime={regime}{escape(tw_bit)}",
        f"真可買 n={len(buy)}｜復原觀察 n={len(obs)}｜處置擋 {int(payload.get('punish_n') or 0)}",
        "<b>真可買</b>（過硬閘＋三種買訊；可空）\n" + _fmt_rows(buy),
        "<b>復原觀察</b>（過資格、尚等買點／還在零）\n" + _fmt_rows(obs),
        "<i>硬閘：資格／流動性／破底／處置／真可買估值底。軟縮排序不杀光。不准總分榜。非即時 tick。</i>",
    ]
    return join_dashed(*blocks)


def run_recovery_job(
    db_path: str, *, skip_if_done: bool = True, now=None, tag: str = ""
) -> Dict[str, Any]:
    """排程入口：06:45／盤後融合後。"""
    desk = _resolve_desk(db_path)
    if not desk:
        return {"ok": False, "reason": "no-desk"}
    ensure_recovery_tables(db_path)
    if skip_if_done:
        con = sqlite3.connect(str(db_path), timeout=15.0)
        try:
            row = con.execute(
                "SELECT ran_at, notes FROM recovery_runs WHERE as_of=?", (desk,)
            ).fetchone()
        finally:
            con.close()
        if row and tag and tag in str(row[1] or ""):
            return {"ok": True, "skipped": True, "as_of": desk}
    payload = run_recovery_funnel(db_path, as_of=desk, now=now, refresh_punish=True)
    # 蓋 tag 方便 skip
    if tag:
        payload["notes"] = f"{payload.get('notes') or ''}|{tag}".strip("|")
        _save_run(db_path, payload)
    return {"ok": True, "as_of": desk, "n_buy": payload.get("n_buy"), "n_observe": payload.get("n_observe")}
